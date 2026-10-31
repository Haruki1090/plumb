#!/usr/bin/env python3
"""Regression suite for plumb-verify (compare and plan) on synthetic data only.

    python3 -B scripts/test-verify.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline in
tempfile.mkdtemp(): rows, thresholds and manifests are generated here, and `plan` runs in throwaway
git repositories. No Node is needed.

Parity. The comparator is a port of SAKUJI's compare.mjs. The parity cases pin the semantics that the
port did not change to this revision of SAKUJI feat/feature-verify:

    SAKUJI_REVISION = 675139921c809c7f142f758ba4f455be8d86b48e
    (scripts/feature-map/verify/compare.mjs, metrics.mjs, thresholds.json)

The expected regressions in the parity case were derived by hand from compare.mjs at that revision.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(HERE))
import verify_compare  # noqa: E402

VERIFY = PLUGIN / "bin" / "plumb-verify"
SAKUJI_REVISION = "675139921c809c7f142f758ba4f455be8d86b48e"
EXPECT_SCHEMA = "verify-expect/1"
COMPARE_SCHEMA = "verify-compare/1"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-verify-test-"))
FAILED: list = []
OUTPUTS: list = []          # every stdout and stderr the CLI produced, scanned for the word "pass"
COUNTER = [0]


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

def fresh(label: str = "t") -> Path:
    COUNTER[0] += 1
    path = ROOT / f"{label}-{COUNTER[0]}"
    path.mkdir()
    return path


def jsonl(rows) -> str:
    if isinstance(rows, str):
        return rows
    return "".join(json.dumps(r) + "\n" for r in rows)


def as_json(value) -> str:
    return value if isinstance(value, str) else json.dumps(value)


# The thresholds file of the first consumer (SAKUJI thresholds.json at SAKUJI_REVISION), with the
# prose fields left out.
THRESHOLDS = {
    "version": "provisional-1",
    "status": "provisional",
    "min_repeat_for_growth": 3,
    "metrics": {
        "console_errors": {"rule": "increase_abs", "max": 0},
        "pageerrors": {"rule": "increase_abs", "field": "pageerrors_unknown", "max": 0},
        "pageerrors_known": {"rule": "known_diff", "max_ratio": 1.5, "min_abs": 3},
        "http_5xx": {"rule": "list_new", "max": 0},
        "http_4xx": {"rule": "list_new", "max": 0},
        "failed_requests": {"rule": "list_new", "max": 0},
        "requests_per_iter": {"rule": "increase_ratio_and_abs", "max_ratio": 1.5, "min_abs": 5},
        "longtask_ms_per_iter": {"rule": "increase_ratio_and_abs", "max_ratio": 1.5, "min_abs": 300},
        "growth.heap_mb": {"rule": "growth_diff", "max": 0.5},
        "growth.listeners": {"rule": "growth_diff", "max": 5},
        "growth.workers": {"rule": "growth_diff", "max": 0.2},
        "growth.dom_nodes": {"rule": "growth_diff", "max": 50},
        "screenshot_diff_ratio": {"rule": "abs_max", "max": 0.01},
    },
}

KEY = "feat.a/S1/ADMIN"


def row(side: str, scenario: str = "S1", feature: str = "feat.a", role: str = "ADMIN", **over) -> dict:
    """A clean `ok` row with every metric the thresholds above read. A value of None removes a field."""
    out = {
        "schema": "verify-metrics/1", "feature": feature, "scenario": scenario, "role": role, "side": side,
        "status": "ok", "error": None, "repeat": 3,
        "console_errors": 0, "pageerrors": 0, "pageerrors_known": {}, "pageerrors_unknown": 0,
        "http_4xx": [], "http_5xx": [], "failed_requests": [],
        "requests_per_iter": 5.0, "longtask_ms_per_iter": 100, "writes": {},
        "growth_per_iter": {"heap_mb": 0.1, "dom_nodes": 0, "listeners": 0, "workers": 0},
    }
    out.update(over)
    return {k: v for k, v in out.items() if v is not None}


def key_of(r: dict) -> str:
    return f"{r['feature']}/{r['scenario']}/{r['role']}"


def manifest_for(*row_lists, **over) -> dict:
    keys = sorted({key_of(r) for rows in row_lists for r in rows})
    out = {"schema": EXPECT_SCHEMA, "expected": keys}
    out.update(over)
    return out


class Run:
    def __init__(self, code: int, stdout: str, stderr: str) -> None:
        self.code, self.stdout, self.stderr = code, stdout, stderr
        try:
            self.out = json.loads(stdout)
        except ValueError:
            self.out = None

    @property
    def kinds(self) -> set:
        return {n["kind"] for n in (self.out or {}).get("notes", [])}


def run_cli(args: list, cwd=None, env=None) -> Run:
    done = subprocess.run([str(VERIFY), *args], capture_output=True, text=True, cwd=cwd,
                          env={**os.environ, **(env or {})})
    OUTPUTS.append(done.stdout)
    OUTPUTS.append(done.stderr)
    return Run(done.returncode, done.stdout, done.stderr)


def compare(base, pr, thresholds=THRESHOLDS, manifest="auto", shots=None, drop=(), extra=()) -> Run:
    """Run `plumb-verify compare` on generated files. `drop` names options to leave out."""
    d = fresh("cmp")
    (d / "base.jsonl").write_text(jsonl(base))
    (d / "pr.jsonl").write_text(jsonl(pr))
    (d / "thr.json").write_text(as_json(thresholds))
    if manifest == "auto":
        manifest = manifest_for(base if not isinstance(base, str) else [], pr if not isinstance(pr, str) else [])
    (d / "expect.json").write_text(as_json(manifest))
    args = ["--base", str(d / "base.jsonl"), "--pr", str(d / "pr.jsonl"),
            "--thresholds", str(d / "thr.json"), "--expect", str(d / "expect.json")]
    if shots is not None:
        (d / "shots.jsonl").write_text(jsonl(shots))
        args += ["--shot-diffs", str(d / "shots.jsonl")]
    for option in drop:
        i = args.index(option)
        del args[i:i + 2]
    return run_cli(["compare", *args, *extra])


def clean_pair(**over):
    return [row("base", **over)], [row("pr", **over)]


def one_rule(rule: dict, metric: str, b: dict, p: dict) -> Run:
    thr = {"version": "t", "status": "provisional", "min_repeat_for_growth": 3, "metrics": {metric: rule}}
    return compare([row("base", **b)], [row("pr", **p)], thresholds=thr)


def regressed_metrics(res: Run) -> list:
    return [r["metric"] for r in res.out["regressions"]]


def want_result(res: Run, result: str, code: int) -> None:
    assert res.out is not None, f"no JSON: {res.stdout!r} {res.stderr!r}"
    assert res.out["result"] == result and res.code == code, (res.out["result"], res.code, res.out["summary"], res.out["notes"])


def want_clean(res: Run) -> None:
    want_result(res, "no_diff", 0)
    assert res.out["regressions"] == [] and res.out["notes"] == [], res.out


def want_regress(res: Run, *metrics) -> None:
    want_result(res, "regressed", 1)
    if metrics:
        assert regressed_metrics(res) == list(metrics), regressed_metrics(res)


def want_incomplete(res: Run, kind: str) -> None:
    want_result(res, "incomplete", 3)
    assert kind in res.kinds, (kind, res.kinds)
    assert res.out["regressions"] == [], res.out["regressions"]


def want_usage(res: Run, *words: str) -> None:
    assert res.code == 2 and res.stdout == "", (res.code, res.stdout, res.stderr)
    for word in words:
        assert word in res.stderr, (word, res.stderr)


# ---------------------------------------------------------------- outcomes

@case("no_diff: identical clean rows exit 0, with the plan's output schema and pr naming")
def _():
    res = compare(*clean_pair())
    want_clean(res)
    assert res.out["schema"] == COMPARE_SCHEMA and res.out["compared"] == [KEY]
    assert res.out["thresholds"] == {"version": "provisional-1", "status": "provisional"}
    assert set(res.out) == {"schema", "result", "summary", "thresholds", "compared", "regressions", "notes", "missing"}
    assert "candidate" not in res.stdout.lower()


@case("regressed: an injected metric regression exits 1 and names key, metric, values, threshold")
def _():
    res = compare([row("base")], [row("pr", console_errors=2)])
    want_regress(res, "console_errors")
    r = res.out["regressions"][0]
    assert (r["key"], r["base"], r["pr"], r["delta"]) == (KEY, 0, 2, 2), r
    assert r["threshold"]["rule"] == "increase_abs" and r["threshold"]["max"] == 0


@case("--out writes the same result that is printed")
def _():
    d = fresh("out")
    base, pr = clean_pair()
    (d / "b").write_text(jsonl(base))
    (d / "p").write_text(jsonl(pr))
    (d / "t").write_text(json.dumps(THRESHOLDS))
    (d / "e").write_text(json.dumps(manifest_for(base, pr)))
    res = run_cli(["compare", "--base", str(d / "b"), "--pr", str(d / "p"), "--thresholds", str(d / "t"),
                   "--expect", str(d / "e"), "--out", str(d / "result.json")])
    assert res.code == 0 and json.loads((d / "result.json").read_text()) == res.out


@case("the last row per key and side wins")
def _():
    base = [row("base", console_errors=9), row("base", console_errors=0)]
    pr = [row("pr", console_errors=0), row("pr", console_errors=0)]
    want_clean(compare(base, pr, manifest=manifest_for(base, pr)))
    pr2 = [row("pr", console_errors=0), row("pr", console_errors=1)]
    want_regress(compare(base, pr2, manifest=manifest_for(base, pr2)), "console_errors")


# ---------------------------------------------------------------- status

@case("status: explicit values are used as given")
def _():
    for status in verify_compare.STATUSES:
        assert verify_compare.status_of({"status": status, "ok": True}) == status


@case("status: legacy derivation (ok true, harness: error, any other ok false)")
def _():
    sof = verify_compare.status_of
    assert sof({"ok": True}) == "ok"
    assert sof({"ok": True, "error": None}) == "ok"
    assert sof({"ok": False, "error": "harness: role mismatch"}) == "harness_error"
    assert sof({"ok": False, "error": "timeout"}) == "scenario_failed"
    assert sof({"ok": False, "error": None}) == "scenario_failed"
    assert sof({"ok": False}) == "scenario_failed"


@case("legacy rows without status compare like status rows")
def _():
    base = [{k: v for k, v in row("base").items() if k != "status"} | {"ok": True}]
    pr = [{k: v for k, v in row("pr", console_errors=1).items() if k != "status"} | {"ok": True}]
    want_regress(compare(base, pr, manifest=manifest_for(base, pr)), "console_errors")


# ---------------------------------------------------------------- incomplete causes, one fixture each

@case("incomplete: expected key with no row on either side")
def _():
    base, pr = clean_pair()
    res = compare(base, pr, manifest=manifest_for(base, pr, ) | {"expected": [KEY, "feat.b/S1/ADMIN"]})
    want_incomplete(res, "no_rows")
    assert res.out["missing"]["no_rows"] == ["feat.b/S1/ADMIN"]


@case("incomplete: key with a row on the base side only / the pr side only")
def _():
    base = [row("base"), row("base", scenario="S2")]
    pr = [row("pr")]
    res = compare(base, pr, manifest=manifest_for(base, pr))
    want_incomplete(res, "only_in_base")
    assert res.out["missing"]["only_in_base"] == ["feat.a/S2/ADMIN"]
    base = [row("base")]
    pr = [row("pr"), row("pr", scenario="S2")]
    res = compare(base, pr, manifest=manifest_for(base, pr))
    want_incomplete(res, "only_in_pr")
    assert res.out["missing"]["only_in_pr"] == ["feat.a/S2/ADMIN"]


@case("incomplete: expected screenshot with --shot-diffs absent")
def _():
    base, pr = clean_pair()
    res = compare(base, pr, manifest=manifest_for(base, pr, shots={KEY: ["list"]}))
    want_incomplete(res, "shot_no_diff")
    assert res.out["missing"]["shots_without_diff"] == [f"{KEY}#list"]


@case("incomplete: expected screenshot with an empty --shot-diffs file")
def _():
    base, pr = clean_pair()
    res = compare(base, pr, manifest=manifest_for(base, pr, shots={KEY: ["list"]}), shots=[])
    want_incomplete(res, "shot_no_diff")


@case("incomplete: --shot-diffs partly filled (one of two expected shots has a row)")
def _():
    base, pr = clean_pair()
    res = compare(base, pr, manifest=manifest_for(base, pr, shots={KEY: ["list", "opened"]}),
                  shots=[{"key": KEY, "name": "list", "ratio": 0.0}])
    want_incomplete(res, "shot_no_diff")
    assert res.out["missing"]["shots_without_diff"] == [f"{KEY}#opened"]


@case("no_diff: every expected screenshot has a diff row under the limit")
def _():
    base, pr = clean_pair()
    res = compare(base, pr, manifest=manifest_for(base, pr, shots={KEY: ["list", "opened"]}),
                  shots=[{"key": KEY, "name": "list", "ratio": 0.0}, {"key": KEY, "name": "opened", "ratio": 0.005}])
    want_clean(res)


@case("incomplete: a screenshot present on one side only (missing pr / missing base)")
def _():
    base, pr = clean_pair()
    manifest = manifest_for(base, pr, shots={KEY: ["list"]})
    res = compare(base, pr, manifest=manifest, shots=[{"key": KEY, "name": "list", "missing": "pr"}])
    want_incomplete(res, "shot_missing")
    assert res.out["missing"]["shots_only_in_base"] == [f"{KEY}#list"] and res.out["missing"]["shots_only_in_pr"] == []
    res = compare(base, pr, manifest=manifest, shots=[{"key": KEY, "name": "list", "missing": "base"}])
    want_incomplete(res, "shot_missing")
    assert res.out["missing"]["shots_only_in_pr"] == [f"{KEY}#list"]


@case("incomplete: a shot-diff row without a finite ratio is not measured")
def _():
    base, pr = clean_pair()
    manifest = manifest_for(base, pr, shots={KEY: ["list"]})
    for bad in ({"key": KEY, "name": "list"}, {"key": KEY, "name": "list", "ratio": "0.1"},
                {"key": KEY, "name": "list", "ratio": None}):
        want_incomplete(compare(base, pr, manifest=manifest, shots=[bad]), "not_measured")


@case("incomplete: shot-diff rows with no abs_max rule in the thresholds")
def _():
    base, pr = clean_pair()
    thr = {**THRESHOLDS, "metrics": {"console_errors": THRESHOLDS["metrics"]["console_errors"]}}
    res = compare(base, pr, thresholds=thr, manifest=manifest_for(base, pr, shots={KEY: ["list"]}),
                  shots=[{"key": KEY, "name": "list", "ratio": 0.5}])
    want_incomplete(res, "not_measured")


@case("incomplete: an unmapped path in the manifest")
def _():
    base, pr = clean_pair()
    res = compare(base, pr, manifest=manifest_for(base, pr, unmapped=["src/orphan.ts"]))
    want_incomplete(res, "unmapped")
    assert res.out["missing"]["unmapped"] == ["src/orphan.ts"]


@case("incomplete: a not-run scenario in the manifest carries its reason")
def _():
    base, pr = clean_pair()
    res = compare(base, pr, manifest=manifest_for(base, pr, not_run=[{"key": "feat.b/S1/ADMIN", "reason": "needs ai"}]))
    want_incomplete(res, "not_run_scenario")
    assert res.out["missing"]["not_run_scenarios"] == [{"key": "feat.b/S1/ADMIN", "reason": "needs ai"}]


@case("incomplete: restore_check.ok false on either side")
def _():
    for side in ("base", "pr"):
        base, pr = clean_pair()
        (base if side == "base" else pr)[0]["restore_check"] = {"ok": False, "error": "state left over"}
        res = compare(base, pr)
        want_incomplete(res, "restore_failed")
        assert side in res.out["notes"][0]["detail"]
    base, pr = clean_pair()
    base[0]["restore_check"] = {"ok": True}
    want_clean(compare(base, pr))


@case("incomplete: cleanup_error on either side (the numbers are still compared)")
def _():
    for side in ("base", "pr"):
        base, pr = clean_pair()
        (base if side == "base" else pr)[0]["cleanup_error"] = "delete failed"
        want_incomplete(compare(base, pr), "cleanup_failed")
    base, pr = [row("base", cleanup_error="x")], [row("pr", console_errors=1, cleanup_error="x")]
    want_regress(compare(base, pr, manifest=manifest_for(base, pr)), "console_errors")


@case("incomplete: a metric a rule names that is missing or not finite (not_measured)")
def _():
    base = [row("base")]
    for value in (None, "3", True, [1]):
        pr = [row("pr", console_errors=value)]
        res = compare(base, pr, manifest=manifest_for(base, pr))
        want_incomplete(res, "not_measured")
        assert res.out["compared"] == [KEY]
    # 1e999 is valid JSON that Python reads as infinity: not a finite number
    text = jsonl([row("pr")]).replace('"console_errors": 0', '"console_errors": 1e999')
    assert "1e999" in text
    want_incomplete(compare(base, text, manifest=manifest_for(base, [row("pr")])), "not_measured")


@case("incomplete: a base metric missing is also not_measured")
def _():
    base, pr = [row("base", http_5xx=None)], [row("pr")]
    want_incomplete(compare(base, pr, manifest=manifest_for(base, pr)), "not_measured")


@case("incomplete: repeat below min_repeat_for_growth (base side, pr side, both)")
def _():
    for b, p in ((2, 3), (3, 2), (1, 1)):
        base, pr = [row("base", repeat=b)], [row("pr", repeat=p)]
        res = compare(base, pr, manifest=manifest_for(base, pr))
        want_incomplete(res, "repeat_too_small")
        assert [n["kind"] for n in res.out["notes"]].count("repeat_too_small") == 1
    base, pr = [row("base", repeat=None)], [row("pr", repeat=None)]       # a missing repeat counts as 1
    want_incomplete(compare(base, pr, manifest=manifest_for(base, pr)), "repeat_too_small")
    base, pr = [row("base", repeat=3)], [row("pr", repeat=3)]
    want_clean(compare(base, pr, manifest=manifest_for(base, pr)))


@case("incomplete: start_failed on either side, on both")
def _():
    for sides in (("base",), ("pr",), ("base", "pr")):
        base = [row("base", status="start_failed" if "base" in sides else "ok")]
        pr = [row("pr", status="start_failed" if "pr" in sides else "ok")]
        res = compare(base, pr, manifest=manifest_for(base, pr))
        want_incomplete(res, "start_failed")
        assert res.out["missing"]["start_failed"] == [KEY] and res.out["missing"]["incomplete"] == [KEY]


@case("incomplete: not_run on either side")
def _():
    for sides in (("base",), ("pr",)):
        base = [row("base", status="not_run" if "base" in sides else "ok")]
        pr = [row("pr", status="not_run" if "pr" in sides else "ok")]
        want_incomplete(compare(base, pr, manifest=manifest_for(base, pr)), "not_run")


@case("incomplete: harness_error, explicit status and legacy error: \"harness:...\"")
def _():
    base = [row("base")]
    pr = [row("pr", status="harness_error", error="role mismatch")]
    res = compare(base, pr, manifest=manifest_for(base, pr))
    want_incomplete(res, "harness_error")
    assert res.out["missing"]["harness_error"] == [KEY]
    legacy = [{k: v for k, v in row("pr").items() if k != "status"} | {"ok": False, "error": "harness: role mismatch"}]
    res = compare(base, legacy, manifest=manifest_for(base, legacy))
    want_incomplete(res, "harness_error")
    res = compare(legacy, [row("pr")], manifest=manifest_for(base, legacy))
    want_incomplete(res, "harness_error")


@case("incomplete: pr_failed is not a regression (candidate-only scenario failure)")
def _():
    base = [row("base")]
    pr = [row("pr", status="scenario_failed", error="timeout")]
    res = compare(base, pr, manifest=manifest_for(base, pr))
    want_incomplete(res, "pr_failed")
    assert res.out["regressions"] == []
    legacy = [{k: v for k, v in row("pr").items() if k != "status"} | {"ok": False, "error": "timeout"}]
    want_incomplete(compare(base, legacy, manifest=manifest_for(base, legacy)), "pr_failed")


@case("incomplete: base_failed and both_failed")
def _():
    base = [row("base", status="scenario_failed", error="boom")]
    pr = [row("pr")]
    want_incomplete(compare(base, pr, manifest=manifest_for(base, pr)), "base_failed")
    pr = [row("pr", status="scenario_failed", error="boom")]
    res = compare(base, pr, manifest=manifest_for(base, pr))
    want_incomplete(res, "both_failed")
    assert "base_failed" not in res.kinds and "pr_failed" not in res.kinds


@case("incomplete: nothing compared (empty inputs, empty manifest)")
def _():
    res = compare([], [], manifest={"schema": EXPECT_SCHEMA, "expected": []})
    want_incomplete(res, "nothing_compared")
    assert res.out["compared"] == []
    base, pr = [row("base")], [row("pr", scenario="S2")]
    res = compare(base, pr, manifest=manifest_for(base, pr))
    want_incomplete(res, "nothing_compared")


@case("a row not ok does not stop other keys from being compared")
def _():
    base = [row("base"), row("base", scenario="S2")]
    pr = [row("pr", status="start_failed"), row("pr", scenario="S2", console_errors=3)]
    res = compare(base, pr, manifest=manifest_for(base, pr))
    want_result(res, "regressed", 1)
    assert regressed_metrics(res) == ["console_errors"] and res.out["regressions"][0]["key"] == "feat.a/S2/ADMIN"
    assert res.out["missing"]["start_failed"] == [KEY]


@case("precedence: a regression and an incomplete cause together are regressed, with the scope listed")
def _():
    base = [row("base"), row("base", scenario="S2")]
    pr = [row("pr", console_errors=1), row("pr", scenario="S2", status="harness_error", error="harness: x")]
    manifest = manifest_for(base, pr, unmapped=["a.ts"], not_run=[{"key": "feat.z/S1/ADMIN", "reason": "r"}])
    res = compare(base, pr, manifest=manifest)
    want_result(res, "regressed", 1)
    assert res.out["missing"]["harness_error"] == ["feat.a/S2/ADMIN"] and res.out["missing"]["unmapped"] == ["a.ts"]
    assert {"harness_error", "unmapped", "not_run_scenario"} <= res.kinds


@case("precedence: incomplete without a regression is incomplete (3), never no_diff")
def _():
    base, pr = clean_pair()
    want_result(compare(base, pr, manifest=manifest_for(base, pr, unmapped=["a.ts"])), "incomplete", 3)


@case("info: new_writes is a note and does not make a clean run incomplete")
def _():
    base, pr = [row("base")], [row("pr", writes={"POST /api/x": 1})]
    res = compare(base, pr, manifest=manifest_for(base, pr))
    want_result(res, "no_diff", 0)
    assert res.kinds == {"new_writes"}


# ---------------------------------------------------------------- rule boundaries: at, below, above

@case("increase_abs: at the limit is clean, one above regresses, below is clean")
def _():
    rule = {"rule": "increase_abs", "max": 2}
    want_clean(one_rule(rule, "console_errors", {"console_errors": 1}, {"console_errors": 3}))      # delta == max
    want_clean(one_rule(rule, "console_errors", {"console_errors": 1}, {"console_errors": 2}))      # below
    want_clean(one_rule(rule, "console_errors", {"console_errors": 5}, {"console_errors": 0}))      # better
    res = one_rule(rule, "console_errors", {"console_errors": 1}, {"console_errors": 4})            # above
    want_regress(res, "console_errors")
    assert res.out["regressions"][0]["delta"] == 3
    want_regress(one_rule(rule, "console_errors", {"console_errors": 0}, {"console_errors": 2.5}), "console_errors")


@case("increase_abs: `field` is read first and the metric name is the fallback (legacy rows)")
def _():
    rule = {"rule": "increase_abs", "field": "pageerrors_unknown", "max": 0}
    want_regress(one_rule(rule, "pageerrors", {"pageerrors_unknown": 0, "pageerrors": 9}, {"pageerrors_unknown": 1, "pageerrors": 9}), "pageerrors")
    want_clean(one_rule(rule, "pageerrors", {"pageerrors_unknown": 0, "pageerrors": 0}, {"pageerrors_unknown": 0, "pageerrors": 7}))
    want_regress(one_rule(rule, "pageerrors", {"pageerrors_unknown": None, "pageerrors": 1}, {"pageerrors_unknown": None, "pageerrors": 2}), "pageerrors")
    want_incomplete(one_rule(rule, "pageerrors", {"pageerrors_unknown": None, "pageerrors": None}, {"pageerrors": 1}), "not_measured")


@case("known_diff: delta at min_abs, ratio at max_ratio, and both just above")
def _():
    rule = {"rule": "known_diff", "min_abs": 3, "max_ratio": 1.5}
    k = lambda v: {"pageerrors_known": {"F-015": v}}  # noqa: E731
    want_clean(one_rule(rule, "pageerrors_known", k(10), k(15)))     # delta 5 > 3 but 15 > 15 is false
    want_regress(one_rule(rule, "pageerrors_known", k(10), k(16)), "pageerrors_known.F-015")
    want_clean(one_rule(rule, "pageerrors_known", k(1), k(4)))       # 4 > 1.5 but delta 3 > 3 is false
    want_regress(one_rule(rule, "pageerrors_known", k(1), k(5)), "pageerrors_known.F-015")
    want_clean(one_rule(rule, "pageerrors_known", k(36), k(20)))     # fewer
    want_clean(one_rule(rule, "pageerrors_known", k(0), k(3)))       # b = 0: delta 3 is not above 3
    res = one_rule(rule, "pageerrors_known", k(0), k(4))             # b = 0: only the absolute part can hold
    want_regress(res, "pageerrors_known.F-015")
    assert res.out["regressions"][0]["base"] == 0 and res.out["regressions"][0]["delta"] == 4


@case("known_diff: a missing id is 0, ids are judged separately, an empty map is measured")
def _():
    rule = {"rule": "known_diff", "min_abs": 3, "max_ratio": 1.5}
    res = one_rule(rule, "pageerrors_known", {"pageerrors_known": {"A": 1}}, {"pageerrors_known": {"B": 4, "A": 1}})
    want_regress(res, "pageerrors_known.B")
    want_clean(one_rule(rule, "pageerrors_known", {"pageerrors_known": {}}, {"pageerrors_known": {}}))
    want_incomplete(one_rule(rule, "pageerrors_known", {"pageerrors_known": {}}, {"pageerrors_known": None}), "not_measured")
    want_incomplete(one_rule(rule, "pageerrors_known", {"pageerrors_known": {"A": "x"}}, {"pageerrors_known": {}}), "not_measured")


@case("list_new: size is the list length with duplicates; at max is clean, above regresses")
def _():
    rule = {"rule": "list_new", "max": 0}
    want_clean(one_rule(rule, "http_5xx", {"http_5xx": ["500 GET /a"]}, {"http_5xx": ["500 GET /a"]}))
    want_clean(one_rule(rule, "http_5xx", {"http_5xx": ["500 GET /a", "500 GET /b"]}, {"http_5xx": ["500 GET /a"]}))
    res = one_rule(rule, "http_5xx", {"http_5xx": ["500 GET /a"]}, {"http_5xx": ["500 GET /a", "500 GET /a"]})
    want_regress(res, "http_5xx")
    assert res.out["regressions"][0]["added"] == ["500 GET /a"] and res.out["regressions"][0]["delta"] == 1
    rule1 = {"rule": "list_new", "max": 1}
    want_clean(one_rule(rule1, "http_5xx", {"http_5xx": []}, {"http_5xx": ["x"]}))               # delta == max
    want_regress(one_rule(rule1, "http_5xx", {"http_5xx": []}, {"http_5xx": ["x", "y"]}), "http_5xx")
    # numbers count too: the size is the number itself
    want_clean(one_rule(rule1, "http_5xx", {"http_5xx": 3}, {"http_5xx": 4}))
    want_regress(one_rule(rule1, "http_5xx", {"http_5xx": 3}, {"http_5xx": 5}), "http_5xx")
    res = one_rule(rule, "http_5xx", {"http_5xx": 0}, {"http_5xx": ["x"]})
    assert res.out["regressions"][0]["added"] == []                                               # not both lists


@case("list_new: the added entries are the multiset difference, at most 10, repeats marked")
def _():
    rule = {"rule": "list_new", "max": 0}
    res = one_rule(rule, "http_4xx", {"http_4xx": ["a", "b"]}, {"http_4xx": ["a", "b", "c", "c", "c"]})
    assert res.out["regressions"][0]["added"] == ["3x c"], res.out["regressions"]
    res = one_rule(rule, "http_4xx", {"http_4xx": ["a", "a"]}, {"http_4xx": ["a", "a", "a", "b"]})
    assert res.out["regressions"][0]["added"] == ["a", "b"], res.out["regressions"]
    res = one_rule(rule, "http_4xx", {"http_4xx": []}, {"http_4xx": [f"e{i}" for i in range(12)]})
    assert len(res.out["regressions"][0]["added"]) == 10
    # same size, different entries: the rule is on the size, so nothing regresses
    want_clean(one_rule(rule, "http_4xx", {"http_4xx": ["a", "b"]}, {"http_4xx": ["a", "z"]}))


@case("increase_ratio_and_abs: the absolute and the ratio limits, each at and just above; b = 0")
def _():
    rule = {"rule": "increase_ratio_and_abs", "min_abs": 5, "max_ratio": 1.5}
    r = lambda v: {"requests_per_iter": v}  # noqa: E731
    want_clean(one_rule(rule, "requests_per_iter", r(10), r(15)))        # delta 5 is not above 5
    want_regress(one_rule(rule, "requests_per_iter", r(10), r(16)), "requests_per_iter")
    want_clean(one_rule(rule, "requests_per_iter", r(10), r(12)))        # below
    want_clean(one_rule(rule, "requests_per_iter", r(20), r(30)))        # delta 10 but 30 > 30 is false
    want_regress(one_rule(rule, "requests_per_iter", r(20), r(31)), "requests_per_iter")
    want_clean(one_rule(rule, "requests_per_iter", r(30), r(10)))
    want_clean(one_rule(rule, "requests_per_iter", r(0), r(5)))          # b = 0: delta 5 is not above 5
    res = one_rule(rule, "requests_per_iter", r(0), r(5.01))
    want_regress(res, "requests_per_iter")
    assert res.out["regressions"][0]["delta"] == 5.01
    res = one_rule(rule, "requests_per_iter", r(5.33), r(12))            # rounded to 2 decimals
    assert res.out["regressions"][0]["delta"] == 6.67, res.out["regressions"]
    want_incomplete(one_rule(rule, "requests_per_iter", r(None), r(1)), "not_measured")


@case("growth_diff: delta at max is clean, above regresses; repeat at min is compared, below is not")
def _():
    rule = {"rule": "growth_diff", "max": 5}
    g = lambda v, rep=3: {"growth_per_iter": {"listeners": v}, "repeat": rep}  # noqa: E731
    want_clean(one_rule(rule, "growth.listeners", g(0), g(5)))
    res = one_rule(rule, "growth.listeners", g(0), g(6))
    want_regress(res, "growth.listeners")
    assert res.out["regressions"][0]["repeat"] == {"base": 3, "pr": 3}
    want_clean(one_rule(rule, "growth.listeners", g(9), g(0)))
    heap = {"rule": "growth_diff", "max": 0.5}
    h = lambda v: {"growth_per_iter": {"heap_mb": v}}  # noqa: E731
    want_clean(one_rule(heap, "growth.heap_mb", h(0.25), h(0.75)))      # exactly 0.5 in binary
    res = one_rule(heap, "growth.heap_mb", h(0.25), h(0.76))
    want_regress(res, "growth.heap_mb")
    assert res.out["regressions"][0]["delta"] == 0.51
    want_clean(one_rule(rule, "growth.listeners", g(0, 3), g(5, 3)))
    want_incomplete(one_rule(rule, "growth.listeners", g(0, 2), g(50, 3)), "repeat_too_small")
    want_incomplete(one_rule(rule, "growth.listeners", g(0, 3), g(50, 2)), "repeat_too_small")
    want_incomplete(one_rule(rule, "growth.listeners", {"growth_per_iter": None}, g(1)), "not_measured")
    want_incomplete(one_rule(rule, "growth.listeners", {"growth_per_iter": {}}, g(1)), "not_measured")
    thr = {"version": "t", "status": "s", "min_repeat_for_growth": 5, "metrics": {"growth.listeners": rule}}
    base, pr = [row("base", **g(0, 4))], [row("pr", **g(99, 5))]
    want_incomplete(compare(base, pr, thresholds=thr, manifest=manifest_for(base, pr)), "repeat_too_small")
    base, pr = [row("base", **g(0, 5))], [row("pr", **g(99, 5))]
    want_regress(compare(base, pr, thresholds=thr, manifest=manifest_for(base, pr)), "growth.listeners")


@case("abs_max: a shot ratio at the limit is clean, just above regresses, below is clean")
def _():
    base, pr = clean_pair()
    manifest = manifest_for(base, pr, shots={KEY: ["list"]})
    for ratio, regress in ((0.0099, False), (0.01, False), (0.0101, True)):
        res = compare(base, pr, manifest=manifest, shots=[{"key": KEY, "name": "list", "ratio": ratio}])
        if regress:
            want_regress(res, "screenshot_diff_ratio")
            r = res.out["regressions"][0]
            assert (r["key"], r["base"], r["pr"], r["shot"]) == (KEY, 0, 0.0101, "list"), r
        else:
            want_clean(res)


@case("rules: every comparison is strict (a delta equal to the limit is never a regression)")
def _():
    cases = [({"rule": "increase_abs", "max": 1}, "m", {"m": 1}, {"m": 2}),
             ({"rule": "list_new", "max": 1}, "m", {"m": 1}, {"m": 2}),
             ({"rule": "increase_ratio_and_abs", "min_abs": 1, "max_ratio": 1.0}, "m", {"m": 1}, {"m": 2}),
             ({"rule": "known_diff", "min_abs": 1, "max_ratio": 0.5}, "m", {"m": {"a": 1}}, {"m": {"a": 2}}),
             ({"rule": "growth_diff", "max": 1}, "growth.m", {"growth_per_iter": {"m": 1}}, {"growth_per_iter": {"m": 2}})]
    for rule, metric, b, p in cases:
        want_clean(one_rule(rule, metric, b, p))


# ---------------------------------------------------------------- exit 2

@case("exit 2: an unknown rule is an error even for a metric no row reads")
def _():
    thr = {**THRESHOLDS, "metrics": {**THRESHOLDS["metrics"], "weird": {"rule": "decrease_abs", "max": 1}}}
    res = compare(*clean_pair(), thresholds=thr)
    want_usage(res, "unknown rule", "weird", "decrease_abs")


@case("exit 2: a rule parameter missing or not a number")
def _():
    for rule in ({"rule": "increase_abs"}, {"rule": "increase_abs", "max": "0"}, {"rule": "known_diff", "max_ratio": 1},
                 {"rule": "increase_abs", "max": True}, {"max": 0}, 5):
        thr = {**THRESHOLDS, "metrics": {"m": rule}}
        want_usage(compare(*clean_pair(), thresholds=thr), "thr.json")


@case("exit 2: malformed rows name the file and the line (base and pr)")
def _():
    good = json.dumps(row("base"))
    res = compare(f"{good}\n{good}\n{{not json\n{good}\n", [row("pr")], manifest=manifest_for([row("base")]))
    want_usage(res, "base.jsonl:3:")
    res = compare([row("base")], f"\n{json.dumps(row('pr'))}\n{{\"a\":\n", manifest=manifest_for([row("base")]))
    want_usage(res, "pr.jsonl:3:")


@case("exit 2: a row that is not an object, lacks a key field, has an unknown status, or lacks status and ok")
def _():
    m = manifest_for([row("base")])
    for text, word in (('[1,2]\n', "not an object"), ('"x"\n', "not an object"),
                       (json.dumps({"scenario": "S1", "role": "R", "ok": True}) + "\n", "`feature`"),
                       (json.dumps(row("pr", status="passed")) + "\n", "unknown status"),
                       (json.dumps({k: v for k, v in row("pr").items() if k != "status"}) + "\n", "neither `status`")):
        res = compare([row("base")], text, manifest=m)
        want_usage(res, "pr.jsonl:1:", word)


@case("exit 2: NaN and Infinity are not JSON")
def _():
    text = json.dumps(row("pr")).replace('"console_errors": 0', '"console_errors": NaN') + "\n"
    assert "NaN" in text
    want_usage(compare([row("base")], text, manifest=manifest_for([row("base")])), "pr.jsonl:1:")


@case("exit 2: malformed thresholds and manifest name the file and line")
def _():
    base, pr = clean_pair()
    want_usage(compare(base, pr, thresholds='{\n "metrics": {\n  oops\n }\n}'), "thr.json:3:")
    want_usage(compare(base, pr, thresholds="[1]"), "thr.json")
    want_usage(compare(base, pr, manifest='{\n "schema": \n'), "expect.json:")
    want_usage(compare(base, pr, manifest={"schema": EXPECT_SCHEMA}), "expected")
    want_usage(compare(base, pr, manifest={"schema": "other/1", "expected": []}), "schema")
    want_usage(compare(base, pr, manifest={"schema": EXPECT_SCHEMA, "expected": [1]}), "expected")
    want_usage(compare(base, pr, manifest={"schema": EXPECT_SCHEMA, "expected": [], "not_run": [{"key": "k"}]}), "not_run[0]")
    want_usage(compare(base, pr, manifest={"schema": EXPECT_SCHEMA, "expected": [], "shots": {"k": "x"}}), "shots.k")
    want_usage(compare(base, pr, manifest=[]), "manifest")


@case("exit 2: malformed shot-diff rows")
def _():
    base, pr = clean_pair()
    want_usage(compare(base, pr, shots='{"key": "k", "name": "n", "ratio": 0}\nnot json\n'), "shots.jsonl:2:")
    want_usage(compare(base, pr, shots=[{"name": "n", "ratio": 0}]), "shots.jsonl:1:", "key")
    want_usage(compare(base, pr, shots=[{"key": "k", "name": "n", "missing": "both"}]), "missing")


@case("exit 2: a missing required argument (each of the four), a missing file and an unknown option")
def _():
    base, pr = clean_pair()
    for option in ("--base", "--pr", "--thresholds", "--expect"):
        res = compare(base, pr, drop=(option,))
        assert res.code == 2 and option in res.stderr, (option, res.code, res.stderr)
    res = run_cli(["compare", "--base", "/nonexistent/b", "--pr", "/nonexistent/p", "--thresholds", "/nonexistent/t", "--expect", "/nonexistent/e"])
    want_usage(res, "cannot read")
    res = compare(base, pr, extra=["--bogus", "1"])
    assert res.code == 2, res.code
    assert run_cli([]).code == 2 and run_cli(["frobnicate"]).code == 2 and run_cli(["compare"]).code == 2


@case("--help exits 0 and names both commands")
def _():
    res = run_cli(["--help"])
    assert res.code == 0 and "compare" in res.stdout and "plan" in res.stdout


# ---------------------------------------------------------------- parity with compare.mjs

# Two rows in the shape of SAKUJI's selftest run (docs/agents/feature-map/runs/2026-10-29-71858bad7-selftest/
# metrics.jsonl at SAKUJI_REVISION), trimmed of series and screenshots. They are legacy rows: `ok`, no `status`.
SAKUJI_BASE = {
    "schema": "verify-metrics/1", "feature": "project.list", "scenario": "S1", "role": "COMPANY_ADMIN", "side": "base",
    "ok": True, "error": None, "repeat": 3, "console_errors": 0, "console_warnings": 0, "pageerrors": 0,
    "pageerrors_known": {}, "pageerrors_unknown": 0, "http_4xx": [], "http_5xx": [], "failed_requests": [],
    "requests": 16, "requests_per_iter": 5.33, "writes": {}, "longtasks": 9, "longtask_ms": 1448,
    "longtask_ms_per_iter": 483,
    "first": {"heap_mb": 22.54, "dom_nodes": 2358, "listeners": 655, "workers": 0},
    "last": {"heap_mb": 23.3, "dom_nodes": 2359, "listeners": 655, "workers": 0},
    "growth_per_iter": {"heap_mb": 0.38, "dom_nodes": 0.5, "listeners": 0, "workers": 0},
    "workers_created": 0, "workers_closed": 0, "dialogs": [], "server_role": "COMPANY_ADMIN", "restore_check": None,
}
SAKUJI_PR = {**SAKUJI_BASE, "side": "pr", "longtasks": 8, "longtask_ms": 1245, "longtask_ms_per_iter": 415,
             "growth_per_iter": {"heap_mb": 0.36, "dom_nodes": 0.5, "listeners": 0, "workers": 0}}
PKEY = "project.list/S1/COMPANY_ADMIN"


@case("parity: SAKUJI's own selftest rows give no_diff, as compare.mjs did")
def _():
    res = compare([SAKUJI_BASE], [SAKUJI_PR], manifest={"schema": EXPECT_SCHEMA, "expected": [PKEY]})
    want_clean(res)
    assert res.out["compared"] == [PKEY]


@case("parity: the regressions compare.mjs reports for these rows, in threshold order, with its deltas")
def _():
    pr = {**SAKUJI_PR, "console_errors": 2, "pageerrors": 5, "pageerrors_unknown": 1,
          "pageerrors_known": {"F-015": 36}, "http_5xx": ["500 GET /api/x"],
          "requests_per_iter": 12, "longtask_ms_per_iter": 900,
          "growth_per_iter": {"heap_mb": 1.0, "dom_nodes": 0.5, "listeners": 8, "workers": 0}}
    base = {**SAKUJI_BASE, "pageerrors_known": {"F-015": 20}, "pageerrors": 4}
    res = compare([base], [pr], manifest={"schema": EXPECT_SCHEMA, "expected": [PKEY]})
    want_result(res, "regressed", 1)
    got = [(r["metric"], r["base"], r["pr"], r["delta"]) for r in res.out["regressions"]]
    assert got == [("console_errors", 0, 2, 2),
                   ("pageerrors", 0, 1, 1),                          # the unknown count, not the total
                   ("pageerrors_known.F-015", 20, 36, 16),           # 16 > 3 and 36 > 30
                   ("http_5xx", 0, 1, 1),
                   ("requests_per_iter", 5.33, 12, 6.67),            # 6.67 > 5 and 12 > 7.995
                   ("longtask_ms_per_iter", 483, 900, 417),          # 417 > 300 and 900 > 724.5
                   ("growth.heap_mb", 0.38, 1, 0.62),                # 0.62 > 0.5
                   ("growth.listeners", 0, 8, 8)], got
    assert res.out["regressions"][3]["added"] == ["500 GET /api/x"]
    assert res.out["regressions"][0]["threshold"] == THRESHOLDS["metrics"]["console_errors"]


@case("parity: the limits compare.mjs used for these rows hold (nothing regresses at them)")
def _():
    pr = {**SAKUJI_PR, "pageerrors_known": {"F-015": 3}, "requests_per_iter": 10.33, "longtask_ms_per_iter": 783,
          "growth_per_iter": {"heap_mb": 0.88, "dom_nodes": 50.5, "listeners": 5, "workers": 0.2}}
    base = {**SAKUJI_BASE, "pageerrors_known": {"F-015": 0}}
    want_clean(compare([base], [pr], manifest={"schema": EXPECT_SCHEMA, "expected": [PKEY]}))


@case("parity: legacy harness: errors were environment problems in compare.mjs and stay so")
def _():
    pr = {**SAKUJI_PR, "ok": False, "error": "harness: role mismatch"}
    res = compare([SAKUJI_BASE], [pr], manifest={"schema": EXPECT_SCHEMA, "expected": [PKEY]})
    want_incomplete(res, "harness_error")


@case("changed from compare.mjs: a candidate-only scenario failure was a regression there and is incomplete here")
def _():
    pr = {**SAKUJI_PR, "ok": False, "error": "timeout"}
    res = compare([SAKUJI_BASE], [pr], manifest={"schema": EXPECT_SCHEMA, "expected": [PKEY]})
    want_incomplete(res, "pr_failed")
    assert "scenario_error" not in res.stdout


@case("parity: a failure on the base side is incomplete (base_failed), both sides both_failed")
def _():
    base = {**SAKUJI_BASE, "ok": False, "error": "boom"}
    want_incomplete(compare([base], [SAKUJI_PR], manifest={"schema": EXPECT_SCHEMA, "expected": [PKEY]}), "base_failed")
    pr = {**SAKUJI_PR, "ok": False, "error": "boom"}
    want_incomplete(compare([base], [pr], manifest={"schema": EXPECT_SCHEMA, "expected": [PKEY]}), "both_failed")


@case("parity: JavaScript rounding (toFixed) is reproduced for the rounded deltas")
def _():
    assert verify_compare.to_fixed(1.005, 2) == 1.0          # 1.005 is below 1.005 in binary
    assert verify_compare.to_fixed(0.5, 0) == 1
    assert verify_compare.to_fixed(2.5, 0) == 3              # JS rounds half up, Python's round() would give 2
    assert verify_compare.to_fixed(12 - 5.33, 2) == 6.67
    assert verify_compare.to_fixed(1 - 0.38, 3) == 0.62
    assert verify_compare.to_fixed(3.0, 2) == 3 and isinstance(verify_compare.to_fixed(3.0, 2), int)


# ---------------------------------------------------------------- plan, in throwaway git repositories

GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout.strip()


RUNNABLE = """\
schema = 1
[verify]
lookup = "scripts/lookup.sh"
up = "sh scripts/up.sh"
down = "scripts/down.sh --all"
scenarios = "docs/scenarios.md"
thresholds = "thresholds.json"
"""


def make_repo(contract=None, files=None, executables=("scripts/lookup.sh", "scripts/down.sh")) -> Path:
    repo = fresh("repo")
    git(repo, "init", "-q")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    tree = {"README.md": "x\n", "scripts/lookup.sh": "#!/bin/sh\n", "scripts/up.sh": "x\n", "scripts/down.sh": "#!/bin/sh\n",
            "docs/scenarios.md": "s\n", "thresholds.json": "{}\n"}
    tree.update(files or {})
    if contract is not None:
        tree[".plumb/project.toml"] = contract
    for rel, text in tree.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if rel in executables:
            path.chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def commit_all(repo: Path, message: str = "next") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def with_origin(repo: Path) -> None:
    bare = fresh("origin") / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env={**os.environ, **GIT_ENV})
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")


def trust(repo: Path) -> None:
    """Put the current HEAD on an origin branch, so it counts as a revision the repository accepted."""
    if not git(repo, "remote"):
        bare = fresh("origin") / "o.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env={**os.environ, **GIT_ENV})
        git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-f", "origin", f"HEAD:refs/heads/accepted-{git(repo, 'rev-parse', '--short', 'HEAD')}")
    git(repo, "fetch", "-q", "origin")


def plan(repo: Path, *args: str) -> Run:
    return run_cli(["plan", "--json", *args], cwd=repo, env=GIT_ENV)


def want_plan(res: Run, outcome: str, code: int) -> dict:
    assert res.out is not None, (res.stdout, res.stderr)
    assert res.out["outcome"] == outcome and res.code == code, (res.out["outcome"], res.code, res.out["message"])
    assert set(res.out) == {"outcome", "message", "contract_from", "keys"}, set(res.out)
    return res.out


@case("plan: runnable (exit 0) when all five keys are set and resolve; the key states say so")
def _():
    out = want_plan(plan(make_repo(RUNNABLE)), "runnable", 0)
    assert out["contract_from"] == "worktree"
    assert {k: v["state"] for k, v in out["keys"].items()} == {k: "resolves" for k in ("lookup", "up", "down", "scenarios", "thresholds")}
    assert out["keys"]["up"]["value"] == "sh scripts/up.sh"


@case("plan: absent (exit 4) with no contract file")
def _():
    out = want_plan(plan(make_repo(None)), "absent", 4)
    assert all(v == {"value": None, "state": "absent"} for v in out["keys"].values()) and len(out["keys"]) == 5


@case("plan: absent (exit 4) with a contract that has no [verify], and with an empty [verify]")
def _():
    want_plan(plan(make_repo("schema = 1\n[repo]\nbase_branch = \"main\"\n")), "absent", 4)
    want_plan(plan(make_repo("schema = 1\n[verify]\n")), "absent", 4)
    want_plan(plan(make_repo('schema = 1\n[verify]\nup = ""\n')), "absent", 4)


@case("plan: partial (exit 5) when some of the five keys are missing, and an empty value counts as missing")
def _():
    out = want_plan(plan(make_repo('schema = 1\n[verify]\nlookup = "scripts/lookup.sh"\nup = "sh scripts/up.sh"\n')), "partial", 5)
    assert out["keys"]["lookup"]["state"] == "set" and out["keys"]["down"]["state"] == "absent"
    assert "down" in out["message"] and "thresholds" in out["message"]
    no_thr = RUNNABLE.replace('thresholds = "thresholds.json"\n', "")
    want_plan(plan(make_repo(no_thr)), "partial", 5)
    want_plan(plan(make_repo(RUNNABLE.replace('down = "scripts/down.sh --all"', 'down = "  "'))), "partial", 5)


@case("plan: unresolved (exit 6) for a command off PATH, a script that is not executable, a missing thresholds file")
def _():
    out = want_plan(plan(make_repo(RUNNABLE.replace('"sh scripts/up.sh"', '"no-such-command-xyz --x"'))), "unresolved", 6)
    assert out["keys"]["up"]["state"] == "unresolved" and out["keys"]["lookup"]["state"] == "resolves", out["keys"]
    want_plan(plan(make_repo(RUNNABLE, executables=("scripts/down.sh",))), "unresolved", 6)       # lookup.sh is not +x
    want_plan(plan(make_repo(RUNNABLE.replace("thresholds.json", "nope.json"))), "unresolved", 6)
    out = want_plan(plan(make_repo(RUNNABLE.replace("docs/scenarios.md", "docs/missing.md"))), "unresolved", 6)
    assert out["keys"]["scenarios"]["state"] == "unresolved"


@case("plan: scenarios may be a command that resolves; a thresholds directory is not a file")
def _():
    want_plan(plan(make_repo(RUNNABLE.replace('"docs/scenarios.md"', '"scripts/down.sh --scenarios"'))), "runnable", 0)
    want_plan(plan(make_repo(RUNNABLE.replace('"docs/scenarios.md"', '"sh"'))), "runnable", 0)
    want_plan(plan(make_repo(RUNNABLE.replace('"thresholds.json"', '"docs"'))), "unresolved", 6)


@case("plan: invalid (exit 2) for TOML syntax, a wrong type, and a wrong schema; the message does not echo the file")
def _():
    out = want_plan(plan(make_repo("schema = 1\n[verify\nSECRET-TOKEN\n")), "invalid", 2)
    assert "SECRET-TOKEN" not in json.dumps(out) and "line" in out["message"]
    out = want_plan(plan(make_repo("schema = 1\n[verify]\nup = 3\n")), "invalid", 2)
    assert "verify.up" in out["message"]
    want_plan(plan(make_repo("schema = 2\n[verify]\n")), "invalid", 2)
    want_plan(plan(make_repo("[verify]\nup = \"x\"\n")), "invalid", 2)


@case("plan: unavailable (exit 3) when Python has no tomllib, for the worktree and for --base")
def _():
    repo = make_repo(RUNNABLE)
    trust(repo)
    saved, cwd = sys.modules.get("tomllib", ...), os.getcwd()
    sys.modules["tomllib"] = None            # `import tomllib` raises ImportError
    os.chdir(repo)
    try:
        for base in (None, "HEAD"):
            result = verify_compare.plan_for(base, None, False, cwd=str(repo))
            assert result["outcome"] == "unavailable" and "tomllib" in result["message"], result
            assert verify_compare.PLAN_EXIT["unavailable"] == 3
        # no file needs no parser: absent is still answered
        empty = make_repo(None)
        os.chdir(empty)
        assert verify_compare.plan_for(None, None, False, cwd=str(empty))["outcome"] == "absent"
    finally:
        os.chdir(cwd)
        if saved is ...:
            sys.modules.pop("tomllib", None)
        else:
            sys.modules["tomllib"] = saved


@case("plan --base reads the base commit's contract, not the worktree's (the base wins)")
def _():
    repo = make_repo(RUNNABLE)
    base = git(repo, "rev-parse", "HEAD")
    trust(repo)
    # The head rewrites the contract and the worktree differs again from the head.
    (repo / ".plumb/project.toml").write_text('schema = 1\n[verify]\nlookup = "evil.sh"\n')
    commit_all(repo, "head rewrites the contract")
    trust(repo)                                                                          # only to read it as a base below
    (repo / ".plumb/project.toml").write_text("schema = 1\n[verify\nbroken\n")
    out = want_plan(plan(repo, "--base", base), "runnable", 0)
    assert out["contract_from"] == base and out["keys"]["lookup"]["value"] == "scripts/lookup.sh"
    want_plan(plan(repo), "invalid", 2)                                                  # the worktree's own is broken
    head_only = git(repo, "rev-parse", "HEAD")
    out = want_plan(plan(repo, "--base", head_only), "partial", 5)
    assert out["contract_from"] == head_only and out["keys"]["lookup"]["value"] == "evil.sh"


@case("plan --base resolves paths in the base commit's tree, not in the worktree")
def _():
    repo = make_repo(RUNNABLE)
    base = git(repo, "rev-parse", "HEAD")
    trust(repo)
    # The worktree loses the thresholds file and an executable bit: the base still has both.
    (repo / "thresholds.json").unlink()
    (repo / "scripts/lookup.sh").chmod(0o644)
    want_plan(plan(repo, "--base", base), "runnable", 0)
    want_plan(plan(repo), "unresolved", 6)
    dotted = RUNNABLE.replace('"scripts/lookup.sh"', '"./scripts/lookup.sh"').replace('"thresholds.json"', '"./thresholds.json"')
    assert verify_compare.is_file("./thresholds.json", str(repo), base) and verify_compare.cmd_resolves("./scripts/lookup.sh", str(repo), base), dotted
    # A file only the worktree has does not make the base runnable.
    git(repo, "rm", "-q", "--cached", "thresholds.json")
    commit_all(repo, "drop thresholds")
    trust(repo)
    (repo / "thresholds.json").write_text("{}\n")
    out = want_plan(plan(repo, "--base", git(repo, "rev-parse", "HEAD")), "unresolved", 6)
    assert out["keys"]["thresholds"]["state"] == "unresolved", out


@case("plan --base: a base without a contract is absent even when the worktree has one; an unknown base is invalid")
def _():
    repo = make_repo(None)
    base = git(repo, "rev-parse", "HEAD")
    (repo / ".plumb").mkdir()
    (repo / ".plumb/project.toml").write_text(RUNNABLE)
    commit_all(repo, "add contract")
    trust(repo)
    want_plan(plan(repo, "--base", base), "absent", 4)
    want_plan(plan(repo), "runnable", 0)
    want_plan(plan(repo, "--base", "HEAD~0"), "runnable", 0)
    out = want_plan(plan(repo, "--base", "0123456789abcdef0123456789abcdef01234567"), "invalid", 2)
    assert "not a commit" in out["message"]
    want_usage(run_cli(["plan", "--base", "--json"], cwd=repo, env=GIT_ENV))
    notrepo = fresh("norepo")
    res = run_cli(["plan", "--json", "--base", "HEAD"], cwd=notrepo, env={**GIT_ENV, "GIT_CEILING_DIRECTORIES": str(ROOT)})
    want_plan(res, "invalid", 2)


@case("plan --base: a base no origin branch contains is untrusted_base (exit 8); an absolute path or a directory does not resolve in the base tree")
def _():
    repo = make_repo(RUNNABLE)
    out = want_plan(plan(repo, "--base", git(repo, "rev-parse", "HEAD")), "untrusted_base", 8)
    assert "origin" in out["message"], out
    absolute = RUNNABLE.replace('thresholds = "thresholds.json"', f'thresholds = "{repo}/thresholds.json"')
    (repo / ".plumb/project.toml").write_text(absolute)
    commit_all(repo, "absolute thresholds")
    trust(repo)
    out = want_plan(plan(repo, "--base", git(repo, "rev-parse", "HEAD")), "unresolved", 6)
    assert out["keys"]["thresholds"]["state"] == "unresolved", out
    want_plan(plan(repo), "runnable", 0)                                                 # the worktree may name an absolute path
    (repo / ".plumb/project.toml").write_text(RUNNABLE.replace('thresholds = "thresholds.json"', 'thresholds = "docs/"'))
    commit_all(repo, "a directory as thresholds")
    trust(repo)
    out = want_plan(plan(repo, "--base", git(repo, "rev-parse", "HEAD")), "unresolved", 6)
    assert out["keys"]["thresholds"]["state"] == "unresolved", out


@case("compare: a thresholds file with no rules is unusable input (exit 2), never no_diff")
def _():
    d = fresh("no-rules")
    row = {"feature": "f", "scenario": "s", "role": "r", "status": "ok", "repeat": 1, "console_errors": 0}
    (d / "b").write_text(json.dumps(row) + "\n")
    (d / "p").write_text(json.dumps({**row, "console_errors": 100}) + "\n")
    (d / "e").write_text(json.dumps({"schema": "verify-expect/1", "expected": ["f/s/r"]}))
    for doc in ({}, {"metrics": {}}):
        (d / "t").write_text(json.dumps(doc))
        res = run_cli(["compare", "--base", str(d / "b"), "--pr", str(d / "p"), "--thresholds", str(d / "t"), "--expect", str(d / "e")])
        assert res.code == 2 and "no rules" in res.stderr, (res.code, res.stderr)


@case("plan --head: a commit no origin branch contains is untrusted_head (exit 7)")
def _():
    repo = make_repo(RUNNABLE)
    with_origin(repo)
    pushed = git(repo, "rev-parse", "HEAD")
    (repo / "change.txt").write_text("local only\n")
    local = commit_all(repo, "local")
    base = pushed
    out = want_plan(plan(repo, "--base", base, "--head", local), "untrusted_head", 7)
    assert "origin" in out["message"] and out["contract_from"] == base
    out = want_plan(plan(repo, "--base", base, "--head", pushed), "runnable", 0)
    # a fork's pull head lives outside refs/remotes/origin
    git(repo, "update-ref", "refs/pull/7/head", local)
    want_plan(plan(repo, "--base", base, "--head", "refs/pull/7/head"), "untrusted_head", 7)
    want_plan(plan(repo, "--head", "0123456789abcdef0123456789abcdef01234567"), "untrusted_head", 7)


@case("plan --head: a commit on an origin branch other than main is trusted; a branch of another remote is not")
def _():
    repo = make_repo(RUNNABLE)
    with_origin(repo)
    git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "x.txt").write_text("x\n")
    sha = commit_all(repo, "x")
    want_plan(plan(repo, "--head", sha), "untrusted_head", 7)
    git(repo, "push", "-q", "origin", "feat/x")
    want_plan(plan(repo, "--head", sha), "runnable", 0)
    git(repo, "checkout", "-q", "-b", "other")
    (repo / "y.txt").write_text("y\n")
    other = commit_all(repo, "y")
    git(repo, "update-ref", "refs/remotes/fork/other", other)
    want_plan(plan(repo, "--head", other), "untrusted_head", 7)


@case("plan --allow-untrusted-head lets the contract's own outcome through")
def _():
    repo = make_repo(RUNNABLE)
    with_origin(repo)
    (repo / "change.txt").write_text("local only\n")
    local = commit_all(repo, "local")
    want_plan(plan(repo, "--head", local), "untrusted_head", 7)
    want_plan(plan(repo, "--head", local, "--allow-untrusted-head"), "runnable", 0)
    broken = make_repo('schema = 1\n[verify]\nlookup = "scripts/lookup.sh"\n')
    with_origin(broken)
    (broken / "z.txt").write_text("z\n")
    z = commit_all(broken, "z")
    want_plan(plan(broken, "--head", z, "--allow-untrusted-head"), "partial", 5)


@case("plan --head: an untrusted head outranks an absent contract (the fallback would run its code)")
def _():
    repo = make_repo(None)
    with_origin(repo)
    (repo / "change.txt").write_text("local\n")
    local = commit_all(repo, "local")
    want_plan(plan(repo, "--head", local), "untrusted_head", 7)
    want_plan(plan(repo, "--head", local, "--allow-untrusted-head"), "absent", 4)


@case("plan text form: one line per key, the outcome line last, the reason on stderr")
def _():
    repo = make_repo('schema = 1\n[verify]\nlookup = "scripts/lookup.sh"\n')
    res = run_cli(["plan"], cwd=repo, env=GIT_ENV)
    lines = res.stdout.splitlines()
    assert res.code == 5 and len(lines) == 6 and lines[-1] == "outcome: partial", res.stdout
    assert lines[0].split() == ["lookup", "set", "scripts/lookup.sh"] and lines[1].split() == ["up", "absent"], lines
    assert "partial" in res.stderr
    ok = run_cli(["plan"], cwd=make_repo(RUNNABLE), env=GIT_ENV)
    assert ok.code == 0 and ok.stdout.splitlines()[-1] == "outcome: runnable" and ok.stderr == ""


@case("plan: an unknown option or a stray argument exits 2")
def _():
    repo = make_repo(RUNNABLE)
    for args in (["--bogus"], ["extra"]):
        res = run_cli(["plan", *args], cwd=repo, env=GIT_ENV)
        assert res.code == 2 and res.stdout == "", (args, res.code, res.stdout)


@case("plan and plumb-project agree: a contract plumb-project calls invalid is invalid for plan")
def _():
    for text in ("schema = 1\n[verify]\nthresholds = 3\n", "schema = 1\n[rework]\nlookahead_days = 0\n[verify]\nup = \"sh\"\n"):
        repo = make_repo(text)
        project = subprocess.run([str(PLUGIN / "bin" / "plumb-project"), "--json"], cwd=repo, capture_output=True, text=True)
        assert project.returncode == 2, project.stdout
        want_plan(plan(repo), "invalid", 2)


@case("plumb-project reads verify.thresholds and calls a non-string invalid")
def _():
    repo = make_repo(RUNNABLE)
    done = subprocess.run([str(PLUGIN / "bin" / "plumb-project"), "verify.thresholds"], cwd=repo, capture_output=True, text=True)
    assert (done.returncode, done.stdout.strip(), done.stderr) == (0, "thresholds.json", ""), done


@case("plumb-doctor: verify.thresholds must be a file, the way commands must resolve")
def _():
    home = fresh("home")
    env = {**GIT_ENV, "HOME": str(home), "PLUMB_CONFIG": str(home / "config")}
    def contract_lines(repo):
        done = subprocess.run(["bash", str(PLUGIN / "scripts" / "doctor.sh")], cwd=repo, capture_output=True, text=True, env={**os.environ, **env})
        return [l for l in done.stdout.splitlines() if "verify." in l]
    lines = contract_lines(make_repo(RUNNABLE))
    assert any(l.startswith("  ok") and "verify.thresholds" in l for l in lines), lines
    lines = contract_lines(make_repo(RUNNABLE.replace("thresholds.json", "missing.json")))
    assert any(l.startswith("  NG") and "verify.thresholds" in l for l in lines), lines
    lines = contract_lines(make_repo(RUNNABLE.replace('"thresholds.json"', '"docs"')))
    assert any(l.startswith("  NG") and "verify.thresholds" in l for l in lines), lines


@case("no output ever names a pass as a result")
def _():
    assert len(OUTPUTS) > 100, len(OUTPUTS)
    text = "\n".join(OUTPUTS)
    assert not re.search(r"\bpass", text, re.IGNORECASE), re.search(r".{0,40}\bpass.{0,40}", text, re.IGNORECASE | re.DOTALL).group(0)


shutil.rmtree(ROOT, ignore_errors=True)
print()
if FAILED:
    print(f"{len(FAILED)} case(s) NG")
    sys.exit(1)
print("all ok")
