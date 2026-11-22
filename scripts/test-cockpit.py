#!/usr/bin/env python3
"""Exercise the cockpit commands against disposable Git repositories and replay fixtures."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
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
        self.cockpit = self.repo / ".plumb/run/cockpit"
        self.spec = directory / "brief.json"
        self.report_path = directory / "report.md"
        self.spec_data = json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8"))
        self.spec_data["report_path"] = str(self.report_path)
        self.write_spec()

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

    def cmd(self, command, *args, code=0, cwd=None, as_json=True):
        argv = [str(ROOT / "bin" / f"plumb-{command}"), *map(str, args)]
        if as_json:
            argv.append("--json")
        result = subprocess.run(argv, cwd=cwd or self.repo, env=self.env, capture_output=True, text=True)
        assert result.returncode == code, (argv, result.returncode, result.stdout, result.stderr)
        if not as_json:
            return result.stdout
        output = json.loads(result.stdout)
        assert set(output) == {"schema", "outcome", "reason_codes", "data"} and output["schema"] == 1, output
        return output

    def lane(self, action, run, *args, lane="lane", code=0, as_json=True):
        options = [] if action in ("init", "status") else ["--lane", lane]
        return self.cmd("lane", action, "--run", run, *options, *args, code=code, as_json=as_json)

    def add(self, run, lane="lane", work="record", extra=()):
        brief = self.cmd("brief", "new", "--run", run, "--lane", lane, "--spec", self.spec)["data"]["path"]
        self.lane("add", run, "--work", work, "--spec", self.spec, *extra, lane=lane)
        return Path(brief)

    def setup(self, run):
        self.lane("init", run)
        self.add(run)

    def worktree(self):
        directory = self.directory / "lane with space"
        self.git(self.repo, "worktree", "add", "-q", "--detach", str(directory))
        return directory

    def events(self, run):
        log = self.cockpit / run / "events.jsonl"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def observe(self, run, ac, result, cause=None, event_id=None):
        args = ["--ac", ac, "--result", result]
        if cause is not None:
            args += ["--cause", cause]
        if event_id is not None:
            args += ["--event-id", event_id]
        return self.lane("observe", run, *args)

    def adjudicate(self, run, verdict, code=0):
        return self.lane("adjudicate", run, "--verdict", verdict, "--reason", "fixture result", code=code)

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

    expect("bulk", "worker-cli --tier x", "preferred")
    assert not fixture.cockpit.exists(), "resolve created state"
    for run, verdicts in (("first", ["miss", "hit", "miss"]), ("second", ["inconclusive", "miss"])):
        fixture.setup(run)
        for verdict in verdicts:
            fixture.attempt(run, verdict)
        if run == "first":
            expect("bulk", "worker-cli --tier x", "preferred")
    expect("implementer", "worker-cli --tier y", "demoted")
    linked = fixture.worktree()
    assert fixture.route(cwd=linked / "checks")["demoted"]
    assert fixture.cmd("route", "resolve", KIND, "--repo", linked)["data"]["demoted"]
    fixture.config.write_text(fixture.config.read_text().replace("after = 2", "after = 3"))
    assert fixture.route()["demoted"], "changing the threshold cleared a latched demotion"
    reset = fixture.cmd("lane", "route-reset", KIND, "--event-id", "clear-route")
    assert reset["outcome"] == "ok"
    print(f"  route-reset {KIND}: exit 0")
    expect("bulk", "worker-cli --tier x", "preferred")
    fixture.attempt("second", "miss")
    repeated = fixture.cmd("lane", "route-reset", KIND, "--event-id", "clear-route")
    assert repeated["outcome"] == "duplicate"
    assert not fixture.route()["demoted"]
    unset = fixture.cmd("route", "resolve", "architecture")["data"]
    assert unset["why"] == "unset" and unset["command"] is None, unset
    assert "main session does it" in fixture.cmd("route", "resolve", "architecture", as_json=False)


def idempotency(fixture):
    run = "duplicate"
    fixture.setup(run)
    first = fixture.lane("start", run, "--event-id", "start-once")
    fixture.lane("collect", run)
    fixture.observe(run, "automated", "pass", event_id="observe-once")
    files = [fixture.cockpit / run / name for name in ("events.jsonl", "lanes.tsv")]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
    assert first["outcome"] == "ok"
    assert fixture.lane("start", run, "--event-id", "start-once")["outcome"] == "duplicate"
    repeated = fixture.observe(run, "automated", "fail", "different-payload", event_id="observe-once")
    assert repeated["outcome"] == "duplicate"
    assert before == [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
    assert fixture.lane("status", run, as_json=False).encode() == files[1].read_bytes()
    print("  repeated start and observe: exit 0, duplicate, events.jsonl and lanes.tsv byte-identical")


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


CASES = {"replay": replay_fixtures, "routing": routing, "idempotency": idempotency,
         "guards": briefs_and_guards, "locks": locks_and_base}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, action="append", help="run only the named case (repeatable)")
    args = parser.parse_args()
    for case in args.case or CASES:
        with TemporaryDirectory(prefix="plumb-cockpit-") as directory:
            CASES[case](Fixture(Path(directory).resolve()))


if __name__ == "__main__":
    main()
