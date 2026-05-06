# Sansad Semantic Crawler

A self-contained, config-driven crawler for Indian Parliament questions —
Lok Sabha and Rajya Sabha — across arbitrary topics. The package knows
the Lok Sabha DSpace API (`elibrary.sansad.in`) and the Rajya Sabha
question API (`rsdoc.nic.in`); the *topic logic* — what to search for,
what to tag, what to keep — lives in JSON profiles, so other projects
can add or extend subjects without editing crawler code.

The package was extracted from
[whoseuniversity.org](https://whoseuniversity.org/)'s parliamentary
research pipeline. It is shared as a public good for civic-tech and
public-interest research; commercial use is not permitted (see
[Licence](#licence) below).

## What it does

- Crawls Lok Sabha questions from `elibrary.sansad.in`.
- Crawls Rajya Sabha questions from `rsdoc.nic.in`.
- Normalises both houses into one JSONL manifest with a stable composite
  key (`LS|U|178|2024-11-25`) so re-running the crawler resumes
  cleanly from where it left off.
- Optionally downloads each answer's PDF.
- Extracts text from PDFs with `pdftotext -layout` (preferred for
  layout-heavy parliamentary tables), falling back to `pdfminer.six`
  when `pdftotext` is unavailable.
- Tags every record against the topic profile's regex rules and emits a
  per-rule match count + score.
- Exports a reusable summary as JSON or as a browser-ready
  `window.<NAME>` JS file for static sites.

## Install

```bash
pip install sansad-semantic-crawler

# Optional extras:
pip install "sansad-semantic-crawler[http]"   # use `requests` instead of stdlib `urllib`
pip install "sansad-semantic-crawler[pdf]"    # pdfminer.six fallback
```

There are zero required third-party dependencies. The crawler runs on a
clean Python 3.10+ install and falls back to `urllib` for HTTP and to
`pdftotext` (system binary) for PDF extraction.

## Quick start

```bash
# Dry smoke crawl: one search bucket, five records, no PDFs.
python -m sansad_semantic_crawler crawl \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --max-buckets 1 \
  --max-records 5 \
  --no-download

# Download a tiny sample.
python -m sansad_semantic_crawler crawl \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --house ls \
  --max-buckets 1 \
  --max-records 1

# Parse PDFs / text and export both analysis + summary JSON.
python -m sansad_semantic_crawler parse  --topic examples/topics/libraries.json --out data/libraries
python -m sansad_semantic_crawler export --topic examples/topics/libraries.json --out data/libraries --format json

# Browser-ready JS export for static sites.
python -m sansad_semantic_crawler export \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --format js \
  --js-global PARLIAMENT_LIBRARY_DATA \
  --export-path data/libraries/parliament_libraries.js
```

After install, the same commands are also available via the
`sansad-crawl` console script.

## Topic profiles

Profiles are plain JSON files. A minimal profile:

```json
{
  "name": "libraries",
  "description": "Public and institutional library questions",
  "search_groups": {
    "public_library": ["public library", "district library"],
    "digital":        ["digital library", "National Digital Library"]
  },
  "lok_sabha_ministries":      ["CULTURE", "EDUCATION"],
  "rajya_sabha_ministry_likes": ["CULTURE", "EDUCATION"],
  "tag_rules": [
    {"tag": "public_library",  "label": "Public libraries",
     "patterns": ["public\\s+librar", "district\\s+librar"]},
    {"tag": "digital_library", "label": "Digital libraries",
     "patterns": ["digital\\s+librar", "National\\s+Digital\\s+Library"]}
  ],
  "fallback_tag": "topic_match"
}
```

`search_groups` controls what the APIs are queried for.
`lok_sabha_ministries` / `rajya_sabha_ministry_likes` add ministry
filters on each house's API.
`tag_rules` controls what is kept, labelled, scored, and exported.
A `weight` field on a rule scales its contribution to the per-record
score.

This repository ships **one example profile** —
[`examples/topics/libraries.json`](examples/topics/libraries.json) —
which is the live profile behind
[freelibraries4all](https://freelibraries4all.org). Profiles for
projects that have a privacy or research-strategy reason to keep their
analytical lens private (e.g. higher-education vacancy research)
typically live in the host project's own repository, gitignored or
otherwise not redistributed; the crawler only needs the path on disk.

## Output layout

```text
data/<topic>/
  manifest.jsonl       normalised crawl records (one per question)
  analysis.jsonl       parsed + scored records (after `parse`)
  summary.json         aggregate export (after `export`)
  crawl.log
  parse.log
  pdfs/
    ls/*.pdf
    rs/*.pdf
  text/*.txt           extracted PDF text, one file per record
```

## Commands

```bash
python -m sansad_semantic_crawler crawl  --help
python -m sansad_semantic_crawler parse  --help
python -m sansad_semantic_crawler export --help
```

## Design notes

- **No required third-party dependency for crawling.** If `requests` is
  installed, it is used; otherwise the crawler uses stdlib `urllib`.
  This keeps the install footprint small for users who only need
  the crawl side.
- **`pdfminer.six` is optional.** `pdftotext` (the system binary) is
  preferred because parliamentary PDFs lean heavily on layout for
  tables; `pdfminer.six` is the fallback.
- **The crawler is polite by default** and sleeps between requests
  (`--sleep 0.25` default).
- **`--max-buckets` and `--max-records` are smoke-test brakes.** Use
  them before a full crawl.
- **Stable keys.** Each record's `key` is derived from
  `(house, qtype, qno, answer-date)`. Re-running the crawler resumes
  from `manifest.jsonl` and never re-fetches a key it has already
  seen.

## Reuse pattern

1. `pip install sansad-semantic-crawler`.
2. Author a topic profile (`my-topic.json`) — start by copying
   `examples/topics/libraries.json` and editing the search groups +
   tag rules.
3. Run a capped dry crawl (`--max-buckets 1 --max-records 5`).
4. Inspect `manifest.jsonl`. Tighten the topic regex if recall or
   precision look off.
5. Run a full crawl (with `--max-records` removed) and let the
   resume-key logic dedupe.
6. Run `parse` then `export` into the host project.

## Status and roadmap

This is the **0.1.0** release: a stable, useful slice of what the
crawler is becoming. Planned for later releases:

- Cover **standing-committee reports** (`prsindia.org`,
  `parliamentwatchindia` style) under the same topic-profile contract.
- A **resume-with-date-floor** mode for incremental backfills.
- A small `evaluate` command that scores precision / recall against a
  hand-labelled gold set.

If you're using the crawler and would like a particular extension,
open an issue at the [repository](https://github.com/CommonSenseLLP/sansad-semantic-crawler/issues).

## Licence

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/).

Source-available and modifiable for research, education, journalism,
public-interest work, and personal use. **Commercial use is not
permitted under any circumstance.** The full canonical licence text is
in [`LICENSE`](./LICENSE) at the repository root.

## Citation

A `CITATION.cff` at the repository root carries machine-readable
metadata; GitHub renders a "Cite this repository" button against it.
The maintainer-recommended citation is:

> CommonSense LLP. *Sansad Semantic Crawler — a config-driven crawler
> for Indian parliamentary questions.* 2026.
> <https://github.com/CommonSenseLLP/sansad-semantic-crawler>.
