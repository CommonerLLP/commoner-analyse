"""Standing-committee report crawler.

Mirrors `sansad.py` (questions) but for parliamentary standing-committee
reports. One record per report (granularity decision: see notes/RELEASE.md
when v0.3.0 ships). Reuses existing topic profiles unchanged — `tag_rules`
and classifiers operate on the report subject. The `lok_sabha_ministries`
and `rajya_sabha_ministry_likes` profile fields are unused here.

Endpoints (verified 2026-05-08):
    LS: GET https://sansad.in/api_ls/committee/lsRSAllReports
    RS: GET https://sansad.in/api_rs/committee/committee-reports

Both return ``{"records": [...], "_metadata": {"totalPages": N, ...}}``.
LS field names use PascalCase / mixedCase; RS uses camelCase. Report
subjects (English) live in `SubjectOfTheReport` (LS) and
`subjectOfTheReport` (RS). PDFs are absolute URLs on `sansad.in/getFile/`.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlencode

from .http_client import make_session
from .runlog import RunLog
from .sansad import date_in_range, now
from .topics import TopicProfile

LS_REPORTS_API = "https://sansad.in/api_ls/committee/lsRSAllReports"
RS_REPORTS_API = "https://sansad.in/api_rs/committee/committee-reports"
DEFAULT_LOK_SABHA = 18

LS_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 sansad-semantic-crawler/0.1",
}
RS_HEADERS = {**LS_HEADERS, "Referer": "https://sansad.in/rs/committees"}

# slug -> (display name, sansad committeeCode). LS-side Department-Related
# Standing Committees (DRSCs). Display names canonical here — the API's
# `CommitteeName` arrives whitespace-padded.
LS_COMMITTEES: dict[str, tuple[str, int]] = {
    "agriculture": ("Agriculture, Animal Husbandry and Food Processing", 5),
    "chemicals": ("Chemicals and Fertilizers", 45),
    "coal": ("Coal, Mines and Steel", 46),
    "communications": ("Communications and Information Technology", 18),
    "consumer_affairs": ("Consumer Affairs, Food and Public Distribution", 13),
    "defence": ("Defence", 7),
    "energy": ("Energy", 9),
    "external_affairs": ("External Affairs", 11),
    "finance": ("Finance", 12),
    "housing": ("Housing and Urban Affairs", 41),
    "labour": ("Labour, Textiles and Skill Development", 19),
    "petroleum": ("Petroleum and Natural Gas", 23),
    "railways": ("Railways", 28),
    "rural_development": ("Rural Development and Panchayati Raj", 32),
    "social_justice": ("Social Justice and Empowerment", 47),
    "water_resources": ("Water Resources", 44),
}

# slug -> (display name, mstCommId). RS-side DRSCs. The API's
# `committeeName` is null on every record — display name comes from here.
RS_COMMITTEES: dict[str, tuple[str, int]] = {
    "commerce": ("Commerce", 12),
    "education": ("Education, Women, Children, Youth and Sports", 16),
    "health": ("Health and Family Welfare", 14),
    "home_affairs": ("Home Affairs", 15),
    "industry": ("Industry", 17),
    "personnel": ("Personnel, Public Grievances, Law and Justice", 18),
    "science": ("Science and Technology, Environment, Forests and Climate Change", 19),
    "transport": ("Transport, Tourism and Culture", 20),
}


def parse_ls_date(value: str | None) -> str:
    """LS dates look like '17-Mar-2026'. Return ISO `YYYY-MM-DD` or ''."""
    if not value:
        return ""
    try:
        return datetime.strptime(value.strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return value.strip()[:10]


def parse_rs_date(value: str | None) -> str:
    """RS dates look like '18/03/2026'. Return ISO `YYYY-MM-DD` or ''."""
    if not value:
        return ""
    try:
        return datetime.strptime(value.strip()[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return value.strip()[:10]


# Action-Taken Reports (ATRs) are the executive's response to a committee's
# recommendations — distinct genre from original committee reports, with
# different political weight (Hull, *Documents and Bureaucracy*: form is data).
# Detected from title; the API does not expose this distinction structurally.
_ATR_RE = re.compile(r"\baction[\s\-]+taken\b", re.IGNORECASE)


def _report_type(title: str | None) -> str:
    """'action_taken' if the title marks an ATR, else 'original'."""
    return "action_taken" if title and _ATR_RE.search(title) else "original"


def _ls_presented_via(raw: dict) -> str:
    """Categorise where the report has been laid, from LS API fields.

    A report Presented to the Speaker but not yet laid in either house is at
    a different lifecycle stage than one that has reached both houses. The
    distinction is a political fact that the date fields encode but never
    surface — make it queryable.
    """
    in_ls = bool((raw.get("PresentedInLS") or "").strip())
    in_rs = bool((raw.get("LaidInRS") or "").strip())
    to_speaker = bool((raw.get("PresentedToSpeaker") or "").strip())
    if in_ls and in_rs:
        return "both_houses"
    if in_ls:
        return "ls_only"
    if in_rs:
        return "rs_only"
    if to_speaker:
        return "speaker_only"
    return "none"


def report_key(house: str, slug: str, report_no: object, ls_no: int | None = None) -> str:
    """Stable composite key for dedup across re-runs.

    LS keys include lokSabha number — the same `report_no` recurs across LS
    terms. RS reports are numbered continuously across the upper house's
    history; no term suffix needed.
    """
    h = "LS" if house == "ls" else "RS"
    n = str(report_no or "X").strip()
    suffix = f"|{ls_no}" if ls_no is not None and house == "ls" else ""
    return f"{h}|{slug}|{n}{suffix}"


class CommitteeCrawler:
    """Crawls standing-committee reports. Sibling of `SansadCrawler`.

    NOTE: log/append/load_seen/write_pdf are duplicated from `SansadCrawler`.
    Factor into a shared base when a third crawler module appears.
    """

    def __init__(
        self,
        topic: TopicProfile,
        out_dir: Path,
        *,
        sleep: float = 0.25,
        lok_sabha_no: int = DEFAULT_LOK_SABHA,
        topic_path: Path | str | None = None,
        classifier_mode: str = "regex",
    ) -> None:
        self.topic = topic
        self.out_dir = out_dir
        self.pdf_dir = out_dir / "pdfs"
        self.manifest = out_dir / "manifest.jsonl"
        self.log_path = out_dir / "crawl.log"
        self.sleep = sleep
        self.lok_sabha_no = lok_sabha_no
        self.session = make_session()
        # `topic_path` and `classifier_mode` are recorded by RunLog so that
        # records can be linked back to the categorical apparatus that
        # produced them. Optional to avoid breaking tests that build a
        # `TopicProfile` programmatically.
        self.topic_path = topic_path
        self.classifier_mode = classifier_mode
        self.runlog = RunLog(out_dir)

    # ---- shared I/O (duplicated from SansadCrawler; factor on third caller) ----

    def log(self, msg: str) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        line = f"[{now()}] {msg}"
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_seen(self) -> set[str]:
        import json

        seen: set[str] = set()
        if not self.manifest.exists():
            return seen
        with self.manifest.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("key"):
                    seen.add(rec["key"])
        return seen

    def append(self, rec: dict) -> None:
        import json

        self.out_dir.mkdir(parents=True, exist_ok=True)
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def write_pdf(self, url: str, path: Path, headers: dict) -> bool:
        if path.exists() and path.stat().st_size > 1000:
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        r = self.session.get(url, headers=headers, timeout=120, stream=True)
        if r.status_code != 200:
            return False
        with path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=16384):
                f.write(chunk)
        return path.exists() and path.stat().st_size > 1000

    # ---- LS ----

    def ls_page(self, code: int, page: int, size: int = 200) -> dict:
        params = {
            "house": "L",
            "committeeCode": code,
            "lsNo": self.lok_sabha_no,
            "page": page,
            "size": size,
            "sortOn": "reportNo",
            "sortBy": "desc",
        }
        url = f"{LS_REPORTS_API}?{urlencode(params)}"
        r = self.session.get(url, headers=LS_HEADERS, timeout=45)
        r.raise_for_status()
        return r.json()

    def ls_all(self, code: int) -> Iterator[dict]:
        page = 1
        while True:
            data = self.ls_page(code, page)
            records = data.get("records") or []
            if not records:
                return
            yield from records
            meta = data.get("_metadata") or {}
            total_pages = int(meta.get("totalPages") or 0)
            if page >= total_pages:
                return
            page += 1
            time.sleep(self.sleep)

    def crawl_ls(
        self,
        seen: set[str],
        *,
        committees: list[str],
        from_date: str | None,
        to_date: str | None,
        max_records: int | None,
        download: bool,
    ) -> int:
        run_id = self.runlog.start(
            kind="committee_report",
            scope={
                "house": "ls",
                "committees": list(committees),
                "lok_sabha_no": self.lok_sabha_no,
                "from_date": from_date,
                "to_date": to_date,
                "max_records": max_records,
                "download": download,
            },
            topic_name=self.topic.name,
            topic_path=self.topic_path,
            classifier_mode=self.classifier_mode,
            classifier_config=self.topic.classifier_config,
        )
        added = 0
        for slug in committees:
            display, code = LS_COMMITTEES[slug]
            self.log(f"LS committee={slug} code={code} ls={self.lok_sabha_no} run={run_id[:8]}")
            try:
                for raw in self.ls_all(code):
                    report_no = raw.get("reportNo")
                    # `dateOfPresentation` is frequently null; fall back to the
                    # presentation/laid/speaker fields actually populated.
                    date = (
                        parse_ls_date(raw.get("PresentedInLS"))
                        or parse_ls_date(raw.get("LaidInRS"))
                        or parse_ls_date(raw.get("PresentedToSpeaker"))
                        or parse_ls_date(raw.get("dateOfPresentation"))
                    )
                    key = report_key("ls", slug, report_no, self.lok_sabha_no)
                    if key in seen or not date_in_range(date, from_date, to_date):
                        continue
                    title = (raw.get("SubjectOfTheReport") or "").strip()
                    semantic = self.topic.classify(title)
                    rec = {
                        "key": key,
                        "run_id": run_id,
                        "house": "Lok Sabha",
                        "kind": "committee_report",
                        "report_type": _report_type(title),
                        "presented_via": _ls_presented_via(raw),
                        "committee_slug": slug,
                        "committee_name": display,
                        "report_no": report_no,
                        "loksabha_no": raw.get("Loksabha") or self.lok_sabha_no,
                        "title": title,
                        "title_hindi": raw.get("SubjectOfTheReportH"),
                        "language_classified": ["en"],  # Hindi title stored, not classified.
                        "date": date,
                        "date_presented_ls": parse_ls_date(raw.get("PresentedInLS")),
                        "date_laid_rs": parse_ls_date(raw.get("LaidInRS")),
                        "date_presented_speaker": parse_ls_date(raw.get("PresentedToSpeaker")),
                        "date_adoption": parse_ls_date(raw.get("dateOfAdoption")),
                        "pdf_url": raw.get("url"),
                        "pdf_url_hindi": raw.get("urlH"),
                        "source": "sansad.in/api_ls/committee",
                        "crawled_at": now(),
                        **semantic,
                    }
                    if download and rec.get("pdf_url"):
                        fname = f"{slug}_{self.lok_sabha_no}_{report_no}.pdf"
                        pdf_path = self.pdf_dir / "ls" / fname
                        if self.write_pdf(rec["pdf_url"], pdf_path, LS_HEADERS):
                            rec["pdf_path"] = str(pdf_path.relative_to(self.out_dir))
                    self.append(rec)
                    seen.add(key)
                    added += 1
                    if max_records is not None and added >= max_records:
                        self.runlog.finish(added=added)
                        return added
                    time.sleep(self.sleep)
            except Exception as exc:  # noqa: BLE001
                self.log(f"LS failed committee={slug}: {exc}")
                self.runlog.record_error(where=f"ls/{slug}", exc=exc)
        self.runlog.finish(added=added)
        return added

    # ---- RS ----

    def rs_page(self, mst_comm_id: int, page: int, size: int = 200) -> dict:
        params = {
            "mstCommId": mst_comm_id,
            "departmentId": "",
            "presentationYear": "",
            "search": "",
            "page": page,
            "size": size,
            "sortOn": "reportNo",
            "sortBy": "desc",
            "locale": "en",
        }
        url = f"{RS_REPORTS_API}?{urlencode(params)}"
        r = self.session.get(url, headers=RS_HEADERS, timeout=45)
        r.raise_for_status()
        return r.json()

    def rs_all(self, mst_comm_id: int) -> Iterator[dict]:
        page = 1
        while True:
            data = self.rs_page(mst_comm_id, page)
            records = data.get("records") or []
            if not records:
                return
            yield from records
            meta = data.get("_metadata") or {}
            total_pages = int(meta.get("totalPages") or 0)
            if page >= total_pages:
                return
            page += 1
            time.sleep(self.sleep)

    def crawl_rs(
        self,
        seen: set[str],
        *,
        committees: list[str],
        from_date: str | None,
        to_date: str | None,
        max_records: int | None,
        download: bool,
    ) -> int:
        run_id = self.runlog.start(
            kind="committee_report",
            scope={
                "house": "rs",
                "committees": list(committees),
                "from_date": from_date,
                "to_date": to_date,
                "max_records": max_records,
                "download": download,
            },
            topic_name=self.topic.name,
            topic_path=self.topic_path,
            classifier_mode=self.classifier_mode,
            classifier_config=self.topic.classifier_config,
        )
        added = 0
        for slug in committees:
            display, mst_id = RS_COMMITTEES[slug]
            self.log(f"RS committee={slug} mstCommId={mst_id}")
            try:
                for raw in self.rs_all(mst_id):
                    report_no = raw.get("reportNo")
                    date = (
                        parse_rs_date(raw.get("dateOfPresentation"))
                        or parse_rs_date(raw.get("dateOfAdoption"))
                    )
                    key = report_key("rs", slug, report_no)
                    if key in seen or not date_in_range(date, from_date, to_date):
                        continue
                    title = (raw.get("subjectOfTheReport") or "").strip()
                    semantic = self.topic.classify(title)
                    # `presented_via`: RS API only confirms RS-side
                    # presentation. LS-side laying, when present, is not
                    # exposed by this endpoint; do not infer it.
                    presented_via = "rs_only" if parse_rs_date(raw.get("dateOfPresentation")) else "none"
                    rec = {
                        "key": key,
                        "run_id": run_id,
                        "house": "Rajya Sabha",
                        "kind": "committee_report",
                        "report_type": _report_type(title),
                        "presented_via": presented_via,
                        "committee_slug": slug,
                        "committee_name": display,
                        "report_no": report_no,
                        "title": title,
                        "title_hindi": raw.get("subjectOfTheReportHindi"),
                        "language_classified": ["en"],  # Hindi title stored, not classified.
                        "date": date,
                        "date_presentation": parse_rs_date(raw.get("dateOfPresentation")),
                        "date_adoption": parse_rs_date(raw.get("dateOfAdoption")),
                        "pdf_url": raw.get("url"),
                        "pdf_url_hindi": raw.get("urlHindi"),
                        "source": "sansad.in/api_rs/committee",
                        "crawled_at": now(),
                        **semantic,
                    }
                    if download and rec.get("pdf_url"):
                        fname = f"{slug}_{report_no}.pdf"
                        pdf_path = self.pdf_dir / "rs" / fname
                        if self.write_pdf(rec["pdf_url"], pdf_path, RS_HEADERS):
                            rec["pdf_path"] = str(pdf_path.relative_to(self.out_dir))
                    self.append(rec)
                    seen.add(key)
                    added += 1
                    if max_records is not None and added >= max_records:
                        self.runlog.finish(added=added)
                        return added
                    time.sleep(self.sleep)
            except Exception as exc:  # noqa: BLE001
                self.log(f"RS failed committee={slug}: {exc}")
                self.runlog.record_error(where=f"rs/{slug}", exc=exc)
        self.runlog.finish(added=added)
        return added


def resolve_committees(house: str, requested: Iterable[str] | None) -> list[str]:
    """Validate and order committee slugs for `house`. None = all."""
    catalog = LS_COMMITTEES if house == "ls" else RS_COMMITTEES
    if not requested:
        return sorted(catalog)
    unknown = [s for s in requested if s not in catalog]
    if unknown:
        raise ValueError(f"unknown {house.upper()} committee slug(s): {unknown}")
    return list(requested)
