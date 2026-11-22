#!/usr/bin/env python3
"""Report what a change newly introduces, against `[code_policy]` in the project contract.

    plumb-code-policy report [--base REF] [--json] [--paths-from FILE]

The contract is read with the same rules as `plumb-project`: no file (or no [code_policy]
table) is a visible skip with exit 0, a contract that does not validate is invalid (exit 2),
and a Python without tomllib is unavailable (exit 3). The rules themselves belong to the
project; this command only holds the comparator.

"Introduced" is a finding on a line that `git diff -U0 --no-renames <merge-base REF HEAD>`
marks as added, plus the uncommitted changes and untracked files in scope. Moved lines count
as added: a diff cannot tell a move from an introduction, so the report prints a note instead
of hiding the case. Report-only makes that acceptable; a project that wants findings to fail
the run sets mode = "enforce" and owns its exceptions file.

Standard library only. The comment kind is a lexer without a parser; its limits are documented
in docs/project-contract.md, not hidden.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE_LABEL = ".plumb/project.toml"
UNAVAILABLE_MESSAGE = "Python 3.11+ (tomllib) is required"
DEFAULT_DIRECTIVES = ("prettier-ignore",)
MOVE_NOTE = "note: moved lines count as added (known limitation)"
# Words after which a `/` opens a regex literal rather than a division. A lexer without a parser
# cannot always tell; this is the usual approximation and its misses are documented, not hidden.
REGEX_AFTER_WORDS = frozenset((
    "await", "case", "delete", "do", "else", "in", "instanceof", "new", "of", "return",
    "throw", "typeof", "void", "yield",
))
REGEX_AFTER_PUNCT = frozenset("([{,;=:?!&|^~+-*%<>")

USAGE = """usage: plumb-code-policy report [--base REF] [--json] [--paths-from FILE]

Reads [code_policy] in the project contract (the file `plumb-path project` prints) and reports
each finding on a line the change newly introduces. Run it inside the checkout.

  report             the only subcommand
  --base REF         compare against merge-base(REF, HEAD); the default is origin/HEAD's
                     target, else main
  --json             {"schema":1,"outcome":"clean|findings|skip","findings":[...],"counts":{...}}
  --paths-from FILE  look only at the repository-relative paths listed in FILE, one per line

Plain output is one line per finding, `rule<TAB>path:line<TAB>excerpt` (the excerpt is at most
80 characters), then `summary: <rule> <count>` for every rule, then a note that moved lines
count as added. A clean change prints `clean`; a contract without [code_policy] prints
`skip: no code_policy`.

The rules live in the contract, not here (docs/project-contract.md documents the table):

  [code_policy]
  mode = "report"               # off | report | enforce; report exits 0 even with findings,
                                # enforce exits 1 on findings
  include = ["src/**/*.ts"]     # globs from the repository top level; absent = every path
  exclude = ["**/*.test.*"]     # subtracted from include
  exceptions = ".plumb/code-policy-exceptions.tsv"   # rule<TAB>path<TAB>reason; a row with an
                                                    # empty reason is invalid
  [[code_policy.rule]]
  id = "no-new-comment"         # kind comment: //, /* */ and JSX {/* */} outside string,
  kind = "comment"              #   template and regex literals. Always allowed: license
                                #   headers in the first block of a file, /** ... */ directly
                                #   above an export, and lines that are only an
                                #   allow_directives entry (default: prettier-ignore)
  [[code_policy.rule]]
  id = "no-new-suppression"
  kind = "pattern"             # kind pattern: one finding per added line with a match
  pattern = '(eslint-disable)'

Exit status: 0 clean, skip or report-mode findings; 1 findings under mode = "enforce"; 2 an
invalid contract or exceptions file, an unresolvable base, or a usage error; 3 a Python
without tomllib.
"""


def usage_error(reason: str) -> None:
    print(f"plumb-code-policy: usage: {reason} (see --help)", file=sys.stderr)
    sys.exit(2)


def parse_args(argv: list) -> dict:
    args = {"base": None, "json": False, "paths_from": None}
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
        elif arg in ("--base", "--paths-from"):
            if index + 1 >= len(rest) or rest[index + 1].startswith("--"):
                usage_error(f"{arg} needs a value")
            args["base" if arg == "--base" else "paths_from"] = rest[index + 1]
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


def git(args: list, cwd: str = None):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except OSError:
        return None


# ---------------------------------------------------------------- the change

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


def added_from_diff(diff_text: str) -> dict:
    """path -> the set of new-side line numbers the unified diff marks as added. With -U0 a
    hunk holds only changes, so the new-side counter moves on context and `+` lines alone."""
    added: dict = {}
    path = None
    newline = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:]
            path = None if target == "/dev/null" else (target[2:] if target.startswith("b/") else target)
            in_hunk = False
            continue
        if raw.startswith("@@"):
            found = re.match(r"@@ -[0-9]+(?:,[0-9]+)? \+([0-9]+)(?:,[0-9]+)? @@", raw)
            in_hunk, newline = found is not None, (int(found.group(1)) if found else 0)
            continue
        if not in_hunk or path is None:
            continue
        if raw.startswith("+"):
            added.setdefault(path, set()).add(newline)
            newline += 1
        elif raw.startswith(" "):
            newline += 1
        # "-" lines and "\ No newline at end of file" do not move the new-side counter.
    return added


def untracked_paths(cwd: str) -> list:
    done = git(["ls-files", "--others", "--exclude-standard", "-z"], cwd)
    if done is None or done.returncode != 0:
        return []
    return [name for name in done.stdout.split("\0") if name]


def introduced(args: dict, top: str) -> tuple:
    """(path -> the set of newly introduced line numbers, error). The committed change is the
    diff from the merge base to HEAD, the uncommitted change the diff from HEAD to the worktree,
    and an untracked file in scope is introduced whole."""
    base = args["base"]
    if base is None:
        head = git(["rev-parse", "--verify", "--quiet", "origin/HEAD"], cwd=top)
        base = "origin/HEAD" if head is not None and head.returncode == 0 else "main"
    merged = git(["merge-base", base, "HEAD"], cwd=top)
    if merged is None or merged.returncode != 0 or not merged.stdout.strip():
        return None, f"cannot resolve the base {base} against HEAD (try --base <ref>)"
    merge_base = merged.stdout.strip()
    added: dict = {}
    for diff_args in ((merge_base, "HEAD"), ("HEAD",)):
        done = git(["diff", "-U0", "--no-renames", *diff_args], cwd=top)
        if done is None or done.returncode != 0:
            return None, f"cannot read the change against {diff_args[0]}"
        for path, numbers in added_from_diff(done.stdout).items():
            added.setdefault(path, set()).update(numbers)
    for path in untracked_paths(top):
        try:
            with open(os.path.join(top, path), "rb") as handle:
                raw = handle.read()
        except OSError:
            continue
        added.setdefault(path, set()).update(range(1, len(raw.decode("utf-8", "replace").splitlines()) + 1))
    return added, None


# ---------------------------------------------------------------- the comment lexer

class Lexed:
    """Which lines hold comments in C-family syntax, scanned token by token. Comment markers
    inside string, template and regex literals are ignored as far as a lexer without a parser
    can tell: a regex literal is told from a division by the previous significant token, an
    unterminated quoted literal ends at its line, and a template's `${...}` is not parsed."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.comment: set = set()   # 1-based line numbers holding comment text
        self.blocks: list = []       # {"start", "end", "doc"} spans of /* */ comments
        self._scan(text)

    @staticmethod
    def _opens_regex(last: tuple) -> bool:
        """A `/` after these opens a regex literal; after anything else it is a division."""
        kind = last[0]
        if kind is None:
            return True
        if kind == "word":
            return last[1] in REGEX_AFTER_WORDS
        if kind == "punct":
            return last[1] in REGEX_AFTER_PUNCT
        return False

    def _scan(self, text: str) -> None:
        size = len(text)
        index = 0
        line = 1
        state = "code"           # code | line | block | string | template | regex
        quote = ""
        in_class = False
        block_start = 0
        block_doc = False
        last: tuple = (None,)
        while index < size:
            char = text[index]
            if state == "code":
                if char == "\n":
                    line += 1
                    index += 1
                elif char in " \t\r":
                    index += 1
                elif char.isalpha() or char in "_$":
                    end = index + 1
                    while end < size and (text[end].isalnum() or text[end] in "_$"):
                        end += 1
                    last = ("word", text[index:end])
                    index = end
                elif char.isdigit():
                    end = index + 1
                    while end < size and (text[end].isalnum() or text[end] in "._"):
                        end += 1
                    last = ("num",)
                    index = end
                elif char in "\"'":
                    state, quote, last = "string", char, (None,)
                    index += 1
                elif char == "`":
                    state, quote, last = "template", char, (None,)
                    index += 1
                elif char == "/":
                    if text.startswith("//", index):
                        self.comment.add(line)
                        state = "line"
                        index += 2
                    elif text.startswith("/*", index):
                        self.comment.add(line)
                        block_start = line
                        block_doc = text.startswith("/**", index) and not text.startswith("/**/", index)
                        state = "block"
                        index += 2
                    elif self._opens_regex(last):
                        state, in_class = "regex", False
                        index += 1
                    else:
                        last = ("punct", char)
                        index += 1
                else:
                    last = ("punct", char)
                    index += 1
            elif state == "line":
                if char == "\n":
                    state = "code"
                    line += 1
                index += 1
            elif state == "block":
                if text.startswith("*/", index):
                    self.blocks.append({"start": block_start, "end": line, "doc": block_doc})
                    state = "code"
                    index += 2
                else:
                    if char == "\n":
                        line += 1
                        self.comment.add(line)
                    index += 1
            elif state in ("string", "template"):
                if char == "\\" and index + 1 < size:
                    if text[index + 1] == "\n":
                        line += 1
                    index += 2
                elif char == quote:
                    state, last = "code", ("str",)
                    index += 1
                else:
                    if char == "\n":
                        line += 1
                        if state == "string":      # a quoted literal does not span lines
                            state = "code"
                    index += 1
            else:  # regex
                if char == "\\" and index + 1 < size:
                    index += 2
                elif char == "\n":                  # an unterminated regex literal ends at its line
                    state = "code"
                    line += 1
                    index += 1
                elif char == "[":
                    in_class = True
                    index += 1
                elif char == "]":
                    in_class = False
                    index += 1
                elif char == "/" and not in_class:
                    state, last = "code", ("regex",)
                    index += 1
                else:
                    index += 1


def directive_body(line: str):
    """The text of a comment-only line with its markers removed, or None when the line holds
    anything but the comment."""
    text = line.strip()
    if text.startswith("//"):
        body = text[2:]
    elif text.startswith("/*") and text.endswith("*/") and len(text) >= 4:
        body = text[2:-2]
    elif text.startswith("*"):                     # a block-comment continuation line
        body = text[1:]
        if body.endswith("*/"):
            body = body[:-2]
    else:
        return None
    return body.strip()


def allowed_lines(lexed: Lexed, directives: tuple) -> set:
    """The lines the comment kind never reports: license headers in the first block of a file
    (a shebang line may sit above one), /** ... */ directly above an export, and lines that
    are only a tool directive."""
    stripped = [line.strip() for line in lexed.lines]
    allowed: set = set()
    total = len(stripped)
    first = 2 if total and stripped[0].startswith("#!") else 1
    if first <= total and stripped[first - 1].startswith("//"):
        runner = first
        while runner <= total and stripped[runner - 1].startswith("//"):
            allowed.add(runner)
            runner += 1
    if first <= total and stripped[first - 1].startswith("/*"):
        for block in lexed.blocks:
            if block["start"] == first and stripped[block["end"] - 1].endswith("*/"):
                allowed.update(range(block["start"], block["end"] + 1))
                break
    for block in lexed.blocks:
        after = block["end"] + 1
        if block["doc"] and after <= total and re.match(r"export\b", stripped[after - 1]):
            allowed.update(range(block["start"], block["end"] + 1))
    for number in sorted(lexed.comment):
        body = directive_body(lexed.lines[number - 1])
        if body is not None and body in directives:
            allowed.add(number)
    return allowed


# ---------------------------------------------------------------- the report

def read_exceptions(spec: str, top: str) -> tuple:
    """(pairs, error). A row is rule<TAB>path<TAB>reason and suppresses that rule in that path;
    a row whose reason is empty is invalid, and a configured file that is not there fails
    closed instead of suppressing nothing."""
    full = spec if os.path.isabs(spec) else os.path.join(top, spec)
    if not os.path.isfile(full):
        return None, f"exceptions file {spec}: does not exist"
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            rows = handle.read().splitlines()
    except OSError:
        return None, f"exceptions file {spec}: cannot be read"
    pairs: set = set()
    for number, row in enumerate(rows, 1):
        if not row.strip():
            continue
        fields = row.split("\t")
        if len(fields) != 3 or not all(field.strip() for field in fields):
            return None, (f"exceptions file {spec}: line {number}: "
                           "expected rule<TAB>path<TAB>reason with a non-empty reason")
        pairs.add((fields[0], fields[1]))
    return pairs, None


def scan(rules: list, added: dict, top: str, scoped, exceptions: set, only_paths, directives: tuple) -> list:
    """The findings, sorted by path, line, then rule order."""
    found = []
    for path in sorted(added):
        if not scoped(path) or (only_paths is not None and path not in only_paths):
            continue
        try:
            with open(os.path.join(top, path), "rb") as handle:
                raw = handle.read()
        except OSError:
            continue          # deleted or unreadable in the worktree: nothing to read
        if b"\0" in raw[:8192]:
            continue          # a binary file has no comment lines worth reporting
        lexed = Lexed(raw.decode("utf-8-sig", errors="replace"))
        allowed = allowed_lines(lexed, directives)
        numbers = sorted(number for number in added[path] if 1 <= number <= len(lexed.lines))
        for order, rule in enumerate(rules):
            if (rule["id"], path) in exceptions:
                continue
            for number in numbers:
                text = lexed.lines[number - 1]
                if rule["kind"] == "comment":
                    hit = number in lexed.comment and number not in allowed
                else:
                    hit = rule["regex"].search(text) is not None
                if hit:
                    found.append((path, number, order, rule["id"], text.strip()[:80]))
    found.sort(key=lambda row: (row[0], row[1], row[2]))
    return [{"rule": row[3], "path": row[0], "line": row[1], "excerpt": row[4]} for row in found]


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
    if not os.path.lexists(path):
        return skip_out(args, "no code_policy")
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
            try:
                rule["regex"] = re.compile(item["pattern"])
            except re.error:
                return invalid_exit(f"code_policy.rule {item['id']}: the pattern is not a regular expression")
        rules.append(rule)
    directives = tuple(table.get("allow_directives") or DEFAULT_DIRECTIVES)
    include = [glob_regex(pattern) for pattern in (table.get("include") or [])]
    exclude = [glob_regex(pattern) for pattern in (table.get("exclude") or [])]

    def scoped(path_: str) -> bool:
        if include and not any(regex.match(path_) for regex in include):
            return False
        return not any(regex.match(path_) for regex in exclude)

    only_paths = None
    if args["paths_from"] is not None:
        try:
            with open(args["paths_from"], encoding="utf-8") as handle:
                only_paths = {line.strip() for line in handle.read().splitlines() if line.strip()}
        except OSError:
            usage_error("--paths-from needs a readable file")

    top_run = git(["rev-parse", "--show-toplevel"])
    if top_run is None or top_run.returncode != 0:
        return invalid_exit("cannot find the repository top level (run inside the checkout)")
    top = top_run.stdout.strip()

    added, error = introduced(args, top)
    if error:
        return invalid_exit(error)

    exceptions: set = set()
    if isinstance(table.get("exceptions"), str):
        exceptions, error = read_exceptions(table["exceptions"], top)
        if error:
            return invalid_exit(error)

    findings = scan(rules, added, top, scoped, exceptions, only_paths, directives)
    counts = {rule["id"]: 0 for rule in rules}
    for finding in findings:
        counts[finding["rule"]] += 1
    outcome = "findings" if findings else "clean"

    if args["json"]:
        print(json.dumps({"schema": 1, "outcome": outcome, "findings": findings, "counts": counts}))
    elif findings:
        for finding in findings:
            print(f"{finding['rule']}\t{finding['path']}:{finding['line']}\t{finding['excerpt']}")
        for rule in rules:
            print(f"summary: {rule['id']} {counts[rule['id']]}")
        print(MOVE_NOTE)
    else:
        print("clean")

    if findings and mode == "enforce":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
