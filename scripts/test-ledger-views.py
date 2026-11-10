#!/usr/bin/env python3
"""Regression suite for `plumb-ledger views`, the remote_session field, session attribution and active
time, on synthetic data only.

    python3 -B scripts/test-ledger-views.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline under
tempfile.mkdtemp(): records are generated here, "GitHub" is a prs/changes file written here, the store
is a local bare repository. No real transcript, record or store is read, and every name is made up.
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(HERE))
import ledger_cost  # noqa: E402
import ledger_views  # noqa: E402

LEDGER = PLUGIN / "bin" / "plumb-ledger"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-ledger-views-test-"))
FAILED: list[str] = []
HAIKU = "claude-haiku-5-5"
OPUS = "claude-opus-5-5"
BASE = datetime(2026, 10, 10, tzinfo=timezone.utc)
REPO = "example/app"
PERIOD = ("--since", "2026-10-09", "--until", "2026-10-11")


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
        self.config.write_text("")
        self.ledger = self.root / "ledger"
        self.cwd = self.root / "work"
        self.cwd.mkdir()
        self.out = self.root / "out"
        self.env = {**os.environ, "HOME": str(self.root / "home"), "PLUMB_CONFIG": str(self.config),
                    "PLUMB_LEDGER_DIR": str(self.ledger), "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        for key in ("PLUMB_LEDGER_GH_FIXTURES", ledger_cost.REMOTE_SESSION_ENV, ledger_cost.CURRENT_SESSION_ENV):
            self.env.pop(key, None)

    def ledger_cmd(self, *args: str, extra_env: dict | None = None, cwd: Path | None = None):
        out = subprocess.run([str(LEDGER), *args], capture_output=True, text=True, cwd=cwd or self.cwd,
                             env={**self.env, **(extra_env or {})}, timeout=300)
        return out.returncode, out.stdout, out.stderr

    def pending(self) -> list[dict]:
        rows = []
        for path in sorted((self.ledger / "pending").glob("*/*.jsonl")):
            rows.extend(json.loads(line) for line in path.read_text().splitlines() if line)
        return rows

    def views(self, *args: str, out: Path | None = None, period: tuple = PERIOD, extra_env: dict | None = None) -> dict[str, str]:
        """Run `views`, return the generated files' text by name."""
        target = out or self.out
        code, stdout, stderr = self.ledger_cmd("views", *period, "--out", str(target), *args, extra_env=extra_env)
        assert code == 0, f"views exited {code}: {stderr}"
        return {path.name: path.read_bytes().decode("utf-8") for path in sorted(target.iterdir()) if path.is_file()}

    def report(self, *args: str) -> dict:
        code, out, err = self.ledger_cmd("report", *PERIOD, "--json", *args)
        assert code == 0, f"report exited {code}: {err}"
        return json.loads(out)


def stamp(minutes: float = 0, seconds: float = 0, base: datetime = BASE) -> str:
    return (base + timedelta(minutes=minutes, seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def record(n, time_: str, *, branch="feat/x", repo=REPO, session="s1", remote="TESTID", role="main", model=HAIKU,
           runtime="claude", inp=1000, out=0, source="reflog", rid="") -> dict:
    return {"id": f"{runtime}:m{rid}{n}", "time": time_, "model": model, "input": inp, "output": out,
            "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0, "repository": repo, "branch": branch,
            "attribution_source": source, "role": role, "agent_type": "implementer" if role == "subagent" else None,
            "agent_id": None, "session": session, "runtime": runtime, "remote_session": remote}


def put(sb: Sandbox, session: str, rows: list[dict], runtime: str = "claude") -> None:
    path = sb.ledger / "pending" / runtime / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))


def put_all(sb: Sandbox, rows: list[dict]) -> None:
    """Pending files, one per (runtime, session) of the rows."""
    for key in sorted({(r["runtime"], r["session"]) for r in rows}):
        put(sb, key[1], [r for r in rows if (r["runtime"], r["session"]) == key], key[0])


def pull(number: int, head: str, created="2026-10-01T00:00:00Z", closed="2026-10-20T00:00:00Z", base="main") -> dict:
    return {"number": number, "head_ref": head, "base_ref": base, "created_at": created, "closed_at": closed}


def write_prs(sb: Sandbox, pulls: list[dict], repo=REPO, name="prs.json") -> str:
    path = sb.root / name
    path.write_text(json.dumps({"repository": repo, "pull_requests": pulls}))
    return str(path)


def change(number: int, sessions: list[str], repo=REPO, head: str | None = None, kind="pull_request") -> dict:
    return {"kind": kind, "repository": repo, "number": number if kind == "pull_request" else None,
            "head_ref": head, "merged_at": "2026-10-12T00:00:00Z", "sessions": sessions}


def link(identity: str) -> str:
    return f"https://claude.ai/code/session_{identity}"


def write_changes(sb: Sandbox, rows: list[dict], name="changes.jsonl") -> str:
    path = sb.root / name
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(path)


def table(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


def task_rows(files: dict[str, str]) -> dict[str, dict[str, str]]:
    """tasks.csv by 'repository#number' / 'repository @ head ref' / state."""
    out = {}
    for row in table(files["tasks.csv"]):
        name = f"{row['repository']}#{row['pull_request']}" if row["pull_request"] else (
            f"{row['repository']} @ {row['head_ref']} ({row['state']})" if row["repository"] else row["state"])
        out[name] = row
    return out


def minutes(row: dict[str, str]) -> Decimal:
    return Decimal(row["active_minutes"])


def snapshot(directory: Path) -> dict[str, bytes | str]:
    """Every path under a directory with its content (symbolic links by target)."""
    state: dict[str, bytes | str] = {}
    for path in sorted(directory.rglob("*")):
        key = str(path.relative_to(directory))
        state[key] = f"-> {os.readlink(path)}" if path.is_symlink() else (path.read_bytes() if path.is_file() else "dir")
    return state


def usage() -> dict:
    return {"input_tokens": 1000, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}


def transcript(directory: Path, session: str, count: int, cwd: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "assistant", "isSidechain": False, "timestamp": stamp(i), "cwd": str(cwd),
                         "gitBranch": "feat/x", "message": {"id": f"msg_{i}", "model": HAIKU, "role": "assistant",
                                                            "content": [{"type": "text", "text": "hello"}], "usage": usage()}})
             for i in range(count)]
    path = directory / f"{session}.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------- A: remote_session

@case("remote_session is the part after the first underscore of the runtime's variable; absent or malformed is null")
def _():
    read = ledger_cost.remote_session_from_env
    assert read({ledger_cost.REMOTE_SESSION_ENV: "cse_TESTID"}) == "TESTID"
    assert read({ledger_cost.REMOTE_SESSION_ENV: "cse_Test_ID-2"}) == "Test_ID-2"   # only the first underscore splits
    assert read({}) is None
    for bad in ("", "TESTID", "cse_", "_TESTID", "cse_a b", "cse_a/b", "cse_a\nb", "cse__x", "cse_" + "x" * 65,
                "c se_x", "cse_é"):
        assert read({ledger_cost.REMOTE_SESSION_ENV: bad}) is None, repr(bad)
    assert ledger_cost.FIELDS[-1] == "remote_session"


@case("remote_session is recorded only for the running session's own transcript (and its subagents): same, different and missing session id")
def _():
    remote, current = ledger_cost.REMOTE_SESSION_ENV, ledger_cost.CURRENT_SESSION_ENV
    read = ledger_cost.remote_session_from_env
    cloud = {remote: "cse_TESTID", current: "sess-cloud"}
    assert read(cloud, session="sess-cloud") == "TESTID"
    assert read(cloud, session="sess-other") is None and read(cloud, session="") is None
    assert read({remote: "cse_TESTID"}, session="sess-cloud") is None          # no id for the running session
    assert read({current: "sess-cloud"}, session="sess-cloud") is None         # a local session
    assert read(cloud) == "TESTID"                                              # no session asked for: the variable alone

    def captured(name: str, env: dict | None, *, sessions=("sess-cloud",), subagent=False, many=False) -> list[dict]:
        sb = Sandbox(name)
        proj = sb.root / "proj"
        for session in sessions:
            transcript(proj, session, 2, sb.cwd)
        if subagent:
            side = proj / "sess-cloud" / "subagents"
            side.mkdir(parents=True)
            (side / "agent-w1.jsonl").write_text(json.dumps({
                "type": "assistant", "isSidechain": True, "agentId": "w1", "timestamp": stamp(3), "cwd": str(sb.cwd),
                "message": {"id": "msg_side", "model": HAIKU, "role": "assistant", "content": [], "usage": usage()}}) + "\n")
        args = ["--transcripts", str(proj)] if many else ["--transcript", str(proj / f"{sessions[0]}.jsonl")]
        code, out, err = sb.ledger_cmd("capture", "--json", *args, extra_env=env)
        assert code == 0, err
        return sb.pending()

    rows = captured("capture-same", cloud, subagent=True)
    assert len(rows) == 3 and {r["session"] for r in rows} == {"sess-cloud"} and {r["remote_session"] for r in rows} == {"TESTID"}, rows
    assert sorted(r["role"] for r in rows) == ["main", "main", "subagent"]       # the subagent's record has the parent's session id
    assert all(list(r) == list(ledger_cost.FIELDS) for r in rows)
    assert {r["remote_session"] for r in captured("capture-diff", {**cloud, current: "sess-running"}, subagent=True)} == {None}
    assert {r["remote_session"] for r in captured("capture-nocur", {remote: "cse_TESTID"})} == {None}
    assert {r["remote_session"] for r in captured("capture-local", None)} == {None}
    assert {r["remote_session"] for r in captured("capture-odd", {**cloud, remote: "not-a-cloud-session"})} == {None}
    # a directory of transcripts: only the running session's own gets the id; the others are past sessions
    mixed = captured("capture-many", cloud, sessions=("sess-old", "sess-cloud", "sess-older"), many=True)
    assert {r["session"]: r["remote_session"] for r in mixed} == {"sess-old": None, "sess-cloud": "TESTID", "sess-older": None}, mixed


@case("a record captured before the field existed reads as null, prices as before and still passes the allowlist")
def _():
    sb = Sandbox("old-records")
    old = record(1, stamp(1))
    del old["remote_session"]
    put(sb, "s1", [old])
    projected = ledger_cost.project(old)
    assert projected is not None and projected["remote_session"] is None and list(projected) == list(ledger_cost.FIELDS)
    assert json.loads(ledger_cost.record_line(projected))["remote_session"] is None
    report = sb.report()
    assert report["requests"] == 1 and Decimal(report["total_cost"]) == Decimal("0.0001"), report["total_cost"]
    files = sb.views()
    assert table(files["sessions.csv"])[0]["remote_session"] == ""
    # a value that is not an id never survives the allowlist
    for bad in ("a b", "x" * 80, 7, ["TESTID"], ""):
        assert ledger_cost.project({**old, "remote_session": bad})["remote_session"] is None, bad


# ---------------------------------------------------------------- C: active time

def credits(rows: list[dict], gap_minutes: int = 30) -> list[timedelta]:
    return ledger_views.active_credits(rows, timedelta(minutes=gap_minutes))


@case("a gap just under, at and just over the limit: only a gap of at most the limit counts, and it goes to the later request")
def _():
    just_under, exactly, just_over = timedelta(minutes=29, seconds=59), timedelta(minutes=30), timedelta(minutes=30, seconds=1)
    for gap, expected in ((just_under, just_under), (exactly, exactly), (just_over, timedelta(0))):
        rows = [record(1, stamp()), record(2, stamp(seconds=gap.total_seconds()))]
        assert credits(rows) == [timedelta(0), expected], (gap, credits(rows))
    chain = [record(1, stamp(0)), record(2, stamp(29, 59)), record(3, stamp(29, 59 + 1800)), record(4, stamp(29, 59 + 1800 + 1801))]
    assert credits(chain) == [timedelta(0), just_under, exactly, timedelta(0)], credits(chain)
    assert credits([record(1, stamp(0)), record(2, stamp(7))], gap_minutes=6) == [timedelta(0), timedelta(0)]
    assert credits([record(1, stamp(0)), record(2, stamp(6))], gap_minutes=6) == [timedelta(0), timedelta(minutes=6)]


@case("the interval is credited to the task of the later request, and the first request of a stretch adds nothing")
def _():
    sb = Sandbox("later")
    rows = [record(1, stamp(0), branch="feat/x"),
            record(2, stamp(10), branch="feat/x"),
            record(3, stamp(100), branch="feat/y"),     # 90 minutes idle: nothing, not even to feat/y
            record(4, stamp(105), branch="feat/y")]
    put_all(sb, rows)
    tasks = task_rows(sb.views("--prs", write_prs(sb, [pull(10, "feat/x"), pull(11, "feat/y")])))
    assert minutes(tasks[f"{REPO}#10"]) == 10 and minutes(tasks[f"{REPO}#11"]) == 5, {k: v["active_minutes"] for k, v in tasks.items()}


@case("a branch switch: the time between the last request on one branch and the first on the next goes to the next branch")
def _():
    sb = Sandbox("switch")
    rows = [record(1, stamp(0), branch="feat/x"), record(2, stamp(1), branch="feat/x"),
            record(3, stamp(11), branch="feat/y"), record(4, stamp(12), branch="feat/y")]
    put_all(sb, rows)
    tasks = task_rows(sb.views("--prs", write_prs(sb, [pull(10, "feat/x"), pull(11, "feat/y")])))
    assert (minutes(tasks[f"{REPO}#10"]), minutes(tasks[f"{REPO}#11"])) == (1, 11), {k: v["active_minutes"] for k, v in tasks.items()}
    assert minutes(table(sb.views()["sessions.csv"])[0]) == 12   # the session's own total is the sum of both


@case("subagents running in parallel with the main transcript share the session's timeline and are not counted twice")
def _():
    main = [record(n, stamp(10 * n)) for n in range(3)]                                   # 0, 10, 20
    side = [record(n, stamp(5 + 10 * n), role="subagent", rid="a") for n in range(2)]      # 5, 15
    twin = [record(n, stamp(5 + 10 * n), role="subagent", rid="b") for n in range(2)]      # 5, 15 again, another subagent
    rows = main + side + twin
    assert sum(credits(rows), timedelta(0)) == timedelta(minutes=20), sum(credits(rows), timedelta(0))
    sb = Sandbox("parallel")
    put(sb, "s1", rows)
    task = task_rows(sb.views("--prs", write_prs(sb, [pull(10, "feat/x")])))[f"{REPO}#10"]
    assert minutes(task) == 20 and task["sessions"] == "1" and task["requests"] == "7", task
    # the same requests as three separate sessions would have counted each timeline on its own
    split = [{**r, "session": f"s-{r['role']}-{r['id'][-2]}"} for r in rows]
    assert sum(credits(split), timedelta(0)) == timedelta(minutes=20 + 10 + 10)


@case("parallel sessions on one task each add their own time, and the span shows the calendar time")
def _():
    sb = Sandbox("two-sessions")
    one = [record(n, stamp(10 * n), session="s1", remote="IDONE", rid="a") for n in range(3)]    # 20 minutes, 0..20
    two = [record(n, stamp(5 + 10 * n), session="s2", remote="IDTWO", rid="b") for n in range(3)]  # 20 minutes, 5..25
    put_all(sb, one + two)
    task = task_rows(sb.views("--prs", write_prs(sb, [pull(10, "feat/x")])))[f"{REPO}#10"]
    assert minutes(task) == 40 and Decimal(task["span_minutes"]) == 25 and task["sessions"] == "2", task


@case("a session of the same id under another runtime is another timeline; a record without a time is outside every timeline")
def _():
    rows = [record(1, stamp(0)), record(2, stamp(5), runtime="codex"), record(3, stamp(10)), record(4, stamp(10), runtime="codex")]
    assert credits(rows) == [timedelta(0), timedelta(0), timedelta(minutes=10), timedelta(minutes=5)]
    assert credits([record(1, stamp(0)), {**record(2, stamp(5)), "time": None}, record(3, stamp(8))]) == [
        timedelta(0), timedelta(0), timedelta(minutes=8)]


@case("an interval across midnight is credited to the day of the later request; --gap-minutes changes the rule and is printed")
def _():
    sb = Sandbox("midnight")
    put_all(sb, [record(1, stamp(-10)), record(2, stamp(10)), record(3, stamp(55))])    # 23:50, 00:10, 00:55
    files = sb.views()
    days = {row["date"]: row for row in table(files["days.csv"])}
    assert (days["2026-10-09"]["requests"], minutes(days["2026-10-09"])) == ("1", 0), days["2026-10-09"]
    assert (days["2026-10-10"]["requests"], minutes(days["2026-10-10"])) == ("2", 20), days["2026-10-10"]   # 20 to 00:10; 45 is idle
    assert "gap 30 minutes" in files["tasks.md"] and "30 minutes apart" in files["README.md"]
    wide = sb.views("--gap-minutes", "60", out=sb.root / "wide")
    assert minutes({row["date"]: row for row in table(wide["days.csv"])}["2026-10-10"]) == 65 and "gap 60 minutes" in wide["days.md"]


@case("--repo keeps a session's timeline whole: the time spent in another repository is not turned into idle time here")
def _():
    sb = Sandbox("repo-scope")
    put_all(sb, [record(1, stamp(0), repo=REPO), record(2, stamp(20), repo="example/other", branch="feat/z"),
                 record(3, stamp(40), repo=REPO)])
    everything = task_rows(sb.views("--prs", write_prs(sb, [pull(10, "feat/x")])))
    scoped = task_rows(sb.views("--repo", REPO, "--prs", write_prs(sb, [pull(10, "feat/x")]), out=sb.root / "scoped"))
    assert minutes(everything[f"{REPO}#10"]) == minutes(scoped[f"{REPO}#10"]) == 20, (everything, scoped)
    assert "every repository" in sb.views()["README.md"] and "example/app only" in sb.views("--repo", REPO, out=sb.root / "o2")["README.md"]


# ---------------------------------------------------------------- B: session attribution

def attribution_fixture(sb: Sandbox) -> tuple[str, str]:
    """Requests on a base branch, an unknown branch and a PR branch for sessions that produced one, none
    and several pull requests; returns the prs and changes files."""
    rows = [
        record(1, stamp(0), branch="main", remote="ONE"),               # base branch, one PR   -> #10 by session
        record(2, stamp(1), branch=None, remote="ONE", source="unknown"),   # unknown branch        -> #10 by session
        record(3, stamp(2), branch="feat/x", remote="ONE"),             # its own PR by branch  -> #10 by branch
        record(4, stamp(0), branch="main", remote="NONE", session="s2"),    # session produced nothing -> stays
        record(5, stamp(0), branch="main", remote=None, session="s3"),      # local record, no id      -> stays
        record(6, stamp(0), branch="main", remote="TWO", session="s4"),     # two PRs                  -> stays, counted
        record(7, stamp(1), branch="feat/x", remote="TWO", session="s4"),
        record(8, stamp(0), branch="feat/y", remote="ONE", session="s5"),   # branch has a PR (#11): the branch rule wins
        record(9, stamp(0), branch="main", remote="ONE", session="s6", repo="example/other"),  # id is mapped only in example/app
        record(10, stamp(0), branch=None, repo=None, remote=None, session="s7", source="unknown"),  # repository and session unknown
    ]
    put_all(sb, rows)
    prs = write_prs(sb, [pull(10, "feat/x"), pull(11, "feat/y"), pull(12, "feat/w")])
    changes = write_changes(sb, [change(10, [link("ONE"), link("TWO")], head="feat/x"), change(12, [link("TWO")], head="feat/w"),
                                 change(0, [link("NONE")], kind="direct")])
    return prs, changes


@case("a request on the base branch or with an unknown branch goes to the one pull request its session produced, marked session")
def _():
    sb = Sandbox("session-one")
    prs, changes = attribution_fixture(sb)
    files = sb.views("--prs", prs, "--changes", changes)
    tasks = task_rows(files)
    assert tasks[f"{REPO}#10"]["requests"] == "4" and tasks[f"{REPO}#10"]["attribution"] == "reflog:2 session:2", tasks[f"{REPO}#10"]
    assert tasks[f"{REPO}#10"]["head_ref"] == "feat/x" and tasks[f"{REPO}#10"]["state"] == "pull_request"
    assert tasks[f"{REPO}#11"]["requests"] == "1"                                   # the branch rule won
    assert f"{REPO} @ main (no_pull_request)" in tasks and tasks[f"{REPO} @ main (no_pull_request)"]["requests"] == "3"  # NONE, local, TWO
    assert tasks["unknown_attribution"]["requests"] == "1"                          # no repository and no session id: stays
    assert tasks["example/other @ main (no_pull_request)"]["requests"] == "1"
    readme = files["README.md"]
    assert "| Moved to a pull request through their session | 2 |" in readme, readme
    assert "| Left in place: their session produced several pull requests | 1 |" in readme, readme
    assert "| Unknown attribution (repository or branch unknown) | 1 |" in readme


@case("without --changes the same requests stay where the branch rule puts them, and the README says session attribution is skipped")
def _():
    sb = Sandbox("session-none")
    prs, _ = attribution_fixture(sb)
    files = sb.views("--prs", prs)
    tasks = task_rows(files)
    assert tasks[f"{REPO}#10"]["requests"] == "2" and "session" not in tasks[f"{REPO}#10"]["attribution"]
    assert "skipped: no `--changes` given" in files["README.md"]
    assert "| Moved to a pull request through their session | 0 |" in files["README.md"]
    without_prs = sb.views("--changes", write_changes(sb, [change(10, [link("ONE")])]), out=sb.root / "noprs")
    assert "skipped: `--changes` was given without `--prs`" in without_prs["README.md"]
    assert all(row["state"] in ("branch", "unknown_attribution") for row in table(without_prs["tasks.csv"]))


@case("only a landed pull request row with a session link maps a session; a trailer that is not a link, a direct commit and another repository do not")
def _():
    sb = Sandbox("session-map")
    path = write_changes(sb, [change(10, [link("ONE"), "not a link", "Claude-Session: " + link("TWO")]),
                              change(0, [link("THREE")], kind="direct"),
                              change(11, [link("FOUR")], repo="example/other")])
    with open(path, "a") as handle:
        handle.write("not json\n[1]\n")
    mapping = ledger_cost.session_map([path, path])
    assert mapping.by_id == {"ONE": {(REPO, 10): (REPO, None)}, "TWO": {(REPO, 10): (REPO, None)},
                             "FOUR": {("example/other", 11): ("example/other", None)}}, mapping.by_id
    assert mapping.produced("FOUR", None) == [("example/other", 11, None)] and mapping.produced("FOUR", REPO) == []
    assert mapping.produced("FOUR", "Example/Other") == [("example/other", 11, None)] and mapping.produced("NOPE", None) == []
    try:
        ledger_cost.session_map([str(sb.root / "missing.jsonl")])
    except ledger_cost.LedgerError as error:
        assert "missing.jsonl" in str(error)
    else:
        raise AssertionError("a missing --changes file was accepted")
    # the repository compares case-insensitively; the task keeps the record's spelling
    sb2 = Sandbox("session-case")
    put_all(sb2, [record(1, stamp(0), branch="main", repo="Example/App", remote="ONE")])
    tasks = task_rows(sb2.views("--prs", write_prs(sb2, [pull(10, "feat/x")], repo="Example/App"),
                                "--changes", write_changes(sb2, [change(10, [link("ONE")], repo="example/app")])))
    assert "Example/App#10" in tasks, tasks


@case("report accepts --changes more than once: landed split as before, and the session rule with the counts in JSON and text")
def _():
    sb = Sandbox("report-changes")
    prs, changes = attribution_fixture(sb)
    plain = sb.report("--prs", prs)
    assert "session_attribution" not in plain and "session_ambiguous" not in plain["unknown"]
    second = write_changes(sb, [change(12, [link("OTHER")], head="feat/w")], name="second.jsonl")
    both = sb.report("--prs", prs, "--changes", changes, "--changes", second)
    assert both["session_attribution"] == {"applied": True, "assigned": 2, "ambiguous": 1}, both["session_attribution"]
    assert both["unknown"]["session_ambiguous"] == 1 and both["unknown"]["no_pull_request"] == 4, both["unknown"]
    assert both["unknown"]["attribution"] == 1 and plain["unknown"]["attribution"] == 2 and plain["unknown"]["no_pull_request"] == 5
    names = {row["name"]: row["requests"] for row in both["by_task"]}
    assert names[f"{REPO}#10"] == 4 and plain["by_task"] != both["by_task"], names
    # #10 (4 requests, 2 of them by session) and #12 are landed, #11 is not
    assert Decimal(both["landed_split"]["landed"]) == Decimal("0.0004") and Decimal(both["landed_split"]["not_landed"]) == Decimal("0.0001"), both["landed_split"]
    # the landed split reads every file: #12 is landed only through the second file here
    only_second = sb.report("--prs", prs, "--changes", second)
    assert Decimal(only_second["landed_split"]["landed"]) == 0 and "session_attribution" in only_second
    code, text, err = sb.ledger_cmd("report", *PERIOD, "--prs", prs, "--changes", changes)
    assert code == 0 and "session attribution: 2 request(s) moved" in text and "1 left" in text, text
    code, text, err = sb.ledger_cmd("report", *PERIOD, "--changes", changes)
    assert code == 0 and "session attribution: skipped (it needs --prs)" in text, text
    code, text, err = sb.ledger_cmd("report", *PERIOD, "--prs", prs)
    assert code == 0 and "session attribution" not in text


def unplaced_fixture(sb: Sandbox) -> tuple[str, str]:
    """Requests with no repository (a cloud session that started outside any checkout) for sessions that
    produced one pull request in one repository, in another, several across repositories, or none."""
    rows = [
        record(1, stamp(0), repo=None, branch=None, remote="INAPP", session="u1", source="unknown"),     # -> example/app#10
        record(2, stamp(10), repo=REPO, branch="feat/x", remote="INAPP", session="u1"),                  # its own PR by branch
        record(3, stamp(0), repo=None, branch=None, remote="INOTHER", session="u2", source="unknown"),   # -> example/other#5 only
        record(4, stamp(0), repo=None, branch=None, remote="CROSS", session="u3", source="unknown"),     # 10 and 5: stays, counted
        record(5, stamp(0), repo=None, branch=None, remote="NOPE", session="u4", source="unknown"),      # produced nothing: stays
        record(6, stamp(0), repo=None, branch=None, remote=None, session="u5", source="unknown"),        # a local session: stays
        record(7, stamp(0), repo=None, branch="main", remote="INAPP", session="u6", source="unknown"),   # branch known, repository not
    ]
    put_all(sb, rows)
    prs = write_prs(sb, [pull(10, "feat/x")])
    changes = write_changes(sb, [change(10, [link("INAPP"), link("CROSS")], head="feat/x"),
                                 change(5, [link("INOTHER"), link("CROSS")], repo="example/other", head="feat/q")])
    return prs, changes


@case("a request with no repository goes to the one pull request its session produced across all repositories, and takes that repository")
def _():
    sb = Sandbox("unplaced")
    prs, changes = unplaced_fixture(sb)
    files = sb.views("--prs", prs, "--changes", changes)
    tasks = task_rows(files)
    assert tasks[f"{REPO}#10"]["requests"] == "3" and tasks[f"{REPO}#10"]["attribution"] == "reflog:1 session:2", tasks[f"{REPO}#10"]
    assert tasks["example/other#5"]["requests"] == "1" and tasks["example/other#5"]["attribution"] == "session:1"
    assert tasks["example/other#5"]["head_ref"] == "feat/q"        # the head ref comes from the changes row
    assert tasks["unknown_attribution"]["requests"] == "3", tasks["unknown_attribution"]   # CROSS, NOPE and the local one
    assert minutes(tasks[f"{REPO}#10"]) == 10                       # the first request of the session has no earlier one
    readme = files["README.md"]
    assert "| Moved to a pull request through their session | 3 |" in readme and "several pull requests | 1 |" in readme, readme
    assert "| Unknown attribution (repository or branch unknown) | 3 |" in readme
    by_session = {r["session"]: r for r in table(files["sessions.csv"])}
    assert by_session["u2"]["pull_requests"] == "example/other#5" and by_session["u3"]["pull_requests"] == ""
    # without --prs nothing is moved; without --changes neither
    assert "unknown_attribution" in task_rows(sb.views("--changes", changes, out=sb.root / "noprs"))
    plain = sb.report("--prs", prs)
    both = sb.report("--prs", prs, "--changes", changes)
    assert plain["unknown"]["attribution"] == 6 and both["unknown"]["attribution"] == 3, (plain["unknown"], both["unknown"])
    assert both["session_attribution"] == {"applied": True, "assigned": 3, "ambiguous": 1}, both["session_attribution"]
    names = {row["name"]: row["requests"] for row in both["by_task"]}
    assert names[f"{REPO}#10"] == 3 and names["example/other#5"] == 1 and names["unknown attribution"] == 3, names


@case("--repo counts a request in the repository it is placed in; only a request still without one is left out as unknown")
def _():
    sb = Sandbox("unplaced-scope")
    prs, changes = unplaced_fixture(sb)
    scoped = sb.report("--prs", prs, "--changes", changes, "--repo", REPO)
    assert scoped["requests"] == 3 and scoped["scope"] == {"repository": REPO, "other_repositories": 1, "unknown_repository": 3}, scoped["scope"]
    assert {row["name"] for row in scoped["by_task"]} == {f"{REPO}#10"} and scoped["unknown"]["attribution"] == 0
    other = sb.report("--prs", prs, "--changes", changes, "--repo", "Example/Other")
    assert other["requests"] == 1 and other["scope"]["other_repositories"] == 3 and other["scope"]["unknown_repository"] == 3, other["scope"]
    # no session rule: all the requests that have no repository are unknown, as before
    before = sb.report("--prs", prs, "--repo", REPO)
    assert before["requests"] == 1 and before["scope"] == {"repository": REPO, "other_repositories": 0, "unknown_repository": 6}, before["scope"]
    # views: the same counts; the active time of the whole session stays with the later request's task
    files = sb.views("--prs", prs, "--changes", changes, "--repo", REPO)
    tasks = task_rows(files)
    assert set(tasks) == {f"{REPO}#10"} and tasks[f"{REPO}#10"]["requests"] == "3" and minutes(tasks[f"{REPO}#10"]) == 10, tasks
    assert "| Left out: other repositories | 1 |" in files["README.md"] and "| Left out: repository unknown | 3 |" in files["README.md"]
    assert "example/app only" in files["README.md"]
    everything = task_rows(sb.views("--prs", prs, "--changes", changes, out=sb.root / "all"))
    assert minutes(everything[f"{REPO}#10"]) == minutes(tasks[f"{REPO}#10"]) == 10


@case("a row whose requests are all unpriced has no cost (empty in CSV, `unpriced` in Markdown), not zero; a mixed row keeps its priced sum")
def _():
    sb = Sandbox("unpriced")
    rows = [record(1, stamp(0), branch="feat/x", session="s1"),                                   # priced
            record(2, stamp(1), branch="feat/x", session="s1", model="gpt-test"),                  # not priced: a mixed row
            record(3, stamp(0), branch="feat/y", session="s2", model="gpt-test"),                  # only unpriced: task, session, model
            record(4, stamp(1), branch="feat/y", session="s2", model="gpt-test", role="subagent")]
    put_all(sb, rows)
    files = sb.views("--prs", write_prs(sb, [pull(10, "feat/x"), pull(11, "feat/y")]),
                     period=("--since", "2026-10-10", "--until", "2026-10-12"))
    tasks = task_rows(files)
    mixed, bare = tasks[f"{REPO}#10"], tasks[f"{REPO}#11"]
    assert (mixed["cost_usd"], mixed["unknown_cost_requests"]) == ("0.000100", "1"), mixed
    assert (bare["cost_usd"], bare["cost_main"], bare["cost_subagent"], bare["cost_other"], bare["unknown_cost_requests"]) == ("", "", "", "", "2"), bare
    md = {l.split("|")[3].strip(): l for l in files["tasks.md"].splitlines() if l.startswith(f"| {REPO}")}
    assert "$0.0001 (+1 unpriced)" in md["#10"] and md["#11"].count("unpriced") == 2 and "$0.0000" not in md["#11"], md
    models = {r["model"]: r for r in table(files["models.csv"])}
    assert models["gpt-test"]["cost_usd"] == "" and models["gpt-test"]["share"] == "" and models[HAIKU]["share"] == "1.0000", models
    assert "| gpt-test | 3 | unpriced | - |" in files["models.md"], files["models.md"]
    sessions = {r["session"]: r for r in table(files["sessions.csv"])}
    assert sessions["s2"]["cost_usd"] == "" and sessions["s1"]["cost_usd"] == "0.000100"
    days = {r["date"]: r for r in table(files["days.csv"])}
    assert days["2026-10-10"]["cost_usd"] == "0.000100" and days["2026-10-11"]["cost_usd"] == "0.000000"   # a day with no request is a real zero
    alone = Sandbox("unpriced-day")
    put_all(alone, [record(1, stamp(0), model="gpt-test")])
    once = alone.views("--prs", write_prs(alone, [pull(10, "feat/x")]), period=("--since", "2026-10-10", "--until", "2026-10-11"))
    assert table(once["days.csv"])[0]["cost_usd"] == "" and table(once["days.csv"])[1]["cost_usd"] == "0.000000"
    assert "| Cost | unpriced |" in once["README.md"] and "| unpriced |" in once["days.md"]


@case("repository names compare without case: landed split, rework and tasks agree when a record, `--prs` and `changes` spell it differently")
def _():
    sb = Sandbox("repo-case")
    put_all(sb, [record(1, stamp(0), repo="Example/App", branch="feat/x", remote="ONE", session="s1"),
                 record(2, stamp(1), repo=None, branch=None, remote="ONE", session="s2", source="unknown"),       # moved by session
                 record(3, stamp(2), repo="Example/App", branch="feat/y", remote="TWO", session="s3")])
    prs = write_prs(sb, [pull(10, "feat/x"), pull(11, "feat/y")], repo="Example/App")
    changes = write_changes(sb, [change(10, [link("ONE")], repo="example/app", head="feat/x"),
                                 change(11, [link("TWO")], repo="EXAMPLE/APP", head="feat/y")])
    rework = sb.root / "rework.json"
    rework.write_text(json.dumps({"repository": "example/APP", "reworked_changes": [{"number": 10, "fixed_by": [11]}]}))
    report = sb.report("--prs", prs, "--changes", changes, "--rework", str(rework))
    names = {row["name"]: row["requests"] for row in report["by_task"]}
    assert names == {"Example/App#10": 2, "Example/App#11": 1}, names                 # one task, one spelling
    assert Decimal(report["landed_split"]["landed"]) == Decimal("0.0003") and Decimal(report["landed_split"]["not_landed"]) == 0, report["landed_split"]
    assert report["rework"]["reworked_changes"] == 1, report["rework"]
    assert Decimal(report["rework"]["cost_of_reworked"]) == Decimal("0.0002") and Decimal(report["rework"]["cost_of_fixes"]) == Decimal("0.0001"), report["rework"]
    files = sb.views("--prs", prs, "--changes", changes)
    tasks = task_rows(files)
    assert set(tasks) == {"Example/App#10", "Example/App#11"} and tasks["Example/App#10"]["requests"] == "2", set(tasks)
    assert {r["pull_requests"] for r in table(files["sessions.csv"])} == {"Example/App#10", "Example/App#11"}
    assert {r["repositories"] for r in table(files["sessions.csv"])} == {"Example/App", ""}
    # --repo matches without case too
    assert sb.report("--prs", prs, "--changes", changes, "--repo", "EXAMPLE/app")["requests"] == 3


@case("a pull request is found whatever the case of the repository name in the record and in --prs: the branch rule wins over the session")
def _():
    sb = Sandbox("case-branch")
    put_all(sb, [record(1, stamp(0), repo="Example/App", branch="feat/y", remote="ONE", session="s1"),     # its own PR (#11) by branch
                 record(2, stamp(1), repo="Example/App", branch="main", remote="ONE", session="s1"),       # base branch: the session's #10
                 record(3, stamp(2), repo="Example/App", branch="feat/x", remote="ONE", session="s1")])
    prs = write_prs(sb, [pull(10, "feat/x"), pull(11, "feat/y")], repo="example/app")
    changes = write_changes(sb, [change(10, [link("ONE")], repo="example/app", head="feat/x")])
    tasks = task_rows(sb.views("--prs", prs, "--changes", changes))
    assert {k: (v["requests"], v["attribution"]) for k, v in tasks.items()} == {
        "Example/App#10": ("2", "reflog:1 session:1"), "Example/App#11": ("1", "reflog:1")}, tasks
    report = sb.report("--prs", prs, "--changes", changes)
    assert report["session_attribution"] == {"applied": True, "assigned": 1, "ambiguous": 0}, report["session_attribution"]
    assert {row["name"]: row["requests"] for row in report["by_task"]} == {"Example/App#10": 2, "Example/App#11": 1}


@case("every comparison of a repository name ignores case, with the record, --prs, --changes, --rework and --repo all spelled differently")
def _():
    spellings = [("record", "EXAMPLE/APP"), ("prs", "Example/app"), ("changes", "example/APP"), ("rework", "exAMPLE/app"), ("scope", "ExAmPlE/aPp")]
    sb = Sandbox("case-all")
    record_name, prs_name, changes_name, rework_name, scope_name = (name for _, name in spellings)
    put_all(sb, [record(1, stamp(0), repo=record_name, branch="feat/x", remote="ONE", session="s1"),
                 record(2, stamp(1), repo=None, branch=None, remote="ONE", session="s2", source="unknown"),   # no repository: the session's #10
                 record(3, stamp(2), repo=record_name, branch="feat/y", remote="ONE", session="s3"),     # its own PR, not the session's
                 record(4, stamp(3), repo="example/other", branch="feat/x", remote=None, session="s4")])     # another repository
    prs = write_prs(sb, [pull(10, "feat/x"), pull(11, "feat/y")], repo=prs_name)
    changes = write_changes(sb, [change(10, [link("ONE")], repo=changes_name, head="feat/x"),
                                 change(11, [link("TWO")], repo=changes_name, head="feat/y")])
    rework = sb.root / "rework.json"
    rework.write_text(json.dumps({"repository": rework_name, "reworked_changes": [{"number": 10, "fixed_by": [11]}]}))
    report = sb.report("--prs", prs, "--changes", changes, "--rework", str(rework), "--repo", scope_name)
    assert report["requests"] == 3 and report["scope"] == {"repository": scope_name, "other_repositories": 1, "unknown_repository": 0}, report["scope"]
    assert {row["name"]: row["requests"] for row in report["by_task"]} == {"EXAMPLE/APP#10": 2, "EXAMPLE/APP#11": 1}, report["by_task"]
    assert Decimal(report["landed_split"]["landed"]) == Decimal("0.0003") and Decimal(report["landed_split"]["not_landed"]) == 0
    assert Decimal(report["rework"]["cost_of_reworked"]) == Decimal("0.0002") and Decimal(report["rework"]["cost_of_fixes"]) == Decimal("0.0001"), report["rework"]
    files = sb.views("--prs", prs, "--changes", changes, "--repo", scope_name)
    tasks = task_rows(files)
    assert set(tasks) == {"EXAMPLE/APP#10", "EXAMPLE/APP#11"} and tasks["EXAMPLE/APP#10"]["requests"] == "2", set(tasks)
    assert "| Left out: other repositories | 1 |" in files["README.md"]
    assert ledger_cost.repo_key(" Example/App ") == "example/app" and ledger_cost.repo_key(None) == ""


@case("views fetches the store into a scratch directory: a read-only ledger directory works and gets nothing; --store-cache is used when given")
def _():
    sb = Sandbox("store-cache")
    bare = sb.root / "store.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
    sb.config.write_text(f"ledger.store = {bare}\n")
    put_all(sb, [record(1, stamp(0))])
    code, out, err = sb.ledger_cmd("export")
    assert code == 0, err
    shutil.rmtree(sb.ledger / "pending", ignore_errors=True)                  # only the store holds the records now
    for name in ("state", "exported", "exported-conflicts", "conflicts"):
        shutil.rmtree(sb.ledger / name, ignore_errors=True)
    before = snapshot(sb.ledger)
    modes = []
    for path in [sb.ledger, *sorted(sb.ledger.rglob("*"))]:
        if path.is_dir():
            modes.append((path, path.stat().st_mode))
            path.chmod(0o555)
    scratch = Path(tempfile.gettempdir())
    leftovers = lambda: sorted(p.name for p in scratch.glob("plumb-ledger-views-*"))
    before_tmp = leftovers()
    try:
        files = sb.views(out=sb.root / "direct")
        assert len(table(files["tasks.csv"])) == 1 and "Store: ok" in files["README.md"], files["README.md"]
        assert snapshot(sb.ledger) == before, set(snapshot(sb.ledger)) ^ set(before)
        assert not list(sb.ledger.glob("store-cache-*")) and leftovers() == before_tmp
        kept = sb.root / "kept-cache.git"
        sb.views("--store-cache", str(kept), out=sb.root / "second")
        assert (kept / "HEAD").exists() and snapshot(sb.ledger) == before
        # nothing of the cache lands in the output directory
        assert sorted(p.name for p in (sb.root / "second").iterdir()) == sorted(ledger_views.GENERATED)
    finally:
        for path, mode in reversed(modes):
            path.chmod(mode)
    # the same store with `report` still keeps its cache beside the records (unchanged)
    code, out, err = sb.ledger_cmd("report", *PERIOD)
    assert code == 0 and list(sb.ledger.glob("store-cache-*")), err


# ---------------------------------------------------------------- D: views

FILES = ["README.md", "agents.csv", "agents.md", "days.csv", "days.md", "models.csv", "models.md", "sessions.csv", "tasks.csv",
         "tasks.md"]


@case("views writes README, tasks, days, models, agents and sessions, and prints one summary line")
def _():
    sb = Sandbox("files")
    put_all(sb, [record(1, stamp(0)), record(2, stamp(5), model=OPUS, out=2000), record(3, stamp(9), role="subagent")])
    code, out, err = sb.ledger_cmd("views", *PERIOD, "--out", str(sb.out), "--prs", write_prs(sb, [pull(10, "feat/x")]))
    assert code == 0 and out.startswith("views: 3 requests, 1 tasks, 10 files"), (out, err)
    assert sorted(p.name for p in sb.out.iterdir()) == FILES
    files = {name: (sb.out / name).read_bytes().decode() for name in FILES}
    tasks = table(files["tasks.csv"])
    assert len(tasks) == 1 and tasks[0]["requests"] == "3" and Decimal(tasks[0]["active_minutes"]) == 9, tasks
    assert Decimal(tasks[0]["cost_main"]) + Decimal(tasks[0]["cost_subagent"]) == Decimal(tasks[0]["cost_usd"]), tasks[0]
    assert tasks[0]["cost_opus"] and tasks[0]["cost_haiku"] and not tasks[0]["cost_sonnet"], tasks[0]
    models = {row["model"]: row for row in table(files["models.csv"])}
    assert set(models) == {HAIKU, OPUS} and models[OPUS]["family"] == "opus" and models[OPUS]["output"] == "2000", models
    assert abs(Decimal(models[OPUS]["share"]) + Decimal(models[HAIKU]["share"]) - 1) < Decimal("0.0002"), models
    assert "Period 2026-10-09 .. 2026-10-11 (days in UTC)" in files["README.md"]
    for name in FILES[1:]:
        assert f"[{name}]({name})" in files["README.md"], name


def agent_record(n, minutes, *, agent_type="implementer", agent_id=None, role="subagent", session="s1", model=HAIKU,
                 inp=0, cache_read=0, w5=0, w1=0, out=0, branch="feat/x") -> dict:
    row = record(n, stamp(minutes), session=session, role=role, model=model, inp=inp, out=out, branch=branch)
    row.update({"agent_type": agent_type if role == "subagent" else None, "agent_id": agent_id,
                "cache_read": cache_read, "cache_write_5m": w5, "cache_write_1h": w1})
    return row


@case("agents: one row per role, agent type and model; threads, medians of first and peak context, unpriced and share as in models")
def _():
    sb = Sandbox("agents")
    rows = [
        # main, session s1: written latest first, the first request is the earliest by time (context 1,000)
        agent_record(2, 1, role="main", inp=3000, cache_read=2000),                      # 5,000
        agent_record(1, 0, role="main", inp=1000),                                        # 1,000
        agent_record(3, 0, role="main", session="s2", inp=200, w5=300),                   # 500
        # implementer a1 of s1 used two models: it is a thread of each row
        agent_record(4, 3, agent_id="a1", inp=100, cache_read=100),                       # 200
        agent_record(5, 4, agent_id="a1", inp=2000, w1=1000),                             # 3,000
        agent_record(6, 5, agent_id="a1", model=OPUS, inp=400),                           # 400
        agent_record(7, 6, agent_id="a2", inp=600),                                       # 600
        # reviewer without an agent id: one thread per session
        agent_record(8, 3, agent_type="reviewer", session="s2", inp=1000),
        agent_record(9, 4, agent_type="reviewer", session="s2", inp=4000),
        agent_record(10, 5, agent_type="reviewer", session="s3", inp=50),
        # a subagent with no agent type, on a model that has no price
        agent_record(11, 6, agent_type=None, agent_id="a3", model="gpt-test", inp=700),
        agent_record(12, 7, agent_type=None, agent_id="a3", model="gpt-test", inp=900)]
    put_all(sb, rows)
    files = sb.views()
    assert files["agents.csv"].startswith("role,agent_type,model,threads,requests,unknown_cost_requests,cost_usd,share,"
                                          "median_first_context,median_peak_context\r\n"), files["agents.csv"]
    got = {(r["role"], r["agent_type"], r["model"]): r for r in table(files["agents.csv"])}
    assert set(got) == {("main", "-", HAIKU), ("subagent", "implementer", HAIKU), ("subagent", "implementer", OPUS),
                        ("subagent", "reviewer", HAIKU), ("subagent", "-", "gpt-test")}, list(got)
    main = got[("main", "-", HAIKU)]
    assert (main["threads"], main["requests"], main["median_first_context"], main["median_peak_context"]) == ("2", "3", "750", "2750"), main
    both = got[("subagent", "implementer", HAIKU)]
    assert (both["threads"], both["requests"], both["median_first_context"], both["median_peak_context"]) == ("2", "3", "400", "1800"), both
    opus = got[("subagent", "implementer", OPUS)]
    assert (opus["threads"], opus["requests"], opus["cost_usd"], opus["median_first_context"]) == ("1", "1", "0.001600", "400"), opus
    reviewer = got[("subagent", "reviewer", HAIKU)]
    assert (reviewer["threads"], reviewer["requests"], reviewer["median_first_context"], reviewer["median_peak_context"]) == ("2", "3", "525", "2025"), reviewer
    bare = got[("subagent", "-", "gpt-test")]
    assert (bare["threads"], bare["requests"], bare["unknown_cost_requests"], bare["cost_usd"], bare["share"]) == ("1", "2", "2", "", ""), bare
    assert (bare["median_first_context"], bare["median_peak_context"]) == ("700", "900"), bare
    models = table(files["models.csv"])
    priced = sum(Decimal(r["cost_usd"]) for r in models if r["cost_usd"])
    assert sum(Decimal(r["cost_usd"]) for r in got.values() if r["cost_usd"]) == priced
    assert sum(Decimal(r["share"]) for r in got.values() if r["share"]) - 1 < Decimal("0.0003")
    costs = [Decimal(r["cost_usd"]) for r in table(files["agents.csv"]) if r["cost_usd"]]
    assert costs == sorted(costs, reverse=True) and table(files["agents.csv"])[0]["model"] == OPUS, costs
    md = files["agents.md"]
    assert "| Role | Agent type | Model | Threads | Requests | Cost | Share | Median first context | Median peak context |" in md, md
    assert "| subagent | - | gpt-test | 1 | 2 | unpriced | - | 700 | 900 |" in md, md
    assert "| main | - | claude-haiku-5-5 | 2 | 3 |" in md and "| 750 | 2,750 |" in md, md
    assert "runs on the main thread's model" in md and "cannot show whether a model is inherited or set" in md, md
    assert "[agents.md](agents.md), [agents.csv](agents.csv)" in files["README.md"]


@case("agents: the median of an even number of threads rounds a half up, and a row with no thread has no median")
def _():
    acc = ledger_views.AgentAcc()
    assert acc.median(1) is None
    for number, size in enumerate((1, 2, 7, 8)):
        acc.add_thread(("claude", "s", str(number)), agent_record(number, 0, inp=size), BASE, number)
    assert (acc.median(1), acc.median(2)) == (5, 5), (acc.median(1), acc.median(2))   # sorted 1, 2, 7, 8: (2 + 7) / 2 = 4.5, up
    other = ledger_views.AgentAcc()
    for number, size in enumerate((1, 2)):
        other.add_thread(("claude", "s", str(number)), agent_record(number, 0, inp=size), BASE, number)
    assert other.median(1) == 2


@case("the same records give the same bytes, whatever the hash seed and the order the files are read in")
def _():
    sb = Sandbox("deterministic")
    rows = [record(n, stamp(3 * n), session=f"s{n % 4}", remote=f"ID{n % 3}", branch=("main", "feat/x", "feat/y", None)[n % 4],
                   model=(HAIKU, OPUS, "claude-sonnet-5-5", "gpt-test")[n % 4], role=("main", "subagent")[n % 2]) for n in range(40)]
    put_all(sb, rows)
    prs = write_prs(sb, [pull(10, "feat/x"), pull(11, "feat/y")])
    changes = write_changes(sb, [change(10, [link("ID0")]), change(11, [link("ID1"), link("ID2")])])
    runs = [sb.views("--prs", prs, "--changes", changes, out=sb.root / f"run{seed}", extra_env={"PYTHONHASHSEED": seed})
            for seed in ("1", "2", "random")]
    assert runs[0] == runs[1] == runs[2], [name for name in runs[0] if runs[0][name] != runs[1][name]]
    assert "\r\n" in runs[0]["tasks.csv"] and runs[0]["tasks.md"].endswith("\n") and "\r" not in runs[0]["tasks.md"]


@case("the Markdown tables hold the 50 costliest rows and say how many more the CSV has; the CSV holds every row, costliest first")
def _():
    sb = Sandbox("top-rows")
    rows = [record(n, stamp(n), branch=f"feat/b{n:02d}", session=f"s{n}", remote=None, inp=1000 + 10 * n) for n in range(60)]
    put_all(sb, rows)
    files = sb.views("--prs", write_prs(sb, [pull(100 + n, f"feat/b{n:02d}") for n in range(60)]))
    csv_rows = table(files["tasks.csv"])
    assert len(csv_rows) == 60
    costs = [Decimal(r["cost_usd"]) for r in csv_rows]
    assert costs == sorted(costs, reverse=True) and csv_rows[0]["pull_request"] == "159", csv_rows[0]
    md_rows = [l for l in files["tasks.md"].splitlines() if l.startswith("| feat") or l.startswith(f"| {REPO}")]
    assert len(md_rows) == 50 and "50 of 60 rows shown; 10 more in `tasks.csv`." in files["tasks.md"], len(md_rows)
    assert "#109" not in files["tasks.md"] and "#159" in files["tasks.md"]
    assert len(table(files["sessions.csv"])) == 60
    small = Sandbox("few-rows")
    put_all(small, [record(1, stamp(0))])
    assert "All 1 row; `tasks.csv` holds the same table." in small.views()["tasks.md"]


@case("a day table has one row per day of the period, empty days included, in the time zone given; the time zone changes the days")
def _():
    sb = Sandbox("days")
    put_all(sb, [record(1, "2026-10-10T23:30:00.000Z"), record(2, "2026-10-10T23:40:00.000Z"), record(3, "2026-10-12T00:00:00.000Z")])
    utc = sb.views(period=("--since", "2026-10-09", "--until", "2026-10-12"))
    days = {row["date"]: row["requests"] for row in table(utc["days.csv"])}
    assert days == {"2026-10-09": "0", "2026-10-10": "2", "2026-10-11": "0", "2026-10-12": "1"}, days
    assert [l.split("|")[1].strip() for l in utc["days.md"].splitlines() if l.startswith("| 2026")] == sorted(days)
    tokyo = sb.views("--timezone", "Asia/Tokyo", period=("--since", "2026-10-09", "--until", "2026-10-12"), out=sb.root / "tokyo")
    days = {row["date"]: row["requests"] for row in table(tokyo["days.csv"])}
    assert days == {"2026-10-09": "0", "2026-10-10": "0", "2026-10-11": "2", "2026-10-12": "1"}, days
    assert "days in Asia/Tokyo" in tokyo["README.md"]
    many = sb.views(period=("--since", "2026-07-01", "--until", "2026-10-12"), out=sb.root / "long")
    assert len(table(many["days.csv"])) == 104 and "54 more in `days.csv`" in many["days.md"] and "2026-10-12" in many["days.md"]


@case("a request whose cost cannot be known is counted and never added as zero")
def _():
    sb = Sandbox("unknown-cost")
    gone = record(3, stamp(2))
    gone["input"] = None
    put_all(sb, [record(1, stamp(0)), record(2, stamp(1), model="gpt-test"), gone])
    files = sb.views("--prs", write_prs(sb, [pull(10, "feat/x")]))
    task = task_rows(files)[f"{REPO}#10"]
    assert task["unknown_cost_requests"] == "2" and Decimal(task["cost_usd"]) == Decimal("0.0001") and task["cost_other"] == "", task
    assert "(+2 unpriced)" in files["tasks.md"] and "| Requests with unknown cost (not in the cost) | 2 |" in files["README.md"]
    models = {row["model"]: row for row in table(files["models.csv"])}
    assert models["gpt-test"]["unknown_cost_requests"] == "1" and models["gpt-test"]["cost_usd"] == "" and models["gpt-test"]["share"] == ""
    assert table(files["sessions.csv"])[0]["unknown_cost_requests"] == "2"


@case("cells are escaped: | and line breaks in Markdown, quotes, commas and line breaks in CSV (RFC 4180)")
def _():
    assert ledger_views.md_cell("a|b") == "a\\|b" and ledger_views.md_cell("a\nb\r\nc\rd") == "a<br>b<br>c<br>d"
    assert ledger_views.md_cell("a\\|b") == "a\\\\\\|b" and ledger_views.md_cell(12) == "12"
    nasty = ['say "hi"', "a,b", "line\nbreak", "cr\r\nlf", "", "plain"]
    text = ledger_views.csv_text(["h1", "h2"], [nasty[:2], nasty[2:4], nasty[4:]])
    assert text == 'h1,h2\r\n"say ""hi""","a,b"\r\n"line\nbreak","cr\r\nlf"\r\n,plain\r\n', repr(text)
    assert [list(r.values()) for r in table(text)] == [nasty[:2], nasty[2:4], nasty[4:]]
    # end to end: a head ref a pull request row carries (git allows | in a ref) must not break a row or a cell
    sb = Sandbox("escape")
    put_all(sb, [record(1, stamp(0), branch="main", remote="ONE")])
    head = "feat/a|b\nc,\"d\""
    files = sb.views("--prs", write_prs(sb, [pull(10, head)]), "--changes", write_changes(sb, [change(10, [link("ONE")])]))
    assert table(files["tasks.csv"])[0]["head_ref"] == head, table(files["tasks.csv"])
    rows = [l for l in files["tasks.md"].splitlines() if l.startswith(f"| {REPO}")]
    assert len(rows) == 1 and "feat/a\\|b<br>c,\"d\"" in rows[0], rows
    header = [l for l in files["tasks.md"].splitlines() if l.startswith("| Repository")][0]
    unescaped = lambda line: len([i for i, ch in enumerate(line) if ch == "|" and (i == 0 or line[i - 1] != "\\")])
    assert unescaped(rows[0]) == unescaped(header), (rows[0], header)


@case("views writes only the generated files under --out: other files stay, stale ones are replaced, nothing outside changes, a link is not followed")
def _():
    sb = Sandbox("only-out")
    put_all(sb, [record(1, stamp(0))])
    outside = sb.root / "outside.txt"
    outside.write_text("keep me")
    sibling = sb.root / "out-sibling"
    sibling.mkdir()
    (sibling / "tasks.csv").write_text("sibling")
    sb.out.mkdir()
    (sb.out / "notes.md").write_text("mine")
    (sb.out / "tasks.md").write_text("stale")
    (sb.out / "tasks.csv").symlink_to(outside)
    (sb.out / "sub").mkdir()
    (sb.out / "sub" / "tasks.csv").write_text("nested")
    before = {"outside": snapshot(sb.root / "home"), "sibling": snapshot(sibling), "ledger": snapshot(sb.ledger),
              "work": snapshot(sb.cwd), "outside.txt": outside.read_text()}
    files = sb.views()
    assert (sb.out / "notes.md").read_text() == "mine" and (sb.out / "sub" / "tasks.csv").read_text() == "nested"
    assert (sb.out / "tasks.md").read_text() == files["tasks.md"] != "stale"
    assert not (sb.out / "tasks.csv").is_symlink() and outside.read_text() == "keep me"
    assert {"outside": snapshot(sb.root / "home"), "sibling": snapshot(sibling), "ledger": snapshot(sb.ledger),
            "work": snapshot(sb.cwd), "outside.txt": outside.read_text()} == before
    assert not [p for p in sb.out.iterdir() if p.name.endswith(".tmp")]
    assert sorted(p.name for p in sb.out.iterdir()) == sorted(FILES + ["notes.md", "sub"])
    # a new directory is created, with parents
    nested = sb.views(out=sb.root / "a" / "b" / "views")
    assert sorted(nested) == FILES
    # a file named as the directory is refused, and nothing is written
    code, out, err = sb.ledger_cmd("views", *PERIOD, "--out", str(outside))
    assert code == 2 and "not a directory" in err and outside.read_text() == "keep me", (code, err)


@case("a views run over an empty ledger writes the files with headers only; bad options exit 2 and write nothing")
def _():
    sb = Sandbox("empty")
    files = sb.views()
    assert sorted(files) == FILES and table(files["tasks.csv"]) == [] and files["tasks.csv"].startswith("repository,head_ref,")
    assert "No rows." in files["tasks.md"] and "| Requests | 0 |" in files["README.md"]
    assert len(table(files["days.csv"])) == 3
    bad = sb.root / "never"
    for args in (["--gap-minutes", "0"], ["--timezone", "Not/AZone"], ["--since", "2026-10-11", "--until", "2026-10-09"],
                 ["--since", "later"]):
        period = PERIOD if "--since" not in args else ()
        code, out, err = sb.ledger_cmd("views", *period, "--out", str(bad), *args)
        assert code == 2 and not bad.exists(), (args, code, err)
    code, out, err = sb.ledger_cmd("views", *PERIOD)
    assert code == 2 and "--out" in err
    code, out, err = sb.ledger_cmd("views", "--help")
    assert code == 0 and "--gap-minutes" in out and "--changes" in out, out
    code, out, err = sb.ledger_cmd("--help")
    assert "views" in out


@case("the store alone is enough: the daily workflow's steps (fetch the session branches into the checkout, point ledger.store at it) give the same tables")
def _():
    sb = Sandbox("store")
    bare = sb.root / "store.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
    sb.config.write_text(f"ledger.store = {bare}\n")
    put_all(sb, [record(1, stamp(0)), record(2, stamp(5), session="s2", remote="IDTWO", model=OPUS)])
    code, out, err = sb.ledger_cmd("export")
    assert code == 0, err
    seed = sb.root / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
    for step in (["checkout", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "readme"], ["push", "-q", "origin", "main"]):
        subprocess.run(["git", "-C", str(seed), "-c", "user.name=t", "-c", "user.email=t@t", *step], check=True,
                       capture_output=True, env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"})
    direct = sb.views(out=sb.root / "direct")
    # the workflow: a full clone of the default branch, the session branches fetched in, ledger.store = the checkout
    checkout = sb.root / "checkout"
    subprocess.run(["git", "clone", "-q", str(bare), str(checkout)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(checkout), "fetch", "-q", "origin", "+refs/heads/plumb-ledger/*:refs/heads/plumb-ledger/*"],
                   check=True, capture_output=True)
    ci = Sandbox("store-ci")
    ci.config.write_text(f"ledger.store = {checkout}\n")
    code, out, err = ci.ledger_cmd("views", *PERIOD, "--timezone", "UTC", "--out", str(ci.out), cwd=checkout)
    assert code == 0, err
    files = {p.name: p.read_bytes().decode() for p in sorted(ci.out.iterdir())}
    assert files["tasks.csv"] == direct["tasks.csv"] and files["models.csv"] == direct["models.csv"], (files["tasks.csv"], direct["tasks.csv"])
    assert len(table(files["tasks.csv"])) == 1 and files["tasks.csv"].count("example/app") == 1
    assert "skipped: no `--changes` given" in files["README.md"] and "Store: ok" in files["README.md"]
    # views never pushes and never writes into the checkout
    assert subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"], capture_output=True, text=True).stdout == ""
    assert subprocess.run(["git", "-C", str(bare), "for-each-ref", "--format=%(refname)"], capture_output=True, text=True
                          ).stdout.split() == sorted(["refs/heads/main", "refs/heads/plumb-ledger/claude/s1", "refs/heads/plumb-ledger/claude/s2"])


@case("sessions.csv: one row per session with its remote id, repositories, branches, first and last request and the pull requests it was assigned")
def _():
    sb = Sandbox("sessions")
    put_all(sb, [record(1, stamp(0), branch="main", remote="ONE"), record(2, stamp(4), branch="feat/x", remote="ONE"),
                 record(3, stamp(9), session="s2", remote=None, branch="feat/y"),
                 record(4, stamp(2), session="s3", runtime="codex", remote=None, branch=None, source="unknown", repo=None)])
    files = sb.views("--prs", write_prs(sb, [pull(10, "feat/x"), pull(11, "feat/y")]),
                     "--changes", write_changes(sb, [change(10, [link("ONE")])]))
    rows = {(r["runtime"], r["session"]): r for r in table(files["sessions.csv"])}
    assert set(rows) == {("claude", "s1"), ("claude", "s2"), ("codex", "s3")}
    first = rows[("claude", "s1")]
    assert (first["remote_session"], first["repositories"], first["branches"], first["pull_requests"]) == (
        "ONE", REPO, "feat/x;main", f"{REPO}#10"), first
    assert (first["first_request"], first["last_request"], first["requests"], first["active_minutes"]) == (
        "2026-10-10T00:00:00.000Z", "2026-10-10T00:04:00.000Z", "2", "4.0"), first
    assert rows[("claude", "s2")]["pull_requests"] == f"{REPO}#11" and rows[("codex", "s3")]["pull_requests"] == ""
    assert [r["session"] for r in table(files["sessions.csv"])] == ["s1", "s3", "s2"]   # by first request


@case("views reads and writes nothing in the ledger directory and spends no network call without a store")
def _():
    sb = Sandbox("read-only")
    put_all(sb, [record(1, stamp(0))])
    exported = sb.ledger / "exported" / "claude"
    exported.mkdir(parents=True)
    (exported / "s9.jsonl").write_text(json.dumps(record(9, stamp(3), session="s9")) + "\n")
    before = snapshot(sb.ledger)
    files = sb.views()
    assert snapshot(sb.ledger) == before
    assert table(files["sessions.csv"])[0]["requests"] in ("1",) and len(table(files["sessions.csv"])) == 2


# ---------------------------------------------------------------- records (for a warehouse)

def records_cmd(sb: Sandbox, *args: str, period: tuple = PERIOD):
    code, out, err = sb.ledger_cmd("records", *period, *args)
    return code, [json.loads(line) for line in out.splitlines() if line], err


@case("records prints the period's requests as JSON lines: the allowlisted fields, the exact list-price cost, the price version, and null (never 0) for an unknown cost")
def _():
    sb = Sandbox("records-lines")
    put_all(sb, [record(1, stamp(0)), record(2, stamp(1), model="made-up-model"),
                 record(3, "2026-10-20T00:00:00.000Z")])                      # outside the period
    code, rows, err = records_cmd(sb)
    assert code == 0, err
    assert [r["id"] for r in rows] == ["claude:m1", "claude:m2"], rows
    assert list(rows[0]) == [*ledger_cost.FIELDS, "cost_usd", "price_version", "conflict"], list(rows[0])
    schema = json.loads((PLUGIN / "assets" / "bigquery" / "requests.schema.json").read_text())
    assert [column["name"] for column in schema] == list(rows[0]), "assets/bigquery/requests.schema.json is out of step"
    assert (rows[0]["cost_usd"], rows[0]["price_version"], rows[0]["conflict"]) == ("0.000100000", "2026-11-10", False), rows[0]
    assert (rows[1]["cost_usd"], rows[1]["price_version"]) == (None, None), rows[1]
    assert "records: 2 requests" in err and "unpriced=1" in err and "store=unset" in err, err


@case("records --out writes the same bytes every run and nothing in the ledger directory")
def _():
    sb = Sandbox("records-out")
    put_all(sb, [record(1, stamp(0)), record(2, stamp(2), session="s2"), record(3, stamp(1), runtime="opencode", session="o1")])
    before = snapshot(sb.ledger)
    target = sb.root / "out" / "records.jsonl"
    code, rows, err = records_cmd(sb, "--out", str(target))
    assert code == 0 and rows == [], (code, err)
    first = target.read_bytes()
    code, _, err = records_cmd(sb, "--out", str(target))
    assert code == 0 and target.read_bytes() == first, err
    assert [json.loads(line)["id"] for line in first.decode().splitlines()] == ["claude:m1", "opencode:m3", "claude:m2"]   # by time
    assert snapshot(sb.ledger) == before


@case("records flags the first copy of an id whose copies disagree, and keeps one row for it")
def _():
    sb = Sandbox("records-conflict")
    put_all(sb, [record(1, stamp(0))])
    exported = sb.ledger / "exported" / "claude"
    exported.mkdir(parents=True)
    (exported / "s1.jsonl").write_text(json.dumps(record(1, stamp(0), inp=2000)) + "\n")
    code, rows, err = records_cmd(sb)
    assert code == 0, err
    assert len(rows) == 1 and rows[0]["conflict"] is True and "conflicting=1" in err, (rows, err)


@case("records reads the store; a store that cannot be read is an error and writes nothing")
def _():
    sb = Sandbox("records-store")
    bare = sb.root / "store.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
    sb.config.write_text(f"ledger.store = {bare}\n")
    put_all(sb, [record(1, stamp(0))])
    code, out, err = sb.ledger_cmd("export")
    assert code == 0, err
    shutil.rmtree(sb.ledger, ignore_errors=True)                               # only the store holds the record now
    code, rows, err = records_cmd(sb)
    assert code == 0 and [r["id"] for r in rows] == ["claude:m1"] and "store=ok" in err, (code, rows, err)
    sb.config.write_text(f"ledger.store = {sb.root / 'missing.git'}\n")
    target = sb.root / "records.jsonl"
    code, rows, err = records_cmd(sb, "--out", str(target))
    assert code == 2 and rows == [] and not target.exists() and "nothing written" in err, (code, err)


shutil.rmtree(ROOT, ignore_errors=True)
print()
if FAILED:
    print(f"{len(FAILED)} case(s) NG")
    sys.exit(1)
print("all ok")
