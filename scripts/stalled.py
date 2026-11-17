#!/usr/bin/env python3
"""plumb-stalled: every open pull request, by how long it has waited and on whom.

    plumb-stalled [--repo <dir>] [--idle-hours 2] [--verified-pattern <regex>] [--promoted-ref <ref>]
                  [--promoted-limit 50] [--json]

A pure function of (the open pull requests the forge reports), (the clock) and, for `--promoted-ref`, the
local git history: no model, no state file, no cache, and it never writes. Each open pull request gets
exactly one `waiting` value:

  verified-not-ready  a draft whose body carries evidence for its current head (see --verified-pattern):
                      it waits for someone to mark it ready
  ready-unmerged      not a draft: it waits for a reviewer or the owner to merge it
  draft-idle          a draft with no real commit for --idle-hours or more
  draft-active        a draft below that threshold

"Real commit" means a commit with fewer than two parents: a base merge is not work and never resets the
clock. Only the last 20 commits are fetched; if all of them are merges the clock falls back to the creation
time and the row says so (`last_work_at_estimated`).

`--verified-pattern` is a regular expression whose first capture group is a commit SHA (7+ hex). The
pattern is matched against the body with HTML comments removed, and counts only when the captured SHA is a
prefix of the pull request's current head: evidence for an older head is stale. The pattern and the ref
come from the command line; nothing about a repository is built in.

`--promoted-ref` lists the merged pull requests into the base branch (`plumb-project repo.base_branch`,
else the open pull requests' most common base, else the default branch) whose merge commit is not an
ancestor of that ref. Nothing is fetched: a ref or a commit that is not in the local clone makes the answer
`unknown` with the reason, never an empty list. Only the newest --promoted-limit merged pull requests are
checked; when the oldest of them is itself unpromoted the count is a lower bound and the answer says so (`more`).

It never fails the caller: a missing or failing gh gives `remote: unavailable` and exit 0; only bad
command-line usage exits non-zero. `build()` is the whole computation and touches neither disk nor
network (the clock is the `now` argument); `main()` only asks the forge, git, and prints. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_view import iso, parse_time, run_gh  # noqa: E402

BUDGET_SECONDS = 10.0
DEFAULT_IDLE_HOURS = 2.0
DEFAULT_PROMOTED_LIMIT = 50
MAX_PROMOTED_LIMIT = 100
OPEN_LIMIT = 100
TITLE_MAX = 60
MIN_SHA = 7
ORDER = ("verified-not-ready", "ready-unmerged", "draft-idle", "draft-active")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
HEX = re.compile(r"[0-9a-fA-F]+")
PROJECT_SCRIPT = HERE / "plumb-project.py"

OPEN_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: %d, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage }
      nodes {
        number title url isDraft createdAt headRefName headRefOid baseRefName body
        author { login }
        commits(last: 20) { nodes { commit { oid committedDate parents { totalCount } } } }
        timelineItems(last: 1, itemTypes: [READY_FOR_REVIEW_EVENT]) { nodes { ... on ReadyForReviewEvent { createdAt } } }
      }
    }
  }
}
""" % OPEN_LIMIT

# `orderBy` has no merge time: ask for the most recently updated, then order by `mergedAt` here.
MERGED_QUERY = """
query($owner: String!, $name: String!, $base: String!) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, baseRefName: $base, first: %d, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title mergedAt author { login } mergeCommit { oid } }
    }
  }
}
"""


# ---------------------------------------------------------------- the forge

def graphql(gh, repo: str, query: str, fields: dict[str, str], timeout: float) -> dict[str, Any]:
    """The `data.repository` object of one GraphQL call, or ValueError when the answer is not that."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in fields.items():
        args += ["-f", f"{key}={value}"]
    done = gh(args, repo, timeout)
    if done.returncode != 0:
        raise ValueError("gh api graphql failed")
    node = json.loads(done.stdout)["data"]["repository"]
    if not isinstance(node, dict):
        raise ValueError("no repository in the answer")
    return node


def nodes_of(connection: Any) -> list[dict[str, Any]]:
    items = connection.get("nodes") if isinstance(connection, dict) else None
    return [n for n in items if isinstance(n, dict)] if isinstance(items, list) else []


def fetch_open(repo: str, budget: float = BUDGET_SECONDS, gh=run_gh) -> tuple[str, dict[str, Any] | None]:
    """("ok", {owner, name, default_branch, prs, truncated, deadline}) or ("unavailable", None). Any failure,
    a missing gh, a timeout or an unreadable answer is unavailable: no partial answer."""
    deadline = time.monotonic() + budget
    try:
        done = gh(["repo", "view", "--json", "owner,name,defaultBranchRef"], repo, max(deadline - time.monotonic(), 0.1))
        if done.returncode != 0:
            return "unavailable", None
        info = json.loads(done.stdout)
        owner, name = str(info["owner"]["login"]), str(info["name"])
        default = (info.get("defaultBranchRef") or {}).get("name")
        node = graphql(gh, repo, OPEN_QUERY, {"owner": owner, "name": name}, max(deadline - time.monotonic(), 0.1))
        connection = node["pullRequests"]
        prs = nodes_of(connection)
        truncated = bool((connection.get("pageInfo") or {}).get("hasNextPage"))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return "unavailable", None
    return "ok", {"owner": owner, "name": name, "default_branch": default, "prs": prs, "truncated": truncated,
                  "deadline": deadline}


def fetch_merged(info: dict[str, Any], base: str, limit: int, repo: str, gh=run_gh) -> list[dict[str, Any]] | None:
    """The newest `limit` merged pull requests into `base`, or None when the forge does not answer."""
    try:
        node = graphql(gh, repo, MERGED_QUERY % limit, {"owner": info["owner"], "name": info["name"], "base": base},
                       max(info["deadline"] - time.monotonic(), 0.1))
        found = nodes_of(node["pullRequests"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
    merged = []
    for raw in found:
        moment = parse_time(raw.get("mergedAt")) if isinstance(raw.get("mergedAt"), str) else None
        if moment is not None and isinstance(raw.get("number"), int):
            merged.append({"number": raw["number"], "title": str(raw.get("title") or ""), "merged": moment,
                           "author": author_of(raw), "oid": str((raw.get("mergeCommit") or {}).get("oid") or "")})
    merged.sort(key=lambda m: (m["merged"], m["number"]), reverse=True)
    return merged[:limit]


def contract_base(repo: str) -> str | None:
    """`repo.base_branch` through plumb-project, or None when it is absent, invalid or unreadable."""
    try:
        done = subprocess.run([sys.executable, str(PROJECT_SCRIPT), "repo.base_branch"], cwd=repo, capture_output=True,
                              text=True, timeout=BUDGET_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    value = done.stdout.strip()
    return value if done.returncode == 0 and value else None


def pick_base(contract: str | None, open_prs: list[dict[str, Any]], default: str | None) -> str | None:
    """The contract's base branch; else the most common base of the open pull requests (ties: the name that
    sorts first); else the default branch."""
    if contract:
        return contract
    bases = Counter(str(p["baseRefName"]) for p in open_prs if p.get("baseRefName"))
    if bases:
        return sorted(bases.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return default or None


# ---------------------------------------------------------------- one pull request

def author_of(raw: dict[str, Any]) -> str:
    who = raw.get("author")
    return str(who.get("login") or "-") if isinstance(who, dict) else "-"


def last_work(raw: dict[str, Any]) -> tuple[datetime | None, bool]:
    """(time of the newest commit with fewer than two parents, False), or (creation time, True) when every
    fetched commit is a merge or none parses. (None, True) when the creation time does not parse either."""
    newest = None
    for node in nodes_of(raw.get("commits")):
        commit = node.get("commit")
        if not isinstance(commit, dict):
            continue
        parents = (commit.get("parents") or {}).get("totalCount")
        moment = parse_time(commit["committedDate"]) if isinstance(commit.get("committedDate"), str) else None
        if moment is None or not isinstance(parents, int) or parents >= 2:
            continue
        newest = moment if newest is None or moment > newest else newest
    if newest is not None:
        return newest, False
    created = parse_time(raw["createdAt"]) if isinstance(raw.get("createdAt"), str) else None
    return created, True


def verified_head(body: str, head: str, pattern: re.Pattern[str] | None) -> str | None:
    """The SHA the body vouches for when it is a prefix of `head`, else None. HTML comments are removed
    first, so a placeholder inside one cannot match. Any match for the current head counts; one for another
    head does not."""
    if pattern is None or not head:
        return None
    for found in pattern.finditer(COMMENT.sub("", body or "")):
        sha = (found.group(1) or "").lower() if pattern.groups else ""
        if len(sha) >= MIN_SHA and HEX.fullmatch(sha) and head.lower().startswith(sha):
            return sha
    return None


def classify(raw: dict[str, Any], now: datetime, idle_hours: float, pattern: re.Pattern[str] | None) -> dict[str, Any] | None:
    """One open pull request as a row, or None when it has no usable number or time."""
    number = raw.get("number")
    if not isinstance(number, int):
        return None
    worked, estimated = last_work(raw)
    created = parse_time(raw["createdAt"]) if isinstance(raw.get("createdAt"), str) else None
    draft = bool(raw.get("isDraft"))
    ready_at = None
    if not draft:
        events = [parse_time(n["createdAt"]) for n in nodes_of(raw.get("timelineItems")) if isinstance(n.get("createdAt"), str)]
        ready_at = max((e for e in events if e), default=None) or created
        since, waiting, verified = ready_at, "ready-unmerged", None
    else:
        since = worked
        verified = verified_head(str(raw.get("body") or ""), str(raw.get("headRefOid") or ""), pattern)
        if verified:
            waiting = "verified-not-ready"
        elif since is not None and (now - since).total_seconds() >= idle_hours * 3600:
            waiting = "draft-idle"
        else:
            waiting = "draft-active"
    if since is None:
        return None
    return {"number": number, "title": str(raw.get("title") or ""), "url": str(raw.get("url") or ""), "author": author_of(raw),
            "draft": draft, "waiting": waiting, "last_work_at": iso(worked) if worked else None,
            "last_work_at_estimated": estimated, "ready_at": iso(ready_at) if ready_at else None,
            "hours": round(max((now - since).total_seconds(), 0.0) / 3600, 1), "verified_head": verified,
            "_sort": max((now - since).total_seconds(), 0.0)}


# ---------------------------------------------------------------- promotion

def git_ancestor(repo: str, commit: str, ref: str) -> bool | None:
    """Whether `commit` is an ancestor of `ref`; None when git cannot say (a commit not in the clone)."""
    try:
        done = subprocess.run(["git", "merge-base", "--is-ancestor", commit, ref], cwd=repo, capture_output=True, text=True,
                              timeout=BUDGET_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(done.returncode)


def git_has_ref(repo: str, ref: str) -> bool:
    try:
        done = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=repo, capture_output=True,
                              text=True, timeout=BUDGET_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def unpromoted(repo: str, ref: str | None, base: str | None, merged: list[dict[str, Any]] | None, now: datetime,
               skipped_reason: str = "", limit: int | None = None) -> dict[str, Any]:
    """The merged pull requests whose merge commit is not in `ref`. `merged` is None when the forge did not
    answer. Anything git cannot decide makes the whole answer `unknown`: an empty list must mean "all
    promoted", never "could not tell". `limit` is how many merged pull requests were asked for: when that many
    came back and the oldest of them is itself unpromoted, older unpromoted ones may exist, and `more` says so."""
    out: dict[str, Any] = {"ref": ref, "base": base, "count": None, "oldest_merged_at": None, "items": [], "more": False,
                           "state": "skipped", "reason": skipped_reason or "no --promoted-ref"}
    if ref is None:
        return out

    def unknown(reason: str) -> dict[str, Any]:
        return {**out, "state": "unknown", "reason": reason}

    if merged is None:
        return unknown("the forge did not list the merged pull requests")
    if not git_has_ref(repo, ref):
        return unknown(f"{ref} is not in the local clone (nothing is fetched)")
    missing, listed = 0, []
    for pr in merged:
        verdict = git_ancestor(repo, pr["oid"], ref) if pr["oid"] else None
        if verdict is None:
            missing += 1
        elif not verdict:
            listed.append(pr)
    if missing:
        return unknown(f"{missing} of {len(merged)} merge commits are not in the local clone (nothing is fetched)")
    listed.sort(key=lambda p: (p["merged"], p["number"]))
    oldest = min(merged, key=lambda p: (p["merged"], p["number"]), default=None)
    more = bool(limit is not None and len(merged) >= limit and oldest is not None and listed and listed[0] is oldest)
    return {**out, "count": len(listed), "more": more, "state": "ok", "reason": "",
            "oldest_merged_at": iso(listed[0]["merged"]) if listed else None,
            "items": [{"number": p["number"], "title": p["title"], "author": p["author"], "merged_at": iso(p["merged"]),
                       "hours": round(max((now - p["merged"]).total_seconds(), 0.0) / 3600, 1)} for p in listed]}


# ---------------------------------------------------------------- the view

def build(prs: list[dict[str, Any]] | None, now: datetime, idle_hours: float = DEFAULT_IDLE_HOURS,
          pattern: re.Pattern[str] | None = None, repo: str = "", promotion: dict[str, Any] | None = None,
          truncated: bool = False) -> dict[str, Any]:
    """The whole answer. `prs` are the forge's open pull request nodes (None: the forge did not answer),
    `now` is the clock, `promotion` an `unpromoted()` result. Rows are grouped in ORDER, oldest first."""
    rows = [r for r in (classify(p, now, idle_hours, pattern) for p in prs or []) if r]
    rows.sort(key=lambda r: (ORDER.index(r["waiting"]), -r["_sort"], r["number"]))
    for row in rows:
        del row["_sort"]
    doc: dict[str, Any] = {"generated_at": iso(now), "repo": repo, "remote": "ok" if prs is not None else "unavailable",
                           "idle_hours": idle_hours, "open": rows}
    if truncated:
        doc["open_truncated"] = True
    doc["unpromoted"] = promotion or unpromoted(repo, None, None, None, now)
    return doc


def plain(text: Any) -> str:
    """A forge string made safe for a terminal: every control character (an escape sequence, a newline) is `?`."""
    return CONTROL.sub("?", str(text))


def clip(title: str) -> str:
    title = " ".join(plain(title).split())
    return title if len(title) <= TITLE_MAX else title[:TITLE_MAX - 3] + "..."


def render(doc: dict[str, Any]) -> str:
    """The human table: grouped, oldest first, one row per pull request."""
    if doc["remote"] != "ok":
        return "remote: unavailable"
    lines: list[str] = []
    for waiting in ORDER[:3]:
        group = [r for r in doc["open"] if r["waiting"] == waiting]
        if not group:
            continue
        lines.append(f"{waiting} ({len(group)})")
        for r in group:
            est = "~" if waiting != "ready-unmerged" and r["last_work_at_estimated"] else ""
            lines.append(f"  #{r['number']}  {est}{r['hours']:g}h  {plain(r['author'])}  {clip(r['title'])}")
    active = sum(1 for r in doc["open"] if r["waiting"] == "draft-active")
    lines.append(f"draft-active: {active}")
    if doc.get("open_truncated"):
        lines.append(f"note: more open pull requests exist than the first {OPEN_LIMIT} read here")
    un = doc["unpromoted"]
    if un["state"] == "ok":
        head = f"unpromoted into {plain(un['ref'])} (merged into {plain(un['base'])}): {un['count']}"
        lines.append(head + (f", oldest merged {un['oldest_merged_at']}" if un["count"] else ""))
        if un.get("more"):
            lines.append("  note: at least this many; the oldest merged pull request checked is itself unpromoted, "
                         "so older ones may exist (raise --promoted-limit)")
        lines += [f"  #{i['number']}  {i['hours']:g}h  {plain(i['author'])}  {clip(i['title'])}" for i in un["items"]]
    elif un["state"] == "unknown":
        lines.append(f"unpromoted into {plain(un['ref'])}: unknown ({plain(un['reason'])})")
    lines.append("hours: verified-not-ready, draft-idle: since the newest non-merge commit (~ = pull request creation, "
                 "no such commit in the last 20); ready-unmerged: since marked ready (else created); unpromoted: since merged.")
    return "\n".join(lines)


# ---------------------------------------------------------------- command line

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plumb-stalled", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=None, help="repository to read (default: the current directory)")
    parser.add_argument("--idle-hours", type=float, default=DEFAULT_IDLE_HOURS,
                        help=f"a draft with no real commit this long is idle (default {DEFAULT_IDLE_HOURS:g})")
    parser.add_argument("--verified-pattern", default=None,
                        help="regex whose first capture group is a SHA; a draft whose body vouches for its head is verified-not-ready")
    parser.add_argument("--promoted-ref", default=None, help="list merged pull requests whose merge commit is not in this local ref")
    parser.add_argument("--promoted-limit", type=int, default=DEFAULT_PROMOTED_LIMIT,
                        help=f"how many merged pull requests to check (default {DEFAULT_PROMOTED_LIMIT}, at most {MAX_PROMOTED_LIMIT})")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the table")
    args = parser.parse_args(argv)
    if args.idle_hours < 0:
        parser.error("--idle-hours must not be negative")
    if not 1 <= args.promoted_limit <= MAX_PROMOTED_LIMIT:
        parser.error(f"--promoted-limit must be between 1 and {MAX_PROMOTED_LIMIT}")
    if args.promoted_ref is not None and (not args.promoted_ref or args.promoted_ref.startswith("-")):
        parser.error("--promoted-ref must be a ref name")
    pattern = None
    if args.verified_pattern is not None:
        try:
            pattern = re.compile(args.verified_pattern)
        except re.error as error:
            parser.error(f"--verified-pattern is not a regular expression: {error}")
        if pattern.groups < 1:
            parser.error("--verified-pattern needs a capture group: the first group is the SHA")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    repo = str(Path(args.repo or ".").resolve())

    remote, info = fetch_open(repo, gh=run_gh)
    promotion = None
    if info is not None and args.promoted_ref is not None:
        base = pick_base(contract_base(repo), info["prs"], info["default_branch"])
        merged = fetch_merged(info, base, args.promoted_limit, repo, gh=run_gh) if base else None
        promotion = unpromoted(repo, args.promoted_ref, base, merged, now, limit=args.promoted_limit)
    elif args.promoted_ref is not None:
        promotion = unpromoted(repo, args.promoted_ref, None, None, now)
    doc = build(info["prs"] if info else None, now, args.idle_hours, pattern, repo, promotion, bool(info and info["truncated"]))
    print(json.dumps(doc, indent=2, ensure_ascii=False) if args.json else render(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
