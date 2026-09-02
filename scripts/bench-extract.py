#!/usr/bin/env python3
"""Build draft review-benchmark items from merged bug-fix PRs."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


FIX_TITLE = re.compile(r"^(?:fix|hotfix|revert)\b", re.IGNORECASE)
PR_REFERENCE = re.compile(r"(?<![A-Za-z0-9_])#([0-9]+)\b")
HUNK_HEADER = re.compile(
    r"^@@\s+-([0-9]+)(?:,([0-9]+))?\s+\+([0-9]+)(?:,([0-9]+))?\s+@@"
)
ITEM_ID = re.compile(r"^[0-9]{5}-[0-9]{5}$")


class BenchError(Exception):
    """A user-facing extraction failure."""


def find_pairs(
    pull_requests: Iterable[dict[str, Any]],
    min_number: int = 20,
    only: Iterable[int] | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return (buggy, fix) pairs in stable buggy-PR order."""
    prs = [pr for pr in pull_requests if isinstance(pr, dict) and isinstance(pr.get("number"), int)]
    by_number = {pr["number"]: pr for pr in prs}
    selected = set(only) if only is not None else None
    pairs = []
    seen = set()

    for fix in prs:
        fix_number = fix["number"]
        if selected is not None and fix_number not in selected:
            continue
        if not FIX_TITLE.match(str(fix.get("title") or "")):
            continue
        references = {int(number) for number in PR_REFERENCE.findall(str(fix.get("body") or ""))}
        for buggy_number in references:
            buggy = by_number.get(buggy_number)
            if buggy is None or buggy_number < min_number or buggy_number == fix_number:
                continue
            buggy_merged = buggy.get("mergedAt")
            fix_merged = fix.get("mergedAt")
            if not isinstance(buggy_merged, str) or not isinstance(fix_merged, str):
                continue
            if buggy_merged >= fix_merged:
                continue
            key = (buggy_number, fix_number)
            if key not in seen:
                seen.add(key)
                pairs.append((buggy, fix))

    return sorted(pairs, key=lambda pair: (pair[0]["number"], pair[1]["number"]))


def decode_diff_path(value: str) -> str | None:
    value = value.strip()
    if value == "/dev/null":
        return None
    if value.startswith('"'):
        try:
            decoded = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            decoded = value.strip('"')
    else:
        decoded = value
    return decoded[2:] if decoded.startswith(("a/", "b/")) else decoded


def line_range(start: str, count: str | None) -> list[int]:
    first = int(start)
    length = int(count) if count is not None else 1
    return [first, first if length == 0 else first + length - 1]


def parse_diff_hunks(diff_text: str) -> dict[str, list[dict[str, list[int]]]]:
    """Parse old- and new-side line ranges from a unified diff, grouped by old path."""
    result: dict[str, list[dict[str, list[int]]]] = {}
    current_path = None
    old_path = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            current_path = None
            old_path = None
        elif line.startswith("--- "):
            old_path = decode_diff_path(line[4:].split("\t", 1)[0])
        elif line.startswith("+++ "):
            new_path = decode_diff_path(line[4:].split("\t", 1)[0])
            current_path = old_path or new_path
            if current_path is not None:
                result.setdefault(current_path, [])
        elif current_path is not None:
            match = HUNK_HEADER.match(line)
            if match:
                result[current_path].append({
                    "lines": line_range(match.group(1), match.group(2)),
                    "fix_lines": line_range(match.group(3), match.group(4)),
                })
    return result


def filter_fix_hunks(fix_diff: str, buggy_diff: str, fix_number: int) -> list[dict[str, Any]]:
    """Keep fix hunks only for paths also touched by the buggy PR."""
    buggy_files = set(parse_diff_hunks(buggy_diff))
    fix_hunks = parse_diff_hunks(fix_diff)
    return [
        {
            "file": path,
            "lines": hunk["lines"],
            "fix_lines": hunk["fix_lines"],
            "source": f"fix#{fix_number}",
            "reviewed": False,
            "note": "",
        }
        for path in sorted(fix_hunks)
        if path in buggy_files
        for hunk in fix_hunks[path]
    ]


def has_reviewed_truth(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BenchError(f"cannot read existing truth {path}: {error}") from error
    if not isinstance(entries, list):
        raise BenchError(f"existing truth is not a JSON array: {path}")
    return any(isinstance(entry, dict) and entry.get("reviewed") is True for entry in entries)


def read_truth_counts(path: Path) -> tuple[int, int]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BenchError(f"cannot read existing truth {path}: {error}") from error
    entries = entries if isinstance(entries, list) else []
    files = {entry.get("file") for entry in entries if isinstance(entry, dict) and entry.get("file")}
    return len(files), len(entries)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(value, target, indent=2, ensure_ascii=False)
            target.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def gh(arguments: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["gh", *arguments], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as error:
        raise BenchError(f"gh failed: {error}") from error
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise BenchError(f"gh failed: {message}")
    return completed.stdout


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Extract draft truth from follow-up fix PRs.")
    command.add_argument("--repo", required=True, help="GitHub repository as owner/name")
    command.add_argument("--out", required=True, type=Path, help="corpus directory to write")
    command.add_argument("--limit", type=int, default=600, help="merged PRs to inspect (default: 600)")
    command.add_argument("--min-number", type=int, default=20, help="lowest referenced PR number (default: 20)")
    command.add_argument("--only", type=int, nargs="+", help="extract only these fix PR numbers")
    command.add_argument("--refresh", help="rewrite this unreviewed item id")
    return command


def extract(args: argparse.Namespace) -> tuple[int, int]:
    fields = "number,title,body,mergeCommit,baseRefName,baseRefOid,headRefOid,mergedAt"
    listing = gh([
        "pr", "list", "--repo", args.repo, "--state", "merged", "--limit", str(args.limit),
        "--json", fields,
    ])
    try:
        pull_requests = json.loads(listing)
    except json.JSONDecodeError as error:
        raise BenchError(f"gh returned invalid JSON for the PR list: {error}") from error
    if not isinstance(pull_requests, list):
        raise BenchError("gh returned a PR list that is not a JSON array")

    pairs = find_pairs(pull_requests, args.min_number, args.only)
    pair_ids = {
        f"{buggy['number']:05d}-{fix['number']:05d}": (buggy, fix)
        for buggy, fix in pairs
    }
    if args.refresh is not None:
        if not ITEM_ID.match(args.refresh):
            raise BenchError("--refresh must be an item id such as 00021-00030")
        if args.refresh not in pair_ids:
            raise BenchError(f"--refresh item is not in the extracted pairs: {args.refresh}")
        refresh_truth = args.out / args.refresh / "truth.json"
        if refresh_truth.is_file() and has_reviewed_truth(refresh_truth):
            raise BenchError(f"refusing --refresh {args.refresh}: it contains reviewed truth")

    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    written = 0
    kept = 0
    for buggy, fix in pairs:
        item_id = f"{buggy['number']:05d}-{fix['number']:05d}"
        item_dir = args.out / item_id
        truth_path = item_dir / "truth.json"
        if truth_path.is_file() and args.refresh != item_id:
            files, hunks = read_truth_counts(truth_path)
            kept += 1
            rows.append((item_id, buggy["number"], fix["number"], files, hunks, "kept"))
            print(f"kept {item_id} (existing truth)")
            continue

        base_sha = buggy.get("baseRefOid")
        buggy_sha = buggy.get("headRefOid")
        fix_base_sha = fix.get("baseRefOid")
        fix_head_sha = fix.get("headRefOid")
        if not isinstance(base_sha, str) or not base_sha or not isinstance(buggy_sha, str) or not buggy_sha:
            raise BenchError(f"PR #{buggy['number']} has no base/head SHA in the gh response")
        if (
            not isinstance(fix_base_sha, str) or not fix_base_sha
            or not isinstance(fix_head_sha, str) or not fix_head_sha
        ):
            raise BenchError(f"PR #{fix['number']} has no base/head SHA in the gh response")
        pinned_sha = gh([
            "api", f"repos/{args.repo}/compare/{fix_base_sha}...{fix_head_sha}",
            "--jq", ".merge_base_commit.sha",
        ]).strip()
        if not pinned_sha:
            raise BenchError(f"GitHub returned no merge base for fix PR #{fix['number']}")
        fix_diff = gh(["pr", "diff", "--repo", args.repo, str(fix["number"])])
        buggy_diff = gh(["pr", "diff", "--repo", args.repo, str(buggy["number"])])
        truth = filter_fix_hunks(fix_diff, buggy_diff, fix["number"])
        pr = {
            "repo": args.repo,
            "number": buggy["number"],
            "sha": pinned_sha,
            "buggy_sha": buggy_sha,
            "base_sha": base_sha,
            "title": str(buggy.get("title") or ""),
            "fixed_by": fix["number"],
            "grade": None,
        }
        write_json(item_dir / "pr.json", pr)
        write_json(truth_path, truth)
        written += 1
        rows.append((item_id, buggy["number"], fix["number"], len({entry["file"] for entry in truth}), len(truth), "written"))

    print("id    buggy  fix    files  hunks  result")
    for item_id, buggy_number, fix_number, files, hunks, result in rows:
        print(f"{item_id}  #{buggy_number:<5} #{fix_number:<5} {files:>5}  {hunks:>5}  {result}")
    print(f"plumb bench-extract: wrote {written} item(s), kept {kept}")
    return written, kept


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.limit <= 0:
        parser().error("--limit must be greater than zero")
    if args.min_number < 0:
        parser().error("--min-number cannot be negative")
    try:
        extract(args)
    except (BenchError, OSError) as error:
        print(f"plumb-bench-extract: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
