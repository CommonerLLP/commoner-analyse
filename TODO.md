# TODO — commoner-analyse

## Current

- [ ] Fix FDA: System Settings → Privacy & Security → Full Disk Access → add Claude Code binary
- [ ] Wait for partial-recall corpus filter fix before using `corpus="folder"` in MCP queries
- [ ] Import `notes/neva-bihar-citations.ris` into Zotero (File → Import)
- [ ] Verify Bihar first session date (22 July 1937) + Ram Dayalu Singh as Speaker — primary source before op-ed publication
- [ ] Search sansad.in written answers for NeVA year-wise expenditure by state

### Codex findings — pre-existing, unaddressed by this session's PRs (re-verified 2026-07-06)
- [ ] `graph.py:59,69,132` — `_load_classifications`/`_load_atr_linkages` use `INSERT OR REPLACE`
      with no unique constraint and no delete-before-reload, so rebuilds after a changed corpus
      insert duplicate rows instead of replacing them (Codex PR#34, P1)
- [ ] `dossier.py:_resolve_display_identity` — counts asker name/entity_id fields from *all*
      matched rows, not just the row for the matched asker, when a record has multiple askers
      (Codex PR#30, P1)
- [ ] `cli.py:268 analyse_ministry_cmd` — only checks `manifest.jsonl` exists, not
      `analysis_discourse.jsonl`; running `analyse-ministry` before `analyse-discourse` silently
      produces an all-UNCLASSIFIED summary instead of failing fast (Codex PR#25, P2)
- [ ] `aggregations.py` (qa branch, `write_ministry_summary`) — `records_total` increments once
      per manifest record but `label_distribution` increments once per discourse row; mismatched
      units when a key has more than one discourse row (Codex PR#25, P1)
- [ ] `discourse.py:526 _VOICE_ACTIVE_RE` — bare auxiliaries (`has|have|had|will|shall|does|do`)
      over-match passive constructions with a named agent as active; ministry/department span
      match is unbounded-greedy (Codex PR#43, P2 x2) — only became re-checkable this session once
      the voice/agency feature merged in via the branch reconciliation
- [ ] `CONTRIBUTING.md` says "requires Python 3.11 or 3.12 or 3.13"; `pyproject.toml` says
      `requires-python = ">=3.10"` — still mismatched (Codex PR#15, P2)

## Future

### NeVA / state assemblies
- [ ] Assam crawl — 14 sessions, only other state with question data — run via
      `commoner-probe state-assembly` (acquisition delegated there as of 2026-07-06)
- [ ] Semantic/intelligence layer: OCR pipeline (two-path Shruti/Shree), translation, embeddings, answer extraction
- [ ] Test H1-H6 hypotheses against PDF answers (`notes/gujarat-assembly15-hypotheses.md`)
- [ ] Expand to UP (`upvs.neva.gov.in`) — largest state, highest volume — via `commoner-probe state-assembly`
- [ ] Expand to Haryana (`hrla.neva.gov.in`) — via `commoner-probe state-assembly`
- [ ] Run `commoner-probe state-assembly-probe --include-councils` across all 37 portals for a
      real coverage report (supersedes the old "move recon script to neva_probe.py" plan — that
      coverage-probe capability now ships natively in commoner-probe, no local script needed)
- [ ] File RTI: MoPA — year-wise funds released per state under NeVA CSS 2019-26
- [ ] File RTI: Bihar Vidhan Sabha — status of pre-2022 paper records, digitization plan
- [ ] File RTI: NIC — status of vidhansabha.bih.nic.in data (migrating or abandoned?)
- [ ] Check Wayback Machine: vidhansabha.bih.nic.in snapshots 2010–2019
- [ ] Op-ed: finish verify checklist then share (notes/op-ed-draft-bihar-hollowtech.md)
- [ ] Publish `notes/neva-api-public-draft.md` once ≥10 states verified

### Central parliament (pre-existing)
- [ ] regex_v2 coverage audit (reference corpora, measure delta from ~28%)
- [ ] Entity resolver fix: Article 101 house+term disambiguation (`resolver.py`)
- [ ] CPR Accountability Initiative adapter (JS-rendered, RSS route preferred)
- [ ] TECHDEBT: duplicate HTTP layer (discourse.py + dossier.py → shared helper)
- [ ] TECHDEBT: topic_hash propagation into analysis_discourse.jsonl
- [ ] TECHDEBT: Channel enum

## Archive

- [x] Renamed sansad-semantic-crawler → commoner-analyse; released v2.1.0 (2026-07-06)
- [x] NeVA acquisition delegated to commoner-probe>=0.7.0's native `state-assembly`;
      local fallback crawler removed (2026-07-06)
- [x] Reconciled duplicated commoner-probe-delegation refactor with origin/main;
      fixed pre-existing RS-filter test bug (2026-07-06)
- [x] `export` now merges `discourseSummary`/`ministryDiscourse`; added
      `export-glossary` command; fixed evasion-rate undercounting for 4
      Instrumented Discourse Tier v2 labels (2026-07-06)
- [x] Filed REQ-0009 (theright2read) / REQ-0010 (zero-hour) for downstream
      consumption of the new export fields (2026-07-06)
- [x] Downstream pins updated: theright2read, academiaindia, zero-hour docs (2026-07-06)
- [x] Gujarat assembly 15 full crawl started (all 8 sessions, with PDFs) (2026-05-21)
- [x] Analytical hypotheses written + typeset as PDF (`notes/gujarat-assembly15-hypotheses.pdf`) (2026-05-21)
- [x] SESSION_LOG.md + WORKING.md maintained (2026-05-21)
- [x] Two mistakes logged to `_org/mistakes.md` (2026-05-21)
- [x] v1.1.0 released — changelog aligned, README updated (2026-05-20)
- [x] NeVA recon: reverse-engineered full Gujarat API surface (2026-05-20)
- [x] NeVA scraper written: neva.py + neva-crawl CLI command (2026-05-21)
- [x] Gujarat assembly 15 smoke test: 2,122 Q + 145 papers + 181 members (2026-05-21)
- [x] v1.0.0 released: ATR linkage, constitutional audit, mp/ministry dossier (2026-05-13)
- [x] CI workflow added (Python 3.10-3.13 matrix) (2026-05-13)
- [x] Security hardening PRs #19, #21 (2026-05-10)
- [x] mp-dossier + ministry-dossier feature v0.6.6 (2026-05-09)
- [ ] OCR pipeline for Session 8 answers (Tesseract 5.5.2 + guj)
- [ ] Analysis: Test H1-H7 against extracted Session 8 text
- [ ] Re-index partial-recall (awaiting corpus="folder" filter fix)
- [ ] Verify NeVA uniformity on Haryana (hrla.neva.gov.in)
- [ ] Verify NeVA uniformity on Tamil Nadu (tnla.neva.gov.in)
- [ ] Comparison: Map "Ghetto" ministries in TN vs GJ (Revenue vs Social Justice)
