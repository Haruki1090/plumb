#!/usr/bin/env python3
"""Regression suite for `plumb-run-view`, on synthetic ledgers and synthetic forge answers only.

    python3 -B scripts/test-run-view.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline under tempfile.mkdtemp():
ledgers are written here, the forge is a function here (or a missing program), and every item, lane, branch
and URL is made up. No real ledger or pull request is read.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
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
import run_view  # noqa: E402

BIN = PLUGIN / "bin" / "plumb-run-view"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-run-view-test-"))
FAILED: list[str] = []
NOW = datetime(2026, 1, 10, 3, 0, 0, tzinfo=timezone.utc)
HEAD = "ts\titem\tstate\tlane\tevidence\tnext\tref"
OLD_HEAD = "ts\titem\tstate\tlane\tevidence\tnext"
URL = "https://example.invalid/pull/"
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

def at(minutes: int) -> str:
    """The ledger timestamp `minutes` after 2026-01-10T00:00:00Z."""
    return f"2026-01-10T{minutes // 60:02d}:{minutes % 60:02d}:00Z"


def write_ledger(rows: list[tuple], name: str | None = None, header: str = HEAD, directory: Path | None = None) -> Path:
    """rows: (minute, item, state, lane, evidence, next[, ref]); short tuples are padded with '-'."""
    _counter[0] += 1
    directory = directory or ROOT / f"d{_counter[0]}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name or f"lead-issues-20260110-000000-{_counter[0]}.tsv")
    lines = [header]
    for row in rows:
        cells = [at(row[0]), *row[1:]]
        want = len(header.split("\t"))
        cells += ["-"] * (want - len(cells))
        lines.append("\t".join(cells[:want]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def ledger(rows: list[tuple], **kwargs):
    parsed = run_view.parse_ledger(write_ledger(rows, **kwargs))
    assert parsed is not None, "the fixture ledger must parse"
    return parsed


def raw_pr(number: int, head: str = "", state: str = "OPEN", draft: bool = False, created: str = at(60),
           merged: str | None = None, checks: list | None = None) -> dict:
    return {"number": number, "url": f"{URL}{number}", "state": state, "isDraft": draft, "headRefName": head or f"branch-{number}",
            "createdAt": created, "mergedAt": merged, "statusCheckRollup": checks or []}


def facts(*raws: dict) -> dict:
    out = {}
    for raw in raws:
        fact = run_view.normalize_pr(raw)
        out[fact["number"]] = fact
    return out


def view(rows: list[tuple], prs: dict | None = None, **kwargs) -> dict:
    """The first run of the view for one ledger."""
    doc = run_view.build([ledger(rows, **kwargs)], prs, NOW)
    return doc["runs"][0]


def lane_of(run: dict, item: str) -> dict:
    return next(l for l in run["lanes"] if l["item"] == item)


def check(conclusion: str = "", status: str = "COMPLETED", typename: str = "CheckRun", state: str = "") -> dict:
    out = {"__typename": typename, "status": status, "conclusion": conclusion}
    if typename == "StatusContext":
        out = {"__typename": typename, "state": state}
    return out


def pr_with_checks(*checks: dict) -> str:
    return run_view.classify_checks(list(checks))


# ---------------------------------------------------------------- link rules

@case("rule 1: pr: ref links by number, the latest ref wins, - and empty are skipped")
def _():
    run = view([(0, "#101", "ready", "lane-101", "e", "n", "-"),
                (10, "#101", "ready-pr", "lane-101", "e", "n", "pr:140"),
                (20, "#101", "ready-pr", "lane-101", "e", "n", "-")],
               facts(raw_pr(140), raw_pr(101, head="other")))
    pr = lane_of(run, "#101")["pr"]
    assert pr["number"] == 140 and pr["url"] == URL + "140", pr
    run = view([(0, "#101", "ready", "lane-101", "e", "n", "pr:140"), (5, "#101", "ready-pr", "lane-101", "e", "n", "pr:141")],
               facts(raw_pr(140), raw_pr(141)))
    assert lane_of(run, "#101")["pr"]["number"] == 141


@case("rule 1: branch: ref links to the newest pull request with exactly that head")
def _():
    prs = facts(raw_pr(150, head="fix-101", created=at(30)), raw_pr(152, head="fix-101", created=at(90)),
                raw_pr(151, head="fix-101-more", created=at(120)), raw_pr(153, head="Fix-101", created=at(150)))
    run = view([(0, "#101", "ready", "lane-101", "e", "n", "branch:fix-101")], prs)
    assert lane_of(run, "#101")["pr"]["number"] == 152
    run = view([(0, "#101", "ready", "lane-101", "e", "n", "branch:fix-none")], prs)
    assert lane_of(run, "#101")["pr"] is None


@case("rule 1 beats rule 2: a ref that resolves to nothing is not replaced by the item number")
def _():
    prs = facts(raw_pr(101, head="x"))
    run = view([(0, "#101", "ready", "lane-101", "e", "n", "branch:fix-none")], prs)
    assert lane_of(run, "#101")["pr"] is None
    run = view([(0, "#101", "ready", "lane-101", "e", "n", "branch:fix-none")], facts(raw_pr(101, head="fix-none")))
    assert lane_of(run, "#101")["pr"]["number"] == 101


@case("rule 2: #N and #N@sha as the whole item link to that pull request when N is one")
def _():
    prs = facts(raw_pr(201), raw_pr(202))
    run = view([(0, "#201", "ready", "lane-201"), (1, "#202@abc1234", "ready", "lane-202")], prs)
    assert lane_of(run, "#201")["pr"]["number"] == 201
    assert lane_of(run, "#202@abc1234")["pr"]["number"] == 202


@case("rule 2: #N that is not a pull request (an issue) has pr null")
def _():
    run = view([(0, "#301", "ready", "lane-301")], facts(raw_pr(201)))
    assert lane_of(run, "#301")["pr"] is None and run["lanes"][0]["done"] is False


@case("a number inside prose is never linked (item text, evidence, next)")
def _():
    prs = facts(raw_pr(1957), raw_pr(1958), raw_pr(1959))
    run = view([(0, "abc #1957 note", "ready", "lane-a", "see PR #1958 and 1958", "after #1959 lands"),
                (5, "#1957x", "ready", "lane-b", "evidence pr:1957", "next pr:1958"),
                (10, "task #1957", "ready", "lane-c", "https://example.invalid/pull/1957", "-")], prs)
    assert [l["pr"] for l in run["lanes"]] == [None, None, None], run["lanes"]
    assert [e["source"] for e in run["events"]] == ["ledger"] * 3


@case("an unreadable latest ref is not a link and no older ref is guessed; rule 2 may still apply")
def _():
    prs = facts(raw_pr(140), raw_pr(401))
    run = view([(0, "#401", "ready", "lane-401", "e", "n", "pr:140"), (5, "#401", "ready", "lane-401", "e", "n", "see-140")], prs)
    assert lane_of(run, "#401")["pr"]["number"] == 401
    run = view([(0, "#402", "ready", "lane-402", "e", "n", "pr:140"), (5, "#402", "ready", "lane-402", "e", "n", "see-140")], prs)
    assert lane_of(run, "#402")["pr"] is None


@case("collect_links names the numbers and branches to ask the forge for, and only those")
def _():
    parsed = ledger([(0, "#1", "ready", "l1", "e", "n", "pr:11"), (1, "#2", "ready", "l2", "e", "n", "branch:b2"),
                     (2, "#3", "ready", "l3"), (3, "abc #4", "ready", "l4", "pr 99 #98", "n #97")])
    numbers, branches = run_view.collect_links([parsed])
    assert numbers == {11, 3} and branches == {"b2"}, (numbers, branches)


# ---------------------------------------------------------------- fields

@case("checks: fail, pending, pass, skipped-only, none")
def _():
    ok, bad, wait = check("SUCCESS"), check("FAILURE"), check("", status="IN_PROGRESS")
    assert pr_with_checks(ok, bad, wait) == "fail"
    for conclusion in ("ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"):
        assert pr_with_checks(check(conclusion)) == "fail", conclusion
    assert pr_with_checks(ok, wait) == "pending"
    for status in ("QUEUED", "IN_PROGRESS", "WAITING", "PENDING"):
        assert pr_with_checks(check("", status=status)) == "pending", status
    assert pr_with_checks(check("")) == "pending", "completed with no conclusion is pending"
    assert pr_with_checks(check(typename="StatusContext", state="PENDING")) == "pending"
    assert pr_with_checks(check(typename="StatusContext", state="EXPECTED")) == "pending"
    assert pr_with_checks(check(typename="StatusContext", state="FAILURE")) == "fail"
    assert pr_with_checks(ok, check("SKIPPED"), check("NEUTRAL")) == "pass"
    assert pr_with_checks(check(typename="StatusContext", state="SUCCESS")) == "pass"
    assert pr_with_checks(check("SKIPPED"), check("NEUTRAL")) == "skipped"
    assert pr_with_checks() == "none" and run_view.classify_checks(None) == "none"


@case("checks are a fact beside the pull request, never a gate: merged with a failure is still merged and done")
def _():
    prs = facts(raw_pr(140, state="MERGED", merged=at(100), checks=[check("FAILURE")]),
                raw_pr(141, draft=True))
    run = view([(0, "#140", "ready-pr", "lane-140"), (1, "#141", "ready-pr", "lane-141")], prs)
    merged, draft = lane_of(run, "#140"), lane_of(run, "#141")
    assert merged["pr"]["state"] == "merged" and merged["pr"]["checks"] == "fail" and merged["done"] is True
    assert draft["pr"]["draft"] is True and draft["pr"]["checks"] == "none" and draft["pr"]["state"] == "open"
    assert draft["done"] is False


@case("pr state: open, merged, closed; merged_at null when absent or the forge's zero time")
def _():
    prs = facts(raw_pr(1), raw_pr(2, state="MERGED", merged=at(100)), raw_pr(3, state="CLOSED"),
                {**raw_pr(4), "mergedAt": "0001-01-01T00:00:00Z"})
    assert [prs[n]["state"] for n in (1, 2, 3, 4)] == ["open", "merged", "closed", "open"]
    assert prs[2]["merged_at"] == "2026-01-10T01:40:00Z" and prs[1]["merged_at"] is None and prs[4]["merged_at"] is None


@case("done: the pull request being merged or closed wins over any ledger word")
def _():
    prs = facts(raw_pr(140, state="MERGED", merged=at(100)), raw_pr(141, state="CLOSED"))
    run = view([(0, "#140", "needs-ruling", "lane-140"), (1, "#141", "blocked", "lane-141"),
                (2, "#142", "ready", "lane-142")], prs)
    assert lane_of(run, "#140")["done"] and lane_of(run, "#141")["done"] and not lane_of(run, "#142")["done"]
    assert lane_of(run, "#140")["needs_owner"] is False, "a merged pull request needs nobody"
    assert [u["item"] for u in run["upcoming"]] == ["#142"]


@case("done: the latest state exactly landed or merged is done; other words are not")
def _():
    run = view([(0, "#1", "landed"), (1, "#2", "merged"), (2, "#3", "landed-ish"), (3, "#4", "ready"),
                (4, "#4", "landed"), (5, "#5", "landed"), (6, "#5", "ready")])
    assert [u["item"] for u in run["upcoming"]] == ["#3", "#5"], run["upcoming"]


@case("needs_owner: exactly needs-ruling or owner-task, and not when done")
def _():
    run = view([(0, "#1", "needs-ruling"), (1, "#2", "owner-task"), (2, "#3", "needs-shape"), (3, "#4", "blocked"),
                (4, "#5", "needs-ruling"), (5, "#5", "landed"), (6, "#6", "needs-ruling-x")])
    got = {u["item"]: u["needs_owner"] for u in run["upcoming"]}
    assert got == {"#1": True, "#2": True, "#3": False, "#4": False, "#6": False}, got


@case("lanes: only items that ever had a lane; the latest lane that is not empty or -; first appearance order")
def _():
    run = view([(0, "#1", "ready", "-"), (1, "#2", "ready", "lane-2"), (2, "#3", "ready", ""),
                (3, "#1", "ready", "lane-1"), (4, "#2", "ready-pr", "-"), (5, "#2", "ready-pr", "lane-2b")])
    assert [(l["item"], l["lane"]) for l in run["lanes"]] == [("#1", "lane-1"), ("#2", "lane-2b")], run["lanes"]
    assert {u["item"]: u["lane"] for u in run["upcoming"]} == {"#1": "lane-1", "#2": "lane-2b", "#3": None}


@case("lane since: the ts of the row where the current state began (walk back while unchanged)")
def _():
    run = view([(0, "#1", "ready", "lane-1"), (10, "#1", "in-progress", "lane-1"), (20, "#1", "in-progress", "lane-1"),
                (30, "#1", "in-progress", "-"), (40, "#2", "ready", "lane-2"), (50, "#2", "in-progress", "lane-2"),
                (60, "#2", "ready", "lane-2")])
    assert lane_of(run, "#1")["since"] == at(10), lane_of(run, "#1")
    assert lane_of(run, "#2")["since"] == at(60), "a state that came back starts again"


@case("late: first row more than 10 minutes after the run began")
def _():
    run = view([(0, "#1", "ready"), (10, "#2", "ready"), (11, "#3", "ready"), (50, "#1", "ready-pr")])
    assert {u["item"]: u["late"] for u in run["upcoming"]} == {"#1": False, "#2": False, "#3": True}


@case("next: trimmed to 120 characters, - and empty are null, taken from the latest row")
def _():
    run = view([(0, "#1", "ready", "-", "e", "x" * 130), (1, "#2", "ready", "-", "e", "-"), (2, "#3", "ready", "-", "e", ""),
                (3, "#4", "ready", "-", "e", "old"), (4, "#4", "ready", "-", "e", "  newest  ")])
    got = {u["item"]: u["next"] for u in run["upcoming"]}
    assert got == {"#1": "x" * 120, "#2": None, "#3": None, "#4": "newest"}, got


@case("evidence never appears anywhere in the output")
def _():
    secret = "SECRET-EVIDENCE-TEXT"
    prs = facts(raw_pr(140, state="MERGED", merged=at(100)))
    doc = run_view.build([ledger([(0, "#140", "ready-pr", "lane-140", secret, "next", "-"),
                                  (5, "#1", "ready", "-", secret + " 2", "n")])], prs, NOW)
    assert secret not in json.dumps(doc) and "evidence" not in json.dumps(doc)


@case("kind is the word between lead- and the next -; name and ledger are the file's")
def _():
    run = view([(0, "#1", "ready")], name="lead-prs-20260110-090000-123.tsv")
    assert run["kind"] == "prs" and run["name"] == "lead-prs-20260110-090000-123" and run["ledger"].endswith("lead-prs-20260110-090000-123.tsv")
    assert view([(0, "#1", "ready")], name="lead-20260110.tsv")["kind"] == "20260110"


# ---------------------------------------------------------------- events

@case("events: ledger rows and remote events, sorted by time, ties keep ledger order, remote after ledger")
def _():
    prs = facts(raw_pr(140, created=at(10), state="MERGED", merged=at(60)))
    run = view([(0, "#140", "ready", "lane-140"), (10, "#140", "ready-pr", "lane-140"), (10, "#9", "ready", "-"),
                (5, "#9", "needs-ruling", "-"), (60, "#140", "landed", "lane-140")], prs)
    got = [(e["at"], e["item"], e["what"], e["source"]) for e in run["events"]]
    assert got == [(at(0), "#140", "ready", "ledger"), (at(5), "#9", "needs-ruling", "ledger"),
                   (at(10), "#140", "ready-pr", "ledger"), (at(10), "#9", "ready", "ledger"),
                   (at(10), "#140", "pr-opened", "remote"), (at(60), "#140", "landed", "ledger"),
                   (at(60), "#140", "pr-merged", "remote")], got
    assert run["events"][0]["lane"] == "lane-140" and run["events"][1]["lane"] is None


@case("events: a remote event outside the run's window is still listed; unparsable ts rows are dropped")
def _():
    prs = facts(raw_pr(140, created="2025-12-01T00:00:00Z"))
    path = write_ledger([(30, "#140", "ready", "lane-140")])
    path.write_text(path.read_text() + "not-a-time\t#7\tready\t-\te\tn\t-\n\t#8\tready\t-\te\tn\t-\n"
                    "2026-01-10T00:40:00Z\t\tready\t-\te\tn\t-\n", encoding="utf-8")
    doc = run_view.build([run_view.parse_ledger(path)], prs, NOW)
    run = doc["runs"][0]
    assert [(e["at"], e["what"]) for e in run["events"]] == [("2025-12-01T00:00:00Z", "pr-opened"), (at(30), "ready")]
    assert [u["item"] for u in run["upcoming"]] == ["#140"] and run["last_at"] == at(30)


@case("started_at and last_at are the first and last row ts")
def _():
    run = view([(5, "#1", "ready"), (50, "#2", "ready"), (20, "#1", "ready-pr")])
    assert run["started_at"] == at(5) and run["last_at"] == at(20), run


# ---------------------------------------------------------------- parsing and files

@case("a header that is not the lead ledger's is skipped; the old header (no ref) and the new one both read")
def _():
    odd = write_ledger([(0, "#1", "ready")], header="ts\titem\tstate\tlane\tevidence")
    other = write_ledger([(0, "#1", "ready")], header="ts\tid\thypothesis\tchange\tbefore\tafter\tx")
    extra = write_ledger([(0, "#1", "ready")], header=HEAD + "\tmore")
    for path in (odd, other, extra):
        assert run_view.parse_ledger(path) is None, path
    old = run_view.parse_ledger(write_ledger([(0, "#1", "ready", "lane-1", "e", "n")], header=OLD_HEAD))
    assert old and old["rows"][0]["ref"] == "" and old["rows"][0]["lane"] == "lane-1"
    new = run_view.parse_ledger(write_ledger([(0, "#1", "ready", "lane-1", "e", "n", "pr:5")]))
    assert new and new["rows"][0]["ref"] == "pr:5"
    assert run_view.parse_ledger(ROOT / "missing.tsv") is None


@case("tab-split with no quoting, short rows padded, blank lines ignored")
def _():
    path = ROOT / "quoting.tsv"
    path.write_text(HEAD + '\n2026-01-10T00:00:00Z\t#1\tready\tlane-1\t"quoted\tevidence"\tnext\n\n'
                    "2026-01-10T00:05:00Z\t#2\tready\n", encoding="utf-8")
    parsed = run_view.parse_ledger(path)
    assert [r["item"] for r in parsed["rows"]] == ["#1", "#2"]
    assert parsed["rows"][0]["next"] == 'evidence"' and parsed["rows"][0]["lane"] == "lane-1", parsed["rows"][0]
    assert parsed["rows"][1]["lane"] == "" and parsed["rows"][1]["ref"] == ""


@case("two ledgers are ordered by last row, newest first")
def _():
    one = ledger([(0, "#1", "ready"), (30, "#1", "ready-pr")], name="lead-issues-a.tsv")
    two = ledger([(10, "#2", "ready"), (90, "#2", "ready-pr")], name="lead-prs-b.tsv")
    three = ledger([(0, "#3", "ready"), (30, "#3", "ready-pr")], name="lead-issues-0.tsv")
    doc = run_view.build([one, two, three], None, NOW)
    assert [r["name"] for r in doc["runs"]] == ["lead-prs-b", "lead-issues-0", "lead-issues-a"], [r["name"] for r in doc["runs"]]


@case("determinism: the same inputs twice give the same document except generated_at")
def _():
    prs = facts(raw_pr(140, checks=[check("SUCCESS")]), raw_pr(141, state="MERGED", merged=at(70)))
    rows = [(0, "#140", "ready", "lane-140"), (5, "#141", "ready", "lane-141", "e", "n", "pr:141"), (9, "#7", "needs-ruling")]
    parsed = ledger(rows, name="lead-issues-x.tsv")
    first = run_view.build([parsed], prs, NOW)
    second = run_view.build([parsed], prs, datetime(2026, 1, 10, 4, tzinfo=timezone.utc))
    assert first["generated_at"] != second["generated_at"]
    first.pop("generated_at"), second.pop("generated_at")
    assert json.dumps(first) == json.dumps(second)


@case("build with prs None: every pr is null and remote is skipped; an explicit remote is kept")
def _():
    rows = [(0, "#140", "ready", "lane-140", "e", "n", "pr:140")]
    doc = run_view.build([ledger(rows)], None, NOW, "/r")
    assert doc["remote"] == "skipped" and doc["runs"][0]["lanes"][0]["pr"] is None and doc["repo"] == "/r"
    assert run_view.build([ledger(rows)], None, NOW, "/r", "unavailable")["remote"] == "unavailable"
    assert run_view.build([ledger(rows)], {}, NOW)["remote"] == "ok"
    assert run_view.build([], {}, NOW) == {"runs": []}


# ---------------------------------------------------------------- the forge

class FakeGh:
    """A forge in a function: pr list (all, or --head <b>) and pr view <n>."""

    def __init__(self, prs: list[dict], list_fails: bool = False, view_fails: bool = False):
        self.prs, self.list_fails, self.view_fails, self.calls = prs, list_fails, view_fails, []

    def __call__(self, args, cwd, timeout):
        self.calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            if self.list_fails:
                return subprocess.CompletedProcess(args, 1, "", "boom")
            rows = self.prs[:2] if "--head" not in args else [p for p in self.prs if p["headRefName"] == args[args.index("--head") + 1]]
            assert "statusCheckRollup" not in args[args.index("--json") + 1], "the list must not carry the check rollup"
            rows = [{k: v for k, v in p.items() if k != "statusCheckRollup"} for p in rows]
            return subprocess.CompletedProcess(args, 0, json.dumps(rows), "")
        number = int(args[2])
        hit = next((p for p in self.prs if p["number"] == number), None)
        if hit is None or self.view_fails:
            return subprocess.CompletedProcess(args, 1, "", "Could not resolve to a PullRequest")
        return subprocess.CompletedProcess(args, 0, json.dumps(hit), "")


@case("fetch: nothing linked makes no forge call at all and remote is ok")
def _():
    gh = FakeGh([])
    assert run_view.fetch_prs("/r", set(), set(), gh=gh) == ("ok", {}) and gh.calls == []


@case("fetch: one list call without checks, a head query only for unseen branches, one read with checks per linked pull request")
def _():
    prs = [raw_pr(1, head="b1"), raw_pr(2, head="b2"), raw_pr(3, head="b3", checks=[check("FAILURE")]),
           raw_pr(4, head="b4", checks=[check("SUCCESS")])]
    gh = FakeGh(prs)
    remote, got = run_view.fetch_prs("/r", {1, 3, 99}, {"b2", "b4", "nope"}, gh=gh)
    kinds = sorted((c[1], c[2] if c[1] == "view" else c[c.index("--head") + 1] if "--head" in c else "all") for c in gh.calls)
    assert remote == "ok" and sorted(got) == [1, 2, 3, 4], (remote, sorted(got))
    assert kinds == sorted([("list", "all"), ("list", "b4"), ("list", "nope")] + [("view", n) for n in ("1", "2", "3", "4", "99")]), kinds
    assert got[3]["checks"] == "fail" and got[4]["checks"] == "pass" and got[1]["checks"] == "none"
    assert all("statusCheckRollup" in c[c.index("--json") + 1] for c in gh.calls if c[1] == "view")


@case("fetch: a number the forge has no pull request for is a miss, not an unavailable forge")
def _():
    remote, got = run_view.fetch_prs("/r", {5}, set(), gh=FakeGh([raw_pr(1)]))
    assert remote == "ok" and 5 not in got and 1 in got
    run = view([(0, "#5", "ready", "lane-5")], got)
    assert lane_of(run, "#5")["pr"] is None


@case("fetch: the list call failing, a missing gh and a timeout are unavailable")
def _():
    assert run_view.fetch_prs("/r", {1}, set(), gh=FakeGh([], list_fails=True)) == ("unavailable", None)

    def missing(args, cwd, timeout):
        raise FileNotFoundError("gh")

    def slow(args, cwd, timeout):
        raise subprocess.TimeoutExpired(args, timeout)

    def garbage(args, cwd, timeout):
        return subprocess.CompletedProcess(args, 0, "not json", "")

    for gh in (missing, slow, garbage):
        assert run_view.fetch_prs("/r", {1}, set(), gh=gh) == ("unavailable", None), gh.__name__


@case("fetch: a view that times out after the list answered makes the forge unavailable")
def _():
    def gh(args, cwd, timeout):
        if args[1] == "list":
            return subprocess.CompletedProcess(args, 0, "[]", "")
        raise subprocess.TimeoutExpired(args, timeout)
    assert run_view.fetch_prs("/r", {7}, set(), gh=gh) == ("unavailable", None)


# ---------------------------------------------------------------- the command

def run_main(argv: list[str], env: dict | None = None, gh=None) -> tuple[int, dict]:
    buffer = io.StringIO()
    saved = {k: os.environ.get(k) for k in (env or {})}
    original = run_view.run_gh
    os.environ.update(env or {})
    if gh is not None:
        run_view.run_gh = gh
    try:
        with contextlib.redirect_stdout(buffer):
            code = run_view.main(argv)
    finally:
        run_view.run_gh = original
        for key, value in saved.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
    return code, json.loads(buffer.getvalue())


def project(rows_by_name: dict[str, list[tuple]], header: str = HEAD) -> tuple[Path, dict]:
    """A repository directory whose run directory (through PLUMB_ROOT) holds these ledgers."""
    _counter[0] += 1
    base = ROOT / f"repo{_counter[0]}"
    run_dir = base / "plumb" / "run"
    for name, rows in rows_by_name.items():
        write_ledger(rows, name=name, header=header, directory=run_dir)
    return base, {"PLUMB_ROOT": str(base / "plumb")}


def fresh(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_fresh(directory: Path, name: str, rows: list[tuple], header: str = HEAD) -> None:
    """rows: (minutes_ago, item, state, lane, ref)"""
    directory.mkdir(parents=True, exist_ok=True)
    lines = [header] + ["\t".join([fresh(m), item, state, lane, "e", "n", ref][:len(header.split("\t"))]) for m, item, state, lane, ref in rows]
    (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


@case("command: an empty or missing run directory is {\"runs\": []} and exit 0, with no forge call")
def _():
    base = ROOT / "emptyrepo"
    base.mkdir()

    def never(args, cwd, timeout):
        raise AssertionError("the forge must not be asked")
    code, doc = run_main(["--repo", str(base)], {"PLUMB_ROOT": str(base / "plumb")}, never)
    assert (code, doc) == (0, {"runs": []}), (code, doc)
    (base / "plumb" / "run").mkdir(parents=True)
    assert run_main(["--repo", str(base)], {"PLUMB_ROOT": str(base / "plumb")}, never) == (0, {"runs": []})
    assert run_main(["--repo", str(base / "nowhere")], {"PLUMB_ROOT": str(base / "plumb")}, never) == (0, {"runs": []})


@case("command: --since filters on the last row; other TSVs and headers in the run directory are skipped")
def _():
    base = ROOT / "since"
    run_dir = base / "plumb" / "run"
    write_fresh(run_dir, "lead-issues-new.tsv", [(300, "#1", "ready", "lane-1", "-"), (30, "#1", "ready-pr", "lane-1", "-")])
    write_fresh(run_dir, "lead-issues-old.tsv", [(900, "#2", "ready", "lane-2", "-"), (800, "#2", "ready-pr", "lane-2", "-")])
    write_fresh(run_dir, "lead-prs-odd.tsv", [(10, "#3", "ready", "lane-3", "-")], header="ts\titem\tstate")
    (run_dir / "decision-20260110.tsv").write_text("ts\titem\tstate\tlane\tevidence\tnext\n", encoding="utf-8")
    env = {"PLUMB_ROOT": str(base / "plumb")}
    code, doc = run_main(["--repo", str(base), "--no-remote"], env)
    assert code == 0 and [r["name"] for r in doc["runs"]] == ["lead-issues-new"], doc
    assert doc["remote"] == "skipped" and doc["repo"] == str(base)
    code, doc = run_main(["--repo", str(base), "--no-remote", "--since", "24"], env)
    assert [r["name"] for r in doc["runs"]] == ["lead-issues-new", "lead-issues-old"], [r["name"] for r in doc["runs"]]
    code, doc = run_main(["--repo", str(base), "--no-remote", "--since", "0.1"], env)
    assert doc == {"runs": []}


@case("command: --ledger reads exactly those files, whatever their age, and skips what is not a ledger")
def _():
    base = ROOT / "explicit"
    old = write_ledger([(0, "#1", "ready", "lane-1")], name="lead-issues-old.tsv", directory=base)
    junk = base / "junk.tsv"
    junk.write_text("a\tb\n1\t2\n", encoding="utf-8")
    code, doc = run_main(["--ledger", str(old), "--ledger", str(junk), "--ledger", str(base / "gone.tsv"), "--no-remote"])
    assert code == 0 and [r["name"] for r in doc["runs"]] == ["lead-issues-old"], doc


@case("command: --no-remote makes no forge call; every pr is null")
def _():
    base = ROOT / "noremote"
    write_fresh(base / "plumb" / "run", "lead-issues-a.tsv", [(20, "#140", "ready-pr", "lane-140", "pr:140")])

    def never(args, cwd, timeout):
        raise AssertionError("the forge must not be asked")
    code, doc = run_main(["--repo", str(base), "--no-remote"], {"PLUMB_ROOT": str(base / "plumb")}, never)
    assert code == 0 and doc["remote"] == "skipped" and doc["runs"][0]["lanes"][0]["pr"] is None


@case("command: a forge that is not there is remote unavailable, every pr null, exit 0")
def _():
    base = ROOT / "nogh"
    write_fresh(base / "plumb" / "run", "lead-issues-a.tsv", [(20, "#140", "ready-pr", "lane-140", "pr:140")])

    def missing(args, cwd, timeout):
        raise FileNotFoundError("gh")
    code, doc = run_main(["--repo", str(base)], {"PLUMB_ROOT": str(base / "plumb")}, missing)
    assert code == 0 and doc["remote"] == "unavailable" and doc["runs"][0]["lanes"][0]["pr"] is None, doc


@case("command: with the forge up, links resolve end to end and a merged pull request is done")
def _():
    base = ROOT / "forge"
    write_fresh(base / "plumb" / "run", "lead-issues-a.tsv",
                [(60, "#101", "ready", "lane-101", "branch:fix-101"), (30, "#101", "ready-pr", "lane-101", "-"),
                 (20, "#102", "ready", "lane-102", "pr:140"), (10, "#103", "needs-ruling", "-", "-")])
    gh = FakeGh([raw_pr(150, head="fix-101", created=fresh(40)), raw_pr(140, state="MERGED", created=fresh(100), merged=fresh(5))])
    code, doc = run_main(["--repo", str(base)], {"PLUMB_ROOT": str(base / "plumb")}, gh)
    run = doc["runs"][0]
    assert code == 0 and doc["remote"] == "ok"
    assert lane_of(run, "#101")["pr"]["number"] == 150 and lane_of(run, "#102")["done"] is True
    assert [(u["item"], u["needs_owner"]) for u in run["upcoming"]] == [("#101", False), ("#103", True)]


@case("command: bad usage exits non-zero; the wrapper runs the script and resolves a symlink")
def _():
    bad = subprocess.run([sys.executable, str(HERE / "run_view.py"), "--since", "soon"], capture_output=True, text=True)
    assert bad.returncode == 2 and "usage" in bad.stderr, bad
    negative = subprocess.run([sys.executable, str(HERE / "run_view.py"), "--since", "-3"], capture_output=True, text=True)
    assert negative.returncode == 2, negative
    base = ROOT / "wrapper"
    base.mkdir()
    link = base / "plumb-run-view"
    link.symlink_to(BIN)
    out = subprocess.run([str(link), "--repo", str(base), "--no-remote"], capture_output=True, text=True,
                         env={**os.environ, "PLUMB_ROOT": str(base / "plumb")})
    assert out.returncode == 0 and json.loads(out.stdout) == {"runs": []}, out
    assert os.access(BIN, os.X_OK)


@case("a ledger written before the ref column existed still reads end to end")
def _():
    base = ROOT / "legacy"
    write_fresh(base / "plumb" / "run", "lead-issues-a.tsv", [(20, "#201", "ready-pr", "lane-201", "-")], header=OLD_HEAD)
    code, doc = run_main(["--repo", str(base)], {"PLUMB_ROOT": str(base / "plumb")}, FakeGh([raw_pr(201)]))
    assert code == 0 and lane_of(doc["runs"][0], "#201")["pr"]["number"] == 201, doc


shutil.rmtree(ROOT, ignore_errors=True)
if FAILED:
    print(f"\n{len(FAILED)} case(s) failed")
    sys.exit(1)
print("\nall cases ok")
