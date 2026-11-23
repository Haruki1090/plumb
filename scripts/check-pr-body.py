#!/usr/bin/env python3
"""plumb-check-pr-body: mechanical checks on a pull request body.

    plumb-check-pr-body (--file PATH | - | --pr N [--repo OWNER/NAME]) [--max-lines 40] [--max-block-lines 15]
                        [--heading NAME]... [--allow-alias "Name=Alias"]... [--json]

Reads one body (a file, standard input with `-`, or `gh pr view N --json body`) and prints one finding per
line as `rule<TAB>detail`, then `pr-body: clean` or `pr-body: N findings`. It calls no model and writes
nothing. Exit status: 0 clean, 1 findings, 2 usage or input error.

The rules:

  too-long          more than --max-lines non-blank lines outside fenced code blocks (headings and table rows
                    count; the lines of a fenced block, a trailer and a bare URL ending the body do not)
  heading-missing   a required `## Name` heading is absent (ATX H2 only, case-insensitive)
  heading-order     the headings that are present are not in the required order
  long-block        a fenced code block holds more than --max-block-lines lines: a log or a long table
                    belongs behind a link
  empty-section     a heading present has nothing before the next `#` or `##` heading (a `###` inside counts
                    as content; a trailer or a bare URL ending the body does not)

The default headings follow playbooks/opening-a-pr.md: Why, Scope, Tradeoffs, Blast Radius, Verification, in
that order. That playbook says to drop a section that would be empty, so only Tradeoffs is optional here (a
`?` on a --heading name marks it optional). `--heading` (repeatable) replaces the whole list; all of it is
then required unless marked. `--allow-alias "Scope=What changed"` lets another H2 text stand for a listed
heading.

Trailers are not counted: `Fixes-PR:`, `Co-Authored-By:`, `Claude-Session:`, `Signed-off-by:`,
`Reviewed-by:`, any `Generated with ...` footer line, and the bare URL lines that end the body. HTML comments
are ignored. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_view import run_gh  # noqa: E402

DEFAULT_MAX_LINES = 40
DEFAULT_MAX_BLOCK_LINES = 15
GH_TIMEOUT = 20.0
DEFAULT_HEADINGS = ("Why", "Scope", "Tradeoffs?", "Blast Radius", "Verification")

HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*))?$")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
TRAILER = re.compile(r"^\s*(fixes-pr|co-authored-by|claude-session|signed-off-by|reviewed-by)\s*:", re.IGNORECASE)
GENERATED = re.compile(r"generated (with|by)\b", re.IGNORECASE)
BARE_URL = re.compile(r"^\s*<?https?://\S+>?\s*$")


class Line(NamedTuple):
    kind: str  # blank | prose | fence_open | fence_body | fence_close
    text: str


class Heading(NamedTuple):
    name: str  # canonical: the listed name, lower-cased and single-spaced
    index: int  # line index in the parsed body


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


# ---------------------------------------------------------------- reading the body

def parse(body: str) -> tuple[list[Line], list[tuple[int, int]]]:
    """(lines, blocks). HTML comments outside fences are blanked. `blocks` is (first line number, number of
    lines between the markers) for every fenced block; one left open runs to the end of the body."""
    lines: list[Line] = []
    blocks: list[tuple[int, int]] = []
    fence: tuple[str, int] | None = None
    in_comment = False
    opened = count = 0
    for number, raw in enumerate(body.replace("\r\n", "\n").replace("\r", "\n").split("\n"), start=1):
        if fence is not None:
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})[ \t]*$", raw)
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= fence[1]:
                blocks.append((opened, count))
                lines.append(Line("fence_close", raw))
                fence = None
            else:
                count += 1
                lines.append(Line("fence_body", raw))
            continue
        text, out, i = raw, "", 0
        while True:
            if in_comment:
                end = text.find("-->", i)
                if end < 0:
                    break
                i, in_comment = end + 3, False
            else:
                start = text.find("<!--", i)
                if start < 0:
                    out += text[i:]
                    break
                out += text[i:start]
                i, in_comment = start + 4, True
        text = out
        opener = FENCE_OPEN.match(text)
        if opener and not (opener.group(1)[0] == "`" and "`" in opener.group(2)):
            fence, opened, count = (opener.group(1)[0], len(opener.group(1))), number, 0
            lines.append(Line("fence_open", text))
        else:
            lines.append(Line("prose" if text.strip() else "blank", text))
    if fence is not None:
        blocks.append((opened, count))
    return lines, blocks


def is_trailer(text: str) -> bool:
    return bool(TRAILER.match(text) or GENERATED.search(text))


def dropped_indexes(lines: list[Line]) -> set[int]:
    """The lines that are not content: every trailer, and the blank, trailer and bare-URL lines that end the body."""
    dropped = {i for i, line in enumerate(lines) if line.kind == "prose" and is_trailer(line.text)}
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if line.kind == "blank" or i in dropped or (line.kind == "prose" and BARE_URL.match(line.text)):
            dropped.add(i)
        else:
            break
    return dropped


def headings_of(lines: list[Line], names: dict[str, str]) -> tuple[dict[str, int], list[int]]:
    """(first line index per canonical heading, the line index of every H1 or H2). `names` maps a normalised
    heading text, an alias included, to its canonical key."""
    first: dict[str, int] = {}
    boundaries: list[int] = []
    for i, line in enumerate(lines):
        if line.kind != "prose":
            continue
        found = HEADING.match(line.text)
        if not found or len(found.group(1)) > 2:
            continue
        boundaries.append(i)
        if len(found.group(1)) == 2:
            text = re.sub(r"[ \t]+#+[ \t]*$", "", found.group(2) or "").strip()
            key = names.get(norm(text))
            if key is not None and key not in first:
                first[key] = i
    return first, boundaries


# ---------------------------------------------------------------- the rules

def check(body: str, headings: list[tuple[str, bool]], aliases: dict[str, str], max_lines: int = DEFAULT_MAX_LINES,
          max_block_lines: int = DEFAULT_MAX_BLOCK_LINES) -> list[tuple[str, str]]:
    """The findings as (rule, detail), in rule order. `headings` is (name, required) in the required order;
    `aliases` maps a normalised alias text to a name from that list. A pure function of its arguments."""
    lines, blocks = parse(body)
    dropped = dropped_indexes(lines)
    out: list[tuple[str, str]] = []

    counted = sum(1 for i, line in enumerate(lines) if line.kind == "prose" and i not in dropped)
    if counted > max_lines:
        out.append(("too-long", f"{counted} non-blank lines outside fenced code blocks (max {max_lines})"))

    keyed = {norm(name): name for name, _ in headings}
    keyed.update({alias: keyed[norm(target)] for alias, target in aliases.items() if norm(target) in keyed})
    first, boundaries = headings_of(lines, keyed)

    for name, required in headings:
        if required and name not in first:
            out.append(("heading-missing", f"## {name}"))

    present = [name for name, _ in headings if name in first]
    for before, after in zip(present, present[1:]):
        if first[after] < first[before]:
            out.append(("heading-order", f"## {after} appears before ## {before}"))

    for opened, size in blocks:
        if size > max_block_lines:
            out.append(("long-block", f"line {opened}: {size} lines in a fenced block (max {max_block_lines}); "
                                      "put a log or a long table behind a link"))

    for name, _ in headings:
        if name not in first:
            continue
        start = first[name]
        end = next((b for b in boundaries if b > start), len(lines))
        body_lines = [i for i in range(start + 1, end) if i not in dropped and lines[i].kind != "blank"]
        if not body_lines:
            out.append(("empty-section", f"## {name} has nothing before the next heading"))
    return out


def parse_headings(values: list[str] | None) -> list[tuple[str, bool]]:
    result: list[tuple[str, bool]] = []
    for value in values or DEFAULT_HEADINGS:
        optional = value.endswith("?")
        name = " ".join((value[:-1] if optional else value).split())
        if not name:
            raise ValueError("a --heading name is empty")
        if any(norm(name) == norm(seen) for seen, _ in result):
            raise ValueError(f"--heading {name} is listed twice")
        result.append((name, not optional))
    return result


def parse_aliases(values: list[str] | None, headings: list[tuple[str, bool]]) -> dict[str, str]:
    names = {norm(name): name for name, _ in headings}
    out: dict[str, str] = {}
    for value in values or []:
        target, equals, alias = value.partition("=")
        if not equals or not norm(target) or not norm(alias):
            raise ValueError(f'--allow-alias needs "Name=Alias", got {value!r}')
        if norm(target) not in names:
            raise ValueError(f"--allow-alias names {target.strip()!r}, which is not a heading in the list")
        out[norm(alias)] = names[norm(target)]
    return out


# ---------------------------------------------------------------- input and output

def read_pr_body(number: int, repo: str | None) -> str:
    """The body of pull request `number`; ValueError when gh cannot give it."""
    args = ["pr", "view", str(number), "--json", "body"] + (["--repo", repo] if repo else [])
    try:
        done = run_gh(args, ".", GH_TIMEOUT)
        if done.returncode != 0:
            raise ValueError(f"gh could not read pull request {number}")
        body = json.loads(done.stdout)["body"]
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"gh could not read pull request {number} ({type(error).__name__})") from error
    if body is not None and not isinstance(body, str):
        raise ValueError(f"pull request {number} has no readable body")
    return body or ""


def read_source(args: argparse.Namespace) -> str:
    if args.pr is not None:
        return read_pr_body(args.pr, args.repo)
    try:
        if args.file == "-":
            return sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return Path(args.file).read_bytes().decode("utf-8", errors="replace")
    except OSError as error:
        raise ValueError(f"cannot read {args.file}: {error.strerror or type(error).__name__}") from error


def render(findings: list[tuple[str, str]]) -> str:
    lines = [f"{rule}\t{detail}" for rule, detail in findings]
    lines.append("pr-body: clean" if not findings else f"pr-body: {len(findings)} findings")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plumb-check-pr-body", description=__doc__.splitlines()[0])
    parser.add_argument("source", nargs="?", help="`-` reads the body from standard input")
    parser.add_argument("--file", default=None, help="read the body from this file (`-`: standard input)")
    parser.add_argument("--pr", type=int, default=None, help="read the body of this pull request through gh")
    parser.add_argument("--repo", default=None, help="OWNER/NAME for --pr (default: the current directory's repository)")
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES,
                        help=f"non-blank lines allowed outside fenced blocks (default {DEFAULT_MAX_LINES})")
    parser.add_argument("--max-block-lines", type=int, default=DEFAULT_MAX_BLOCK_LINES,
                        help=f"lines allowed in one fenced block (default {DEFAULT_MAX_BLOCK_LINES})")
    parser.add_argument("--heading", action="append", default=None, metavar="NAME",
                        help="a required H2 heading, in order; repeat it (replaces the default list; NAME? is optional)")
    parser.add_argument("--allow-alias", action="append", default=None, metavar="NAME=ALIAS",
                        help='another H2 text accepted for a listed heading, e.g. "Scope=What changed"')
    parser.add_argument("--json", action="store_true", help="print JSON instead of lines")
    args = parser.parse_args(argv)
    if args.source is not None:
        if args.source != "-":
            parser.error("the only positional argument is `-` (standard input); use --file PATH")
        if args.file is not None:
            parser.error("give the body once: `-` or --file, not both")
        args.file = "-"
    if (args.file is None) == (args.pr is None):
        parser.error("give exactly one of --file PATH, `-`, or --pr N")
    if args.pr is not None and args.pr < 1:
        parser.error("--pr must be a positive number")
    if args.repo is not None and (not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo) or args.pr is None):
        parser.error("--repo is OWNER/NAME and goes with --pr")
    for flag in ("max_lines", "max_block_lines"):
        if getattr(args, flag) < 0:
            parser.error(f"--{flag.replace('_', '-')} must not be negative")
    try:
        headings = parse_headings(args.heading)
        aliases = parse_aliases(args.allow_alias, headings)
        body = read_source(args)
    except ValueError as error:
        print(f"plumb-check-pr-body: {error}", file=sys.stderr)
        return 2
    findings = check(body, headings, aliases, args.max_lines, args.max_block_lines)
    if args.json:
        doc: dict[str, Any] = {"schema": 1, "outcome": "findings" if findings else "clean",
                               "findings": [{"rule": rule, "detail": detail} for rule, detail in findings]}
        print(json.dumps(doc, indent=2, ensure_ascii=False))
    else:
        print(render(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
