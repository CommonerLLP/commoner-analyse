"""Tests for runlog: provenance log that ties records to apparatus.

Coverage rationale: this module is the load-bearing piece for the
"categories travel with records" property (Suchman / Power). If
`topic_hash` is unstable, or secrets leak through `classifier_config`,
or `_runs.jsonl` is malformed, that property quietly fails. These
tests pin those down.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sansad_semantic_crawler.runlog import RunLog, _redact, topic_hash


class RedactTests(unittest.TestCase):
    def test_redacts_known_secret_keys(self):
        out = _redact({"api_key": "sk-real", "model": "x", "token": "t"})
        self.assertEqual(out["api_key"], "<redacted>")
        self.assertEqual(out["token"], "<redacted>")
        self.assertEqual(out["model"], "x")

    def test_redacts_recursively_through_nested_structures(self):
        config = {
            "members": [
                {"mode": "llm", "api_key": "sk-leaky"},
                {"mode": "regex"},
            ],
            "outer": {"Authorization": "Bearer x"},  # case-insensitive match
        }
        out = _redact(config)
        self.assertEqual(out["members"][0]["api_key"], "<redacted>")
        self.assertEqual(out["members"][1], {"mode": "regex"})
        self.assertEqual(out["outer"]["Authorization"], "<redacted>")


class TopicHashTests(unittest.TestCase):
    def test_same_bytes_yield_same_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.json"
            p.write_text('{"name":"x"}', encoding="utf-8")
            self.assertEqual(topic_hash(p), topic_hash(p))

    def test_whitespace_only_edits_change_the_hash(self):
        """Power: every variation of the apparatus is a different apparatus."""
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            a.write_text('{"name":"x"}', encoding="utf-8")
            b.write_text('{"name": "x"}', encoding="utf-8")  # one extra space
            self.assertNotEqual(topic_hash(a), topic_hash(b))

    def test_hash_format_is_prefixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.json"
            p.write_text("x", encoding="utf-8")
            self.assertTrue(topic_hash(p).startswith("sha256:"))


class RunLogTests(unittest.TestCase):
    def _profile(self, tmp: str) -> Path:
        path = Path(tmp) / "topic.json"
        path.write_text('{"name":"demo"}', encoding="utf-8")
        return path

    def test_start_finish_appends_one_record_with_expected_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = RunLog(Path(tmp))
            run_id = log.start(
                kind="committee_report",
                scope={"house": "ls"},
                topic_name="demo",
                topic_path=self._profile(tmp),
                classifier_mode="regex",
                classifier_config={},
            )
            log.finish(added=3)
            lines = (Path(tmp) / "_runs.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["run_id"], run_id)
        self.assertEqual(rec["kind"], "committee_report")
        self.assertEqual(rec["added"], 3)
        self.assertEqual(rec["scope"]["house"], "ls")
        self.assertTrue(rec["topic_hash"].startswith("sha256:"))
        self.assertEqual(rec["classifier_mode"], "regex")
        self.assertIn("started_at", rec)
        self.assertIn("ended_at", rec)
        self.assertIn("elapsed_ms", rec)
        self.assertEqual(rec["errors"], [])

    def test_two_runs_append_two_lines_with_distinct_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = RunLog(Path(tmp))
            ids = []
            for _ in range(2):
                ids.append(
                    log.start(
                        kind="committee_report",
                        scope={},
                        topic_name="demo",
                        topic_path=self._profile(tmp),
                        classifier_mode="regex",
                        classifier_config={},
                    )
                )
                log.finish(added=0)
            lines = (Path(tmp) / "_runs.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_classifier_config_is_redacted_in_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = RunLog(Path(tmp))
            log.start(
                kind="committee_report",
                scope={},
                topic_name="demo",
                topic_path=self._profile(tmp),
                classifier_mode="llm",
                classifier_config={"endpoint": "http://x", "api_key": "sk-leaky"},
            )
            log.finish(added=0)
            rec = json.loads((Path(tmp) / "_runs.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["classifier_config_redacted"]["api_key"], "<redacted>")
        self.assertEqual(rec["classifier_config_redacted"]["endpoint"], "http://x")

    def test_record_error_appears_in_finished_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = RunLog(Path(tmp))
            log.start(
                kind="committee_report",
                scope={},
                topic_name="demo",
                topic_path=self._profile(tmp),
                classifier_mode="regex",
                classifier_config={},
            )
            log.record_error(where="ls/finance", exc=ValueError("bad data"))
            log.finish(added=0)
            rec = json.loads((Path(tmp) / "_runs.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["errors"], [{"where": "ls/finance", "error": "ValueError: bad data"}])

    def test_finish_without_start_is_a_noop(self):
        """Defensive: ensure stray finish() does not crash or write."""
        with tempfile.TemporaryDirectory() as tmp:
            log = RunLog(Path(tmp))
            log.finish(added=99)  # no start
            self.assertFalse((Path(tmp) / "_runs.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
