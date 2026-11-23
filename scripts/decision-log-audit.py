#!/usr/bin/env python3
"""Audit the evidence a decision log names. Reads only; writes nothing; calls no model.

    decision-log.sh <logfile> --audit [--repo DIR] [--all] [--no-remote] [--json]

Every commit, pull request and file mentioned in a cell is resolved by machine, never by trust:
a commit by `git cat-file`, a pull request by `gh pr view`, a file by the file system. A reference is
`resolved`, `missing`, or `unchecked` (no way to ask: --no-remote, no gh, a gh failure that is not
"not found", or no repository). Unchecked is never counted as resolved. Exit 1 when any is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

FILE_EXTENSIONS = (".md", ".py", ".sh", ".json", ".tsv", ".txt", ".log", ".html", ".toml", ".yml", ".yaml", ".png")
COMMIT = re.compile(r"(?<![0-9A-Za-z_])[0-9a-f]{7,40}(?![0-9A-Za-z_])")
PR_HASH = re.compile(r"(?<![0-9A-Za-z_&])#(\d+)(?![0-9A-Za-z_])")
PR_URL = re.compile(r"/pull/(\d+)(?![0-9A-Za-z_])")
LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")
NOT_FOUND = ("could not resolve to a pullrequest", "no pull requests found", "no pull request found", "not found")
GH_TIMEOUT = 30


def is_commit_token(token: str) -> bool:
    return bool(re.search(r"[a-f]", token)) and bool(re.search(r"[0-9]", token))


def trim(token: str) -> str:
    """Strip what surrounds a token in prose: the formula-neutralising quote, brackets, trailing punctuation."""
    token = re.sub(r"^'[=+@-]", "", token)  # decision-log.sh quotes a cell that starts like a formula
    token = token.lstrip("'\"`([<{")
    token = token.rstrip("'\"`)]>},;:.!?")
    return token


def file_candidate(raw: str) -> tuple[str, str] | None:
    """The path a whitespace-separated word names: ("file", path) when it ends in a known extension (a
    reference whether or not it exists), ("path", path) when it only contains a slash (a reference only
    when it exists, so "and/or" and "1200/940" are prose). None when it is neither."""
    if "://" in raw:
        return None
    token = LINE_SUFFIX.sub("", trim(raw))
    if not token or not re.search(r"[0-9A-Za-z]", token):
        return None
    if token.lower().endswith(FILE_EXTENSIONS):
        return "file", token
    if "/" in token:
        return "path", token
    return None


def references_in(cell: str) -> list[tuple[str, str]]:
    """(kind, token) pairs in one cell, in order of appearance, without repeats."""
    found: list[tuple[str, str]] = []
    blanked = cell
    for word in cell.split():
        candidate = file_candidate(word)
        if candidate is not None:
            found.append(candidate)
            if candidate[0] == "file":
                blanked = blanked.replace(word, " " * len(word), 1)  # a file name is not a commit hash
    for word in cell.split():
        if "://" in word and PR_URL.search(word):
            found.append(("pr", trim(word)))
            blanked = blanked.replace(word, " " * len(word), 1)
    for match in PR_HASH.finditer(blanked):
        found.append(("pr", match.group(0)))
    for match in COMMIT.finditer(blanked):
        if is_commit_token(match.group(0)):
            found.append(("commit", match.group(0)))
    seen: set[tuple[str, str]] = set()
    unique = []
    for ref in found:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def pr_number(token: str) -> str:
    match = PR_URL.search(token) or PR_HASH.search(token)
    return match.group(1)


class Resolver:
    def __init__(self, repo: str | None, logdir: str, remote: bool):
        self.repo = repo  # the git top level, or None when there is no repository
        self.logdir = logdir
        self.remote = remote
        self.cache: dict[tuple[str, str], str] = {}
        self.notes: set[str] = set()

    def resolve(self, kind: str, token: str) -> str:
        key = (kind, token)
        if key not in self.cache:
            self.cache[key] = getattr(self, f"_{kind}")(token)
        return self.cache[key]

    def _commit(self, token: str) -> str:
        if self.repo is None:
            self.notes.add("not in a git repository: commits are unchecked")
            return "unchecked"
        done = subprocess.run(["git", "-C", self.repo, "cat-file", "-e", f"{token}^{{commit}}"],
                              capture_output=True, stdin=subprocess.DEVNULL)
        return "resolved" if done.returncode == 0 else "missing"

    def origin_slug(self) -> str | None:
        done = subprocess.run(["git", "-C", self.repo, "remote", "get-url", "origin"], capture_output=True,
                              text=True, stdin=subprocess.DEVNULL)
        match = re.search(r"[:/]([^/:]+/[^/:]+?)(?:\.git)?/?$", done.stdout.strip()) if done.returncode == 0 else None
        return match.group(1).lower() if match else None

    def _pr(self, token: str) -> str:
        if not self.remote:
            return "unchecked"
        if self.repo is None:
            self.notes.add("not in a git repository: pull requests are unchecked")
            return "unchecked"
        if "://" in token:
            url = re.search(r"://[^/]+/([^/]+/[^/]+)/pull/\d+", token)
            if url is None or url.group(1).lower() != self.origin_slug():
                self.notes.add("a pull request URL names a repository other than origin (or origin is unknown): unchecked")
                return "unchecked"
        if shutil.which("gh") is None:
            self.notes.add("gh is not on PATH: pull requests are unchecked")
            return "unchecked"
        try:
            done = subprocess.run(["gh", "pr", "view", pr_number(token), "--json", "number"], cwd=self.repo,
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=GH_TIMEOUT,
                                  env={**os.environ, "GH_PROMPT_DISABLED": "1"})
        except (OSError, subprocess.TimeoutExpired) as error:
            self.notes.add(f"gh could not be run ({type(error).__name__}): pull requests are unchecked")
            return "unchecked"
        if done.returncode == 0:
            return "resolved"
        message = (done.stderr + done.stdout).lower()
        if any(phrase in message for phrase in NOT_FOUND):
            return "missing"
        self.notes.add("gh failed for a reason other than not found (auth or network): those pull requests are unchecked")
        return "unchecked"

    def _file(self, token: str) -> str:
        # As given (relative to where the audit runs), then the repository, then the log's own directory.
        paths = [token] + [os.path.join(base, token) for base in (self.repo, self.logdir) if base]
        return "resolved" if any(os.path.exists(path) for path in paths) else "missing"


def git_top(directory: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", directory, "rev-parse", "--show-toplevel"], capture_output=True,
                              text=True, stdin=subprocess.DEVNULL)
    except OSError:
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="decision-log.sh <logfile> --audit", add_help=True)
    parser.add_argument("logfile")
    parser.add_argument("--repo", metavar="DIR")
    parser.add_argument("--all", action="store_true", help="audit the whole file, not only after the last start row")
    parser.add_argument("--no-remote", action="store_true", help="do not ask the forge: pull requests are unchecked")
    parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return 0 if stop.code in (0, None) else 2

    try:
        with open(args.logfile, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError as error:
        print(f"cannot read {args.logfile}: {error.strerror or error}", file=sys.stderr)
        return 2
    if not lines:
        print(f"{args.logfile} is empty: no header", file=sys.stderr)
        return 2

    if args.repo is not None and not os.path.isdir(args.repo):
        print(f"--repo {args.repo} is not a directory", file=sys.stderr)
        return 2
    repo = git_top(args.repo if args.repo is not None else os.getcwd())
    logdir = os.path.dirname(os.path.abspath(args.logfile))
    resolver = Resolver(repo, logdir, remote=not args.no_remote)

    header = lines[0].split("\t")
    rows = [(number, line.split("\t")) for number, line in enumerate(lines[1:], start=2) if line.strip()]
    is_start = [len(cells) > 1 and cells[1] == "start" for _, cells in rows]
    first = 0
    if not args.all:
        for index in range(len(rows) - 1, -1, -1):
            if is_start[index]:
                first = index + 1
                break

    references = []
    without = 0
    for index in range(first, len(rows)):
        if is_start[index]:
            continue  # a boundary, not evidence
        number, cells = rows[index]
        count = 0
        for column, cell in enumerate(cells):
            if column == 0:
                continue  # ts is written by the tool
            name = header[column] if column < len(header) else f"col{column}"
            for kind, token in references_in(cell):
                if kind == "path":
                    if resolver.resolve("file", token) != "resolved":
                        continue  # a slash alone, with nothing there, is prose
                    kind = "file"
                references.append({"line": number, "column": name, "kind": kind, "token": token,
                                   "status": resolver.resolve(kind, token)})
                count += 1
        if count == 0:
            without += 1

    counts = {"references": len(references)}
    for status in ("resolved", "missing", "unchecked"):
        counts[status] = sum(1 for ref in references if ref["status"] == status)

    if args.json:
        print(json.dumps({"schema": 1, "references": references, "counts": counts,
                          "rows_without_reference": without}, ensure_ascii=False))
    else:
        for ref in references:
            print("\t".join([str(ref["line"]), ref["column"], ref["kind"], ref["token"], ref["status"]]))
        print(f"audit: {counts['references']} references, {counts['resolved']} resolved, "
              f"{counts['missing']} missing, {counts['unchecked']} unchecked")
        print(f"rows without evidence: {without}")
    for note in sorted(resolver.notes):
        print(f"note: {note}", file=sys.stderr)
    return 1 if counts["missing"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
