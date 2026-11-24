#!/usr/bin/env python3
"""Report findings on lines added between a merge base and a worktree.

The project contract defines scope, rules, exceptions, and whether findings fail the run.
The built-in comment scans use only the added lines of one file. See docs/project-contract.md for their limits.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE_LABEL = ".plumb/project.toml"
DEFAULT_DIRECTIVES = ("prettier-ignore",)
MOVE_NOTE = "note: moved lines count as added (known limitation)"
DATE_FORM = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
NO_NEWLINE = rb"\ No newline at end of file"
HUNK_HEADER = re.compile(rb"@@ -[0-9]+(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@(?: |$)")
# Match complete same-line literals before looking for comment markers.
COMMENT_TOKENS = re.compile(r"""'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`|(//|/\*)""")
HASH_SUFFIXES = (".py", ".sh", ".bash", ".zsh", ".rb", ".pl", ".r", ".yaml", ".yml", ".toml", ".tf",
                 ".ps1", ".cmake", ".mk")
HASH_NAMES = ("Makefile", "Dockerfile")
SEQUENCE_KINDS = ("comment-block", "commented-code")
CODE_END = re.compile(r"(?:[;{}]|\)\s*;?)$")
CODE_START = re.compile(r"(?:(?:return|if|for|while|const|let|var|import|from|def|class|function|final|"
                        r"await|async|export|elif|except)\b|else:|try:)")
CODE_MARKS = re.compile(r"[({;]|\s=\s|\+=|-=")
ASSIGNMENT = re.compile(r"[A-Za-z_][\w.\[\]]*\s*(?:=|\+=|-=)\s*\S")
CALL = re.compile(r"[A-Za-z_][\w.]*\(.*\)\s*;?$")
PROSE = re.compile(r"[A-Z][a-z]*:?\s+[a-z]")

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
80 characters), then `summary: <rule> <count>` for every configured rule and for
`non-regular` or `expired-exception` when that finding occurs. A report with findings ends with a
note that moved lines count as added. A clean change prints `clean` before its summaries.
A contract without [code_policy] prints `skip: no code_policy`.

An exceptions row may carry a 4th column `expires` (YYYY-MM-DD) and a 5th `approved_by`. A row
that expired before today (PLUMB_TODAY, else the local date) stops suppressing and is itself
reported as `expired-exception` at line 0.

The comment kind scans each added line for // or /* outside a quote or backtick pair that
closes on that line. Standalone allow_directives entries are the only allowance.

The comment-block kind (min_lines = N, an integer of at least 2) reports one finding per run of
at least N consecutive added comment-only lines, at the run's first line. The commented-code kind
reports one finding per run of consecutive added comment-only lines that look like code. A
comment-only line starts with //, /* or */, or sits inside an open /* ... */ block; in .py .sh
.bash .zsh .rb .pl .r .yaml .yml .toml .tf .ps1 .cmake .mk, Makefile and Dockerfile files it
starts with # instead (a #! first line is not one). Added lines that are not consecutive never
join a run, and a line that already existed is never counted.
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


def checked_git(args: list, cwd, message: str, allowed=(0,)) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            env={**os.environ, "LC_ALL": "C"})
    if result.stderr:
        sys.stderr.buffer.write(result.stderr)
        if not result.stderr.endswith(b"\n"):
            sys.stderr.buffer.write(b"\n")
    incomplete = any(line.startswith((b"warning: could not open", b"warning: unable to access"))
                     for line in result.stderr.split(b"\n"))
    if result.returncode not in allowed or incomplete:
        raise ScanError(message)
    return result


def glob_matches(parts: list, pattern: list) -> bool:
    """Match a repository-relative path, with fnmatch syntax within each segment."""
    ends = {0}
    for index, segment in enumerate(pattern):
        if not ends:
            return False
        if segment == "**":
            start = min(ends)
            if index == len(pattern) - 1:
                return start < len(parts)
            ends = set(range(start, len(parts) + 1))
        else:
            ends = {end + 1 for end in ends
                    if end < len(parts) and fnmatchcase(parts[end], segment)}
    return len(parts) in ends


def added_from_diff(output: bytes) -> tuple:
    """Associate patch sections with the raw part of the same Git diff.

    Raw records and patch sections share an order. A type change has two sections:
    the deletion of the old type, followed by the addition of the new type.
    """
    added = {}
    file_types = {}
    if not output:
        return added, file_types

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
            added[path] = {}
        if mode == b"160000":
            file_types[path] = "gitlink"
        elif mode == b"120000":
            file_types[path] = "symlink"
        if status == b"T":
            sections.append(None)
        sections.append(path if path in added else None)

    section = -1
    old_left = new_left = line_number = 0
    patch_lines = patch.split(b"\n")
    for index, line in enumerate(patch_lines):
        if line == NO_NEWLINE:
            continue
        if old_left or new_left:
            prefix = line[:1]
            if prefix in (b"-", b" "):
                old_left -= 1
            if prefix in (b"+", b" "):
                if prefix == b"+" and sections[section] is not None:
                    payload = line[1:]
                    # Git adds a display LF to unterminated source lines.
                    if (payload.endswith(b"\r") and index + 1 < len(patch_lines)
                            and patch_lines[index + 1] != NO_NEWLINE):
                        payload = payload[:-1]
                    added[sections[section]][line_number] = payload
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
    return added, file_types


def introduced(base, top: bytes) -> tuple:
    """Each changed path maps to its added lines. None means the whole untracked file."""
    if base is None:
        head = checked_git(["rev-parse", "--verify", "--quiet", "origin/HEAD"], top,
                           "cannot resolve origin/HEAD (try --base <ref>)", allowed=(0, 1))
        base = "origin/HEAD" if head.returncode == 0 else "main"
    merge_base = checked_git(["merge-base", "--", base, "HEAD"], top,
                             f"cannot resolve the base {base} against HEAD (try --base <ref>)").stdout.strip()
    diff = checked_git(
        ["-c", "core.safecrlf=false", "diff", "-U0", "--find-renames", "--raw", "-z", "--patch",
         "--text", "--no-color", "--no-ext-diff", "--no-textconv", "--no-relative",
         "--inter-hunk-context=0",
         "--ignore-submodules=none", "--submodule=short", merge_base, "--"],
        top, f"cannot read the change against {os.fsdecode(merge_base)}",
    ).stdout
    added, file_types = added_from_diff(diff)
    untracked = checked_git(["ls-files", "--others", "--exclude-standard", "-z"], top,
                            "cannot enumerate untracked files").stdout
    if untracked:
        if not untracked.endswith(b"\0"):
            raise ScanError("incomplete Git untracked path list")
        for path in untracked[:-1].split(b"\0"):
            if not path:
                raise ScanError("empty path in Git untracked path list")
            added.setdefault(path.rstrip(b"/"), None)
    return added, file_types


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


def uses_hash_marker(name: str) -> bool:
    base = os.path.basename(name)
    return base in HASH_NAMES or os.path.splitext(base)[1].lower() in HASH_SUFFIXES


def comment_body(text: str, hash_marker: bool) -> str:
    """The text of a comment-only line with its marker removed."""
    if hash_marker:
        return text[1:].strip()
    if text.endswith("*/"):
        text = text[:-2]
    if text.startswith("//"):
        text = text.lstrip("/")
    elif text.startswith("/*"):
        text = text[2:].lstrip("*")
    elif text.startswith("*"):
        text = text[1:]
    return text.strip()


def comment_lines(lines: list, name: str, directives: tuple) -> list:
    """Pair each (number, text) line with its comment body, or None when the line is not comment-only.

    A /* block opened on a comment-only line makes the lines up to its */ comment-only. The block
    state resets at a gap in line numbers, because the lines between hunks are not visible."""
    hash_marker = uses_hash_marker(name)
    in_block = False
    previous = None
    result = []
    for number, line in lines:
        text = line.strip()
        if previous is None or number != previous + 1:
            in_block = False
        previous = number
        comment = False
        if hash_marker:
            comment = text.startswith("#") and not (number == 1 and text.startswith("#!"))
        elif in_block:
            comment = True
            in_block = "*/" not in text
        elif directive_body(line) in directives:
            comment = False
        elif text.startswith(("//", "/*", "*/")):
            comment = True
            in_block = text.startswith("/*") and text.rfind("/*") > text.rfind("*/")
        result.append((number, text, comment_body(text, hash_marker) if comment else None))
    return result


def looks_like_code(body: str) -> bool:
    if "://" in body or PROSE.match(body):
        return False
    if CODE_END.search(body) and "(" in body:
        return True
    if CODE_START.match(body) and (CODE_MARKS.search(body) or body.endswith(":")):
        return True
    return ASSIGNMENT.match(body) is not None or CALL.match(body) is not None


def runs_of(items: list, wanted) -> list:
    """Maximal runs of consecutive line numbers whose items satisfy wanted, as lists of items."""
    runs = []
    current = []
    for item in items:
        if wanted(item) and (not current or current[-1][0] == item[0] - 1):
            current.append(item)
            continue
        if current:
            runs.append(current)
        current = [item] if wanted(item) else []
    if current:
        runs.append(current)
    return runs


def sequence_hits(rule: dict, items: list) -> list:
    """Findings of a comment-block or commented-code rule as (line, excerpt) pairs."""
    if rule["kind"] == "comment-block":
        runs = runs_of(items, lambda item: item[2] is not None)
        return [(run[0][0], f"{len(run)} comment lines: {run[0][1]}"[:80])
                for run in runs if len(run) >= rule["min_lines"]]
    runs = runs_of(items, lambda item: item[2] is not None and looks_like_code(item[2]))
    return [(run[0][0], f"{len(run)} commented-out lines: {run[0][1]}"[:80]) for run in runs]


def parse_date(text: str):
    if not DATE_FORM.fullmatch(text):
        return None
    try:
        return datetime.date(int(text[:4]), int(text[5:7]), int(text[8:]))
    except ValueError:
        return None


def today_date():
    """PLUMB_TODAY (YYYY-MM-DD) when set and non-empty, else the local date; None when malformed."""
    text = os.environ.get("PLUMB_TODAY", "")
    return parse_date(text) if text else datetime.date.today()


def read_exceptions(spec: str, top: Path) -> tuple:
    """Return the active exception pairs, the expired rows and any error.

    Each row is rule<TAB>path<TAB>reason[<TAB>expires[<TAB>approved_by]]. A row whose expires
    is before today no longer suppresses and is reported as a finding.
    """
    full = spec if os.path.isabs(spec) else os.path.join(top, spec)
    if not os.path.isfile(full):
        return None, None, f"exceptions file {spec}: does not exist"
    try:
        with open(full, encoding="utf-8", errors="surrogateescape", newline="") as handle:
            rows = handle.read().replace("\r\n", "\n").split("\n")
    except OSError:
        return None, None, f"exceptions file {spec}: cannot be read"
    parsed = []
    for number, row in enumerate(rows, 1):
        if not row:
            continue
        fields = row.split("\t")
        where = f"exceptions file {spec}: line {number}: "
        if len(fields) < 3 or not all(field.strip() for field in fields[:3]):
            return None, None, where + "expected rule<TAB>path<TAB>reason with a non-empty reason"
        if len(fields) > 5:
            return None, None, where + "expected at most 5 columns: rule, path, reason, expires, approved_by"
        expires = parse_date(fields[3]) if len(fields) > 3 and fields[3] else None
        if len(fields) > 3 and fields[3] and expires is None:
            return None, None, where + "expected expires as a date, YYYY-MM-DD"
        if len(fields) > 4 and not fields[4].strip():
            return None, None, where + "expected a non-empty approved_by when the 5th column is present"
        parsed.append((fields[0], fields[1], expires))
    today = None
    if any(expires for _, _, expires in parsed):
        today = today_date()
        if today is None:
            return None, None, "PLUMB_TODAY: expected a date, YYYY-MM-DD"
    pairs: set = set()
    expired: set = set()
    for rule, path, expires in parsed:
        if expires is not None and expires < today:
            expired.add((rule, path, expires))
        else:
            pairs.add((rule, path))
    return pairs, sorted(expired, key=lambda row: (row[1], row[0], row[2])), None


def read_source(full: bytes, info: os.stat_result) -> bytes:
    # Guard against a symlink or FIFO replacing the regular file between lstat and open.
    fd = os.open(full, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        current = os.fstat(handle.fileno())
        if (not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)):
            raise ScanError("file changed type or identity before reading")
        return handle.read()


def scan(rules: list, added: dict, file_types: dict, top: bytes, scoped,
         exceptions: set, only_paths, directives: tuple, mode: str) -> list:
    """Report findings in path, line, and contract rule order."""
    found = []
    for path in sorted(added):
        name = os.fsdecode(path)
        if not scoped(name) or (only_paths is not None and name not in only_paths):
            continue
        full = os.path.join(top, path)
        kind = file_types.get(path)
        tracked_lines = added[path]
        try:
            if kind != "gitlink":
                info = os.lstat(full)
                if not stat.S_ISREG(info.st_mode):
                    kind = "symlink" if stat.S_ISLNK(info.st_mode) else "non-regular file"
            if kind:
                if mode == "enforce":
                    if ("non-regular", name) not in exceptions:
                        found.append({"rule": "non-regular", "path": name, "line": 0, "excerpt": kind})
                else:
                    print(f"skip: {kind} {name!r}", file=sys.stderr)
                continue
            if tracked_lines is None:
                raw = read_source(full, info)
                parts = raw.replace(b"\r\n", b"\n").split(b"\n")
                if parts[-1] == b"":
                    parts.pop()
                lines = enumerate(parts, 1)
            else:
                lines = sorted(tracked_lines.items())
        except (OSError, ScanError) as error:
            raise ScanError(f"cannot read source {name!r}: {error}") from error
        decoded = [(number, payload.decode("utf-8-sig" if number == 1 else "utf-8", errors="replace"))
                   for number, payload in lines]
        hits = []
        items = None
        for position, rule in enumerate(rules):
            if (rule["id"], name) in exceptions:
                continue
            if rule["kind"] in SEQUENCE_KINDS:
                if items is None:
                    items = comment_lines(decoded, name, directives)
                hits += [(number, position, excerpt) for number, excerpt in sequence_hits(rule, items)]
                continue
            for number, line in decoded:
                if rule["kind"] == "comment":
                    hit = comment_hit(line, directives)
                else:
                    hit = rule["regex"].search(line) is not None
                if hit:
                    hits.append((number, position, line.strip()[:80]))
        for number, position, excerpt in sorted(hits, key=lambda hit: hit[:2]):
            found.append({"rule": rules[position]["id"], "path": name, "line": number, "excerpt": excerpt})
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
        rule = {"id": item["id"], "kind": item["kind"], "regex": None, "min_lines": item.get("min_lines")}
        if item["kind"] == "pattern":
            rule["regex"] = re.compile(item["pattern"])
        rules.append(rule)
    directives = tuple(table.get("allow_directives", DEFAULT_DIRECTIVES))
    include = [pattern.split("/") for pattern in table.get("include", [])]
    exclude = [pattern.split("/") for pattern in table.get("exclude", [])]

    def scoped(path_: str) -> bool:
        parts = path_.split("/")
        if include and not any(glob_matches(parts, pattern) for pattern in include):
            return False
        return not any(glob_matches(parts, pattern) for pattern in exclude)

    only_paths = None
    if args["paths_from"] is not None:
        try:
            with open(args["paths_from"], encoding="utf-8", errors="surrogateescape", newline="") as handle:
                only_paths = set(handle.read().replace("\r\n", "\n").split("\n"))
        except OSError:
            usage_error("--paths-from needs a readable file")

    exceptions: set = set()
    expired: list = []
    if isinstance(table.get("exceptions"), str):
        policy_top = Path(path).parent.parent
        exceptions, expired, error = read_exceptions(table["exceptions"], policy_top)
        if error:
            return invalid_exit(error)

    try:
        top = checked_git(["rev-parse", "--show-toplevel"], args["worktree"],
                          "cannot find the worktree top level").stdout.removesuffix(b"\n")
        added, file_types = introduced(args["base"], top)
        findings = scan(rules, added, file_types, top, scoped, exceptions, only_paths, directives, mode)
        findings += [{"rule": "expired-exception", "path": row_path, "line": 0,
                      "excerpt": f"expired {expires.isoformat()}: {rule}"[:80]}
                     for rule, row_path, expires in expired]
    except (ScanError, OSError) as error:
        return invalid_exit(str(error))
    counts = {rule["id"]: 0 for rule in rules}
    for finding in findings:
        rule_id = finding["rule"]
        counts[rule_id] = counts.get(rule_id, 0) + 1
    outcome = "findings" if findings else "clean"

    if args["json"]:
        print(json.dumps({"schema": 1, "outcome": outcome, "findings": findings, "counts": counts}))
    else:
        if not findings:
            print("clean")
        for finding in findings:
            print(f"{finding['rule']}\t{finding['path']}:{finding['line']}\t{finding['excerpt']}")
        for rule_id, count in counts.items():
            print(f"summary: {rule_id} {count}")
        if findings:
            print(MOVE_NOTE)

    if findings and mode == "enforce":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
