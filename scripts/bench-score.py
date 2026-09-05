#!/usr/bin/env python3
"""Score review verdicts against a pruned benchmark corpus."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from statistics import median
from typing import Any, Iterable


LOCATION = re.compile(r"`([^`\r\n]+?):([0-9]+)(?:-([0-9]+))?`")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$")
TABLE_SEPARATOR = re.compile(r"^:?-{3,}:?$")
FREE_FORM_SEVERITY = re.compile(r"\b(?:block|fix)\b")
FREE_FORM_NOTE = re.compile(r"\bnote\b")
NUMBERED_FINDING = re.compile(r"^f(?:[- ]?\d+)\b")
NUMBERED_NOTE = re.compile(r"^n(?:[- ]?\d+)\b")
WHERE_LINE = re.compile(
    r"^\s*(?:(?:[-*+])\s+)?(?:\|\s*)?(?:\*\*|__)?where(?=(?:\*\*|__)|\W|$)"
)
TOKEN_ALIASES = {
    "input": ("input", "input_tokens"),
    "cache_read": ("cache_read", "cache_read_tokens", "cache_read_input_tokens"),
    "cache_creation": ("cache_creation", "cache_creation_tokens", "cache_creation_input_tokens"),
    "output": ("output", "output_tokens"),
}


class ScoreError(Exception):
    """A user-facing scoring failure."""


def locations(value: str) -> list[dict[str, Any]]:
    parsed = []
    for match in LOCATION.finditer(value):
        start = int(match.group(2))
        end = int(match.group(3)) if match.group(3) else start
        parsed.append({"file": match.group(1), "lines": [min(start, end), max(start, end)]})
    return parsed


def first_cell_locations(cells: list[str]) -> list[dict[str, Any]]:
    for cell in cells:
        parsed = locations(cell)
        if parsed:
            return parsed
    return []


def heading_text(line: str) -> str | None:
    match = HEADING.match(line)
    if match is None:
        return None
    return match.group(1).casefold().strip()


def table_cells(line: str) -> list[str] | None:
    if not line.lstrip().startswith("|"):
        return None
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table_separator(cells: list[str] | None) -> bool:
    return cells is not None and bool(cells) and all(
        TABLE_SEPARATOR.match(cell.replace(" ", "")) for cell in cells
    )


def finding_heading(text: str | None) -> bool:
    return text is not None and (
        FREE_FORM_SEVERITY.search(text) is not None
        or text.startswith(("blockers", "fix before merge", "findings"))
    )


def note_heading(text: str | None) -> bool:
    return text is not None and (
        FREE_FORM_NOTE.search(text) is not None or text.startswith("recorded only")
    )


def location_key(location: dict[str, Any]) -> tuple[str, int, int]:
    return location["file"], location["lines"][0], location["lines"][1]


def deduplicate_findings(findings: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    deduplicated: list[list[dict[str, Any]]] = []
    location_sets: list[set[tuple[str, int, int]]] = []
    for finding in findings:
        unique = []
        keys: set[tuple[str, int, int]] = set()
        for location in finding:
            key = location_key(location)
            if key not in keys:
                unique.append(location)
                keys.add(key)

        duplicates = [
            index for index, existing in enumerate(location_sets) if keys and keys & existing
        ]
        if not duplicates:
            deduplicated.append(unique)
            location_sets.append(keys)
            continue

        first = duplicates[0]
        merged = deduplicated[first]
        merged_keys = location_sets[first]
        for index in duplicates[1:]:
            for location in deduplicated[index]:
                key = location_key(location)
                if key not in merged_keys:
                    merged.append(location)
                    merged_keys.add(key)
        for location in unique:
            key = location_key(location)
            if key not in merged_keys:
                merged.append(location)
                merged_keys.add(key)
        for index in reversed(duplicates[1:]):
            del deduplicated[index]
            del location_sets[index]
    return deduplicated


def parse_verdict(text: str, include_note: bool = False) -> list[list[dict[str, Any]]]:
    findings: list[list[dict[str, Any]]] = []
    nearest_heading = None
    table_heading = None
    where_column: int | None = None
    table_without_where = False
    free_form_finding: list[dict[str, Any]] | None = None
    free_form_where_seen = False
    note_section = False
    lines = text.splitlines()
    has_english_table_heading = any(
        heading is not None and heading.startswith(("blockers", "fix before merge"))
        for heading in (heading_text(line) for line in lines)
    )
    for index, line in enumerate(lines):
        heading = heading_text(line)
        if heading is not None:
            nearest_heading = heading
            table_heading, where_column, table_without_where = None, None, False
            free_form_finding = None
            free_form_where_seen = False
            template_section = heading.startswith(
                ("blockers", "fix before merge", "recorded only")
            )
            note_section = heading.startswith("recorded only")
            if (
                not template_section
                and (
                    FREE_FORM_SEVERITY.search(heading)
                    or NUMBERED_FINDING.match(heading)
                    or (include_note and (FREE_FORM_NOTE.search(heading) or NUMBERED_NOTE.match(heading)))
                )
            ):
                findings.append([])
                free_form_finding = findings[-1]
            continue

        cells = table_cells(line)
        next_cells = table_cells(lines[index + 1]) if index + 1 < len(lines) else None
        if cells is not None:
            folded_cells = [cell.casefold() for cell in cells]
            if table_separator(next_cells):
                table_heading, where_column, table_without_where = None, None, False
                if "where" in folded_cells:
                    if (
                        free_form_finding is not None
                        and not free_form_finding
                        and not free_form_where_seen
                    ):
                        findings.pop()
                        free_form_finding = None
                    table_heading = nearest_heading
                    where_column = folded_cells.index("where")
                elif not has_english_table_heading and any(folded_cells) and (
                    finding_heading(nearest_heading)
                    or (include_note and note_heading(nearest_heading))
                ):
                    if (
                        free_form_finding is not None
                        and not free_form_finding
                        and not free_form_where_seen
                    ):
                        findings.pop()
                        free_form_finding = None
                    table_heading = nearest_heading
                    table_without_where = True
                continue
            if where_column is not None or table_without_where:
                if table_separator(cells):
                    continue
                row_is_note = note_heading(table_heading)
                row_is_finding = finding_heading(table_heading) or any(
                    FREE_FORM_SEVERITY.search(cell.casefold()) for cell in cells
                )
                if include_note or (row_is_finding and not row_is_note):
                    if where_column is None:
                        findings.append(first_cell_locations(cells))
                    else:
                        findings.append(
                            locations(cells[where_column]) if where_column < len(cells) else []
                        )
                continue
        else:
            table_heading, where_column, table_without_where = None, None, False

        if free_form_finding is not None and not free_form_where_seen and WHERE_LINE.match(line.casefold()):
            free_form_finding.extend(locations(line))
            free_form_where_seen = True
        elif note_section and include_note and re.match(r"^\s*[-*]\s+", line):
            parsed = locations(line)
            if parsed:
                findings.append(parsed)
    return deduplicate_findings(findings)


def reviewed_truth(entries: Any, source: Path) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ScoreError(f"truth is not a JSON array: {source}")
    truth = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("reviewed") is not True:
            continue
        lines = entry.get("lines")
        path = entry.get("file")
        if (
            not isinstance(path, str)
            or not isinstance(lines, list)
            or len(lines) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in lines)
        ):
            raise ScoreError(f"reviewed truth has an invalid location: {source}")
        truth.append({"file": path, "lines": [min(lines), max(lines)]})
    return truth


def overlaps(finding: dict[str, Any], truth: dict[str, Any], granularity: str, slack: int) -> bool:
    if finding["file"] != truth["file"]:
        return False
    if granularity == "file":
        return True
    finding_start, finding_end = finding["lines"]
    truth_start, truth_end = truth["lines"]
    return finding_end >= truth_start - slack and finding_start <= truth_end + slack


def maximum_matches(
    findings: list[list[dict[str, Any]]],
    truth: list[dict[str, Any]],
    granularity: str,
    slack: int,
) -> int:
    edges = [
        [
            index
            for index, entry in enumerate(truth)
            if any(overlaps(location, entry, granularity, slack) for location in finding)
        ]
        for finding in findings
    ]
    owners: dict[int, int] = {}

    def place(finding_index: int, visited: set[int]) -> bool:
        for truth_index in edges[finding_index]:
            if truth_index in visited:
                continue
            visited.add(truth_index)
            if truth_index not in owners or place(owners[truth_index], visited):
                owners[truth_index] = finding_index
                return True
        return False

    return sum(place(index, set()) for index in range(len(findings)))


def metric(findings: int, truth: int, matched: int) -> dict[str, Any]:
    precision = matched / findings if findings else 0.0
    recall = matched / truth if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "findings": findings,
        "truth_entries": truth,
        "matched": matched,
    }


def numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    try:
        parsed = float(value)
    except OverflowError:
        return None
    return parsed if math.isfinite(parsed) else None


def usage_total(usage: Any) -> tuple[float | None, str | None]:
    if not isinstance(usage, dict):
        return None, "is not an object"
    total = 0.0
    for canonical, aliases in TOKEN_ALIASES.items():
        present = [name for name in aliases if name in usage]
        if not present:
            return None, f"missing {canonical}"
        value = usage[present[0]]
        parsed = numeric(value)
        if parsed is None:
            return None, f"invalid {canonical}"
        total += parsed
    if not math.isfinite(total):
        return None, "nonfinite token sum"
    return total, None


def session_tokens(path: Path) -> tuple[float | None, str | None]:
    if not path.is_file():
        return None, "session.json missing"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, "session.json unreadable"
    except json.JSONDecodeError:
        return None, "session.json is invalid JSON"
    if not isinstance(report, dict):
        return None, "session.json is not an object"
    for key in ("token_usage", "token_totals", "usage"):
        if key in report:
            total, problem = usage_total(report[key])
            return total, f"{key} {problem}" if problem is not None else None
    return None, "token totals missing"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ScoreError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ScoreError(f"invalid JSON in {path}: {error}") from error


def load_corpus(corpus: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not corpus.is_dir():
        raise ScoreError(f"corpus directory not found: {corpus}")
    items = []
    skipped = []
    for item_dir in sorted(path for path in corpus.iterdir() if path.is_dir()):
        pr_path = item_dir / "pr.json"
        truth_path = item_dir / "truth.json"
        if not pr_path.is_file() or not truth_path.is_file():
            continue
        pr = load_json(pr_path)
        if not isinstance(pr, dict):
            raise ScoreError(f"PR metadata is not a JSON object: {pr_path}")
        truth = reviewed_truth(load_json(truth_path), truth_path)
        if not truth:
            skipped.append(item_dir.name)
            continue
        items.append({"id": item_dir.name, "grade": pr.get("grade"), "truth": truth})
    if not items:
        raise ScoreError("corpus is unpruned: no item has a reviewed truth entry")
    return items, skipped


def aggregate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    result = metric(
        sum(row["findings"] for row in rows),
        sum(row["truth_entries"] for row in rows),
        sum(row["matched"] for row in rows),
    )
    costs = [row["tokens_per_review"] for row in rows if row["tokens_per_review"] is not None]
    all_costed = len(costs) == len(rows) and bool(rows)
    mean_cost = sum(costs) / len(costs) if all_costed else None
    median_cost = median(costs) if all_costed else None
    overflowed = all_costed and (not math.isfinite(mean_cost) or not math.isfinite(median_cost))
    result["tokens_per_review"] = mean_cost if not overflowed else None
    result["tokens_per_review_median"] = median_cost if not overflowed else None
    result["costed_reviews"] = len(costs)
    reasons = list(dict.fromkeys(
        row["tokens_unavailable"] for row in rows if row["tokens_unavailable"] is not None
    ))
    if overflowed:
        reasons.append("nonfinite aggregate token cost")
    result["tokens_unavailable"] = "; ".join(reasons) if reasons else None
    return result


def score_run(
    name: str,
    run_dir: Path,
    items: list[dict[str, Any]],
    granularity: str,
    slack: int,
    include_note: bool,
) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise ScoreError(f"run directory not found: {run_dir}")
    rows = []
    for item in items:
        verdict_path = run_dir / item["id"] / "verdict.md"
        no_verdict = not verdict_path.is_file()
        if no_verdict:
            verdict = ""
        else:
            try:
                verdict = verdict_path.read_text(encoding="utf-8")
            except OSError as error:
                raise ScoreError(f"cannot read {verdict_path}: {error}") from error
        findings = parse_verdict(verdict, include_note)
        matched = maximum_matches(findings, item["truth"], granularity, slack)
        row = {"id": item["id"], "grade": item["grade"] if item["grade"] in ("easy", "medium", "hard") else "ungraded"}
        row.update(metric(len(findings), len(item["truth"]), matched))
        row["tokens_per_review"], row["tokens_unavailable"] = session_tokens(
            run_dir / item["id"] / "session.json"
        )
        row["tokens_per_review_median"] = row["tokens_per_review"]
        row["no_verdict"] = no_verdict
        row["empty_verdict"] = not verdict.strip()
        rows.append(row)

    by_grade: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_grade[row["grade"]].append(row)
    return {
        "name": name,
        "items": rows,
        "grades": {grade: aggregate(grade_rows) for grade, grade_rows in sorted(by_grade.items())},
        "overall": aggregate(rows),
        "no_verdict": [row["id"] for row in rows if row["no_verdict"]],
    }


def pareto_frontier(runs: list[dict[str, Any]]) -> list[str]:
    comparable = [
        run for run in runs if run["overall"]["tokens_per_review_median"] is not None
    ]
    frontier = []
    for candidate in comparable:
        c_f1 = candidate["overall"]["f1"]
        c_cost = candidate["overall"]["tokens_per_review_median"]
        dominated = any(
            other is not candidate
            and other["overall"]["f1"] >= c_f1
            and other["overall"]["tokens_per_review_median"] <= c_cost
            and (
                other["overall"]["f1"] > c_f1
                or other["overall"]["tokens_per_review_median"] < c_cost
            )
            for other in comparable
        )
        if not dominated:
            frontier.append(candidate["name"])
    return frontier


def not_compared(runs: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "name": run["name"],
            "reason": run["overall"]["tokens_unavailable"] or "tokens unavailable",
        }
        for run in runs
        if run["overall"]["tokens_per_review_median"] is None
    ]


def display_ratio(value: float) -> str:
    return f"{value:.3f}"


def acceptance_gate(runs: list[dict[str, Any]], baseline: str, candidate: str) -> dict[str, Any]:
    """A measured recommendation, never a model/configuration mutation."""
    by_name = {run["name"]: run for run in runs}
    before, after = by_name[baseline], by_name[candidate]
    reasons = []
    for run in (before, after):
        missing = [row["id"] for row in run["items"] if row["empty_verdict"]]
        if missing:
            reasons.append(f"{run['name']}: missing or empty verdicts: {', '.join(missing)}")
        if run["overall"]["tokens_per_review"] is None:
            reasons.append(f"{run['name']}: incomplete token measurement")
    for label, old, new in [("overall", before["overall"], after["overall"])] + [
        (f"grade:{grade}", before["grades"][grade], after["grades"][grade])
        for grade in before["grades"]
    ]:
        def exact(row, metric_name):
            denominator = (row["findings"] if metric_name == "precision" else row["truth_entries"]
                           if metric_name == "recall" else row["findings"] + row["truth_entries"])
            numerator = row["matched"] * (2 if metric_name == "f1" else 1)
            return Fraction(numerator, denominator) if denominator else Fraction(0)
        for metric_name in ("precision", "recall", "f1"):
            if exact(new, metric_name) < exact(old, metric_name):
                reasons.append(f"{label}: {metric_name} regressed ({old[metric_name]} -> {new[metric_name]})")
    for cost in ("tokens_per_review", "tokens_per_review_median"):
        old, new = before["overall"][cost], after["overall"][cost]
        if old is not None and new is not None and new >= old:
            reasons.append(f"{cost}: no strict improvement ({old} -> {new})")
    return {"baseline": baseline, "candidate": candidate, "passed": not reasons, "reasons": reasons}


def display_tokens(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:,.0f}" if value.is_integer() else f"{value:,.1f}"


def print_text(report: dict[str, Any]) -> None:
    skipped = report["not_pruned_yet"]
    print("not pruned yet: " + (", ".join(skipped) if skipped else "--"))
    missing = [
        f"{run['name']}/{item_id}"
        for run in report["runs"]
        for item_id in run["no_verdict"]
    ]
    print("no verdict: " + (", ".join(missing) if missing else "--"))
    print(
        "run              item          grade     precision  recall  f1     findings  truth  matched  "
        "tokens/review  tokens/review (med)"
    )
    for run in report["runs"]:
        for row in run["items"]:
            print(
                f"{run['name']:<16} {row['id']:<13} {row['grade']:<9} "
                f"{display_ratio(row['precision']):>9}  {display_ratio(row['recall']):>6}  {display_ratio(row['f1']):>5}  "
                f"{row['findings']:>8}  {row['truth_entries']:>5}  {row['matched']:>7}  "
                f"{display_tokens(row['tokens_per_review']):>13}  {display_tokens(row['tokens_per_review_median']):>19}"
            )
        for grade, row in run["grades"].items():
            print(
                f"{run['name']:<16} {'grade:' + grade:<13} {grade:<9} "
                f"{display_ratio(row['precision']):>9}  {display_ratio(row['recall']):>6}  {display_ratio(row['f1']):>5}  "
                f"{row['findings']:>8}  {row['truth_entries']:>5}  {row['matched']:>7}  "
                f"{display_tokens(row['tokens_per_review']):>13}  {display_tokens(row['tokens_per_review_median']):>19}"
            )
        row = run["overall"]
        print(
            f"{run['name']:<16} {'overall':<13} {'all':<9} "
            f"{display_ratio(row['precision']):>9}  {display_ratio(row['recall']):>6}  {display_ratio(row['f1']):>5}  "
            f"{row['findings']:>8}  {row['truth_entries']:>5}  {row['matched']:>7}  "
            f"{display_tokens(row['tokens_per_review']):>13}  {display_tokens(row['tokens_per_review_median']):>19}"
        )
    if report["pareto"]:
        print("pareto: " + ", ".join(report["pareto"]) + " (by median tokens/review)")
    else:
        print("pareto: -- (median tokens/review unavailable)")
    for excluded in report["not_compared"]:
        print(
            f"not compared: {excluded['name']} "
            f"(tokens/review unavailable; {excluded['reason']})"
        )
    if report.get("acceptance_gate") is not None:
        gate = report["acceptance_gate"]
        print(f"acceptance: {'PASS' if gate['passed'] else 'FAIL'} ({gate['baseline']} -> {gate['candidate']})")
        for reason in gate["reasons"]:
            print(f"  - {reason}")


def run_argument(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("run must be NAME=DIR")
    name, directory = value.split("=", 1)
    if not name or not directory:
        raise argparse.ArgumentTypeError("run must be NAME=DIR")
    return name, Path(directory)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Score review verdicts against reviewed truth.")
    command.add_argument("--corpus", required=True, type=Path)
    command.add_argument("--run", required=True, action="append", type=run_argument, dest="runs")
    command.add_argument("--granularity", choices=("hunk", "file"), default="hunk")
    command.add_argument("--slack", type=int, default=5)
    command.add_argument("--include-note", action="store_true")
    command.add_argument("--json", action="store_true", dest="as_json")
    command.add_argument("--baseline", help="named baseline run for the quality/cost acceptance gate")
    command.add_argument("--candidate", help="named candidate run; gate failure exits 1")
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.slack < 0:
        parser().error("--slack cannot be negative")
    names = [name for name, _ in args.runs]
    if len(names) != len(set(names)):
        parser().error("run names must be unique")
    if (args.baseline is None) != (args.candidate is None):
        parser().error("--baseline and --candidate must be supplied together")
    if args.baseline is not None and (not args.baseline or not args.candidate or args.baseline not in names or args.candidate not in names or args.baseline == args.candidate):
        parser().error("baseline and candidate must name two different --run entries")
    if args.baseline is not None and args.include_note:
        parser().error("--include-note is diagnostic only and cannot be used for acceptance")
    try:
        items, skipped = load_corpus(args.corpus)
        runs = [score_run(name, directory, items, args.granularity, args.slack, args.include_note) for name, directory in args.runs]
    except ScoreError as error:
        print(f"plumb-bench-score: {error}", file=sys.stderr)
        return 2
    report = {
        "granularity": args.granularity,
        "slack": args.slack,
        "include_note": args.include_note,
        "not_pruned_yet": skipped,
        "runs": runs,
        "pareto": pareto_frontier(runs),
        "not_compared": not_compared(runs),
    }
    if args.baseline is not None:
        report["acceptance_gate"] = acceptance_gate(runs, args.baseline, args.candidate)
        if skipped:
            report["acceptance_gate"]["passed"] = False
            report["acceptance_gate"]["reasons"].append("unpruned corpus items: " + ", ".join(skipped))
    if args.as_json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    return 1 if report.get("acceptance_gate", {}).get("passed") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
