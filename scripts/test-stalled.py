#!/usr/bin/env python3
"""Regression suite for `plumb-stalled`, on synthetic pull requests and a synthetic forge only.

    python3 -B scripts/test-stalled.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline under tempfile.mkdtemp():
the forge is a function here (or a missing program), git is a real repository built here, and every title,
author, branch and URL is made up. The clock is the `now` argument, never the machine's.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(HERE))
import stalled  # noqa: E402

BIN = PLUGIN / "bin" / "plumb-stalled"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-stalled-test-"))
FAILED: list[str] = []
NOW = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
PATTERN = re.compile(r"verified at ([0-9a-f]{7,40})")
HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
OTHER = "ffffffffffffffffffffffffffffffffffffffff"
_counter = [0]


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

def ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def commit(hours_ago: float, parents: int = 1, oid: str = "c0ffee0") -> dict:
    return {"commit": {"oid": oid, "committedDate": ago(hours_ago), "parents": {"totalCount": parents}}}


def raw_pr(number: int = 1, draft: bool = True, commits: list | None = None, created: float = 100, body: str = "",
           head: str = HEAD, ready: float | None = None, base: str = "main", author: str = "alice") -> dict:
    return {"number": number, "title": f"pull request {number}", "url": f"https://example.invalid/pull/{number}",
            "isDraft": draft, "createdAt": ago(created), "headRefName": f"branch-{number}", "headRefOid": head,
            "baseRefName": base, "body": body, "author": {"login": author},
            "commits": {"nodes": commits if commits is not None else [commit(1)]},
            "timelineItems": {"nodes": [] if ready is None else [{"createdAt": ago(ready)}]}}


def row_of(raw: dict, idle: float = 2.0, pattern=PATTERN) -> dict:
    doc = stalled.build([raw], NOW, idle, pattern)
    assert len(doc["open"]) == 1, doc
    return doc["open"][0]


def merged_node(number: int, oid: str, hours_ago: float, author: str = "bob") -> dict:
    return {"number": number, "title": f"merged {number}", "mergedAt": ago(hours_ago), "author": {"login": author},
            "mergeCommit": {"oid": oid} if oid else None}


class FakeGh:
    """A forge in a function: `gh repo view` and `gh api graphql` (open, or merged when the query says MERGED)."""

    def __init__(self, open_prs: list[dict] | None = None, merged: list[dict] | None = None, default: str = "main",
                 fail: str | None = None, has_next: bool = False):
        self.open_prs, self.merged, self.default, self.fail, self.has_next, self.calls = open_prs or [], merged or [], default, fail, has_next, []

    def __call__(self, args, cwd, timeout):
        self.calls.append(list(args))
        if self.fail == "all":
            return subprocess.CompletedProcess(args, 1, "", "boom")
        if args[:2] == ["repo", "view"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"owner": {"login": "o"}, "name": "r",
                                                                      "defaultBranchRef": {"name": self.default}}), "")
        query = next(a for a in args if a.startswith("query="))
        if "states: MERGED" in query:
            if self.fail == "merged":
                return subprocess.CompletedProcess(args, 1, "", "boom")
            base = next(a for a in args if a.startswith("base="))[5:]
            self.merged_base = base
            nodes = self.merged
            return subprocess.CompletedProcess(args, 0, json.dumps({"data": {"repository": {"pullRequests": {"nodes": nodes}}}}), "")
        if self.fail == "garbage":
            return subprocess.CompletedProcess(args, 0, "not json", "")
        data = {"data": {"repository": {"pullRequests": {"pageInfo": {"hasNextPage": self.has_next}, "nodes": self.open_prs}}}}
        return subprocess.CompletedProcess(args, 0, json.dumps(data), "")


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=tester", "-c", "commit.gpgsign=false",
                           *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def repo_with_shas() -> tuple[Path, list[str]]:
    """A repository: main has c1 <- c2 <- c3; `promoted` points at c2. Returns the path and the three commit ids."""
    _counter[0] += 1
    repo = ROOT / f"repo{_counter[0]}"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    shas = []
    for name in ("c1", "c2", "c3"):
        (repo / name).write_text(name)
        git(repo, "add", name)
        git(repo, "commit", "-q", "-m", name)
        shas.append(git(repo, "rev-parse", "HEAD"))
    git(repo, "branch", "promoted", shas[1])
    return repo, shas


# ---------------------------------------------------------------- last_work_at

@case("last_work_at: a base merge newer than the last real commit does not reset it")
def _():
    row = row_of(raw_pr(commits=[commit(30), commit(0.5, parents=2), commit(10)]))
    assert row["last_work_at"] == ago(10) and row["last_work_at_estimated"] is False, row
    assert row["waiting"] == "draft-idle" and row["hours"] == 10.0, row


@case("last_work_at: the newest real commit wins whatever the order, and only fetched real commits count")
def _():
    row = row_of(raw_pr(commits=[commit(3), commit(7), commit(5)]))
    assert row["last_work_at"] == ago(3), row


@case("last_work_at: all fetched commits being merges falls back to creation and says so")
def _():
    row = row_of(raw_pr(commits=[commit(1, parents=2), commit(2, parents=2)], created=40))
    assert row["last_work_at"] == ago(40) and row["last_work_at_estimated"] is True and row["waiting"] == "draft-idle", row
    row = row_of(raw_pr(commits=[], created=1))
    assert row["last_work_at_estimated"] is True and row["waiting"] == "draft-active", row


# ---------------------------------------------------------------- waiting

@case("threshold: exactly idle-hours is idle; below is active")
def _():
    assert row_of(raw_pr(commits=[commit(2.0)]), idle=2.0)["waiting"] == "draft-idle"
    assert row_of(raw_pr(commits=[commit(1.99)]), idle=2.0)["waiting"] == "draft-active"
    assert row_of(raw_pr(commits=[commit(5.0)]), idle=5.0)["waiting"] == "draft-idle"
    assert row_of(raw_pr(commits=[commit(0.0)]), idle=0)["waiting"] == "draft-idle"


@case("ready: a pull request that is not a draft is never draft-*; ready_at comes from the event, else creation")
def _():
    row = row_of(raw_pr(draft=False, commits=[commit(500)], created=600, ready=20))
    assert row["waiting"] == "ready-unmerged" and row["ready_at"] == ago(20) and row["hours"] == 20.0 and row["draft"] is False, row
    row = row_of(raw_pr(draft=False, commits=[commit(500)], created=600))
    assert row["waiting"] == "ready-unmerged" and row["ready_at"] == ago(600) and row["hours"] == 600.0, row
    row = row_of(raw_pr(draft=True, commits=[commit(0.1)], ready=5))
    assert row["waiting"] == "draft-active" and row["ready_at"] is None, row  # converted back to draft: a draft again


@case("verified-not-ready: needs the captured SHA to match the current head")
def _():
    row = row_of(raw_pr(body=f"verified at {HEAD[:7]}", commits=[commit(1)]))
    assert row["waiting"] == "verified-not-ready" and row["verified_head"] == HEAD[:7], row  # wins over draft-active
    row = row_of(raw_pr(body=f"verified at {HEAD}", commits=[commit(30)]))
    assert row["waiting"] == "verified-not-ready" and row["hours"] == 30.0, row  # wins over draft-idle
    row = row_of(raw_pr(body=f"verified at {OTHER[:7]}", commits=[commit(30)]))
    assert row["waiting"] == "draft-idle" and row["verified_head"] is None, row  # stale evidence
    row = row_of(raw_pr(body="verified at a1b2c3", commits=[commit(30)]))
    assert row["waiting"] == "draft-idle", row  # too short a pattern match never reaches 7 hex chars
    row = row_of(raw_pr(body=f"verified at {OTHER[:7]}\nlater\nverified at {HEAD[:9]}"))
    assert row["waiting"] == "verified-not-ready", row  # one of two lines vouches for the current head


@case("verified-not-ready: a match inside an HTML comment, or a non-draft pull request, does not produce it")
def _():
    row = row_of(raw_pr(body=f"<!-- verified at {HEAD[:7]} -->", commits=[commit(30)]))
    assert row["waiting"] == "draft-idle", row
    row = row_of(raw_pr(body=f"<!--\nverified at {HEAD[:7]}\n-->\ntext", commits=[commit(30)]))
    assert row["waiting"] == "draft-idle", row
    row = row_of(raw_pr(draft=False, body=f"verified at {HEAD[:7]}"))
    assert row["waiting"] == "ready-unmerged" and row["verified_head"] is None, row
    row = row_of(raw_pr(body=f"<!-- x --> verified at {HEAD[:7]}"))
    assert row["waiting"] == "verified-not-ready", row  # a comment elsewhere does not hide real evidence


@case("verified-not-ready: no pattern, no verified state")
def _():
    row = row_of(raw_pr(body=f"verified at {HEAD[:7]}", commits=[commit(30)]), pattern=None)
    assert row["waiting"] == "draft-idle", row


# ---------------------------------------------------------------- build: order and shape

@case("build: grouped verified, ready, idle, active; oldest first inside a group; shape of the JSON")
def _():
    prs = [raw_pr(1, commits=[commit(1)]), raw_pr(2, commits=[commit(9)]), raw_pr(3, commits=[commit(40)]),
           raw_pr(4, draft=False, ready=3), raw_pr(5, draft=False, ready=50), raw_pr(6, body=f"verified at {HEAD[:7]}", commits=[commit(8)])]
    doc = stalled.build(prs, NOW, 2.0, PATTERN, "/r")
    assert [(r["number"], r["waiting"]) for r in doc["open"]] == [
        (6, "verified-not-ready"), (5, "ready-unmerged"), (4, "ready-unmerged"), (3, "draft-idle"), (2, "draft-idle"), (1, "draft-active")], doc["open"]
    assert doc["remote"] == "ok" and doc["idle_hours"] == 2.0 and doc["repo"] == "/r" and doc["generated_at"] == "2026-01-10T12:00:00Z"
    assert set(doc["open"][0]) == {"number", "title", "url", "author", "draft", "waiting", "last_work_at", "last_work_at_estimated",
                                   "ready_at", "hours", "verified_head"}, sorted(doc["open"][0])
    assert doc["unpromoted"]["state"] == "skipped" and doc["unpromoted"]["items"] == []
    assert stalled.build(prs, NOW) == stalled.build(prs, NOW), "same inputs, same output"


@case("render: the table groups, truncates, marks an estimate and ends with what the hours mean")
def _():
    long_title = "x" * 100
    prs = [dict(raw_pr(1, commits=[commit(9, parents=2)], created=9), title=long_title), raw_pr(2, draft=False, ready=4)]
    text = stalled.render(stalled.build(prs, NOW, 2.0, PATTERN))
    lines = text.splitlines()
    assert "ready-unmerged (1)" in lines and "  #2  4h  alice  pull request 2" in lines, text
    assert "draft-idle (1)" in lines and any(l.startswith("  #1  ~9h  alice  xxx") and l.endswith("...") for l in lines), text
    assert "draft-active: 0" in lines and lines[-1].startswith("hours:"), text
    assert not any(l.startswith("verified-not-ready") for l in lines), "an empty group is not printed"


@case("render: a control character in a forge string never reaches the terminal and the row stays on one line")
def _():
    evil = "fix\x1b[2J\nsecond line\x07\x9b"
    prs = [dict(raw_pr(1, commits=[commit(9)]), title=evil, author={"login": "al\x1bice"}), dict(raw_pr(2, draft=False, ready=4), title=evil)]
    promotion = {"ref": "st\x1bg", "base": "ma\nin", "count": 1, "oldest_merged_at": ago(3), "state": "ok", "reason": "",
                 "items": [{"number": 9, "title": evil, "author": "b\x1bb", "merged_at": ago(3), "hours": 3.0}]}
    text = stalled.render(stalled.build(prs, NOW, 2.0, PATTERN, "/r", promotion))
    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]", text), repr(text)
    lines = text.splitlines()
    assert "  #1  9h  al?ice  fix?[2J?second line??" in lines and "  #2  4h  alice  fix?[2J?second line??" in lines, lines
    assert "  #9  3h  b?b  fix?[2J?second line??" in lines and "unpromoted into st?g (merged into ma?in): 1, oldest merged " + ago(3) in lines, lines
    unknown = dict(promotion, state="unknown", reason="no \x1b[31mref")
    assert "unpromoted into st?g: unknown (no ?[31mref)" in stalled.render(stalled.build(prs, NOW, 2.0, PATTERN, "/r", unknown)).splitlines()
    assert json.loads(json.dumps(stalled.build(prs, NOW)))["open"][1]["title"] == evil, "JSON keeps the string; json.dumps escapes it"


# ---------------------------------------------------------------- base branch

@case("base branch: the contract wins, then the open pull requests' most common base, then the default branch")
def _():
    prs = [raw_pr(1, base="develop"), raw_pr(2, base="develop"), raw_pr(3, base="main")]
    assert stalled.pick_base("trunk", prs, "main") == "trunk"
    assert stalled.pick_base(None, prs, "main") == "develop"
    assert stalled.pick_base(None, [raw_pr(1, base="b"), raw_pr(2, base="a")], "main") == "a"
    assert stalled.pick_base(None, [], "main") == "main" and stalled.pick_base(None, [], None) is None


# ---------------------------------------------------------------- promotion

@case("unpromoted: an ancestor of the ref is not listed, a non-ancestor is, oldest first")
def _():
    repo, shas = repo_with_shas()
    merged = [merged_node(11, shas[0], 30), merged_node(12, shas[1], 20), merged_node(13, shas[2], 10), merged_node(14, shas[2], 5)]
    out = stalled.unpromoted(str(repo), "promoted", "main", stalled.fetch_merged({"owner": "o", "name": "r", "deadline": 1e18}, "main", 50, "/r",
                                                                              gh=FakeGh(merged=merged)), NOW)
    assert out["state"] == "ok" and out["count"] == 2 and [i["number"] for i in out["items"]] == [13, 14], out
    assert out["oldest_merged_at"] == ago(10) and out["items"][0]["hours"] == 10.0 and out["ref"] == "promoted", out
    assert set(out["items"][0]) == {"number", "title", "author", "merged_at", "hours"}


@case("unpromoted: everything already promoted is ok with count 0, not unknown")
def _():
    repo, shas = repo_with_shas()
    out = stalled.unpromoted(str(repo), "main", "main", [{"number": 1, "title": "t", "merged": NOW, "author": "a", "oid": shas[0]}], NOW)
    assert out["state"] == "ok" and out["count"] == 0 and out["items"] == [] and out["oldest_merged_at"] is None, out


@case("unpromoted: a missing ref or a missing commit is unknown with a reason, never an empty all-promoted result")
def _():
    repo, shas = repo_with_shas()
    pr = {"number": 1, "title": "t", "merged": NOW, "author": "a", "oid": shas[2]}
    out = stalled.unpromoted(str(repo), "origin/nowhere", "main", [pr], NOW)
    assert out["state"] == "unknown" and out["count"] is None and out["items"] == [] and "origin/nowhere" in out["reason"], out
    ghost = dict(pr, oid="1234567890123456789012345678901234567890")
    out = stalled.unpromoted(str(repo), "promoted", "main", [pr, ghost], NOW)
    assert out["state"] == "unknown" and out["items"] == [] and "1 of 2" in out["reason"], out
    out = stalled.unpromoted(str(repo), "promoted", "main", [dict(pr, oid="")], NOW)
    assert out["state"] == "unknown", out  # the forge gave no merge commit
    out = stalled.unpromoted(str(repo), "promoted", "main", None, NOW)
    assert out["state"] == "unknown", out  # the forge did not answer
    out = stalled.unpromoted(str(ROOT / "not-a-repo"), "promoted", "main", [pr], NOW)
    assert out["state"] == "unknown", out  # not even a directory


@case("unpromoted: at the limit with the oldest checked one unpromoted, the count is a lower bound and says so")
def _():
    repo, shas = repo_with_shas()
    old, new = ({"number": 1, "title": "a", "author": "x", "merged": stalled.parse_time(ago(9)), "oid": shas[2]},
                {"number": 2, "title": "b", "author": "x", "merged": stalled.parse_time(ago(1)), "oid": shas[2]})
    out = stalled.unpromoted(str(repo), "promoted", "main", [new, old], NOW, limit=2)
    assert out["state"] == "ok" and out["count"] == 2 and out["more"] is True, out
    assert "at least this many" in stalled.render(stalled.build([], NOW, promotion=out)), out
    assert stalled.unpromoted(str(repo), "promoted", "main", [new, old], NOW, limit=3)["more"] is False
    done = dict(old, oid=shas[0])  # the oldest checked one is promoted: nothing older can be waiting
    assert stalled.unpromoted(str(repo), "promoted", "main", [new, done], NOW, limit=2)["more"] is False
    assert stalled.unpromoted(str(repo), "promoted", "main", [new, old], NOW)["more"] is False


@case("unpromoted: without a ref it is skipped")
def _():
    out = stalled.unpromoted("/r", None, None, None, NOW)
    assert out["state"] == "skipped" and out["ref"] is None and out["items"] == [], out


@case("fetch_merged: the newest by merge time, capped at the limit, a pull request without a merge time dropped")
def _():
    merged = [merged_node(1, "a" * 40, 50), merged_node(2, "b" * 40, 5), merged_node(3, "c" * 40, 20), dict(merged_node(4, "d" * 40, 1), mergedAt=None)]
    gh = FakeGh(merged=merged)
    got = stalled.fetch_merged({"owner": "o", "name": "r", "deadline": 1e18}, "develop", 2, "/r", gh=gh)
    assert [m["number"] for m in got] == [2, 3] and gh.merged_base == "develop", got


# ---------------------------------------------------------------- the forge being unavailable

@case("fetch: gh missing, gh error, a timeout and malformed JSON are unavailable")
def _():
    def missing(args, cwd, timeout):
        raise FileNotFoundError("gh")

    def slow(args, cwd, timeout):
        raise subprocess.TimeoutExpired(args, timeout)

    def odd(args, cwd, timeout):
        return subprocess.CompletedProcess(args, 0, json.dumps({"owner": 3}), "")

    for gh in (missing, slow, odd, FakeGh(fail="all"), FakeGh(fail="garbage"), FakeGh(fail="garbage")):
        assert stalled.fetch_open("/r", gh=gh) == ("unavailable", None), gh
    remote, info = stalled.fetch_open("/r", gh=FakeGh([raw_pr(1)], default="trunk", has_next=True))
    assert remote == "ok" and info["default_branch"] == "trunk" and info["truncated"] is True and len(info["prs"]) == 1, info


# ---------------------------------------------------------------- the command

def run_main(argv: list[str], gh=None) -> tuple[int, str]:
    buffer = io.StringIO()
    original = stalled.run_gh
    if gh is not None:
        stalled.run_gh = gh
    try:
        with contextlib.redirect_stdout(buffer):
            code = stalled.main(argv)
    finally:
        stalled.run_gh = original
    return code, buffer.getvalue()


@case("command: gh failing is `remote: unavailable` in the table and in JSON, exit 0, no traceback")
def _():
    def missing(args, cwd, timeout):
        raise FileNotFoundError("gh")
    for gh in (missing, FakeGh(fail="all"), FakeGh(fail="garbage")):
        code, out = run_main(["--repo", str(ROOT)], gh)
        assert code == 0 and out.strip() == "remote: unavailable", (code, out)
        code, out = run_main(["--repo", str(ROOT), "--json", "--promoted-ref", "promoted"], gh)
        doc = json.loads(out)
        assert code == 0 and doc["remote"] == "unavailable" and doc["open"] == [] and doc["unpromoted"]["state"] == "unknown", doc


@case("command: end to end, with the contract absent the open pull requests' base is used for the merged list")
def _():
    repo, shas = repo_with_shas()
    gh = FakeGh([raw_pr(1, base="trunk", commits=[commit(9)]), raw_pr(2, draft=False, ready=3, base="trunk")],
                [merged_node(11, shas[1], 20), merged_node(12, shas[2], 4)], default="main")
    code, out = run_main(["--repo", str(repo), "--json", "--promoted-ref", "promoted", "--verified-pattern", PATTERN.pattern], gh)
    doc = json.loads(out)
    assert code == 0 and doc["remote"] == "ok", doc
    assert [(r["number"], r["waiting"]) for r in doc["open"]] == [(2, "ready-unmerged"), (1, "draft-idle")], doc["open"]
    assert doc["unpromoted"]["base"] == "trunk" and gh.merged_base == "trunk", doc["unpromoted"]
    assert doc["unpromoted"]["state"] == "ok" and [i["number"] for i in doc["unpromoted"]["items"]] == [12], doc["unpromoted"]
    assert "open_truncated" not in doc
    code, out = run_main(["--repo", str(repo), "--promoted-ref", "promoted"], gh)
    assert code == 0 and "unpromoted into promoted (merged into trunk): 1" in out and "ready-unmerged (1)" in out, out
    code, out = run_main(["--repo", str(repo)], FakeGh([], has_next=True))
    assert "more open pull requests exist" in out, out


@case("command: the contract's base_branch is used when set")
def _():
    repo, shas = repo_with_shas()
    (repo / ".plumb").mkdir()
    (repo / ".plumb" / "project.toml").write_text('schema = 1\n[repo]\nbase_branch = "release"\n')
    gh = FakeGh([raw_pr(1, base="trunk")], [], default="main")
    code, out = run_main(["--repo", str(repo), "--json", "--promoted-ref", "promoted"], gh)
    assert json.loads(out)["unpromoted"]["base"] == "release" and gh.merged_base == "release", out


@case("command: it writes nothing under the repository")
def _():
    repo, shas = repo_with_shas()
    before = git(repo, "status", "--porcelain=v1", "--ignored")
    run_main(["--repo", str(repo), "--promoted-ref", "promoted"], FakeGh([raw_pr(1)], [merged_node(1, shas[2], 1)]))
    assert git(repo, "status", "--porcelain=v1", "--ignored") == before and before == ""


@case("command: bad usage exits non-zero; the wrapper runs the script and resolves a symlink")
def _():
    script = str(HERE / "stalled.py")
    for bad in (["--idle-hours", "soon"], ["--idle-hours", "-1"], ["--verified-pattern", "(["], ["--verified-pattern", "no-group"],
                ["--promoted-limit", "0"], ["--promoted-limit", "101"], ["--promoted-ref", "--upload-pack=x"], ["--bogus"]):
        done = subprocess.run([sys.executable, script, *bad], capture_output=True, text=True)
        assert done.returncode == 2 and "usage" in done.stderr and "Traceback" not in done.stderr, (bad, done)
    base = ROOT / "wrapper"
    base.mkdir()
    link = base / "plumb-stalled"
    link.symlink_to(BIN)
    stub = base / "bin"
    stub.mkdir()
    (stub / "gh").write_text("#!/bin/sh\nexit 1\n")
    (stub / "gh").chmod(0o755)
    out = subprocess.run([str(link), "--repo", str(base)], capture_output=True, text=True,
                         env={**os.environ, "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}"})
    assert out.returncode == 0 and out.stdout.strip() == "remote: unavailable" and out.stderr == "", out
    assert os.access(BIN, os.X_OK)
    nogh = subprocess.run([sys.executable, script, "--repo", str(base), "--json"], capture_output=True, text=True,
                          env={**os.environ, "PATH": str(stub.parent / "empty")})
    assert nogh.returncode == 0 and json.loads(nogh.stdout)["remote"] == "unavailable" and "Traceback" not in nogh.stderr, nogh


shutil.rmtree(ROOT, ignore_errors=True)
if FAILED:
    print(f"\n{len(FAILED)} case(s) failed")
    sys.exit(1)
print("\nall cases ok")
