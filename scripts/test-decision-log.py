#!/usr/bin/env python3
"""Regression suite for `plumb-decision-log --start` and `--audit`, on a throwaway repository only.

    python3 -B scripts/test-decision-log.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline under tempfile.mkdtemp():
git is a real repository built here, the forge is a fake `gh` program placed first on PATH, and every
name and path is made up.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "decision-log.sh"
AUDIT = HERE / "decision-log-audit.py"
_spec = importlib.util.spec_from_file_location("decision_log_audit", AUDIT)
audit_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit_tool)
ROOT = Path(tempfile.mkdtemp(prefix="plumb-decision-log-test-"))
FAILED: list[str] = []
_counter = [0]
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def case(name: str):
    def wrap(fn):
        try:
            fn()
        except AssertionError as error:
            FAILED.append(name)
            print(f"  NG   {name}: {error}")
        except Exception:  # noqa: BLE001 - a crashing case is a failing case
            FAILED.append(name)
            print(f"  NG   {name}: crashed\n{traceback.format_exc()}")
        else:
            print(f"  ok   {name}")
        return fn
    return wrap


# ---------------------------------------------------------------- scaffolding

def fresh(label: str) -> Path:
    _counter[0] += 1
    path = ROOT / f"{_counter[0]:02d}-{label}"
    path.mkdir()
    return path


GIT_ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t",
                           "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, env=GIT_ENV, check=True)
    return done.stdout.strip()


def make_repo() -> tuple[Path, str]:
    """A real repository with one commit whose 7-character hash holds both a letter and a digit."""
    repo = fresh("repo")
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin", "https://example.invalid/org/repo.git")
    for attempt in range(40):
        (repo / "kept.txt").write_text(f"made up {attempt}\n")
        git(repo, "add", "kept.txt")
        git(repo, "commit", "-q", "--allow-empty", "-m", f"first {attempt}")
        short = git(repo, "rev-parse", "--short=7", "HEAD")
        if re.search(r"[a-f]", short) and re.search(r"[0-9]", short):
            return repo, short
    raise AssertionError("could not make a commit hash with a letter and a digit")


REPO, SHA = make_repo()
UNKNOWN_SHA = "deadbee1"

FAKE_GH = """#!/bin/sh
# made-up forge: pull request 7 exists, 404 does not, 500 fails like a network error
[ -n "$FAKE_GH_CALLS" ] && echo "$@" >> "$FAKE_GH_CALLS"
[ "$1" = "pr" ] && [ "$2" = "view" ] || { echo "unexpected: $*" >&2; exit 2; }
case "$3" in
  7) echo '{"number":7}'; exit 0 ;;
  404) echo "GraphQL: Could not resolve to a PullRequest with the number of 404. (repository.pullRequest)" >&2; exit 1 ;;
  *) echo "error connecting to forge.invalid" >&2; exit 1 ;;
esac
"""
GH_DIR = fresh("fake-gh")
(GH_DIR / "gh").write_text(FAKE_GH)
(GH_DIR / "gh").chmod(0o755)
GH_CALLS = GH_DIR / "calls.txt"

# a PATH that holds git and nothing that could be gh
NO_GH_DIR = fresh("no-gh")
os.symlink(shutil.which("git"), NO_GH_DIR / "git")


def run(*args: str, cwd: Path | None = None, with_gh: bool = True) -> subprocess.CompletedProcess:
    """decision-log.sh with a fake gh first on PATH. with_gh=False runs the audit with no gh anywhere."""
    env = {**GIT_ENV, "FAKE_GH_CALLS": str(GH_CALLS)}
    if with_gh:
        env["PATH"] = f"{GH_DIR}{os.pathsep}{os.environ['PATH']}"
        command = ["bash", str(SCRIPT), *args]
    else:
        env["PATH"] = str(NO_GH_DIR)
        # --audit is `exec python3 decision-log-audit.py`, so call that directly and keep PATH gh-free
        assert args[1] == "--audit"
        command = [sys.executable, "-B", str(AUDIT), args[0], *args[2:]]
    return subprocess.run(command, capture_output=True, text=True, cwd=str(cwd or ROOT), env=env)


def log_with(rows: list[list[str]], header: tuple[str, ...] = ("id", "did", "evidence"), where: Path | None = None) -> Path:
    """A log written through the tool itself, so the cells are exactly what a run would leave."""
    log = (where or fresh("log")) / "run.tsv"
    done = run(str(log), "--header", *header)
    assert done.returncode == 0, done.stderr
    for row in rows:
        done = run(str(log), *row)
        assert done.returncode == 0, done.stderr
    return log


def audit(log: Path, *flags: str, cwd: Path | None = None, with_gh: bool = True) -> subprocess.CompletedProcess:
    return run(str(log), "--audit", "--repo", str(REPO), *flags, cwd=cwd, with_gh=with_gh)


def refs(done: subprocess.CompletedProcess) -> list[list[str]]:
    return [line.split("\t") for line in done.stdout.splitlines() if line.count("\t") == 4]


def statuses(done: subprocess.CompletedProcess) -> dict[str, str]:
    return {fields[3]: fields[4] for fields in refs(done)}


# ---------------------------------------------------------------- --start

@case("--start writes ts, the literal start, the label, and empty cells for the rest")
def _():
    log = log_with([], header=("id", "did", "why", "evidence"))
    done = run(str(log), "--start", "second run")
    assert done.returncode == 0, done.stderr
    lines = log.read_text().splitlines()
    assert len(lines) == 2, lines
    cells = lines[1].split("\t")
    assert TS.match(cells[0]), cells
    assert cells[1:] == ["start", "second run", "", ""], cells
    assert len(cells) == len(lines[0].split("\t")), "the row must have as many cells as the header"


@case("--start with exactly two caller columns fills no extra cells")
def _():
    log = log_with([], header=("a", "b"))
    assert run(str(log), "--start", "r1").returncode == 0
    assert log.read_text().splitlines()[1].split("\t")[1:] == ["start", "r1"]


@case("--start without a header exits 1, says so, and creates no file")
def _():
    log = fresh("noheader") / "run.tsv"
    done = run(str(log), "--start", "r1")
    assert done.returncode == 1, done.returncode
    assert "no header" in done.stderr, done.stderr
    assert not log.exists(), "a run boundary must not conjure a log"


@case("--start on a one-column header exits 1 and writes nothing")
def _():
    log = log_with([], header=("only",))
    before = log.read_text()
    done = run(str(log), "--start", "r1")
    assert done.returncode == 1 and "at least 2" in done.stderr, (done.returncode, done.stderr)
    assert log.read_text() == before


@case("--start neutralises a formula label like any other cell")
def _():
    log = log_with([])
    assert run(str(log), "--start", "=SUM(1)").returncode == 0
    assert log.read_text().splitlines()[1].split("\t")[2] == "'=SUM(1)"


# ---------------------------------------------------------------- --audit: commits and files

@case("a commit in the repository resolves; one that is not there is missing; exit 1")
def _():
    log = log_with([["1", "did a thing", f"fixed at {SHA}"], ["2", "did another", f"fixed at {UNKNOWN_SHA}"]])
    done = audit(log)
    assert done.returncode == 1, (done.returncode, done.stdout)
    assert statuses(done) == {SHA: "resolved", UNKNOWN_SHA: "missing"}, done.stdout
    first = refs(done)[0]
    assert first[:3] == ["2", "evidence", "commit"], first  # line 2 is the first data row
    assert "audit: 2 references, 1 resolved, 1 missing, 0 unchecked" in done.stdout, done.stdout


@case("only resolved references: exit 0")
def _():
    log = log_with([["1", "did a thing", f"fixed at {SHA}."]])
    done = audit(log)
    assert done.returncode == 0, (done.returncode, done.stdout)
    assert statuses(done) == {SHA: "resolved"}


@case("a word of hex without a digit, or without a letter, is not a commit")
def _():
    log = log_with([["1", "decade", "deadbeef and 1234567 and 123456"], ["2", "real", f"fixed at {SHA} and {UNKNOWN_SHA}"]])
    done = audit(log)
    assert statuses(done) == {SHA: "resolved", UNKNOWN_SHA: "missing"}, done.stdout
    assert "audit: 2 references" in done.stdout and "rows without evidence: 1" in done.stdout, done.stdout


@case("a file resolves relative to the working directory, the repository and the log's directory")
def _():
    where = fresh("cwd")
    logdir = fresh("logdir")
    (where / "only-cwd.md").write_text("x")
    (REPO / "only-repo.md").write_text("x")
    (logdir / "only-log.md").write_text("x")
    (logdir / "sub").mkdir()
    (logdir / "sub" / "nested.txt").write_text("x")
    absolute = REPO / "kept.txt"
    log = log_with([["1", "read", "only-cwd.md only-repo.md only-log.md sub/nested.txt nowhere.md missing/dir/x"],
                    ["2", "abs", str(absolute)]], where=logdir)
    done = audit(log, cwd=where)
    got = statuses(done)
    assert "missing/dir/x" not in got, "a slash-only word that is not there is prose, not a reference"
    assert got == {"only-cwd.md": "resolved", "only-repo.md": "resolved", "only-log.md": "resolved",
                   "sub/nested.txt": "resolved", "nowhere.md": "missing",
                   str(absolute): "resolved"}, got
    assert done.returncode == 1


@case("a file word with surrounding prose punctuation or a :line suffix still resolves")
def _():
    log = log_with([["1", "read", "(see kept.txt), then kept.txt:12 and `kept.txt`."]])
    done = audit(log)
    assert statuses(done) == {"kept.txt": "resolved"}, done.stdout
    assert len(refs(done)) == 1, "the same token in one cell is reported once"
    # each wrapped form alone in its own row, so the line suffix cannot rescue a word the trimming should have cleaned
    forms = ["(see kept.txt),", "`kept.txt`.", "<kept.txt>", '"kept.txt";', "kept.txt:12-14,", "(`kept.txt`)", "ghost-nowhere.md)."]
    done = audit(log_with([[str(n), "read", form] for n, form in enumerate(forms, 1)]))
    assert [(r[0], r[3], r[4]) for r in refs(done)] == \
        [(str(n + 2), "kept.txt", "resolved") for n in range(6)] + [("8", "ghost-nowhere.md", "missing")], done.stdout


@case("a markdown link yields its target as the token and its text as ordinary words; wrapping punctuation is stripped")
def _():
    refs_in = audit_tool.references_in
    assert refs_in("[the scope](docs/scope.md)") == [("file", "docs/scope.md")]
    assert refs_in("see [kept.txt](docs/scope.md) now") == [("file", "kept.txt"), ("file", "docs/scope.md")]
    assert refs_in("[text](docs/scope.md).") == [("file", "docs/scope.md")]
    assert refs_in("[PR](https://example.invalid/org/repo/pull/7)") == [("pr", "https://example.invalid/org/repo/pull/7")]
    assert refs_in("[a](<docs/x.md>) and [b]( docs/y.md )") == [("file", "docs/x.md"), ("file", "docs/y.md")]
    for wrapped in ("`docs/x.md`", "(docs/x.md)", "<docs/x.md>", "docs/x.md,", "docs/x.md.", "\"docs/x.md\"", "'docs/x.md'", "(`docs/x.md`),",
                    "**docs/x.md**", "docs/x.md:", "docs/x.md;", "[docs/x.md]", "(see docs/x.md)", "docs/x.md:12,"):
        assert refs_in(wrapped) == [("file", "docs/x.md")], (wrapped, refs_in(wrapped))
    assert refs_in("and/or 1200/940") == [("path", "and/or"), ("path", "1200/940")], "a bare slash word stays a candidate path"
    log = log_with([["1", "read", "[the scope](docs/scope.md) and [kept.txt](docs/other.md)."]])
    done = audit(log)
    assert statuses(done) == {"docs/scope.md": "missing", "kept.txt": "resolved", "docs/other.md": "missing"}, done.stdout
    (REPO / "docs").mkdir(exist_ok=True)
    (REPO / "docs" / "scope.md").write_text("x")
    assert statuses(audit(log))["docs/scope.md"] == "resolved", "the link target is looked up as a path, not as `text](docs/scope.md`"


@case("words with a slash and no known extension are references only when the path exists")
def _():
    where = fresh("slashes")
    (where / "plain-dir").mkdir()
    (where / "plain-dir" / "noext").write_text("x")
    log = log_with([["1", "prose", "and/or 1200/940 yes/no"], ["2", "paths", "plain-dir plain-dir/noext plain-dir/ghost"]],
                   where=where)
    done = audit(log, cwd=where)
    assert statuses(done) == {"plain-dir/noext": "resolved"}, done.stdout  # "plain-dir" has no slash: not a path word
    assert done.returncode == 0, "prose with a slash must never turn the exit code to 1"
    done = audit(log, cwd=where, with_gh=False)
    assert "and/or" not in done.stdout and "1200/940" not in done.stdout, done.stdout
    where2 = fresh("slashes2")
    (where2 / "a" / "b").mkdir(parents=True)
    log2 = log_with([["1", "dir", "see a/b and also and/or"]], where=where2)
    done = audit(log2, cwd=where2)
    assert statuses(done) == {"a/b": "resolved"}, done.stdout
    assert "rows without evidence: 0" in done.stdout, done.stdout


@case("a word that ends in a known extension is a reference even when nothing is there")
def _():
    log = log_with([["1", "did", "x/y.md only.json kept.txt"]])
    done = audit(log)
    assert statuses(done) == {"x/y.md": "missing", "only.json": "missing", "kept.txt": "resolved"}, done.stdout
    assert done.returncode == 1


@case("a URL is not a file")
def _():
    log = log_with([["1", "read", "https://example.invalid/some/page.html kept.txt"]])
    done = audit(log)
    assert statuses(done) == {"kept.txt": "resolved"}, done.stdout


@case("a formula-neutralised cell (leading quote) is still audited")
def _():
    log = log_with([["1", "did", f"+{SHA}"], ["2", "did", "@kept.txt"], ["3", "did", "-nowhere.md"]])
    cells = [line.split("\t")[3] for line in log.read_text().splitlines()[1:]]
    assert all(cell.startswith("'") for cell in cells), cells
    done = audit(log)
    assert statuses(done) == {SHA: "resolved", "kept.txt": "resolved", "nowhere.md": "missing"}, done.stdout
    assert done.returncode == 1


# ---------------------------------------------------------------- --audit: pull requests

@case("a pull request resolves through gh, as #N and as a /pull/N URL")
def _():
    GH_CALLS.write_text("")
    log = log_with([["1", "merged", "#7"], ["2", "merged", "https://example.invalid/org/repo/pull/7"]])
    done = audit(log)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert statuses(done) == {"#7": "resolved", "https://example.invalid/org/repo/pull/7": "resolved"}, done.stdout
    assert GH_CALLS.read_text().split("\n")[0] == "pr view 7 --json number", GH_CALLS.read_text()


@case("a pull request URL of another repository than origin is unchecked and gh is not asked")
def _():
    GH_CALLS.write_text("")
    log = log_with([["1", "merged", "https://example.invalid/other/thing/pull/7"]])
    done = audit(log)
    assert statuses(done) == {"https://example.invalid/other/thing/pull/7": "unchecked"}, done.stdout
    assert GH_CALLS.read_text() == "", "gh must not be asked about another repository's number"
    done = audit(log_with([["1", "merged", "https://example.invalid/org/repo/pull/7"]]))
    assert statuses(done) == {"https://example.invalid/org/repo/pull/7": "resolved"}, "origin's own repository is asked"
    assert done.returncode == 0


@case("a pull request URL that matches origin ignoring case and the .git suffix is checked")
def _():
    GH_CALLS.write_text("")
    log = log_with([["1", "merged", "https://example.invalid/ORG/Repo/pull/7 https://example.invalid/ORG/Repo/pull/404"]])
    done = audit(log)
    assert statuses(done) == {"https://example.invalid/ORG/Repo/pull/7": "resolved",
                              "https://example.invalid/ORG/Repo/pull/404": "missing"}, done.stdout


def repo_with_origin(url: str) -> Path:
    repo = fresh("origin-repo")
    git(repo, "init", "-q")
    if url:
        git(repo, "remote", "add", "origin", url)
    return repo


def pr_status(origin: str, token: str) -> tuple[str, str]:
    """(status of `token`, what the fake gh was asked) for a repository whose origin is `origin`."""
    GH_CALLS.write_text("")
    log = log_with([["1", "merged", token]])
    done = run(str(log), "--audit", "--repo", str(repo_with_origin(origin)))
    return statuses(done)[token], GH_CALLS.read_text()


@case("a pull request URL is checked only when host and owner/name both match origin; another host is unchecked, gh is not asked")
def _():
    at = chr(64)
    token = "https://example.invalid/org/repo/pull/7"
    other_host = "https://other.invalid/org/repo/pull/7"
    for origin in ("https://example.invalid/org/repo.git", "https://example.invalid/org/repo", "https://EXAMPLE.invalid/Org/Repo.git",
                   "https://user:pw" + at + "example.invalid/org/repo.git", "ssh://git" + at + "example.invalid:2222/org/repo.git",
                   "ssh://git" + at + "example.invalid/org/repo.git", "git" + at + "example.invalid:org/repo.git",
                   "git" + at + "EXAMPLE.invalid:Org/Repo"):
        status, asked = pr_status(origin, token)
        assert (status, asked.split("\n")[0]) == ("resolved", "pr view 7 --json number"), (origin, status, asked)
        status, asked = pr_status(origin, "https://Example.Invalid/ORG/repo/pull/7")
        assert (status, asked.split("\n")[0]) == ("resolved", "pr view 7 --json number"), (origin, "host case", status, asked)
        status, asked = pr_status(origin, other_host)
        assert (status, asked) == ("unchecked", ""), (origin, status, asked)
        status, asked = pr_status(origin, "https://example.invalid/org/other/pull/7")
        assert (status, asked) == ("unchecked", ""), (origin, "other name", status, asked)
    for origin in ("", "not a url", "https://example.invalid/just-one-segment"):
        assert pr_status(origin, token) == ("unchecked", ""), origin
    status, asked = pr_status("git" + at + "example.invalid:org/repo.git", "#7")
    assert (status, asked.split("\n")[0]) == ("resolved", "pr view 7 --json number"), "a bare #7 still goes to gh"


@case("a pull request gh says it cannot find is missing")
def _():
    log = log_with([["1", "merged", "(#404) #7"]])
    done = audit(log)
    assert statuses(done) == {"#404": "missing", "#7": "resolved"}, done.stdout
    assert done.returncode == 1


@case("a gh failure that is not 'not found' leaves the pull request unchecked, never resolved")
def _():
    log = log_with([["1", "merged", "#500 #7"]])
    done = audit(log)
    assert statuses(done) == {"#500": "unchecked", "#7": "resolved"}, done.stdout
    assert done.returncode == 0
    assert "unchecked" in done.stdout.splitlines()[-2], done.stdout


@case("no gh on PATH: pull requests are unchecked, and commits and files are still checked")
def _():
    log = log_with([["1", "merged", f"#7 {SHA} {UNKNOWN_SHA}"]])
    done = audit(log, with_gh=False)
    assert statuses(done) == {"#7": "unchecked", SHA: "resolved", UNKNOWN_SHA: "missing"}, done.stdout
    assert "gh is not on PATH" in done.stderr, done.stderr
    assert done.returncode == 1


@case("--no-remote: pull requests are unchecked and gh is never called")
def _():
    GH_CALLS.write_text("")
    log = log_with([["1", "merged", "#7 #404"]])
    done = audit(log, "--no-remote")
    assert statuses(done) == {"#7": "unchecked", "#404": "unchecked"}, done.stdout
    assert GH_CALLS.read_text() == "", "gh must not be called under --no-remote"
    assert done.returncode == 0
    assert statuses(audit(log)) == {"#7": "resolved", "#404": "missing"}, "without --no-remote the same log is asked"


@case("outside a repository commits and pull requests are unchecked, files are still checked")
def _():
    where = fresh("norepo")
    log = log_with([["1", "did", f"{SHA} #7 {where.name} run.tsv nowhere.md"]], where=where)
    env = {**GIT_ENV, "PATH": f"{GH_DIR}{os.pathsep}{os.environ['PATH']}", "GIT_CEILING_DIRECTORIES": str(ROOT)}
    done = subprocess.run(["bash", str(SCRIPT), str(log), "--audit"], capture_output=True, text=True, cwd=str(where), env=env)
    got = statuses(done)
    assert got[SHA] == "unchecked" and got["#7"] == "unchecked", done.stdout
    assert got["run.tsv"] == "resolved" and got["nowhere.md"] == "missing", done.stdout
    assert done.returncode == 1


# ---------------------------------------------------------------- --audit: scope, output, safety

@case("the audit covers the rows after the last start row; --all covers the whole file")
def _():
    log = log_with([["1", "old run", f"gone {UNKNOWN_SHA}"]])
    assert run(str(log), "--start", "second").returncode == 0
    assert run(str(log), "2", "ok", SHA).returncode == 0
    assert run(str(log), "--start", "third").returncode == 0
    assert run(str(log), "3", "ok", "kept.txt").returncode == 0
    scoped = audit(log)
    assert statuses(scoped) == {"kept.txt": "resolved"}, scoped.stdout
    assert scoped.returncode == 0, scoped.stdout
    assert refs(scoped)[0][0] == "6", refs(scoped)  # file line numbers, header is line 1
    whole = audit(log, "--all")
    assert statuses(whole) == {UNKNOWN_SHA: "missing", SHA: "resolved", "kept.txt": "resolved"}, whole.stdout
    assert whole.returncode == 1


@case("a log with no start row is audited whole; a start row with nothing after it audits nothing")
def _():
    log = log_with([["1", "did", f"x {UNKNOWN_SHA} {SHA}"]])
    done = audit(log)
    assert done.returncode == 1 and statuses(done) == {UNKNOWN_SHA: "missing", SHA: "resolved"}, done.stdout
    assert run(str(log), "--start", "empty run").returncode == 0
    done = audit(log)
    assert done.returncode == 0 and "audit: 0 references" in done.stdout and "rows without evidence: 0" in done.stdout, done.stdout


@case("rows without any reference are counted; start rows are not rows")
def _():
    log = log_with([["1", "thought about it", "-"], ["2", "ran it", f"{SHA}"], ["3", "again", "1200"]])
    assert run(str(log), "--start", "x").returncode == 0
    assert run(str(log), "4", "no evidence", "-").returncode == 0
    assert "rows without evidence: 3" in audit(log, "--all").stdout
    assert "rows without evidence: 1" in audit(log).stdout


@case("--json prints schema, references, counts and rows_without_reference")
def _():
    log = log_with([["1", "did", f"{SHA} {UNKNOWN_SHA} kept.txt"], ["2", "idle", "-"]])
    done = audit(log, "--json")
    assert done.returncode == 1
    doc = json.loads(done.stdout)
    assert set(doc) == {"schema", "references", "counts", "rows_without_reference"}, sorted(doc)
    assert doc["schema"] == 1 and doc["rows_without_reference"] == 1, doc
    assert doc["counts"] == {"references": 3, "resolved": 2, "missing": 1, "unchecked": 0}, doc["counts"]
    assert {r["token"] for r in doc["references"]} == {SHA, UNKNOWN_SHA, "kept.txt"}, doc
    assert {r["line"] for r in doc["references"]} == {2} and {r["column"] for r in doc["references"]} == {"evidence"}, doc
    assert all(set(r) == {"line", "column", "kind", "token", "status"} for r in doc["references"]), doc["references"]


@case("the audit writes nothing and creates nothing")
def _():
    log = log_with([["1", "did", f"{SHA}"]])
    before = log.read_bytes()
    assert audit(log).returncode == 0 and statuses(audit(log)) == {SHA: "resolved"}
    assert audit(log, "--json").returncode == 0
    assert log.read_bytes() == before
    ghost = fresh("ghost") / "deeper" / "run.tsv"
    done = run(str(ghost), "--audit")
    assert done.returncode == 2, done.returncode
    assert not ghost.parent.exists(), "an audit of a log that is not there must not create its directory"


@case("--help documents both new modes")
def _():
    done = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert done.returncode == 0 and "--start" in done.stdout and "--audit" in done.stdout, done.stdout


# ---------------------------------------------------------------- done

shutil.rmtree(ROOT, ignore_errors=True)
print()
if FAILED:
    print(f"{len(FAILED)} case(s) NG: {', '.join(FAILED)}")
    sys.exit(1)
print("all cases ok")
