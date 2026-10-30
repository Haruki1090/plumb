#!/usr/bin/env python3
"""The work ledger, failure side: one record per agent failure created in a period.

    plumb-ledger failures --repo <owner/name> --since <date> --until <date>
                          [--label agent-failure] [--findings <jsonl>]... [--json]

A failure record is a GitHub issue or pull request carrying the label (default `agent-failure`) whose
body, or else one of its comments, holds one `<!-- plumb:failure v1 {...} -->` block, or a line of a
`findings.jsonl` written by `plumb:verify`. The format is docs/failure-taxonomy.md.

Dates are calendar days in `ledger.timezone` (default UTC); --until is inclusive. Issues are read
from `repos/{repo}/issues?labels=..&state=all&since=<start>&per_page=100` page by page (REST only,
never `gh api --paginate`, never GraphQL; see ledger_changes.gh_get). That endpoint also returns
pull requests: those get source `pull_request`. Every item **created** in the period is kept,
whatever its `updated_at` (`since` filters on the update time, which is never before the creation
time, so nothing created in the period is missed). An item created before the period but updated in
it is not a record of the period. Comments (`repos/{repo}/issues/{n}/comments`, paged) are read for
an item only when its body has no block.

Per record, in this order: the body's first block, else the first block of the comments. The first
block wins; a second block in the text that was read is the problem `duplicate_block`. Each field is
validated: `code` (C01..C15, a contract `failure.extra_codes` code, or null), `kind` (product |
harness | stale_scenario | null), `category` (non-empty string up to 200 characters, or null), `layer`
(harness | contract | personal | null), `evidence` (non-empty string up to 500 characters, or null),
`origin` (`#n`, `owner/repo#n`, a 7-40 hex commit id, or null). A missing field is null. An invalid
field becomes null and adds `invalid_<field>` to `problems`; a record with no block has every field
null and the problem `no_block`; an unreadable block is `malformed_block`. Nothing is guessed from a
title or from prose, and no record is dropped.

--findings (repeatable) adds the lines of a findings.jsonl as records with source `findings`: one
JSON object per line, `id` and the same fields, `time` (ISO 8601) as the creation time. A line with a
`time` outside the period is left out; a line with no `time` is included. A line that is not a JSON
object is kept with every field null and the problem `malformed_line`.

Output: one JSON object per line on stdout (id, source, number, created_at, updated_at, code, kind,
category, layer, evidence, origin, problems) and a summary on stderr; with --json, one JSON object
`{"records": [...], "summary": {...}}` on stdout instead. Titles and bodies are never printed.

The contract is read only through plumb-project, run in the current directory (ledger.timezone,
failure.extra_codes). An invalid contract exits 2, an unavailable parser exits 3. Exit status: 0 ok,
1 a gh call failed or an input is unreadable, 2 usage or an invalid contract, 3 no TOML parser.
The test hook PLUMB_LEDGER_GH_FIXTURES is the one of ledger_changes.py.

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ledger_changes import (FIELD_LIMIT, LedgerError, contract_value, gh_get, iso_utc, parse_time,  # noqa: E402
                            period_bounds, read_contract)

DEFAULT_LABEL = "agent-failure"
BASE_CODES = tuple(f"C{n:02d}" for n in range(1, 16))
KINDS = ("product", "harness", "stale_scenario")
LAYERS = ("harness", "contract", "personal")
EVIDENCE_LIMIT = 500
FIELDS = ("code", "kind", "category", "layer", "evidence", "origin")
RECORD_KEYS = ("id", "source", "number", "created_at", "updated_at", *FIELDS, "problems")

MARKER = re.compile(r"<!--\s*plumb:failure\b(.*?)-->", re.DOTALL)
BLOCK_V1 = re.compile(r"\s+v1\s+(\{.*\})\s*", re.DOTALL)
ORIGIN = re.compile(r"#\d+|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+|[0-9A-Fa-f]{7,40}")


# ---------------------------------------------------------------------------------------------
# the block and its fields


def markers_of(text: Any) -> list:
    """The raw inside of every `<!-- plumb:failure ... -->` comment in a text, in order."""
    return MARKER.findall(text) if isinstance(text, str) else []


def parse_marker(inner: str) -> tuple:
    """(fields, problem). Only `v1` followed by one JSON object is a block."""
    match = BLOCK_V1.fullmatch(inner)
    if not match:
        return None, "malformed_block"
    try:
        fields = json.loads(match.group(1))
    except ValueError:
        return None, "malformed_block"
    return (fields, None) if isinstance(fields, dict) else (None, "malformed_block")


def text_field(value: Any, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def validate(fields: dict | None, extra_codes: set) -> tuple:
    """({field: value or None}, problems): an absent field is null, an invalid one is null and a problem."""
    fields = fields or {}
    checks = {
        "code": lambda v: isinstance(v, str) and (v in BASE_CODES or v in extra_codes),
        "kind": lambda v: isinstance(v, str) and v in KINDS,
        "category": lambda v: text_field(v, FIELD_LIMIT),
        "layer": lambda v: isinstance(v, str) and v in LAYERS,
        "evidence": lambda v: text_field(v, EVIDENCE_LIMIT),
        "origin": lambda v: isinstance(v, str) and ORIGIN.fullmatch(v) is not None,
    }
    values: dict = {}
    problems: list = []
    for name in FIELDS:
        value = fields.get(name)
        if value is None:
            values[name] = None
        elif checks[name](value):
            values[name] = value
        else:
            values[name] = None
            problems.append(f"invalid_{name}")
    return values, problems


def block_fields(markers: list) -> tuple:
    """(fields or None, problems) from the markers found, the first one winning."""
    if not markers:
        return None, ["no_block"]
    fields, problem = parse_marker(markers[0])
    problems = [problem] if problem else []
    if len(markers) > 1:
        problems.append("duplicate_block")
    return fields, problems


def make_record(identity: Any, source: str, number: int | None, created: str | None, updated: str | None,
                fields: dict | None, problems: list, extra_codes: set) -> dict:
    values, field_problems = validate(fields, extra_codes)
    record = {"id": identity, "source": source, "number": number, "created_at": created, "updated_at": updated,
              **values, "problems": problems + field_problems}
    return {key: record[key] for key in RECORD_KEYS}


# ---------------------------------------------------------------------------------------------
# issues and pull requests


def issue_records(repo: str, label: str, start: datetime, end: datetime, extra_codes: set) -> list:
    endpoint = f"repos/{repo}/issues?labels={quote(label, safe='')}&state=all&since={iso_utc(start)}&per_page=100"
    items = gh_get(endpoint, paginate=True)
    seen: set = set()
    kept: list = []
    for item in items:
        number = item.get("number") if isinstance(item, dict) else None
        if not isinstance(number, int) or isinstance(number, bool):
            raise LedgerError(1, f"repos/{repo}/issues returned an item with no number")
        if number in seen:  # a page boundary that moved while we read
            continue
        seen.add(number)
        try:
            created = parse_time(item["created_at"])
        except (KeyError, TypeError, ValueError):
            raise LedgerError(1, f"issue #{number} has no usable created_at")
        if start <= created < end:
            kept.append((created, number, item))
    kept.sort(key=lambda entry: (entry[0], entry[1]))
    return [from_item(repo, number, item, extra_codes) for _, number, item in kept]


def from_item(repo: str, number: int, item: dict, extra_codes: set) -> dict:
    markers = markers_of(item.get("body"))
    if not markers:
        found = [False]

        def stop(page: list) -> bool:
            found[0] = found[0] or any(markers_of(c.get("body")) for c in page if isinstance(c, dict))
            return found[0]

        comments = gh_get(f"repos/{repo}/issues/{number}/comments?per_page=100", paginate=True, stop=stop)
        for comment in comments:
            if isinstance(comment, dict):
                markers.extend(markers_of(comment.get("body")))
    fields, problems = block_fields(markers)
    source = "pull_request" if item.get("pull_request") else "issue"
    return make_record(number, source, number, item.get("created_at"), item.get("updated_at"), fields,
                       problems, extra_codes)


# ---------------------------------------------------------------------------------------------
# findings.jsonl


def finding_records(paths: list, start: datetime, end: datetime, extra_codes: set) -> list:
    records: list = []
    for path in paths:
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            raise LedgerError(1, f"--findings: cannot read {path}")
        for line in lines:
            if not line.strip():
                continue
            try:
                fields = json.loads(line)
            except ValueError:
                fields = None
            if not isinstance(fields, dict):
                records.append(make_record(None, "findings", None, None, None, None, ["malformed_line"], extra_codes))
                continue
            problems: list = []
            created = None
            if fields.get("time") is not None:
                try:
                    moment = parse_time(fields["time"])
                except (TypeError, ValueError, AttributeError):
                    problems.append("invalid_time")
                else:
                    if not start <= moment < end:
                        continue
                    created = iso_utc(moment)
            identity = fields.get("id")
            if isinstance(identity, bool) or not isinstance(identity, (str, int)):
                identity = None
                problems.append("missing_id")
            records.append(make_record(identity, "findings", None, created, None, fields, problems, extra_codes))
    return records


# ---------------------------------------------------------------------------------------------
# summary


def tally(records: list, field: str) -> dict:
    counts: dict = {}
    for record in records:
        if record[field] is not None:
            counts[record[field]] = counts.get(record[field], 0) + 1
    return dict(sorted(counts.items()))


def summarize(records: list, end: datetime) -> dict:
    after = 0
    for record in records:
        try:
            if record["updated_at"] and parse_time(record["updated_at"]) >= end:
                after += 1
        except ValueError:
            pass
    sources = {name: sum(1 for r in records if r["source"] == name) for name in ("issue", "pull_request", "findings")}
    return {
        "count": len(records),
        "by_source": sources,
        "by_code": tally(records, "code"),
        "by_kind": tally(records, "kind"),
        "by_layer": tally(records, "layer"),
        "unknown": {name: sum(1 for r in records if r[name] is None) for name in FIELDS},
        "with_problems": sum(1 for r in records if r["problems"]),
        "updated_after_period": after,
    }


def render_summary(summary: dict, repo: str, since: str, until: str, zone: str, label: str) -> str:
    def row(title: str, counts: dict) -> str:
        return f"  {title}: " + (", ".join(f"{k} {v}" for k, v in counts.items()) or "none")

    unknown = summary["unknown"]
    lines = [f"plumb-ledger failures: {repo} label {label}, {since} to {until} inclusive ({zone})",
             f"  failures: {summary['count']}",
             row("by source", {k: v for k, v in summary["by_source"].items() if v}),
             row("by code", summary["by_code"]),
             row("by kind", summary["by_kind"]),
             row("by layer", summary["by_layer"]),
             "  unknown: " + ", ".join(f"{name} {unknown[name]}" for name in FIELDS),
             f"  with problems: {summary['with_problems']}",
             f"  updated after the period: {summary['updated_after_period']}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------
# command


def extra_code_set(contract: dict) -> set:
    entries = contract_value(contract, "failure.extra_codes")
    return {e["code"] for e in entries if isinstance(e, dict) and isinstance(e.get("code"), str)} \
        if isinstance(entries, list) else set()


def failures_main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="plumb-ledger failures",
                                     description="One record per agent failure created in a period.")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--since", required=True, help="first day, YYYY-MM-DD, in ledger.timezone")
    parser.add_argument("--until", required=True, help="last day (inclusive), YYYY-MM-DD")
    parser.add_argument("--label", default=DEFAULT_LABEL, help=f"issue label (default {DEFAULT_LABEL})")
    parser.add_argument("--findings", action="append", default=[], metavar="JSONL",
                        help="a findings.jsonl to add as records (repeatable)")
    parser.add_argument("--json", action="store_true", help="print one JSON object {records, summary}")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        raise LedgerError(2, "--repo: expected owner/name")
    if not args.label.strip():
        raise LedgerError(2, "--label: must not be empty")
    contract = read_contract(".")
    zone = contract_value(contract, "ledger.timezone")
    start, end = period_bounds(args.since, args.until, zone)
    extra_codes = extra_code_set(contract)
    records = issue_records(args.repo, args.label, start, end, extra_codes)
    records += finding_records(args.findings, start, end, extra_codes)
    summary = summarize(records, end)
    if args.json:
        sys.stdout.write(json.dumps({"records": records, "summary": summary}, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
        sys.stderr.write(render_summary(summary, args.repo, args.since, args.until, zone or "UTC", args.label))
    return 0


def main(argv: list) -> int:
    if not argv or argv[0] != "failures":
        print("usage: plumb-ledger failures ... (see --help)", file=sys.stderr)
        return 2
    try:
        return failures_main(argv[1:])
    except LedgerError as error:
        print(f"plumb-ledger: {error}", file=sys.stderr)
        return error.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
