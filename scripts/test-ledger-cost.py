#!/usr/bin/env python3
"""Regression suite for plumb-ledger capture / export / prs / report on synthetic data only.

    python3 -B scripts/test-ledger-cost.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline: transcripts are
generated here, "GitHub" is PLUMB_LEDGER_GH_FIXTURES, the store is a local bare repository, all under
tempfile.mkdtemp(). No real transcript is read or copied.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(HERE))
import ledger_cost  # noqa: E402

LEDGER = PLUGIN / "bin" / "plumb-ledger"
FIXTURES = HERE / "fixtures" / "ledger-cost"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-ledger-test-"))
FAILED: list[str] = []
SECRET = "SECRET-BODY-9f3a"
REMOTE_VAR = "CLAUDE_CODE_REMOTE_SESSION_ID"

HAIKU = "claude-haiku-5-5"
OPUS = "claude-opus-5-5"


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

class Sandbox:
    """A private HOME, config, ledger directory and working directory."""

    def __init__(self, name: str) -> None:
        self.root = ROOT / name
        self.root.mkdir(parents=True)
        (self.root / "home").mkdir()
        self.config = self.root / "config"
        self.config.write_text("ledger.capture = on\n")
        self.ledger = self.root / "ledger"
        self.cwd = self.root / "work"
        self.cwd.mkdir()
        # Where a sweep looks: all inside the sandbox, never the real ~/.codex or ~/.local/share/opencode.
        self.codex = self.root / "codex-home"
        self.data = self.root / "data-home"
        self.opencode = self.data / "opencode" / "opencode.db"
        self.env = {**os.environ, "HOME": str(self.root / "home"), "PLUMB_CONFIG": str(self.config),
                    "PLUMB_LEDGER_DIR": str(self.ledger), "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                    "CODEX_HOME": str(self.codex), "XDG_DATA_HOME": str(self.data)}
        for name in ("PLUMB_LEDGER_GH_FIXTURES", "OPENCODE_DATA_DIR", "CLAUDE_CODE_REMOTE", REMOTE_VAR):
            self.env.pop(name, None)

    def set_config(self, text: str) -> None:
        self.config.write_text(text)

    def ledger_cmd(self, *args: str, extra_env: dict | None = None, cwd: Path | None = None):
        out = subprocess.run([str(LEDGER), *args], capture_output=True, text=True, cwd=cwd or self.cwd,
                             env={**self.env, **(extra_env or {})}, timeout=300)
        return out.returncode, out.stdout, out.stderr

    def pending(self) -> list[dict]:
        return read_records(self.ledger, "pending")

    def exported(self) -> list[dict]:
        return read_records(self.ledger, "exported")

    def report(self, *args: str, since: str = "2026-09-01", until: str = "2026-10-31") -> dict:
        code, out, err = self.ledger_cmd("report", "--since", since, "--until", until, "--json", *args)
        assert code == 0, f"report exited {code}: {err}"
        return json.loads(out)


def read_records(ledger: Path, kind: str) -> list[dict]:
    rows = []
    for path in sorted((ledger / kind).glob("*/*.jsonl")) if (ledger / kind).is_dir() else []:
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line)
    return rows


def git(path: Path, *args: str, at: str | None = None) -> str:
    """Run git; `at` (an ISO time) is the committer date, which is the time the reflog records."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", **({"GIT_COMMITTER_DATE": at} if at else {})}
    out = subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, f"git {args}: {out.stderr}"
    return out.stdout.strip()


def make_repo(path: Path, origin: str = "https://github.com/acme/widgets.git", branches=("feat/a", "feat/b")) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "commit", "-q", "--allow-empty", "-m", "init", at="2026-10-01T00:00:00Z")   # the reflog starts here
    git(path, "remote", "add", "origin", origin)
    for branch in branches:
        git(path, "branch", branch)
    return path


def usage(inp=1000, out=0, read=0, w5=0, w1=0) -> dict:
    return {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": w5 + w1,
            "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}


def assistant(msg_id, ts, cwd, branch, *, req=None, model=HAIKU, use=None, side=False, agent=None, text="hello") -> str:
    rec = {"type": "assistant", "isSidechain": side, "timestamp": ts, "cwd": str(cwd), "gitBranch": branch,
           "message": {"id": msg_id, "model": model, "role": "assistant",
                       "content": [{"type": "text", "text": text}], "usage": use if use is not None else usage()}}
    if req:
        rec["requestId"] = req
    if agent:
        rec["agentId"] = agent
    return json.dumps(rec)


def write_transcript(directory: Path, session: str, lines: list[str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session}.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


def capture(sb: Sandbox, transcript: Path, *extra: str) -> dict:
    code, out, err = sb.ledger_cmd("capture", "--json", "--transcript", str(transcript), *extra)
    assert code == 0, f"capture exited {code}: {err}"
    return json.loads(out.splitlines()[0])


def record(i, time_="2026-10-10T00:00:00.000Z", *, model=HAIKU, repo="acme/widgets", branch="feat/x", session="s1",
           runtime="claude", inp=1000, out=0, cache_read=0, w5=0, w1=0, rid="x", role="main", agent_type=None) -> dict:
    return {"id": rid if rid is None else f"{runtime}:{rid}{i}", "time": time_, "model": model, "input": inp,
            "output": out, "cache_read": cache_read, "cache_write_5m": w5, "cache_write_1h": w1,
            "repository": repo, "branch": branch, "attribution_source": "transcript" if branch else "unknown",
            "role": role, "agent_type": agent_type, "agent_id": None, "session": session, "runtime": runtime}


def put_pending(sb: Sandbox, session: str, rows: list[dict], runtime: str = "claude") -> None:
    path = sb.ledger / "pending" / runtime / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))


def bare_store(sb: Sandbox) -> Path:
    store = sb.root / "store.git"
    subprocess.run(["git", "init", "--bare", "-q", str(store)], check=True)
    sb.set_config(f"ledger.capture = on\nledger.store = {store}\n")
    return store


def refs(store: Path) -> dict[str, str]:
    out = subprocess.run(["git", "ls-remote", str(store)], capture_output=True, text=True).stdout
    return {line.split("\t")[1]: line.split("\t")[0] for line in out.splitlines()}


def by_task(report: dict) -> dict[str, str]:
    return {row["name"]: row["cost"] for row in report["by_task"]}


# ---------------------------------------------------------------- capture: attribution

def attributed(sb: Sandbox) -> dict[str, tuple]:
    """(branch, source) per request id."""
    return {r["id"].removeprefix("claude:"): (r["branch"], r["attribution_source"]) for r in sb.pending()}


@case("a branch switch inside one turn attributes each request to its own branch, read from the reflog")
def _():
    sb = Sandbox("switch")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:00Z")
    git(repo, "checkout", "-q", "feat/b", at="2026-10-10T00:00:02Z")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:04Z")
    lines = [assistant(f"msg_{i}", f"2026-10-10T00:00:0{i}Z", repo, "feat/a") for i in (1, 3, 5)]  # gitBranch is the launch branch
    capture(sb, write_transcript(sb.root / "proj", "sess-switch", lines))
    assert attributed(sb) == {"msg_1": ("feat/a", "reflog"), "msg_3": ("feat/b", "reflog"),
                              "msg_5": ("feat/a", "reflog")}, attributed(sb)
    assert {r["repository"] for r in sb.pending()} == {"acme/widgets"}


@case("launched outside a repository (gitBranch HEAD), then cd into a repo: the reflog names the branch")
def _():
    sb = Sandbox("launched-outside")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:00Z")
    capture(sb, write_transcript(sb.root / "proj", "sess-out", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo, "HEAD"), assistant("msg_2", "2026-10-10T00:00:02Z", repo, "HEAD")]))
    assert attributed(sb) == {"msg_1": ("feat/a", "reflog"), "msg_2": ("feat/a", "reflog")}, attributed(sb)


@case("a branch switched away from and deleted in the same turn is still the branch of the earlier requests")
def _():
    sb = Sandbox("switch-delete")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:00Z")
    git(repo, "checkout", "-q", "-b", "feat/new", at="2026-10-10T00:00:02Z")
    git(repo, "branch", "-D", "feat/a")
    capture(sb, write_transcript(sb.root / "proj", "sess-del", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo, "feat/a"), assistant("msg_2", "2026-10-10T00:00:03Z", repo, "feat/a")]))
    assert attributed(sb) == {"msg_1": ("feat/a", "reflog"), "msg_2": ("feat/new", "reflog")}, attributed(sb)


@case("cd into a worktree: the worktree's branch, not the launch checkout's gitBranch")
def _():
    sb = Sandbox("cd-worktree")
    repo = make_repo(sb.root / "repo", branches=("feat/main",))
    git(repo, "checkout", "-q", "feat/main", at="2026-10-10T00:00:00Z")
    wt = sb.root / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feat/wt", str(wt), at="2026-10-10T00:00:00Z")
    capture(sb, write_transcript(sb.root / "proj", "sess-cd", [
        assistant("msg_wt", "2026-10-10T00:00:01Z", wt, "feat/main"),
        assistant("msg_main", "2026-10-10T00:00:01Z", repo, "feat/main")]))
    assert attributed(sb) == {"msg_wt": ("feat/wt", "reflog"), "msg_main": ("feat/main", "reflog")}, attributed(sb)


@case("a branch renamed after the request is attributed under its new name")
def _():
    sb = Sandbox("rename")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "feat/b", at="2026-10-10T00:00:00Z")
    git(repo, "branch", "-m", "feat/b", "fix/b", at="2026-10-10T00:00:05Z")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:07Z")     # moved away after the rename
    capture(sb, write_transcript(sb.root / "proj", "sess-ren", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo, "feat/b"), assistant("msg_2", "2026-10-10T00:00:06Z", repo, "feat/b")]))
    assert attributed(sb) == {"msg_1": ("fix/b", "reflog"), "msg_2": ("fix/b", "reflog")}, attributed(sb)


@case("a detached HEAD at the request's time, by commit, `--detach` or tag, is unknown")
def _():
    sb = Sandbox("detached-at")
    repo = make_repo(sb.root / "repo")
    git(repo, "tag", "v1")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:00Z")
    git(repo, "checkout", "-q", "--detach", at="2026-10-10T00:00:02Z")       # "moving from feat/a to HEAD"
    git(repo, "checkout", "-q", "feat/b", at="2026-10-10T00:00:04Z")
    git(repo, "checkout", "-q", "v1", at="2026-10-10T00:00:06Z")             # a tag detaches too
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:08Z")
    capture(sb, write_transcript(sb.root / "proj", "sess-det", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo, "feat/a"),    # on feat/a
        assistant("msg_3", "2026-10-10T00:00:03Z", repo, "feat/a"),    # detached by --detach
        assistant("msg_5", "2026-10-10T00:00:05Z", repo, "feat/b"),    # on feat/b
        assistant("msg_7", "2026-10-10T00:00:07Z", repo, "feat/b"),    # on the tag
        assistant("msg_9", "2026-10-10T00:00:09Z", repo, "feat/b")]))  # back on feat/a
    assert attributed(sb) == {"msg_1": ("feat/a", "reflog"), "msg_3": (None, "unknown"), "msg_5": ("feat/b", "reflog"),
                              "msg_7": (None, "unknown"), "msg_9": ("feat/a", "reflog")}, attributed(sb)


@case("a request during a rebase belongs to the branch being rebased")
def _():
    sb = Sandbox("rebase")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "feat/b", at="2026-10-10T00:00:00Z")
    git(repo, "commit", "-q", "--allow-empty", "-m", "work", at="2026-10-10T00:00:01Z")
    git(repo, "checkout", "-q", "main", at="2026-10-10T00:00:02Z")
    git(repo, "commit", "-q", "--allow-empty", "-m", "base", at="2026-10-10T00:00:03Z")
    git(repo, "checkout", "-q", "feat/b", at="2026-10-10T00:00:04Z")
    git(repo, "branch", "-m", "fix/b", at="2026-10-10T00:00:04Z")
    git(repo, "rebase", "-q", "main", at="2026-10-10T00:00:06Z")            # start .. finish, returning to fix/b
    capture(sb, write_transcript(sb.root / "proj", "sess-rb", [
        assistant("msg_1", "2026-10-10T00:00:05Z", repo, "feat/b"),     # between the rename and the rebase
        assistant("msg_2", "2026-10-10T00:00:07Z", repo, "feat/b")]))   # after the rebase
    assert attributed(sb) == {"msg_1": ("fix/b", "reflog"), "msg_2": ("fix/b", "reflog")}, attributed(sb)


@case("an event in the same second as the request counts as already happened")
def _():
    sb = Sandbox("same-second")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:00Z")
    git(repo, "checkout", "-q", "feat/b", at="2026-10-10T00:00:02Z")
    capture(sb, write_transcript(sb.root / "proj", "sess-sec", [
        assistant("msg_1", "2026-10-10T00:00:02.900Z", repo, "feat/a")]))
    assert attributed(sb) == {"msg_1": ("feat/b", "reflog")}, attributed(sb)


@case("a request older than the repository's first reflog entry falls back to the transcript's gitBranch")
def _():
    sb = Sandbox("before-reflog")
    repo = make_repo(sb.root / "repo")                                   # first reflog line: 2026-10-01
    git(repo, "checkout", "-q", "feat/b", at="2026-10-10T00:00:00Z")
    capture(sb, write_transcript(sb.root / "proj", "sess-old", [
        assistant("msg_old", "2026-09-20T00:00:00Z", repo, "feat/a"),    # before any reflog line
        assistant("msg_new", "2026-10-10T00:00:01Z", repo, "feat/a")]))
    assert attributed(sb) == {"msg_old": ("feat/a", "transcript"), "msg_new": ("feat/b", "reflog")}, attributed(sb)


@case("a rebase stopped on a conflict, unfinished at capture: a request before it keeps its branch")
def _():
    sb = Sandbox("rebase-stopped")
    repo = make_repo(sb.root / "repo", branches=())
    (repo / "f").write_text("base\n")
    git(repo, "add", "f")
    git(repo, "commit", "-q", "-m", "base", at="2026-10-10T00:00:00Z")
    git(repo, "checkout", "-q", "-b", "feat/a", at="2026-10-10T00:00:01Z")
    (repo / "f").write_text("a\n")
    git(repo, "commit", "-q", "-am", "a", at="2026-10-10T00:00:02Z")
    git(repo, "checkout", "-q", "main", at="2026-10-10T00:00:03Z")
    (repo / "f").write_text("main\n")
    git(repo, "commit", "-q", "-am", "main", at="2026-10-10T00:00:04Z")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:05Z")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_COMMITTER_DATE": "2026-10-10T00:00:07Z"}
    stopped = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "rebase", "main"],
                             capture_output=True, text=True, env=env)
    assert stopped.returncode != 0 and (repo / ".git" / "rebase-merge").is_dir(), stopped.stdout + stopped.stderr
    capture(sb, write_transcript(sb.root / "proj", "sess-rbstop", [
        assistant("msg_1", "2026-10-10T00:00:06Z", repo, "feat/a"),      # on feat/a, before the rebase started
        assistant("msg_2", "2026-10-10T00:00:08Z", repo, "feat/a")]))    # inside the stopped rebase: detached
    assert attributed(sb) == {"msg_1": ("feat/a", "reflog"), "msg_2": (None, "unknown")}, attributed(sb)


@case("a rebase start with no earlier branch-changing event cannot be decided and falls back")
def _():
    log = ledger_cost.parse_reflog("HEAD@{1760054410}\trebase (start): checkout main\n"
                                   "HEAD@{1760054400}\tcommit (initial): init")
    assert [(e[1], e[2]) for e in log.events] == [(None, "HEAD")] and log.oldest == 1760054400, vars(log)
    checkouts = ledger_cost.Checkouts()
    checkouts.cache.update({("top", "/r"): "/r", ("head", "/r"): None, ("moves", "/r"): log})
    assert checkouts.branch_at("/r", 1760054405) is ledger_cost.UNDECIDED


@case("a branch that shares its name with a tag is the branch")
def _():
    sb = Sandbox("branch-tag")
    repo = make_repo(sb.root / "repo", branches=("release",))
    git(repo, "tag", "release")
    git(repo, "checkout", "-q", "release", at="2026-10-10T00:00:00Z")     # git prefers the branch
    git(repo, "checkout", "-q", "main", at="2026-10-10T00:00:02Z")
    capture(sb, write_transcript(sb.root / "proj", "sess-tag", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo, "main")]))
    assert attributed(sb) == {"msg_1": ("release", "reflog")}, attributed(sb)


@case("on a branch that shares its name with a tag, the current branch is still read (symbolic-ref --short says heads/x)")
def _():
    sb = Sandbox("branch-tag-now")
    repo = make_repo(sb.root / "repo", branches=("release",))
    git(repo, "tag", "release")
    git(repo, "checkout", "-q", "release", at="2026-10-10T00:00:00Z")
    capture(sb, write_transcript(sb.root / "proj", "sess-tag-now", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo, "main")]))
    assert attributed(sb) == {"msg_1": ("release", "reflog")}, attributed(sb)


@case("checking out a revision (HEAD~1, an abbreviated hash) is a detached HEAD: unknown, not the transcript branch")
def _():
    sb = Sandbox("revision")
    repo = make_repo(sb.root / "repo")
    git(repo, "commit", "-q", "--allow-empty", "-m", "second", at="2026-10-09T00:00:00Z")
    git(repo, "checkout", "-q", "HEAD~1", at="2026-10-10T00:00:00Z")
    lines = [assistant("msg_1", "2026-10-10T00:00:01Z", repo, "main")]
    capture(sb, write_transcript(sb.root / "proj", "sess-rev", lines))
    assert attributed(sb) == {"msg_1": (None, "unknown")}, attributed(sb)
    sb2 = Sandbox("short-hash")
    repo2 = make_repo(sb2.root / "repo")
    git(repo2, "commit", "-q", "--allow-empty", "-m", "second", at="2026-10-09T00:00:00Z")
    abbrev = git(repo2, "rev-parse", "--short", "HEAD~1")
    git(repo2, "checkout", "-q", abbrev, at="2026-10-10T00:00:00Z")
    capture(sb2, write_transcript(sb2.root / "proj", "sess-short", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo2, "main")]))
    assert attributed(sb2) == {"msg_1": (None, "unknown")}, attributed(sb2)
    sb3 = Sandbox("hex-branch")
    repo3 = make_repo(sb3.root / "repo", branches=("cafe",))
    git(repo3, "checkout", "-q", "cafe", at="2026-10-10T00:00:00Z")
    git(repo3, "checkout", "-q", "main", at="2026-10-10T00:00:02Z")
    git(repo3, "branch", "-D", "cafe")
    capture(sb3, write_transcript(sb3.root / "proj", "sess-hex", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo3, "main")]))
    assert attributed(sb3) == {"msg_1": ("cafe", "reflog")}, attributed(sb3)   # a deleted branch named like a hash


@case("a HEAD change the reflog missed (symbolic-ref without -m) makes the reflog undecided, not wrong")
def _():
    sb = Sandbox("missed-head")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "feat/b", at="2026-10-10T00:00:00Z")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")                    # nothing written to the reflog
    capture(sb, write_transcript(sb.root / "proj", "sess-missed", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo, "feat/b")]))
    assert attributed(sb) == {"msg_1": ("feat/b", "transcript")}, attributed(sb)


@case("read_complete_lines stops at the size seen on opening: lines appended later wait for the next capture")
def _():
    path = ROOT / "grow.jsonl"
    path.write_bytes(b"a\nb\nc")                                           # `c` has no newline yet
    lines = ledger_cost.read_complete_lines(path, 0)
    assert next(lines) == (2, b"a")
    with open(path, "ab") as handle:
        handle.write(b"d\ne\n")
    assert list(lines) == [(4, b"b")]                                       # `c`, `d`, `e` are not read
    assert list(ledger_cost.read_complete_lines(path, 4)) == [(7, b"cd"), (9, b"e")]
    assert list(ledger_cost.read_complete_lines(path, 9)) == []


@case("branch_at bisects the events: many requests on a long reflog stay fast and correct")
def _():
    count = 50000
    text = "\n".join(f"HEAD@{{{1760000000 + 2 * n}}}\tcheckout: moving from b{n} to b{n + 1}"
                     for n in reversed(range(count)))
    log = ledger_cost.parse_reflog(text)
    assert len(log.events) == count and log.oldest == 1760000000
    checkouts = ledger_cost.Checkouts()
    checkouts.cache[("top", "/r")] = "/r"
    checkouts.cache[("moves", "/r")] = log
    for n in range(count + 1):
        checkouts.cache[("ref", "/r", f"refs/heads/b{n}")] = "sha"
    started = time.monotonic()
    for n in range(0, count, 3):
        # event n is at 1760000000 + 2n; one second later the first later event is n + 1: HEAD was on b{n+1}
        assert checkouts.branch_at("/r", 1760000000 + 2 * n + 1) == f"b{n + 1}"
    assert time.monotonic() - started < 3, "branch_at scans the events"


@case("when the reflog cannot be read the transcript's gitBranch applies as before")
def _():
    sb = Sandbox("no-reflog")
    repo = make_repo(sb.root / "repo")
    git(repo, "config", "core.logAllRefUpdates", "false")
    shutil.rmtree(repo / ".git" / "logs")      # no reflog at all: `git reflog show HEAD` prints nothing
    wt = sb.root / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feat/wt", str(wt))
    shutil.rmtree(repo / ".git" / "worktrees" / "wt" / "logs", ignore_errors=True)   # the worktree has no reflog either
    sub = sb.root / "proj" / "sess-nolog" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-w1.jsonl").write_text(assistant("msg_w1", "2026-10-10T00:00:01Z", wt, "feat/a", side=True, agent="w1") + "\n")
    (sub / "agent-w1.meta.json").write_text(json.dumps({"agentType": "implementer", "worktreePath": str(wt)}))
    capture(sb, write_transcript(sb.root / "proj", "sess-nolog", [
        assistant("msg_1", "2026-10-10T00:00:01Z", repo, "feat/a"),
        assistant("msg_2", "2026-10-10T00:00:01Z", repo, "no/such-branch"),
        assistant("msg_3", "2026-10-10T00:00:01Z", repo, "HEAD")]))
    assert attributed(sb) == {"msg_1": ("feat/a", "transcript"), "msg_2": (None, "unknown"), "msg_3": (None, "unknown"),
                              "msg_w1": ("feat/wt", "worktree_at_capture")}, attributed(sb)


@case("a worktree subagent gets its worktree's branch; a subagent without a worktree gets its cwd's branch")
def _():
    sb = Sandbox("worktree")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "feat/b", at="2026-10-10T00:00:00Z")
    wt = sb.root / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feat/wt", str(wt), at="2026-10-10T00:00:00Z")
    main = write_transcript(sb.root / "proj", "sess-wt", [assistant("msg_main", "2026-10-10T00:00:00Z", repo, "feat/a")])
    sub = sb.root / "proj" / "sess-wt" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-w1.jsonl").write_text(
        assistant("msg_w1", "2026-10-10T00:00:01Z", wt, "feat/a", side=True, agent="w1") + "\n")
    (sub / "agent-w1.meta.json").write_text(json.dumps(
        {"agentType": "implementer", "worktreePath": str(wt), "worktreeBranch": "feat/wt", "spawnedWithWorktree": True}))
    (sub / "agent-e1.jsonl").write_text(
        assistant("msg_e1", "2026-10-10T00:00:02Z", repo, "feat/b", side=True, agent="e1") + "\n")
    (sub / "agent-e1.meta.json").write_text(json.dumps({"agentType": "Explore"}))
    capture(sb, main)
    got = {r["id"]: r for r in sb.pending()}
    w = got["claude:msg_w1"]
    assert (w["branch"], w["attribution_source"], w["role"], w["agent_type"], w["agent_id"]) == \
        ("feat/wt", "reflog", "subagent", "implementer", "w1"), w
    e = got["claude:msg_e1"]
    assert (e["branch"], e["attribution_source"], e["agent_type"]) == ("feat/b", "reflog", "Explore"), e
    assert got["claude:msg_main"]["role"] == "main" and got["claude:msg_main"]["agent_type"] is None


@case("a removed worktree and a detached HEAD give unknown")
def _():
    sb = Sandbox("unknown")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "--detach", at="2026-10-09T00:00:00Z")   # the main checkout is detached: any gitBranch is moot
    gone, detached = sb.root / "gone", sb.root / "detached"
    git(repo, "worktree", "add", "-q", "-b", "feat/gone", str(gone))
    git(repo, "worktree", "add", "-q", "--detach", str(detached))
    sub = sb.root / "proj" / "sess-u" / "subagents"
    sub.mkdir(parents=True)
    for name, path in (("g1", gone), ("d1", detached)):
        (sub / f"agent-{name}.jsonl").write_text(assistant(f"msg_{name}", "2026-10-10T00:00:01Z", path, "feat/a", side=True) + "\n")
        (sub / f"agent-{name}.meta.json").write_text(json.dumps({"agentType": "implementer", "worktreePath": str(path)}))
    git(repo, "worktree", "remove", "--force", str(gone))
    main = write_transcript(sb.root / "proj", "sess-u", [
        assistant("msg_head", "2026-10-10T00:00:00Z", repo, "HEAD"),
        assistant("msg_empty", "2026-10-10T00:00:00Z", repo, ""),
        assistant("msg_fake", "2026-10-10T00:00:00Z", repo, "no/such-branch"),
        assistant("msg_removed_cwd", "2026-10-10T00:00:00Z", gone, "feat/gone")])
    capture(sb, main)
    for r in sb.pending():
        assert (r["branch"], r["attribution_source"]) == (None, "unknown"), r


# ---------------------------------------------------------------- capture: identity

@case("identity is the message id alone, whatever requestId a copy carries; copies count once; a request with no id is kept and never merged")
def _():
    sb = Sandbox("identity")
    repo = make_repo(sb.root / "repo")

    def line(msg, req, ts="2026-10-10T00:00:00Z", **kw):
        rec = json.loads(assistant(msg, ts, repo, "feat/a", req=req, **kw))
        if msg is None:
            del rec["message"]["id"]
        return json.dumps(rec)
    lines = [line("msg_1", "req_1"), line("msg_1", "req_1"), line("msg_2", None), line("msg_2", None),
             line("msg_3", "req_3"), line("msg_3", None),            # one copy lost its requestId
             line(None, None), line(None, None)]
    summary = capture(sb, write_transcript(sb.root / "proj", "sess-id", lines))
    ids = sorted(r["id"] or "" for r in sb.pending())
    assert ids == ["", "", "claude:msg_1", "claude:msg_2", "claude:msg_3"], ids
    assert summary["unidentified"] == 2 and summary["duplicates"] == 3, summary


@case("a request whose copies split across two captures, the first with a requestId and the later without, is counted once")
def _():
    sb = Sandbox("identity-split")
    repo = make_repo(sb.root / "repo")
    path = write_transcript(sb.root / "proj", "sess-split", [
        assistant("msg_s", "2026-10-10T00:00:00Z", repo, "feat/a", req="req_s"),
        assistant("msg_t", "2026-10-10T00:00:01Z", repo, "feat/a")])
    first = capture(sb, path)
    with open(path, "a") as handle:
        handle.write(assistant("msg_s", "2026-10-10T00:00:00Z", repo, "feat/a") + "\n")   # a later copy, no requestId
        handle.write(assistant("msg_t", "2026-10-10T00:00:01Z", repo, "feat/a", req="req_t") + "\n")  # and the reverse
    second = capture(sb, path)
    assert first["new"] == 2 and second["new"] == 0 and second["duplicates"] == 2, (first, second)
    assert sorted(r["id"] for r in sb.pending()) == ["claude:msg_s", "claude:msg_t"], sb.pending()
    assert sb.report()["requests"] == 2


@case("a forked transcript counts a request once even when its copies differ in requestId")
def _():
    sb = Sandbox("fork-request-id")
    repo = make_repo(sb.root / "repo")
    capture(sb, write_transcript(sb.root / "proj", "sess-parent", [
        assistant("msg_f", "2026-10-10T00:00:00Z", repo, "feat/a", req="req_f"),
        assistant("msg_g", "2026-10-10T00:00:01Z", repo, "feat/a")]))
    capture(sb, write_transcript(sb.root / "proj", "sess-fork", [
        assistant("msg_f", "2026-10-10T00:00:00Z", repo, "feat/a"),
        assistant("msg_g", "2026-10-10T00:00:01Z", repo, "feat/a", req="req_g")]))
    assert len(sb.pending()) == 4
    report = sb.report()
    assert report["requests"] == 2 and report["unknown"]["id_conflicts"] == 0, (report["requests"], report["unknown"])


@case("an id conflict is kept once and reported")
def _():
    sb = Sandbox("conflict")
    repo = make_repo(sb.root / "repo")
    lines = [assistant("msg_c", "2026-10-10T00:00:00Z", repo, "feat/a", use=usage(1000, 5)),
             assistant("msg_c", "2026-10-10T00:00:01Z", repo, "feat/a", use=usage(1000, 9)),
             assistant("msg_ok", "2026-10-10T00:00:02Z", repo, "feat/a")]
    summary = capture(sb, write_transcript(sb.root / "proj", "sess-conf", lines))
    assert summary["conflicts"] == 1 and summary["new"] == 2, summary
    assert [r["output"] for r in sb.pending() if r["id"] == "claude:msg_c"] == [5]
    report = sb.report()
    assert report["unknown"]["id_conflicts"] == 1, report["unknown"]


@case("a forked transcript counts the shared requests once; differing copies across sessions are conflicts")
def _():
    sb = Sandbox("fork")
    repo = make_repo(sb.root / "repo")
    shared = [assistant(f"msg_{i}", f"2026-10-10T00:00:0{i}Z", repo, "feat/a") for i in range(1, 4)]
    own1 = [assistant("msg_own1", "2026-10-10T00:01:00Z", repo, "feat/a")]
    own2 = [shared[0], shared[2],
            assistant("msg_2", "2026-10-10T00:00:02Z", repo, "feat/a", use=usage(1000, 77)),  # this copy differs
            assistant("msg_own2", "2026-10-10T00:02:00Z", repo, "feat/a")]
    capture(sb, write_transcript(sb.root / "proj", "sess-one", shared + own1))
    capture(sb, write_transcript(sb.root / "proj", "sess-two", own2))
    assert len(sb.pending()) == 8
    report = sb.report()
    assert report["requests"] == 5, report["requests"]  # msg_1..3, own1, own2
    assert report["unknown"]["id_conflicts"] == 1, report["unknown"]


def codex_transcript(path: Path, session: str, model: str = "gpt-test") -> None:
    def tc(total, last):
        return json.dumps({"type": "event_msg", "timestamp": "2026-10-10T00:00:05Z", "payload": {
            "type": "token_count", "info": {"total_token_usage": total, "last_token_usage": last}}})
    first = {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10}
    second_last = {"input_tokens": 50, "cached_input_tokens": 10, "output_tokens": 5}
    second_total = {"input_tokens": 150, "cached_input_tokens": 50, "output_tokens": 15}
    path.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"id": session}}),
        json.dumps({"type": "turn_context", "payload": {"model": model}}),
        tc(first, first), tc(second_total, second_last)]) + "\n")


@case("a Codex request gets the branch its cwd's reflog names at the request's time")
def _():
    sb = Sandbox("codex-branch")
    repo = make_repo(sb.root / "repo")
    git(repo, "branch", "feat/c")
    git(repo, "checkout", "-q", "feat/c", at="2026-10-10T00:00:00Z")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-10T00:00:06Z")
    directory = sb.root / "codex"
    directory.mkdir()
    codex_transcript(directory / "rollout-c.jsonl", "sess-codex-c")
    lines = (directory / "rollout-c.jsonl").read_text().splitlines()
    lines.insert(1, json.dumps({"type": "turn_context", "payload": {"model": "gpt-test", "cwd": str(repo)}}))
    (directory / "rollout-c.jsonl").write_text("\n".join(lines) + "\n")       # both token_count rows are at 00:00:05
    code, out, err = sb.ledger_cmd("capture", "--runtime", "codex", "--transcripts", str(directory), "--json")
    assert code == 0, err
    assert {(r["repository"], r["branch"], r["attribution_source"]) for r in sb.pending()} == \
        {("acme/widgets", "feat/c", "reflog")}, sb.pending()
    assert len(sb.pending()) == 2


@case("Codex ids from two sessions never merge, and a resumed capture reads only the new snapshots")
def _():
    sb = Sandbox("codex")
    directory = sb.root / "codex"
    directory.mkdir()
    codex_transcript(directory / "rollout-a.jsonl", "sess-codex-a")
    codex_transcript(directory / "rollout-b.jsonl", "sess-codex-b")
    code, out, err = sb.ledger_cmd("capture", "--runtime", "codex", "--transcripts", str(directory), "--json")
    assert code == 0, err
    ids = sorted(r["id"] for r in sb.pending())
    assert ids == ["codex:sess-codex-a:1", "codex:sess-codex-a:2", "codex:sess-codex-b:1", "codex:sess-codex-b:2"], ids
    assert {(r["runtime"], r["session"]) for r in sb.pending()} == {("codex", "sess-codex-a"), ("codex", "sess-codex-b")}
    assert sb.report()["requests"] == 4
    code, out, err = sb.ledger_cmd("capture", "--runtime", "codex", "--transcripts", str(directory), "--json")
    assert code == 0 and all(json.loads(l)["new"] == 0 for l in out.splitlines()), out
    assert len(sb.pending()) == 4


# ---------------------------------------------------------------- capture: reading and privacy

@case("only the allowlisted fields reach a record, the pending file and the store")
def _():
    sb = Sandbox("allowlist")
    store = bare_store(sb)
    repo = make_repo(sb.root / "repo", origin=f"https://user:{SECRET}-token@github.com/acme/widgets.git")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-09T00:00:00Z")
    rec = json.loads(assistant("msg_p", "2026-10-10T00:00:00Z", repo, "feat/a", text=SECRET))
    rec["message"]["content"].append({"type": "tool_use", "name": "Bash", "input": {"command": f"cat /etc/{SECRET}"}})
    rec["toolUseResult"] = {"stdout": SECRET}
    rec["message"]["usage"]["server_tool_use"] = {"note": SECRET}
    capture(sb, write_transcript(sb.root / "proj", "sess-priv", [json.dumps(rec)]))
    for path in (sb.ledger).rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(errors="replace"), f"secret in {path.relative_to(sb.ledger)}"
    assert all(list(r) == list(ledger_cost.FIELDS) for r in sb.pending())
    assert sb.pending()[0]["repository"] == "acme/widgets"
    code, out, err = sb.ledger_cmd("export")
    assert code == 0, err
    blob = subprocess.run(["git", "-C", str(store), "show", "refs/heads/plumb-ledger/claude/sess-priv:records.jsonl"],
                          capture_output=True, text=True).stdout
    assert SECRET not in blob and "feat/a" in blob


@case("a line without its newline is left for the next capture; a second capture reads only the new bytes")
def _():
    sb = Sandbox("partial")
    repo = make_repo(sb.root / "repo")
    first = [assistant(f"msg_{i}", f"2026-10-10T00:00:0{i}Z", repo, "feat/a") for i in (1, 2)]
    third = assistant("msg_3", "2026-10-10T00:00:03Z", repo, "feat/a")
    path = write_transcript(sb.root / "proj", "sess-part", first)
    size = path.stat().st_size
    with open(path, "a") as handle:
        handle.write(third[:40])
    one = capture(sb, path)
    assert one["new"] == 2 and one["files"][0]["offset"] == size, one
    with open(path, "a") as handle:
        handle.write(third[40:] + "\n")
    two = capture(sb, path)
    assert two["new"] == 1 and two["files"][0]["offset_before"] == size, two
    assert two["bytes_read"] == len(third) + 1, two
    three = capture(sb, path)
    assert three["new"] == 0 and three["bytes_read"] == 0, three


# ---------------------------------------------------------------- price

@case("a request is priced with the version in effect at its time, with cache-write multipliers and the long-context tier")
def _():
    versions = ledger_cost.load_prices()
    base = record(1, inp=1_000_000, out=1_000_000, cache_read=1_000_000, w5=1_000_000, w1=1_000_000, model=OPUS)
    cost = ledger_cost.price_request(base, versions)
    # Opus 5.5: input 4, output 20, cache read 0.20, writes 1.25x and 2x of input
    assert cost == {"input": Decimal(4), "output": Decimal(20), "cache_read": Decimal("0.2"),
                    "cache_write_5m": Decimal(5), "cache_write_1h": Decimal(8)}, cost
    small = record(2, model="claude-haiku-5-5", inp=100_000)  # exactly the threshold: base tier
    assert ledger_cost.price_request(small, versions)["input"] == Decimal("0.01")
    large = record(3, model="claude-haiku-5-5", inp=60_000, cache_read=30_000, w5=10_001)  # 100,001 in all
    cost = ledger_cost.price_request(large, versions)
    assert cost["input"] == Decimal("0.03") and cost["cache_read"] == Decimal("0.0015"), cost
    assert cost["cache_write_5m"] == Decimal("10001") * Decimal("0.5") * Decimal("1.25") / Decimal(1000000)
    two = [{"id": "a", "effective_from": "1970-01-01T00:00:00Z", "checked": "x", "source": "x",
            "cache_write_multiplier": {"5m": 1.25, "1h": 2},
            "models": {OPUS: {"input": Decimal(4), "output": Decimal(20), "cache_read": Decimal("0.2")}}},
           {"id": "b", "effective_from": "2026-10-20T00:00:00Z", "checked": "x", "source": "x",
            "cache_write_multiplier": {"5m": 1.25, "1h": 2},
            "models": {OPUS: {"input": Decimal(1), "output": Decimal(20), "cache_read": Decimal("0.2")}}}]
    for version in two:
        version["_from"] = ledger_cost.parse_time(version["effective_from"])
    early = ledger_cost.price_request(record(4, "2026-10-19T23:59:59.000Z", model=OPUS, inp=1_000_000), two)
    late = ledger_cost.price_request(record(5, "2026-10-20T00:00:00.000Z", model=OPUS, inp=1_000_000), two)
    assert (early["input"], late["input"]) == (Decimal(4), Decimal(1)), (early, late)
    assert ledger_cost.price_request(record(6, model=OPUS + "[1m]", inp=1_000_000), versions)["input"] == Decimal(4)


@case("an unknown model or missing token counts give an unknown cost, counted and not zero")
def _():
    sb = Sandbox("unknown-cost")
    repo = make_repo(sb.root / "repo")
    lines = [assistant("msg_ok", "2026-10-10T00:00:00Z", repo, "feat/a"),
             assistant("msg_model", "2026-10-10T00:00:01Z", repo, "feat/a", model="mystery-model-9"),
             assistant("msg_tokens", "2026-10-10T00:00:02Z", repo, "feat/a", use={"input_tokens": 1000, "output_tokens": 0}),
             assistant("msg_time", "not a time", repo, "feat/a")]
    capture(sb, write_transcript(sb.root / "proj", "sess-uc", lines))
    report = sb.report()
    assert report["requests"] == 3 and report["priced"] == 1, report  # the request without a time is outside every period
    assert report["unknown"]["cost"] == 2 and report["unknown"]["time"] == 1, report["unknown"]
    assert Decimal(report["total_cost"]) == Decimal("0.0001"), report["total_cost"]
    rows = {row["name"]: row for row in report["by_model"]}
    assert rows["mystery-model-9"]["unknown_cost"] == 1 and Decimal(rows["mystery-model-9"]["cost"]) == 0
    text = sb.ledger_cmd("report", "--since", "2026-09-01", "--until", "2026-10-31")[1]
    assert "2 with unknown cost" in text and "unknown, counted and not guessed" in text, text


@case("10,000 requests of $0.0001 sum to $1.00 before rounding")
def _():
    sb = Sandbox("decimal")
    put_pending(sb, "s1", [record(i, rid="d") for i in range(10_000)])
    report = sb.report()
    assert report["requests"] == 10_000 and Decimal(report["total_cost"]) == Decimal("1"), report["total_cost"]
    naive = 0.0
    for _ in range(10_000):
        naive += 0.0001
    assert naive != 1.0  # the reason Decimal is used
    text = sb.ledger_cmd("report", "--since", "2026-09-01", "--until", "2026-10-31")[1]
    assert "total cost: $1.00" in text, text


# ---------------------------------------------------------------- task assignment and report

def task_report(sb: Sandbox, rows: list[dict]) -> dict:
    put_pending(sb, "s1", rows)
    prs = sb.root / "prs.json"
    prs.write_text(json.dumps({"repository": "acme/widgets", "pull_requests": [
        {"number": 10, "head_ref": "feat/x", "base_ref": "main", "created_at": "2026-10-01T00:00:00Z", "closed_at": "2026-10-10T00:00:00Z"},
        {"number": 20, "head_ref": "feat/y", "base_ref": "main", "created_at": "2026-10-01T00:00:00Z", "closed_at": "2026-10-05T00:00:00Z"},
        {"number": 21, "head_ref": "feat/y", "base_ref": "main", "created_at": "2026-10-08T00:00:00Z", "closed_at": "2026-10-12T00:00:00Z"},
        {"number": 30, "head_ref": "feat/z", "base_ref": "main", "created_at": "2026-10-01T00:00:00Z", "closed_at": None},
        {"number": 31, "head_ref": "feat/z", "base_ref": "release", "created_at": "2026-10-02T00:00:00Z", "closed_at": None}]}))
    return sb.report("--prs", str(prs))


@case("task assignment: work before the pull request, a reused branch and two open pull requests")
def _():
    sb = Sandbox("tasks")
    rows = [record(1, "2026-09-28T00:00:00.000Z", branch="feat/x"),    # before PR 10 was opened -> PR 10
            record(2, "2026-10-04T00:00:00.000Z", branch="feat/y"),    # reused name, first use -> PR 20
            record(3, "2026-10-09T00:00:00.000Z", branch="feat/y"),    # after PR 20 closed -> PR 21
            record(4, "2026-10-20T00:00:00.000Z", branch="feat/z"),    # two open PRs -> ambiguous
            record(5, "2026-10-20T00:00:00.000Z", branch="main"),      # no pull request has this head
            record(6, "2026-10-20T00:00:00.000Z", branch="feat/x"),    # after PR 10 closed -> none
            record(7, "2026-10-20T00:00:00.000Z", branch=None)]        # unknown attribution
    report = task_report(sb, rows)
    names = by_task(report)
    assert set(names) == {"acme/widgets#10", "acme/widgets#20", "acme/widgets#21", "ambiguous", "no pull request",
                          "unknown attribution"}, names
    counts = {row["name"]: row["requests"] for row in report["by_task"]}
    assert counts == {"acme/widgets#10": 1, "acme/widgets#20": 1, "acme/widgets#21": 1, "ambiguous": 1,
                      "no pull request": 2, "unknown attribution": 1}, counts
    assert (report["unknown"]["ambiguous"], report["unknown"]["no_pull_request"], report["unknown"]["attribution"]) == (1, 2, 1)


@case("--repo keeps one repository's requests and counts the others and the unknown ones without adding them")
def _():
    sb = Sandbox("repo-scope")
    rows = [record(1, model=HAIKU, inp=50_000), record(2, repo="acme/other", model=HAIKU, inp=50_000),
            record(3, repo=None, branch=None, model=HAIKU, inp=50_000)]  # under the long-context tier
    put_pending(sb, "s1", rows)
    everything = sb.report()
    scoped = sb.report("--repo", "ACME/Widgets")
    assert Decimal(everything["total_cost"]) == Decimal("0.015"), everything["total_cost"]
    assert Decimal(scoped["total_cost"]) == Decimal("0.005"), scoped["total_cost"]
    assert scoped["scope"] == {"repository": "ACME/Widgets", "other_repositories": 1, "unknown_repository": 1}, scoped["scope"]
    assert "scope" not in everything


@case("the report breaks cost down by model, frontier share, role, agent type and token kind, and the rework and landed splits")
def _():
    sb = Sandbox("breakdown")
    rows = [record(1, "2026-10-04T00:00:00.000Z", branch="feat/y", model=OPUS, inp=1_000_000, out=100_000, cache_read=500_000, w5=100_000, w1=50_000),
            record(2, "2026-10-09T00:00:00.000Z", branch="feat/y", model=HAIKU, inp=100_000, role="subagent", agent_type="implementer"),
            record(3, "2026-10-04T00:00:00.000Z", branch="feat/x", model="claude-fable-5-1", inp=100_000)]
    report = task_report(sb, rows)
    opus = Decimal(4) + Decimal(2) + Decimal("0.1") + Decimal("0.5") + Decimal("0.4")  # in, out, read, w5, w1
    haiku = Decimal("0.01")
    fable = Decimal(1)
    assert Decimal(report["total_cost"]) == opus + haiku + fable, report["total_cost"]
    assert Decimal(report["frontier_share"]) == ((opus + fable) / (opus + haiku + fable)).quantize(Decimal("0.0001"))
    kinds = {k: Decimal(v) for k, v in report["by_token_kind"].items()}
    assert kinds["output"] == 2 and kinds["cache_write_1h"] == Decimal("0.4"), kinds
    roles = {row["name"]: Decimal(row["cost"]) for row in report["by_role"]}
    assert roles == {"main": opus + fable, "subagent:implementer": haiku}, roles
    assert len(report["by_task_top10"]) == 3
    rework = sb.root / "rework.json"
    # The exact shape `plumb-ledger rework --json` prints (scripts/ledger_changes.py rework_rate):
    # `reworked` is the count, the rows are under `reworked_changes`.
    rework.write_text(json.dumps({"repository": "acme/widgets", "reworked": 1, "reworked_changes": [
        {"repository": "acme/widgets", "number": 20, "fixed_by": [21]}]}))
    changes = sb.root / "changes.jsonl"
    changes.write_text(json.dumps({"kind": "pull_request", "number": 21, "merged_at": "2026-10-12T00:00:00Z", "repository": "acme/widgets"}) + "\n")
    report = sb.report("--prs", str(sb.root / "prs.json"), "--rework", str(rework), "--changes", str(changes))
    assert (Decimal(report["rework"]["cost_of_reworked"]), Decimal(report["rework"]["cost_of_fixes"])) == (opus, haiku), report["rework"]
    assert Decimal(report["landed_split"]["landed"]) == haiku, report["landed_split"]


@case("prs lists pull requests from paginated fixtures (arrays of several pages) and drops those closed before --since")
def _():
    sb = Sandbox("prs")
    env = {"PLUMB_LEDGER_GH_FIXTURES": str(FIXTURES / "gh")}
    out_file = sb.root / "prs.json"
    code, out, err = sb.ledger_cmd("prs", "--repo", "acme/widgets", "--since", "2026-09-15", "--out", str(out_file), extra_env=env)
    assert code == 0, err
    data = json.loads(out_file.read_text())
    assert data["repository"] == "acme/widgets"
    assert [(p["number"], p["head_ref"], p["base_ref"], p["closed_at"]) for p in data["pull_requests"]] == [
        (2, "feat/b", "main", None), (4, "feat/a", "main", "2026-10-06T00:00:00Z")], data
    code, out, err = sb.ledger_cmd("prs", "--repo", "acme/widgets", "--since", "2026-01-01", extra_env=env)
    assert code == 0 and [p["number"] for p in json.loads(out)["pull_requests"]] == [3, 1, 2, 4], out
    code, out, err = sb.ledger_cmd("prs", "--repo", "acme/missing", "--since", "2026-01-01", extra_env=env)
    assert code != 0 and "no fixture" in err


@case("prs asks gh for numbered pages, never --paginate, and keeps gh's first stderr line when it fails")
def _():
    sb = Sandbox("gh-stub")
    stub_dir, log = sb.root / "stub", sb.root / "gh-calls"
    stub_dir.mkdir()
    pull = lambda n: {"number": n, "head": {"ref": f"feat/{n}"}, "base": {"ref": "main"},
                      "created_at": "2026-10-01T00:00:00Z", "closed_at": None}
    page1 = sb.root / "p1.json"
    page2 = sb.root / "p2.json"
    page1.write_text(json.dumps([pull(n) for n in range(1, 101)]))
    page2.write_text(json.dumps([pull(n) for n in range(101, 103)]))
    gh = stub_dir / "gh"
    gh.write_text(f'''#!/bin/sh
echo "$@" >> "{log}"
case "$*" in
  *--paginate*) echo "gh: --paginate is refused here" >&2; exit 1 ;;
  *'&page=1') cat "{page1}" ;;
  *'&page=2') cat "{page2}" ;;
  *'&page=3') echo "HTTP 403: Forbidden (secondline)" >&2; echo "second line" >&2; exit 1 ;;
  *) echo "[]" ;;
esac
''')
    gh.chmod(0o755)
    env = {"PATH": f"{stub_dir}:{os.environ['PATH']}"}
    code, out, err = sb.ledger_cmd("prs", "--repo", "acme/widgets", "--since", "2026-01-01", extra_env=env)
    assert code == 0, err
    assert len(json.loads(out)["pull_requests"]) == 102
    calls = log.read_text().splitlines()
    assert len(calls) == 2 and not any("--paginate" in c for c in calls), calls
    assert calls[0].endswith("&page=1") and calls[1].endswith("&page=2") and "per_page=100" in calls[0], calls
    page2.write_text(json.dumps([pull(n) for n in range(101, 201)]))  # a full page 2: page 3 is asked and refused
    code, out, err = sb.ledger_cmd("prs", "--repo", "acme/widgets", "--since", "2026-01-01", extra_env=env)
    assert code != 0 and "HTTP 403: Forbidden (secondline)" in err and "second line" not in err, err


# ---------------------------------------------------------------- export and the store

def two_sessions(sb: Sandbox) -> None:
    for session, n in (("sess-a", 3), ("sess-b", 4)):
        put_pending(sb, session, [record(i, f"2026-10-10T00:00:0{i}.000Z", session=session, rid=session) for i in range(n)])


@case("two sessions exporting concurrently to a local bare repository both land")
def _():
    sb = Sandbox("concurrent")
    store = bare_store(sb)
    two_sessions(sb)
    procs = [subprocess.Popen([str(LEDGER), "export", "--session", s], env=sb.env, cwd=sb.cwd,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for s in ("sess-a", "sess-b")]
    results = [(p.wait(timeout=120), p.stderr.read()) for p in procs]
    assert all(code == 0 for code, _ in results), results
    assert set(refs(store)) == {"refs/heads/plumb-ledger/claude/sess-a", "refs/heads/plumb-ledger/claude/sess-b"}, refs(store)
    counts = {s: len(subprocess.run(["git", "-C", str(store), "show", f"refs/heads/plumb-ledger/claude/{s}:records.jsonl"],
                                    capture_output=True, text=True).stdout.splitlines()) for s in ("sess-a", "sess-b")}
    assert counts == {"sess-a": 3, "sess-b": 4}, counts
    assert sb.pending() == [] and len(sb.exported()) == 7


@case("a repeated export is a no-op: the same records give the same commit")
def _():
    sb = Sandbox("repeat")
    store = bare_store(sb)
    two_sessions(sb)
    assert sb.ledger_cmd("export")[0] == 0
    first = refs(store)
    assert sb.ledger_cmd("export")[1].strip() == "export: nothing is pending"
    # A lost acknowledgement: the push landed but the records are still pending.
    shutil.rmtree(sb.ledger / "pending", ignore_errors=True)
    shutil.copytree(sb.ledger / "exported", sb.ledger / "pending")
    shutil.rmtree(sb.ledger / "exported")
    code, out, err = sb.ledger_cmd("export")
    assert code == 0, err
    assert refs(store) == first, (first, refs(store))
    commit = first["refs/heads/plumb-ledger/claude/sess-a"]
    meta = subprocess.run(["git", "-C", str(store), "show", "-s", "--format=%an <%ae>|%cn <%ce>|%at|%P", commit],
                          capture_output=True, text=True).stdout.strip()
    assert meta == "plumb-ledger <ledger@plumb.invalid>|plumb-ledger <ledger@plumb.invalid>|" \
        + str(int(ledger_cost.parse_time("2026-10-10T00:00:02.000Z").timestamp())) + "|", meta
    # New records after an export join the old ones: the ref holds the whole session.
    put_pending(sb, "sess-a", [record(9, "2026-10-11T00:00:00.000Z", session="sess-a", rid="sess-a")])
    assert sb.ledger_cmd("export")[0] == 0
    body = subprocess.run(["git", "-C", str(store), "show", "refs/heads/plumb-ledger/claude/sess-a:records.jsonl"],
                          capture_output=True, text=True).stdout
    assert len(body.splitlines()) == 4


@case("two identical unidentified rows both survive export, the store and the report")
def _():
    sb = Sandbox("null-multiplicity")
    store = bare_store(sb)
    twin = record(0, "2026-10-10T00:00:00.000Z", rid=None)
    put_pending(sb, "sess-n", [twin, twin, record(1, "2026-10-10T00:00:01.000Z", rid="n")])
    assert sb.ledger_cmd("export")[0] == 0
    body = subprocess.run(["git", "-C", str(store), "show", "refs/heads/plumb-ledger/claude/sess-n:records.jsonl"],
                          capture_output=True, text=True).stdout
    assert len(body.splitlines()) == 3 and body.count('"id":null') == 2, body
    assert len(sb.exported()) == 3
    shutil.rmtree(sb.ledger / "exported")  # only the store has them now
    report = sb.report("--store-cache", str(sb.root / "cache.git"))
    assert report["requests"] == 3 and report["unknown"]["unidentified"] == 2, report["unknown"]
    assert Decimal(report["total_cost"]) == Decimal("0.0003"), report["total_cost"]


def append_pending(sb: Sandbox, session: str, rows: list[dict]) -> None:
    """What a capture does while an export is running: append to the pending file under the capture lock."""
    path = sb.ledger / "pending" / "claude" / f"{session}.jsonl"
    with ledger_cost.locked(sb.ledger):
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))


def during_first_push(action):
    """Patch ledger_cost.run so that `action()` runs just before the first `git push`; returns the restore function."""
    real, state = ledger_cost.run, {"done": False}

    def hooked(cmd, *args, **kwargs):
        if "push" in cmd and not state["done"]:
            state["done"] = True
            action()
        return real(cmd, *args, **kwargs)
    ledger_cost.run = hooked
    return lambda: setattr(ledger_cost, "run", real)


def export_quietly(sb: Sandbox, session: str, store: Path) -> None:
    """In-process export; the caller silences stdout once (redirects from several threads would not nest)."""
    ledger_cost.export_session(sb.ledger, "claude", session, str(store))


def stored_lines(store: Path, session: str) -> list[str]:
    return subprocess.run(["git", "-C", str(store), "show", f"refs/heads/plumb-ledger/claude/{session}:records.jsonl"],
                          capture_output=True, text=True).stdout.splitlines()


@case("two overlapping exports of one session never leave an older snapshot over a newer one")
def _():
    with contextlib.redirect_stdout(io.StringIO()):
        sb = Sandbox("export-race")
        store = bare_store(sb)
        session = "sess-race"
        put_pending(sb, session, [record(i, f"2026-10-10T00:00:0{i}.000Z", session=session, rid=session) for i in range(3)])
        newer = record(3, "2026-10-10T00:00:03.000Z", session=session, rid=session)
        second: list = []

        def overlap():
            append_pending(sb, session, [newer])      # a capture lands after the first export took its snapshot ...

            def other():                              # ... and a second export of the same session starts
                try:
                    export_quietly(sb, session, store)
                except BaseException as error:  # noqa: BLE001 - reported by the assertion below
                    second.append(error)
            thread = threading.Thread(target=other)
            second.append(thread)
            thread.start()
            thread.join(1.0)                          # without a per-session lock it finishes in this time
        restore = during_first_push(overlap)
        try:
            export_quietly(sb, session, store)
        finally:
            restore()
        second[0].join(60)
        assert len(second) == 1, second
        want = sorted(f"claude:{session}{i}" for i in range(4))
        assert sorted(json.loads(l)["id"] for l in stored_lines(store, session)) == want, stored_lines(store, session)
        assert sorted(r["id"] for r in sb.exported()) == want and sb.pending() == [], (sb.exported(), sb.pending())


@case("rows captured while an export pushes stay pending, even a twin of an unidentified row in the snapshot")
def _():
    with contextlib.redirect_stdout(io.StringIO()):
        sb = Sandbox("export-append")
        store = bare_store(sb)
        session = "sess-append"
        twin = record(0, "2026-10-10T00:00:00.000Z", rid=None)
        put_pending(sb, session, [twin, record(1, "2026-10-10T00:00:01.000Z", rid=session)])
        late = record(2, "2026-10-10T00:00:02.000Z", rid=session)
        restore = during_first_push(lambda: append_pending(sb, session, [twin, late]))
        try:
            export_quietly(sb, session, store)
        finally:
            restore()
        assert len(stored_lines(store, session)) == 2
        assert sorted(r["id"] or "" for r in sb.pending()) == ["", f"claude:{session}2"], sb.pending()
        export_quietly(sb, session, store)
        assert len(stored_lines(store, session)) == 4 and sb.pending() == [], stored_lines(store, session)


def conflict_lines(lines: list[str], repo: Path, second_output: int = 9) -> list[str]:
    return lines + [assistant("msg_c", "2026-10-10T00:00:00Z", repo, "feat/a", use=usage(1000, 5)),
                    assistant("msg_c", "2026-10-10T00:00:01Z", repo, "feat/a", use=usage(1000, second_output)),
                    assistant("msg_ok", "2026-10-10T00:00:02Z", repo, "feat/a")]


def store_only_report(sb: Sandbox) -> dict:
    """The report as another machine sees it: an empty local ledger and the store."""
    empty = sb.root / "empty-ledger"
    empty.mkdir(exist_ok=True)
    code, out, err = sb.ledger_cmd("report", "--since", "2026-09-01", "--until", "2026-10-31", "--json",
                                   "--store-cache", str(sb.root / "other-cache.git"), extra_env={"PLUMB_LEDGER_DIR": str(empty)})
    assert code == 0, err
    return json.loads(out)


@case("conflicting copies travel in the exported commit, ids only, so a report from the store alone shows them")
def _():
    sb = Sandbox("conflict-export")
    store = bare_store(sb)
    repo = make_repo(sb.root / "repo")
    capture(sb, write_transcript(sb.root / "proj", "sess-cx", conflict_lines([], repo)))
    capture(sb, write_transcript(sb.root / "proj", "sess-plain", [assistant("msg_p", "2026-10-10T00:00:00Z", repo, "feat/a")]))
    assert sb.ledger_cmd("export")[0] == 0
    tree = subprocess.run(["git", "-C", str(store), "ls-tree", "--name-only", "refs/heads/plumb-ledger/claude/sess-cx"],
                          capture_output=True, text=True).stdout.split()
    assert tree == ["conflicts.jsonl", "records.jsonl"], tree
    body = subprocess.run(["git", "-C", str(store), "show", "refs/heads/plumb-ledger/claude/sess-cx:conflicts.jsonl"],
                          capture_output=True, text=True).stdout
    assert body == '{"id": "claude:msg_c"}\n', body
    plain = subprocess.run(["git", "-C", str(store), "ls-tree", "--name-only", "refs/heads/plumb-ledger/claude/sess-plain"],
                           capture_output=True, text=True).stdout.split()
    assert plain == ["records.jsonl"], plain
    first = refs(store)
    assert sb.ledger_cmd("export")[1].strip() == "export: nothing is pending"
    assert refs(store) == first
    report = store_only_report(sb)
    assert report["requests"] == 3 and report["unknown"]["id_conflicts"] == 1, (report["requests"], report["unknown"])


@case("a conflict found by a later capture that adds no rows is exported too")
def _():
    sb = Sandbox("conflict-late")
    store = bare_store(sb)
    repo = make_repo(sb.root / "repo")
    path = write_transcript(sb.root / "proj", "sess-late", [assistant("msg_c", "2026-10-10T00:00:00Z", repo, "feat/a", use=usage(1000, 5))])
    capture(sb, path)
    assert sb.ledger_cmd("export")[0] == 0
    before = refs(store)
    with open(path, "a") as handle:
        handle.write(assistant("msg_c", "2026-10-10T00:00:01Z", repo, "feat/a", use=usage(1000, 9)) + "\n")
    summary = capture(sb, path)
    assert summary["new"] == 0 and summary["conflicts"] == 1, summary
    assert sb.ledger_cmd("export")[0] == 0
    assert refs(store) != before
    assert store_only_report(sb)["unknown"]["id_conflicts"] == 1
    after = refs(store)
    assert sb.ledger_cmd("export")[1].strip() == "export: nothing is pending" and refs(store) == after


@case("an export with an unreachable store exits non-zero, keeps the records pending, and the report shows incomplete coverage")
def _():
    sb = Sandbox("unreachable")
    sb.set_config(f"ledger.store = {sb.root / 'does-not-exist.git'}\n")
    two_sessions(sb)
    code, out, err = sb.ledger_cmd("export")
    assert code != 0 and "stay pending" in err, (code, err)
    assert len(sb.pending()) == 7 and sb.exported() == []
    report = sb.report()
    cov = report["coverage"]
    assert cov["complete"] is False and cov["pending_records"] == 7 and cov["pending_sessions"] == 2, cov
    assert cov["store"] == "unreachable", cov
    text = sb.ledger_cmd("report", "--since", "2026-09-01", "--until", "2026-10-31")[1]
    assert "coverage: INCOMPLETE" in text and "pending export: 7 requests in 2 session(s)" in text, text


@case("credentials in the store URL are never printed")
def _():
    sb = Sandbox("secret-url")
    sb.set_config(f"ledger.store = http://deploy:{SECRET}@127.0.0.1:9/private/ledger.git\n")
    two_sessions(sb)
    code, out, err = sb.ledger_cmd("export")
    code2, out2, err2 = sb.ledger_cmd("export", "--check")
    code3, out3, err3 = sb.ledger_cmd("report", "--since", "2026-09-01", "--until", "2026-10-31")
    assert code != 0 and code2 != 0 and code3 == 0
    for text in (out, err, out2, err2, out3, err3):
        assert SECRET not in text, text
    assert out2.startswith("NG "), out2
    doctor = subprocess.run(["bash", str(PLUGIN / "scripts" / "doctor.sh"), str(PLUGIN)], capture_output=True, text=True,
                            env={**sb.env, "PLUMB_IN_SELFTEST": "1"}, cwd=sb.cwd).stdout
    assert SECRET not in doctor
    line = [l for l in doctor.splitlines() if "ledger.store" in l]
    assert line and line[0].startswith("  NG "), doctor


@case("an unset store exits 0 and says records stay local and cloud sessions are not covered")
def _():
    sb = Sandbox("unset")
    sb.set_config("")
    two_sessions(sb)
    code, out, err = sb.ledger_cmd("export")
    assert code == 0 and "stay local" in out and "cloud sessions are not covered" in out, out
    assert len(sb.pending()) == 7
    report = sb.report()
    assert report["coverage"]["store"] == "unset" and report["coverage"]["complete"] is False
    assert "cloud sessions are not covered" in report["coverage"]["note"]


@case("the report reads the store's refs: records exported elsewhere count once, local copies merge with them")
def _():
    sb = Sandbox("from-store")
    bare_store(sb)
    two_sessions(sb)
    assert sb.ledger_cmd("export")[0] == 0
    before = sb.report()
    assert before["requests"] == 7 and before["coverage"]["complete"] is True, before["coverage"]
    shutil.rmtree(sb.ledger / "exported")  # another machine: only the store has them
    after = sb.report("--store-cache", str(sb.root / "cache.git"))
    assert after["requests"] == 7 and after["coverage"]["store"] == "ok"
    put_pending(sb, "sess-a", [record(i, f"2026-10-10T00:00:0{i}.000Z", session="sess-a", rid="sess-a") for i in range(3)])
    assert sb.report()["requests"] == 7  # the same ids in pending and in the store are one request each


@case("a session ref deleted from the store no longer counts in the report")
def _():
    sb = Sandbox("store-prune")
    store = bare_store(sb)
    two_sessions(sb)
    assert sb.ledger_cmd("export")[0] == 0
    shutil.rmtree(sb.ledger / "exported")  # the store is the only holder
    assert sb.report()["requests"] == 7
    subprocess.run(["git", "-C", str(store), "update-ref", "-d", "refs/heads/plumb-ledger/claude/sess-b"], check=True)
    report = sb.report()
    assert report["requests"] == 3 and report["coverage"]["store"] == "ok", report["requests"]


@case("switching ledger.store never counts the old store's sessions; the cache is keyed by the URL without credentials")
def _():
    sb = Sandbox("store-switch")
    bare_store(sb)
    two_sessions(sb)
    assert sb.ledger_cmd("export")[0] == 0
    shutil.rmtree(sb.ledger / "exported")
    assert sb.report()["requests"] == 7
    other = sb.root / "other-store.git"
    subprocess.run(["git", "init", "--bare", "-q", str(other)], check=True)
    sb.set_config(f"ledger.capture = on\nledger.store = {other}\n")
    put_pending(sb, "sess-c", [record(i, f"2026-10-11T00:00:0{i}.000Z", session="sess-c", rid="sess-c") for i in range(2)])
    assert sb.ledger_cmd("export")[0] == 0
    shutil.rmtree(sb.ledger / "exported")
    assert sb.report()["requests"] == 2, "the old store's sessions are still counted"
    caches = sorted(p.name for p in sb.ledger.glob("store-cache*.git"))
    assert len(caches) == 2, caches   # one cache per store URL
    secret_url = f"http://deploy:{SECRET}@127.0.0.1:9/private/ledger.git"
    plain_url = "http://127.0.0.1:9/private/ledger.git"
    assert SECRET not in ledger_cost.store_cache_name(secret_url)
    assert ledger_cost.store_cache_name(secret_url) == ledger_cost.store_cache_name(plain_url)
    assert ledger_cost.store_cache_name(plain_url) != ledger_cost.store_cache_name(plain_url + "x")


# ---------------------------------------------------------------- the hook

def hook_input(sb: Sandbox, transcript: Path, cwd: Path) -> str:
    return json.dumps({"session_id": transcript.stem, "transcript_path": str(transcript), "cwd": str(cwd)})


def python_shim(sb: Sandbox) -> tuple[Path, Path]:
    """A python3 on PATH that leaves a mark when started and another when it exits."""
    shim_dir, mark = sb.root / "shim", sb.root / "python-started"
    shim_dir.mkdir()
    real = shutil.which("python3")
    # Not exec: the shim outlives the real python by one line so it can mark the end. A process
    # table is not portable (macOS has no /proc), the mark file is.
    (shim_dir / "python3").write_text(f'#!/bin/sh\necho started >> "{mark}"\n"{real}" "$@"\nstatus=$?\n'
                                      f'echo finished >> "{mark}"\nexit $status\n')
    (shim_dir / "python3").chmod(0o755)
    return shim_dir, mark


def run_hook(sb: Sandbox, payload: str, path_prefix: Path | None = None) -> float:
    env = dict(sb.env)
    if path_prefix:
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
    start = time.perf_counter()
    out = subprocess.run(["bash", str(PLUGIN / "scripts" / "ledger-capture.sh")], input=payload, text=True,
                         capture_output=True, env=env, cwd=sb.cwd)
    elapsed = time.perf_counter() - start
    assert out.returncode == 0 and out.stdout == "" and out.stderr == "", (out.returncode, out.stdout, out.stderr)
    return elapsed


@case("with capture off the hook returns in under 50 ms without starting Python")
def _():
    sb = Sandbox("hook-off")
    repo = make_repo(sb.root / "repo")
    transcript = write_transcript(sb.root / "proj", "sess-off", [assistant("msg_1", "2026-10-10T00:00:00Z", repo, "feat/a")])
    shim, mark = python_shim(sb)
    payload = hook_input(sb, transcript, repo)
    for config_text in ("ledger.capture = off\n", "", "ledger.capture = yes\n"):
        sb.set_config(config_text)
        times = [run_hook(sb, payload, shim) for _ in range(10)]
        assert statistics.median(times) < 0.05, f"median {statistics.median(times) * 1000:.1f} ms for [{config_text.strip()}]"
        print(f"       hook, capture off [{config_text.strip() or 'empty config'}]: median {statistics.median(times) * 1000:.1f} ms, max {max(times) * 1000:.1f} ms")
    os.remove(sb.config)  # no config file at all
    assert run_hook(sb, payload, shim) < 0.2
    time.sleep(0.3)
    assert not mark.exists() and not sb.ledger.exists(), "Python was started or state was written with capture off"


def wait_for(predicate, seconds: float = 180) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.2)
    return False


@case("with capture on the hook adds under 200 ms at p95 on a 50 MB transcript, and a second capture reads only the new bytes")
def _():
    sb = Sandbox("hook-on")
    repo = make_repo(sb.root / "repo")
    session = "sess-big"
    path = sb.root / "proj" / f"{session}.jsonl"
    path.parent.mkdir()
    padding = "x" * 3800
    distinct = 0
    with open(path, "w") as handle:
        written = 0
        while written < 50 * 1024 * 1024:
            distinct += 1
            row = assistant(f"msg_{distinct}", "2026-10-10T00:00:00Z", repo, "feat/a", text=padding) + "\n"
            handle.write(row * 2)  # two copies of every request
            written += 2 * len(row)
    size = path.stat().st_size
    assert size >= 50 * 1024 * 1024
    payload = hook_input(sb, path, repo)
    shim, mark = python_shim(sb)
    times = sorted(run_hook(sb, payload, shim) for _ in range(24))
    p95 = times[math.ceil(0.95 * len(times)) - 1]  # nearest rank
    assert p95 < 0.2, f"p95 {p95 * 1000:.0f} ms (max {times[-1] * 1000:.0f} ms)"
    print(f"       hook, capture on, {size / 1e6:.0f} MB transcript, {len(times)} runs: median {statistics.median(times) * 1000:.1f} ms, "
          f"p95 {p95 * 1000:.1f} ms, max {times[-1] * 1000:.1f} ms")
    state_file = sb.ledger / "state" / "claude" / f"{session}.json"

    def captured() -> bool:
        try:
            return json.loads(state_file.read_text())["files"][str(path)]["offset"] == size
        except (OSError, ValueError, KeyError):
            return False
    assert wait_for(captured), "the background capture did not finish"
    assert wait_for(lambda: len(sb.pending()) == distinct), (len(sb.pending()), distinct)
    # Every queued hook run must have finished (they find nothing new) before the next bytes are appended.
    assert wait_for(lambda: mark.read_text().count("finished") == 24), "hook runs did not drain"
    extra = [assistant(f"msg_new{i}", "2026-10-10T01:00:00Z", repo, "feat/a") for i in range(3)]
    with open(path, "a") as handle:
        handle.write("\n".join(extra) + "\n")
    appended = sum(len(l) + 1 for l in extra)
    code, out, err = sb.ledger_cmd("capture", "--json", "--transcript", str(path))
    summary = json.loads(out.splitlines()[0])
    assert code == 0 and summary["new"] == 3 and summary["bytes_read"] == appended, summary
    assert summary["files"][0]["offset_before"] == size and summary["files"][0]["offset"] == size + appended
    assert len(sb.pending()) == distinct + 3


@case("a failing capture in the hook never fails the turn")
def _():
    sb = Sandbox("hook-fail")
    payload = json.dumps({"session_id": "nope", "transcript_path": str(sb.root / "missing.jsonl"), "cwd": str(sb.cwd)})
    assert run_hook(sb, payload) < 0.5
    run_hook(sb, "not json at all")
    run_hook(sb, "")
    time.sleep(1)


# ---------------------------------------------------------------- export at the end of a turn

def hook_shims(sb: Sandbox) -> tuple[Path, Path, Path]:
    """The python3 shim plus a git shim that logs every call, so a test can count pushes."""
    shim, mark = python_shim(sb)
    log = sb.root / "git-calls"
    real = shutil.which("git")
    (shim / "git").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexec "{real}" "$@"\n')
    (shim / "git").chmod(0o755)
    return shim, mark, log


def pushes(log: Path) -> int:
    return sum(1 for line in log.read_text().splitlines() if " push " in f" {line} ") if log.exists() else 0


def finished(mark: Path, runs: int):
    return lambda: mark.exists() and mark.read_text().count("finished") >= runs


def on_stop_sandbox(name: str, config_extra: str = "ledger.export = on-stop\n", store: bool = True):
    sb = Sandbox(name)
    repo = make_repo(sb.root / "repo")
    if store:
        bare = bare_store(sb)
    else:
        bare = None
    sb.set_config(sb.config.read_text() + config_extra)
    return sb, repo, bare


def turn(sb: Sandbox, repo: Path, session: str, count: int, first: int, shim: Path) -> float:
    """Append `count` requests to the session's transcript and run the Stop hook once."""
    lines = [assistant(f"msg_{session}_{first + i}", f"2026-10-10T00:00:{first + i:02d}Z", repo, "feat/a") for i in range(count)]
    path = sb.root / "proj" / f"{session}.jsonl"
    path.parent.mkdir(exist_ok=True)
    with open(path, "a") as handle:
        handle.write("\n".join(lines) + "\n")
    return run_hook(sb, hook_input(sb, path, repo), shim)


@case("ledger.export = on-stop: the hook pushes that session after its capture, only that session, only when something is new")
def _():
    sb, repo, store = on_stop_sandbox("stop-push")
    shim, mark, log = hook_shims(sb)
    put_pending(sb, "other", [record(0, session="other", rid="other")])
    elapsed = turn(sb, repo, "sess-stop", 2, 0, shim)
    assert elapsed < 0.2, f"the hook took {elapsed * 1000:.0f} ms"
    print(f"       hook, ledger.export = on-stop: returned in {elapsed * 1000:.1f} ms")
    ref = "refs/heads/plumb-ledger/claude/sess-stop"
    assert wait_for(lambda: ref in refs(store), 60) and wait_for(finished(mark, 1), 60), refs(store)
    assert len(stored_lines(store, "sess-stop")) == 2
    assert wait_for(lambda: not any(r["session"] == "sess-stop" for r in sb.pending()), 30), "pushed rows stay pending"
    assert len([r for r in sb.exported() if r["session"] == "sess-stop"]) == 2
    assert [r["session"] for r in sb.pending()] == ["other"], "another session's pending rows were exported or lost"
    assert list(refs(store)) == [ref], refs(store)
    # A second turn with new requests pushes the session again, with all of its records.
    first_commit = refs(store)[ref]
    turn(sb, repo, "sess-stop", 1, 2, shim)
    assert wait_for(lambda: refs(store).get(ref) not in (None, first_commit), 60) and wait_for(finished(mark, 2), 60)
    assert len(stored_lines(store, "sess-stop")) == 3
    # A turn that captures nothing new does not push (counted on git's own calls).
    before = pushes(log)
    path = sb.root / "proj" / "sess-stop.jsonl"
    run_hook(sb, hook_input(sb, path, repo), shim)
    assert wait_for(finished(mark, 3), 60)
    time.sleep(0.3)
    assert pushes(log) == before and refs(store)[ref] != first_commit, "a turn with nothing new pushed"
    assert not (sb.ledger / "capture.log").exists(), (sb.ledger / "capture.log").read_text()


@case("on-stop: a turn that finds only a conflicting copy of an exported request still pushes the conflict")
def _():
    sb, repo, store = on_stop_sandbox("stop-conflict")
    shim, mark, log = hook_shims(sb)
    path = sb.root / "proj" / "sess-cf.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text(assistant("msg_cf", "2026-10-10T00:00:00Z", repo, "feat/a", use=usage(1000, 5)) + "\n")
    run_hook(sb, hook_input(sb, path, repo), shim)
    ref = "refs/heads/plumb-ledger/claude/sess-cf"
    assert wait_for(lambda: ref in refs(store), 60) and wait_for(finished(mark, 1), 60), refs(store)
    first = refs(store)[ref]
    with open(path, "a") as handle:  # the same request again, with different usage: a conflict, no new row
        handle.write(assistant("msg_cf", "2026-10-10T00:00:01Z", repo, "feat/a", use=usage(1000, 9)) + "\n")
    run_hook(sb, hook_input(sb, path, repo), shim)
    assert wait_for(finished(mark, 2), 60)
    assert wait_for(lambda: refs(store).get(ref) not in (None, first), 60), "the conflict was not pushed"
    tree = subprocess.run(["git", "-C", str(store), "ls-tree", "--name-only", ref], capture_output=True, text=True).stdout.split()
    assert tree == ["conflicts.jsonl", "records.jsonl"], tree
    assert len(stored_lines(store, "sess-cf")) == 1


@case("ledger.export manual (default or explicit) captures but never pushes")
def _():
    for name, extra in (("stop-manual-default", ""), ("stop-manual-explicit", "ledger.export = manual\n"),
                        ("stop-manual-typo", "ledger.export = on_stop\n")):
        sb, repo, store = on_stop_sandbox(name, extra)
        shim, mark, log = hook_shims(sb)
        turn(sb, repo, "sess-m", 2, 0, shim)
        assert wait_for(finished(mark, 1), 60) and wait_for(lambda: len(sb.pending()) == 2, 30), name
        time.sleep(0.3)
        assert pushes(log) == 0 and refs(store) == {} and sb.exported() == [], f"{name}: pushed with export not on-stop"


@case("on-stop with capture off does nothing, even with a store; with no store it pushes nothing and says so in the log")
def _():
    sb, repo, store = on_stop_sandbox("stop-capture-off")
    sb.set_config(f"ledger.capture = off\nledger.store = {store}\nledger.export = on-stop\n")
    shim, mark, log = hook_shims(sb)
    turn(sb, repo, "sess-off", 1, 0, shim)
    time.sleep(0.5)
    assert not mark.exists() and not sb.ledger.exists() and refs(store) == {}, "capture off must not start Python"
    sb, repo, _ = on_stop_sandbox("stop-no-store", store=False)
    shim, mark, log = hook_shims(sb)
    assert turn(sb, repo, "sess-ns", 2, 0, shim) < 0.2
    assert wait_for(finished(mark, 1), 60) and wait_for(lambda: len(sb.pending()) == 2, 30)
    assert wait_for(lambda: (sb.ledger / "capture.log").exists(), 30)
    assert "export skipped: ledger.store is unset" in (sb.ledger / "capture.log").read_text()
    assert pushes(log) == 0 and sb.exported() == []


@case("a failing push keeps the records pending, logs the error masked, and the hook still returns within its budget")
def _():
    sb, repo, store = on_stop_sandbox("stop-push-fails")
    reject = store / "hooks" / "pre-receive"
    reject.write_text("#!/bin/sh\necho 'rejected by the store' >&2\nexit 1\n")
    reject.chmod(0o755)
    shim, mark, log = hook_shims(sb)
    elapsed = turn(sb, repo, "sess-fail", 2, 0, shim)
    assert elapsed < 0.2, f"the hook took {elapsed * 1000:.0f} ms"
    assert wait_for(finished(mark, 1), 60)
    assert wait_for(lambda: (sb.ledger / "capture.log").exists() and "export failed" in (sb.ledger / "capture.log").read_text(), 30)
    assert len(sb.pending()) == 2 and sb.exported() == [] and refs(store) == {}, "a failed push must leave the records pending"
    # The next turn, with the store healthy again, sends everything that was pending.
    reject.unlink()
    turn(sb, repo, "sess-fail", 1, 2, shim)
    ref = "refs/heads/plumb-ledger/claude/sess-fail"
    assert wait_for(lambda: ref in refs(store), 60) and wait_for(finished(mark, 2), 60)
    assert len(stored_lines(store, "sess-fail")) == 3 and wait_for(lambda: sb.pending() == [], 30)
    # An unreachable store with a credential in its URL: failure logged, secret never written.
    sb, repo, _ = on_stop_sandbox("stop-secret", store=False)
    sb.set_config(f"ledger.capture = on\nledger.export = on-stop\nledger.store = http://deploy:{SECRET}@127.0.0.1:9/private/ledger.git\n")
    shim, mark, log = hook_shims(sb)
    assert turn(sb, repo, "sess-sec", 1, 0, shim) < 0.2
    assert wait_for(finished(mark, 1), 90)
    assert wait_for(lambda: (sb.ledger / "capture.log").exists(), 30)
    logged = (sb.ledger / "capture.log").read_text()
    assert "export failed" in logged and SECRET not in logged, logged
    assert len(sb.pending()) == 1
    assert all(len(line) < 400 for line in logged.splitlines()), "log lines must stay short"


# ---------------------------------------------------------------- sweep: Codex rollouts and OpenCode

BASE_MS = int(datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp() * 1000)
CRED = "CRED-SENTINEL-7c1e"      # held only by a decoy table of the OpenCode fixture
TITLE = "TITLE-SENTINEL-52bd"    # a column the adapter never selects


@contextlib.contextmanager
def sandbox_environ(sb: Sandbox, extra_env: dict | None = None):
    """Run ledger_cost in this process with the sandbox's environment."""
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update({**sb.env, **(extra_env or {})})
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def run_main(sb: Sandbox, *argv: str, extra_env: dict | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with sandbox_environ(sb, extra_env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ledger_cost.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def sweep_json(sb: Sandbox, extra_env: dict | None = None, expect: int = 0) -> tuple[list[dict], list[dict], str]:
    """(session summaries, runtime summaries, stderr) of `capture --sweep --json` run as the CLI."""
    code, out, err = sb.ledger_cmd("capture", "--sweep", "--json", extra_env=extra_env)
    assert code == expect, f"sweep exited {code}: {err}"
    rows = [json.loads(line) for line in out.splitlines()]
    return [r for r in rows if r.get("kind") != "sweep"], [r for r in rows if r.get("kind") == "sweep"], err


def rollout(sb: Sandbox, name: str, session: str, where: str = "sessions/2026/10/10") -> Path:
    path = sb.codex / where / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    codex_transcript(path, session)
    return path


def codex_extend(path: Path) -> None:
    """A third snapshot after the two codex_transcript() writes."""
    total, last = {"input_tokens": 200, "cached_input_tokens": 60, "output_tokens": 20}, \
        {"input_tokens": 50, "cached_input_tokens": 10, "output_tokens": 5}
    with open(path, "a") as handle:
        handle.write(json.dumps({"type": "event_msg", "timestamp": "2026-10-10T00:00:09Z", "payload": {
            "type": "token_count", "info": {"total_token_usage": total, "last_token_usage": last}}}) + "\n")


def bad_rollout(sb: Sandbox, name: str) -> Path:
    """The first snapshot's total is not its last: the normalizer refuses the file."""
    path = sb.codex / "sessions" / "2026" / "10" / "10" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    total, last = {"input_tokens": 200, "cached_input_tokens": 60, "output_tokens": 20}, \
        {"input_tokens": 50, "cached_input_tokens": 10, "output_tokens": 5}
    path.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"id": "sess-codex-bad"}}),
        json.dumps({"type": "event_msg", "timestamp": "2026-10-10T00:00:05Z", "payload": {
            "type": "token_count", "info": {"total_token_usage": total, "last_token_usage": last}}})]) + "\n")
    return path


def log_text(sb: Sandbox) -> str:
    path = sb.ledger / "capture.log"
    return path.read_text() if path.exists() else ""


def omsg(mid: str, sid: str, created: int, *, done: bool | int | None = True, updated: int | None = None,
         inp=100, out=20, reasoning=5, read=30, write=7, model: object = "default", agent: str | None = None,
         extra: dict | None = None) -> tuple:
    """A session_message row of type assistant. `created` is milliseconds after BASE_MS."""
    tokens = {"input": inp, "output": out, "reasoning": reasoning, "cache": {"read": read, "write": write}}
    if reasoning == "absent":
        del tokens["reasoning"]
    data = {"role": "assistant", "time": {"created": BASE_MS + created}, "tokens": tokens,
            "content": [{"type": "text", "text": SECRET}], **(extra or {})}
    if done:
        data["time"]["completed"] = BASE_MS + created + 900
    if model == "default":
        model = {"providerID": "opencode", "id": "deepseek-v4.1-flash-free"}
    if model is not None:
        data["model"] = model
    if agent:
        data["agent"] = agent
    return (mid, sid, "assistant", 1, BASE_MS + created + 1000 if updated is None else updated, json.dumps(data))


def make_opencode(path: Path, sessions: list[tuple], messages: list[tuple], tables: str = "both") -> None:
    """A synthetic OpenCode database: the two tables the adapter reads, columns it must not select,
    and a decoy credential table. sessions: (id, parent_id, directory, model JSON or None)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE credential (id TEXT, token TEXT);"
                       "CREATE TABLE session_v2 (id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT, model TEXT, title TEXT);")
    if tables == "both":
        conn.executescript("CREATE TABLE session_message (id TEXT PRIMARY KEY, session_id TEXT, type TEXT, seq INTEGER, "
                           "time_created INTEGER, time_updated INTEGER, data TEXT);")
    conn.execute("INSERT INTO credential VALUES ('c1', ?)", (CRED,))
    conn.executemany("INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?)", [(*row, TITLE) for row in sessions])
    if tables == "both":
        conn.executemany("INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(m[0], m[1], m[2], m[3], m[4], m[4], m[5]) for m in messages])
    conn.commit()
    conn.close()


def edit_opencode(sb: Sandbox, sql: str, args: tuple = ()) -> None:
    conn = sqlite3.connect(sb.opencode)
    conn.execute(sql, args)
    conn.commit()
    conn.close()


def insert_message(sb: Sandbox, message: tuple) -> None:
    conn = sqlite3.connect(sb.opencode)
    conn.execute("INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (message[0], message[1], message[2], message[3], message[4], message[4], message[5]))
    conn.commit()
    conn.close()


def no_sentinels(sb: Sandbox, *outputs: str) -> None:
    for path in sb.ledger.rglob("*"):
        if path.is_file():
            text = path.read_text(errors="replace")
            assert CRED not in text and TITLE not in text and SECRET not in text, f"a sentinel in {path.relative_to(sb.ledger)}"
    for text in outputs:
        assert CRED not in text and TITLE not in text and SECRET not in text, text


def opencode_rows(sb: Sandbox) -> dict[str, dict]:
    return {r["id"]: r for r in sb.pending() if r["runtime"] == "opencode"}


@case("codex --transcripts reads every depth of a YYYY/MM/DD tree; claude --transcripts stays non-recursive")
def _():
    sb = Sandbox("transcripts-recursive")
    tree = sb.root / "tree"
    for name, session, where in (("rollout-1", "sess-codex-d0", "."), ("rollout-2", "sess-codex-d1", "2026"),
                                 ("rollout-3", "sess-codex-d3", "2026/10/10")):
        (tree / where).mkdir(parents=True, exist_ok=True)
        codex_transcript(tree / where / f"{name}.jsonl", session)
    code, out, err = sb.ledger_cmd("capture", "--runtime", "codex", "--transcripts", str(tree), "--json")
    assert code == 0, err
    assert sorted(json.loads(l)["session"] for l in out.splitlines()) == ["sess-codex-d0", "sess-codex-d1", "sess-codex-d3"], out
    assert len(sb.pending()) == 6
    repo = make_repo(sb.root / "repo")
    claude = sb.root / "claude-tree"
    write_transcript(claude, "top", [assistant("msg_top", "2026-10-10T00:00:00Z", repo, "feat/a")])
    write_transcript(claude / "deeper", "below", [assistant("msg_below", "2026-10-10T00:00:00Z", repo, "feat/a")])
    code, out, err = sb.ledger_cmd("capture", "--transcripts", str(claude), "--json")
    assert code == 0 and [json.loads(l)["session"] for l in out.splitlines()] == ["top"], (out, err)


@case("sweep: Codex rollouts under sessions/ and archived_sessions/ are captured, and a second sweep opens none of them")
def _():
    sb = Sandbox("sweep-codex")
    rollout(sb, "rollout-a", "sess-codex-a")
    rollout(sb, "rollout-b", "sess-codex-b", "archived_sessions/2026/09/30")
    sessions, runtimes, err = sweep_json(sb)
    assert sorted(s["session"] for s in sessions) == ["sess-codex-a", "sess-codex-b"] and len(sb.pending()) == 4, sessions
    codex = [r for r in runtimes if r["runtime"] == "codex"][0]
    assert (codex["files"], codex["unchanged"], codex["failed"], codex["missing"]) == (2, 0, 0, []), codex
    assert [r["runtime"] for r in runtimes] == ["codex", "opencode"] and runtimes[1]["missing"] == ["opencode.db"], runtimes
    assert err == "", err
    # In this process, with the parser counting the files it is given.
    opened: list[str] = []
    real = ledger_cost.capture_codex_file

    def counting(path, *args, **kwargs):
        opened.append(path.name)
        return real(path, *args, **kwargs)
    ledger_cost.capture_codex_file = counting
    try:
        code, out, err = run_main(sb, "capture", "--sweep", "--json")
        assert code == 0 and opened == [], (code, opened, err)
        assert json.loads(out.splitlines()[0])["files"] == 2 and "unchanged" in out, out
        # A file that grew is read from its offset, and only that file.
        grown = sb.codex / "sessions/2026/10/10/rollout-a.jsonl"
        before = grown.stat().st_size
        codex_extend(grown)
        code, out, err = run_main(sb, "capture", "--sweep", "--json")
        rows = [json.loads(l) for l in out.splitlines()]
        assert code == 0 and opened == ["rollout-a.jsonl"], (code, opened, err)
        assert rows[0]["new"] == 1 and rows[0]["files"][0]["offset_before"] > 0 and rows[0]["bytes_read"] == grown.stat().st_size - rows[0]["files"][0]["offset_before"], rows[0]
        assert rows[0]["files"][0]["offset_before"] <= before
        assert len(sb.pending()) == 5
    finally:
        ledger_cost.capture_codex_file = real
    index = json.loads((sb.ledger / "state" / "codex" / "sweep.json").read_text())
    assert sorted(e["status"] for e in index.values()) == ["ok", "ok"] and all(set(e) == {"size", "mtime_ns", "status"} for e in index.values()), index


@case("sweep: a rollout the normalizer refuses is failed, counted, logged once and not retried until it changes; the others still run")
def _():
    sb = Sandbox("sweep-codex-failed")
    bad = bad_rollout(sb, "rollout-bad")
    rollout(sb, "rollout-good", "sess-codex-good")
    sessions, runtimes, err = sweep_json(sb)
    codex = runtimes[0]
    assert (codex["files"], codex["failed"]) == (2, 1) and [s["session"] for s in sessions] == ["sess-codex-good"], (codex, sessions)
    assert len(sb.pending()) == 2 and err == ""
    refused = [l for l in log_text(sb).splitlines() if "file refused" in l]
    assert len(refused) == 1 and "LedgerError" in refused[0] and "unobserved usage prefix" in refused[0], log_text(sb)
    assert all(len(l) < 400 for l in log_text(sb).splitlines())
    opened: list[str] = []
    real = ledger_cost.capture_codex_file

    def counting(path, *args, **kwargs):
        opened.append(path.name)
        return real(path, *args, **kwargs)
    ledger_cost.capture_codex_file = counting
    try:
        code, out, err = run_main(sb, "capture", "--sweep", "--json")
        line = [json.loads(l) for l in out.splitlines() if '"sweep"' in l][0]
        assert code == 0 and opened == [] and (line["files"], line["unchanged"], line["failed"]) == (2, 2, 1), (opened, line)
        assert len([l for l in log_text(sb).splitlines() if "file refused" in l]) == 1, "logged again without a change"
        with open(bad, "a") as handle:
            handle.write("\n")                      # the file changed: it is tried again (and refused again)
        code, out, err = run_main(sb, "capture", "--sweep", "--json")
        assert opened == ["rollout-bad.jsonl"], opened
        assert len([l for l in log_text(sb).splitlines() if "file refused" in l]) == 2
    finally:
        ledger_cost.capture_codex_file = real
    text = sb.ledger_cmd("capture", "--sweep")[1]
    assert "sweep: codex files=2 unchanged=2 failed=1 missing=archived_sessions" in text, text


@case("sweep: a rollout that cannot be read is failed for itself only; the later files are still captured")
def _():
    sb = Sandbox("sweep-codex-unreadable")
    rollout(sb, "rollout-a-locked", "sess-codex-locked")
    rollout(sb, "rollout-b-good", "sess-codex-later")
    real = ledger_cost.capture_one

    def locked_one(directory, runtime, main, checkouts):
        if main.name == "rollout-a-locked.jsonl":
            raise PermissionError(13, "Permission denied", str(main))
        return real(directory, runtime, main, checkouts)
    ledger_cost.capture_one = locked_one
    try:
        code, out, err = run_main(sb, "capture", "--sweep", "--json")
    finally:
        ledger_cost.capture_one = real
    rows = [json.loads(l) for l in out.splitlines()]
    line = [r for r in rows if r.get("kind") == "sweep" and r["runtime"] == "codex"][0]
    assert code == 0 and (line["files"], line["failed"]) == (2, 1), (code, line, err)
    assert [r["session"] for r in rows if "session" in r] == ["sess-codex-later"], rows
    assert any("file refused: PermissionError" in l for l in log_text(sb).splitlines()), log_text(sb)
    index = json.loads((sb.ledger / "state" / "codex" / "sweep.json").read_text())
    assert sorted(e["status"] for e in index.values()) == ["failed", "ok"], index


@case("sweep: a failure to write the ledger is not remembered as a refused file; the next sweep reads it")
def _():
    sb = Sandbox("sweep-codex-write-fails")
    rollout(sb, "rollout-w", "sess-codex-w")
    real = ledger_cost.capture_one

    def write_fails(directory, runtime, main, checkouts):
        raise OSError(28, "No space left on device", str(directory / "pending" / runtime / "x.jsonl"))
    ledger_cost.capture_one = write_fails
    try:
        code, out, err = run_main(sb, "capture", "--sweep", "--json")
    finally:
        ledger_cost.capture_one = real
    line = [json.loads(l) for l in out.splitlines() if '"sweep"' in l][0]
    assert code == 0 and line["failed"] == 1 and sb.pending() == [], (line, err)
    assert any("ledger write failed: OSError" in l for l in log_text(sb).splitlines()), log_text(sb)
    index_path = sb.ledger / "state" / "codex" / "sweep.json"
    assert not index_path.exists() or json.loads(index_path.read_text()) == {}, index_path.read_text()
    sessions, runtimes, err = sweep_json(sb)   # the ledger is writable again: the unchanged file is read
    assert [s["session"] for s in sessions] == ["sess-codex-w"] and len(sb.pending()) == 2, (sessions, runtimes)


@case("capture --runtime opencode with a transcript source is refused: only the sweep reads OpenCode")
def _():
    sb = Sandbox("opencode-no-transcript")
    path = rollout(sb, "rollout-o", "sess-codex-o")
    for args in (("--transcript", str(path)), ("--transcripts", str(path.parent))):
        code, out, err = run_main(sb, "capture", "--runtime", "opencode", *args)
        assert code != 0 and "use capture --sweep" in err, (args, code, out, err)
    assert sb.pending() == [], sb.pending()


@case("sweep: a rollout moved to archived_sessions/ adds nothing, and the index forgets the old path")
def _():
    sb = Sandbox("sweep-codex-moved")
    path = rollout(sb, "rollout-m", "sess-codex-m")
    sweep_json(sb)
    assert len(sb.pending()) == 2
    target = sb.codex / "archived_sessions" / path.name
    target.parent.mkdir(parents=True)
    shutil.move(str(path), str(target))
    sessions, runtimes, err = sweep_json(sb)
    assert len(sb.pending()) == 2 and all(s["new"] == 0 for s in sessions) and sessions[0]["duplicates"] == 2, sessions
    assert list(json.loads((sb.ledger / "state" / "codex" / "sweep.json").read_text())) == [str(target)]


@case("sweep: OpenCode messages map to records field by field, and nothing but the allowlist is written")
def _():
    sb = Sandbox("sweep-opencode-map")
    repo = make_repo(sb.root / "repo")
    git(repo, "checkout", "-q", "feat/a", at="2026-10-09T00:00:00Z")
    session_model = json.dumps({"providerID": "anthropic", "id": "claude-haiku-5-5"})
    make_opencode(sb.opencode, [("ses_a", None, str(repo), session_model), ("ses_nodir", None, None, None)], [
        omsg("msg_1", "ses_a", 123),
        omsg("msg_2", "ses_a", 5000, model=None, inp=1000, out=10, reasoning=0, read=0, write=0),   # the session's model
        omsg("msg_3", "ses_a", 6000, reasoning="absent", out=40),                                   # no reasoning figure
        omsg("msg_4", "ses_a", 7000, reasoning="x"),                                                # reasoning is not a number
        omsg("msg_5", "ses_nodir", 8000, write=None, extra={"tokens": None}),                       # no tokens object
        omsg("msg_6", "ses_nodir", 9000, extra={"tokens": {"input": "many", "output": None, "cache": {}}}),   # nothing usable
    ])
    sessions, runtimes, err = sweep_json(sb)
    rows = opencode_rows(sb)
    assert sorted(rows) == ["opencode:msg_1", "opencode:msg_2", "opencode:msg_3", "opencode:msg_4"], sorted(rows)
    first = rows["opencode:msg_1"]
    assert first == {"id": "opencode:msg_1", "time": "2026-10-10T00:00:00.123Z", "model": "opencode/deepseek-v4.1-flash-free",
                     "input": 100, "output": 25, "cache_read": 30, "cache_write_5m": 7, "cache_write_1h": 0,
                     "repository": "acme/widgets", "branch": "feat/a", "attribution_source": "reflog", "role": "main",
                     "agent_type": None, "agent_id": None, "session": "ses_a", "runtime": "opencode", "remote_session": None}, first
    assert list(first) == list(ledger_cost.FIELDS)
    assert rows["opencode:msg_2"]["model"] == "anthropic/claude-haiku-5-5" and rows["opencode:msg_2"]["output"] == 10
    assert rows["opencode:msg_3"]["output"] == 40, "no reasoning figure: output is the visible output"
    assert rows["opencode:msg_4"]["output"] is None and rows["opencode:msg_4"]["input"] == 100, rows["opencode:msg_4"]
    assert {s["session"]: s for s in sessions}["ses_nodir"]["skipped_lines"] == 1 and "ses_nodir" in {s["session"] for s in sessions}
    assert [r for r in runtimes if r["runtime"] == "opencode"][0]["rows"] == 6
    no_sentinels(sb, json.dumps(sessions), err)
    report = sb.report()
    # msg_1 and msg_3 are the free model (cost 0); msg_2's model has no price and msg_4's output is unknown.
    assert (report["requests"], report["priced"], report["unknown"]["cost"]) == (4, 2, 2), report
    assert Decimal(report["total_cost"]) == 0


@case("sweep: an OpenCode message still streaming is skipped, then captured once it completes; a second sweep adds nothing")
def _():
    sb = Sandbox("sweep-opencode-streaming")
    make_opencode(sb.opencode, [("ses_a", None, None, None)], [omsg("msg_1", "ses_a", 0), omsg("msg_2", "ses_a", 2000, done=None)])
    sessions, _, err = sweep_json(sb)
    assert sorted(opencode_rows(sb)) == ["opencode:msg_1"] and sessions[0]["new"] == 1, (opencode_rows(sb), sessions)
    done = omsg("msg_2", "ses_a", 2000, inp=555)
    edit_opencode(sb, "UPDATE session_message SET data = ?, time_updated = ? WHERE id = 'msg_2'", (done[5], BASE_MS + 4000))
    sessions, _, err = sweep_json(sb)
    assert sorted(opencode_rows(sb)) == ["opencode:msg_1", "opencode:msg_2"] and opencode_rows(sb)["opencode:msg_2"]["input"] == 555
    before = sb.pending()
    sessions, _, err = sweep_json(sb)
    assert sb.pending() == before and all(s["new"] == 0 and s["conflicts"] == 0 for s in sessions), sessions
    assert sessions[0]["duplicates"] == 2, sessions   # the ten minutes behind the watermark are read again
    no_sentinels(sb, err)


@case("sweep: a subagent session is a subagent record of its root session; a parent cycle has one root")
def _():
    sb = Sandbox("sweep-opencode-tree")
    make_opencode(sb.opencode, [("ses_root", None, None, None), ("ses_child", "ses_root", None, None),
                                ("ses_grand", "ses_child", None, None), ("ses_orphan", "ses_gone", None, None),
                                ("ses_c2", "ses_c1", None, None), ("ses_c1", "ses_c2", None, None)], [
        omsg("m_root", "ses_root", 0), omsg("m_child", "ses_child", 1000, agent="general"),
        omsg("m_grand", "ses_grand", 2000, agent="explore"), omsg("m_orphan", "ses_orphan", 3000),
        omsg("m_c1", "ses_c1", 4000), omsg("m_c2", "ses_c2", 5000, agent="general")])
    sweep_json(sb)
    rows = opencode_rows(sb)
    pick = lambda mid: (rows[f"opencode:{mid}"]["session"], rows[f"opencode:{mid}"]["role"], rows[f"opencode:{mid}"]["agent_id"],
                        rows[f"opencode:{mid}"]["agent_type"])
    assert pick("m_root") == ("ses_root", "main", None, None)
    assert pick("m_child") == ("ses_root", "subagent", "ses_child", "general")
    assert pick("m_grand") == ("ses_root", "subagent", "ses_grand", "explore")
    assert pick("m_orphan") == ("ses_orphan", "main", None, None), "a missing parent stops the walk at the last session found"
    assert pick("m_c1")[0] == pick("m_c2")[0] == "ses_c1", "both members of a cycle share one root"
    assert pick("m_c1")[1] == "main" and pick("m_c2")[1] == "subagent"
    assert sorted(p.name for p in (sb.ledger / "pending" / "opencode").iterdir()) == ["ses_c1.jsonl", "ses_orphan.jsonl", "ses_root.jsonl"]


@case("sweep: OpenCode rows whose tokens changed are a conflict, kept once; the watermark window catches a late row")
def _():
    sb = Sandbox("sweep-opencode-window")
    hour = 3_600_000
    make_opencode(sb.opencode, [("ses_a", None, None, None)], [omsg("m_old", "ses_a", 0), omsg("m_new", "ses_a", hour)])
    sweep_json(sb)
    state = json.loads(next((sb.ledger / "state" / "opencode").glob("*.json")).read_text())
    assert state == {"watermark": BASE_MS + hour + 1000}, state
    changed = omsg("m_new", "ses_a", hour, inp=999)
    edit_opencode(sb, "UPDATE session_message SET data = ? WHERE id = 'm_new'", (changed[5],))
    sessions, _, err = sweep_json(sb)
    assert sessions[0]["conflicts"] == 1 and sessions[0]["new"] == 0, sessions
    assert [json.loads(l) for l in (sb.ledger / "conflicts" / "opencode" / "ses_a.jsonl").read_text().splitlines()] == [{"id": "opencode:m_new"}]
    assert opencode_rows(sb)["opencode:m_new"]["input"] == 100 and len(sb.pending()) == 2
    sweep_json(sb)
    assert len((sb.ledger / "conflicts" / "opencode" / "ses_a.jsonl").read_text().splitlines()) == 1
    # Committed after the watermark moved: inside the ten minutes it is read; further back it is not.
    insert_message(sb, omsg("m_late", "ses_a", hour - 300_000, updated=BASE_MS + hour + 1000 - 300_000))
    insert_message(sb, omsg("m_later", "ses_a", hour - 700_000, updated=BASE_MS + hour + 1000 - 700_000))
    sessions, _, err = sweep_json(sb)
    assert sorted(opencode_rows(sb)) == ["opencode:m_late", "opencode:m_new", "opencode:m_old"], sorted(opencode_rows(sb))
    # A restored database (time_updated behind the watermark) is read again from the start; ids absorb the repeats.
    edit_opencode(sb, "UPDATE session_message SET time_updated = time_updated - ?", (50 * hour,))
    before = len(sb.pending())
    sessions, _, err = sweep_json(sb)
    assert len(sb.pending()) == before + 1 and "opencode:m_later" in opencode_rows(sb), "the restore was not re-read"
    assert json.loads(next((sb.ledger / "state" / "opencode").glob("*.json")).read_text())["watermark"] < BASE_MS
    no_sentinels(sb, err)


@case("sweep: the OpenCode database is opened read-only, only the two tables are queried, and the file is untouched")
def _():
    sb = Sandbox("sweep-opencode-readonly")
    make_opencode(sb.opencode, [("ses_a", None, None, None), ("ses_b", "ses_a", None, None)],
                  [omsg("m_1", "ses_a", 0), omsg("m_2", "ses_b", 1000, agent="general")])
    stat = sb.opencode.stat()
    content = sb.opencode.read_bytes()
    statements: list[str] = []
    uris: list[str] = []
    real = ledger_cost.sqlite3.connect

    def traced(target, *args, **kwargs):
        uris.append(target)
        conn = real(target, *args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    ledger_cost.sqlite3.connect = traced
    try:
        code, out, err = run_main(sb, "capture", "--sweep", "--json")
    finally:
        ledger_cost.sqlite3.connect = real
    assert code == 0 and len(opencode_rows(sb)) == 2, (code, err)
    assert len(uris) == 1 and "mode=ro" in uris[0], uris
    assert statements[0].startswith("PRAGMA query_only") and all(
        s.startswith(("SELECT", "PRAGMA query_only")) for s in statements), statements
    assert all("credential" not in s.lower() and "title" not in s.lower() and "time_created" not in s for s in statements), statements
    tables = {t for s in statements for t in ("session_v2", "session_message") if t in s}
    assert tables == {"session_v2", "session_message"}
    assert sb.opencode.read_bytes() == content and sb.opencode.stat().st_mtime_ns == stat.st_mtime_ns, "the database was written"
    no_sentinels(sb, out, err)
    assert not [p for p in sb.opencode.parent.iterdir() if p != sb.opencode], list(sb.opencode.parent.iterdir())   # no journal left behind


@case("sweep: OPENCODE_DATA_DIR names the database before XDG_DATA_HOME")
def _():
    sb = Sandbox("sweep-opencode-datadir")
    other = sb.root / "elsewhere"
    make_opencode(other / "opencode.db", [("ses_x", None, None, None)], [omsg("m_x", "ses_x", 0)])
    sessions, runtimes, err = sweep_json(sb, {"OPENCODE_DATA_DIR": str(other)})
    assert list(opencode_rows(sb)) == ["opencode:m_x"] and runtimes[1]["missing"] == [], (sessions, runtimes)


@case("sweep: a database missing a table is a defined failure for OpenCode only; Codex still runs and nothing leaks")
def _():
    sb = Sandbox("sweep-opencode-broken")
    rollout(sb, "rollout-a", "sess-codex-a")
    make_opencode(sb.opencode, [("ses_a", None, None, None)], [], tables="one")
    code, out, err = sb.ledger_cmd("capture", "--sweep", "--json")
    assert code == 1, (code, out, err)
    assert len(sb.pending()) == 2 and all(r["runtime"] == "codex" for r in sb.pending()), sb.pending()
    assert len(err.strip().splitlines()) == 1 and "opencode" in err and "session_message" in err, err
    lines = [l for l in log_text(sb).splitlines() if "sweep opencode failed" in l]
    assert len(lines) == 1 and "LedgerError" not in lines[0] and len(lines[0]) < 400, log_text(sb)
    runtimes = [json.loads(l) for l in out.splitlines() if '"sweep"' in l]
    assert [(r["runtime"], r["failed"]) for r in runtimes] == [("codex", 0), ("opencode", 1)], runtimes
    no_sentinels(sb, out, err)
    sb.opencode.write_bytes(b"this is not a database" * 100)      # not a database at all
    code, out, err = sb.ledger_cmd("capture", "--sweep")
    assert code == 1 and len(err.strip().splitlines()) == 1 and "opencode" in err, (code, err)
    assert "sweep: codex files=1 unchanged=1 failed=0" in out, out


@case("remote_session of swept rows: set only with CLAUDE_CODE_REMOTE=true, null elsewhere")
def _():
    results = {}
    for name, extra in (("cloud", {"CLAUDE_CODE_REMOTE": "true", REMOTE_VAR: "session_01SyntheticAbc"}),
                        ("laptop", {REMOTE_VAR: "session_01SyntheticAbc"}),
                        ("not-true", {"CLAUDE_CODE_REMOTE": "1", REMOTE_VAR: "session_01SyntheticAbc"}),
                        ("no-id", {"CLAUDE_CODE_REMOTE": "true"}),
                        ("malformed", {"CLAUDE_CODE_REMOTE": "true", REMOTE_VAR: "nounderscore"})):
        sb = Sandbox(f"sweep-remote-{name}")
        rollout(sb, "rollout-r", "sess-codex-r")
        make_opencode(sb.opencode, [("ses_r", None, None, None)], [omsg("m_r", "ses_r", 0)])
        sweep_json(sb, extra)
        assert {r["runtime"] for r in sb.pending()} == {"codex", "opencode"}
        results[name] = {r["remote_session"] for r in sb.pending()}
    assert results == {"cloud": {"01SyntheticAbc"}, "laptop": {None}, "not-true": {None}, "no-id": {None}, "malformed": {None}}, results
    # Claude keeps its own rule: the id only for the running session's own transcript.
    sb = Sandbox("sweep-remote-claude")
    repo = make_repo(sb.root / "repo")
    transcript = write_transcript(sb.root / "proj", "sess-own", [assistant("msg_1", "2026-10-10T00:00:00Z", repo, "feat/a")])
    code, out, err = sb.ledger_cmd("capture", "--transcript", str(transcript), extra_env={
        "CLAUDE_CODE_REMOTE": "true", REMOTE_VAR: "session_01SyntheticAbc", "CLAUDE_CODE_SESSION_ID": "sess-own"})
    assert code == 0 and {r["remote_session"] for r in sb.pending()} == {"01SyntheticAbc"}, err
    sb = Sandbox("sweep-remote-claude-other")
    code, out, err = sb.ledger_cmd("capture", "--transcript", str(transcript), extra_env={
        "CLAUDE_CODE_REMOTE": "true", REMOTE_VAR: "session_01SyntheticAbc", "CLAUDE_CODE_SESSION_ID": "another"})
    assert code == 0 and {r["remote_session"] for r in sb.pending()} == {None}, err


@case("ledger.runtimes: codex only skips OpenCode, the default sweeps both, names are comma or space separated, unknown ones are reported")
def _():
    sb = Sandbox("sweep-runtimes")
    rollout(sb, "rollout-a", "sess-codex-a")
    make_opencode(sb.opencode, [("ses_a", None, None, None)], [omsg("m_a", "ses_a", 0)])
    sb.set_config("ledger.capture = on\nledger.runtimes = codex\n")
    sessions, runtimes, err = sweep_json(sb)
    assert [r["runtime"] for r in runtimes] == ["codex"] and {r["runtime"] for r in sb.pending()} == {"codex"} and err == "", (runtimes, err)
    sb.set_config("ledger.capture = on\nledger.runtimes = opencode\n")
    sessions, runtimes, err = sweep_json(sb)
    assert [r["runtime"] for r in runtimes] == ["opencode"] and {r["runtime"] for r in sb.pending()} == {"codex", "opencode"}
    for text, expected in (("", ["codex", "opencode"]), ("ledger.runtimes = claude,codex,opencode\n", ["codex", "opencode"]),
                           ("ledger.runtimes = claude\n", []), ("ledger.runtimes = opencode  codex\n", ["codex", "opencode"]),
                           ("ledger.runtimes = \"codex, opencode\"\n", ["codex", "opencode"])):
        sb.set_config("ledger.capture = on\n" + text)
        assert [r["runtime"] for r in sweep_json(sb)[1]] == expected, text
    sb.set_config("ledger.capture = on\nledger.runtimes = codex,cursor,Aider\n")
    sessions, runtimes, err = sweep_json(sb)
    assert [r["runtime"] for r in runtimes] == ["codex"] and len(err.strip().splitlines()) == 1 and "aider" in err and "cursor" in err, err


@case("sweep: a location that is not there is reported as missing, not as an error")
def _():
    sb = Sandbox("sweep-missing")
    code, out, err = sb.ledger_cmd("capture", "--sweep")
    assert code == 0 and err == "", (code, err)
    assert out.splitlines() == ["sweep: codex files=0 unchanged=0 failed=0 missing=sessions,archived_sessions",
                                "sweep: opencode rows=0 failed=0 missing=opencode.db"], out
    assert not (sb.ledger / "capture.log").exists() and sb.pending() == []
    (sb.codex / "sessions").mkdir(parents=True)                      # one of Codex's two places
    code, out, err = sb.ledger_cmd("capture", "--sweep")
    assert code == 0 and "files=0 unchanged=0 failed=0 missing=archived_sessions" in out, out


def tripled_sandbox(name: str, **kwargs):
    """A sandbox with one Claude transcript, one Codex rollout and one OpenCode database."""
    sb = Sandbox(name)
    repo = make_repo(sb.root / "repo")
    rollout(sb, "rollout-h", "sess-codex-h")
    make_opencode(sb.opencode, [("ses_h", None, str(repo), None)], [omsg("m_h", "ses_h", 0)], **kwargs)
    return sb, repo


@case("hook: capture with capture on records the Claude session and then sweeps the other runtimes")
def _():
    sb, repo = tripled_sandbox("sweep-hook")
    transcript = write_transcript(sb.root / "proj", "sess-hook", [assistant("msg_h", "2026-10-10T00:00:00Z", repo, "feat/a")])
    assert run_hook(sb, hook_input(sb, transcript, repo)) < 0.5
    assert wait_for(lambda: {r["runtime"] for r in sb.pending()} == {"claude", "codex", "opencode"}, 60), sb.pending()
    assert len(sb.pending()) == 1 + 2 + 1
    assert not (sb.ledger / "capture.log").exists(), log_text(sb)
    # Capture off: the hook never starts Python, so nothing is swept (the existing contract).
    off, repo = tripled_sandbox("sweep-hook-off")
    off.set_config("ledger.capture = off\n")
    run_hook(off, hook_input(off, transcript, repo))
    time.sleep(0.3)
    assert not off.ledger.exists()


@case("hook: a sweep that fails leaves one log line and the Claude rows are written; with ledger.runtimes = claude nothing is swept")
def _():
    sb, repo = tripled_sandbox("sweep-hook-fail", tables="one")
    transcript = write_transcript(sb.root / "proj", "sess-hf", [assistant("msg_hf", "2026-10-10T00:00:00Z", repo, "feat/a")])
    run_hook(sb, hook_input(sb, transcript, repo))
    assert wait_for(lambda: {r["runtime"] for r in sb.pending()} == {"claude", "codex"}, 60), sb.pending()
    assert wait_for(lambda: "sweep opencode failed" in log_text(sb), 30)
    assert len([l for l in log_text(sb).splitlines()]) == 1, log_text(sb)
    # Anything unexpected in the sweep, in this process: caught, one line, the Claude rows are there, the status is 0.
    sb, repo = tripled_sandbox("sweep-hook-boom")
    transcript = write_transcript(sb.root / "proj", "sess-boom", [assistant("msg_b", "2026-10-10T00:00:00Z", repo, "feat/a")])
    payload = sb.root / "hook.json"
    payload.write_text(hook_input(sb, transcript, repo))
    real = ledger_cost.sweep

    def boom(*args, **kwargs):
        raise RuntimeError("boom https://user:pw@example.invalid/x")
    ledger_cost.sweep = boom
    try:
        code, out, err = run_main(sb, "capture", "--hook-input", str(payload))
    finally:
        ledger_cost.sweep = real
    assert code == 0 and [r["runtime"] for r in sb.pending()] == ["claude"], (code, err, sb.pending())
    lines = log_text(sb).splitlines()
    assert len(lines) == 1 and "sweep failed: RuntimeError" in lines[0] and "pw@" not in lines[0], lines
    sb, repo = tripled_sandbox("sweep-hook-claude-only")
    sb.set_config("ledger.capture = on\nledger.runtimes = claude\n")
    transcript = write_transcript(sb.root / "proj", "sess-co", [assistant("msg_c", "2026-10-10T00:00:00Z", repo, "feat/a")])
    shim, mark = python_shim(sb)
    run_hook(sb, hook_input(sb, transcript, repo), shim)
    assert wait_for(finished(mark, 1), 60)
    assert [r["runtime"] for r in sb.pending()] == ["claude"] and not (sb.ledger / "capture.log").exists()


@case("hook with ledger.export = on-stop also exports the swept sessions")
def _():
    sb, repo, store = on_stop_sandbox("sweep-stop")
    rollout(sb, "rollout-s", "sess-codex-s")
    make_opencode(sb.opencode, [("ses_s", None, str(repo), None)], [omsg("m_s", "ses_s", 0)])
    shim, mark, log = hook_shims(sb)
    turn(sb, repo, "sess-claude-s", 1, 0, shim)
    wanted = {"refs/heads/plumb-ledger/claude/sess-claude-s", "refs/heads/plumb-ledger/codex/sess-codex-s",
              "refs/heads/plumb-ledger/opencode/ses_s"}
    assert wait_for(lambda: set(refs(store)) == wanted, 90) and wait_for(finished(mark, 1), 60), refs(store)
    assert wait_for(lambda: sb.pending() == [], 30), sb.pending()
    assert len(sb.exported()) == 4
    assert len(stored_lines(store, "sess-claude-s")) == 1


@case("on-stop: a swept session whose push failed is sent on a later turn that sweeps nothing new")
def _():
    sb, repo, store = on_stop_sandbox("sweep-stop-retry")
    reject = store / "hooks" / "pre-receive"
    reject.write_text("#!/bin/sh\necho 'rejected by the store' >&2\nexit 1\n")
    reject.chmod(0o755)
    rollout(sb, "rollout-r", "sess-codex-r")
    make_opencode(sb.opencode, [("ses_r", None, str(repo), None)], [omsg("m_r", "ses_r", 0)])
    shim, mark, log = hook_shims(sb)
    turn(sb, repo, "sess-claude-r", 1, 0, shim)
    assert wait_for(finished(mark, 1), 60)
    assert wait_for(lambda: (sb.ledger / "capture.log").exists() and "export failed" in (sb.ledger / "capture.log").read_text(), 30)
    assert refs(store) == {} and {r["runtime"] for r in sb.pending()} == {"claude", "codex", "opencode"}, sb.pending()
    # The store is healthy again. The rollout and the database are unchanged, so the sweep adds no
    # row; the swept sessions must still leave pending.
    reject.unlink()
    turn(sb, repo, "sess-claude-r", 1, 1, shim)
    wanted = {"refs/heads/plumb-ledger/claude/sess-claude-r", "refs/heads/plumb-ledger/codex/sess-codex-r",
              "refs/heads/plumb-ledger/opencode/ses_r"}
    assert wait_for(lambda: set(refs(store)) == wanted, 90) and wait_for(finished(mark, 2), 60), refs(store)
    assert wait_for(lambda: sb.pending() == [], 30), sb.pending()


@case("on-stop: with nothing pending for a swept runtime, its export does not reach the store")
def _():
    sb, repo, _ = on_stop_sandbox("sweep-stop-quiet", store=False)
    sb.set_config(sb.config.read_text() + "ledger.store = http://127.0.0.1:9/unreachable.git\n")
    shim, mark, log = hook_shims(sb)
    turn(sb, repo, "sess-claude-q", 1, 0, shim)   # no rollout, no database: nothing swept
    assert wait_for(finished(mark, 1), 60)
    text = (sb.ledger / "capture.log").read_text() if (sb.ledger / "capture.log").exists() else ""
    assert text.count("export failed") == 1, text   # the Claude session only; the swept runtimes had nothing


@case("OpenCode rows are priced: the free model costs 0, a per-model checked/source is read and a provider/model name is looked up as written")
def _():
    versions = ledger_cost.load_prices()
    row = record(1, model="opencode/deepseek-v4.1-flash-free", runtime="opencode", inp=1_000_000, out=500_000, cache_read=7, w5=3, w1=0)
    cost = ledger_cost.price_request(row, versions)
    assert cost is not None and all(value == 0 for value in cost.values()), cost
    rates = ledger_cost.model_rates(versions[0], "opencode/deepseek-v4.1-flash-free")
    assert rates["checked"] == "2026-11-02" and "free tier" in rates["source"], rates
    assert ledger_cost.model_rates(versions[0], "opencode/other-model") is None
    assert ledger_cost.price_request(record(2, model="opencode/other-model", runtime="opencode"), versions) is None
    version = {"id": "x", "effective_from": "1970-01-01T00:00:00Z", "checked": "2026-01-01", "source": "v",
               "cache_write_multiplier": {"5m": 1.25, "1h": 2}, "per_tokens": 1000000,
               "models": {"vendor/model-x": {"input": Decimal(2), "output": Decimal(8), "cache_read": Decimal("0.5"),
                                             "checked": "2026-02-02", "source": "page",
                                             "long_context": {"threshold_input_tokens": 10, "input": Decimal(4)}}}}
    version["_from"] = ledger_cost.parse_time(version["effective_from"])
    cost = ledger_cost.price_request(record(3, model="vendor/model-x", inp=1_000_000, out=1_000_000, cache_read=0), [version])
    assert cost["input"] == Decimal(4) and cost["output"] == Decimal(8), cost    # the long-context tier, with the extra keys around it
    sb = Sandbox("opencode-priced")
    put_pending(sb, "ses_p", [row], "opencode")
    report = sb.report()
    assert report["requests"] == 1 and report["priced"] == 1 and Decimal(report["total_cost"]) == 0, report


# ---------------------------------------------------------------- the rest of the contract

@case("session-audit's output on its existing fixture is byte-identical")
def _():
    audit = PLUGIN / "bin" / "plumb-session-audit"
    folder = FIXTURES / "session-audit"
    for flags, expected in (("--json", "expected.json"), ("", "expected.txt")):
        cmd = [str(audit), "--transcripts", str(folder), "--all"] + ([flags] if flags else [])
        out = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "HOME": str(ROOT)})
        assert out.returncode == 0 and out.stdout == (folder / expected).read_text(), f"{expected} differs"


@case("hooks.json registers one Stop hook in the plugin hook format")
def _():
    data = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    assert data == {"hooks": {"Stop": [{"hooks": [{"type": "command",
                    "command": 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/ledger-capture.sh"'}]}]}}, data
    assert os.access(PLUGIN / "scripts" / "ledger-capture.sh", os.X_OK)


@case("prices.json carries the checked list prices and every model the plan names")
def _():
    data = json.loads((PLUGIN / "assets" / "prices.json").read_text(), parse_float=Decimal)
    version = data["versions"][0]
    assert version["checked"] == "2026-10-30" and version["cache_write_multiplier"] == {"5m": Decimal("1.25"), "1h": 2}
    models = version["models"]
    assert {k: (v["input"], v["output"], v["cache_read"]) for k, v in models.items() if k.startswith("claude-")} == {
        "claude-fable-5-1": (10, 50, Decimal("0.25")), "claude-opus-5-5": (4, 20, Decimal("0.20")),
        "claude-sonnet-5-5": (2, 10, Decimal("0.20")), "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"), Decimal("0.01"))}
    assert sorted(k for k in models if not k.startswith("claude-")) == ["opencode/deepseek-v4.1-flash-free"], list(models)
    assert models["claude-haiku-5-5"]["long_context"] == {
        "threshold_input_tokens": 100000, "input": Decimal("0.50"), "output": Decimal("2.50"), "cache_read": Decimal("0.05")}


@case("every subcommand prints usage for --help and exits 0; the doctor ledger block reports capture, the store and the export mode")
def _():
    for name in ("capture", "export", "prs", "report"):
        out = subprocess.run([str(LEDGER), name, "--help"], capture_output=True, text=True)
        assert out.returncode == 0 and out.stdout.startswith(f"usage: plumb-ledger {name}"), (name, out.stdout[:80])
    sb = Sandbox("doctor")
    store = bare_store(sb)
    doctor = lambda: subprocess.run(["bash", str(PLUGIN / "scripts" / "doctor.sh"), str(PLUGIN)], capture_output=True,
                                    text=True, env={**sb.env, "PLUMB_IN_SELFTEST": "1"}, cwd=sb.cwd).stdout
    lines = [l for l in doctor().splitlines() if "ledger." in l]
    assert [l[:6] for l in lines] == ["  ok  ", "  ok  ", "  --  "], lines
    sb.set_config("")
    lines = [l for l in doctor().splitlines() if "ledger." in l]
    assert [l[:6] for l in lines] == ["  --  ", "  --  ", "  --  "], lines
    sb.set_config("ledger.capture = yes\n")
    assert any(l.startswith("  NG ") and "ledger.capture" in l for l in doctor().splitlines())
    for text, expected in ((f"ledger.capture = on\nledger.store = {store}\nledger.export = on-stop\n", "  ok  "),
                           (f"ledger.capture = on\nledger.export = on-stop\n", "  NG  "),
                           (f"ledger.store = {store}\nledger.export = on-stop\n", "  NG  "),
                           (f"ledger.capture = on\nledger.store = {store}\nledger.export = manual\n", "  --  "),
                           (f"ledger.capture = on\nledger.store = {store}\nledger.export = always\n", "  NG  ")):
        sb.set_config(text)
        export_lines = [l for l in doctor().splitlines() if "ledger.export" in l]
        assert len(export_lines) == 1 and export_lines[0][:6] == expected, (text, export_lines)


shutil.rmtree(ROOT, ignore_errors=True)
print()
if FAILED:
    print(f"{len(FAILED)} case(s) NG")
    sys.exit(1)
print("all ok")
