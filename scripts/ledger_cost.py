"""Cost per task: capture, price, store, export, task assignment and the weekly report.

    plumb-ledger capture [--hook-input <file> | --transcript <path> | --transcripts <dir> | --sweep]
                         [--runtime claude|codex|opencode] [--cwd <dir>] [--json]
    plumb-ledger export  [--session <id>] [--runtime claude|codex|opencode] [--check] [--ledger-dir <dir>]
    plumb-ledger prs     --repo <owner/name> --since <date> [--out <json>]
    plumb-ledger report  --since <date> --until <date> [--prs <json>] [--changes <jsonl>]...
                         [--rework <json>] [--store-cache <dir>] [--json]
    plumb-ledger views   --since <date> --until <date> --out <dir> [--changes <jsonl>]... [--prs <json>]...
                         [--gap-minutes 30] [--repo <owner/name>] [--timezone <tz>]   (scripts/ledger_views.py)

scripts/ledger.py dispatches here with argv[0] naming the subcommand. See each subcommand's --help.

What leaves the transcript is the allowlist in FIELDS and nothing else: no message text, no tool
input or output, no path, no credential. A number that cannot be known is None (null) and counted,
never zero. Money is summed with decimal.Decimal and rounded only for display.

Standard library only. GitHub is reached only through `gh api` (REST), one numbered page at a
time (never --paginate, which a cloud session's proxy refuses); setting PLUMB_LEDGER_GH_FIXTURES=<dir> reads recorded pages
from that directory instead (offline tests): for `repos/o/n/pulls?state=all` the files are
`repos__o__n__pulls.page1.json`, `.page2.json`, ... (the query is ignored), each a JSON array.
"""
from __future__ import annotations

import argparse
import bisect
import contextlib
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

SCRIPTS = Path(__file__).resolve().parent
PLUGIN = SCRIPTS.parent
PRICES_FILE = PLUGIN / "assets" / "prices.json"

# The only keys a record carries, in this order. Everything that is written to a pending file,
# an exported file or the store passes through project().
FIELDS = ("id", "time", "model", "input", "output", "cache_read", "cache_write_5m",
          "cache_write_1h", "repository", "branch", "attribution_source", "role", "agent_type",
          "agent_id", "session", "runtime", "remote_session")
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
# `transcript` and `worktree_at_capture` are no longer written but old records in stores hold them.
SOURCES = ("reflog", "transcript", "worktree_at_capture", "unknown")
RUNTIMES = ("claude", "codex", "opencode")
SWEPT = ("codex", "opencode")   # the runtimes `capture --sweep` reads; Claude is captured by its own Stop hook
FRONTIER = ("fable", "mythos", "opus")
SAFE = re.compile(r"[\w./@+:#=,%~\-\[\]]{1,200}")
SAFE_SESSION = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")
# The cloud session id the runtime exposes as `<prefix>_<id>`; a record keeps `<id>`, the part a
# commit's `Claude-Session: https://claude.ai/code/session_<id>` trailer carries.
REMOTE_SESSION_ENV = "CLAUDE_CODE_REMOTE_SESSION_ID"
CURRENT_SESSION_ENV = "CLAUDE_CODE_SESSION_ID"   # the running session's own transcript id
REMOTE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
REMOTE_VALUE = re.compile(r"[A-Za-z0-9]+_([A-Za-z0-9][A-Za-z0-9_-]{0,63})")
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
HOOK_TEMP_PREFIX = "plumb-ledger-hook."
# Under refs/heads/: a cloud session's git proxy accepts branch pushes (forced ones too) but drops a
# push to any other ref namespace (measured 2026-10-30). The store holds nothing but these branches.
STORE_REFS = "refs/heads/plumb-ledger"
GIT_TIMEOUT = 120
PREFLIGHT_TIMEOUT = 20


class LedgerError(Exception):
    """A defined failure: the message is safe to print."""


# ---------------------------------------------------------------- small helpers

def run(cmd: list[str], cwd: str | None = None, env: dict[str, str] | None = None,
        timeout: int = 30, stdin: str | None = None) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, input=stdin, capture_output=True, text=True,
                              errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def redact(text: str) -> str:
    """Drop credentials from anything printed: userinfo in a URL, token-looking query values."""
    text = re.sub(r"(://)[^/@\s]*@", r"\1***@", text)
    return re.sub(r"(?i)\b(access_token|token|password|secret|key)=[^&\s]+", r"\1=***", text)


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return redact(line.strip())[:300]
    return ""


def config(key: str, default: str = "") -> str:
    out = run(["bash", str(SCRIPTS / "plumb-config.sh"), key, default])
    return out.stdout.strip() if out and out.returncode == 0 else default


def integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def clean(value: Any, limit: int = 200) -> str | None:
    """A short token-like string, or None. Nothing free-form passes."""
    if isinstance(value, str) and len(value) <= limit and SAFE.fullmatch(value):
        return value
    return None


def safe_session(value: str) -> str:
    """A session id that is also a valid ref component; anything else becomes a stable hash."""
    if (SAFE_SESSION.fullmatch(value) and ".." not in value and not value.endswith((".", ".lock"))):
        return value
    return "x-" + hashlib.sha1(value.encode("utf-8", "replace")).hexdigest()[:20]


def remote_session_from_env(env: Any = None, session: str | None = None) -> str | None:
    """`<id>` of `CLAUDE_CODE_REMOTE_SESSION_ID=<prefix>_<id>`, or None when the variable is absent
    (a local session) or does not have that shape.

    The id belongs to the session that is running this process, not to every transcript it reads:
    `session` (the transcript's session id, which its subagents share) must equal
    `CLAUDE_CODE_SESSION_ID`, the id of the running session's own transcript. Another session's
    transcript (`capture --transcripts <dir>`), or a run where that variable is missing, records None
    rather than a wrong id. `session=None` skips this check."""
    env = os.environ if env is None else env
    if session is not None and (not session or env.get(CURRENT_SESSION_ENV) != session):
        return None
    value = env.get(REMOTE_SESSION_ENV)
    match = REMOTE_VALUE.fullmatch(value) if isinstance(value, str) else None
    return match.group(1) if match else None


def cloud_remote_session() -> str | None:
    """`remote_session` of a Codex or OpenCode record: the cloud session id, only when this process
    runs inside that cloud session's own container (`CLAUDE_CODE_REMOTE=true`), which holds that
    session's work and nothing else. Elsewhere (a laptop, also one driven by Remote Control) the
    variable can name a session these transcripts do not belong to, so the record gets None."""
    return remote_session_from_env(session=None) if os.environ.get("CLAUDE_CODE_REMOTE") == "true" else None


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def timestamp_seconds(value: Any) -> int | None:
    """Whole unix seconds of a transcript timestamp, or None when it is not a time."""
    moment = parse_time(value)
    return int(moment.timestamp()) if moment else None


def format_time(moment: datetime) -> str:
    return moment.strftime(TIME_FORMAT)[:-4] + "Z"  # milliseconds


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(directory: Path, name: str = "capture.lock") -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / name, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


_MODULES: dict[str, Any] = {}


def load_module(name: str, filename: str) -> Any:
    if name in _MODULES:
        return _MODULES[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULES[name] = module
    return module


# ---------------------------------------------------------------- records

def project(raw: Any) -> dict[str, Any] | None:
    """Reduce anything to the allowlisted record, or None when it is not a record."""
    if not isinstance(raw, dict):
        return None
    moment = parse_time(raw.get("time"))
    record: dict[str, Any] = {
        "id": clean(raw.get("id")),
        "time": format_time(moment) if moment else None,
        "model": clean(raw.get("model"), 100),
    }
    for key in TOKEN_FIELDS:
        record[key] = integer(raw.get(key))
    record["repository"] = clean(raw.get("repository"))
    record["branch"] = clean(raw.get("branch"))
    source = raw.get("attribution_source")
    record["attribution_source"] = source if source in SOURCES else "unknown"
    role = raw.get("role")
    record["role"] = role if role in ("main", "subagent") else "main"
    record["agent_type"] = clean(raw.get("agent_type"), 100)
    record["agent_id"] = clean(raw.get("agent_id"), 100)
    session = clean(raw.get("session"), 130)
    record["session"] = session
    runtime = raw.get("runtime")
    record["runtime"] = runtime if runtime in RUNTIMES else None
    remote = raw.get("remote_session")   # absent in records captured before 0.20.0: null
    record["remote_session"] = remote if isinstance(remote, str) and REMOTE_ID.fullmatch(remote) else None
    if session is None or record["runtime"] is None:
        return None
    return record


def record_line(record: dict[str, Any]) -> str:
    return json.dumps({key: record[key] for key in FIELDS}, separators=(",", ":"))


def load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return records
    for line in text.splitlines():
        try:
            record = project(json.loads(line))
        except ValueError:
            continue
        if record is not None:
            records.append(record)
    return records


def sort_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (record["time"] or "", record["id"] or "", record_line(record))


def tokens_of(record: dict[str, Any]) -> tuple[Any, ...]:
    return (record["model"],) + tuple(record[key] for key in TOKEN_FIELDS)


def unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact repeats of rows that have an id (a pending line that is also in the exported file).
    Same id with a different payload is a conflict, handled by the caller; here only identical lines
    merge. A row without an id is never merged with another: two equal unidentified rows are two
    requests, so every one of them is kept."""
    seen: set[str] = set()
    out = []
    for record in sorted(records, key=sort_key):
        if record["id"] is not None:
            line = record_line(record)
            if line in seen:
                continue
            seen.add(line)
        out.append(record)
    return out


# ---------------------------------------------------------------- where things live

def git_top(cwd: str | None) -> str | None:
    if not cwd:
        return None
    out = run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], timeout=10)
    top = out.stdout.strip() if out and out.returncode == 0 else ""
    return top or None


def ledger_dir(cwd: str | None, create: bool) -> Path:
    """~/.claude/plumb/ledger, or PLUMB_LEDGER_DIR. The same place for every repository.

    Records are the personal layer: they never go under a product repository (no run root, no
    `.plumb/.gitignore` created by a background hook). Each record carries its repository, so one
    directory serves every checkout. `cwd` is accepted for callers and ignored.
    """
    override = os.environ.get("PLUMB_LEDGER_DIR")
    path = Path(override) if override else Path.home() / ".claude" / "plumb" / "ledger"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def ledger_dirs(cwd: str | None, extra: list[str]) -> list[Path]:
    found: list[Path] = [Path(item) for item in extra]
    if not found:
        found.append(ledger_dir(cwd, False))
    out: list[Path] = []
    for path in found:
        if path.is_dir() and path.resolve() not in [item.resolve() for item in out]:
            out.append(path)
    return out


def session_files(directory: Path, kind: str) -> list[tuple[str, str, Path]]:
    """(runtime, session, path) for every file under <directory>/<kind>/<runtime>/."""
    found = []
    for runtime in RUNTIMES:
        folder = directory / kind / runtime
        if folder.is_dir():
            for path in sorted(folder.glob("*.jsonl")):
                found.append((runtime, path.stem, path))
    return found


# ---------------------------------------------------------------- git facts about a checkout

def normalize_remote(url: str) -> str | None:
    """A remote URL to owner/name. Credentials in the URL are never kept."""
    url = url.strip()
    match = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://(?:[^/@]*@)?[^/]*/(.+)$", url)
    if not match:
        match = re.match(r"^(?:[^@/:]+@)?[^/:]+:(.+)$", url)  # git@host:owner/name
    path = match.group(1) if match else url
    path = re.sub(r"\.git/?$", "", path.strip("/"))
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return None
    name = "/".join(parts[-2:])
    return name if SAFE.fullmatch(name) else None


UNDECIDED = object()   # branch_at(): the reflog cannot say, so the older evidence applies
FULL_HASH = re.compile(r"[0-9a-f]{4,64}")   # a full or abbreviated hash checked out by itself
NOT_A_BRANCH = re.compile(r"[~^:?*\[\\\s]|\.\.|@\{")   # revision syntax (HEAD~1, x^, @{-1}): detaches HEAD
REFLOG_LINE = re.compile(r"HEAD@\{(\d+)\}\t(.*)")
REFLOG_MOVE = re.compile(r"checkout: moving from (\S+) to (\S+)")      # also what `git switch` writes
REFLOG_RENAME = re.compile(r"Branch: renamed refs/heads/(\S+) to refs/heads/(\S+)")
REFLOG_RETURN = re.compile(r".*\((?:finish|abort)\): returning to refs/heads/(\S+)")  # rebase, pull --rebase
REFLOG_REBASE = re.compile(r".*\(start\): checkout \S+")    # rebase, rebase -i, pull --rebase: HEAD detaches


class Reflog:
    """One worktree's HEAD reflog, reduced to what attribution needs.

    `oldest` is the oldest timestamp of any line: the log says nothing about earlier times.
    `events` are the branch-changing lines, oldest first: (unix seconds, branch before, branch
    after, is a rename). A rebase start does not write the branch it leaves, so its "before" is
    None and its "after" is `HEAD`. `times` and `rename_times` let branch_at() bisect."""

    def __init__(self, oldest: int, events: list[tuple[int, str | None, str, bool]]) -> None:
        self.oldest = oldest
        self.events = events
        self.times = [event[0] for event in events]
        self.renames = [event for event in events if event[3]]
        self.rename_times = [event[0] for event in self.renames]


def parse_reflog(text: str) -> Reflog | None:
    """The Reflog of `git reflog show --date=unix` output, or None when no line parses. A name may
    be a hash, `HEAD`, a tag or `origin/x` (a detached HEAD); the caller decides. Every other
    subject leaves the branch name alone."""
    events: list[tuple[int, str | None, str, bool]] = []
    oldest = None
    for line in text.splitlines():
        parsed = REFLOG_LINE.fullmatch(line)
        if not parsed:
            continue
        when, subject = int(parsed.group(1)), parsed.group(2)
        oldest = when if oldest is None else min(oldest, when)
        if move := REFLOG_MOVE.fullmatch(subject):
            events.append((when, move.group(1), move.group(2), False))
        elif rename := REFLOG_RENAME.fullmatch(subject):
            events.append((when, rename.group(1), rename.group(2), True))
        elif back := REFLOG_RETURN.fullmatch(subject):
            events.append((when, back.group(1), back.group(1), False))
        elif REFLOG_REBASE.fullmatch(subject):
            events.append((when, None, "HEAD", False))
    events.reverse()   # git prints the newest first; the order inside one second is kept
    return None if oldest is None else Reflog(oldest, events)


class Checkouts:
    """Cached, read-only questions about checkouts, asked at capture time."""

    def __init__(self) -> None:
        self.cache: dict[tuple[str, ...], Any] = {}

    def ask(self, key: tuple[str, ...], cmd: list[str]) -> Any:
        if key not in self.cache:
            out = run(cmd, timeout=10)
            self.cache[key] = out.stdout.strip() if out and out.returncode == 0 else None
        return self.cache[key]

    def top(self, path: str) -> str | None:
        return self.ask(("top", path), ["git", "-C", path, "rev-parse", "--show-toplevel"]) or None

    def repository(self, path: str) -> str | None:
        url = self.ask(("origin", path), ["git", "-C", path, "remote", "get-url", "origin"])
        return normalize_remote(url) if url else None

    def has_branch(self, path: str, branch: str) -> bool:
        for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
            if self.ask(("ref", path, ref), ["git", "-C", path, "rev-parse", "--verify", "--quiet", ref]):
                return True
        return False

    def head_branch(self, path: str) -> str | None:
        # The full ref, not --short: --short says `heads/x` when a tag `x` also exists.
        ref = self.ask(("head", path), ["git", "-C", path, "symbolic-ref", "-q", "HEAD"])
        return ref[len("refs/heads/"):] if ref and ref.startswith("refs/heads/") else None

    def moves(self, top: str) -> Reflog | None:
        """This worktree's HEAD reflog, read once per worktree (the HEAD reflog is per worktree).
        None when it cannot be read or is empty."""
        key = ("moves", top)
        if key not in self.cache:
            text = self.ask(("reflog", top), ["git", "-C", top, "reflog", "show", "--date=unix",
                                              "--format=%gd%x09%gs", "HEAD"])
            self.cache[key] = parse_reflog(text) if text else None
        return self.cache[key]

    def names_branch(self, top: str, name: str) -> bool:
        """False for a hash, `HEAD`, a tag or a remote-tracking ref: checking those out detaches HEAD.
        A branch that exists now is a branch even when a tag or remote has the same name (git
        checks the branch out)."""
        if name == "HEAD" or NOT_A_BRANCH.search(name):
            return False

        def exists(ref: str) -> bool:
            return bool(self.ask(("ref", top, ref), ["git", "-C", top, "rev-parse", "--verify", "--quiet", ref]))
        if exists(f"refs/heads/{name}"):
            return True
        if FULL_HASH.fullmatch(name) and exists(f"{name}^{{commit}}"):
            return False                               # a hash; a deleted branch named like one is still a branch
        return not (exists(f"refs/tags/{name}") or exists(f"refs/remotes/{name}"))

    def branch_at(self, path: str, when: int | None) -> Any:
        """The branch the worktree's HEAD named at `when` (unix seconds): a name, None for a
        detached HEAD, or UNDECIDED when the reflog cannot say.

        The first branch-changing event after `when` says which branch HEAD was on before it; with
        none, HEAD has not moved since and still names the current branch. Later renames are
        followed so the name is the one a pull request will use. A deleted branch keeps its name.

        UNDECIDED: no reflog; `when` before the reflog's oldest line (it only covers time since
        then); the first later event is a rebase start (which does not write the branch it leaves)
        and no earlier event names one; or, with no later event, the last event's branch is not the
        current HEAD (something moved HEAD without writing the reflog)."""
        top = self.top(path)
        log = self.moves(top) if top and when is not None else None
        if log is None or when < log.oldest:
            return UNDECIDED
        index = bisect.bisect_right(log.times, when)   # same second as `when`: already happened
        if index < len(log.events):
            before = log.events[index][1]
            if before is None:                         # a rebase started: the branch is the one last moved to
                if index == 0:
                    return UNDECIDED
                before = log.events[index - 1][2]
            name = before
            if not self.names_branch(top, name):
                return None
        else:
            name = self.head_branch(top)
            if log.events:
                last = log.events[-1][2]
                last = last if self.names_branch(top, last) else None
                if last != name:
                    return UNDECIDED
            if name is None:
                return None
        for _, before, after, _ in log.renames[bisect.bisect_right(log.rename_times, when):]:
            if before == name:
                name = after
        return name

    def from_reflog(self, path: str, when: int | None) -> tuple[str | None, str] | None:
        """(branch, source) when the reflog decides, else None. A detached HEAD is (None, unknown)."""
        branch = self.branch_at(path, when)
        if branch is UNDECIDED:
            return None
        return (branch, "reflog") if branch else (None, "unknown")

    def attribute(self, record: dict[str, Any], meta: dict[str, Any] | None) -> tuple[str | None, str | None, str]:
        """(repository, branch, source) in the order of evidence the contract gives. The record's
        directory is the subagent's worktree when it has one, else its cwd.

        1. That directory's HEAD reflog at the request's time (`reflog`). Claude Code's gitBranch is
           the branch of the directory the session was launched in and does not follow `cd`.
        2. The reflog cannot be read: a subagent started in a worktree gets that worktree's current
           branch, read now; otherwise the record's gitBranch when it is a real branch there.
        3. Otherwise unknown. A past branch is never inferred from today's main checkout."""
        when = timestamp_seconds(record.get("timestamp"))
        worktree = meta.get("worktreePath") if meta else None
        if isinstance(worktree, str) and worktree:
            if not self.top(worktree):
                return None, None, "unknown"
            repository = self.repository(worktree)
            if decided := self.from_reflog(worktree, when):
                return repository, *decided
            branch = self.head_branch(worktree)
            if branch:
                return repository, branch, "worktree_at_capture"
            return repository, None, "unknown"
        cwd = record.get("cwd")
        if not isinstance(cwd, str) or not cwd or not self.top(cwd):
            return None, None, "unknown"
        repository = self.repository(cwd)
        if decided := self.from_reflog(cwd, when):
            return repository, *decided
        branch = record.get("gitBranch")
        if isinstance(branch, str) and branch not in ("", "HEAD") and self.has_branch(cwd, branch):
            return repository, branch, "transcript"
        return repository, None, "unknown"


# ---------------------------------------------------------------- reading transcripts

def read_complete_lines(path: Path, offset: int) -> Iterator[tuple[int, bytes]]:
    """(offset after the line, line) for each newline-terminated line from `offset` up to the
    file's size when it was opened. A last line without its newline is not complete yet, and lines
    written while this runs come later: both are left for the next capture, so every line is
    attributed with the checkout state read for this run."""
    position = offset
    carry = b""
    with open(path, "rb") as handle:
        remaining = os.fstat(handle.fileno()).st_size - offset
        handle.seek(offset)
        while remaining > 0:
            chunk = handle.read(min(1 << 22, remaining))
            if not chunk:
                return
            remaining -= len(chunk)
            *lines, carry = (carry + chunk).split(b"\n")
            for line in lines:
                position += len(line) + 1
                yield position, line


def head_hash(path: Path, length: int) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha1(handle.read(length)).hexdigest()


def claude_request(rec: dict[str, Any]) -> dict[str, Any] | None:
    """The token facts of one assistant record, or None. Nothing but numbers, ids and the model."""
    if rec.get("type") != "assistant":
        return None
    message = rec.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    if message.get("model") == "<synthetic>":
        return None
    numbers = {key: integer(usage.get(key)) for key in (
        "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    if all(value is None for value in numbers.values()):
        return None
    detail = usage.get("cache_creation")
    detail = detail if isinstance(detail, dict) else {}
    write_5m = integer(detail.get("ephemeral_5m_input_tokens"))
    write_1h = integer(detail.get("ephemeral_1h_input_tokens"))
    total = numbers["cache_creation_input_tokens"]
    if write_5m is None and write_1h is None:
        # No breakdown: the older API had one 5-minute cache, so the whole figure is 5-minute.
        write_5m, write_1h = total, (0 if total is not None else None)
    elif write_5m is None or write_1h is None or (total is not None and write_5m + write_1h != total):
        write_5m = write_1h = None  # a breakdown that does not add up is unknown, not a guess
    message_id = message.get("id")
    return {
        "message_id": message_id if isinstance(message_id, str) and message_id else None,
        "time": rec.get("timestamp"),
        "model": message.get("model"),
        "input": numbers["input_tokens"], "output": numbers["output_tokens"],
        "cache_read": numbers["cache_read_input_tokens"],
        "cache_write_5m": write_5m, "cache_write_1h": write_1h,
        "sidechain": rec.get("isSidechain") is True,
        "agent_id": rec.get("agentId"),
    }


def request_tokens(request: dict[str, Any]) -> tuple[Any, ...]:
    """The same tuple tokens_of() gives for the record this request would become."""
    return (clean(request["model"], 100),) + tuple(request[key] for key in TOKEN_FIELDS)


def load_meta(path: Path) -> dict[str, Any] | None:
    meta_path = path.with_name(path.name[:-len(".jsonl")] + ".meta.json")
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class Capture:
    """One capture run for one session: counts, the ids already held, and the new records."""

    def __init__(self, runtime: str, session: str, known: dict[str, tuple[Any, ...]],
                 remote_session: str | None = None) -> None:
        self.runtime = runtime
        self.session = session
        self.remote_session = remote_session
        self.known = dict(known)               # id -> tokens_of(record)
        self.new: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()
        self.conflicts: list[str] = []

    def add(self, request: dict[str, Any], role: str, agent_type: str | None, agent_id: str | None,
            attribution: tuple[str | None, str | None, str], identity: str | None) -> None:
        moment = parse_time(request["time"])
        record = project({
            "id": identity, "time": format_time(moment) if moment else None, "model": request["model"],
            "input": request["input"], "output": request["output"], "cache_read": request["cache_read"],
            "cache_write_5m": request["cache_write_5m"], "cache_write_1h": request["cache_write_1h"],
            "repository": attribution[0], "branch": attribution[1], "attribution_source": attribution[2],
            "role": role, "agent_type": agent_type, "agent_id": agent_id,
            "session": self.session, "runtime": self.runtime, "remote_session": self.remote_session,
        })
        if record is None:
            return
        if identity is None:
            self.counts["unidentified"] += 1
        self.new.append(record)
        if identity is not None:
            self.known[identity] = tokens_of(record)


def claude_identity(request: dict[str, Any]) -> str | None:
    """`claude:<message.id>`. Every assistant record carries message.id and all copies of one
    request (one per content block, or in a forked transcript) share it. `requestId` is not part of
    the identity: it is absent on many records, so mixing the two keys counted one request twice
    when its copies were captured at different times. No message.id means unidentified (None)."""
    message_id = request["message_id"]
    return clean("claude:" + message_id, 210) if message_id else None


def capture_claude_file(path: Path, is_main: bool, offset: int, capture: Capture,
                        checkouts: Checkouts) -> tuple[int, int]:
    """Read new lines of one transcript. Returns (new offset, bytes read)."""
    meta = None if is_main else load_meta(path)
    agent_type = clean(meta.get("agentType"), 100) if meta else None
    file_agent = path.name[len("agent-"):-len(".jsonl")] if not is_main and path.name.startswith("agent-") else None
    end = offset
    for end, line in read_complete_lines(path, offset):
        if b'"usage"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            capture.counts["skipped_lines"] += 1
            continue
        if not isinstance(rec, dict):
            continue
        request = claude_request(rec)
        if request is None:
            continue
        identity = claude_identity(request)
        if identity is not None and identity in capture.known:
            capture.counts["duplicates"] += 1
            if request_tokens(request) != capture.known[identity] and identity not in capture.conflicts:
                capture.conflicts.append(identity)
            continue
        sidechain = request["sidechain"] or not is_main
        attribution = checkouts.attribute(rec, meta)
        agent_id = (clean(request["agent_id"], 100) or file_agent) if sidechain else None
        capture.add(request, "subagent" if sidechain else "main", agent_type if sidechain else None,
                    agent_id, attribution, identity)
    return end, end - offset


def cwd_attribution(checkouts: Checkouts, cwd: str | None, time_text: Any) -> tuple[str | None, str | None, str]:
    """(repository, branch, source) of a record that has a directory and a time but no branch of its
    own (Codex, OpenCode): the directory's HEAD reflog at that time."""
    if cwd and checkouts.top(cwd):
        branch, source = checkouts.from_reflog(cwd, timestamp_seconds(time_text)) or (None, "unknown")
        return checkouts.repository(cwd), branch, source
    return None, None, "unknown"


def codex_cwd(rec: dict[str, Any]) -> str | None:
    payload = rec.get("payload")
    if rec.get("type") in ("session_meta", "turn_context") and isinstance(payload, dict):
        cwd = payload.get("cwd")
        return cwd if isinstance(cwd, str) and cwd else None
    return None


def capture_codex_file(path: Path, entry: dict[str, Any], offset: int, capture: Capture,
                       checkouts: Checkouts) -> tuple[int, int]:
    """Codex keeps cumulative snapshots: the normalizer's state is saved with the offset."""
    codex_audit = load_module("codex_audit", "codex_audit.py")
    normalizer = codex_audit.CodexNormalizer()
    saved = entry.get("codex") if isinstance(entry.get("codex"), dict) else {}
    normalizer.previous = saved.get("previous")
    normalizer.sequence = saved.get("sequence", 0)
    normalizer.model = saved.get("model")
    normalizer.session_id = saved.get("session_id")
    cwd = saved.get("cwd")
    end = offset
    for end, line in read_complete_lines(path, offset):
        try:
            rec = json.loads(line)
            if not isinstance(rec, dict):
                continue
            cwd = codex_cwd(rec) or cwd
            out = normalizer.accept(rec)
        except ValueError as error:
            raise LedgerError(f"{path.name}: {redact(str(error))}") from error
        if out is None or out.get("type") != "assistant":
            continue
        capture.session = safe_session(normalizer.session_id or path.stem)
        message = out["message"]
        usage = message["usage"]
        total = integer(usage.get("cache_creation_input_tokens"))
        sequence = normalizer.sequence
        identity = clean(f"codex:{capture.session}:{sequence}", 210)
        request = {
            "time": out.get("timestamp"), "model": message.get("model"),
            "input": integer(usage.get("input_tokens")), "output": integer(usage.get("output_tokens")),
            "cache_read": integer(usage.get("cache_read_input_tokens")),
            "cache_write_5m": total, "cache_write_1h": 0 if total is not None else None,
        }
        # Codex rows carry no branch, but they have a cwd and a time: the reflog gives the branch.
        if identity is not None and identity in capture.known:
            capture.counts["duplicates"] += 1
            continue
        capture.add(request, "main", None, None, cwd_attribution(checkouts, cwd, request["time"]), identity)
    entry["codex"] = {"previous": normalizer.previous, "sequence": normalizer.sequence,
                      "model": normalizer.model, "session_id": normalizer.session_id, "cwd": cwd}
    if normalizer.session_id:
        capture.session = safe_session(normalizer.session_id)
    return end, end - offset


# ---------------------------------------------------------------- capture command

def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}}
    return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else {"files": {}}


def known_ids(directory: Path, runtime: str, session: str) -> dict[str, tuple[Any, ...]]:
    known: dict[str, tuple[Any, ...]] = {}
    for kind in ("exported", "pending"):
        for record in load_records(directory / kind / runtime / f"{session}.jsonl"):
            if record["id"]:
                known.setdefault(record["id"], tokens_of(record))
    return known


def append_conflicts(directory: Path, runtime: str, session: str, ids: list[str]) -> None:
    path = directory / "conflicts" / runtime / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    with contextlib.suppress(OSError, ValueError):
        existing = {json.loads(line).get("id") for line in path.read_text().splitlines()}
    with open(path, "a", encoding="utf-8") as handle:
        for identity in ids:
            if identity not in existing:
                handle.write(json.dumps({"id": identity}) + "\n")


def read_conflict_ids(path: Path) -> list[str]:
    """The conflicting request ids a conflicts file holds: ids only, sorted, once each. A line that
    is not {"id": <token-like string>} is ignored, the same allowlist as every other record."""
    ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        with contextlib.suppress(ValueError, AttributeError):
            identity = clean(json.loads(line).get("id"), 210)
            if identity:
                ids.add(identity)
    return sorted(ids)


def capture_one(directory: Path, runtime: str, main: Path, checkouts: Checkouts) -> dict[str, Any]:
    stem = safe_session(main.stem)
    state_path = directory / "state" / runtime / f"{stem}.json"
    state = load_state(state_path)
    session = stem
    if runtime == "claude":
        audit = load_module("session_audit", "session-audit.py")
        paths = [(main, True)] + [(path, False) for path in audit.transcript_paths(main.parent, main)[1:]]
    else:
        paths = [(main, True)]
        saved = state["files"].get(str(main), {}).get("codex")
        if saved is None:
            # The same rollout under another path (Codex moves old ones to archived_sessions/ keeping
            # the name, so the state file, which is named after it, knows the session): read it from
            # the start, and let the ids already held absorb what was captured at the old path.
            saved = next((entry["codex"] for entry in state["files"].values()
                          if isinstance(entry, dict) and isinstance(entry.get("codex"), dict)
                          and isinstance(entry["codex"].get("session_id"), str)), None)
        if isinstance(saved, dict) and isinstance(saved.get("session_id"), str):
            session = safe_session(saved["session_id"])
    capture = Capture(runtime, session, known_ids(directory, runtime, session),
                      remote_session_from_env(session=main.stem) if runtime == "claude" else cloud_remote_session())
    summary_files = []
    for path, is_main in paths:
        key = str(path)
        entry = state["files"].get(key) if isinstance(state["files"].get(key), dict) else {}
        try:
            size = path.stat().st_size
            offset = integer(entry.get("offset")) or 0
            head_len = integer(entry.get("head_len")) or 0
            if offset > size or (offset and head_hash(path, head_len) != entry.get("head")):
                offset, entry = 0, {}  # shorter or replaced: read again, the known ids absorb repeats
        except OSError:
            continue
        if runtime == "claude":
            end, read = capture_claude_file(path, is_main, offset, capture, checkouts)
        else:
            end, read = capture_codex_file(path, entry, offset, capture, checkouts)
        head_len = min(256, end)
        entry.update({"offset": end, "head_len": head_len, "head": head_hash(path, head_len)})
        state["files"][key] = entry
        summary_files.append({"file": path.name, "offset_before": offset, "offset": end, "bytes_read": read})
    session = capture.session
    if capture.new:
        pending = directory / "pending" / runtime / f"{session}.jsonl"
        pending.parent.mkdir(parents=True, exist_ok=True)
        with open(pending, "a", encoding="utf-8") as handle:
            handle.write("".join(record_line(record) + "\n" for record in capture.new))
    if capture.conflicts:
        append_conflicts(directory, runtime, session, capture.conflicts)
    atomic_write(state_path, json.dumps(state, sort_keys=True))
    return {"runtime": runtime, "session": session, "new": len(capture.new),
            "duplicates": capture.counts["duplicates"], "unidentified": capture.counts["unidentified"],
            "conflicts": len(capture.conflicts), "skipped_lines": capture.counts["skipped_lines"],
            "bytes_read": sum(f["bytes_read"] for f in summary_files), "files": summary_files}


# ---------------------------------------------------------------- sweep: every other runtime on the machine

def sweep_runtimes() -> list[str]:
    """The runtimes `ledger.runtimes` names that a sweep reads (default: all of them). The list is
    separated by commas or white space; a name that is not a runtime is ignored with one stderr line."""
    names = [name.lower() for name in re.split(r"[,\s]+", config("ledger.runtimes", ",".join(RUNTIMES))) if name]
    unknown = sorted({clean(name, 40) or "?" for name in names if name not in RUNTIMES})
    if unknown:
        print("plumb-ledger capture: ledger.runtimes ignores unknown runtime(s): " + ", ".join(unknown), file=sys.stderr)
    return [runtime for runtime in SWEPT if runtime in names]


def codex_roots() -> list[tuple[str, Path]]:
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    return [(name, home / name) for name in ("sessions", "archived_sessions")]


def codex_files(root: Path) -> list[Path]:
    """Every rollout below `root` (Codex writes sessions/YYYY/MM/DD/rollout-*.jsonl), sorted by path."""
    return sorted(path for path in root.rglob("*.jsonl") if path.is_file())


def load_sweep_index(path: Path) -> dict[str, dict[str, Any]]:
    """path -> {size, mtime_ns, status}. A missing or unreadable index, or an entry that does not have
    that shape, means the file is checked again (its own offsets still prevent reading it twice)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for key, entry in (data.items() if isinstance(data, dict) else []):
        if (isinstance(entry, dict) and integer(entry.get("size")) is not None
                and integer(entry.get("mtime_ns")) is not None and entry.get("status") in ("ok", "failed")):
            index[key] = {"size": entry["size"], "mtime_ns": entry["mtime_ns"], "status": entry["status"]}
    return index


def sweep_codex(directory: Path, checkouts: Checkouts, sessions: list[dict[str, Any]], cwd: str | None) -> dict[str, Any]:
    """Capture every Codex rollout that changed since the last sweep.

    state/codex/sweep.json holds, per rollout path, the size and mtime the file had when it was last
    looked at and whether it was `ok` or `failed` (refused by the normalizer, for example a rollout
    that starts with a usage total it never observed). A file whose size and mtime are unchanged is
    not opened; a failed one is counted and not retried until it changes. The error type and a short
    masked message go to capture.log once per change of the file, never the file's content. The
    per-file state (offset, head hash, normalizer state) is the one `capture_one` keeps."""
    index_path = directory / "state" / "codex" / "sweep.json"
    index = load_sweep_index(index_path)
    summary: dict[str, Any] = {"runtime": "codex", "kind": "sweep", "files": 0, "unchanged": 0, "failed": 0, "missing": []}
    seen: dict[str, dict[str, Any]] = {}
    missing_roots: list[str] = []
    try:
        for name, root in codex_roots():
            if not root.is_dir():
                summary["missing"].append(name)
                missing_roots.append(str(root) + os.sep)
                continue
            for path in codex_files(root):
                key = str(path)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                summary["files"] += 1
                previous = index.get(key)
                if previous and previous["size"] == stat.st_size and previous["mtime_ns"] == stat.st_mtime_ns:
                    seen[key] = previous
                    summary["unchanged"] += 1
                    summary["failed"] += previous["status"] == "failed"
                    continue
                status = "ok"
                try:
                    captured = capture_one(directory, "codex", path, checkouts)
                    if not captured["files"]:
                        # capture_one could not stat or hash the file and read nothing: not `ok`, and
                        # not refused either. It stays out of the index, so the next sweep reads it.
                        summary["failed"] += 1
                        log_line(cwd, "sweep codex: file skipped: it could not be read this time")
                        continue
                    sessions.append(captured)
                except (LedgerError, OSError) as error:
                    summary["failed"] += 1
                    if isinstance(error, OSError) and getattr(error, "filename", None) != key:
                        # Writing the ledger failed (its directory, the disk), not reading this file:
                        # the file stays out of the index, so the next sweep tries it again.
                        log_line(cwd, f"sweep codex: ledger write failed: {type(error).__name__}: {redact(str(error))[:200]}")
                        continue
                    # Refused by the normalizer, or this file is not readable (permissions): this file
                    # only. The other rollouts go on, and this one waits for a change.
                    status = "failed"
                    log_line(cwd, f"sweep codex: file refused: {type(error).__name__}: {redact(str(error))[:200]}")
                # The size and mtime read before the capture: a file that grows meanwhile differs next time.
                seen[key] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "status": status}
    finally:
        # Paths no longer listed (a rollout moved to archived_sessions/) leave the index; those below a
        # location that was not there are kept.
        kept = {key: entry for key, entry in index.items() if key not in seen
                and any(key.startswith(prefix) for prefix in missing_roots)}
        atomic_write(index_path, json.dumps({**kept, **seen}, sort_keys=True))
    return summary


def opencode_db() -> Path:
    override = os.environ.get("OPENCODE_DATA_DIR")
    if override:
        return Path(override).expanduser() / "opencode.db"
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "opencode" / "opencode.db"


OPENCODE_LOOKBACK_MS = 600_000   # rows committed late: re-read this far behind the watermark


def as_json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", "replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def millis_to_time(value: Any) -> str | None:
    """Epoch milliseconds to the record's time text, exact to the millisecond, or None."""
    ms = integer(value)
    if ms is None:
        return None
    try:
        return format_time(datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms))
    except (OverflowError, ValueError):
        return None


def opencode_model(data: dict[str, Any], session_model: Any) -> str | None:
    """`<providerID>/<id>` from the message's own `model`, else from the session's."""
    for source in (data.get("model"), as_json_object(session_model)):
        if isinstance(source, dict) and isinstance(source.get("providerID"), str) and isinstance(source.get("id"), str):
            return f"{source['providerID']}/{source['id']}"
    return None


def opencode_request(data: dict[str, Any], session_model: Any) -> dict[str, Any] | None:
    """The token facts of one completed assistant message, or None when it is still streaming or has
    no tokens object. Nothing but numbers and the model; `skipped` marks a row with no usable number."""
    moments = data.get("time")
    tokens = data.get("tokens")
    if not isinstance(moments, dict) or not integer(moments.get("completed")) or not isinstance(tokens, dict):
        return None
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    written = integer(cache.get("write"))
    if "reasoning" in tokens:
        # OpenCode stores the visible output and the reasoning apart and bills both at the output
        # rate; Claude and Codex rows count reasoning inside output. A sum with an unknown part is
        # unknown (None), never the part that is known.
        visible, reasoning = integer(tokens.get("output")), integer(tokens.get("reasoning"))
        output = visible + reasoning if visible is not None and reasoning is not None else None
    else:
        output = integer(tokens.get("output"))   # no reasoning figure at all: output is all there is
    request = {
        "time": millis_to_time(moments.get("created")), "model": opencode_model(data, session_model),
        "input": integer(tokens.get("input")), "output": output, "cache_read": integer(cache.get("read")),
        "cache_write_5m": written, "cache_write_1h": 0 if written is not None else None,
    }
    request["skipped"] = all(request[key] is None for key in TOKEN_FIELDS)
    return request


class OpenCodeSessions:
    """Read-only lookups in session_v2, cached: the row of a session and the root of its parent chain."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.rows: dict[str, tuple[Any, Any, Any] | None] = {}

    def row(self, identity: str) -> tuple[Any, Any, Any] | None:
        """(parent_id, directory, model) of one session, or None when there is no such session."""
        if identity not in self.rows:
            found = self.conn.execute("SELECT parent_id, directory, model FROM session_v2 WHERE id = ?",
                                      (identity,)).fetchone()
            self.rows[identity] = tuple(found) if found else None
        return self.rows[identity]

    def root(self, identity: str) -> str:
        """The top of the parent_id chain. A missing parent stops the walk at the last session found;
        a cycle ends at its smallest id, so every member of it has the same root."""
        chain = [identity]
        while len(chain) < 100:
            found = self.row(chain[-1])
            parent = found[0] if found else None
            if not isinstance(parent, str) or not parent or self.row(parent) is None:
                return chain[-1]
            if parent in chain:
                return min(chain[chain.index(parent):])
            chain.append(parent)
        return chain[-1]


def opencode_failure(error: BaseException) -> LedgerError:
    return LedgerError(f"opencode database: {type(error).__name__}: {redact(str(error))[:120]}")


def sweep_opencode(directory: Path, checkouts: Checkouts, sessions: list[dict[str, Any]], cwd: str | None) -> dict[str, Any]:
    """Capture the completed assistant messages of OpenCode's SQLite database.

    Read-only (`mode=ro`, `query_only`), and only these columns of these two tables:
    session_v2.id, parent_id, directory, model and session_message.id, session_id, type, time_updated,
    data (the contract also lists seq; it is not needed). The database also holds account and
    credential tables; no query names them. `data` is parsed for time, tokens, model and agent and
    nothing else. The watermark (the largest time_updated seen) is advanced only after every
    session's pending rows are written; a sweep re-reads the ten minutes behind it, and the ids
    already held absorb the repeats."""
    summary: dict[str, Any] = {"runtime": "opencode", "kind": "sweep", "rows": 0, "failed": 0, "missing": []}
    db = opencode_db()
    if not db.is_file():
        summary["missing"].append("opencode.db")
        return summary
    state_path = directory / "state" / "opencode" / (hashlib.sha1(str(db).encode("utf-8", "replace")).hexdigest()[:16] + ".json")
    try:
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        stored = integer(saved.get("watermark")) if isinstance(saved, dict) else None
    except (OSError, ValueError):
        stored = None
    watermark = stored or 0
    newest = watermark
    groups: dict[str, list[dict[str, Any]]] = {}
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True, timeout=5)
        try:
            conn.text_factory = lambda raw: raw.decode("utf-8", "replace")
            conn.execute("PRAGMA query_only = ON")
            latest = conn.execute("SELECT MAX(time_updated) FROM session_message").fetchone()[0]
            if isinstance(latest, (int, float)) and latest < watermark:
                watermark = newest = 0   # the database went back in time (a restore): read it all, the ids absorb repeats
            lookup = OpenCodeSessions(conn)
            rows = conn.execute("SELECT id, session_id, time_updated, data FROM session_message "
                                "WHERE type = 'assistant' AND time_updated > ? ORDER BY time_updated, id",
                                (watermark - OPENCODE_LOOKBACK_MS,))
            for message_id, session_id, updated, raw in rows:
                summary["rows"] += 1
                if isinstance(updated, (int, float)) and not isinstance(updated, bool):
                    newest = max(newest, int(updated))
                if not isinstance(session_id, str) or not session_id:
                    continue
                data = as_json_object(raw)
                found = lookup.row(session_id)
                request = opencode_request(data, found[2] if found else None) if data is not None else {"skipped": True}
                if request is None:
                    continue   # still streaming, or no tokens object
                root = lookup.root(session_id)
                child = root != session_id
                request.update({
                    "message_id": message_id if isinstance(message_id, str) and message_id else None,
                    "directory": found[1] if found and isinstance(found[1], str) else None,
                    "role": "subagent" if child else "main",
                    "agent_id": session_id if child else None,
                    "agent_type": data.get("agent") if child and data is not None else None,
                })
                groups.setdefault(root, []).append(request)
        finally:
            conn.close()
    except sqlite3.Error as error:
        raise opencode_failure(error) from error
    for root, requests in groups.items():
        session = safe_session(root)
        capture = Capture("opencode", session, known_ids(directory, "opencode", session), cloud_remote_session())
        for request in requests:
            if request["skipped"]:
                capture.counts["skipped_lines"] += 1
                continue
            identity = clean("opencode:" + request["message_id"], 210) if request["message_id"] else None
            if identity is not None and identity in capture.known:
                capture.counts["duplicates"] += 1
                if request_tokens(request) != capture.known[identity] and identity not in capture.conflicts:
                    capture.conflicts.append(identity)
                continue
            capture.add(request, request["role"], clean(request["agent_type"], 100), clean(request["agent_id"], 100),
                        cwd_attribution(checkouts, request["directory"], request["time"]), identity)
        if capture.new:
            pending = directory / "pending" / "opencode" / f"{session}.jsonl"
            pending.parent.mkdir(parents=True, exist_ok=True)
            with open(pending, "a", encoding="utf-8") as handle:
                handle.write("".join(record_line(record) + "\n" for record in capture.new))
        if capture.conflicts:
            append_conflicts(directory, "opencode", session, capture.conflicts)
        sessions.append({"runtime": "opencode", "session": session, "new": len(capture.new),
                         "duplicates": capture.counts["duplicates"], "unidentified": capture.counts["unidentified"],
                         "conflicts": len(capture.conflicts), "skipped_lines": capture.counts["skipped_lines"],
                         "bytes_read": 0, "files": []})
    if newest and newest != stored:
        atomic_write(state_path, json.dumps({"watermark": newest}))
    return summary


SWEEPERS = {"codex": sweep_codex, "opencode": sweep_opencode}


def sweep(directory: Path, checkouts: Checkouts, cwd: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Capture every runtime of `ledger.runtimes` other than Claude from its default location.
    Returns (the sessions captured, one summary per runtime, status). A runtime that fails (a
    database that cannot be opened, anything unexpected) leaves one stderr line and one capture.log
    line, makes the status 1 and does not stop the others; a location that is not there is only
    reported as missing."""
    sessions: list[dict[str, Any]] = []
    runtimes: list[dict[str, Any]] = []
    status = 0
    for runtime in sweep_runtimes():
        try:
            runtimes.append(SWEEPERS[runtime](directory, checkouts, sessions, cwd))
        except Exception as error:  # noqa: BLE001 - one runtime's failure must not stop the others
            message = redact(str(error))[:200] if isinstance(error, LedgerError) \
                else f"{type(error).__name__}: {redact(str(error))[:200]}"
            print(f"plumb-ledger capture: sweep {runtime}: {message}", file=sys.stderr)
            log_line(cwd, f"sweep {runtime} failed: {message}")
            runtimes.append({"runtime": runtime, "kind": "sweep", "failed": 1, "missing": [], "error": message})
            status = 1
    return sessions, runtimes, status


def read_hook_input(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LedgerError(f"hook input is not readable JSON: {type(error).__name__}") from error
    finally:
        if path.name.startswith(HOOK_TEMP_PREFIX):
            with contextlib.suppress(OSError):
                path.unlink()
    if not isinstance(data, dict):
        raise LedgerError("hook input is not a JSON object")
    return data


def capture_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plumb-ledger capture",
        description="Record the requests new since the last capture, from a transcript and its "
                    "subagents, as allowlisted per-request rows under ~/.claude/plumb/ledger. Makes no network call.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--hook-input", metavar="FILE", help="the Stop hook's JSON (session_id, transcript_path, cwd)")
    source.add_argument("--transcript", metavar="PATH", help="a main transcript (.jsonl)")
    source.add_argument("--transcripts", metavar="DIR", help="a directory of transcripts (every direct .jsonl; with --runtime codex, every .jsonl below it)")
    source.add_argument("--sweep", action="store_true", help="capture the other runtimes on this machine from their default locations "
                        "(Codex rollouts, OpenCode's database), as ledger.runtimes lists them; --runtime is ignored")
    parser.add_argument("--runtime", choices=RUNTIMES, default="claude", help="the runtime of --transcript / --transcripts (default: claude)")
    parser.add_argument("--cwd", metavar="DIR", help="the checkout the session ran in, for repository and branch (default: the hook's cwd, else the current directory)")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    return parser


def cmd_capture(argv: list[str]) -> int:
    args = capture_parser().parse_args(argv)
    if args.runtime == "opencode" and not args.sweep:
        # OpenCode keeps its sessions in a database, not in transcript files; only the sweep reads it.
        raise LedgerError("OpenCode has no transcript files: use capture --sweep")
    cwd = args.cwd
    mains: list[Path] = []
    if args.hook_input:
        hook = read_hook_input(Path(args.hook_input))
        transcript = hook.get("transcript_path")
        if not isinstance(transcript, str) or not transcript:
            raise LedgerError("hook input has no transcript_path")
        mains = [Path(transcript)]
        cwd = cwd or (hook.get("cwd") if isinstance(hook.get("cwd"), str) else None)
    elif args.transcript:
        mains = [Path(args.transcript).expanduser()]
    elif args.transcripts:
        directory = Path(args.transcripts).expanduser()
        if not directory.is_dir():
            raise LedgerError(f"transcript directory not found: {directory}")
        if args.runtime == "codex":   # Codex writes sessions/YYYY/MM/DD/rollout-*.jsonl
            mains = codex_files(directory)
        else:   # Claude's subagent transcripts are read through their main transcript
            mains = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".jsonl")
    elif not args.sweep:
        raise LedgerError("give --hook-input, --transcript, --transcripts or --sweep")
    cwd = cwd or os.getcwd()
    directory = ledger_dir(cwd, True)
    summaries: list[dict[str, Any]] = []
    runtimes: list[dict[str, Any]] = []
    status = 0
    with locked(directory):
        checkouts = Checkouts()
        for main in mains:
            if not main.is_file():
                print(f"plumb-ledger capture: transcript not found: {main.name}", file=sys.stderr)
                status = 1
                continue
            try:
                summaries.append(capture_one(directory, args.runtime, main, checkouts))
            except LedgerError as error:
                print(f"plumb-ledger capture: {error}", file=sys.stderr)
                status = 1
        if args.sweep:
            swept, runtimes, code = sweep(directory, checkouts, cwd)
            summaries += swept
            status = status or code
        elif args.hook_input:
            # After the Claude capture, under the same lock: the other runtimes on this machine. A
            # failure here never fails the Claude capture or the hook; it leaves one line in the log.
            try:
                if config("ledger.capture", "off") == "on":
                    swept, runtimes, _ = sweep(directory, checkouts, cwd)
                    summaries += swept
            except Exception as error:  # noqa: BLE001 - the hook's background job must not raise
                log_line(cwd, f"sweep failed: {type(error).__name__}: {redact(str(error))[:200]}")
    for summary in summaries:
        if args.json:
            print(json.dumps(summary, sort_keys=True))
        else:
            print("capture: {runtime} session={session} new={new} duplicates={duplicates} "
                  "unidentified={unidentified} conflicts={conflicts} bytes_read={bytes_read}".format(**summary))
    for line in runtimes:
        if args.json:
            print(json.dumps(line, sort_keys=True))
        else:
            counts = " ".join(f"{key}={line[key]}" for key in ("files", "unchanged", "rows") if key in line)
            print(f"sweep: {line['runtime']} {counts + ' ' if counts else ''}failed={line['failed']} "
                  f"missing={','.join(line['missing']) or 'none'}")
    if args.hook_input:
        export_on_stop(summaries, cwd, [line["runtime"] for line in runtimes])
    return status


def export_on_stop(summaries: list[dict[str, Any]], cwd: str | None, swept: list[str] = ()) -> None:
    """The end of a turn in a cloud session: a container can be reclaimed with no session-end event,
    so when the owner opted in (ledger.capture = on, ledger.export = on-stop, ledger.store set) the
    Claude sessions this hook run captured something new for (a row, or a conflicting copy) are exported now, by the same code path as
    `plumb-ledger export --session <id>`. Only the hook path calls this, in its background job: it
    never raises, and what goes wrong leaves one line (type and a short, masked message) in the
    capture log while the records stay pending. A session with nothing new does not push.

    Each runtime the hook swept (`swept`) is exported as `plumb-ledger export --runtime <runtime>`,
    which sends every session of it that is still pending, not only the ones this run added to: a
    swept session whose push failed gets no new row on the next turn (its rollout or database rows
    are unchanged), so it would otherwise stay pending until the container is gone. With nothing
    pending that export returns without touching the network."""
    try:
        if config("ledger.capture", "off") != "on" or config("ledger.export", "manual") != "on-stop":
            return
        # A conflicting copy found by this capture is news too, even with no new row: cmd_export
        # sends a session whose conflicts changed, and the container may not wait for another turn.
        jobs = [["--session", s["session"], "--runtime", s["runtime"]] for s in summaries
                if s.get("runtime") not in swept and (s.get("new") or s.get("conflicts"))]
        due_swept = any(s.get("new") or s.get("conflicts") for s in summaries if s.get("runtime") in swept)
        if not config("ledger.store"):
            if jobs or due_swept:
                log_line(cwd, "export skipped: ledger.store is unset")
            return
        jobs += [["--runtime", runtime] for runtime in dict.fromkeys(swept)]
        for job in jobs:
            out, err = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = cmd_export(job)
            except LedgerError as error:
                log_line(cwd, f"export failed: LedgerError: {redact(str(error))[:200]}")
                continue
            if code != 0:
                log_line(cwd, f"export failed: exit {code}: {first_line(err.getvalue()) or 'no message'}")
    except Exception as error:  # noqa: BLE001 - the hook's background job must not raise
        log_line(cwd, f"export failed: {type(error).__name__}: {redact(str(error))[:200]}")


def log_line(cwd: str | None, text: str) -> None:
    """The hook path has nowhere to print: leave one line in the ledger directory's capture log."""
    with contextlib.suppress(Exception):
        directory = ledger_dir(cwd, True)
        with open(directory / "capture.log", "a", encoding="utf-8") as handle:
            handle.write(f"{format_time(datetime.now(timezone.utc))} {text}\n")


def log_failure(error: BaseException, cwd: str | None) -> None:
    """Type and message only."""
    log_line(cwd, f"capture failed: {type(error).__name__}: {redact(str(error))[:200]}")


# ---------------------------------------------------------------- prices

def load_prices(path: Path = PRICES_FILE) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    versions = data["versions"]
    for version in versions:
        version["_from"] = parse_time(version["effective_from"])
        if version["_from"] is None:
            raise LedgerError(f"prices: bad effective_from in version {version.get('id')}")
    return sorted(versions, key=lambda v: v["_from"])


def version_in_effect(versions: list[dict[str, Any]], moment: datetime) -> dict[str, Any] | None:
    current = None
    for version in versions:
        if version["_from"] <= moment:
            current = version
    return current


def model_rates(version: dict[str, Any], model: str) -> dict[str, Any] | None:
    """The rates of a model in a version. A model may carry its own `checked` and `source` (they
    override the version's for that model); pricing reads only the rate keys, so they change no sum.
    A name with a provider prefix (`opencode/deepseek-v4.1-flash-free`) is looked up as it is."""
    models = version["models"]
    name = re.sub(r"\[[^\]]*\]$", "", model)  # a context-window suffix such as [1m]
    for candidate in (name, re.sub(r"-\d{8}$", "", name)):
        if candidate in models:
            return models[candidate]
    return None


def price_request(record: dict[str, Any], versions: list[dict[str, Any]]) -> dict[str, Decimal] | None:
    """Cost by token kind in USD, or None when anything needed is unknown."""
    moment = parse_time(record["time"])
    if moment is None or record["model"] is None or any(record[key] is None for key in TOKEN_FIELDS):
        return None
    version = version_in_effect(versions, moment)
    rates = model_rates(version, record["model"]) if version else None
    if rates is None:
        return None
    context = record["input"] + record["cache_read"] + record["cache_write_5m"] + record["cache_write_1h"]
    long_context = rates.get("long_context")
    if isinstance(long_context, dict) and context > long_context["threshold_input_tokens"]:
        rates = {**rates, **{k: v for k, v in long_context.items() if k != "threshold_input_tokens"}}
    multiplier = version["cache_write_multiplier"]
    per = Decimal(version.get("per_tokens", 1000000))
    with localcontext() as ctx:
        ctx.prec = 60
        return {
            "input": record["input"] * rates["input"] / per,
            "output": record["output"] * rates["output"] / per,
            "cache_read": record["cache_read"] * rates["cache_read"] / per,
            "cache_write_5m": record["cache_write_5m"] * rates["input"] * Decimal(multiplier["5m"]) / per,
            "cache_write_1h": record["cache_write_1h"] * rates["input"] * Decimal(multiplier["1h"]) / per,
        }


def money(value: Decimal) -> str:
    places = Decimal("0.01") if abs(value) >= 1 else Decimal("0.0001")
    return "$" + format(value.quantize(places, rounding=ROUND_HALF_UP), ",")


# ---------------------------------------------------------------- store and export

def git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "LC_ALL": "C"})
    return env


def git_cache(directory: Path, name: str) -> Path:
    """A bare repository next to the ledger (export builds commits in it, report fetches into it)."""
    repo = directory / name
    if not (repo / "HEAD").exists():
        directory.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "--bare", "--quiet", str(repo)], timeout=30)
    if not (repo / "HEAD").exists():
        raise LedgerError(f"cannot create the cache repository {name}")
    return repo


def preflight(store: str) -> tuple[bool, str]:
    out = run(["git", "ls-remote", store], env=git_env(), timeout=PREFLIGHT_TIMEOUT)
    if out is None:
        return False, "git did not answer"
    if out.returncode != 0:
        return False, first_line(out.stderr) or f"git ls-remote exited {out.returncode}"
    return True, "ok"


def build_commit(cache: Path, runtime: str, session: str, records: list[dict[str, Any]],
                 conflicts: list[str] | None = None) -> str:
    """The same records and conflict ids always give the same commit: fixed identity, date from the
    newest record, no parent. Files: records.jsonl, and conflicts.jsonl (ids only, sorted) when the
    session has conflicting copies; a session without any has the one file it always had."""
    conflicts = sorted(set(conflicts or []))
    body = "".join(record_line(r) + "\n" for r in records)
    newest = max((parse_time(r["time"]) for r in records if r["time"]), default=None)
    stamp = f"{int(newest.timestamp()) if newest else 0} +0000"
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "plumb-ledger", "GIT_AUTHOR_EMAIL": "ledger@plumb.invalid",
                "GIT_COMMITTER_NAME": "plumb-ledger", "GIT_COMMITTER_EMAIL": "ledger@plumb.invalid",
                "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})

    def git(args: list[str], stdin: str | None = None) -> str:
        out = run(["git", "-C", str(cache), "-c", "commit.gpgsign=false"] + args, env=env, stdin=stdin, timeout=60)
        if out is None or out.returncode != 0:
            raise LedgerError(f"git {args[0]} failed: {first_line(out.stderr) if out else 'no answer'}")
        return out.stdout.strip()

    entries = ""
    if conflicts:
        blob = git(["hash-object", "-w", "--stdin"], "".join(json.dumps({"id": i}) + "\n" for i in conflicts))
        entries += f"100644 blob {blob}\tconflicts.jsonl\n"
    blob = git(["hash-object", "-w", "--stdin"], body)
    entries += f"100644 blob {blob}\trecords.jsonl\n"
    tree = git(["mktree"], entries)
    note = f", {len(conflicts)} conflicts" if conflicts else ""
    return git(["commit-tree", tree, "-m", f"plumb-ledger {runtime}/{session}: {len(records)} records{note}"])


def export_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plumb-ledger export",
        description="Push captured sessions to the store named by ledger.store: one commit per "
                    "session, to refs/heads/plumb-ledger/<runtime>/<session>. Non-interactive. A failure keeps "
                    "the records pending and exits non-zero. Unset store: exit 0, records stay local.")
    parser.add_argument("--session", metavar="ID", help="export only this session")
    parser.add_argument("--runtime", choices=RUNTIMES, help="export only this runtime")
    parser.add_argument("--check", action="store_true", help="only run the preflight (git ls-remote) and print ok or NG <reason>")
    parser.add_argument("--ledger-dir", action="append", default=[], metavar="DIR", help="look here for pending records (repeatable; default: ~/.claude/plumb/ledger or PLUMB_LEDGER_DIR)")
    return parser


def cmd_export(argv: list[str]) -> int:
    args = export_parser().parse_args(argv)
    store = config("ledger.store")
    dirs = ledger_dirs(os.getcwd(), args.ledger_dir)
    if not store:
        if args.check:
            print("--  ledger.store unset")
            return 0
        print("export: ledger.store is unset; records stay local under "
              + (str(dirs[0]) if dirs else str(ledger_dir(None, False))) + " and cloud sessions are not covered")
        return 0
    if args.check:
        good, reason = preflight(store)
        print("ok" if good else f"NG {reason}")
        return 0 if good else 1
    work = []
    for directory in dirs:
        # A session is due when it has pending rows, or conflict ids its last export did not carry
        # (a later capture can find a conflicting copy without adding a row).
        due = {(runtime, session) for runtime, session, _path in session_files(directory, "pending")}
        for runtime, session, path in session_files(directory, "conflicts"):
            if read_conflict_ids(path) != read_conflict_ids(directory / "exported-conflicts" / runtime / f"{session}.jsonl"):
                due.add((runtime, session))
        for runtime, session in sorted(due):
            if args.session and args.session != session:
                continue
            if args.runtime and args.runtime != runtime:
                continue
            work.append((directory, runtime, session))
    if not work:
        print("export: nothing is pending")
        return 0
    good, reason = preflight(store)
    if not good:
        print(f"export: the store is not reachable ({reason}); {len(work)} session(s) stay pending", file=sys.stderr)
        return 1
    failed = 0
    for directory, runtime, session in work:
        try:
            export_session(directory, runtime, session, store)
        except LedgerError as error:
            failed += 1
            print(f"export: {runtime}/{session} stays pending: {error}", file=sys.stderr)
    return 1 if failed else 0


def export_session(directory: Path, runtime: str, session: str, store: str) -> None:
    """Push one session's records and move the pushed rows from pending to exported.

    The session's own lock (export-<runtime>-<session>.lock) is held from the read of its records
    through the push to the acknowledgement. Two overlapping exports of one session would otherwise
    each build a commit from the records they read, and the older snapshot could be pushed last over
    the newer one after its rows had left pending, losing requests. Capture does not take this lock:
    it keeps appending to pending, so the acknowledgement removes only the rows that were in the
    snapshot that was pushed (counted, so a row appended later that equals one of them stays)."""
    pending_path = directory / "pending" / runtime / f"{session}.jsonl"
    exported_path = directory / "exported" / runtime / f"{session}.jsonl"
    conflicts_path = directory / "conflicts" / runtime / f"{session}.jsonl"
    exported_conflicts_path = directory / "exported-conflicts" / runtime / f"{session}.jsonl"
    with locked(directory, f"export-{runtime}-{session}.lock"):
        with locked(directory):
            pending = load_records(pending_path)
            merged = unique_records(load_records(exported_path) + pending)
            conflicts = read_conflict_ids(conflicts_path)
        if not merged or (not pending and conflicts == read_conflict_ids(exported_conflicts_path)):
            return
        sent = Counter(record_line(r) for r in pending)
        ref = f"{STORE_REFS}/{runtime}/{session}"
        check = run(["git", "check-ref-format", ref], timeout=10)
        if check is None or check.returncode != 0:
            raise LedgerError("the session id is not a valid ref name")
        with locked(directory, "export.lock"):
            cache = git_cache(directory, "store.git")
        commit = build_commit(cache, runtime, session, merged, conflicts)
        out = run(["git", "-C", str(cache), "push", "--porcelain", store, f"+{commit}:{ref}"],
                  env=git_env(), timeout=GIT_TIMEOUT)
        if out is None or out.returncode != 0:
            raise LedgerError("push failed: " + (first_line(out.stderr) if out else "git did not answer")
                              + " (" + redact(store.split("://")[-1].split("@")[-1])[:60] + ")")
        with locked(directory):
            now_pending = load_records(pending_path)
            atomic_write(exported_path, "".join(record_line(r) + "\n" for r in merged))
            if conflicts:
                atomic_write(exported_conflicts_path, "".join(json.dumps({"id": i}) + "\n" for i in conflicts))
            keep = []
            for r in now_pending:
                line = record_line(r)
                if sent[line] > 0:
                    sent[line] -= 1
                else:
                    keep.append(r)
            if keep:
                atomic_write(pending_path, "".join(record_line(r) + "\n" for r in keep))
            else:
                with contextlib.suppress(OSError):
                    pending_path.unlink()
    print(f"export: {runtime}/{session} {len(merged)} records -> {commit[:12]}")


# ---------------------------------------------------------------- GitHub (REST through gh)

def gh_run(endpoint: str) -> Any:
    out = run(["gh", "api", "-H", "Accept: application/vnd.github+json", endpoint], timeout=120)
    if out is None:
        raise LedgerError("gh did not answer (is the GitHub CLI installed?)")
    if out.returncode != 0:
        # gh's own first line says why (403, 404, rate limit); it never carries a token.
        raise LedgerError(f"gh api {endpoint.split('?')[0]} failed (exit {out.returncode}): {first_line(out.stderr)}")
    try:
        return json.loads(out.stdout)
    except ValueError as error:
        raise LedgerError(f"gh api {endpoint.split('?')[0]} did not return JSON") from error


def gh_api(endpoint: str) -> list[Any]:
    """Every item of a list endpoint. Pages are requested by number, never with `gh api --paginate`:
    --paginate follows GitHub's Link headers to repositories/{id}/... paths, which a cloud session's
    proxy refuses (HTTP 403, measured 2026-10-30). A page shorter than per_page is the last.

    With PLUMB_LEDGER_GH_FIXTURES=<dir> the pages are read from <name>.page1.json, .page2.json, ...
    (name: the endpoint without its query, `/` as `__`) until the next one is missing."""
    fixtures = os.environ.get("PLUMB_LEDGER_GH_FIXTURES")
    items: list[Any] = []
    if fixtures:
        stem = endpoint.split("?")[0].strip("/").replace("/", "__")
        page = 1
        while (Path(fixtures) / f"{stem}.page{page}.json").is_file():
            try:
                items.extend(json.loads((Path(fixtures) / f"{stem}.page{page}.json").read_text(encoding="utf-8")))
            except (ValueError, TypeError) as error:
                raise LedgerError(f"fixture {stem}.page{page}.json is not a JSON array") from error
            page += 1
        if page == 1:
            raise LedgerError(f"no fixture {stem}.page1.json for {endpoint.split('?')[0]} in PLUMB_LEDGER_GH_FIXTURES")
        return items
    match = re.search(r"[?&]per_page=(\d+)", endpoint)
    per_page = int(match.group(1)) if match else 30
    joiner = "&" if "?" in endpoint else "?"
    page = 1
    while True:
        result = gh_run(f"{endpoint}{joiner}page={page}")
        batch = result if isinstance(result, list) else []
        items.extend(batch)
        if len(batch) < per_page:
            return items
        page += 1


# ---------------------------------------------------------------- prs and task assignment

def prs_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plumb-ledger prs",
        description="Pull requests of one repository (state=all) that were open on or after --since, "
                    "with number, head_ref, base_ref, created_at and closed_at: the input of task "
                    "assignment in `report`. GitHub REST through gh api, paginated.")
    parser.add_argument("--repo", required=True, metavar="OWNER/NAME")
    parser.add_argument("--since", required=True, metavar="YYYY-MM-DD", help="keep pull requests still open or closed on/after this day (UTC)")
    parser.add_argument("--out", metavar="FILE", help="write the JSON here instead of stdout")
    return parser


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise LedgerError(f"not a date (YYYY-MM-DD): {value}") from error


def cmd_prs(argv: list[str]) -> int:
    args = prs_parser().parse_args(argv)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        raise LedgerError(f"--repo must be owner/name: {args.repo}")
    since = datetime.combine(parse_day(args.since), datetime.min.time(), timezone.utc)
    rows = gh_api(f"repos/{args.repo}/pulls?state=all&per_page=100&sort=created&direction=asc")
    pulls = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("number"), int):
            continue
        head, base = row.get("head") or {}, row.get("base") or {}
        closed = parse_time(row.get("closed_at"))
        if closed is not None and closed < since:
            continue
        pulls.append({"number": row["number"], "head_ref": clean(head.get("ref")), "base_ref": clean(base.get("ref")),
                      "created_at": row.get("created_at"), "closed_at": row.get("closed_at")})
    pulls.sort(key=lambda p: (p["created_at"] or "", p["number"]))
    text = json.dumps({"repository": args.repo, "since": args.since, "pull_requests": pulls}, indent=2) + "\n"
    if args.out:
        atomic_write(Path(args.out), text)
        print(f"prs: {len(pulls)} pull requests of {args.repo} -> {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def repo_key(name: str | None) -> str:
    """The key every repository comparison uses: GitHub names are case-insensitive, and a record
    (its remote URL), a `--prs` file, a `changes` row, a `rework` file and `--repo` may spell one
    repository differently. Compare keys, never the spellings; show a spelling from
    canonical_repositories()."""
    return (name or "").strip().lower()


def assign_task(repository: str | None, branch: str | None, moment: datetime | None,
                pulls: dict[tuple[str, str], list[dict[str, Any]]], now: datetime) -> tuple[str, int | None]:
    """('pr', number) | ('ambiguous', None) | ('none', None) for a known repository and branch.

    Among the pull requests of the repository and head ref, in creation order, the request belongs
    to the first whose close time (or now, while open) is at or after the request's time. If that
    first one is open and another is open too, the request is ambiguous."""
    candidates = pulls.get((repo_key(repository), branch or ""), [])
    if moment is None:
        return "none", None
    chosen = None
    for pull in candidates:
        if (pull["closed"] or now) >= moment:
            chosen = pull
            break
    if chosen is None:
        return "none", None
    if chosen["closed"] is None and sum(1 for p in candidates if p["closed"] is None) > 1:
        return "ambiguous", None
    return "pr", chosen["number"]


def load_prs(paths: list[str]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    pulls: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in paths:
        try:
            data = json.loads(Path(item).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise LedgerError(f"--prs {item}: not readable JSON ({type(error).__name__})") from error
        for entry in (data if isinstance(data, list) else [data]):
            if not isinstance(entry, dict) or not isinstance(entry.get("pull_requests"), list):
                raise LedgerError(f"--prs {item}: expected the output of `plumb-ledger prs`")
            for pull in entry["pull_requests"]:
                created = parse_time(pull.get("created_at"))
                if created is None or not isinstance(pull.get("number"), int) or not pull.get("head_ref"):
                    continue
                pulls.setdefault((repo_key(entry.get("repository") if isinstance(entry.get("repository"), str) else ""), pull["head_ref"]), []).append({
                    "number": pull["number"], "created": created, "closed": parse_time(pull.get("closed_at"))})
    for rows in pulls.values():
        rows.sort(key=lambda p: (p["created"], p["number"]))
    return pulls


# ---------------------------------------------------------------- session attribution

SESSION_LINK = re.compile(r"https?://claude\.ai/code/session_([A-Za-z0-9][A-Za-z0-9_-]*)")

class SessionMap:
    """Which landed pull requests each cloud session produced: id -> {(repo_key, number):
    (repository as written, head ref or None)}."""

    def __init__(self) -> None:
        self.by_id: dict[str, dict[tuple[str, int], tuple[str, str | None]]] = {}

    def add(self, identity: str, repository: str, number: int, head: str | None) -> None:
        self.by_id.setdefault(identity, {}).setdefault((repo_key(repository), number), (repository, head))

    def produced(self, identity: str, repository: str | None) -> list[tuple[str, int, str | None]]:
        """(repository, number, head ref) of the pull requests of the session, sorted: those of one
        repository, or, with repository None, those across all repositories."""
        wanted = repo_key(repository) if repository else None
        return sorted((name, number, head) for (key, number), (name, head) in self.by_id.get(identity, {}).items()
                      if wanted is None or key == wanted)


def session_map(paths: list[str]) -> SessionMap:
    """Which landed pull requests a session produced, from the `sessions` of `plumb-ledger changes`
    rows (the `Claude-Session:` trailers of the pull request's commits). Only pull request rows
    count; a value that is not a session link is ignored."""
    found = SessionMap()
    for path in paths:
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise LedgerError(f"--changes {path}: not readable ({type(error).__name__})") from error
        for line in lines:
            with contextlib.suppress(ValueError):
                row = json.loads(line)
                if not isinstance(row, dict) or row.get("kind") != "pull_request":
                    continue
                number, repository = row.get("number"), row.get("repository")
                if isinstance(number, bool) or not isinstance(number, int) or not isinstance(repository, str) or not repository:
                    continue
                head = row.get("head_ref") if isinstance(row.get("head_ref"), str) and 0 < len(row["head_ref"]) <= 200 else None
                for value in row.get("sessions") if isinstance(row.get("sessions"), list) else []:
                    for identity in SESSION_LINK.findall(value) if isinstance(value, str) else []:
                        found.add(identity, repository, number, head)
    return found


class Placement:
    """Where one request goes. `kind` is `unknown` (repository or branch unknown), `branch` (no pull
    requests were given: the task is repository @ branch), `pr`, `ambiguous` or `none` (the branch
    has no pull request). `via` is `branch` or `session`; `session_ambiguous` marks a request the
    session rule looked at and left, because its session produced two or more pull requests."""

    __slots__ = ("kind", "repository", "branch", "number", "head_ref", "via", "session_ambiguous")

    def __init__(self, kind: str, repository: str | None, branch: str | None, number: int | None = None,
                 head_ref: str | None = None, via: str = "branch", session_ambiguous: bool = False) -> None:
        self.kind, self.repository, self.branch, self.number = kind, repository, branch, number
        self.head_ref, self.via, self.session_ambiguous = head_ref, via, session_ambiguous


def place_request(record: dict[str, Any], moment: datetime | None,
                  pulls: dict[tuple[str, str], list[dict[str, Any]]] | None, now: datetime,
                  sessions: SessionMap | None = None) -> Placement:
    """The task of a request: first by repository, branch and time as `assign_task` does. Only when
    that gives no pull request (the branch has none, is the base branch, or is unknown) and the
    request's cloud session produced exactly one landed pull request of the same repository, the
    request goes to that pull request (`via = session`). Two or more: it stays and is marked.
    A request whose repository is unknown (a cloud session often starts outside any checkout) goes
    to a pull request only when its session produced exactly one across all repositories, and then
    takes that pull request's repository. Nothing else is guessed; a run without `pulls` is never
    moved."""
    repository, branch = record["repository"], record["branch"]
    if repository is None or branch is None:
        placed = Placement("unknown", repository, branch)
    elif pulls is None:
        return Placement("branch", repository, branch)
    else:
        kind, number = assign_task(repository, branch, moment, pulls, now)
        if kind == "pr":
            return Placement("pr", repository, branch, number, branch)
        placed = Placement(kind, repository, branch)
    if (placed.kind not in ("unknown", "none") or sessions is None or pulls is None
            or not record.get("remote_session")):
        return placed
    produced = sessions.produced(record["remote_session"], repository)
    if not produced:
        return placed
    if len(produced) > 1:
        placed.session_ambiguous = True
        return placed
    (name, number, head), = produced
    return Placement("pr", repository or name, branch, number, head, "session")


# ---------------------------------------------------------------- report

def zone_for(tz_name: str | None) -> tuple[Any, str]:
    """(tzinfo, label) of a time zone name; UTC for none."""
    if not tz_name:
        return timezone.utc, "UTC"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name), tz_name
    except Exception as error:  # noqa: BLE001 - zoneinfo raises several types
        raise LedgerError(f"unknown time zone: {tz_name}") from error


def day_range(since: str, until: str, tz_name: str | None) -> tuple[datetime, datetime, str]:
    zone, label = zone_for(tz_name)
    start = datetime.combine(parse_day(since), datetime.min.time(), zone)
    end = datetime.combine(parse_day(until) + timedelta(days=1), datetime.min.time(), zone)
    if end <= start:
        raise LedgerError("--until is before --since")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc), label


def contract_timezone() -> str | None:
    """ledger.timezone from the contract of the current checkout; UTC outside a repository, when
    the contract has no such key, or when Python has no tomllib. An invalid contract is an error."""
    if git_top(os.getcwd()) is None:
        return None
    out = run([sys.executable, str(SCRIPTS / "plumb-project.py"), "ledger.timezone"], timeout=15)
    if out is None or out.returncode == 3:
        return None
    if out.returncode != 0:
        raise LedgerError("the project contract is invalid: " + first_line(out.stderr))
    return out.stdout.strip() or None


def collect_local(dirs: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], int]:
    """(pending records, exported records, conflict ids, pending sessions)."""
    pending: list[dict[str, Any]] = []
    exported: list[dict[str, Any]] = []
    conflicts: set[str] = set()
    sessions = 0
    for directory in dirs:
        for _runtime, _session, path in session_files(directory, "pending"):
            rows = load_records(path)
            if rows:
                sessions += 1
            pending.extend(rows)
        for _runtime, _session, path in session_files(directory, "exported"):
            exported.extend(load_records(path))
        for _runtime, _session, path in session_files(directory, "conflicts"):
            conflicts.update(read_conflict_ids(path))
    return pending, exported, conflicts, sessions


def store_cache_name(store: str) -> str:
    """The cache repository's directory name for a store: a hash of its URL with the credentials
    stripped, so a different store never shares a cache and a secret never reaches a path."""
    bare = re.sub(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/@]*@", r"\1", store.strip())
    bare = re.sub(r"^[^@/:]+@(?=[^/:]+:)", "", bare)  # git@host:owner/name
    return "store-cache-" + hashlib.sha1(bare.encode("utf-8", "replace")).hexdigest()[:16] + ".git"


def fetch_store(store: str, cache: Path) -> tuple[list[dict[str, Any]], set[str], str]:
    """(records, conflict ids, status) of every session ref in the store. Each ref's commit holds
    records.jsonl and, when the session had conflicting copies, conflicts.jsonl (ids only)."""
    repo = git_cache(cache.parent, cache.name)
    out = run(["git", "-C", str(repo), "fetch", "--quiet", "--no-tags", "--prune", store,
               f"+{STORE_REFS}/*:{STORE_REFS}/*"], env=git_env(), timeout=GIT_TIMEOUT)
    if out is None or out.returncode != 0:
        return [], set(), "unreachable: " + (first_line(out.stderr) if out else "git did not answer")
    refs = run(["git", "-C", str(repo), "for-each-ref", "--format=%(refname)", STORE_REFS + "/"], timeout=30)
    names = [n for n in (refs.stdout.split() if refs and refs.returncode == 0 else [])]
    if not names:
        return [], set(), "ok"
    wanted = [(name, file) for name in names for file in ("records.jsonl", "conflicts.jsonl")]
    batch = run(["git", "-C", str(repo), "cat-file", "--batch"], stdin="".join(f"{n}:{f}\n" for n, f in wanted),
                timeout=GIT_TIMEOUT)
    if batch is None or batch.returncode != 0:
        return [], set(), "unreachable: could not read the fetched refs"
    records: list[dict[str, Any]] = []
    conflicts: set[str] = set()
    text = batch.stdout
    index = 0
    for _name, file in wanted:
        end = text.index("\n", index)
        header = text[index:end].split()
        if len(header) == 3 and header[1] == "blob":
            size = int(header[2])
            body = text[end + 1:end + 1 + size]
            index = end + 1 + size + 1
            for line in body.splitlines():
                with contextlib.suppress(ValueError, AttributeError):
                    if file == "records.jsonl":
                        record = project(json.loads(line))
                        if record is not None:
                            records.append(record)
                    else:
                        identity = clean(json.loads(line).get("id"), 210)
                        if identity:
                            conflicts.add(identity)
        else:
            index = end + 1
    return records, conflicts, "ok"


def merge_sources(sources: list[list[dict[str, Any]]], local_conflicts: set[str]) -> tuple[list[dict[str, Any]], set[str], int]:
    """One record per id (first source wins); the same id with different tokens or model is a
    conflict. Records without an id are never merged with another, except that the same row
    held by two sources (local copy and store copy) is one row."""
    by_id: dict[str, dict[str, Any]] = {}
    conflicts = set(local_conflicts)
    null_counts: list[Counter[str]] = []
    null_rows: dict[str, dict[str, Any]] = {}
    for rows in sources:
        counter: Counter[str] = Counter()
        for record in sorted(rows, key=sort_key):
            if record["id"] is None:
                line = record_line(record)
                counter[line] += 1
                null_rows[line] = record
            elif record["id"] not in by_id:
                by_id[record["id"]] = record
            elif tokens_of(record) != tokens_of(by_id[record["id"]]):
                conflicts.add(record["id"])
        null_counts.append(counter)
    merged = list(by_id.values())
    unidentified = 0
    for line, record in null_rows.items():
        count = max(counter[line] for counter in null_counts)
        merged.extend([record] * count)
        unidentified += count
    merged.sort(key=sort_key)
    return merged, conflicts, unidentified


def load_json(path: str, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LedgerError(f"{label} {path}: not readable JSON ({type(error).__name__})") from error


def rework_numbers(data: Any) -> tuple[set[tuple[str | None, int]], set[tuple[str | None, int]]]:
    """(originals, fixers) as (repo_key or None, number) from `plumb-ledger rework --json`.
    Accepts a list of numbers or of objects with number / pr / original (+ fixed_by / fix)."""
    originals: set[tuple[str | None, int]] = set()
    fixers: set[tuple[str | None, int]] = set()
    repo = repo_key(data["repository"]) if isinstance(data, dict) and isinstance(data.get("repository"), str) else None
    # `plumb-ledger rework --json` lists them under reworked_changes (reworked is the count).
    rows = (data.get("reworked_changes", data.get("reworked")) if isinstance(data, dict) else data)
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, int) and not isinstance(row, bool):
            originals.add((repo, row))
        elif isinstance(row, dict):
            row_repo = repo_key(row["repository"]) if isinstance(row.get("repository"), str) else repo
            for key in ("number", "pr", "original"):
                if isinstance(row.get(key), int):
                    originals.add((row_repo, row[key]))
                    break
            for key in ("fixed_by", "fix", "fixing_pr"):
                values = row.get(key)
                for value in values if isinstance(values, list) else [values]:
                    if isinstance(value, dict):
                        value = value.get("number")
                    if isinstance(value, int) and not isinstance(value, bool):
                        fixers.add((row_repo, value))
    return originals, fixers


def landed_numbers(path: str) -> set[tuple[str, int]]:
    landed: set[tuple[str, int]] = set()
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise LedgerError(f"--changes {path}: not readable ({type(error).__name__})") from error
    for line in lines:
        with contextlib.suppress(ValueError):
            row = json.loads(line)
            if isinstance(row, dict) and row.get("kind") == "pull_request" and isinstance(row.get("number"), int) and row.get("merged_at"):
                landed.add((repo_key(row.get("repository") if isinstance(row.get("repository"), str) else ""), row["number"]))
    return landed


def canonical_repositories(names: Any) -> dict[str, str]:
    """lowercase name -> the spelling shown for it: the smallest of the spellings seen, whatever the
    order. GitHub names are case-insensitive, and a record, a pull request row from `changes` and a
    `--prs` file may spell one repository differently; a task must not split in two for that."""
    chosen: dict[str, str] = {}
    for name in names:
        if name:
            key = repo_key(name)
            chosen[key] = min(chosen.get(key, name), name)
    return chosen


def build_report(records: list[dict[str, Any]], pulls: dict[tuple[str, str], list[dict[str, Any]]] | None,
                 versions: list[dict[str, Any]], now: datetime, sessions: SessionMap | None = None) -> dict[str, Any]:
    """Pure: records in, the report's numbers out. Every Decimal is rendered with str().
    With `sessions` (and `pulls`), a request the branch rule leaves without a pull request may go to
    the one pull request its session produced; see place_request."""
    zero = Decimal(0)
    total = zero
    priced = unknown_cost = unknown_attribution = ambiguous = no_pr = unknown_time = 0
    session_assigned = session_ambiguous = 0
    by_task: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_role: dict[str, dict[str, Any]] = {}
    by_kind = {key: zero for key in TOKEN_FIELDS}
    frontier = zero

    def bump(table: dict[str, dict[str, Any]], key: str, cost: dict[str, Decimal] | None) -> None:
        row = table.setdefault(key, {"cost": zero, "requests": 0, "unknown_cost": 0})
        row["requests"] += 1
        if cost is None:
            row["unknown_cost"] += 1
        else:
            row["cost"] += sum(cost.values(), zero)

    placements = [place_request(record, parse_time(record["time"]), pulls, now, sessions) for record in records]
    spelling = canonical_repositories(placed.repository for placed in placements)
    for record, placed in zip(records, placements):
        cost = price_request(record, versions)
        moment = parse_time(record["time"])
        if moment is None:
            unknown_time += 1
        if cost is None:
            unknown_cost += 1
        else:
            amount = sum(cost.values(), zero)
            total += amount
            priced += 1
            for key, value in cost.items():
                by_kind[key] += value
            if any(word in (record["model"] or "").lower() for word in FRONTIER):
                frontier += amount
        session_ambiguous += placed.session_ambiguous
        name = spelling.get(repo_key(placed.repository), placed.repository)
        if placed.kind == "unknown":
            unknown_attribution += 1
            task = "unknown attribution"
        elif placed.kind == "branch":
            task = f"{name} @ {placed.branch}"
        elif placed.kind == "pr":
            session_assigned += placed.via == "session"
            task = f"{name}#{placed.number}"
        elif placed.kind == "ambiguous":
            ambiguous += 1
            task = "ambiguous"
        else:
            no_pr += 1
            task = "no pull request"
        bump(by_task, task, cost)
        bump(by_model, record["model"] or "unknown model", cost)
        role = "main" if record["role"] == "main" else f"subagent:{record['agent_type'] or 'unknown'}"
        bump(by_role, role, cost)
    result = {
        "requests": len(records), "priced": priced, "total_cost": total, "frontier_cost": frontier,
        "by_task": by_task, "by_model": by_model, "by_role": by_role, "by_token_kind": by_kind,
        "unknown": {"cost": unknown_cost, "attribution": unknown_attribution, "ambiguous": ambiguous,
                    "no_pull_request": no_pr, "time": unknown_time},
    }
    if sessions is not None:
        result["unknown"]["session_ambiguous"] = session_ambiguous
        result["session_attribution"] = {"applied": pulls is not None, "assigned": session_assigned,
                                         "ambiguous": session_ambiguous}
    return result


def render_table(table: dict[str, dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    rows = [{"name": name, "cost": row["cost"], "requests": row["requests"], "unknown_cost": row["unknown_cost"]}
            for name, row in table.items()]
    rows.sort(key=lambda row: (-row["cost"], row["name"]))
    return rows[:limit] if limit else rows


def add_source_arguments(parser: argparse.ArgumentParser) -> None:
    """The options `report` and `views` share: where records come from and which are kept."""
    parser.add_argument("--since", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--until", required=True, metavar="YYYY-MM-DD", help="inclusive")
    parser.add_argument("--prs", action="append", default=[], metavar="FILE", help="output of `plumb-ledger prs` (repeatable, one per repository); without it tasks are repository @ branch")
    parser.add_argument("--changes", action="append", default=[], metavar="FILE", help="output of `plumb-ledger changes` (repeatable): splits cost into landed and not landed pull requests, and moves a request the branch rule leaves without a pull request to the one landed pull request its cloud session produced (needs --prs)")
    parser.add_argument("--store-cache", metavar="DIR", help="the cache repository for the store's refs (default: <ledger dir>/store-cache-<hash of the store URL>.git)")
    parser.add_argument("--ledger-dir", action="append", default=[], metavar="DIR", help="look here for local records (repeatable)")
    parser.add_argument("--repo", metavar="OWNER/NAME", help="only this repository's requests, by the repository a request is placed in (see --changes); requests of other "
                        "repositories, and those still without one, are counted and left out")
    parser.add_argument("--timezone", metavar="ZONE", help="calendar days in this zone (default: ledger.timezone of the contract, else UTC)")
    parser.add_argument("--prices", metavar="FILE", default=str(PRICES_FILE), help=argparse.SUPPRESS)
    parser.add_argument("--now", metavar="ISO", help=argparse.SUPPRESS)


def report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plumb-ledger report",
        description="The weekly cost report: total, by task (top 10), model, frontier share, role and "
                    "agent type, token kind; cost of reworked changes; what is unknown; coverage. Reads the "
                    "local records and the store's refs (fetched into a cache repository).")
    add_source_arguments(parser)
    parser.add_argument("--rework", metavar="FILE", help="output of `plumb-ledger rework --json`: adds the cost of reworked changes")
    parser.add_argument("--json", action="store_true", help="print JSON (money as exact decimal strings)")
    return parser


def gather(args: argparse.Namespace, start: datetime, end: datetime) -> dict[str, Any]:
    """The records of the period from the local directories and the store, merged by id, and what
    is known about them. `merged` is every record with its time (the timeline of a session needs
    the requests around the period); `in_period` is the period's and `in_period_index` their
    positions in `merged`. scope_period() then applies --repo."""
    dirs = ledger_dirs(os.getcwd(), args.ledger_dir)
    pending, exported, local_conflicts, pending_sessions = collect_local(dirs)

    store = config("ledger.store")
    store_rows: list[dict[str, Any]] = []
    store_conflicts: set[str] = set()
    store_status = "unset"
    if store:
        cache = Path(args.store_cache) if args.store_cache else (dirs[0] if dirs else ledger_dir(os.getcwd(), False)) / store_cache_name(store)
        store_rows, store_conflicts, store_status = fetch_store(store, cache)
    merged, conflicts, unidentified = merge_sources([pending, exported, store_rows], local_conflicts | store_conflicts)
    in_period = []
    for index, record in enumerate(merged):
        moment = parse_time(record["time"])
        if moment is not None and start <= moment < end:
            in_period.append(index)
    outside_time = sum(1 for record in merged if parse_time(record["time"]) is None)
    return {"merged": merged, "in_period_index": in_period, "in_period": [merged[i] for i in in_period],
            "unidentified": unidentified, "conflicts": conflicts, "outside_time": outside_time,
            "scope": None, "pending_sessions": pending_sessions, "pending_records": len(pending),
            "store": store, "store_status": store_status}


def scope_period(found: dict[str, Any], repo: str | None, pulls: dict | None, sessions: SessionMap | None,
                 now: datetime) -> None:
    """Keep the period's requests of --repo, by the repository a request is placed in: a request
    whose repository is unknown but whose session produced exactly one pull request is counted in
    that pull request's repository. Only requests still without a repository are reported as
    unknown. One repository's retro must not carry another's cost; what cannot be placed is counted,
    never added."""
    if not repo:
        return
    merged, wanted = found["merged"], repo_key(repo)
    kept, other, unknown = [], 0, 0
    for index in found["in_period_index"]:
        record = merged[index]
        name = place_request(record, parse_time(record["time"]), pulls, now, sessions).repository
        if not name:
            unknown += 1
        elif repo_key(name) == wanted:
            kept.append(index)
        else:
            other += 1
    found["in_period_index"] = kept
    found["in_period"] = [merged[i] for i in kept]
    found["scope"] = {"repository": repo, "other_repositories": other, "unknown_repository": unknown}


def cmd_report(argv: list[str]) -> int:
    args = report_parser().parse_args(argv)
    tz_name = args.timezone or contract_timezone()
    start, end, label = day_range(args.since, args.until, tz_name)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    versions = load_prices(Path(args.prices))
    found = gather(args, start, end)
    pulls = load_prs(args.prs) if args.prs else None
    sessions = session_map(args.changes) if args.changes else None
    scope_period(found, args.repo, pulls, sessions, now)
    in_period, conflicts, scope = found["in_period"], found["conflicts"], found["scope"]
    store, store_status = found["store"], found["store_status"]
    result = build_report(in_period, pulls, versions, now, sessions)
    period_ids = {record["id"] for record in in_period if record["id"]}
    result["unknown"]["unidentified"] = sum(1 for record in in_period if record["id"] is None)
    result["unknown"]["id_conflicts"] = len(conflicts & period_ids)
    result["unknown"]["time"] = found["outside_time"]
    pending_records = found["pending_records"]
    result["coverage"] = {
        "pending_sessions": found["pending_sessions"], "pending_records": pending_records, "store": store_status.split(":")[0],
        "store_detail": store_status, "complete": pending_records == 0 and store_status in ("unset", "ok"),
        "note": "cloud sessions are not covered (ledger.store is unset)" if not store else "",
    }
    result["period"] = {"since": args.since, "until": args.until, "timezone": label}
    if scope:
        result["scope"] = scope
    if args.changes:
        landed: set[tuple[str, int]] = set()
        for path in args.changes:
            landed |= landed_numbers(path)
        split = {"landed": Decimal(0), "not_landed": Decimal(0)}
        for name, row in result["by_task"].items():
            match = re.fullmatch(r"(.+)#(\d+)", name)
            if match:
                is_landed = any((repo == "" or repo == repo_key(match.group(1))) and number == int(match.group(2))
                                for repo, number in landed)
                split["landed" if is_landed else "not_landed"] += row["cost"]
        result["landed_split"] = split
    if args.rework:
        originals, fixers = rework_numbers(load_json(args.rework, "--rework"))

        def task_cost(wanted: set[tuple[str | None, int]]) -> Decimal:
            sum_cost = Decimal(0)
            for name, row in result["by_task"].items():
                match = re.fullmatch(r"(.+)#(\d+)", name)
                if match and any((repo is None or repo == repo_key(match.group(1))) and number == int(match.group(2))
                                 for repo, number in wanted):
                    sum_cost += row["cost"]
            return sum_cost

        result["rework"] = {"reworked_changes": len(originals), "cost_of_reworked": task_cost(originals),
                            "cost_of_fixes": task_cost(fixers)}
    if args.json:
        print(json.dumps(jsonable(result), indent=2, sort_keys=True))
    else:
        print_report(result)
    return 0


def jsonable(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    for key in ("by_task", "by_model", "by_role"):
        out[key] = render_table(result[key])
    out["by_task_top10"] = out["by_task"][:10]
    frontier = result["frontier_cost"]
    out["frontier_share"] = str((frontier / result["total_cost"]).quantize(Decimal("0.0001"))) if result["total_cost"] else None

    def convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        return value

    return convert(out)


def print_report(result: dict[str, Any]) -> None:
    period = result["period"]
    unknown = result["unknown"]
    coverage = result["coverage"]
    total = result["total_cost"]
    print(f"plumb-ledger report {period['since']} .. {period['until']} ({period['timezone']})")
    print(f"total cost: {money(total)}  ({result['priced']} of {result['requests']} requests priced; "
          f"{unknown['cost']} with unknown cost are not in the total)")

    def table(title: str, rows: list[dict[str, Any]]) -> None:
        print(f"\n{title}")
        for row in rows:
            extra = f"  [{row['unknown_cost']} unknown cost]" if row["unknown_cost"] else ""
            print(f"  {money(row['cost']):>12}  {row['requests']:>6} req  {row['name']}{extra}")

    table("by task (top 10)", render_table(result["by_task"], 10))
    table("by model", render_table(result["by_model"]))
    share = f"{(result['frontier_cost'] / total * 100).quantize(Decimal('0.1'))}%" if total else "n/a"
    print(f"\nfrontier share (fable, mythos, opus): {money(result['frontier_cost'])} = {share}")
    table("by role and agent type", render_table(result["by_role"]))
    print("\nby token kind")
    for key, value in result["by_token_kind"].items():
        print(f"  {money(value):>12}  {key}")
    if "landed_split" in result:
        split = result["landed_split"]
        print(f"\nlanded pull requests: {money(split['landed'])}; not landed: {money(split['not_landed'])}")
    if "rework" in result:
        rework = result["rework"]
        print(f"\nreworked changes: {rework['reworked_changes']}; their cost {money(rework['cost_of_reworked'])}; "
              f"the fixes' cost {money(rework['cost_of_fixes'])}")
    print("\nunknown, counted and not guessed")
    print(f"  cost: {unknown['cost']}   attribution: {unknown['attribution']}   ambiguous: {unknown['ambiguous']}   "
          f"no pull request: {unknown['no_pull_request']}")
    print(f"  unidentified requests: {unknown['unidentified']}   id conflicts: {unknown['id_conflicts']}   "
          f"without a time: {unknown['time']}")
    if result.get("scope"):
        scope = result["scope"]
        print(f"\nrepository: {scope['repository']} only; left out: {scope['other_repositories']} request(s) of other "
              f"repositories, {scope['unknown_repository']} whose repository is unknown")
    if "session_attribution" in result:
        moved = result["session_attribution"]
        print("\nsession attribution: " + (
            f"{moved['assigned']} request(s) moved to the pull request their session produced; "
            f"{moved['ambiguous']} left (the session produced several)" if moved["applied"]
            else "skipped (it needs --prs)"))
    print("\ncoverage: " + ("complete" if coverage["complete"] else "INCOMPLETE"))
    print(f"  pending export: {coverage['pending_records']} requests in {coverage['pending_sessions']} session(s)")
    print(f"  store: {coverage['store_detail']}" + (f" ({coverage['note']})" if coverage["note"] else ""))


# ---------------------------------------------------------------- entry

def cmd_views(argv: list[str]) -> int:
    import ledger_views   # imports this module: loaded on demand
    return ledger_views.cmd_views(argv)


COMMANDS = {"capture": cmd_capture, "export": cmd_export, "prs": cmd_prs, "report": cmd_report, "views": cmd_views}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print("usage: plumb-ledger capture|export|prs|report|views [options]", file=sys.stderr)
        return 2
    hook_cwd = os.getcwd()
    try:
        return COMMANDS[argv[0]](argv[1:])
    except LedgerError as error:
        print(f"plumb-ledger {argv[0]}: {error}", file=sys.stderr)
        if "--hook-input" in argv:
            log_failure(error, hook_cwd)
        return 2 if argv[0] != "capture" else 1
    except Exception as error:  # noqa: BLE001 - the CLI's defined unexpected-error boundary
        print(f"plumb-ledger {argv[0]}: unexpected {type(error).__name__}", file=sys.stderr)
        if "--hook-input" in argv:
            log_failure(error, hook_cwd)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
