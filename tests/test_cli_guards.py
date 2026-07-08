"""Tests for cli.py's fail-fast input guards."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from commoner_analyse.cli import analyse_ministry_cmd


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class AnalyseMinistryCmdGuardTests(unittest.TestCase):

    def test_missing_discourse_file_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa", "ministry": "FINANCE"},
            ])
            args = argparse.Namespace(out=str(out), topic=None)
            with self.assertRaises(SystemExit) as ctx:
                analyse_ministry_cmd(args)
            self.assertIn("analyse-discourse", str(ctx.exception))

    def test_missing_manifest_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            args = argparse.Namespace(out=str(out), topic=None)
            with self.assertRaises(SystemExit) as ctx:
                analyse_ministry_cmd(args)
            self.assertIn("crawl", str(ctx.exception))

    def test_runs_when_both_inputs_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa", "ministry": "FINANCE"},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "ACCEPTED", "channel": "qa"},
            ])
            args = argparse.Namespace(out=str(out), topic=None)
            analyse_ministry_cmd(args)  # must not raise
            self.assertTrue((out / "ministry_summary_qa.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
