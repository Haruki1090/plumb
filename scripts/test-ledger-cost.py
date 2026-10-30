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
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
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
        self.env = {**os.environ, "HOME": str(self.root / "home"), "PLUMB_CONFIG": str(self.config),
                    "PLUMB_LEDGER_DIR": str(self.ledger), "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        self.env.pop("PLUMB_LEDGER_GH_FIXTURES", None)

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


def git(path: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                         capture_output=True, text=True, env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"})
    assert out.returncode == 0, f"git {args}: {out.stderr}"
    return out.stdout.strip()


def make_repo(path: Path, origin: str = "https://github.com/acme/widgets.git", branches=("feat/a", "feat/b")) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "commit", "-q", "--allow-empty", "-m", "init")
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

@case("a branch switch inside one turn attributes each request to its own branch")
def _():
    sb = Sandbox("switch")
    repo = make_repo(sb.root / "repo")
    lines = [assistant(f"msg_{i}", f"2026-10-10T00:00:0{i}Z", repo, branch)
             for i, branch in enumerate(["feat/a", "feat/b", "feat/a"], 1)]
    capture(sb, write_transcript(sb.root / "proj", "sess-switch", lines))
    got = {r["id"]: (r["branch"], r["attribution_source"], r["repository"]) for r in sb.pending()}
    assert got == {"claude:msg_1": ("feat/a", "transcript", "acme/widgets"),
                   "claude:msg_2": ("feat/b", "transcript", "acme/widgets"),
                   "claude:msg_3": ("feat/a", "transcript", "acme/widgets")}, got


@case("a worktree subagent gets its worktree's branch; a subagent without a worktree keeps the transcript branch")
def _():
    sb = Sandbox("worktree")
    repo = make_repo(sb.root / "repo")
    wt = sb.root / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feat/wt", str(wt))
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
        ("feat/wt", "worktree_at_capture", "subagent", "implementer", "w1"), w
    e = got["claude:msg_e1"]
    assert (e["branch"], e["attribution_source"], e["agent_type"]) == ("feat/b", "transcript", "Explore"), e
    assert got["claude:msg_main"]["role"] == "main" and got["claude:msg_main"]["agent_type"] is None


@case("a removed worktree and a detached HEAD give unknown")
def _():
    sb = Sandbox("unknown")
    repo = make_repo(sb.root / "repo")
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
    """A python3 on PATH that leaves a mark when started, then runs the real one."""
    shim_dir, mark = sb.root / "shim", sb.root / "python-started"
    shim_dir.mkdir()
    real = shutil.which("python3")
    (shim_dir / "python3").write_text(f'#!/bin/sh\necho started >> "{mark}"\nexec "{real}" "$@"\n')
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


def hook_captures_running() -> bool:
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if b"ledger.py\0capture\0--hook-input" in cmdline.read_bytes():
                return True
        except OSError:
            continue
    return False


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
    assert wait_for(lambda: mark.read_text().count("started") == 24 and not hook_captures_running()), "hook runs did not drain"
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
    assert {k: (v["input"], v["output"], v["cache_read"]) for k, v in models.items()} == {
        "claude-fable-5-1": (10, 50, Decimal("0.25")), "claude-opus-5-5": (4, 20, Decimal("0.20")),
        "claude-sonnet-5-5": (2, 10, Decimal("0.20")), "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"), Decimal("0.01"))}
    assert models["claude-haiku-5-5"]["long_context"] == {
        "threshold_input_tokens": 100000, "input": Decimal("0.50"), "output": Decimal("2.50"), "cache_read": Decimal("0.05")}


@case("every subcommand prints usage for --help and exits 0; the doctor ledger block reports capture and the store")
def _():
    for name in ("capture", "export", "prs", "report"):
        out = subprocess.run([str(LEDGER), name, "--help"], capture_output=True, text=True)
        assert out.returncode == 0 and out.stdout.startswith(f"usage: plumb-ledger {name}"), (name, out.stdout[:80])
    sb = Sandbox("doctor")
    store = bare_store(sb)
    doctor = lambda: subprocess.run(["bash", str(PLUGIN / "scripts" / "doctor.sh"), str(PLUGIN)], capture_output=True,
                                    text=True, env={**sb.env, "PLUMB_IN_SELFTEST": "1"}, cwd=sb.cwd).stdout
    lines = [l for l in doctor().splitlines() if "ledger." in l]
    assert [l[:6] for l in lines] == ["  ok  ", "  ok  "], lines
    sb.set_config("")
    lines = [l for l in doctor().splitlines() if "ledger." in l]
    assert [l[:6] for l in lines] == ["  --  ", "  --  "], lines
    sb.set_config("ledger.capture = yes\n")
    assert any(l.startswith("  NG ") and "ledger.capture" in l for l in doctor().splitlines())
    del store


shutil.rmtree(ROOT, ignore_errors=True)
print()
if FAILED:
    print(f"{len(FAILED)} case(s) NG")
    sys.exit(1)
print("all ok")
