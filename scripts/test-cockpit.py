#!/usr/bin/env python3
"""Exercise the cockpit commands against disposable Git repositories and replay fixtures."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "scripts/fixtures/cockpit"
KIND = "test-transcription"


class Fixture:
    def __init__(self, directory):
        self.directory = directory
        self.repo = directory / "repo"
        self.repo.mkdir()
        self.config = directory / "config"
        self.config.write_bytes((FIXTURES / "config").read_bytes())
        self.env = {**os.environ, "PLUMB_CONFIG": str(self.config), "PLUMB_ROOT": "",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "Fixture", "GIT_COMMITTER_NAME": "Fixture",
                    "GIT_AUTHOR_EMAIL": "fixture", "GIT_COMMITTER_EMAIL": "fixture"}
        self.git(self.repo, "init", "-q")
        self.file(self.repo, "checks/record.txt")
        self.git(self.repo, "add", "checks")
        self.git(self.repo, "commit", "-qm", "base")
        self.spec = directory / "brief.json"
        self.report_path = directory / "report.md"
        self.spec_data = json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8"))
        self.spec_data["report_path"] = str(self.report_path)
        self.write_spec()

    @property
    def cockpit(self):
        common = (self.repo / ".git").stat()
        artifacts = Path(self.env["PLUMB_ROOT"]) if self.env["PLUMB_ROOT"] else self.repo / ".plumb"
        return artifacts / "run/cockpit" / f"{common.st_dev:x}-{common.st_ino:x}"

    @staticmethod
    def file(directory, name):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")

    def write_spec(self):
        self.spec.write_text(json.dumps(self.spec_data), encoding="utf-8")

    def git(self, directory, *args):
        return subprocess.run(["git", *args], cwd=directory, env=self.env, check=True,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True).stdout.strip()

    def cmd(self, command, *args, code=0, cwd=None, as_json=True, plugin=ROOT, timeout=None):
        argv = [str(plugin / "bin" / f"plumb-{command}"), *map(str, args)]
        if as_json:
            argv.append("--json")
        result = subprocess.run(argv, cwd=cwd or self.repo, env=self.env, capture_output=True,
                                text=True, timeout=timeout)
        self.stderr = result.stderr
        assert result.returncode == code, (argv, result.returncode, result.stdout, result.stderr)
        if not as_json:
            return result.stdout
        output = json.loads(result.stdout)
        assert set(output) == {"schema", "outcome", "reason_codes", "data"} and output["schema"] == 1, output
        return output

    def lane(self, action, run, *args, lane="lane", code=0, as_json=True):
        options = [] if action in ("init", "status") else ["--lane", lane]
        return self.cmd("lane", action, "--run", run, *options, *args, code=code, as_json=as_json)

    def inject(self, code, *args):
        return subprocess.run([sys.executable, "-B", "-c", code, str(ROOT / "scripts"), *args],
                              cwd=self.repo, env=self.env, capture_output=True, text=True)

    def add(self, run, lane="lane", work="record", extra=()):
        brief = self.cmd("brief", "new", "--run", run, "--lane", lane, "--spec", self.spec)["data"]["path"]
        self.lane("add", run, "--work", work, "--spec", self.spec, *extra, lane=lane)
        return Path(brief)

    def setup(self, run):
        self.lane("init", run)
        self.add(run)

    def worktree(self, name="lane with space"):
        directory = self.directory / name
        self.git(self.repo, "worktree", "add", "-q", "--detach", str(directory))
        return directory

    def events(self, run):
        log = self.cockpit / run / "events.jsonl"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def evidence(self, run, lane):
        return next(event["data"] for event in reversed(self.events(run))
                    if event["lane"] == lane and event["type"] == "attempt-collected")

    def observe(self, run, ac, result, cause=None, event_id=None, lane="lane", code=0):
        collected = self.evidence(run, lane)
        args = ["--attempt", collected["attempt"], "--head", collected["head"], "--ac", ac, "--result", result]
        if cause is not None:
            args += ["--cause", cause]
        if event_id is not None:
            args += ["--event-id", event_id]
        return self.lane("observe", run, *args, lane=lane, code=code)

    def adjudicate(self, run, verdict, code=0, lane="lane"):
        collected = self.evidence(run, lane)
        return self.lane("adjudicate", run, "--attempt", collected["attempt"], "--head", collected["head"],
                         "--verdict", verdict, "--reason", "fixture result", code=code, lane=lane)

    def route(self, **kwargs):
        return self.cmd("route", "resolve", KIND, **kwargs)["data"]

    def attempt(self, run, verdict):
        self.lane("start", run)
        self.lane("collect", run)
        self.adjudicate(run, verdict)


def replay_fixtures(fixture):
    scenarios = json.loads((FIXTURES / "replays.json").read_text(encoding="utf-8"))
    lane_worktree = fixture.worktree()
    fixture.report_path.write_text("No files changed.\n", encoding="utf-8")
    for scenario in scenarios:
        run, reason = scenario["run"], scenario["reason"]
        fixture.setup(run)
        for attempt in scenario["attempts"]:
            fixture.lane("start", run, "--worktree", lane_worktree)
            for name in attempt.get("committed", []):
                fixture.file(lane_worktree, name)
                fixture.git(lane_worktree, "add", "--", name)
            if attempt.get("committed"):
                fixture.git(lane_worktree, "commit", "-qm", "fixture edit")
            for name in attempt.get("untracked", []):
                fixture.file(lane_worktree, name)
            collected = fixture.lane("collect", run, code=int(reason == "out-of-range"))
            if reason == "out-of-range":
                data = collected["data"]["event"]["data"]
                assert data["changed_paths"] == sorted(attempt["committed"] + attempt["untracked"]), data
                assert data["verdict"] == "miss", data
                assert fixture.adjudicate(run, "miss", code=2)["outcome"] == "invalid"
                verdicts = [e["data"].get("verdict") for e in fixture.events(run)]
                assert verdicts.count("miss") == 1, verdicts
            else:
                for observation in attempt["observations"]:
                    fixture.observe(run, *observation)
                fixture.adjudicate(run, attempt["verdict"])
        action = scenario["action"]
        result = fixture.lane(action, run, code=1)
        assert result["outcome"] == "hold" and result["reason_codes"] == [reason], result
        row = fixture.lane("status", run)["data"]["lanes"][0]
        if action == "guard":
            assert row["state"] == "held" and row["stop_code"] == reason, row
            refused = fixture.lane("start", run, code=1)
            assert refused["reason_codes"] == [reason], refused
            if reason == "out-of-range":
                fixture.lane("resume", run, "--diagnosis", "scope crossed",
                             "--hypothesis", "the shared edit can be reverted", "--test", "collect the corrected diff")
                fixture.observe(run, "automated", "pass")
                fixture.observe(run, "manual", "pass")
                assert fixture.lane("close", run, code=1)["reason_codes"] == ["out-of-range"]
        else:
            assert result["data"]["missing"] == scenario["missing"], result
            fixture.observe(run, "manual", "pass")
            fixture.lane("close", run)
            assert fixture.lane("status", run)["data"]["lanes"][0]["state"] == "closed"
        detail = " and one miss" if reason == "out-of-range" else ""
        print(f"  {run}: {action} exit 1, {reason}{detail}")


def routing(fixture):
    def expect(role, command, why):
        result = fixture.route()
        assert (result["role"], result["command"], result["why"]) == (role, command, why), result
        print(f"  resolve {KIND}: {role}, {command}, {why}")

    expect("draft", "worker-cli --tier x", "preferred")
    assert not fixture.cockpit.exists(), "resolve created state"
    for run, verdicts in (("first", ["miss", "hit", "miss"]), ("second", ["inconclusive", "miss"])):
        fixture.setup(run)
        for verdict in verdicts:
            fixture.attempt(run, verdict)
            if verdict == "inconclusive":
                expect("draft", "worker-cli --tier x", "preferred")
        if run == "first":
            expect("draft", "worker-cli --tier x", "preferred")
    expect("complex", "worker-cli --tier y", "demoted")
    linked = fixture.worktree()
    assert fixture.route(cwd=linked / "checks")["demoted"]
    assert fixture.cmd("route", "resolve", KIND, "--repo", linked)["data"]["demoted"]
    fixture.config.write_text(fixture.config.read_text().replace("after = 2", "after = 3"))
    assert fixture.route()["demoted"], "changing the threshold cleared a latched demotion"
    reset = fixture.cmd("lane", "route-reset", KIND, "--event-id", "clear-route")
    assert reset["outcome"] == "ok"
    print(f"  route-reset {KIND}: exit 0")
    expect("draft", "worker-cli --tier x", "preferred")
    fixture.attempt("second", "miss")
    repeated = fixture.cmd("lane", "route-reset", KIND, "--event-id", "clear-route")
    assert repeated == reset
    assert not fixture.route()["demoted"]
    unset = fixture.cmd("route", "resolve", "architecture")["data"]
    assert unset["why"] == "unset" and unset["command"] is None, unset
    assert "main session does it" in fixture.cmd("route", "resolve", "architecture", as_json=False)
    print("  C15 inconclusive preserves the preferred route; both role overrides select their commands")


def idempotency(fixture):
    run = "duplicate"
    fixture.setup(run)
    first = fixture.lane("start", run, "--event-id", "start-once")
    fixture.lane("collect", run)
    observed = fixture.observe(run, "automated", "pass", event_id="observe-once")
    files = [fixture.cockpit / run / name for name in ("events.jsonl", "lanes.tsv")]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
    assert first["outcome"] == "ok"
    assert fixture.lane("start", run, "--event-id", "start-once") == first
    assert first["data"]["data"]["command"] == "worker-cli --tier x"
    repeated = fixture.observe(run, "automated", "fail", "different-payload", event_id="observe-once")
    assert repeated == observed
    assert before == [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
    assert fixture.lane("status", run, as_json=False).encode() == files[1].read_bytes()
    print("  repeated start and observe: exit 0, original response, unchanged log and TSV")


def briefs_and_guards(fixture):
    run = "guard"
    fixture.lane("init", run)
    brief = fixture.add(run)
    contents = brief.read_text()
    fixture.cmd("brief", "new", "--run", run, "--lane", "lane", "--spec", fixture.spec)
    assert brief.read_text() == contents
    assert contents.splitlines()[0] == f"Read {ROOT}/skills/cockpit/references/worker.md before anything else."
    fixture.cmd("brief", "check", brief)
    brief.write_text(contents.replace("  Check: cat checks/record.txt", "")
                     .replace(str(fixture.report_path), "").replace("## Forbidden means", "## Unknown"))
    issues = fixture.cmd("brief", "check", brief, code=1)["data"]["issues"]
    assert {"acceptance item manual has no check command", "missing absolute report path",
            "missing section: Forbidden means"} <= set(issues), issues
    assert fixture.lane("start", run, code=1)["reason_codes"] == ["stale-brief"]
    brief.write_text(contents)
    fixture.lane("start", run)
    fixture.lane("collect", run)
    fixture.observe(run, "automated", "fail")
    assert fixture.lane("guard", run, code=1)["reason_codes"] == ["unclassified"]
    fixture.observe(run, "automated", "pass")
    assert fixture.lane("guard", run, code=1)["reason_codes"] == ["unclassified"]
    fixture.observe(run, "automated", "fail", "missing-label")
    assert fixture.lane("guard", run)["outcome"] == "allow"
    fixture.adjudicate(run, "inconclusive")
    fixture.attempt(run, "inconclusive")
    fixture.observe(run, "manual", "pass")
    for _ in range(2):
        fixture.attempt(run, "inconclusive")
    assert fixture.lane("guard", run)["outcome"] == "allow"
    fixture.attempt(run, "inconclusive")
    assert fixture.lane("guard", run, code=1)["reason_codes"] == ["no-progress"]
    assert fixture.lane("resume", run, code=1)["reason_codes"] == ["stale-brief"]
    context = ("--diagnosis", "no rendering check", "--hypothesis", "the label is lost", "--test", "render label alone")
    fixture.lane("resume", run, *context)
    fixture.lane("start", run)
    fixture.lane("collect", run)
    fixture.observe(run, "manual", "fail", "missing-label")
    fixture.adjudicate(run, "miss")
    assert fixture.lane("guard", run, code=1)["reason_codes"] == ["regression", "same-cause"]
    assert fixture.lane("resume", run, *context, code=1)["reason_codes"] == ["stale-brief"]
    print("  deterministic briefs, missing sections/check/report, unclassified, no-progress, stale-brief and resume")


def locks_and_base(fixture):
    fixture.spec_data["locks"] = ["shared-runner"]
    fixture.write_spec()
    fixture.setup("left")
    fixture.setup("right")
    worktree = fixture.worktree()
    started = fixture.lane("start", "left", "--worktree", worktree)["data"]
    lock = fixture.cockpit / "locks/shared-runner"
    assert lock.is_dir()
    assert fixture.lane("start", "right", code=1)["reason_codes"] == ["resource-busy"]
    # Move HEAD while preserving the original committed tree.
    fixture.git(worktree, "mv", "checks/record.txt", "former-name.txt")
    fixture.git(worktree, "commit", "-qm", "prepare a second base")
    fixture.git(worktree, "mv", "former-name.txt", "checks/record.txt")
    fixture.git(worktree, "commit", "-qm", "restore original content")
    fixture.file(worktree, "checks/new.txt")
    fixture.git(worktree, "add", "--", "checks/new.txt")
    collected = fixture.lane("collect", "left")["data"]["data"]
    assert collected["uncommitted"] and collected["changed_paths"] == ["checks/new.txt"], collected
    fixture.observe("left", "automated", "pass")
    fixture.observe("left", "manual", "pass")
    fixture.adjudicate("left", "hit")
    assert fixture.lane("close", "left", code=1)["reason_codes"] == ["uncommitted-edits"]
    fixture.git(worktree, "reset", "-q", "--", "checks/new.txt")
    (worktree / "checks/new.txt").unlink()
    assert not lock.exists()
    fixture.lane("start", "right")
    fixture.lane("collect", "right")
    fixture.adjudicate("right", "inconclusive")
    assert fixture.lane("start", "left", "--base", "HEAD", "--worktree", worktree, code=2)["outcome"] == "invalid"
    retry = fixture.lane("start", "left", "--worktree", worktree)["data"]
    assert retry["data"]["base"] == started["data"]["base"]
    for command in ("route", "brief", "lane"):
        assert fixture.cmd(command, "--help", as_json=False).startswith(f"usage: plumb-{command}")
    assert fixture.cmd("lane", "start", code=2)["outcome"] == "invalid"
    fixture.file(worktree, "checks/new.txt")
    fixture.git(worktree, "add", "--", "checks/new.txt")
    fixture.git(worktree, "commit", "-qm", "finish the staged edit")
    fixture.git(worktree, "mv", "checks/record.txt", "outside.txt")
    fixture.git(worktree, "commit", "-qm", "move outside the range")
    renamed = fixture.lane("collect", "left", code=1)["data"]["event"]["data"]
    assert renamed["changed_paths"] == ["checks/new.txt", "checks/record.txt", "outside.txt"], renamed
    print("  shared directory locks, pinned retry base, staged edits, renames, JSON errors and CLI help")


def stale_attempt(fixture):
    run = "evidence"
    fixture.setup(run)
    fixture.attempt(run, "inconclusive")
    old = fixture.evidence(run, "lane")
    fixture.lane("start", run)
    fixture.file(fixture.repo, "checks/new.txt")
    fixture.git(fixture.repo, "add", "checks")
    fixture.git(fixture.repo, "commit", "-qm", "new evidence")
    collected = fixture.lane("collect", run)["data"]["data"]
    assert collected["attempt"] == 2 and collected["head"] != old["head"], collected
    before = fixture.events(run)
    for action, args in (
        ("observe", ("--ac", "automated", "--result", "pass")),
        ("adjudicate", ("--verdict", "hit", "--reason", "fixture")),
    ):
        assert fixture.lane(action, run, *args, code=2)["outcome"] == "invalid"
        for attempt, head in ((old["attempt"], old["head"]), (old["attempt"], collected["head"]),
                              (collected["attempt"], old["head"])):
            stale = fixture.lane(action, run, *args, "--attempt", attempt, "--head", head, code=1)
            assert stale["reason_codes"] == ["stale-attempt"], stale
        fixture.git(fixture.repo, "checkout", "-q", "--detach", old["head"])
        stale = fixture.lane(action, run, *args, "--attempt", collected["attempt"], code=1)
        assert stale["reason_codes"] == ["stale-attempt"], stale
        fixture.git(fixture.repo, "checkout", "-q", "--detach", collected["head"])
    assert fixture.events(run) == before
    fixture.observe(run, "automated", "pass")
    fixture.observe(run, "manual", "pass")
    fixture.adjudicate(run, "hit")
    fixture.lane("close", run, "--head", collected["head"])
    print("  C01 stale evidence: earlier attempt, supplied head and checkout head all refused")


def divergent_base(fixture):
    run = "ancestry"
    fixture.setup(run)
    base = fixture.git(fixture.repo, "rev-parse", "HEAD")
    tree = fixture.worktree()
    fixture.file(tree, "preexisting-outside.txt")
    fixture.git(tree, "add", ".")
    fixture.git(tree, "commit", "-qm", "divergent lane")
    fixture.file(fixture.repo, "checks/base-change.txt")
    fixture.git(fixture.repo, "add", "checks")
    fixture.git(fixture.repo, "commit", "-qm", "pinned base")
    pinned = fixture.git(fixture.repo, "rev-parse", "HEAD")
    start = fixture.lane("start", run, "--worktree", tree, "--base", pinned, code=2)
    assert "not an ancestor" in start["data"]["message"], start
    assert len(fixture.events(run)) == 1
    fixture.git(tree, "checkout", "-q", "--detach", pinned)
    fixture.lane("start", run, "--worktree", tree)
    fixture.git(tree, "checkout", "-q", "--detach", "@{-1}")
    collect = fixture.lane("collect", run, code=2)
    assert "not an ancestor" in collect["data"]["message"], collect
    assert len(fixture.events(run)) == 2 and not fixture.route()["demoted"]
    assert fixture.git(tree, "merge-base", "HEAD", pinned) == base
    print("  C02 divergent base: start and collect exit 2 with no miss")


def observation_order(fixture):
    for run, order in (("forward", "abcd"), ("reverse", "bacd")):
        fixture.lane("init", run)
        for name in "abcd":
            fixture.add(run, lane=name)
            fixture.lane("start", run, "--worktree", fixture.worktree(f"{run}-{name}"), lane=name)
            fixture.lane("collect", run, lane=name)
        for name in order:
            fixture.observe(run, "automated", "pass", lane=name)
        for name in reversed(order):
            fixture.adjudicate(run, "hit", lane=name)
        result = fixture.lane("guard", run, lane=order[-1], code=1)
        assert result["reason_codes"] == ["no-progress"], (order, result)
    print("  C03 both cross-lane reporting orders hold when the earliest report leaves the window")


def recover_tail(fixture):
    run = "recover"
    fixture.setup(run)
    fixture.lane("start", run)
    log = fixture.cockpit / run / "events.jsonl"
    before = log.read_bytes()
    log.write_bytes(before + b'{"event_id":"collected","data":"\xf0\x9f')
    first = fixture.lane("collect", run, "--event-id", "collected")
    assert "recovered incomplete event" in fixture.stderr
    durable = log.read_bytes()
    assert durable.startswith(before) and len(fixture.events(run)) == 3
    log.write_bytes(durable + b'{"event_id":')
    assert fixture.lane("collect", run, "--event-id", "collected") == first
    assert "recovered incomplete event" in fixture.stderr and log.read_bytes() == durable
    incomplete = durable + b'{"event_id":"complete-json-without-newline"}'
    log.write_bytes(incomplete)
    fixture.route()
    assert not fixture.stderr and log.read_bytes() == incomplete
    assert fixture.lane("collect", run, "--event-id", "collected") == first
    assert "recovered incomplete event" in fixture.stderr and log.read_bytes() == durable
    for broken in (durable + b"broken\n", before + b"broken\n" + durable[len(before):] + b"tail"):
        log.write_bytes(broken)
        result = fixture.cmd("route", "resolve", KIND, code=2)
        assert "invalid event" in result["data"]["message"], result
        assert log.read_bytes() == broken
    print("  C04 partial append recovered on resend, newline-terminated corruption preserved")


def immutable_brief(fixture):
    run = "immutable"
    fixture.lane("init", run)
    original = fixture.add(run)
    snapshot = original.read_bytes(), original.stat().st_mtime_ns
    args = ("--run", run, "--lane", "lane", "--spec", fixture.spec)
    fixture.cmd("brief", "new", *args)
    assert snapshot == (original.read_bytes(), original.stat().st_mtime_ns)
    fixture.lane("start", run)
    fixture.spec_data["title"] = "Second title"
    fixture.write_spec()
    result = fixture.cmd("brief", "new", *args, code=2)
    assert "immutable" in result["data"]["message"], result
    revised = Path(fixture.cmd("brief", "new", *args, "--rev", "R2")["data"]["path"])
    assert revised != original and "Second title" in revised.read_text()
    assert snapshot == (original.read_bytes(), original.stat().st_mtime_ns)
    add = ("--work", "record", "--spec", fixture.spec, "--rev", "r2")
    fixture.lane("add", run, *add, code=2)
    fixture.lane("collect", run)
    fixture.observe(run, "automated", "pass")
    fixture.observe(run, "manual", "pass")
    fixture.adjudicate(run, "hit")
    fixture.lane("add", run, *add)
    assert fixture.lane("close", run, code=1)["reason_codes"] == ["stale-brief"]
    fixture.lane("add", run, *add, code=2)
    fixture.cmd("brief", "new", *args, code=2)
    fixture.lane("start", run)
    print("  C05 registered bytes and mtime preserved, revised brief requires a new add")


def repository_scope(fixture):
    location = str(fixture.directory / "shared-artifacts")
    fixture.env["PLUMB_ROOT"] = location
    other_directory = fixture.directory / "second"
    other_directory.mkdir()
    other = Fixture(other_directory)
    other.env["PLUMB_ROOT"] = location
    for item in (fixture, other):
        item.spec_data["locks"] = ["shared-runner"]
        item.write_spec()
        item.setup("same-run")
    fixture.attempt("same-run", "miss")
    fixture.attempt("same-run", "miss")
    fixture.lane("start", "same-run")
    linked = fixture.worktree()
    assert fixture.route(cwd=linked)["demoted"]
    state = fixture.cmd("lane", "status", "--run", "same-run", cwd=linked)
    assert state["data"]["lanes"][0]["attempt"] == 3, state
    fixture.setup("competing")
    busy = fixture.cmd("lane", "start", "--run", "competing", "--lane", "lane", cwd=linked, code=1)
    assert busy["reason_codes"] == ["resource-busy"], busy
    assert fixture.cockpit != other.cockpit and not other.route()["demoted"]
    other.lane("start", "same-run")
    assert (other.cockpit / "locks/shared-runner").is_dir()
    print("  C06 linked worktrees share state and resources, repositories with one artifact root are isolated")


def abandonment(fixture):
    fixture.spec_data["locks"] = ["shared-runner"]
    fixture.write_spec()
    fixture.setup("lost")
    fixture.setup("waiting")
    tree = fixture.worktree()
    fixture.lane("start", "lost", "--worktree", tree)
    fixture.git(fixture.repo, "worktree", "remove", str(tree))
    fixture.lane("collect", "lost", code=2)
    assert fixture.lane("start", "waiting", code=1)["reason_codes"] == ["resource-busy"]
    args = ("--attempt", 1, "--reason", "worktree disappeared")
    abandoned = fixture.lane("abandon", "lost", *args)["data"]["data"]
    assert abandoned["verdict"] == "inconclusive"
    assert not (fixture.cockpit / "locks/shared-runner").exists()
    fixture.lane("start", "waiting")
    fixture.lane("collect", "waiting")
    fixture.observe("waiting", "automated", "pass")
    fixture.observe("waiting", "manual", "pass")
    miss = fixture.lane("abandon", "waiting", "--miss", *args)["data"]["data"]
    assert miss["verdict"] == "miss"
    fixture.lane("close", "waiting", code=2)
    assert not fixture.route()["demoted"]
    unavailable = fixture.lane("start", "lost", code=2)
    assert "worktree is unavailable" in unavailable["data"]["message"], unavailable
    fixture.lane("start", "lost", "--worktree", fixture.repo, "--rebase-baseline")
    assert fixture.lane("abandon", "lost", *args, code=1)["reason_codes"] == ["stale-attempt"]
    fixture.lane("abandon", "lost", "--attempt", 2, "--reason", "retry unavailable", "--miss")
    assert fixture.route()["demoted"]
    print("  C07 vanished worktree abandoned, resources released, only explicit misses advance routing")


def canonical_names(fixture):
    fixture.spec_data["locks"] = ["Shared_Runner", "shared_runner"]
    fixture.write_spec()
    init = fixture.lane("init", "Build")
    brief = fixture.add("BUILD", lane="Compile")
    assert brief.name == "compile.md", brief
    assert fixture.lane("init", "build") == init and init["data"]["run"] == "build"
    rows = fixture.lane("status", "bUiLd")["data"]["lanes"]
    assert len(rows) == 1 and rows[0]["lane"] == "compile", rows
    assert fixture.events("build")[0]["data"]["locks"] == ["shared_runner"]
    fixture.lane("start", "Build", lane="Compile")
    assert (fixture.cockpit / "locks/shared_runner").is_dir()
    fixture.setup("competing")
    assert fixture.lane("start", "competing", code=1)["reason_codes"] == ["resource-busy"]
    for bad in ("../alias", "has.dot", "has space", "İ"):
        assert fixture.lane("init", bad, code=2)["outcome"] == "invalid"
        assert fixture.lane("start", "build", lane=bad, code=2)["outcome"] == "invalid"
        result = fixture.cmd("brief", "new", "--run", "build", "--lane", bad, "--spec", fixture.spec, code=2)
        assert result["outcome"] == "invalid"
        fixture.spec_data["locks"] = [bad]
        fixture.write_spec()
        result = fixture.cmd("brief", "new", "--run", "build", "--lane", "compile", "--spec", fixture.spec, code=2)
        assert "lock name" in result["data"]["message"], result
    error = fixture.inject("""
import sys
sys.path.insert(0, sys.argv.pop(1))
from cockpit import parser, run_cli
def handler(args):
    raise KeyError("injected")
sys.exit(run_cli(parser("boundary", "fixture"), handler))
""", "--json")
    assert error.returncode == 2 and not error.stderr, error
    assert json.loads(error.stdout) == {"schema": 1, "outcome": "invalid", "reason_codes": [],
                                       "data": {"message": "'injected'"}}, error
    print("  C08 aliases share canonical keys, invalid names and unexpected exceptions return the JSON envelope")


def snapshot_scope(fixture):
    run = "snapshot-scope"
    ignore = fixture.directory / "global-ignore"
    ignore.write_text("*.local\n")
    fixture.git(fixture.repo, "config", "core.excludesFile", str(ignore))
    (fixture.repo / ".gitignore").write_text("*.ignored\n__pycache__/\n")
    fixture.file(fixture.repo, "checks/skipped.txt")
    fixture.file(fixture.repo, "checks/tracked.ignored")
    artifact = ".plumb/run/cockpit/tracked-artifact"
    fixture.file(fixture.repo, artifact)
    fixture.git(fixture.repo, "add", "-f", ".gitignore", "checks/skipped.txt", "checks/tracked.ignored", artifact)
    fixture.git(fixture.repo, "commit", "-qm", "ignore a fixture pattern")
    worker = fixture.repo / "lane_check.py"
    worker.write_text("value = 1\n")
    fixture.git(fixture.repo, "add", worker.name)
    fixture.git(fixture.repo, "commit", "-qm", "add the lane check")

    def run_check():
        env = {key: value for key, value in fixture.env.items() if key != "PYTHONDONTWRITEBYTECODE"}
        subprocess.run([sys.executable, "-c", "import lane_check"], cwd=fixture.repo, env=env, check=True)
        return next((fixture.repo / "__pycache__").glob("*.pyc")).read_bytes()

    before = run_check()
    fixture.setup(run)
    started = fixture.lane("start", run)["data"]["data"]
    fixture.setup("later")
    for name in ("outside/new.ignored", "outside/new.local", ".plumb/run/cockpit/new-artifact"):
        fixture.file(fixture.repo, name)
    (fixture.repo / artifact).write_text("new artifact content\n")
    worker.write_text("value = 123\n")
    assert run_check() != before
    fixture.git(fixture.repo, "restore", "--", worker.name)
    data = fixture.lane("collect", run)["data"]["data"]
    assert data["changed_paths"] == [] and not data["uncommitted"], data
    assert data["collected_tree"] == started["baseline_tree"], data
    assert not fixture.git(fixture.repo, "ls-tree", data["collected_tree"], "--", ".plumb")
    fixture.adjudicate(run, "hit")
    fixture.lane("start", run)
    fixture.git(fixture.repo, "update-index", "--assume-unchanged", "checks/record.txt")
    fixture.git(fixture.repo, "update-index", "--skip-worktree", "checks/skipped.txt")
    for path in ("checks/record.txt", "checks/skipped.txt", "checks/new.txt", "checks/tracked.ignored"):
        (fixture.repo / path).write_text("new content\n")
    index = fixture.repo / ".git/index"
    before = index.read_bytes()
    data = fixture.lane("collect", run)["data"]["data"]
    assert data["changed_paths"] == ["checks/new.txt", "checks/record.txt", "checks/skipped.txt", "checks/tracked.ignored"], data
    assert data["uncommitted"] and index.read_bytes() == before, data
    print("  C09 ignored bytecode and cockpit artifacts stay out of scope, index flags cannot hide lane edits")


def repeat_collection(fixture):
    run = "lost-response"
    fixture.setup(run)
    fixture.lane("start", run)
    fixture.file(fixture.repo, "outside.txt")
    first = fixture.lane("collect", run, "--event-id", "scope", code=1)
    assert first["reason_codes"] == ["out-of-range"], first
    files = [fixture.cockpit / run / name for name in ("events.jsonl", "lanes.tsv")]
    snapshot = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
    assert fixture.lane("collect", run, "--event-id", "scope", code=1) == first
    assert snapshot == [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
    print("  C10 out-of-range retry returns the original exit 1 and reasons with unchanged log and TSV")


def repair_view(fixture):
    for run, repair in (("write-repair", "other-write"), ("brief-repair", "brief-write")):
        fixture.setup(run)
        table = fixture.cockpit / run / "lanes.tsv"
        before = table.read_bytes()
        crash = fixture.inject("""
import os
import runpy
import sys
from pathlib import Path
scripts = sys.argv.pop(1)
sys.path.insert(0, scripts)
import cockpit
append = cockpit.append
def stop_after_append(path, event):
    append(path, event)
    os._exit(73)
cockpit.append = stop_after_append
runpy.run_path(str(Path(scripts) / "plumb-lane.py"), run_name="__main__")
""", "start", "--run", run, "--lane", "lane")
        assert crash.returncode == 73 and not crash.stderr, crash
        assert table.read_bytes() == before and fixture.events(run)[-1]["type"] == "attempt-started"
        status = fixture.lane("status", run, as_json=False)
        assert "\trunning\t" in status and table.read_bytes() == before
        if repair == "other-write":
            fixture.cmd("lane", "route-reset", KIND)
        else:
            fixture.cmd("brief", "new", "--run", run, "--lane", "lane", "--spec", fixture.spec)
        assert b"\trunning\t" in table.read_bytes(), repair
        fixture.lane("abandon", run, "--attempt", 1, "--reason", "fixture finished")
    print("  C11 status reads past a stale TSV after fsync, cross-run writers repair it")


def refresh_brief(fixture):
    run = "plugin-move"
    old = fixture.directory / "former plugin"
    for directory in ("scripts", "bin", "skills/cockpit/references", ".claude-plugin"):
        shutil.copytree(ROOT / directory, old / directory)
    fixture.lane("init", run)
    options = ("--run", run, "--lane", "lane")
    original = Path(fixture.cmd("brief", "new", *options, "--spec", fixture.spec, plugin=old)["data"]["path"])
    fixture.cmd("lane", "add", *options, "--work", "record", "--spec", fixture.spec, plugin=old)
    contents = original.read_bytes()
    fixture.cmd("brief", "check", original)
    stripped = fixture.directory / "stripped.md"
    stripped.write_bytes(contents.partition(b"\n")[2])
    issue = "first line must refer to the cockpit worker.md in a recognized plumb installation"
    assert issue in fixture.cmd("brief", "check", stripped, code=1)["data"]["issues"]
    fake = fixture.directory / "wrong-opening.md"
    for root, relative, manifest in (
        (old, "unrelated/worker.md", None),
        (fixture.directory / "unmarked", "skills/cockpit/references/worker.md", None),
        (fixture.directory / "other", "skills/cockpit/references/worker.md", '{"name":"other"}'),
    ):
        fixture.file(root, relative)
        if manifest:
            fixture.file(root, ".claude-plugin/plugin.json")
            (root / ".claude-plugin/plugin.json").write_text(manifest)
        fake.write_bytes(f"Read {root / relative} before anything else.\n".encode() + contents.partition(b"\n")[2])
        assert issue in fixture.cmd("brief", "check", fake, code=1)["data"]["issues"]
    (old / "skills/cockpit/references/worker.md").unlink()
    assert issue in fixture.cmd("brief", "check", original, code=1)["data"]["issues"]
    assert fixture.lane("start", run, code=1)["reason_codes"] == ["invalid-brief"]
    refreshed = Path(fixture.cmd("brief", "refresh", *options, "--rev", "relocated")["data"]["path"])
    assert original.read_bytes() == contents
    assert contents.partition(b"\n")[2] == refreshed.read_bytes().partition(b"\n")[2]
    fixture.cmd("brief", "check", refreshed)
    fixture.lane("add", run, "--work", "record", "--spec", fixture.spec, "--rev", "relocated")
    fixture.lane("start", run)
    print("  C12 check and start enforce the worker's first line, refresh survives a moved plugin")


def malformed_numbers(fixture):
    run = "corrupt"
    fixture.setup(run)
    fixture.attempt(run, "miss")
    log = fixture.cockpit / run / "events.jsonl"
    original = log.read_bytes()
    for field, value in (("demote_after", "2"), ("demote_after", 0), ("attempt", True), ("attempt", -1), ("seq", 4.0)):
        events = fixture.events(run)
        event = events[-1]
        event["event_id"] = f"broken-{field}"
        target = event if field == "seq" else event["data"]
        target[field] = value
        log.write_text("".join(json.dumps(event) + "\n" for event in events))
        for command, arguments in (("route", ("resolve", KIND)), ("lane", ("status", "--run", run))):
            result = fixture.cmd(command, *arguments, code=2)
            assert f"broken-{field}" in result["data"]["message"] and field in result["data"]["message"], result
        log.write_bytes(original)
    print("  C13 invalid sequence, attempt and threshold fields exit 2 naming the event and field")


def collection_demotes(fixture):
    fixture.setup("explicit-miss")
    fixture.attempt("explicit-miss", "miss")
    assert fixture.route()["why"] == "preferred"
    run = "collection-miss"
    fixture.setup(run)
    fixture.lane("start", run)
    fixture.file(fixture.repo, "outside.txt")
    args = ("--event-id", "automatic-miss")
    first = fixture.lane("collect", run, *args, code=1)
    assert first["reason_codes"] == ["out-of-range"], first
    route = fixture.route()
    assert route["demoted"] and route["role"] == "complex", route
    before = fixture.events(run)
    assert sum(event["data"].get("verdict") == "miss" for event in before) == 1
    assert fixture.lane("collect", run, *args, code=1) == first
    assert fixture.events(run) == before and fixture.route() == route
    print("  C14 an explicit miss and a collection miss demote across runs, resend leaves the count unchanged")


def protected_ignored_files(fixture):
    run = "fingerprint"
    fixture.spec_data["do_not_touch"] = ["`checks/mode.ignored`", "deleted.ignored", "existing.ignored",
                                         "link.ignored", "type.ignored", "unchanged.ignored"]
    fixture.write_spec()
    fixture.setup(run)
    (fixture.repo / ".git/info/exclude").write_text("*.ignored\n")
    for name in ("checks/mode.ignored", "deleted.ignored", "existing.ignored", "existing.txt", "type.ignored",
                 "unchanged.ignored", "unlisted.ignored"):
        fixture.file(fixture.repo, name)
    link = fixture.repo / "link.ignored"
    link.symlink_to("old-target")
    fixture.lane("start", run)
    for name in ("existing.ignored", "existing.txt", "unlisted.ignored"):
        (fixture.repo / name).write_text("changed\n")
    (fixture.repo / "checks/mode.ignored").chmod(0o600)
    (fixture.repo / "deleted.ignored").unlink()
    (fixture.repo / "type.ignored").unlink()
    (fixture.repo / "type.ignored").symlink_to("fixture")
    link.unlink()
    link.symlink_to("new-target")
    result = fixture.lane("collect", run, code=1)
    data = result["data"]["event"]["data"]
    assert result["reason_codes"] == ["out-of-range"], result
    assert data["outside_paths"] == ["checks/mode.ignored", "deleted.ignored", "existing.ignored", "existing.txt",
                                     "link.ignored", "type.ignored"], data
    print("  C16 protected ignored files catch mode, content, deletion, symlink target and type changes")


def retry_snapshot(fixture):
    run = "retry-scope"
    fixture.setup(run)
    outside = fixture.repo / "outside.txt"
    fixture.lane("start", run)
    fixture.file(fixture.repo, outside.name)
    for number in (1, 2):
        result = fixture.lane("collect", run, code=1)
        data = result["data"]["event"]["data"]
        assert data["attempt"] == number and data["outside_paths"] == [outside.name], data
        fixture.lane("resume", run, "--diagnosis", f"scope crossing {number}",
                     "--hypothesis", f"revert outside edit {number}", "--test", f"check status {number}")
        if number == 2:
            outside.unlink()
        fixture.lane("start", run)
    data = fixture.lane("collect", run)["data"]["data"]
    assert data["attempt"] == 3 and not data["changed_paths"] and not data["uncommitted"], data
    print("  C17 a surviving outside path still misses on retry and removal clears it")


def commit_baseline_file(fixture):
    run = "commit-untracked"
    fixture.setup(run)
    path = "checks/initially-untracked.txt"
    fixture.file(fixture.repo, path)
    fixture.lane("start", run)
    fixture.git(fixture.repo, "add", "--", path)
    fixture.git(fixture.repo, "commit", "-qm", "commit an in-range file")
    data = fixture.lane("collect", run)["data"]["data"]
    assert data["changed_paths"] == [] and not data["uncommitted"], data
    fixture.observe(run, "automated", "pass")
    fixture.observe(run, "manual", "pass")
    fixture.adjudicate(run, "hit")
    fixture.lane("close", run)
    print("  C18 committing an unchanged baseline file clears uncommitted edits and permits close")


def classify_inactive(fixture):
    for run in ("abandoned", "revised"):
        fixture.setup(run)
        tree = fixture.worktree(run)
        fixture.lane("start", run, "--worktree", tree)
        fixture.lane("collect", run)
        fixture.observe(run, "automated", "fail")
        if run == "abandoned":
            fixture.lane("abandon", run, "--attempt", 1, "--reason", "checkout removed")
        else:
            fixture.adjudicate(run, "inconclusive")
            spec = fixture.spec.read_bytes()
            revised = json.loads(spec)
            revised["acceptance"] = [item for item in revised["acceptance"] if item["id"] == "manual"]
            fixture.spec.write_text(json.dumps(revised))
            options = ("--run", run, "--lane", "lane", "--spec", fixture.spec, "--rev", "new")
            fixture.cmd("brief", "new", *options)
            fixture.lane("add", run, "--work", "record", "--spec", fixture.spec, "--rev", "new")
            fixture.spec.write_bytes(spec)
        fixture.git(fixture.repo, "worktree", "remove", str(tree))
        assert fixture.lane("start", run, code=1)["reason_codes"] == ["unclassified"]
        before = fixture.events(run)
        assert fixture.observe(run, "automated", "pass", code=1)["reason_codes"] == ["stale-attempt"]
        assert fixture.observe(run, "manual", "fail", "other", code=1)["reason_codes"] == ["stale-attempt"]
        wrong = fixture.lane("observe", run, "--attempt", 2, "--ac", "automated", "--result", "fail",
                             "--cause", "missing-label", code=1)
        assert wrong["reason_codes"] == ["stale-attempt"] and fixture.events(run) == before, wrong
        fixture.observe(run, "automated", "fail", "missing-label")
        assert fixture.lane("guard", run)["outcome"] == "allow"
        fixture.lane("start", run, "--worktree", fixture.repo, "--rebase-baseline")
        fixture.lane("abandon", run, "--attempt", 2, "--reason", "fixture finished")
    print("  C19 the original failure can be classified after abandonment or brief replacement")


def reject_dirty_evidence(fixture):
    run = "dirty"
    fixture.setup(run)
    (fixture.repo / ".git/info/exclude").write_text("*.ignored\n")
    fixture.lane("start", run)
    collected = fixture.lane("collect", run)["data"]["data"]
    assert not collected["uncommitted"], collected
    tracked = fixture.repo / "checks/record.txt"
    original = tracked.read_bytes()
    before = fixture.events(run)

    def refuse():
        observe = fixture.observe(run, "automated", "pass", code=1)
        adjudicate = fixture.adjudicate(run, "hit", code=1)
        assert observe["reason_codes"] == adjudicate["reason_codes"] == ["dirty-checkout"], (observe, adjudicate)
        assert fixture.events(run) == before
        assert fixture.git(fixture.repo, "rev-parse", "HEAD") == collected["head"]

    tracked.write_text("different\n")
    refuse()
    fixture.git(fixture.repo, "add", "--", "checks/record.txt")
    refuse()
    tracked.write_bytes(original)
    fixture.git(fixture.repo, "reset", "-q", "--", "checks/record.txt")
    new = fixture.repo / "checks/new file.txt"
    fixture.file(fixture.repo, "checks/new file.txt")
    refuse()
    new.unlink()
    fixture.file(fixture.repo, "checks/new.ignored")
    fixture.observe(run, "automated", "pass")
    fixture.adjudicate(run, "hit")
    fixture.lane("start", run)
    fixture.file(fixture.repo, "checks/already-collected.txt")
    assert fixture.lane("collect", run)["data"]["data"]["uncommitted"]
    (fixture.repo / "checks/already-collected.txt").write_text("edited after collection\n")
    assert fixture.observe(run, "automated", "pass", code=1)["reason_codes"] == ["dirty-checkout"]
    assert fixture.adjudicate(run, "hit", code=1)["reason_codes"] == ["dirty-checkout"]
    fixture.file(fixture.repo, "checks/already-collected.txt")
    fixture.observe(run, "automated", "pass")
    fixture.adjudicate(run, "hit")
    print("  C20 both evidence commands verify collected tracked and untracked content at the same HEAD")


def reserve_worktree(fixture):
    fixture.spec_data.update(locks=[], allow_paths=["checks/"])
    fixture.write_spec()
    fixture.setup("writer")
    fixture.spec_data["allow_paths"] = ["other/"]
    fixture.write_spec()
    fixture.setup("competing")
    alias = fixture.directory / "checkout-alias"
    alias.symlink_to(fixture.repo, target_is_directory=True)
    fixture.lane("start", "writer")
    for state in ("running", "collected"):
        before = fixture.events("competing")
        busy = fixture.lane("start", "competing", "--worktree", alias / "checks", code=1)
        assert busy["reason_codes"] == ["worktree-busy"] and fixture.events("competing") == before, busy
        if state == "running":
            fixture.lane("collect", "writer")
    fixture.adjudicate("writer", "hit")
    fixture.lane("start", "competing", "--worktree", alias)
    fixture.lane("abandon", "competing", "--attempt", 1, "--reason", "fixture finished")
    fixture.spec_data.update(kind="review-preview", allow_paths=[])
    fixture.write_spec()
    for reader in ("reader-one", "reader-two"):
        fixture.setup(reader)
        fixture.lane("start", reader)
    busy = fixture.lane("start", "writer", code=1)
    assert busy["reason_codes"] == ["worktree-busy"], busy
    print("  C21 an active writer reserves the canonical checkout across runs with no resource lock")


def reserve_moved_worktree(fixture):
    fixture.setup("writer")
    fixture.setup("competing")
    worktree = fixture.worktree()
    fixture.lane("start", "writer", "--worktree", worktree)
    moved = fixture.directory / "moved worktree"
    fixture.git(fixture.repo, "worktree", "move", str(worktree), str(moved))
    # The former path can even acquire a different checkout.
    fixture.git(fixture.repo, "worktree", "add", "-q", "--detach", str(worktree))
    for state in ("running", "collected"):
        busy = fixture.lane("start", "competing", "--worktree", moved, code=1)
        assert busy["reason_codes"] == ["worktree-busy"], busy
        if state == "running":
            fixture.file(moved, "checks/moved.txt")
            data = fixture.lane("collect", "writer")["data"]["data"]
            assert data["changed_paths"] == ["checks/moved.txt"], data
    fixture.adjudicate("writer", "hit")
    fixture.lane("start", "competing", "--worktree", moved)
    print("  C29 moving the lane preserves its reservation and collection follows the moved checkout")


def retained_baseline(fixture):
    run = "retained-tree"
    ref = f"refs/plumb-cockpit/{run}/lane"
    fixture.setup(run)
    fixture.file(fixture.repo, "checks/baseline.txt")
    started = fixture.lane("start", run)["data"]["data"]
    refs = fixture.git(fixture.repo, "for-each-ref", "--format=%(objectname) %(objecttype)", ref)
    assert refs and refs == f"{started['baseline_tree']} tree", (refs, started)
    (fixture.repo / "checks/baseline.txt").unlink()
    fixture.git(fixture.repo, "prune", "--expire=now")
    data = fixture.lane("collect", run)["data"]["data"]
    assert data["changed_paths"] == ["checks/baseline.txt"] and not data["uncommitted"], data
    fixture.observe(run, "automated", "pass")
    fixture.observe(run, "manual", "pass")
    fixture.adjudicate(run, "hit")
    fixture.lane("close", run)
    assert not fixture.git(fixture.repo, "for-each-ref", ref)
    print("  C30 the first tree survives pruning while pinned and close removes its ref")


def missing_baseline(fixture):
    run = "missing-tree"
    ref = f"refs/plumb-cockpit/{run}/lane"
    fixture.setup(run)
    fixture.file(fixture.repo, "checks/baseline.txt")
    fixture.lane("start", run)
    fixture.git(fixture.repo, "update-ref", "-d", ref)
    fixture.git(fixture.repo, "prune", "--expire=now")
    before = fixture.events(run)
    result = fixture.lane("collect", run, code=1)
    assert result["reason_codes"] == ["missing-baseline"] and fixture.events(run) == before, result
    fixture.lane("abandon", run, "--attempt", 1, "--reason", "baseline disappeared")
    print("  C31 a pruned baseline refuses collection without recording a result")


def abandon_scope_hold(fixture):
    run = "held-attempt"
    ref = f"refs/plumb-cockpit/{run}/lane"
    fixture.setup(run)
    fixture.lane("start", run)
    fixture.file(fixture.repo, "outside.txt")
    assert fixture.lane("collect", run, code=1)["reason_codes"] == ["out-of-range"]
    assert fixture.lane("guard", run, code=1)["reason_codes"] == ["out-of-range"]
    args = ("--attempt", 1, "--reason", "scope review complete", "--miss", "--event-id", "abandon-held")
    result = fixture.lane("abandon", run, *args)
    assert result["data"]["type"] == "abandoned", result
    assert not fixture.git(fixture.repo, "for-each-ref", ref)
    assert fixture.lane("abandon", run, *args) == result
    assert not fixture.route()["demoted"]
    fixture.lane("resume", run, "--diagnosis", "scope crossing", "--hypothesis", "revert outside edit",
                 "--test", "check collected paths")
    retry = fixture.lane("start", run)["data"]["data"]
    assert retry["attempt"] == 2 and fixture.git(fixture.repo, "for-each-ref", ref), retry
    assert fixture.lane("collect", run, code=1)["reason_codes"] == ["out-of-range"]
    print("  C32 a collected scope hold can be abandoned without doubling the miss or replacing the baseline")


def snapshot_nested_head(fixture):
    run = "nested-head"
    nested = fixture.repo / "checks/nested"
    nested.mkdir()
    fixture.git(nested, "init", "-q")
    fixture.file(nested, "tracked.txt")
    fixture.git(nested, "add", ".")
    fixture.git(nested, "commit", "-qm", "nested baseline")
    (fixture.repo / ".git/info/exclude").write_text("*.ignored\n")
    fixture.file(nested, "cache.ignored")
    fixture.git(fixture.repo, "add", "--", "checks/nested")
    fixture.git(fixture.repo, "commit", "-qm", "record nested head")
    fixture.spec_data["do_not_touch"] = ["checks/nested/cache.ignored"]
    fixture.write_spec()
    fixture.setup(run)
    fixture.lane("start", run)
    (nested / "tracked.txt").write_text("local nested change\n")
    (nested / "cache.ignored").write_text("changed cache\n")
    data = fixture.lane("collect", run)["data"]["data"]
    assert not data["changed_paths"] and not data["uncommitted"], data
    fixture.adjudicate(run, "hit")
    fixture.lane("start", run)
    fixture.git(nested, "commit", "-qam", "advance nested head")
    data = fixture.lane("collect", run)["data"]["data"]
    assert data["changed_paths"] == ["checks/nested"] and data["uncommitted"], data
    print("  C33 a nested checkout is visible through its HEAD only")


def legacy_presence(fixture):
    run = "old-log"
    fixture.setup(run)
    old_path = "checks/known.txt"
    fixture.file(fixture.repo, old_path)
    fixture.lane("start", run)
    fixture.lane("collect", run)
    added, started, collected = fixture.events(run)
    assert not {"inventory", "untracked"} & (started["data"].keys() | collected["data"].keys())
    for field in ("baseline_tree", "git_dir", "protected_ignored"):
        del started["data"][field]
    del collected["data"]["collected_tree"]
    log = fixture.cockpit / run / "events.jsonl"
    for inventory in ([old_path], {old_path: {"sha256": "obsolete"}}):
        started["data"]["inventory"] = inventory
        log.write_text("".join(json.dumps(event) + "\n" for event in (added, started, collected)))
        (fixture.repo / old_path).write_text("changed legacy file\n")
        fixture.observe(run, "automated", "pass")
        fixture.file(fixture.repo, "checks/unknown.txt")
        assert fixture.observe(run, "manual", "pass", code=1)["reason_codes"] == ["dirty-checkout"]
        (fixture.repo / "checks/unknown.txt").unlink()
    fixture.lane("abandon", run, "--attempt", 1, "--reason", "legacy attempt replaced")
    retry = fixture.lane("start", run)["data"]["data"]
    assert retry["attempt"] == 2 and retry.get("baseline_tree"), retry
    assert fixture.lane("collect", run)["data"]["data"]["changed_paths"] == []
    print("  C34 old inventory shapes supply path presence only, new events omit them, and a retry records a tree")


def protected_collection_evidence(fixture):
    run = "protected-evidence"
    name = "checks/local.ignored"
    fixture.spec_data["do_not_touch"] = [name, "checks/absent.ignored"]
    fixture.write_spec()
    fixture.setup(run)
    (fixture.repo / ".git/info/exclude").write_text("*.ignored\n")
    fixture.file(fixture.repo, name)
    fixture.lane("start", run)
    data = fixture.lane("collect", run)["data"]["data"]
    before = fixture.events(run)
    path = fixture.repo / name
    path.write_text("changed\n")
    assert fixture.observe(run, "automated", "pass", code=1)["reason_codes"] == ["dirty-checkout"]
    path.unlink()
    assert fixture.adjudicate(run, "hit", code=1)["reason_codes"] == ["dirty-checkout"]
    fixture.file(fixture.repo, name)
    fixture.file(fixture.repo, "checks/absent.ignored")
    assert fixture.observe(run, "automated", "pass", code=1)["reason_codes"] == ["dirty-checkout"]
    assert fixture.adjudicate(run, "hit", code=1)["reason_codes"] == ["dirty-checkout"]
    assert fixture.events(run) == before
    assert data["collected_protected_ignored"]["checks/absent.ignored"] is None, data
    (fixture.repo / "checks/absent.ignored").unlink()
    fixture.observe(run, "automated", "pass")
    fixture.adjudicate(run, "hit")
    print("  C35 evidence rejects changes to protected ignored files and paths collected as absent")


def canonical_protected_paths(fixture):
    run = "protected-names"
    name = "checks/local.ignored"
    fixture.spec_data["do_not_touch"] = ["`./checks/./local.ignored`", "checks/./local.ignored"]
    fixture.write_spec()
    fixture.setup(run)
    (fixture.repo / ".git/info/exclude").write_text("*.ignored\n")
    fixture.file(fixture.repo, name)
    started = fixture.lane("start", run)["data"]["data"]
    assert list(started["protected_ignored"]) == [name], started
    (fixture.repo / name).write_text("changed\n")
    result = fixture.lane("collect", run, code=1)
    assert result["data"]["event"]["data"]["outside_paths"] == [name], result
    print("  C36 a dotted protected path is stored and reported under its canonical name")


def reject_unsafe_protected_paths(fixture):
    for run, unsafe in (("parent", "checks/../local.ignored"), ("absolute", str(fixture.repo / "local.ignored"))):
        fixture.spec_data["do_not_touch"] = [unsafe]
        fixture.write_spec()
        fixture.setup(run)
        before = fixture.events(run)
        result = fixture.lane("start", run, code=2)
        assert result["outcome"] == "invalid" and unsafe in result["data"]["message"], result
        assert fixture.events(run) == before
    print("  C37 start rejects parent traversals and absolute protected paths")


def protected_absence(fixture):
    run = "protected-absence"
    name = "checks/new.ignored"
    fixture.spec_data["do_not_touch"] = [name]
    fixture.write_spec()
    fixture.setup(run)
    (fixture.repo / ".git/info/exclude").write_text("*.ignored\n")
    started = fixture.lane("start", run)["data"]["data"]
    assert started["protected_ignored"] == {name: None}, started
    fixture.file(fixture.repo, name)
    result = fixture.lane("collect", run, code=1)
    data = result["data"]["event"]["data"]
    assert result["reason_codes"] == ["out-of-range"] and data["outside_paths"] == [name], result
    assert data["collected_protected_ignored"][name] is not None, data
    print("  C38 collection reports ignored files that appear at protected paths")


def protected_directory(fixture):
    run = "protected-directory"
    name = "checks/cache"
    fixture.spec_data["do_not_touch"] = [name + "/"]
    fixture.write_spec()
    fixture.setup(run)
    (fixture.repo / ".git/info/exclude").write_text("/checks/cache/\n")
    for entry in ("z", "nested/file", "a"):
        fixture.file(fixture.repo, f"{name}/{entry}")
    started = fixture.lane("start", run)["data"]["data"]
    fixture.lane("collect", run)
    (fixture.repo / name / "nested/file").write_text("changed\n")
    assert fixture.observe(run, "automated", "pass", code=1)["reason_codes"] == ["dirty-checkout"]
    fixture.file(fixture.repo, name + "/nested/file")
    fixture.adjudicate(run, "hit")
    fixture.lane("start", run)
    (fixture.repo / name / "nested/file").write_text("changed\n")
    result = fixture.lane("collect", run, code=1)
    data = result["data"]["event"]["data"]
    assert data["outside_paths"] == [name], result
    assert list(started["protected_ignored"][name]["entries"]) == ["a", "nested", "nested/file", "z"], started
    print("  C39 directory fingerprints catch nested edits during collection and evidence checks")


def cap_protected_directory(fixture):
    run = "protected-cap"
    name = "checks/cache"
    fixture.spec_data["do_not_touch"] = [name]
    fixture.write_spec()
    fixture.setup(run)
    (fixture.repo / ".git/info/exclude").write_text("/checks/cache/\n")
    directory = fixture.repo / name
    directory.mkdir()
    for number in range(10_000):
        (directory / str(number)).touch()
    extra = directory / "extra"
    extra.touch()
    before = fixture.events(run)
    result = fixture.lane("start", run, code=1)
    assert result["reason_codes"] == ["protected-too-large"] and fixture.events(run) == before, result
    extra.unlink()
    fixture.lane("start", run)
    fixture.lane("collect", run)
    extra.touch()
    assert fixture.adjudicate(run, "hit", code=1)["reason_codes"] == ["dirty-checkout"]
    extra.unlink()
    fixture.adjudicate(run, "hit")
    extra.touch()
    assert fixture.lane("start", run, code=1)["reason_codes"] == ["protected-too-large"]
    extra.unlink()
    fixture.lane("start", run)
    extra.touch()
    result = fixture.lane("collect", run, code=1)
    assert result["data"]["event"]["data"]["outside_paths"] == [name], result
    print("  C40 the protected directory limit accepts 10,000 entries and detects overflow")


def retry_moved_checkout(fixture):
    run = "retry-move"
    fixture.setup(run)
    worktree = fixture.worktree()
    fixture.file(worktree, "notes.txt")
    started = fixture.lane("start", run, "--worktree", worktree)["data"]["data"]
    fixture.lane("collect", run)
    fixture.adjudicate(run, "hit")
    moved = fixture.directory / "moved checkout"
    fixture.git(fixture.repo, "worktree", "move", str(worktree), str(moved))
    retry = fixture.lane("start", run)["data"]["data"]
    assert retry["worktree"] == str(moved) and retry["git_dir"] == started["git_dir"], retry
    data = fixture.lane("collect", run)["data"]["data"]
    assert data["changed_paths"] == [], data
    print("  C41 a retry defaults to the recorded checkout even after it moves")


def retry_other_checkout(fixture):
    run = "retry-other"
    name = "checks/local.ignored"
    fixture.spec_data["do_not_touch"] = [name]
    fixture.write_spec()
    fixture.setup(run)
    (fixture.repo / ".git/info/exclude").write_text("*.ignored\n")
    worktree = fixture.worktree()
    fixture.file(worktree, "notes.txt")
    fixture.lane("start", run, "--worktree", worktree)
    fixture.lane("collect", run)
    fixture.adjudicate(run, "hit")
    ref = f"refs/plumb-cockpit/{run}/lane"
    baseline = fixture.git(fixture.repo, "rev-parse", ref)
    before = fixture.events(run)
    result = fixture.lane("start", run, "--worktree", fixture.repo, code=1)
    assert result["reason_codes"] == ["other-checkout"] and fixture.events(run) == before, result
    assert fixture.git(fixture.repo, "rev-parse", ref) == baseline
    fixture.file(fixture.repo, name)
    retry = fixture.lane("start", run, "--worktree", fixture.repo, "--rebase-baseline")["data"]["data"]
    assert fixture.git(fixture.repo, "rev-parse", ref) == retry.get("baseline_tree") != baseline, retry
    data = fixture.lane("collect", run)["data"]["data"]
    assert data["changed_paths"] == [], data
    fixture.adjudicate(run, "hit")
    before = fixture.events(run)
    same = fixture.lane("start", run, "--rebase-baseline", code=1)
    assert same["reason_codes"] == ["same-checkout"] and fixture.events(run) == before, same
    fixture.lane("start", run)
    (fixture.repo / name).write_text("changed\n")
    result = fixture.lane("collect", run, code=1)
    assert result["data"]["event"]["data"]["outside_paths"] == [name], result
    print("  C42 replacing the checkout requires permission and sets the baseline for later retries")


def reject_sparse_checkout(fixture):
    run = "sparse"
    fixture.setup(run)
    fixture.git(fixture.repo, "config", "core.sparseCheckout", "true")
    before = fixture.events(run)
    result = fixture.lane("start", run, code=1)
    assert result["reason_codes"] == ["sparse-checkout"] and fixture.events(run) == before, result
    print("  C43 start refuses core.sparseCheckout")


def reject_sparse_index(fixture):
    run = "sparse-index"
    fixture.setup(run)
    fixture.file(fixture.repo, "other/file.txt")
    fixture.git(fixture.repo, "add", "other")
    fixture.git(fixture.repo, "commit", "-qm", "add another directory")
    fixture.git(fixture.repo, "sparse-checkout", "set", "--cone", "--sparse-index", "checks")
    index = fixture.git(fixture.repo, "ls-files", "--sparse", "--stage")
    assert "\n040000 " in index, index
    fixture.git(fixture.repo, "config", "--worktree", "core.sparseCheckout", "false")
    fixture.git(fixture.repo, "config", "--worktree", "index.sparse", "false")
    before = fixture.events(run)
    result = fixture.lane("start", run, code=1)
    assert result["reason_codes"] == ["sparse-checkout"] and fixture.events(run) == before, result
    print("  C44 start refuses a sparse index even with core.sparseCheckout disabled")


def legacy_collected_names(fixture):
    run = "old-collection"
    name = "checks/known.txt"
    fixture.setup(run)
    (fixture.repo / ".git/info/exclude").write_text("*.ignored\n")
    fixture.file(fixture.repo, name)
    fixture.lane("start", run)
    fixture.lane("collect", run)
    added, started, collected = fixture.events(run)
    del collected["data"]["collected_tree"]
    collected["data"]["untracked"] = [name, "checks/old-cache.ignored"]
    log = fixture.cockpit / run / "events.jsonl"
    log.write_text("".join(json.dumps(event) + "\n" for event in (added, started, collected)))
    (fixture.repo / name).unlink()
    assert fixture.observe(run, "automated", "pass", code=1)["reason_codes"] == ["dirty-checkout"]
    assert fixture.adjudicate(run, "hit", code=1)["reason_codes"] == ["dirty-checkout"]
    fixture.file(fixture.repo, name)
    fixture.file(fixture.repo, "checks/new.txt")
    assert fixture.observe(run, "automated", "pass", code=1)["reason_codes"] == ["dirty-checkout"]
    (fixture.repo / "checks/new.txt").unlink()
    fixture.file(fixture.repo, "checks/new-cache.ignored")
    fixture.observe(run, "automated", "pass")
    fixture.adjudicate(run, "hit")
    print("  C45 legacy collected names reject additions and removals of non-ignored paths")


def read_only_history(fixture):
    run = "read-only"
    assert fixture.route()["why"] == "preferred"
    assert fixture.lane("status", run)["data"]["lanes"] == []
    assert not fixture.cockpit.parent.exists()
    fixture.setup(run)
    fixture.attempt(run, "miss")
    fixture.attempt(run, "miss")
    directory = fixture.cockpit / run
    log = directory / "events.jsonl"
    log.write_bytes(log.read_bytes() + b'{"event_id":"unfinished","utf8":"\xf0\x9f')
    table = directory / "lanes.tsv"
    table.unlink()
    lock = fixture.cockpit / ".writer-lock"

    def read():
        assert fixture.route(timeout=5)["demoted"] and not fixture.stderr
        status = fixture.cmd("lane", "status", "--run", run, timeout=5)
        assert status["data"]["lanes"][0]["state"] == "reviewed" and not fixture.stderr, status

    with lock.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            read()
        except subprocess.TimeoutExpired as exc:
            raise AssertionError("a reader waited for the writer lock") from exc
    lock.unlink()
    snapshot = log.read_bytes(), log.stat().st_mtime_ns
    readonly = (log, directory, fixture.cockpit)
    for path in readonly:
        path.chmod(0o555 if path.is_dir() else 0o444)
    try:
        read()
        assert snapshot == (log.read_bytes(), log.stat().st_mtime_ns)
        assert not lock.exists() and not table.exists()
    finally:
        for path in reversed(readonly):
            path.chmod(0o755 if path.is_dir() else 0o644)
    print("  C22 readers use the complete prefix with a held or missing lock and leave read-only state untouched")


def refuse_closed_start(fixture):
    run = "closed"
    fixture.setup(run)
    fixture.lane("start", run)
    fixture.lane("collect", run)
    fixture.observe(run, "automated", "pass")
    fixture.observe(run, "manual", "pass")
    fixture.adjudicate(run, "hit")
    fixture.lane("close", run)
    before = fixture.events(run)
    guarded = fixture.lane("guard", run, code=1)
    started = fixture.lane("start", run, code=1)
    assert started == guarded and started["reason_codes"] == ["closed"], (started, guarded)
    assert fixture.events(run) == before
    print("  C23 guard and start both refuse a closed lane with exit 1 and closed")


def reject_reused_resume(fixture):
    run = "resume-context"
    fixture.setup(run)
    fixture.lane("init", run)
    fixture.add(run, lane="other")
    contexts = [("--diagnosis", f"scope crossing {n}", "--hypothesis", f"revert outside edit {n}",
                 "--test", f"check status {n}") for n in ("a", "b")]
    outside = fixture.repo / "outside.txt"
    for i, lane in enumerate(("lane", "other", "other")):
        fixture.lane("start", run, lane=lane)
        fixture.file(fixture.repo, outside.name)
        fixture.lane("collect", run, lane=lane, code=1)
        outside.unlink()
        before = fixture.events(run)
        resumed = fixture.lane("resume", run, *contexts[i % 2], lane=lane, code=int(i == 2))
        if i == 2:
            assert resumed["reason_codes"] == ["stale-brief"] and fixture.events(run) == before, resumed
    print("  C24 a work ID rejects a reused resume context across lanes after a different context")


def validate_replay(fixture):
    run = "corrupt"
    fixture.setup(run)
    fixture.setup("healthy")
    fixture.attempt(run, "hit")
    before = fixture.events(run)
    log = fixture.cockpit / run / "events.jsonl"
    route_log = fixture.cockpit / "route-events.jsonl"
    fixture.cmd("lane", "route-reset", KIND)
    reset = json.loads(route_log.read_bytes())

    def verify(event_id):
        for command, action in (("route", ("resolve", KIND)), ("lane", ("status", "--run", "healthy"))):
            invalid = fixture.cmd(command, *action, code=2)
            assert event_id in invalid["data"]["message"], invalid

    for field, value in (("verdict", "typo"), ("attempt", 2)):
        events = fixture.events(run)
        events[-1]["event_id"] = f"bad-{field}"
        events[-1]["data"][field] = value
        log.write_text("".join(json.dumps(event) + "\n" for event in events))
        verify(f"bad-{field}")
        log.write_text("".join(json.dumps(event) + "\n" for event in before))
    abandoned = {**before[-2], "event_id": "abandoned-first", "type": "abandoned",
                 "data": {"attempt": 1, "verdict": "inconclusive"}}
    collected = {**before[-2], "seq": abandoned["seq"] + 1, "event_id": "collected-after-abandon"}
    log.write_text("".join(json.dumps(event) + "\n" for event in [*before[:2], abandoned, collected]))
    verify("collected-after-abandon")
    log.write_text("".join(json.dumps(event) + "\n" for event in before))
    reset["event_id"] = "bad-reset"
    reset["data"]["kind"] = []
    route_log.write_text(json.dumps(reset) + "\n")
    verify("bad-reset")
    print("  C25 route and status both name invalid verdict, attempt, transition and reset events")


def default_bulk_route(fixture):
    fixture.config.write_text("role.bulk = worker-cli --tier w\nrole.implementer = worker-cli --tier z\n")
    result = fixture.route()
    assert (result["role"], result["command"], result["why"]) == ("bulk", "worker-cli --tier w", "preferred"), result
    assert not fixture.cockpit.exists()
    print("  C26 fresh routing selects the configured bulk command without route overrides")


def configured_demotion(fixture):
    fixture.config.write_text(fixture.config.read_text().replace("after = 2", "after = 3"))
    run = "three-misses"
    fixture.setup(run)
    for _ in range(2):
        fixture.attempt(run, "miss")
    result = fixture.route()
    assert result["why"] == "preferred" and not result["demoted"], result
    fixture.attempt(run, "miss")
    result = fixture.route()
    assert result["why"] == "demoted" and result["demoted"], result
    print("  C27 a fresh threshold of three holds through two misses and demotes on the third")


def unsupported_python(fixture):
    run = "runtime"
    fixture.lane("init", run)
    brief = fixture.add(run)
    shim = fixture.directory / "shim"
    shim.mkdir()
    executable = shim / "python3"
    interpreter = shlex.quote(sys.executable)
    executable.write_text(f"""#!/bin/sh
if [ "$1" = -B ] && [ "$2" = -c ]; then
  exec {interpreter} -B -c 'import sys; sys.version_info = (3, int(sys.argv[1])); exec(sys.argv[2])' "$FIXTURE_PYTHON_MINOR" "$3"
fi
exec {interpreter} "$@"
""")
    executable.chmod(0o755)
    fixture.env["PATH"] = f"{shim}{os.pathsep}{fixture.env['PATH']}"
    for command, action in (("route", ("resolve", KIND)), ("lane", ("status", "--run", run)),
                            ("brief", ("check", brief))):
        fixture.env["FIXTURE_PYTHON_MINOR"] = "8"
        result = fixture.cmd(command, *action, code=3)
        assert result["outcome"] == "unavailable" and "Python 3.9" in result["data"]["message"], result
        fixture.env["FIXTURE_PYTHON_MINOR"] = "9"
        assert fixture.cmd(command, *action)["outcome"] == "ok"
    print("  C28 all three launchers return unavailable for Python 3.8 and accept Python 3.9")


CASES = {"replay": replay_fixtures, "routing": routing, "idempotency": idempotency,
         "guards": briefs_and_guards, "locks": locks_and_base, "c01-stale": stale_attempt,
         "c02-base": divergent_base, "c03-order": observation_order, "c04-tail": recover_tail,
         "c05-brief": immutable_brief, "c06-repo": repository_scope, "c07-abandon": abandonment,
         "c08-names": canonical_names, "c09-snapshot-scope": snapshot_scope, "c10-resend": repeat_collection,
         "c11-view": repair_view, "c12-refresh": refresh_brief, "c13-numbers": malformed_numbers,
         "c14-collection-demotes": collection_demotes, "c16-fingerprints": protected_ignored_files,
         "c17-retry-snapshot": retry_snapshot, "c18-commit-baseline-file": commit_baseline_file,
         "c19-inactive-failure": classify_inactive, "c20-dirty-evidence": reject_dirty_evidence,
         "c21-worktree-busy": reserve_worktree, "c22-read-only": read_only_history,
         "c23-closed-start": refuse_closed_start, "c24-resume-context": reject_reused_resume,
         "c25-invalid-replay": validate_replay, "c26-default-bulk": default_bulk_route,
         "c27-configured-threshold": configured_demotion, "c28-python-version": unsupported_python,
         "c29-moved-worktree": reserve_moved_worktree, "c30-retained-baseline": retained_baseline,
         "c31-missing-baseline": missing_baseline, "c32-abandon-scope-hold": abandon_scope_hold,
         "c33-nested-head": snapshot_nested_head, "c34-legacy-presence": legacy_presence,
         "c35-protected-evidence": protected_collection_evidence, "c36-protected-names": canonical_protected_paths,
         "c37-unsafe-protected-paths": reject_unsafe_protected_paths, "c38-protected-absence": protected_absence,
         "c39-protected-directory": protected_directory, "c40-protected-cap": cap_protected_directory,
         "c41-retry-moved": retry_moved_checkout, "c42-retry-other": retry_other_checkout,
         "c43-sparse-config": reject_sparse_checkout, "c44-sparse-index": reject_sparse_index,
         "c45-legacy-collected": legacy_collected_names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, action="append", help="run only the named case (repeatable)")
    args = parser.parse_args()
    for case in args.case or CASES:
        with TemporaryDirectory(prefix="plumb-cockpit-") as directory:
            CASES[case](Fixture(Path(directory).resolve()))


if __name__ == "__main__":
    main()
