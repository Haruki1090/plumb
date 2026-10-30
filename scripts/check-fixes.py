#!/usr/bin/env python3
"""Validate the `Fixes-PR:` line of a pull request body.

    plumb-check-fixes --author <login> --required-authors <a,b,...> --pr <n> --body-file <path>

This is a checker, not a policy reader: the caller passes the author, the list of authors who must
write the line, and the pull request number, all from a trusted source (docs/project-contract.md,
"Trusted CI wiring"). Nothing here reads the contract or the repository.

An author is required when their login (case-insensitive) is in the list (entries trimmed, empty
entries dropped). A non-required author passes before the body file is opened. For a required
author the body, with HTML comments and carriage returns removed, must hold exactly one line that
starts with `Fixes-PR:`; its value is `none` or `#<1-9 digits>` items separated by commas, each
number once, none of them this pull request.

Exit status: 0 ok, 1 not ok, 2 usage error. Messages name the rule and never echo the body.

Linear time on purpose (str.find loops and split, one short fullmatch per item): the body is
untrusted input that a CI parses.
"""
from __future__ import annotations

import re
import sys

USAGE = """usage: plumb-check-fixes --author <login> --required-authors <a,b,...> --pr <n> --body-file <path>

Checks the `Fixes-PR:` line of a pull request body when --author is one of --required-authors
(case-insensitive). The caller supplies all four values from a trusted source; this tool reads
no policy itself.

  Fixes-PR: none
  Fixes-PR: #12, #34

Exactly one such line (HTML comments are ignored); the value is `none` or `#<number>` items
separated by commas, each number once, none of them --pr.

Exit status: 0 ok (or the author is not required), 1 not ok, 2 usage error.
"""

PREFIX = "Fixes-PR:"
OPTIONS = ("--author", "--required-authors", "--pr", "--body-file")
ITEM = re.compile(r"#[0-9]{1,9}")
BLANKS = " \t"


class NotOk(Exception):
    """The body breaks a rule. The message names the rule and never quotes the body."""


def usage_error(reason: str) -> None:
    print(f"plumb-check-fixes: usage: {reason} (see --help)", file=sys.stderr)
    sys.exit(2)


def parse_args(argv: list) -> dict:
    values: dict = {}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-h", "--help"):
            sys.stdout.write(USAGE)
            sys.exit(0)
        name, equals, inline = arg.partition("=")
        if name not in OPTIONS:
            usage_error(f"unknown argument {name}")
        if equals:
            value = inline
        else:
            index += 1
            # An empty value is legitimate (an unset CI expression); a following flag is not a value.
            if index >= len(argv) or argv[index].startswith("--"):
                usage_error(f"{name} needs a value")
            value = argv[index]
        values[name] = value
        index += 1
    for name in ("--author", "--required-authors"):
        if name not in values:
            usage_error(f"{name} is required")
    return values


def is_required(author: str, required_authors: str) -> bool:
    names = [name.strip(BLANKS).lower() for name in required_authors.split(",")]
    names = [name for name in names if name]
    if not names:
        return False
    if not author.strip(BLANKS):
        # Somebody is required but we cannot tell who wrote this: that is a failure, not a pass.
        raise NotOk("--author is empty while the required-authors list is not")
    return author.strip(BLANKS).lower() in names


def strip_comments(text: str) -> str:
    """Remove `<!-- ... -->`; an unclosed comment stays as text. One pass over the text."""
    parts = []
    position = 0
    while True:
        start = text.find("<!--", position)
        if start == -1:
            break
        end = text.find("-->", start + 4)
        if end == -1:
            break
        parts.append(text[position:start])
        position = end + 3
    parts.append(text[position:])
    return "".join(parts)


def parse_pr(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,9}", value) or int(value) < 1:
        raise NotOk("--pr is missing or not a positive integer")
    return int(value)


def check_line(value: str, pr: int) -> None:
    value = value.strip(BLANKS)
    if value == "none":
        return
    seen = set()
    for item in value.split(","):
        item = item.strip(BLANKS)
        if not ITEM.fullmatch(item):
            raise NotOk("Fixes-PR: malformed item (expected none, or #<number> items separated by commas)")
        number = int(item[1:])
        if number in seen:
            raise NotOk("Fixes-PR: duplicate number")
        if number == pr:
            raise NotOk("Fixes-PR: lists this pull request itself")
        seen.add(number)


def check_body(body: str, pr: int) -> None:
    text = strip_comments(body).replace("\r", "")
    lines = [line for line in text.split("\n") if line.startswith(PREFIX)]
    if not lines:
        raise NotOk("no Fixes-PR line (write exactly one: Fixes-PR: none, or Fixes-PR: #<number>, ...)")
    if len(lines) > 1:
        raise NotOk(f"more than one Fixes-PR line ({len(lines)}; write exactly one)")
    check_line(lines[0][len(PREFIX):], pr)


def main(argv: list) -> int:
    args = parse_args(argv)
    try:
        if not is_required(args["--author"], args["--required-authors"]):
            return 0
        pr = parse_pr(args.get("--pr", ""))
        if "--body-file" not in args:
            usage_error("--body-file is required when the author is required")
        try:
            with open(args["--body-file"], "rb") as handle:
                body = handle.read().decode("utf-8", errors="replace")
        except OSError:
            raise NotOk("cannot read the body file")
        check_body(body, pr)
    except NotOk as error:
        print(f"plumb-check-fixes: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
