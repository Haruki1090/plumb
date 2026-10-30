#!/usr/bin/env python3
"""The work ledger, change side: one record per landed change, and the rework rate.

    plumb-ledger changes --repo <owner/name> --since <date> --until <date>
                         [--base <branch>] [--clone <dir>] [--out <jsonl>]
    plumb-ledger rework  --changes <jsonl> --since <date> --until <date>
                         [--lookahead-days N] [--json]

`changes` writes one JSON object per line (to --out, else stdout) and a summary on stderr. Dates are
calendar days in `ledger.timezone` (default UTC); --until is inclusive. Pull requests come from
`gh api` (REST, --paginate, never GraphQL); direct commits and landing detection come from the local
clone (--clone, default the current directory) with `git -C`. A shallow clone that cannot reach the
start of the period exits 2 with the fetch command it needs; nothing is truncated silently.

Record fields: kind (pull_request | direct), number, author, merged_at, merge_commit, landing
(merge | squash | rebase), head_ref, created_at, closed_at, classes, agents, co_authors, sessions,
attribution (complete | incomplete), sources, fixes_pr (list of numbers, [] for `none`, null when
there is no line or it is malformed), fixes_pr_error. A value that cannot be known is null and
counted in the summary. No commit body and no pull request text is written, only the parsed
trailers (Co-Authored-By, Claude-Session, session links) and the Fixes-PR result.

`rework` reads that file. The cohort is the pull requests landed in the period by
`rework.required_authors` (case-insensitive). A cohort change is reworked when a later change by any
author lists it in `fixes_pr` and landed within the look-ahead window (--lookahead-days, else
`rework.lookahead_days`, else 7) after it. A change whose window has not closed and that is not yet
reworked is pending. rate = reworked / (reworked + clean); pending is left out of the rate. Direct
commits are counted apart and never enter the cohort.

The contract is read only through plumb-project, run inside the clone (changes) or the current
directory (rework): repo.base_branch, rework.required_authors, rework.lookahead_days,
ledger.classify, ledger.timezone. An invalid contract exits 2, an unavailable parser exits 3.
Classify globs match the whole repository-relative path: `*` and `?` stop at `/`, `**` does not,
`**/` may match no directory. A file takes the class of the first matching rule; a file that
matches none is `unclassified`, and so is every file when the contract has no rules.

Test hooks (environment):
  PLUMB_LEDGER_GH_FIXTURES  a directory. Each gh call reads a file there instead of running gh. The
                            name is the endpoint without its query string, `/` written as `__`:
                            repos/o/r/pulls/5 -> repos__o__r__pulls__5.json. A paginated call reads
                            <name>.page1.json, <name>.page2.json, ... until the next one is missing
                            and joins the lists. A missing file is an error.
  PLUMB_LEDGER_NOW          an ISO 8601 time that stands for "now" in `rework`.

Exit status: 0 ok, 1 a gh/git call failed or an input is unreadable, 2 usage, an invalid contract or
a shallow clone, 3 no TOML parser for the contract.

Standard library only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
PROJECT_SCRIPT = HERE / "plumb-project.py"
CHECK_FIXES = HERE / "check-fixes.py"
FIXTURES_ENV = "PLUMB_LEDGER_GH_FIXTURES"
NOW_ENV = "PLUMB_LEDGER_NOW"
DEFAULT_LOOKAHEAD_DAYS = 7
UNCLASSIFIED = "unclassified"
FIELD_LIMIT = 200

COAUTHOR = re.compile(r"^co-authored-by:[ \t]*(\S.*?)[ \t]*$", re.IGNORECASE | re.MULTILINE)
SESSION_TRAILER = re.compile(r"^claude-session:[ \t]*(\S.*?)[ \t]*$", re.IGNORECASE | re.MULTILINE)
SESSION_URL = re.compile(r"https?://claude\.ai/code/session_[A-Za-z0-9_-]+")
AGENT_WORDS = (("claude", ("claude", "anthropic")), ("codex", ("codex", "openai")), ("cursor", ("cursor",)))
OTHER_AGENT_WORDS = ("[bot]", "copilot", "gemini", "aider", "devin", "windsurf")


class LedgerError(Exception):
    """A failure with its exit status. The message never quotes a body."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------
# gh (REST only) and its offline fixtures


def fixture_name(endpoint: str, page: int | None = None) -> str:
    name = endpoint.split("?", 1)[0].strip("/").replace("/", "__")
    return f"{name}.json" if page is None else f"{name}.page{page}.json"


def read_fixture(directory: str, endpoint: str, paginate: bool, stop: Any = None) -> Any:
    def load(name: str) -> Any:
        try:
            return json.loads((Path(directory) / name).read_text(encoding="utf-8"))
        except OSError:
            raise LedgerError(1, f"no fixture {name} for {endpoint.split('?', 1)[0]}")
        except ValueError:
            raise LedgerError(1, f"fixture {name} is not JSON")

    if not paginate:
        return load(fixture_name(endpoint))
    first = load(fixture_name(endpoint, 1))
    items: list = list(first)
    page = 2
    while not (stop and first and stop(first)) and (Path(directory) / fixture_name(endpoint, page)).exists():
        first = load(fixture_name(endpoint, page))
        items.extend(first)
        page += 1
    return items


def decode_stream(text: str) -> list:
    """`gh api --paginate` prints each page's JSON one after another (`[..][..]`): read them all."""
    decoder = json.JSONDecoder()
    documents = []
    position = 0
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            return documents
        document, position = decoder.raw_decode(text, position)
        documents.append(document)


def gh_run(endpoint: str) -> Any:
    try:
        done = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True)
    except OSError:
        raise LedgerError(1, "gh is not available (install the GitHub CLI, or set " + FIXTURES_ENV + ")")
    if done.returncode != 0:
        # gh's own first line says why (403, 404, rate limit); it never carries a token.
        reason = (done.stderr.strip().splitlines() or [""])[0][:200]
        raise LedgerError(1, f"gh api {endpoint.split('?', 1)[0]} failed (exit {done.returncode}): {reason}")
    try:
        documents = decode_stream(done.stdout)
    except ValueError:
        raise LedgerError(1, f"gh api {endpoint.split('?', 1)[0]} did not return JSON")
    return documents[0] if documents else None


def gh_get(endpoint: str, paginate: bool = False, stop: Any = None) -> Any:
    """GET one REST endpoint; with `paginate`, every page joined.

    Pages are requested by number (`page=N`) rather than with `gh api --paginate`: --paginate
    follows GitHub's `Link` headers, which name `repositories/{id}/...` paths, and a cloud session's
    proxy refuses those (measured 2026-10-30, HTTP 403). A page shorter than `per_page` is the last.
    `stop(page_items)` true ends the walk after that page (a list sorted by time can stop early).
    """
    directory = os.environ.get(FIXTURES_ENV)
    if directory:
        return read_fixture(directory, endpoint, paginate, stop)
    if not paginate:
        return gh_run(endpoint)
    match = re.search(r"[?&]per_page=(\d+)", endpoint)
    per_page = int(match.group(1)) if match else 30
    joiner = "&" if "?" in endpoint else "?"
    items: list = []
    page = 1
    while True:
        result = gh_run(f"{endpoint}{joiner}page={page}")
        batch = result if isinstance(result, list) else ([result] if result is not None else [])
        items.extend(batch)
        if len(batch) < per_page or (stop and stop(batch)):
            return items
        page += 1


# ---------------------------------------------------------------------------------------------
# contract, dates


def read_contract(cwd: str) -> dict:
    """The whole contract, through plumb-project only. Absent file: an empty dict."""
    try:
        done = subprocess.run([sys.executable, str(PROJECT_SCRIPT), "--json"], capture_output=True,
                              text=True, cwd=cwd)
        answer = json.loads(done.stdout)
    except (OSError, ValueError):
        raise LedgerError(2, "cannot read the project contract through plumb-project")
    outcome = answer.get("outcome")
    if outcome == "absent":
        return {}
    if outcome == "set" and isinstance(answer.get("value"), dict):
        return answer["value"]
    if outcome == "unavailable":
        raise LedgerError(3, f"project contract: {answer.get('message')}")
    raise LedgerError(2, f"project contract: {answer.get('message') or 'unreadable'}")


def contract_value(contract: dict, dotted: str) -> Any:
    node: Any = contract
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_day(text: str, option: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise LedgerError(2, f"{option}: expected a date like 2026-10-31")


def period_bounds(since: str, until: str, timezone_name: str | None) -> tuple:
    """[start, end) as aware datetimes: midnight of --since to midnight after --until, in the zone."""
    first, last = parse_day(since, "--since"), parse_day(until, "--until")
    if last < first:
        raise LedgerError(2, "--until is before --since")
    zone: Any = timezone.utc
    if timezone_name:
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(timezone_name)
        except Exception:
            raise LedgerError(2, "ledger.timezone: this Python cannot load that time zone")
    start = datetime(first.year, first.month, first.day, tzinfo=zone)
    after = last + timedelta(days=1)
    return start, datetime(after.year, after.month, after.day, tzinfo=zone)


# ---------------------------------------------------------------------------------------------
# trailers, Fixes-PR, classes


def agent_of(co_author: str) -> str | None:
    low = co_author.lower()
    for name, words in AGENT_WORDS:
        if any(word in low for word in words):
            return name
    return "other" if any(word in low for word in OTHER_AGENT_WORDS) else None


def scan_messages(messages: list) -> tuple:
    """(co_authors, sessions, agents), each a set, from the trailers of commit messages."""
    co_authors: set = set()
    sessions: set = set()
    agents: set = set()
    for message in messages:
        text = message.replace("\r", "")
        for value in COAUTHOR.findall(text):
            co_authors.add(value[:FIELD_LIMIT])
            agent = agent_of(value)
            if agent:
                agents.add(agent)
        for value in SESSION_TRAILER.findall(text):
            sessions.add(value[:FIELD_LIMIT])
            agents.add("claude")
        for value in SESSION_URL.findall(text):
            sessions.add(value)
            agents.add("claude")
    return co_authors, sessions, agents


def load_check_fixes() -> Any:
    spec = importlib.util.spec_from_file_location("plumb_check_fixes", CHECK_FIXES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_fixes(body: str | None, number: int) -> tuple:
    """(fixes_pr, error). The grammar is check-fixes.py's: its comment stripper, prefix and line check."""
    checker = load_check_fixes()
    text = checker.strip_comments(body or "").replace("\r", "")
    lines = [line for line in text.split("\n") if line.startswith(checker.PREFIX)]
    if not lines:
        return None, None
    if len(lines) > 1:
        return None, f"more than one Fixes-PR line ({len(lines)})"
    value = lines[0][len(checker.PREFIX):]
    try:
        checker.check_line(value, number)
    except checker.NotOk as error:
        return None, str(error)
    value = value.strip(checker.BLANKS)
    if value == "none":
        return [], None
    return [int(item.strip(checker.BLANKS)[1:]) for item in value.split(",")], None


def glob_to_regex(glob: str) -> "re.Pattern[str]":
    out = []
    i = 0
    while i < len(glob):
        char = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[" and glob.find("]", i + 2) != -1:
            end = glob.find("]", i + 2)
            body = glob[i + 1:end]
            out.append("[" + ("^" if body.startswith("!") else "") + body.lstrip("!").replace("\\", "\\\\") + "]")
            i = end
        else:
            out.append(re.escape(char))
        i += 1
    return re.compile("".join(out))


def compile_rules(rules: Any) -> list:
    pairs = []
    for rule in rules or []:
        if isinstance(rule, dict) and isinstance(rule.get("glob"), str) and isinstance(rule.get("class"), str):
            pairs.append((glob_to_regex(rule["glob"]), rule["class"]))
    return pairs


def classify(paths: list, rules: list) -> list:
    classes = set()
    for path in paths:
        for pattern, name in rules:
            if pattern.fullmatch(path):
                classes.add(name)
                break
        else:
            classes.add(UNCLASSIFIED)
    return sorted(classes)


# ---------------------------------------------------------------------------------------------
# the local clone


def git(clone: str, *args: str, check: bool = True) -> str | None:
    try:
        done = subprocess.run(["git", "-C", clone, *args], capture_output=True, text=True, errors="replace")
    except OSError:
        raise LedgerError(1, "git is not available")
    if done.returncode != 0:
        if check:
            raise LedgerError(1, f"git {args[0]} failed in {clone}")
        return None
    return done.stdout


def resolve_base_ref(clone: str, base: str) -> str:
    if git(clone, "rev-parse", "--git-dir", check=False) is None:
        raise LedgerError(2, f"{clone} is not a git repository (--clone)")
    for ref in (f"refs/remotes/origin/{base}", f"refs/heads/{base}"):
        if git(clone, "rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False) is not None:
            return ref
    raise LedgerError(2, f"the clone has neither origin/{base} nor {base}: git -C {clone} fetch origin {base}")


def check_depth(clone: str, ref: str, base: str, start: datetime) -> None:
    """Exit 2 when the clone is shallow and its first-parent history ends inside the period."""
    if (git(clone, "rev-parse", "--is-shallow-repository") or "").strip() != "true":
        return
    shallow_file = Path(clone, (git(clone, "rev-parse", "--git-path", "shallow") or "").strip())
    try:
        boundary = set(shallow_file.read_text().split())
    except OSError:
        return
    chain = (git(clone, "rev-list", "--first-parent", ref) or "").split()
    if not chain or chain[-1] not in boundary:
        return
    oldest = int((git(clone, "show", "-s", "--format=%ct", chain[-1]) or "0").strip())
    if oldest <= start.timestamp():
        return
    since = start.astimezone(timezone.utc).date().isoformat()
    reach = datetime.fromtimestamp(oldest, timezone.utc).date().isoformat()
    raise LedgerError(
        2,
        f"the clone is shallow: depth {len(chain)} on {base}, back to {reach}, but the period starts "
        f"{since} (UTC). Fetch more history and run again:\n"
        f"  git -C {clone} fetch --shallow-since={since} origin {base}\n"
        f"or add commits with: git -C {clone} fetch --deepen=<n> origin {base}  (depth now {len(chain)})")


def commit_facts(clone: str, sha: str) -> tuple | None:
    """(parents, subject) of a commit the clone has, else None."""
    out = git(clone, "show", "-s", "--format=%P%x1f%s", sha + "^{commit}", check=False)
    if out is None:
        return None
    parents, _, subject = out.rstrip("\n").partition("\x1f")
    return parents.split(), subject


def log_messages(clone: str, *args: str) -> list:
    out = git(clone, "log", "--format=%B%x00", *args, check=False) or ""
    return [piece for piece in out.split("\0") if piece.strip()]


def landing_of(parents: list, merge_sha: str, number: int, tip_subject: str, pr_shas: list,
               pr_subjects: list, complete: bool) -> str | None:
    if len(parents) >= 2:
        return "merge"
    if merge_sha in pr_shas:
        return "rebase"
    if tip_subject.endswith(f"(#{number})"):
        return "squash"
    if tip_subject in pr_subjects:
        return "rebase"  # a rebase keeps each commit's message; a squash writes a new one
    return "squash" if complete else None


def land_pull_request(clone: str, merge_sha: str | None, number: int, rest: list, expected: int | None,
                      want_messages: bool) -> tuple:
    """(landing, landed_shas, history_messages). Unknown values are None and an empty set."""
    facts = commit_facts(clone, merge_sha) if merge_sha else None
    if facts is None:
        return None, set(), None
    parents, subject = facts
    pr_shas = [commit.get("sha") for commit in rest]
    pr_subjects = [str(commit["commit"]["message"]).split("\n", 1)[0] for commit in rest]
    complete = expected is not None and expected == len(rest)
    landing = landing_of(parents, merge_sha, number, subject, pr_shas, pr_subjects, complete)
    shas = {merge_sha}
    count = expected if expected else (len(rest) or 1)
    if landing == "rebase":
        shas = set((git(clone, "rev-list", "--first-parent", f"--max-count={count}", merge_sha, check=False)
                    or merge_sha).split())
    messages = None
    if want_messages and landing == "merge":
        messages = log_messages(clone, f"{merge_sha}^1..{merge_sha}^2")
    elif want_messages and landing == "rebase":
        messages = log_messages(clone, "--first-parent", f"--max-count={count}", merge_sha)
    elif want_messages and landing == "squash":
        messages = log_messages(clone, "--max-count=1", merge_sha)
    return landing, shas, messages


def first_parent_commits(clone: str, ref: str) -> list:
    out = git(clone, "log", "--first-parent", "--format=%H%x1f%ct%x1f%an", ref) or ""
    commits = []
    for line in out.splitlines():
        sha, epoch, author = line.split("\x1f", 2)
        commits.append({"sha": sha, "time": datetime.fromtimestamp(int(epoch), timezone.utc), "author": author})
    return commits


def commit_paths(clone: str, sha: str) -> list:
    if commit_facts(clone, sha)[0]:
        out = git(clone, "diff", "--name-only", f"{sha}^1", sha)
    else:
        out = git(clone, "diff-tree", "--root", "-r", "--no-commit-id", "--name-only", sha)
    return (out or "").splitlines()


# ---------------------------------------------------------------------------------------------
# records


def pull_request_record(repo: str, item: dict, clone: str, rules: list) -> tuple:
    """(record, landed_shas)."""
    number = item["number"]
    detail = item if "commits" in item else gh_get(f"repos/{repo}/pulls/{number}")
    expected = detail.get("commits") if isinstance(detail.get("commits"), int) else None
    rest = gh_get(f"repos/{repo}/pulls/{number}/commits?per_page=100", paginate=True)
    files = gh_get(f"repos/{repo}/pulls/{number}/files?per_page=100", paginate=True)
    incomplete = expected is None or expected != len(rest)
    merge_sha = item.get("merge_commit_sha")
    landing, shas, history = land_pull_request(clone, merge_sha, number, rest, expected, incomplete)
    messages = [str(commit["commit"]["message"]) for commit in rest]
    sources = ["pulls_commits"]
    if incomplete and history is not None:
        sources.append("landed_history")
        messages += history
    co_authors, sessions, agents = scan_messages(messages)
    fixes_pr, fixes_error = parse_fixes(item.get("body"), number)
    record = {
        "kind": "pull_request",
        "number": number,
        "author": (item.get("user") or {}).get("login"),
        "merged_at": item.get("merged_at"),
        "merge_commit": merge_sha,
        "landing": landing,
        "head_ref": (item.get("head") or {}).get("ref"),
        "created_at": item.get("created_at"),
        "closed_at": item.get("closed_at"),
        "classes": classify([str(f.get("filename")) for f in files], rules),
        "agents": sorted(agents),
        "co_authors": sorted(co_authors),
        "sessions": sorted(sessions),
        "attribution": "incomplete" if incomplete else "complete",
        "sources": sources,
        "fixes_pr": fixes_pr,
        "fixes_pr_error": fixes_error,
    }
    return record, shas


def direct_record(clone: str, commit: dict, rules: list) -> dict:
    messages = log_messages(clone, "--max-count=1", commit["sha"])
    co_authors, sessions, agents = scan_messages(messages)
    return {
        "kind": "direct",
        "number": None,
        "author": commit["author"],
        "merged_at": iso_utc(commit["time"]),
        "merge_commit": commit["sha"],
        "landing": None,
        "head_ref": None,
        "created_at": None,
        "closed_at": None,
        "classes": classify(commit_paths(clone, commit["sha"]), rules),
        "agents": sorted(agents),
        "co_authors": sorted(co_authors),
        "sessions": sorted(sessions),
        "attribution": "complete",
        "sources": ["landed_history"],
        "fixes_pr": None,
        "fixes_pr_error": None,
    }


def collect(repo: str, base: str, clone: str, start: datetime, end: datetime, rules: list) -> list:
    ref = resolve_base_ref(clone, base)
    check_depth(clone, ref, base, start)
    query = f"state=closed&base={quote(base, safe='')}&sort=updated&direction=desc&per_page=100"
    # Sorted by update time, newest first: once a whole page was last updated before the period,
    # no later page can hold a pull request that landed in it (landing updates the pull request).
    closed = gh_get(f"repos/{repo}/pulls?{query}", paginate=True,
                    stop=lambda page: all(item.get("updated_at") and parse_time(item["updated_at"]) < start
                                         for item in page))
    merged = [item for item in closed if item.get("merged_at")]
    landed = {item["merge_commit_sha"] for item in merged if item.get("merge_commit_sha")}
    records = []
    for item in merged:
        if start <= parse_time(item["merged_at"]) < end:
            record, shas = pull_request_record(repo, item, clone, rules)
            records.append(record)
            landed |= shas
    for commit in first_parent_commits(clone, ref):
        if start <= commit["time"] < end and commit["sha"] not in landed:
            records.append(direct_record(clone, commit, rules))
    records.sort(key=lambda r: (r["merged_at"], r["number"] or 0, r["merge_commit"] or ""))
    return records


def summarize(records: list, repo: str, base: str, since: str, until: str, zone: str, has_rules: bool) -> str:
    pulls = [r for r in records if r["kind"] == "pull_request"]
    direct = [r for r in records if r["kind"] == "direct"]
    landings = {name: sum(1 for r in pulls if r["landing"] == name) for name in ("merge", "squash", "rebase")}
    unknown_landing = sum(1 for r in pulls if r["landing"] is None)
    readable = sum(1 for r in pulls if r["fixes_pr"] is not None)
    malformed = sum(1 for r in pulls if r["fixes_pr_error"])
    absent = len(pulls) - readable - malformed
    classes: dict = {}
    for record in records:
        for name in record["classes"]:
            classes[name] = classes.get(name, 0) + 1
    lines = [
        f"plumb-ledger changes: {repo} {base} {since}..{until} ({zone})",
        f"  pull requests: {len(pulls)} (merge {landings['merge']}, squash {landings['squash']}, "
        f"rebase {landings['rebase']}, landing unknown {unknown_landing})",
        f"  direct commits: {len(direct)}",
        f"  attribution incomplete: {sum(1 for r in pulls if r['attribution'] == 'incomplete')}",
        f"  Fixes-PR line: readable {readable}, malformed {malformed}, absent {absent}",
        "  classes: " + (", ".join(f"{k} {v}" for k, v in sorted(classes.items())) or "none"),
    ]
    if not has_rules:
        lines.append("  note: the contract has no classify rules; every change is unclassified")
    return "\n".join(lines)


def changes_main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="plumb-ledger changes", description="One record per landed change.")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--since", required=True, help="first day, YYYY-MM-DD, in ledger.timezone")
    parser.add_argument("--until", required=True, help="last day (inclusive), YYYY-MM-DD")
    parser.add_argument("--base", help="base branch (default repo.base_branch, else the default branch)")
    parser.add_argument("--clone", default=".", help="local clone for direct commits and landing (default .)")
    parser.add_argument("--out", help="write the JSONL here instead of stdout")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        raise LedgerError(2, "--repo: expected owner/name")
    contract = read_contract(args.clone)
    zone = contract_value(contract, "ledger.timezone")
    start, end = period_bounds(args.since, args.until, zone)
    rules_raw = contract_value(contract, "ledger.classify")
    rules = compile_rules(rules_raw)
    base = args.base or contract_value(contract, "repo.base_branch")
    if not base:
        base = gh_get(f"repos/{args.repo}").get("default_branch")
        if not base:
            raise LedgerError(1, f"repos/{args.repo} has no default_branch")
    records = collect(args.repo, base, args.clone, start, end, rules)
    text = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    if args.out:
        try:
            Path(args.out).write_text(text, encoding="utf-8")
        except OSError:
            raise LedgerError(1, f"cannot write {args.out}")
    else:
        sys.stdout.write(text)
    print(summarize(records, args.repo, base, args.since, args.until, zone or "UTC", bool(rules)), file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------------------------
# rework


def load_records(path: str) -> list:
    records = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        raise LedgerError(1, f"cannot read {path}")
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            raise LedgerError(1, f"{path} line {number} is not JSON")
        if isinstance(record, dict):
            records.append(record)
    return records


def merged_at(record: dict) -> datetime | None:
    try:
        return parse_time(record["merged_at"])
    except (KeyError, TypeError, ValueError):
        return None


def rework_rate(records: list, required: list, start: datetime, end: datetime, days: int, now: datetime) -> dict:
    wanted = {name.strip().lower() for name in required}
    pulls = [(r, merged_at(r)) for r in records if r.get("kind") == "pull_request"]
    pulls = [(r, when) for r, when in pulls if when is not None]
    cohort = [(r, when) for r, when in pulls
              if start <= when < end and str(r.get("author") or "").lower() in wanted]
    reworked, clean, pending = [], [], []
    window = timedelta(days=days)
    for record, when in cohort:
        fixers = sorted(other["number"] for other, later in pulls
                        if when < later <= when + window and record["number"] in (other.get("fixes_pr") or []))
        if fixers:
            reworked.append({"number": record["number"], "fixed_by": fixers})
        elif when + window > now:
            pending.append(record["number"])
        else:
            clean.append(record["number"])
    decided = len(reworked) + len(clean)
    rate = Fraction(len(reworked), decided) if decided else None
    readable = sum(1 for r, _ in cohort if r.get("fixes_pr") is not None)
    direct = sum(1 for r in records if r.get("kind") == "direct"
                 and merged_at(r) is not None and start <= merged_at(r) < end)
    return {
        "lookahead_days": days,
        "cohort": len(cohort),
        "reworked": len(reworked),
        "clean": len(clean),
        "pending": len(pending),
        "rate": float(rate) if rate is not None else None,
        "rate_fraction": f"{rate.numerator}/{rate.denominator}" if rate is not None else None,
        "rate_excludes_pending": True,
        "reworked_changes": reworked,
        "clean_changes": sorted(clean),
        "pending_changes": sorted(pending),
        "readable_fixes_pr": readable,
        "readable_fixes_pr_share": float(Fraction(readable, len(cohort))) if cohort else None,
        "direct_commits": direct,
    }


def render_rework(result: dict, since: str, until: str, zone: str, now: datetime) -> str:
    rate = result["rate"]
    share = result["readable_fixes_pr_share"]
    lines = [
        f"plumb-ledger rework: {since}..{until} ({zone}), look-ahead {result['lookahead_days']} days, "
        f"as of {iso_utc(now)}",
        f"  cohort: {result['cohort']} changes by rework.required_authors",
        f"  reworked: {result['reworked']}",
        f"  clean: {result['clean']}",
        f"  pending: {result['pending']} (window still open; left out of the rate)",
        "  rate: " + (f"{result['rate_fraction']} = {rate * 100:.1f}% (reworked / (reworked + clean))"
                      if rate is not None else "n/a (no change has a closed window)"),
        f"  readable Fixes-PR line: {result['readable_fixes_pr']}/{result['cohort']}"
        + (f" = {share * 100:.1f}%" if share is not None else ""),
        f"  direct commits in the period (not in the cohort): {result['direct_commits']}",
    ]
    for item in result["reworked_changes"]:
        lines.append(f"  reworked #{item['number']} fixed by " + ", ".join(f"#{n}" for n in item["fixed_by"]))
    return "\n".join(lines)


def rework_main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="plumb-ledger rework", description="The rework rate over a period.")
    parser.add_argument("--changes", required=True, help="the JSONL written by `changes`")
    parser.add_argument("--since", required=True, help="first day, YYYY-MM-DD, in ledger.timezone")
    parser.add_argument("--until", required=True, help="last day (inclusive), YYYY-MM-DD")
    parser.add_argument("--lookahead-days", type=int, help="look-ahead window (default rework.lookahead_days, else 7)")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    if args.lookahead_days is not None and args.lookahead_days < 1:
        raise LedgerError(2, "--lookahead-days: expected an integer >= 1")
    contract = read_contract(".")
    zone = contract_value(contract, "ledger.timezone")
    start, end = period_bounds(args.since, args.until, zone)
    required = contract_value(contract, "rework.required_authors") or []
    days = args.lookahead_days or contract_value(contract, "rework.lookahead_days") or DEFAULT_LOOKAHEAD_DAYS
    try:
        now = parse_time(os.environ[NOW_ENV]) if os.environ.get(NOW_ENV) else datetime.now(timezone.utc)
    except ValueError:
        raise LedgerError(2, NOW_ENV + " is not an ISO 8601 time")
    result = rework_rate(load_records(args.changes), required, start, end, days, now)
    if not required:
        print("plumb-ledger rework: the contract has no rework.required_authors; the cohort is empty",
              file=sys.stderr)
    if args.json:
        result.update({"since": args.since, "until": args.until, "timezone": zone or "UTC", "as_of": iso_utc(now)})
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(render_rework(result, args.since, args.until, zone or "UTC", now))
    return 0


def main(argv: list) -> int:
    commands = {"changes": changes_main, "rework": rework_main}
    if not argv or argv[0] not in commands:
        print("usage: plumb-ledger changes|rework ... (see --help)", file=sys.stderr)
        return 2
    try:
        return commands[argv[0]](argv[1:])
    except LedgerError as error:
        print(f"plumb-ledger: {error}", file=sys.stderr)
        return error.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
