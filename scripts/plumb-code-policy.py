#!/usr/bin/env python3
"""Report findings on lines added between a merge base and a worktree.

The project contract defines scope, rules, exceptions, and whether findings fail the run.
The built-in comment scan is line-local. See docs/project-contract.md for its limits.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE_LABEL = ".plumb/project.toml"
DEFAULT_DIRECTIVES = ("prettier-ignore",)
MOVE_NOTE = "note: moved lines count as added (known limitation)"
HUNK_HEADER = re.compile(rb"@@ -[0-9]+(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@(?: |$)")
# Match complete same-line literals before looking for comment markers.
COMMENT_TOKENS = re.compile(r"""'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`|(//|/\*)""")

USAGE = """usage: plumb-code-policy report [--base REF] [--json] [--paths-from FILE] [--worktree DIR]

Reads [code_policy] in the project contract (the file `plumb-path project` prints) and reports
each finding on a line the change newly introduces. Run it inside the policy checkout.

  report             the only subcommand
  --base REF         compare against merge-base(REF, HEAD); the default is origin/HEAD's
                     target, else main
  --json             {"schema":1,"outcome":"clean|findings|skip","findings":[...],"counts":{...}}
  --paths-from FILE  look only at the repository-relative paths listed in FILE, one per line
  --worktree DIR     scan DIR using the current checkout's contract and exceptions

Plain output is one line per finding, `rule<TAB>path:line<TAB>excerpt` (the excerpt is at most
80 characters), then `summary: <rule> <count>` for every rule. A report with findings ends with
a note that moved lines count as added. A clean change prints `clean` before its summaries.
A contract without [code_policy] prints `skip: no code_policy`.

The comment kind scans each added line for // or /* outside a quote or backtick pair that
closes on that line. Standalone allow_directives entries are the only allowance.
The project contract and the scan's limits are described in docs/project-contract.md.

Exit 0 means clean, skip or report-mode findings. Exit 1 means enforce-mode findings.
Exit 2 means invalid input or an incomplete scan. Exit 3 means tomllib is unavailable.
"""


def usage_error(reason: str) -> None:
    print(f"plumb-code-policy: usage: {reason} (see --help)", file=sys.stderr)
    sys.exit(2)


def parse_args(argv: list) -> dict:
    args = {"base": None, "json": False, "paths_from": None, "worktree": None}
    if not argv:
        usage_error("expected the report subcommand")
    if argv[0] in ("-h", "--help"):
        sys.stdout.write(USAGE)
        sys.exit(0)
    if argv[0] != "report":
        usage_error(f"unknown subcommand {argv[0]}")
    rest = argv[1:]
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg in ("-h", "--help"):
            sys.stdout.write(USAGE)
            sys.exit(0)
        elif arg == "--json":
            args["json"] = True
        elif arg in ("--base", "--paths-from", "--worktree"):
            if index + 1 >= len(rest) or rest[index + 1].startswith("--"):
                usage_error(f"{arg} needs a value")
            args[arg[2:].replace("-", "_")] = rest[index + 1]
            index += 1
        else:
            usage_error(f"unknown option {arg}")
        index += 1
    return args


def load_project_module():
    """scripts/plumb-project.py has a hyphen, so it is loaded by path. The contract's validity
    is decided in that one place, so the two commands can never disagree about it."""
    spec = importlib.util.spec_from_file_location("plumb_project", HERE / "plumb-project.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScanError(Exception):
    """An incomplete scan must exit with an error."""


def checked_git(args: list, cwd, message: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    # Git can warn about an unreadable path while returning success.
    if result.returncode or result.stderr:
        raise ScanError(message)
    return result.stdout


def glob_regex(pattern: str) -> re.Pattern:
    """A gitwildmatch-shaped glob: a `**` segment spans whole directories (zero or more), `*`
    and `?` stay inside one segment, and the pattern matches from the repository top level."""
    parts = pattern.split("/")
    chunks = []
    for index, part in enumerate(parts):
        if part == "**":
            body = ".*" if index == len(parts) - 1 else "(?:[^/]+/)*"
            chunks.append(("/" + body) if index > 0 and parts[index - 1] != "**" else body)
            continue
        if index > 0 and parts[index - 1] != "**":
            chunks.append("/")
        piece = []
        for char in part:
            if char == "*":
                piece.append("[^/]*")
            elif char == "?":
                piece.append("[^/]")
            else:
                piece.append(re.escape(char))
        chunks.append("".join(piece))
    return re.compile("\\A" + "".join(chunks) + "\\Z")


def added_from_diff(output: bytes) -> tuple:
    """Associate patch sections with the raw part of the same Git diff.

    Raw records and patch sections share an order. A type change has two sections:
    the deletion of the old type, followed by the addition of the new type.
    """
    added = {}
    gitlinks = set()
    if not output:
        return added, gitlinks

    raw, separator, patch = output.partition(b"\0\0")
    if not separator:
        raise ScanError("missing raw path records or patch in Git diff")
    fields = iter(raw.split(b"\0"))
    sections = []
    for record in fields:
        parts = record.split()
        source = next(fields, b"")
        if len(parts) != 5 or not parts[0].startswith(b":") or not source:
            raise ScanError("invalid raw path record in Git diff")
        mode, status = parts[1], parts[4][:1]
        path = next(fields, b"") if status in (b"R", b"C") else source
        if not path:
            raise ScanError("missing destination path in Git diff")
        if mode != b"000000":
            added[path] = set()
        if mode == b"160000":
            gitlinks.add(path)
        if status == b"T":
            sections.append(None)
        sections.append(path if path in added else None)

    section = -1
    old_left = new_left = line_number = 0
    for line in patch.split(b"\n"):
        if line == rb"\ No newline at end of file":
            continue
        if old_left or new_left:
            prefix = line[:1]
            if prefix in (b"-", b" "):
                old_left -= 1
            if prefix in (b"+", b" "):
                if prefix == b"+" and sections[section] is not None:
                    added[sections[section]].add(line_number)
                new_left -= 1
                line_number += 1
            if prefix not in (b"-", b"+", b" ") or old_left < 0 or new_left < 0:
                raise ScanError("invalid line counts in Git diff hunk")
        elif line.startswith(b"diff --git "):
            section += 1
            if section >= len(sections):
                raise ScanError("extra patch section in Git diff")
        elif line.startswith(b"@@"):
            header = HUNK_HEADER.match(line)
            if section < 0 or header is None:
                raise ScanError("invalid Git diff hunk header")
            old_count, new_start, new_count = header.groups()
            old_left = int(old_count or b"1")
            new_left = int(new_count or b"1")
            line_number = int(new_start)

    if old_left or new_left or section + 1 != len(sections):
        raise ScanError("incomplete Git diff patch")
    return added, gitlinks


def introduced(base, top: bytes) -> tuple:
    """Each changed path maps to its added line numbers. None means the whole untracked file."""
    if base is None:
        head = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "origin/HEAD"],
                              cwd=top, capture_output=True)
        if head.returncode not in (0, 1) or head.stderr:
            raise ScanError("cannot resolve origin/HEAD (try --base <ref>)")
        base = "origin/HEAD" if head.returncode == 0 else "main"
    merge_base = checked_git(["merge-base", "--", base, "HEAD"], top,
                             f"cannot resolve the base {base} against HEAD (try --base <ref>)").strip()
    diff = checked_git(
        ["-c", "core.safecrlf=false", "diff", "-U0", "--find-renames", "--raw", "-z", "--patch",
         "--no-color", "--no-ext-diff", "--no-textconv", "--no-relative",
         "--inter-hunk-context=0",
         "--ignore-submodules=none", "--submodule=short", merge_base, "--"],
        top, f"cannot read the change against {os.fsdecode(merge_base)}",
    )
    added, gitlinks = added_from_diff(diff)
    untracked = checked_git(["ls-files", "--others", "--exclude-standard", "-z"], top,
                            "cannot enumerate untracked files")
    if untracked:
        if not untracked.endswith(b"\0"):
            raise ScanError("incomplete Git untracked path list")
        for path in untracked[:-1].split(b"\0"):
            if not path:
                raise ScanError("empty path in Git untracked path list")
            added.setdefault(path.rstrip(b"/"), None)
    return added, gitlinks


def directive_body(line: str):
    """Return the body of a standalone //, /* */ or {/* */} directive."""
    text = line.strip()
    if text.startswith("//"):
        return text[2:].strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1].strip()
    if text.startswith("/*"):
        body, closing, tail = text[2:].partition("*/")
        if closing and not tail.strip():
            return body.strip()
    return None


def comment_hit(line: str, directives: tuple) -> bool:
    return (directive_body(line) not in directives
            and any(token.group(1) for token in COMMENT_TOKENS.finditer(line)))


def read_exceptions(spec: str, top: Path) -> tuple:
    """Return exception pairs and any error. Each row is rule<TAB>path<TAB>reason."""
    full = spec if os.path.isabs(spec) else os.path.join(top, spec)
    if not os.path.isfile(full):
        return None, f"exceptions file {spec}: does not exist"
    try:
        with open(full, encoding="utf-8", errors="surrogateescape", newline="") as handle:
            rows = handle.read().replace("\r\n", "\n").split("\n")
    except OSError:
        return None, f"exceptions file {spec}: cannot be read"
    pairs: set = set()
    for number, row in enumerate(rows, 1):
        if not row:
            continue
        fields = row.split("\t")
        if len(fields) != 3 or not all(field.strip() for field in fields):
            return None, (f"exceptions file {spec}: line {number}: "
                           "expected rule<TAB>path<TAB>reason with a non-empty reason")
        pairs.add((fields[0], fields[1]))
    return pairs, None


def read_source(full: bytes, info: os.stat_result) -> bytes:
    # Guard against a symlink or FIFO replacing the regular file between lstat and open.
    fd = os.open(full, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        current = os.fstat(handle.fileno())
        if (not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)):
            raise ScanError("file changed type or identity before reading")
        return handle.read()


def scan(rules: list, added: dict, gitlinks: set, top: bytes, scoped,
         exceptions: set, only_paths, directives: tuple) -> list:
    """Report findings in path, line, and contract rule order."""
    found = []
    for path in sorted(added):
        name = os.fsdecode(path)
        if not scoped(name) or (only_paths is not None and name not in only_paths):
            continue
        if path in gitlinks:
            print(f"skip: gitlink {name!r}", file=sys.stderr)
            continue
        full = os.path.join(top, path)
        numbers = added[path]
        try:
            info = os.lstat(full)
            if not stat.S_ISREG(info.st_mode):
                kind = "symlink" if stat.S_ISLNK(info.st_mode) else "non-regular file"
                print(f"skip: {kind} {name!r}", file=sys.stderr)
                continue
            if numbers is not None and not numbers:
                continue
            raw = read_source(full, info)
        except (OSError, ScanError) as error:
            raise ScanError(f"cannot read source {name!r}: {error}") from error
        if b"\0" in raw[:8192]:
            continue
        lines = raw.replace(b"\r\n", b"\n").decode("utf-8-sig", errors="replace").split("\n")
        if lines[-1] == "":
            lines.pop()
        if numbers is not None and max(numbers) > len(lines):
            raise ScanError(f"source {name!r} has fewer lines than its Git diff")
        for number in range(1, len(lines) + 1) if numbers is None else sorted(numbers):
            line = lines[number - 1]
            for rule in rules:
                if (rule["id"], name) in exceptions:
                    continue
                if rule["kind"] == "comment":
                    hit = comment_hit(line, directives)
                else:
                    hit = rule["regex"].search(line) is not None
                if hit:
                    found.append({"rule": rule["id"], "path": name, "line": number, "excerpt": line.strip()[:80]})
    return found


def skip_out(args: dict, reason: str) -> int:
    if args["json"]:
        print(json.dumps({"schema": 1, "outcome": "skip", "findings": [], "counts": {}}))
    else:
        print(f"skip: {reason}")
    return 0


def invalid_exit(message: str) -> int:
    print(f"plumb-code-policy: invalid: {message}", file=sys.stderr)
    return 2


def main(argv: list) -> int:
    args = parse_args(argv)

    project = load_project_module()
    path, problem = project.contract_path()
    if problem:
        # Fail closed: a caller that cannot find the contract must not read that as "no policy".
        return invalid_exit(f"{FILE_LABEL}: {problem}")
    try:
        __import__("tomllib")
    except ImportError:
        print(f"plumb-code-policy: unavailable: {project.UNAVAILABLE_MESSAGE}", file=sys.stderr)
        return 3
    try:
        os.lstat(path)
    except FileNotFoundError:
        return skip_out(args, "no code_policy")
    except OSError as error:
        return invalid_exit(f"{FILE_LABEL}: {error}")
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return invalid_exit(f"{FILE_LABEL}: cannot read the file")
    outcome, doc, message, warnings = project.evaluate(raw)
    if outcome == "unavailable":
        print(f"plumb-code-policy: unavailable: {message}", file=sys.stderr)
        return 3
    if outcome == "invalid":
        return invalid_exit(message)
    for name in warnings:
        print(f"plumb-code-policy: warning: unknown key {name}", file=sys.stderr)

    table = doc.get("code_policy")
    if not isinstance(table, dict) or not table:
        return skip_out(args, "no code_policy")
    mode = table.get("mode", "report")
    if mode == "off":
        return skip_out(args, "code_policy mode is off")

    rules = []
    for item in table.get("rule") or []:
        rule = {"id": item["id"], "kind": item["kind"], "regex": None}
        if item["kind"] == "pattern":
            rule["regex"] = re.compile(item["pattern"])
        rules.append(rule)
    directives = tuple(table.get("allow_directives", DEFAULT_DIRECTIVES))
    include = [glob_regex(pattern) for pattern in (table.get("include") or [])]
    exclude = [glob_regex(pattern) for pattern in (table.get("exclude") or [])]

    def scoped(path_: str) -> bool:
        if include and not any(regex.match(path_) for regex in include):
            return False
        return not any(regex.match(path_) for regex in exclude)

    only_paths = None
    if args["paths_from"] is not None:
        try:
            with open(args["paths_from"], encoding="utf-8", errors="surrogateescape", newline="") as handle:
                only_paths = set(handle.read().replace("\r\n", "\n").split("\n"))
        except OSError:
            usage_error("--paths-from needs a readable file")

    exceptions: set = set()
    if isinstance(table.get("exceptions"), str):
        policy_top = Path(path).parent.parent
        exceptions, error = read_exceptions(table["exceptions"], policy_top)
        if error:
            return invalid_exit(error)

    try:
        top = checked_git(["rev-parse", "--show-toplevel"], args["worktree"],
                          "cannot find the worktree top level").removesuffix(b"\n")
        added, gitlinks = introduced(args["base"], top)
        findings = scan(rules, added, gitlinks, top, scoped, exceptions, only_paths, directives)
    except (ScanError, OSError) as error:
        return invalid_exit(str(error))
    counts = {rule["id"]: 0 for rule in rules}
    for finding in findings:
        counts[finding["rule"]] += 1
    outcome = "findings" if findings else "clean"

    if args["json"]:
        print(json.dumps({"schema": 1, "outcome": outcome, "findings": findings, "counts": counts}))
    else:
        if not findings:
            print("clean")
        for finding in findings:
            print(f"{finding['rule']}\t{finding['path']}:{finding['line']}\t{finding['excerpt']}")
        for rule in rules:
            print(f"summary: {rule['id']} {counts[rule['id']]}")
        if findings:
            print(MOVE_NOTE)

    if findings and mode == "enforce":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
