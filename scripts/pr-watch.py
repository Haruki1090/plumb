#!/usr/bin/env python3
"""plumb-pr-watch: the state of one pull request as one word and one exit code.

    plumb-pr-watch <number> [--repo OWNER/NAME] [--json] [--wait SECONDS [--interval SECONDS]]

Reads the pull request once through gh (`gh pr view` for state, draft, mergeability and the check rollup,
`gh api graphql` for the review threads) and prints exactly one state, the first that matches, then tab-separated
`key=value` detail:

  state      exit  when
  merged       0   the pull request is merged
  closed       6   it is closed without a merge
  conflicts    3   it cannot merge into its base (mergeable CONFLICTING, or mergeStateStatus DIRTY)
  threads      4   a review thread is unresolved
  failing      5   a completed check failed (the first 5 names are in the detail)
  pending      7   a check is still running, or a field is missing or not understood
  draft        8   it is a draft and nothing above applies
  ready        0   none of the above

`ready` is never printed on missing data: an unknown or absent field makes the state `pending`. Review
approval and `mergeStateStatus` BLOCKED or BEHIND are not states: a `ready` line names them in its detail
(`review=...`, `merge=...`) and the caller decides. gh missing or failing prints `remote: unavailable` and
exits 9.

`--wait S` reads every `--interval` seconds (default 60, at least 30) until the state is not `pending` or S
seconds have passed; on timeout it prints `pending` with `timeout` in the detail and exits 7. Without
`--wait` it reads once. It calls no model and writes nothing. `classify()` is the whole classification on the
parsed JSON and touches neither disk nor network. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_view import run_gh  # noqa: E402

PR_FIELDS = "number,state,isDraft,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup"
THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) { pageInfo { hasNextPage } nodes { isResolved } }
    }
  }
}
"""
GH_TIMEOUT = 20.0
DEFAULT_INTERVAL = 60.0
MIN_INTERVAL = 30.0
NAMES_MAX = 5
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

EXIT = {"merged": 0, "closed": 6, "conflicts": 3, "threads": 4, "failing": 5, "pending": 7, "draft": 8, "ready": 0,
        "unavailable": 9}
# Closed sets: only a value listed here is understood. Anything else (a new value, a wrong type) is unknown.
STATES = {"OPEN", "MERGED", "CLOSED"}
MERGEABLE = {"MERGEABLE", "CONFLICTING"}  # UNKNOWN is the forge saying it has not computed it yet: not understood
MERGE_STATES = {"CLEAN", "BLOCKED", "BEHIND", "DIRTY", "DRAFT", "HAS_HOOKS", "UNSTABLE"}
REVIEW_DECISIONS = {"APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"}
CHECK_STATUSES = {"QUEUED", "IN_PROGRESS", "WAITING", "PENDING", "REQUESTED"}
FAILED_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}
PASSED_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FAILED_STATES = {"FAILURE", "ERROR"}
PENDING_STATES = {"PENDING", "EXPECTED"}


def clock() -> float:
    return time.monotonic()


def pause(seconds: float) -> None:
    time.sleep(seconds)


def one_of(value: Any, allowed: set[str]) -> bool:
    """`value` is a string in `allowed`. A list or an object is simply not in it (it is not hashable, so `in`
    would raise)."""
    return isinstance(value, str) and value in allowed


def plain(text: Any) -> str:
    """A forge string made safe for one tab-separated line: every control character (a tab, a newline, an
    escape) is `?`."""
    return CONTROL.sub("?", str(text))


# ---------------------------------------------------------------- the classification

def check_outcome(entry: Any) -> tuple[str, str]:
    """(name, "passed" | "failed" | "pending" | "unknown") for one statusCheckRollup entry. A check run is
    pending until it completes; a completed one with a conclusion this tool does not know is `unknown`."""
    if not isinstance(entry, dict):
        return "?", "unknown"
    label = entry.get("context") if "context" in entry or entry.get("__typename") == "StatusContext" else entry.get("name")
    if label is not None and not isinstance(label, str):
        return "?", "unknown"  # a name that is not text means the entry is not what the forge documents
    if "context" in entry or entry.get("__typename") == "StatusContext":
        name, state = str(entry.get("context") or "?"), entry.get("state")
        if state == "SUCCESS":
            return name, "passed"
        if one_of(state, FAILED_STATES):
            return name, "failed"
        return name, "pending" if one_of(state, PENDING_STATES) else "unknown"
    name, status = str(entry.get("name") or "?"), entry.get("status")
    if status != "COMPLETED":
        return name, "pending" if one_of(status, CHECK_STATUSES) else "unknown"
    conclusion = entry.get("conclusion")
    if one_of(conclusion, PASSED_CONCLUSIONS):
        return name, "passed"
    return name, "failed" if one_of(conclusion, FAILED_CONCLUSIONS) else "unknown"


def classify(pr: Any, threads: Any = None) -> tuple[str, list[str]]:
    """(state, detail) for one pull request. `pr` is the parsed `gh pr view --json` object; `threads` is the
    parsed `reviewThreads` connection (`{"pageInfo": {...}, "nodes": [{"isResolved": bool}]}`), or None when it
    is not known. Precedence: merged, closed, conflicts, threads, failing, pending, draft, ready. An absent or
    unrecognised field is never read as good: it makes the state `pending`."""
    if not isinstance(pr, dict):
        return "pending", ["unknown=pull-request"]
    state = pr.get("state")
    if state == "MERGED":
        return "merged", []
    if state == "CLOSED":
        return "closed", []
    unknown: list[str] = []
    if state != "OPEN":
        unknown.append("state")

    mergeable, merge_state = pr.get("mergeable"), pr.get("mergeStateStatus")
    if mergeable == "CONFLICTING" or merge_state == "DIRTY":
        return "conflicts", [f"mergeable={plain(mergeable).lower()}", f"merge={plain(merge_state).lower()}"]
    if mergeable != "MERGEABLE":
        unknown.append("mergeable")
    if not one_of(merge_state, MERGE_STATES):
        unknown.append("merge")
    review = pr.get("reviewDecision", ...)
    if review is ... or not (review in ("", None) or one_of(review, REVIEW_DECISIONS)):
        unknown.append("review")

    unresolved = None
    nodes = threads.get("nodes") if isinstance(threads, dict) else None
    if isinstance(nodes, list) and all(isinstance(n, dict) and isinstance(n.get("isResolved"), bool) for n in nodes):
        unresolved = sum(1 for n in nodes if not n["isResolved"])
        page_info = threads.get("pageInfo")
        more = page_info.get("hasNextPage") if isinstance(page_info, dict) else None
        if not unresolved and (more is not False):
            unresolved = None  # a second page may hold one, or we were not told whether there is one
    if unresolved:
        return "threads", [f"unresolved={unresolved}"]
    if unresolved is None:
        unknown.append("threads")

    rollup = pr.get("statusCheckRollup")
    outcomes = [check_outcome(e) for e in rollup] if isinstance(rollup, list) else []
    if not isinstance(rollup, list):
        unknown.append("statusCheckRollup")
    count = {kind: sum(1 for _, o in outcomes if o == kind) for kind in ("passed", "failed", "pending", "unknown")}
    if count["failed"]:
        names = [plain(n) for n, o in outcomes if o == "failed"]
        shown = ", ".join(names[:NAMES_MAX]) + (f" (+{len(names) - NAMES_MAX} more)" if len(names) > NAMES_MAX else "")
        detail = [f"failed={count['failed']}"] + ([f"pending={count['pending']}"] if count["pending"] else [])
        return "failing", detail + [f"names={shown}"]
    if count["unknown"]:
        unknown.append("check-state")

    if count["pending"] or unknown:
        detail = ([f"checks_pending={count['pending']}"] if count["pending"] else [])
        return "pending", detail + ([f"unknown={','.join(unknown)}"] if unknown else [])

    detail = [f"checks_passed={count['passed']}"]
    if pr.get("isDraft") is not False:
        return ("draft", detail) if pr.get("isDraft") is True else ("pending", ["unknown=isDraft"])
    if review:
        detail.append(f"review={plain(review).lower()}")
    if merge_state != "CLEAN":
        detail.append(f"merge={plain(merge_state).lower()}")
    return "ready", detail


# ---------------------------------------------------------------- the forge

class Unavailable(Exception):
    """gh is missing, failed, timed out or answered something that is not JSON."""


def gh_json(args: list[str]) -> Any:
    try:
        done = run_gh(args, ".", GH_TIMEOUT)
        if done.returncode != 0:
            raise Unavailable("gh failed")
        return json.loads(done.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise Unavailable(type(error).__name__) from error


def read_pr(number: int, repo: str | None) -> tuple[str, list[str]]:
    """One read: `gh pr view`, and the review threads when the answer so far could still be `threads` or
    better. Raises Unavailable when gh cannot answer."""
    where = ["--repo", repo] if repo else []
    pr = gh_json(["pr", "view", str(number), "--json", PR_FIELDS, *where])
    threads = None
    if isinstance(pr, dict) and pr.get("state") == "OPEN" and pr.get("mergeable") != "CONFLICTING" \
            and pr.get("mergeStateStatus") != "DIRTY":
        owner, name = repo.split("/", 1) if repo else (":owner", ":repo")
        data = gh_json(["api", "graphql", "-f", f"query={THREADS_QUERY}", "-F", f"owner={owner}", "-F", f"name={name}",
                        "-F", f"number={number}"])
        try:
            threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        except (KeyError, TypeError):
            threads = None
    return classify(pr, threads)


def watch(read, wait: float | None = None, interval: float = DEFAULT_INTERVAL) -> tuple[str, list[str]]:
    """`read()` once; with `wait`, while the state is `pending` and `wait` seconds have not passed, read again
    after `interval`. A pending state at the deadline gets `timeout` appended. Without `wait` it is one read
    and nothing is appended. Unavailable propagates."""
    deadline = clock() + (wait or 0.0)
    while True:
        state, detail = read()
        if state != "pending" or wait is None:
            return state, detail
        left = deadline - clock()
        if left <= 0:
            return state, detail + ["timeout"]
        pause(min(interval, left))


def render(state: str, detail: list[str]) -> str:
    return "\t".join([state, *detail])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plumb-pr-watch", description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int, help="the pull request number")
    parser.add_argument("--repo", default=None, help="OWNER/NAME (default: the current directory's repository)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the line")
    parser.add_argument("--wait", type=float, default=None, metavar="SECONDS",
                        help="keep reading while the state is pending, for at most this long")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, metavar="SECONDS",
                        help=f"seconds between reads with --wait (default {DEFAULT_INTERVAL:g}, at least {MIN_INTERVAL:g})")
    args = parser.parse_args(argv)
    if args.number < 1:
        parser.error("the pull request number must be positive")
    if args.repo is not None and not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        parser.error("--repo is OWNER/NAME")
    if args.wait is not None and args.wait < 0:
        parser.error("--wait must not be negative")
    if args.interval < MIN_INTERVAL:
        parser.error(f"--interval must be at least {MIN_INTERVAL:g} seconds")
    try:
        state, detail = watch(lambda: read_pr(args.number, args.repo), args.wait, args.interval)
    except Unavailable:
        if args.json:
            print(json.dumps({"schema": 1, "remote": "unavailable", "state": None, "exit": EXIT["unavailable"]}))
        else:
            print("remote: unavailable")
        return EXIT["unavailable"]
    if args.json:
        print(json.dumps({"schema": 1, "remote": "ok", "number": args.number, "state": state, "exit": EXIT[state],
                          "detail": detail}, indent=2))
    else:
        print(render(state, detail))
    return EXIT[state]


if __name__ == "__main__":
    sys.exit(main())
