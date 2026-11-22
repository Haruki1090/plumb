#!/usr/bin/env python3
"""Exercise the cockpit commands against disposable Git repositories and replay fixtures."""

from __future__ import annotations

import argparse
import json
import os
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

    def cmd(self, command, *args, code=0, cwd=None, as_json=True, plugin=ROOT):
        argv = [str(plugin / "bin" / f"plumb-{command}"), *map(str, args)]
        if as_json:
            argv.append("--json")
        result = subprocess.run(argv, cwd=cwd or self.repo, env=self.env, capture_output=True, text=True)
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

    def observe(self, run, ac, result, cause=None, event_id=None, lane="lane"):
        collected = self.evidence(run, lane)
        args = ["--attempt", collected["attempt"], "--head", collected["head"], "--ac", ac, "--result", result]
        if cause is not None:
            args += ["--cause", cause]
        if event_id is not None:
            args += ["--event-id", event_id]
        return self.lane("observe", run, *args, lane=lane)

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
            fixture.lane("start", run, lane=name)
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
    log.write_bytes(durable + b'{"event_id":"complete-json-without-newline"}')
    fixture.route()
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
    fixture.lane("start", "lost")
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


def ignored_inventory(fixture):
    run = "inventory"
    ignore = fixture.directory / "global-ignore"
    ignore.write_text("*.local\n")
    fixture.git(fixture.repo, "config", "core.excludesFile", str(ignore))
    (fixture.repo / ".gitignore").write_text("*.ignored\n")
    fixture.git(fixture.repo, "add", ".gitignore")
    fixture.git(fixture.repo, "commit", "-qm", "ignore a fixture pattern")
    for name in ("existing.ignored", "existing.local", "existing.txt"):
        fixture.file(fixture.repo, name)
    fixture.setup(run)
    started = fixture.lane("start", run)["data"]["data"]
    assert started["inventory"] == ["existing.ignored", "existing.local", "existing.txt"], started
    fixture.setup("later")
    for name in ("outside/new.ignored", "outside/new.local"):
        fixture.file(fixture.repo, name)
        fixture.git(fixture.repo, "check-ignore", "--", name)
    result = fixture.lane("collect", run, code=1)
    assert result["reason_codes"] == ["out-of-range"], result
    data = result["data"]["event"]["data"]
    assert data["uncommitted"] and data["changed_paths"] == ["outside/new.ignored", "outside/new.local"], data
    assert data["verdict"] == "miss"
    print("  C09 repository and global ignores included, pre-existing files and cockpit artifacts excluded")


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
    for run, repair in (("status-repair", "status"), ("write-repair", "other-write"), ("brief-repair", "brief-write")):
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
        if repair == "status":
            status = fixture.lane("status", run, as_json=False)
            assert table.read_text() == status
        elif repair == "other-write":
            fixture.cmd("lane", "route-reset", KIND)
        else:
            fixture.cmd("brief", "new", "--run", run, "--lane", "lane", "--spec", fixture.spec)
        assert b"\trunning\t" in table.read_bytes(), repair
    print("  C11 process interrupted after fsync, status and cross-run writes repair the TSV")


def refresh_brief(fixture):
    run = "plugin-move"
    old = fixture.directory / "former plugin"
    for directory in ("scripts", "bin", "skills/cockpit/references"):
        shutil.copytree(ROOT / directory, old / directory)
    fixture.lane("init", run)
    options = ("--run", run, "--lane", "lane")
    original = Path(fixture.cmd("brief", "new", *options, "--spec", fixture.spec, plugin=old)["data"]["path"])
    fixture.cmd("lane", "add", *options, "--work", "record", "--spec", fixture.spec, plugin=old)
    contents = original.read_bytes()
    fixture.cmd("brief", "check", original)
    stripped = fixture.directory / "stripped.md"
    stripped.write_bytes(contents.partition(b"\n")[2])
    issue = "first line must refer to an existing absolute worker.md path"
    assert issue in fixture.cmd("brief", "check", stripped, code=1)["data"]["issues"]
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


CASES = {"replay": replay_fixtures, "routing": routing, "idempotency": idempotency,
         "guards": briefs_and_guards, "locks": locks_and_base, "c01-stale": stale_attempt,
         "c02-base": divergent_base, "c03-order": observation_order, "c04-tail": recover_tail,
         "c05-brief": immutable_brief, "c06-repo": repository_scope, "c07-abandon": abandonment,
         "c08-names": canonical_names, "c09-inventory": ignored_inventory, "c10-resend": repeat_collection,
         "c11-view": repair_view, "c12-refresh": refresh_brief, "c13-numbers": malformed_numbers,
         "c14-collection-demotes": collection_demotes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, action="append", help="run only the named case (repeatable)")
    args = parser.parse_args()
    for case in args.case or CASES:
        with TemporaryDirectory(prefix="plumb-cockpit-") as directory:
            CASES[case](Fixture(Path(directory).resolve()))


if __name__ == "__main__":
    main()
