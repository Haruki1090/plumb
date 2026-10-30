#!/usr/bin/env python3
"""Read the repository's project contract (<checkout>/.plumb/project.toml).

    plumb-project <dotted.key>
    plumb-project --json [<dotted.key>]
    plumb-project --enforce <dotted.key>

The path comes from `plumb-path project`; this script never rebuilds it. The whole file is
validated against schema v1 once, so a broken file is invalid for every key (a broken contract is
not partly trusted). Unknown tables or keys are a warning on stderr, never an error.

Outcomes (the JSON form always has outcome, key, value and message):

    absent       no file, or the key is not set          prints nothing, exit 0
    set          the key is set in a valid file          prints the value, exit 0
    invalid      TOML error, wrong type, bad schema      stderr, exit 2
    unavailable  Python has no tomllib (< 3.11)          stderr, exit 3

Standard library only. The file is parsed with tomllib (Python 3.11+); on an older Python the
answer is `unavailable`, which is the documented fallback. The syntax below stays valid for older
interpreters on purpose so that answer can be given at all.

Error messages name the key (or the line of a TOML syntax error) and never echo the contract's
contents.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PATH_SCRIPT = Path(__file__).resolve().parent / "plumb-path.sh"
FILE_LABEL = ".plumb/project.toml"
UNAVAILABLE_MESSAGE = "Python 3.11+ (tomllib) is required"

USAGE = """usage: plumb-project <dotted.key>
       plumb-project --json [<dotted.key>]
       plumb-project --enforce <dotted.key>

Reads the repository's project contract (the file `plumb-path project` prints) and validates it
against schema v1 as a whole. Run it inside the checkout.

  <dotted.key>  e.g. rework.required_authors, ledger.timezone, verify.lookup
  --json        always print {"outcome", "key", "value", "message"}; without a key, value is the
                whole contract
  --enforce     the form a CI uses. The rule: no file -> empty output, exit 0; an invalid file ->
                exit 2; no TOML parser -> exit 3; otherwise the value of the key (empty if it is
                unset). A CI must treat any non-zero exit as a failure and read the policy from a
                trusted ref, never from the pull request's own head (docs/project-contract.md)

Outcomes and exit status:
  absent       no file, or the key is not set                      prints nothing   exit 0
  set          the key is set in a valid file                      prints the value exit 0
  invalid      TOML error, wrong type, schema missing or not 1     stderr           exit 2
  unavailable  Python 3.11+ (tomllib) is not available             stderr           exit 3

A string prints as-is, an array of strings one per line, anything else as JSON. Unknown tables or
keys warn on stderr and do not fail. A usage error exits 2.
"""

TOP_LEVEL = ("schema", "repo", "rework", "ledger", "verify", "failure")
VERIFY_KEYS = ("lookup", "up", "down", "scenarios")
KEY_RE = re.compile(r"[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*")


class Invalid(Exception):
    """The contract breaks schema v1. `key` names where; `reason` never quotes the file."""

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(reason)
        self.key = key
        self.reason = reason


def is_int(value: object) -> bool:
    # bool is an int subclass in Python; `lookahead_days = true` is not an integer.
    return type(value) is int


def want_table(value: object, key: str) -> dict:
    if not isinstance(value, dict):
        raise Invalid(key, "expected a table")
    return value


def want_str(table: dict, prefix: str, name: str) -> None:
    if name in table and not isinstance(table[name], str):
        raise Invalid(f"{prefix}.{name}", "expected a string")


def want_str_list(table: dict, prefix: str, name: str) -> None:
    if name not in table:
        return
    value = table[name]
    key = f"{prefix}.{name}"
    if not isinstance(value, list):
        raise Invalid(key, "expected an array of strings")
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise Invalid(f"{key}[{index}]", "expected a string")


def want_pairs(table: dict, prefix: str, name: str, first: str, second: str, warnings: list) -> None:
    """An array of tables, each with a string `first` and a string `second`."""
    if name not in table:
        return
    value = table[name]
    key = f"{prefix}.{name}"
    if not isinstance(value, list):
        raise Invalid(key, f"expected an array of tables with {first} and {second}")
    for index, item in enumerate(value):
        here = f"{key}[{index}]"
        if not isinstance(item, dict):
            raise Invalid(here, f"expected a table with {first} and {second}")
        for field in (first, second):
            if field not in item:
                raise Invalid(f"{here}.{field}", "missing")
            if not isinstance(item[field], str):
                raise Invalid(f"{here}.{field}", "expected a string")
        for extra in sorted(set(item) - {first, second}):
            warnings.append(f"{here}.{extra}")


def check_timezone(name: str) -> None:
    key = "ledger.timezone"
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError:
        # zoneinfo ships with every Python that also has tomllib; reaching this means a broken install.
        raise Invalid(key, "cannot validate: zoneinfo is not available")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise Invalid(key, "expected an IANA time zone name such as Asia/Tokyo")


def validate(doc: dict) -> list:
    """Raise Invalid on the first break of schema v1; return the unknown keys as warnings."""
    warnings: list = []
    if "schema" not in doc:
        raise Invalid("schema", "missing (expected schema = 1)")
    if not is_int(doc["schema"]):
        raise Invalid("schema", "expected the integer 1")
    if doc["schema"] != 1:
        raise Invalid("schema", "unsupported version (this plumb reads schema 1)")

    for name in sorted(set(doc) - set(TOP_LEVEL)):
        warnings.append(name)

    if "repo" in doc:
        repo = want_table(doc["repo"], "repo")
        want_str(repo, "repo", "base_branch")
        warnings.extend(f"repo.{k}" for k in sorted(set(repo) - {"base_branch"}))

    if "rework" in doc:
        rework = want_table(doc["rework"], "rework")
        want_str_list(rework, "rework", "required_authors")
        if "lookahead_days" in rework:
            days = rework["lookahead_days"]
            if not is_int(days) or days < 1:
                raise Invalid("rework.lookahead_days", "expected an integer >= 1")
        warnings.extend(f"rework.{k}" for k in sorted(set(rework) - {"required_authors", "lookahead_days"}))

    if "ledger" in doc:
        ledger = want_table(doc["ledger"], "ledger")
        want_pairs(ledger, "ledger", "classify", "glob", "class", warnings)
        want_str(ledger, "ledger", "timezone")
        if "timezone" in ledger:
            check_timezone(ledger["timezone"])
        warnings.extend(f"ledger.{k}" for k in sorted(set(ledger) - {"classify", "timezone"}))

    if "verify" in doc:
        verify = want_table(doc["verify"], "verify")
        for name in VERIFY_KEYS:
            want_str(verify, "verify", name)
        warnings.extend(f"verify.{k}" for k in sorted(set(verify) - set(VERIFY_KEYS)))

    if "failure" in doc:
        failure = want_table(doc["failure"], "failure")
        want_pairs(failure, "failure", "extra_codes", "code", "mechanism", warnings)
        warnings.extend(f"failure.{k}" for k in sorted(set(failure) - {"extra_codes"}))

    return warnings


def lookup(doc: dict, key: str) -> tuple:
    """Walk the dotted key through tables only. Returns (found, value)."""
    node: object = doc
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def render(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "\n".join(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def contract_path() -> tuple:
    """(path, error). The path is asked from plumb-path; it is never rebuilt here."""
    try:
        done = subprocess.run(["bash", str(PATH_SCRIPT), "project"], capture_output=True, text=True)
    except OSError:
        return None, "cannot run plumb-path"
    if done.returncode != 0 or not done.stdout.strip():
        return None, "cannot locate the contract (run inside a git repository)"
    return done.stdout.strip().splitlines()[0], None


def syntax_reason(error: Exception) -> str:
    # tomllib reports "... (at line N, column M)". Keep the position, drop the rest.
    found = re.search(r"at line ([0-9]+)", str(error))
    return f"TOML syntax error at line {found.group(1)}" if found else "TOML syntax error"


def emit(args: dict, outcome: str, value: object, message: str, code: int) -> int:
    key = args["key"]
    if args["json"]:
        print(json.dumps({"outcome": outcome, "key": key, "value": value, "message": message},
                         ensure_ascii=False, default=str))
    elif outcome == "set":
        print(render(value))
    elif outcome in ("invalid", "unavailable"):
        print(f"plumb-project: {outcome}: {message}", file=sys.stderr)
    return code


def parse_args(argv: list) -> dict:
    args = {"json": False, "enforce": False, "key": None}
    for arg in argv:
        if arg in ("-h", "--help"):
            sys.stdout.write(USAGE)
            sys.exit(0)
        elif arg == "--json":
            args["json"] = True
        elif arg == "--enforce":
            args["enforce"] = True
        elif arg.startswith("-"):
            usage_error(f"unknown option {arg}")
        elif args["key"] is None:
            args["key"] = arg
        else:
            usage_error("expected at most one key")
    if args["key"] is None and not args["json"]:
        usage_error("a key is required (or --json for the whole contract)")
    if args["enforce"] and args["key"] is None:
        usage_error("--enforce needs a key")
    if args["key"] is not None and not KEY_RE.fullmatch(args["key"]):
        usage_error("the key must be dotted names such as rework.required_authors")
    return args


def usage_error(reason: str) -> None:
    print(f"plumb-project: usage: {reason} (see --help)", file=sys.stderr)
    sys.exit(2)


def main(argv: list) -> int:
    args = parse_args(argv)

    path, problem = contract_path()
    if problem:
        # Fail closed: a CI that cannot find the contract must not read that as "no policy".
        return emit(args, "invalid", None, f"{FILE_LABEL}: {problem}", 2)

    # No file means no policy. That needs no parser, so it is answered before tomllib is touched.
    if not os.path.lexists(path):
        return emit(args, "absent", None, "no contract file", 0)

    try:
        import tomllib
    except ImportError:
        return emit(args, "unavailable", None, UNAVAILABLE_MESSAGE, 3)

    try:
        with open(path, "rb") as handle:
            doc = tomllib.load(handle)
        warnings = validate(doc)
    except tomllib.TOMLDecodeError as error:
        return emit(args, "invalid", None, f"{FILE_LABEL}: {syntax_reason(error)}", 2)
    except UnicodeDecodeError:
        return emit(args, "invalid", None, f"{FILE_LABEL}: not valid UTF-8", 2)
    except OSError:
        return emit(args, "invalid", None, f"{FILE_LABEL}: cannot read the file", 2)
    except Invalid as error:
        return emit(args, "invalid", None, f"{error.key}: {error.reason}", 2)

    for name in warnings:
        print(f"plumb-project: warning: unknown key {name}", file=sys.stderr)

    if args["key"] is None:
        return emit(args, "set", doc, "", 0)
    found, value = lookup(doc, args["key"])
    if not found:
        return emit(args, "absent", None, "key not set", 0)
    return emit(args, "set", value, "", 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
