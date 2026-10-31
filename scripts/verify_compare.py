#!/usr/bin/env python3
"""plumb-verify: the deterministic half of verification (docs/verify-protocol.md).

    plumb-verify compare --base <rows> --pr <rows> --thresholds <file> --expect <manifest>
                         [--shot-diffs <rows>] [--out <file>]
    plumb-verify plan [--base <sha>] [--head <sha>] [--allow-untrusted-head] [--json]

`compare` is a port of SAKUJI's compare.mjs (scripts/feature-map/verify/compare.mjs, branch
feat/feature-verify) with the changes docs/verify-protocol.md lists: a `status` on every row, a
manifest of what the run committed to, a candidate-only scenario failure that is `incomplete` and not a
regression, and the output schema `verify-compare/1`. It decides from numbers and thresholds only.
The results are `regressed`, `incomplete` and `no_diff`; none of them is a success verdict.

`plan` reads the project contract's [verify] table and reports one outcome, so a caller can decide
whether verification can run at all. With --base the contract is read from that commit.

Standard library only. Messages name files, lines and keys, and never echo a file's contents.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCHEMA = "verify-compare/1"
EXPECT_SCHEMA = "verify-expect/1"
STATUSES = ("ok", "start_failed", "scenario_failed", "harness_error", "not_run")
EXIT = {"no_diff": 0, "regressed": 1, "incomplete": 3}
SHOT_RULE_NAME = "screenshot_diff_ratio"

# rule -> the numeric parameters it needs. A rule that is not here is an error, never skipped.
RULES = {
    "increase_abs": ("max",),
    "known_diff": ("min_abs", "max_ratio"),
    "list_new": ("max",),
    "increase_ratio_and_abs": ("min_abs", "max_ratio"),
    "growth_diff": ("max",),
    "abs_max": ("max",),
}

VERIFY_KEYS = ("lookup", "up", "down", "scenarios", "thresholds")
PLAN_EXIT = {"runnable": 0, "invalid": 2, "unavailable": 3, "absent": 4, "partial": 5,
             "unresolved": 6, "untrusted_head": 7, "untrusted_base": 8}


class Usage(Exception):
    """Bad arguments or malformed input. The message names the file and line; exit 2."""


# ------------------------------------------------------------------ reading input

def _reject_constant(name: str):
    raise ValueError(f"{name} is not JSON")


def loads(text: str):
    """json.loads that refuses NaN and Infinity, as JSON.parse does."""
    return json.loads(text, parse_constant=_reject_constant)


def read_file(path: str, what: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as error:
        reason = error.strerror if isinstance(error, OSError) and error.strerror else "not readable UTF-8"
        raise Usage(f"{what}: cannot read {path} ({reason})")


def is_num(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def num(value: object):
    """A finite number, or None. bool is not a number."""
    if not is_num(value):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def parse_rows(path: str, what: str) -> list:
    """JSON Lines: one object per line, blank lines skipped. Returns [(line number, row)]."""
    rows = []
    for number, line in enumerate(read_file(path, what).split("\n"), start=1):
        if not line.strip():
            continue
        try:
            row = loads(line)
        except ValueError as error:
            raise Usage(f"{path}:{number}: not valid JSON ({str(error)[:60]})")
        if not isinstance(row, dict):
            raise Usage(f"{path}:{number}: the row is not an object")
        rows.append((number, row))
    return rows


def check_observation(path: str, number: int, row: dict) -> None:
    for field in ("feature", "scenario", "role"):
        if not isinstance(row.get(field), str) or not row[field]:
            raise Usage(f"{path}:{number}: `{field}` must be a non-empty string")
    if "status" in row and row["status"] not in STATUSES:
        raise Usage(f"{path}:{number}: unknown status (expected one of {', '.join(STATUSES)})")
    if "status" not in row and not isinstance(row.get("ok"), bool):
        raise Usage(f"{path}:{number}: the row has neither `status` nor a boolean `ok`")


def load_observations(path: str, what: str) -> list:
    out = []
    for number, row in parse_rows(path, what):
        check_observation(path, number, row)
        out.append(row)
    return out


def load_shot_diffs(path: str) -> list:
    out = []
    for number, row in parse_rows(path, "--shot-diffs"):
        if not isinstance(row.get("key"), str) or not row["key"]:
            raise Usage(f"{path}:{number}: `key` must be a non-empty string")
        if "name" in row and not isinstance(row["name"], str):
            raise Usage(f"{path}:{number}: `name` must be a string")
        if "missing" in row and row["missing"] not in ("base", "pr"):
            raise Usage(f"{path}:{number}: `missing` must be \"base\" or \"pr\"")
        out.append(row)
    return out


def load_json_file(path: str, what: str) -> object:
    text = read_file(path, what)
    try:
        return loads(text)
    except json.JSONDecodeError as error:
        raise Usage(f"{path}:{error.lineno}: not valid JSON ({error.msg})")
    except ValueError as error:
        raise Usage(f"{path}: not valid JSON ({str(error)[:60]})")


def load_thresholds(path: str) -> dict:
    doc = load_json_file(path, "--thresholds")
    if not isinstance(doc, dict):
        raise Usage(f"{path}: the thresholds file must be a JSON object")
    metrics = doc.get("metrics", {})
    if not isinstance(metrics, dict):
        raise Usage(f"{path}: `metrics` must be an object")
    if not metrics:
        raise Usage(f"{path}: `metrics` holds no rules, so nothing could be compared")
    for name, rule in metrics.items():
        if not isinstance(rule, dict) or not isinstance(rule.get("rule"), str):
            raise Usage(f"{path}: metrics.{name}: `rule` must be a string")
        kind = rule["rule"]
        if kind not in RULES:
            raise Usage(f"{path}: metrics.{name}: unknown rule {kind!r} (known: {', '.join(RULES)})")
        for param in RULES[kind]:
            if num(rule.get(param)) is None:
                raise Usage(f"{path}: metrics.{name}: `{param}` must be a finite number for rule {kind}")
        if "field" in rule and not isinstance(rule["field"], str):
            raise Usage(f"{path}: metrics.{name}: `field` must be a string")
    if "min_repeat_for_growth" in doc and num(doc["min_repeat_for_growth"]) is None:
        raise Usage(f"{path}: `min_repeat_for_growth` must be a number")
    return doc


def load_manifest(path: str) -> dict:
    doc = load_json_file(path, "--expect")
    if not isinstance(doc, dict):
        raise Usage(f"{path}: the manifest must be a JSON object")
    if doc.get("schema") != EXPECT_SCHEMA:
        raise Usage(f"{path}: `schema` must be {EXPECT_SCHEMA!r}")

    def strings(field: str) -> list:
        value = doc.get(field, [])
        if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
            raise Usage(f"{path}: `{field}` must be an array of non-empty strings")
        return value

    if "expected" not in doc:
        raise Usage(f"{path}: `expected` is required")
    expected = strings("expected")
    unmapped = strings("unmapped")
    shots = doc.get("shots", {})
    if not isinstance(shots, dict):
        raise Usage(f"{path}: `shots` must be an object of key to array of names")
    for key, names in shots.items():
        if not isinstance(names, list) or not all(isinstance(x, str) and x for x in names):
            raise Usage(f"{path}: shots.{key}: must be an array of non-empty strings")
    not_run = doc.get("not_run", [])
    if not isinstance(not_run, list):
        raise Usage(f"{path}: `not_run` must be an array of {{key, reason}}")
    for index, entry in enumerate(not_run):
        if (not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or not entry["key"]
                or not isinstance(entry.get("reason"), str)):
            raise Usage(f"{path}: not_run[{index}]: expected {{\"key\": string, \"reason\": string}}")
    return {"expected": expected, "shots": shots, "unmapped": unmapped, "not_run": not_run}


# ------------------------------------------------------------------ the comparator

def key_of(row: dict) -> str:
    return f"{row['feature']}/{row['scenario']}/{row['role']}"


def last_by_key(rows: list) -> dict:
    """The last row per key wins."""
    out = {}
    for row in rows:
        out[key_of(row)] = row
    return out


def status_of(row: dict) -> str:
    """The row's status; a row without one derives it (the legacy rule, docs/verify-protocol.md)."""
    if "status" in row:
        return row["status"]
    if row["ok"] is True:
        return "ok"
    error = row.get("error")
    if isinstance(error, str) and error.startswith("harness:"):
        return "harness_error"
    return "scenario_failed"


def first(*values):
    """JS `a ?? b ?? ...`: the first value that is not None."""
    for value in values:
        if value is not None:
            return value
    return None


def to_fixed(value: float, digits: int) -> float:
    """+(value).toFixed(digits): the exact binary value rounded half away from zero."""
    try:
        out = float(Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))
    except (InvalidOperation, OverflowError):
        return value
    return int(out) if out.is_integer() else out


def tidy(value):
    """Print an integral float as an integer, as JSON written by JavaScript does."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    return value


def size_of(value):
    """A list is its length (duplicates count); a number is itself. Anything else is not measured."""
    if isinstance(value, list):
        return len(value) if all(isinstance(x, str) for x in value) else None
    return num(value)


def added_entries(base_list, pr_list) -> list:
    """The entries the pr has more of than the base (multiset difference), 'Nx entry' for several."""
    if not isinstance(base_list, list) or not isinstance(pr_list, list):
        return []
    have = {}
    for item in base_list:
        have[item] = have.get(item, 0) + 1
    want = {}
    for item in pr_list:
        want[item] = want.get(item, 0) + 1
    out = []
    for item, count in want.items():
        extra = count - have.get(item, 0)
        if extra > 0:
            out.append(f"{extra}x {item}" if extra > 1 else item)
    return out


def number_map(value):
    """A map of id to finite number, or None when it is not one."""
    if not isinstance(value, dict):
        return None
    if any(num(v) is None for v in value.values()):
        return None
    return value


def compare_rows(base_rows: list, pr_rows: list, thresholds: dict, manifest: dict, shot_diffs: list) -> dict:
    base = last_by_key(base_rows)
    pr = last_by_key(pr_rows)
    keys = sorted(set(base) | set(pr))
    metrics = thresholds.get("metrics") or {}
    min_repeat = first(thresholds.get("min_repeat_for_growth"), 3)

    regressions: list = []
    notes: list = []
    compared: list = []
    only_in_base: list = []
    only_in_pr: list = []
    incomplete: list = []
    harness_error: list = []
    start_failed: list = []
    shots_only_in_base: list = []
    shots_only_in_pr: list = []
    shots_without_diff: list = []
    shots_not_measured: list = []

    def note(key, kind, detail):
        notes.append({"key": key, "kind": kind, "detail": detail})

    def mark(key):
        if key not in incomplete:
            incomplete.append(key)

    def reg(key, metric, b, p, delta, rule, **extra):
        regressions.append({"key": key, "metric": metric, "base": tidy(b), "pr": tidy(p),
                            "delta": tidy(delta), "threshold": dict(rule), **extra})

    for key in keys:
        b = base.get(key)
        p = pr.get(key)
        if b is None:
            only_in_pr.append(key)
            continue
        if p is None:
            only_in_base.append(key)
            continue
        compared.append(key)
        sides = (("base", b), ("pr", p))

        # A restore that did not return the state, and a failed cleanup, leave the environment dirty.
        # Reported even when the scenario failed, and the numbers below are still compared.
        for side, row in sides:
            check = row.get("restore_check")
            if isinstance(check, dict) and check.get("ok") is False:
                mark(key)
                extra = f" ({check['error']})" if check.get("error") else ""
                note(key, "restore_failed", f"{side}: the read-back after the restore differed from the original{extra}; rebuild the environment before continuing")
        for side, row in sides:
            if row.get("cleanup_error"):
                mark(key)
                note(key, "cleanup_failed", f"{side}: cleanup failed ({row['cleanup_error']}); rebuild the environment before continuing")

        # A row that did not run its scenario to the end has no numbers worth comparing.
        status = {side: status_of(row) for side, row in sides}
        if any(s != "ok" for s in status.values()):
            mark(key)
            for kind in ("start_failed", "not_run", "harness_error"):
                hit = [f"{side}: {sd_row.get('error') or kind}" if kind == "harness_error" else side
                       for (side, sd_row) in sides if status[side] == kind]
                if not hit:
                    continue
                if kind == "start_failed":
                    start_failed.append(key)
                if kind == "harness_error":
                    harness_error.append(key)
                text = {"start_failed": "the environment did not start",
                        "not_run": "the scenario was not run",
                        "harness_error": "the verification environment failed, not the product"}[kind]
                note(key, kind, f"{text} ({' / '.join(hit)})")
            failed = [side for side in ("base", "pr") if status[side] == "scenario_failed"]
            errors = {side: row.get("error") or "?" for side, row in sides}
            if len(failed) == 2:
                note(key, "both_failed", f"neither side ran the scenario to the end (base: {errors['base']} / pr: {errors['pr']}); the procedure may be stale or the environment broken")
            elif failed == ["base"]:
                note(key, "base_failed", f"base did not run the scenario to the end ({errors['base']}); there is no comparison")
            elif failed == ["pr"]:
                note(key, "pr_failed", f"base ran the scenario but pr did not ({errors['pr']}); a product difference or a stale procedure, to be told apart on the screen. Not counted as a regression")
            continue

        for metric, rule in metrics.items():
            kind = rule["rule"]
            if kind == "increase_abs":
                field = rule.get("field") or metric
                bv = num(first(b.get(field), b.get(metric)))
                pv = num(first(p.get(field), p.get(metric)))
                if bv is None or pv is None:
                    mark(key)
                    note(key, "not_measured", f"{metric} was not measured")
                    continue
                if pv - bv > rule["max"]:
                    reg(key, metric, bv, pv, pv - bv, rule)
            elif kind == "known_diff":
                bk = number_map(b.get(metric))
                pk = number_map(p.get(metric))
                if bk is None or pk is None:
                    mark(key)
                    note(key, "not_measured", f"{metric} was not measured")
                    continue
                for ident in dict.fromkeys([*bk, *pk]):
                    bv = bk.get(ident, 0)
                    pv = pk.get(ident, 0)
                    if pv - bv > rule["min_abs"] and pv > bv * rule["max_ratio"]:
                        reg(key, f"{metric}.{ident}", bv, pv, pv - bv, rule)
            elif kind == "list_new":
                bv = size_of(b.get(metric))
                pv = size_of(p.get(metric))
                if bv is None or pv is None:
                    mark(key)
                    note(key, "not_measured", f"{metric} was not measured")
                    continue
                if pv - bv > rule["max"]:
                    reg(key, metric, bv, pv, pv - bv, rule, added=added_entries(b.get(metric), p.get(metric))[:10])
            elif kind == "increase_ratio_and_abs":
                bv = num(b.get(metric))
                pv = num(p.get(metric))
                if bv is None or pv is None:
                    mark(key)
                    note(key, "not_measured", f"{metric} was not measured")
                    continue
                if pv - bv > rule["min_abs"] and pv > bv * rule["max_ratio"]:
                    reg(key, metric, bv, pv, to_fixed(pv - bv, 2), rule)
            elif kind == "growth_diff":
                field = metric[len("growth."):] if metric.startswith("growth.") else metric
                rb = 1 if b.get("repeat") is None else num(b["repeat"])
                rp = 1 if p.get("repeat") is None else num(p["repeat"])
                if rb is None or rp is None:
                    mark(key)
                    note(key, "not_measured", f"{metric} was not measured (repeat is not a number)")
                    continue
                if rb < min_repeat or rp < min_repeat:
                    mark(key)
                    if not any(n["key"] == key and n["kind"] == "repeat_too_small" for n in notes):
                        note(key, "repeat_too_small", f"fewer than {tidy(min_repeat)} repeats (base {tidy(rb)} / pr {tidy(rp)}); growth metrics were not compared")
                    continue
                gb = b.get("growth_per_iter")
                gp = p.get("growth_per_iter")
                bv = num(gb.get(field)) if isinstance(gb, dict) else None
                pv = num(gp.get(field)) if isinstance(gp, dict) else None
                if bv is None or pv is None:
                    mark(key)
                    note(key, "not_measured", f"{metric} was not measured")
                    continue
                if pv - bv > rule["max"]:
                    reg(key, metric, bv, pv, to_fixed(pv - bv, 3), rule, repeat={"base": tidy(rb), "pr": tidy(rp)})
            # abs_max applies to shot-diff rows only; see below.

        # Information, not a regression: write requests that only the pr makes more of.
        bw = b.get("writes") if isinstance(b.get("writes"), dict) else {}
        pw = p.get("writes") if isinstance(p.get("writes"), dict) else {}
        added = [k for k in pw if (num(pw[k]) or 0) > (num(bw.get(k)) or 0)]
        if added:
            note(key, "new_writes", f"write requests that the pr makes more of: {', '.join(added[:8])}")

    # Screenshots. Each expected (key, name) needs a shot-diff row; a row says it differs or that a side lacks it.
    shot_name = SHOT_RULE_NAME if SHOT_RULE_NAME in metrics and metrics[SHOT_RULE_NAME]["rule"] == "abs_max" else next(
        (m for m, r in metrics.items() if r["rule"] == "abs_max"), None)
    shot_rule = metrics.get(shot_name) if shot_name else None
    shots = {}
    for row in shot_diffs:
        shots[(row["key"], row.get("name"))] = row
    for key, names in manifest["shots"].items():
        for name in dict.fromkeys(names):
            if (key, name) not in shots:
                label = f"{key}#{name}"
                shots_without_diff.append(label)
                note(key, "shot_no_diff", f"screenshot {name} was expected but there is no diff row; the screen was not compared")
    for (key, name), row in shots.items():
        label = f"{key}#{name if name is not None else '?'}"
        shown = name if name is not None else "?"
        if row.get("missing") in ("base", "pr"):
            lacking = row["missing"]
            (shots_only_in_base if lacking == "pr" else shots_only_in_pr).append(label)
            note(key, "shot_missing", f"screenshot {shown} is missing on {lacking}; the screen was not compared")
            continue
        ratio = num(row.get("ratio"))
        if ratio is None or shot_rule is None:
            shots_not_measured.append(label)
            why = "has no finite ratio" if ratio is None else "has no abs_max rule in the thresholds"
            note(key, "not_measured", f"screenshot {shown} {why}")
            continue
        if ratio > shot_rule["max"]:
            reg(key, shot_name, 0, ratio, to_fixed(ratio, 4), shot_rule, shot=name)

    # The manifest: what the run committed to.
    expected = list(dict.fromkeys(manifest["expected"]))
    no_rows = [k for k in expected if k not in base and k not in pr]
    for k in no_rows:
        note(k, "no_rows", "expected, but there is no row on either side")
    for k in only_in_base:
        note(k, "only_in_base", "there is a base row and no pr row")
    for k in only_in_pr:
        note(k, "only_in_pr", "there is a pr row and no base row")
    unmapped = list(dict.fromkeys(manifest["unmapped"]))
    for path in unmapped:
        note(None, "unmapped", f"no feature owns {path}; it was not verified")
    not_run_scenarios = [{"key": e["key"], "reason": e["reason"]} for e in manifest["not_run"]]
    for e in not_run_scenarios:
        note(e["key"], "not_run_scenario", f"selected but not run: {e['reason'] or 'no reason given'}")
    if not compared:
        note(None, "nothing_compared", "no key has a row on both sides, so nothing was compared")

    causes = [only_in_base, only_in_pr, incomplete, no_rows, shots_only_in_base, shots_only_in_pr,
              shots_without_diff, shots_not_measured, unmapped, not_run_scenarios]
    is_incomplete = any(causes) or not compared
    counts = (f"{len(only_in_base)} only in base, {len(only_in_pr)} only in pr, {len(incomplete)} not comparable, "
              f"{len(no_rows)} with no rows, {len(shots_only_in_base) + len(shots_only_in_pr) + len(shots_without_diff) + len(shots_not_measured)} screenshots, "
              f"{len(unmapped)} unmapped, {len(not_run_scenarios)} not run")
    if regressions:
        result = "regressed"
        summary = f"regressed: {len(regressions)} regressions in {len({r['key'] for r in regressions})} rows"
        if is_incomplete:
            summary += f"; also not compared ({counts})"
    elif is_incomplete:
        result = "incomplete"
        summary = f"incomplete: {counts}" if compared else f"incomplete: nothing was compared ({counts})"
    else:
        result = "no_diff"
        summary = (f"no_diff: no regression found in {len(compared)} compared rows. "
                   "This says nothing about screens, roles and scenarios that were not compared")

    return {
        "schema": SCHEMA,
        "result": result,
        "summary": summary,
        "thresholds": {"version": thresholds.get("version"), "status": thresholds.get("status")},
        "compared": compared,
        "regressions": regressions,
        "notes": notes,
        "missing": {
            "no_rows": no_rows,
            "only_in_base": only_in_base,
            "only_in_pr": only_in_pr,
            "incomplete": incomplete,
            "start_failed": start_failed,
            "harness_error": harness_error,
            "shots_only_in_base": shots_only_in_base,
            "shots_only_in_pr": shots_only_in_pr,
            "shots_without_diff": shots_without_diff,
            "shots_not_measured": shots_not_measured,
            "unmapped": unmapped,
            "not_run_scenarios": not_run_scenarios,
        },
    }


class Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse exits 2 on its own; keep the message in plumb's shape
        print(f"plumb-verify: usage: {message} (see --help)", file=sys.stderr)
        sys.exit(2)


def cmd_compare(argv: list) -> int:
    parser = Parser(prog="plumb-verify compare", allow_abbrev=False,
                    description="Compare base and pr observation rows. Exit 0 no_diff, 1 regressed, 3 incomplete, 2 usage or malformed input.")
    parser.add_argument("--base", required=True, help="observation rows (JSON Lines) from the base side")
    parser.add_argument("--pr", required=True, help="observation rows (JSON Lines) from the pr side")
    parser.add_argument("--thresholds", required=True, help="the thresholds file (JSON)")
    parser.add_argument("--expect", required=True, help="the manifest of what the run committed to (JSON)")
    parser.add_argument("--shot-diffs", help="screenshot diff rows (JSON Lines)")
    parser.add_argument("--out", help="also write the result to this file")
    args = parser.parse_args(argv)
    try:
        thresholds = load_thresholds(args.thresholds)
        manifest = load_manifest(args.expect)
        base_rows = load_observations(args.base, "--base")
        pr_rows = load_observations(args.pr, "--pr")
        shot_diffs = load_shot_diffs(args.shot_diffs) if args.shot_diffs else []
    except Usage as error:
        print(f"plumb-verify: {error}", file=sys.stderr)
        return 2
    out = compare_rows(base_rows, pr_rows, thresholds, manifest, shot_diffs)
    text = json.dumps(out, indent=1, ensure_ascii=False)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text + "\n")
        except OSError as error:
            print(f"plumb-verify: cannot write {args.out} ({error.strerror})", file=sys.stderr)
            return 2
    print(text)
    return EXIT[out["result"]]


# ------------------------------------------------------------------ preflight

def git(args: list, cwd: str | None = None, text: bool = True):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=text)
    except OSError:
        return None


def load_project_module():
    """scripts/plumb-project.py has a hyphen, so it is loaded by path."""
    spec = importlib.util.spec_from_file_location("plumb_project", HERE / "plumb-project.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree_mode(path: str, top: str, commit: str | None) -> str | None:
    """The git mode of a relative path in `commit` ("100644", "100755", ...), or with no commit, of
    the file on disk ("100755" when executable). None when there is no such file."""
    if commit is None:
        full = os.path.join(top, path)
        if not os.path.isfile(full):
            return None
        return "100755" if os.access(full, os.X_OK) else "100644"
    path = os.path.normpath(path)                            # git lists `./x` as `x`
    listed = git(["ls-tree", "-z", commit, "--", path], top)
    if listed is None or listed.returncode != 0:
        return None
    for entry in listed.stdout.split("\0"):
        meta, _, name = entry.partition("\t")
        if name == path and meta.split()[1:2] == ["blob"]:   # a directory lists its children instead
            return meta.split()[0]
    return None


def cmd_resolves(command: str, top: str, commit: str | None = None) -> bool:
    """doctor's cmd_resolves: a first word with a / is a path (relative to the top level, read from
    `commit` when one is given) to an executable file; otherwise it is on PATH."""
    words = command.split()
    if not words:
        return False
    word = words[0]
    if "/" in word:
        if os.path.isabs(word):   # outside the tree: with a base commit it would escape it
            return commit is None and os.path.isfile(word) and os.access(word, os.X_OK)
        return tree_mode(word, top, commit) == "100755"
    return shutil.which(word) is not None


def is_file(value: str, top: str, commit: str | None = None) -> bool:
    if os.path.isabs(value):   # outside the tree: with a base commit it would escape it
        return commit is None and os.path.isfile(value)
    return tree_mode(value, top, commit) is not None


def head_trust(head: str, cwd: str | None, side: str = "head") -> tuple:
    """(trusted, message). A revision is trusted when an origin branch already contains it."""
    done = git(["rev-parse", "--verify", "--quiet", f"{head}^{{commit}}"], cwd)
    if done is None or done.returncode != 0:
        return False, f"{side} {head} is not a commit in this repository"
    sha = done.stdout.strip()
    found = git(["for-each-ref", "--format=%(refname)", "--contains", sha, "refs/remotes/origin/"], cwd)
    if found is None or found.returncode != 0:
        return False, "cannot ask git which origin branches contain the head"
    if not found.stdout.strip():
        if side == "base":
            return False, (f"base {sha[:12]} is not contained in any refs/remotes/origin branch, so its "
                           "contract is not one the repository has accepted")
        return False, (f"head {sha[:12]} is not contained in any refs/remotes/origin branch "
                       "(a fork's pull request head is not); the owner can allow it with --allow-untrusted-head")
    return True, ""


def plan_for(base: str | None, head: str | None, allow_untrusted_head: bool, cwd: str | None = None) -> dict:
    """The preflight. Returns {"outcome", "message", "contract_from", "keys", "warnings"}.

    A head that no origin branch contains outranks every contract outcome: nothing may start it, and
    even the no-contract fallback runs the repository's own code.
    """
    result = contract_plan(base, cwd)
    if base is not None and result["outcome"] != "invalid":
        trusted, message = head_trust(base, cwd, side="base")
        if not trusted:
            result["outcome"], result["message"] = "untrusted_base", message
            return result
    if head is not None and not allow_untrusted_head:
        trusted, message = head_trust(head, cwd)
        if not trusted:
            result["outcome"], result["message"] = "untrusted_head", message
    return result


def contract_plan(base: str | None, cwd: str | None) -> dict:
    """The outcome the contract alone gives."""
    result = {"outcome": "invalid", "message": "", "contract_from": "worktree", "keys": {}, "warnings": []}

    def finish(outcome: str, message: str) -> dict:
        result["outcome"], result["message"] = outcome, message
        return result

    top_run = git(["rev-parse", "--show-toplevel"], cwd)
    top = top_run.stdout.strip() if top_run is not None and top_run.returncode == 0 else None

    # Read the contract's bytes: from the base commit, or from the worktree.
    project = load_project_module()
    raw: bytes | None = None
    if base is not None:
        result["contract_from"] = base
        if top is None:
            return finish("invalid", "not inside a git repository, so the base commit cannot be read")
        resolved = git(["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"], cwd)
        if resolved is None or resolved.returncode != 0:
            return finish("invalid", f"base {base} is not a commit in this repository")
        sha = resolved.stdout.strip()
        result["contract_from"] = sha
        exists = git(["cat-file", "-e", f"{sha}:.plumb/project.toml"], cwd)
        if exists is not None and exists.returncode == 0:
            blob = git(["cat-file", "blob", f"{sha}:.plumb/project.toml"], cwd, text=False)
            if blob is None or blob.returncode != 0:
                return finish("invalid", f"cannot read .plumb/project.toml at {sha[:12]}")
            raw = blob.stdout
    else:
        path, problem = project.contract_path()
        if problem:
            return finish("invalid", f"{project.FILE_LABEL}: {problem}")
        if os.path.lexists(path):
            try:
                with open(path, "rb") as handle:
                    raw = handle.read()
            except OSError:
                return finish("invalid", f"{project.FILE_LABEL}: cannot read the file")

    if raw is None:
        result["keys"] = {name: {"value": None, "state": "absent"} for name in VERIFY_KEYS}
        return finish("absent", "no contract file, so no [verify] contract")

    outcome, doc, message, warnings = project.evaluate(raw)
    result["warnings"] = warnings
    if outcome != "set":
        return finish(outcome, message)

    table = doc.get("verify") if isinstance(doc.get("verify"), dict) else {}
    values = {}
    for name in VERIFY_KEYS:
        value = table.get(name)
        values[name] = value.strip() if isinstance(value, str) and value.strip() else None
    missing = [name for name in VERIFY_KEYS if values[name] is None]
    if len(missing) == len(VERIFY_KEYS):
        result["keys"] = {name: {"value": None, "state": "absent"} for name in VERIFY_KEYS}
        return finish("absent", "the contract has no [verify] keys")
    if missing:
        result["keys"] = {name: ({"value": None, "state": "absent"} if values[name] is None
                                 else {"value": values[name], "state": "set"}) for name in VERIFY_KEYS}
        return finish("partial", f"[verify] is missing: {', '.join(missing)}")

    # Paths resolve in the tree the commands will run from: the base commit when there is one.
    where = top or os.getcwd()
    commit = result["contract_from"] if base is not None else None
    unresolved = []
    for name in VERIFY_KEYS:
        value = values[name]
        if name == "thresholds":
            good = is_file(value, where, commit)
        elif name == "scenarios":
            good = is_file(value, where, commit) or cmd_resolves(value, where, commit)
        else:
            good = cmd_resolves(value, where, commit)
        result["keys"][name] = {"value": value, "state": "resolves" if good else "unresolved"}
        if not good:
            unresolved.append(name)
    if unresolved:
        return finish("unresolved", f"does not resolve: {', '.join(unresolved)}")
    return finish("runnable", "lookup, up, down, scenarios and thresholds are set and resolve")


def cmd_plan(argv: list) -> int:
    parser = Parser(prog="plumb-verify plan", allow_abbrev=False,
                    description="Report whether the project contract can drive verification. Exit 0 runnable, 2 invalid, "
                                "3 unavailable, 4 absent, 5 partial, 6 unresolved, 7 untrusted_head, 8 untrusted_base.")
    parser.add_argument("--base", help="read the contract from this commit (the trusted one)")
    parser.add_argument("--head", help="the commit that will be started; it must be in an origin branch")
    parser.add_argument("--allow-untrusted-head", action="store_true", help="the owner accepts a head that no origin branch contains")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args(argv)
    for flag, value in (("--base", args.base), ("--head", args.head)):
        if value is not None and (not value or value.startswith("-")):
            parser.error(f"{flag} needs a commit")
    result = plan_for(args.base, args.head, args.allow_untrusted_head)
    for name in result["warnings"]:
        print(f"plumb-verify: warning: unknown key {name}", file=sys.stderr)
    if args.json:
        print(json.dumps({k: result[k] for k in ("outcome", "message", "contract_from", "keys")}, ensure_ascii=False))
    else:
        for name, info in result["keys"].items():
            print(f"{name:<11} {info['state']:<10} {info['value'] if info['value'] is not None else ''}".rstrip())
        if result["outcome"] != "runnable":
            print(f"plumb-verify: {result['outcome']}: {result['message']}", file=sys.stderr)
        print(f"outcome: {result['outcome']}")
    return PLAN_EXIT[result["outcome"]]


USAGE = """usage: plumb-verify compare --base <rows> --pr <rows> --thresholds <file> --expect <manifest>
                            [--shot-diffs <rows>] [--out <file>]
       plumb-verify plan [--base <sha>] [--head <sha>] [--allow-untrusted-head] [--json]

compare  base against pr, deterministic. Results: regressed (exit 1), incomplete (3), no_diff (0).
         No result is a success verdict. Bad arguments or malformed input exit 2 with the file and line.
plan     whether the project contract can drive verification: runnable 0, invalid 2,
         unavailable 3, absent 4, partial 5, unresolved 6, untrusted_head 7, untrusted_base 8.

Both are described in docs/verify-protocol.md.
"""


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        sys.stdout.write(USAGE)
        return 0 if argv else 2
    if argv[0] == "compare":
        return cmd_compare(argv[1:])
    if argv[0] == "plan":
        return cmd_plan(argv[1:])
    print(f"plumb-verify: usage: unknown command {argv[0]} (see --help)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
