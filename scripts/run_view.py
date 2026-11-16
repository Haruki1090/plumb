#!/usr/bin/env python3
"""plumb-run-view: the lanes of the running plumb:lead ledgers and the pull requests they point at, as JSON.

    plumb-run-view [--repo <dir>] [--ledger <file>]... [--since <hours>] [--no-remote]

A pure function of (lead ledgers in `plumb-path run`) and (pull request facts from the forge): no model,
no state file, no cache. Run it twice on the same inputs and the output differs only in `generated_at`.
It never fails the caller: a missing run directory, an unreadable ledger, a forge that is unreachable
all give valid JSON and exit 0; only bad command-line usage exits non-zero.

An item is linked to a pull request by exactly two rules, and by nothing read from free text:
  1. the item's latest `ref` cell that is not empty and not `-`: `pr:<number>`, or `branch:<name>`
     (the newest pull request whose head branch is exactly <name>);
  2. else, the item cell as a whole is `#<number>` or `#<number>@<hex>` and that number is a pull request.
The `evidence` cell is never part of the output.

`build(ledgers, prs, now)` is the whole computation and touches neither disk nor network; `main()` only
discovers ledgers, asks the forge, and prints. Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
HEADER = ["ts", "item", "state", "lane", "evidence", "next"]
BUDGET_SECONDS = 10.0
DEFAULT_SINCE_HOURS = 12.0
LIST_LIMIT = 200
BRANCH_LIMIT = 30
NEXT_MAX = 120
LATE_AFTER = timedelta(minutes=10)
LIST_FIELDS = "number,url,state,isDraft,headRefName,createdAt,mergedAt"
PR_FIELDS = LIST_FIELDS + ",statusCheckRollup"
WORKERS = 8
FAIL = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}
PENDING = {"PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "WAITING"}
ITEM_PR = re.compile(r"#(\d+)(?:@[0-9a-fA-F]+)?")
REF_PR = re.compile(r"pr:(\d+)")
REF_BRANCH = re.compile(r"branch:(.+)")


# ---------------------------------------------------------------- times

def parse_time(text: str) -> datetime | None:
    """A ledger timestamp as an aware UTC datetime, or None when it does not parse."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_or_none(text: Any) -> str | None:
    moment = parse_time(text) if isinstance(text, str) else None
    # A forge that has no merge time may print the zero time instead of null.
    return iso(moment) if moment is not None and moment.year > 1970 else None


# ---------------------------------------------------------------- ledgers

def lane_value(cell: str) -> str | None:
    cell = (cell or "").strip()
    return None if cell in ("", "-") else cell


def parse_ledger(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """One lead ledger as {path, name, kind, rows}, or None when it is not one (unreadable, another
    header, no row with a time). A row is {ts, item, state, lane, next, ref}; `evidence` is read past
    and never kept. A row whose time does not parse, or that names no item, is dropped."""
    path = Path(path)
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as handle:
            table = list(csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))
    except OSError:
        return None
    if not table:
        return None
    header = [cell.strip() for cell in table[0]]
    if header != HEADER and header != HEADER + ["ref"]:
        return None
    width = len(header)
    rows = []
    for raw in table[1:]:
        if not any(cell.strip() for cell in raw):
            continue
        cells = [cell.strip() for cell in raw[:width]] + [""] * (width - len(raw))
        moment = parse_time(cells[0])
        if moment is None or not cells[1]:
            continue
        rows.append({"ts": moment, "item": cells[1], "state": cells[2], "lane": cells[3],
                     "next": cells[5], "ref": cells[6] if width > 6 else ""})
    if not rows:
        return None
    stem = path.name[:-4] if path.name.endswith(".tsv") else path.name
    kind = stem[len("lead-"):].split("-", 1)[0] if stem.startswith("lead-") else ""
    return {"path": str(path), "name": stem, "kind": kind, "rows": rows}


def discover(repo: str) -> list[str]:
    """The lead ledgers in the run directory `plumb-path run` names for the repository, sorted by name."""
    try:
        done = subprocess.run(["bash", str(HERE / "plumb-path.sh"), "run", repo], capture_output=True,
                              text=True, timeout=BUDGET_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0 or not done.stdout.strip():
        return []
    directory = Path(done.stdout.strip().splitlines()[-1])
    try:
        return sorted(str(p) for p in directory.glob("lead-*.tsv") if p.is_file())
    except OSError:
        return []


# ---------------------------------------------------------------- links

def item_link(rows: list[dict[str, Any]]) -> tuple[str, Any] | None:
    """How an item points at a pull request: ("pr", number), ("branch", name), ("item", number) or None.
    `rows` are the item's rows in file order. Only the ref cell and the item cell as a whole are read."""
    for row in reversed(rows):
        ref = row["ref"].strip()
        if ref in ("", "-"):
            continue
        if (m := REF_PR.fullmatch(ref)):
            return ("pr", int(m.group(1)))
        if (m := REF_BRANCH.fullmatch(ref)):
            return ("branch", m.group(1).strip())
        break  # the latest ref is not one we read: rule 1 does not apply, and no older ref is guessed
    if (m := ITEM_PR.fullmatch(rows[0]["item"])):
        return ("item", int(m.group(1)))
    return None


def group_items(ledger: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    items: dict[str, list[dict[str, Any]]] = {}
    for row in ledger["rows"]:
        items.setdefault(row["item"], []).append(row)
    return items


def collect_links(ledgers: list[dict[str, Any]]) -> tuple[set[int], set[str]]:
    """Every pull request number and branch name the ledgers point at, to ask the forge for them at once."""
    numbers: set[int] = set()
    branches: set[str] = set()
    for ledger in ledgers:
        for rows in group_items(ledger).values():
            link = item_link(rows)
            if link is None:
                continue
            (branches if link[0] == "branch" else numbers).add(link[1])
    return numbers, branches


# ---------------------------------------------------------------- pull request facts

def classify_checks(rollup: Any) -> str:
    """fail | pending | pass | skipped | none from a check rollup (check runs and commit statuses)."""
    seen_fail = seen_pending = seen_pass = False
    count = 0
    for entry in rollup if isinstance(rollup, list) else []:
        if not isinstance(entry, dict):
            continue
        count += 1
        status = str(entry.get("status") or "").upper()
        verdict = str(entry.get("conclusion") or entry.get("state") or "").upper()
        if entry.get("__typename") == "CheckRun" and status != "COMPLETED":
            seen_pending = True  # still queued or running, whatever it printed before
        elif verdict in FAIL:
            seen_fail = True
        elif verdict == "" or verdict in PENDING:
            seen_pending = True
        elif verdict == "SUCCESS":
            seen_pass = True
    if seen_fail:
        return "fail"
    if seen_pending:
        return "pending"
    if seen_pass:
        return "pass"
    return "skipped" if count else "none"


def normalize_pr(raw: dict[str, Any]) -> dict[str, Any] | None:
    """The fields of one forge pull request that the view uses; `head` is for the branch rule only."""
    try:
        number = int(raw["number"])
    except (KeyError, TypeError, ValueError):
        return None
    merged_at = iso_or_none(raw.get("mergedAt"))
    state = str(raw.get("state") or "").upper()
    state = "merged" if state == "MERGED" or merged_at else "closed" if state == "CLOSED" else "open"
    return {"number": number, "url": raw.get("url") or "", "state": state, "draft": bool(raw.get("isDraft")),
            "checks": classify_checks(raw.get("statusCheckRollup")), "created_at": iso_or_none(raw.get("createdAt")),
            "merged_at": merged_at, "head": raw.get("headRefName") or ""}


def run_gh(args: list[str], cwd: str, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=max(timeout, 0.1),
                          stdin=subprocess.DEVNULL, env={**os.environ, "GH_PROMPT_DISABLED": "1"})


def fetch_prs(repo: str, numbers: set[int], branches: set[str],
              budget: float = BUDGET_SECONDS, gh=run_gh) -> tuple[str, dict[int, dict[str, Any]] | None]:
    """(remote, facts): "ok" with {number: fact}, or "unavailable" with None. Nothing linked -> no call.
    One list call (without checks: the rollup is most of the list's weight and the page is slow with it)
    finds the pull requests and the branches' heads; a branch the page does not hold is asked for by name.
    Then each linked pull request is read once, with its checks. The list call is the gate: if it fails the
    forge is unavailable. A number the forge has no pull request for is simply absent (an issue number is
    not a pull request). A read that times out makes the whole forge unavailable: no partial answer."""
    if not numbers and not branches:
        return "ok", {}
    deadline = time.monotonic() + budget
    left = lambda: deadline - time.monotonic()  # noqa: E731
    facts: dict[int, dict[str, Any]] = {}

    def load(done: subprocess.CompletedProcess) -> list[dict[str, Any]]:
        data = json.loads(done.stdout)
        data = data if isinstance(data, list) else [data]
        return [fact for fact in (normalize_pr(r) for r in data if isinstance(r, dict)) if fact]

    try:
        done = gh(["pr", "list", "--state", "all", "--limit", str(LIST_LIMIT), "--json", LIST_FIELDS], repo, left())
        if done.returncode != 0:
            return "unavailable", None
        for fact in load(done):
            facts[fact["number"]] = fact
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unavailable", None

    def ask(args: list[str]) -> list[dict[str, Any]]:
        try:
            done = gh(args, repo, left())
            return load(done) if done.returncode == 0 else []
        except ValueError:
            return []  # this one answer is unreadable: a miss, not a dead forge

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            unseen = sorted(b for b in branches if not any(f["head"] == b for f in facts.values()))
            for found in pool.map(lambda b: ask(["pr", "list", "--state", "all", "--head", b, "--limit", str(BRANCH_LIMIT),
                                                 "--json", LIST_FIELDS]), unseen):
                for fact in found:
                    facts[fact["number"]] = fact
            wanted = set(numbers)
            for branch in branches:
                head = resolve(("branch", branch), facts)
                if head:
                    wanted.add(head["number"])
            for number, found in zip(sorted(wanted), pool.map(lambda n: ask(["pr", "view", str(n), "--json", PR_FIELDS]),
                                                               sorted(wanted))):
                for fact in found:
                    facts[fact["number"]] = fact  # the read carries the checks the list left out
    except (OSError, subprocess.SubprocessError):
        return "unavailable", None
    return "ok", facts


# ---------------------------------------------------------------- the view

def public_pr(fact: dict[str, Any]) -> dict[str, Any]:
    return {key: fact[key] for key in ("number", "url", "state", "draft", "checks", "created_at", "merged_at")}


def resolve(link: tuple[str, Any] | None, prs: dict[int, dict[str, Any]] | None) -> dict[str, Any] | None:
    if link is None or prs is None:
        return None
    kind, key = link
    if kind == "branch":
        heads = [f for f in prs.values() if f["head"] == key]
        return max(heads, key=lambda f: (f["created_at"] or "", f["number"])) if heads else None
    return prs.get(key)


def build_run(ledger: dict[str, Any], prs: dict[int, dict[str, Any]] | None) -> dict[str, Any]:
    rows = ledger["rows"]
    started, last = rows[0]["ts"], rows[-1]["ts"]
    items = group_items(ledger)
    lanes, upcoming = [], []
    events: list[tuple[datetime, int, int, dict[str, Any]]] = []
    sequence = 0
    for row in rows:
        events.append((row["ts"], 0, sequence, {"at": iso(row["ts"]), "item": row["item"], "lane": lane_value(row["lane"]),
                                                 "what": row["state"], "source": "ledger"}))
        sequence += 1
    for item, own in items.items():
        latest = own[-1]
        lane = next((lane_value(r["lane"]) for r in reversed(own) if lane_value(r["lane"])), None)
        fact = resolve(item_link(own), prs)
        done = (fact is not None and fact["state"] in ("merged", "closed")) or latest["state"] in ("landed", "merged")
        needs_owner = not done and latest["state"] in ("needs-ruling", "owner-task")
        if lane is not None:
            begin = len(own) - 1
            while begin > 0 and own[begin - 1]["state"] == latest["state"]:
                begin -= 1
            lanes.append({"lane": lane, "item": item, "state": latest["state"], "since": iso(own[begin]["ts"]),
                          "done": done, "needs_owner": needs_owner, "pr": public_pr(fact) if fact else None})
        if fact is not None:
            for what, at in (("pr-opened", fact["created_at"]), ("pr-merged", fact["merged_at"])):
                moment = parse_time(at) if at else None
                if moment is not None:
                    events.append((moment, 1, sequence, {"at": iso(moment), "item": item, "lane": lane,
                                                         "what": what, "source": "remote"}))
                    sequence += 1
        if not done:
            text = latest["next"].strip()
            upcoming.append({"item": item, "lane": lane, "state": latest["state"],
                             "next": None if text in ("", "-") else text[:NEXT_MAX],
                             "needs_owner": needs_owner, "late": own[0]["ts"] - started > LATE_AFTER})
    events.sort(key=lambda e: e[:3])
    return {"name": ledger["name"], "ledger": ledger["path"], "kind": ledger["kind"],
            "started_at": iso(started), "last_at": iso(last), "lanes": lanes,
            "events": [e[3] for e in events], "upcoming": upcoming}


def build(ledgers: list[dict[str, Any]], prs: dict[int, dict[str, Any]] | None, now: datetime,
          repo: str = "", remote: str | None = None) -> dict[str, Any]:
    """The whole answer. `ledgers` are parse_ledger results, `prs` the forge facts by number (None when the
    forge was not asked or did not answer), `now` only stamps generated_at. No ledger -> {"runs": []}."""
    ledgers = [l for l in ledgers if l and l["rows"]]
    if not ledgers:
        return {"runs": []}
    runs = sorted((build_run(l, prs) for l in ledgers), key=lambda r: r["name"])
    runs.sort(key=lambda r: r["last_at"], reverse=True)
    return {"generated_at": iso(now), "repo": repo, "remote": remote or ("ok" if prs is not None else "skipped"),
            "runs": runs}


# ---------------------------------------------------------------- command line

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plumb-run-view", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=None, help="repository to read (default: the current directory)")
    parser.add_argument("--ledger", action="append", default=[], help="read exactly this ledger (repeatable)")
    parser.add_argument("--since", type=float, default=DEFAULT_SINCE_HOURS,
                        help=f"only ledgers whose last row is within this many hours (default {DEFAULT_SINCE_HOURS:g})")
    parser.add_argument("--no-remote", action="store_true", help="do not ask the forge; every pr is null")
    args = parser.parse_args(argv)
    if args.since < 0:
        parser.error("--since must not be negative")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    repo = os.path.abspath(args.repo or os.getcwd())

    paths = [os.path.abspath(p) for p in args.ledger] if args.ledger else discover(repo)
    ledgers = [l for l in (parse_ledger(p) for p in paths) if l]
    if not args.ledger:
        cutoff = now - timedelta(hours=args.since)
        ledgers = [l for l in ledgers if l["rows"][-1]["ts"] >= cutoff]

    remote, prs = "skipped", None
    if not args.no_remote:
        numbers, branches = collect_links(ledgers)
        remote, prs = fetch_prs(repo, numbers, branches, gh=run_gh)
    print(json.dumps(build(ledgers, prs, now, repo, remote), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
