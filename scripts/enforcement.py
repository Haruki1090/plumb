#!/usr/bin/env python3
"""plumb-enforcement: which of plumb's rules a machine enforces, and which rest on prose alone.

    plumb-enforcement [--root DIR] [--json] [--check]

Reads docs/enforcement.tsv (header `rule<TAB>stated_in<TAB>mechanism<TAB>enforced_by`, one row per rule),
validates it against the tree, and prints

    enforcement: <total> rules: check <a>, hook <b>, command <c>, prose <d>

followed by the prose rows as `prose<TAB><stated_in><TAB><rule>`. `--check` prints only the problems and
exits 1 when there is one, 0 otherwise. `--json` prints the whole table, the counts and the problems as one
JSON object (exit 1 when there is a problem). A usage error exits 2.

The four mechanisms:

  check    a script or a numbered check-harness rule fails
  hook     a hook in hooks/hooks.json changes or blocks the action
  command  a plumb-* command reports it, and nothing runs it automatically
  prose    nothing but the text

`stated_in` is a repository path, optionally `path#heading` (the heading is a case-insensitive part of a
heading line of that Markdown file). `enforced_by` is `check-harness rule N`, `hook <Event>[:<matcher>]`, a
plumb-* command (first word resolved against bin/, further words are arguments), a repository path, or `-` for
prose. Every path must exist. Calls no model, reads the network never, writes nothing. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TABLE = "docs/enforcement.tsv"
COLUMNS = ("rule", "stated_in", "mechanism", "enforced_by")
MECHANISMS = ("check", "hook", "command", "prose")
HARNESS = "scripts/check-harness.sh"
HOOKS = "hooks/hooks.json"
RULE_REF = re.compile(r"^check-harness rule (\d+[a-z]?)$")
HOOK_REF = re.compile(r"^hook (\S+)$")


def squash(text: str) -> str:
    return " ".join(text.split()).lower()


def hook_names(root: Path) -> tuple[set[str], str]:
    """The names `Event` and `Event:matcher` of every hook in hooks/hooks.json, and an error text if unreadable."""
    path = root / HOOKS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for event, entries in data["hooks"].items():
            names.add(event)
            for entry in entries:
                matcher = entry.get("matcher")
                if matcher:
                    names.add(f"{event}:{matcher}")
        return names, ""
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
        return set(), f"{HOOKS}: cannot read the hooks ({type(error).__name__})"


def harness_rules(root: Path) -> set[str]:
    """The numbers N of every `# N.` comment that opens a rule in scripts/check-harness.sh."""
    try:
        text = (root / HARNESS).read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(re.findall(r"^# (\d+[a-z]?)\.", text, re.MULTILINE))


def headings(path: Path) -> list[str]:
    found = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^#{1,6}\s+(.*)$", line)
        if match:
            found.append(squash(match.group(1)))
    return found


def read_rows(root: Path) -> tuple[list[dict], list[str]]:
    path = root / TABLE
    if not path.is_file():
        return [], [f"{TABLE}: missing"]
    problems: list[str] = []
    rows: list[dict] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or tuple(lines[0].split("\t")) != COLUMNS:
        return [], [f"{TABLE}:1: the header must be {' | '.join(COLUMNS)} (tab-separated)"]
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) != len(COLUMNS):
            problems.append(f"{TABLE}:{number}: expected {len(COLUMNS)} columns, found {len(cells)}")
            continue
        row = dict(zip(COLUMNS, (cell.strip() for cell in cells)))
        row["line"] = number
        empty = [column for column in COLUMNS if not row[column]]
        if empty:
            problems.append(f"{TABLE}:{number}: empty {', '.join(empty)}")
            continue
        rows.append(row)
    return rows, problems


def validate(root: Path, rows: list[dict]) -> list[str]:
    problems: list[str] = []
    rules = harness_rules(root)
    hooks, hooks_error = hook_names(root)
    hooks_error_reported = False
    seen: dict[str, int] = {}

    def at(row: dict, message: str) -> str:
        return f"{TABLE}:{row['line']}: {message}"

    for row in rows:
        key = squash(row["rule"])
        if key in seen:
            problems.append(at(row, f"duplicate rule text (first on line {seen[key]})"))
        else:
            seen[key] = row["line"]

        mechanism = row["mechanism"]
        if mechanism not in MECHANISMS:
            problems.append(at(row, f"unknown mechanism {mechanism!r} (one of {', '.join(MECHANISMS)})"))

        path_text, _, heading = row["stated_in"].partition("#")
        stated = root / path_text
        if not path_text or not stated.is_file():
            problems.append(at(row, f"stated_in: no such file {path_text!r}"))
        elif heading:
            if not path_text.endswith(".md"):
                problems.append(at(row, f"stated_in: a heading needs a Markdown file, not {path_text!r}"))
            elif not any(squash(heading) in text for text in headings(stated)):
                problems.append(at(row, f"stated_in: no heading containing {heading!r} in {path_text}"))

        by = row["enforced_by"]
        if mechanism == "prose":
            if by != "-":
                problems.append(at(row, f"a prose rule has enforced_by '-', not {by!r}"))
            continue
        if mechanism not in MECHANISMS:
            continue
        if by == "-":
            problems.append(at(row, f"a {mechanism} rule names what enforces it"))
            continue

        rule_ref = RULE_REF.match(by)
        hook_ref = HOOK_REF.match(by)
        first = by.split()[0]
        if rule_ref:
            if mechanism != "check":
                problems.append(at(row, f"a check-harness rule is mechanism check, not {mechanism}"))
            if rule_ref.group(1) not in rules:
                problems.append(at(row, f"{HARNESS} has no rule {rule_ref.group(1)} (a '# {rule_ref.group(1)}.' comment)"))
        elif hook_ref:
            if mechanism != "hook":
                problems.append(at(row, f"a hook is mechanism hook, not {mechanism}"))
            if hooks_error:
                if not hooks_error_reported:
                    problems.append(hooks_error)
                    hooks_error_reported = True
            elif hook_ref.group(1) not in hooks:
                problems.append(at(row, f"{HOOKS} has no hook {hook_ref.group(1)!r}"))
        elif first.startswith("plumb-"):
            if mechanism != "command":
                problems.append(at(row, f"a plumb-* command is mechanism command, not {mechanism}"))
            if not (root / "bin" / first).is_file():
                problems.append(at(row, f"bin/{first} does not exist"))
        elif "/" in first:
            if mechanism not in ("check", "command"):
                problems.append(at(row, f"a script path is mechanism check or command, not {mechanism}"))
            if not (root / first).is_file():
                problems.append(at(row, f"enforced_by: no such file {first!r}"))
        else:
            problems.append(at(row, f"enforced_by {by!r} is not 'check-harness rule N', 'hook <name>', a plumb-* command or a path"))
    return problems


def summarize(rows: list[dict]) -> tuple[dict, str]:
    counts = {mechanism: sum(1 for row in rows if row["mechanism"] == mechanism) for mechanism in MECHANISMS}
    line = (f"enforcement: {len(rows)} rules: check {counts['check']}, hook {counts['hook']}, "
            f"command {counts['command']}, prose {counts['prose']}")
    return counts, line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plumb-enforcement",
        description="Which of plumb's rules a machine enforces, and which rest on prose alone.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                        help="the plumb checkout (default: this one)")
    parser.add_argument("--json", action="store_true", help="print the table, counts and problems as JSON")
    parser.add_argument("--check", action="store_true",
                        help="print only the problems; exit 1 when there is one, 0 otherwise")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        parser.error(f"not a directory: {args.root}")

    rows, problems = read_rows(root)
    problems += validate(root, rows)
    counts, summary = summarize(rows)

    if args.json:
        public = [{column: row[column] for column in COLUMNS} for row in rows]
        print(json.dumps({"total": len(rows), "counts": counts, "rules": public, "problems": problems},
                         ensure_ascii=False, indent=2))
    elif args.check:
        for problem in problems:
            print(problem)
    else:
        if rows:
            print(summary)
            for row in rows:
                if row["mechanism"] == "prose":
                    print(f"prose\t{row['stated_in']}\t{row['rule']}")
        for problem in problems:
            print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
