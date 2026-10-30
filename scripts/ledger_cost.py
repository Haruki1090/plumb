"""Cost per task: capture, price, store, export, task assignment and the weekly report.

    plumb-ledger capture [--hook-input <file> | --transcript <path>] [--runtime claude|codex]
                         [--transcripts <dir>] [--cwd <dir>] [--json]
    plumb-ledger export  [--session <id>] [--runtime claude|codex] [--check] [--ledger-dir <dir>]
    plumb-ledger prs     --repo <owner/name> --since <date> [--out <json>]
    plumb-ledger report  --since <date> --until <date> [--prs <json>] [--changes <jsonl>]
                         [--rework <json>] [--store-cache <dir>] [--json]

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
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any, Iterator

SCRIPTS = Path(__file__).resolve().parent
PLUGIN = SCRIPTS.parent
PRICES_FILE = PLUGIN / "assets" / "prices.json"

# The only keys a record carries, in this order. Everything that is written to a pending file,
# an exported file or the store passes through project().
FIELDS = ("id", "time", "model", "input", "output", "cache_read", "cache_write_5m",
          "cache_write_1h", "repository", "branch", "attribution_source", "role", "agent_type",
          "agent_id", "session", "runtime")
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
SOURCES = ("transcript", "worktree_at_capture", "unknown")
RUNTIMES = ("claude", "codex")
FRONTIER = ("fable", "mythos", "opus")
SAFE = re.compile(r"[\w./@+:#=,%~\-\[\]]{1,200}")
SAFE_SESSION = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")
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
        return self.ask(("head", path), ["git", "-C", path, "symbolic-ref", "--short", "-q", "HEAD"]) or None

    def attribute(self, record: dict[str, Any], meta: dict[str, Any] | None) -> tuple[str | None, str | None, str]:
        """(repository, branch, source) in the order of evidence the contract gives.

        1. The record's own cwd resolves to a checkout and its gitBranch is a real branch there
           (HEAD and empty mean no branch).
        2. A subagent started in a worktree: that worktree's current branch, read now.
        3. Otherwise unknown. A past branch is never inferred from today's main checkout."""
        worktree = meta.get("worktreePath") if meta else None
        if isinstance(worktree, str) and worktree:
            if self.top(worktree):
                branch = self.head_branch(worktree)
                if branch:
                    return self.repository(worktree), branch, "worktree_at_capture"
                return self.repository(worktree), None, "unknown"
            return None, None, "unknown"
        cwd = record.get("cwd")
        if not isinstance(cwd, str) or not cwd or not self.top(cwd):
            return None, None, "unknown"
        repository = self.repository(cwd)
        branch = record.get("gitBranch")
        if isinstance(branch, str) and branch not in ("", "HEAD") and self.has_branch(cwd, branch):
            return repository, branch, "transcript"
        return repository, None, "unknown"


# ---------------------------------------------------------------- reading transcripts

def read_complete_lines(path: Path, offset: int) -> Iterator[tuple[int, bytes]]:
    """(offset after the line, line) for each newline-terminated line from `offset`. A last line
    without its newline is not complete yet and is left for the next capture."""
    position = offset
    carry = b""
    with open(path, "rb") as handle:
        handle.seek(offset)
        while True:
            chunk = handle.read(1 << 22)
            if not chunk:
                return
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

    def __init__(self, runtime: str, session: str, known: dict[str, tuple[Any, ...]]) -> None:
        self.runtime = runtime
        self.session = session
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
            "session": self.session, "runtime": self.runtime,
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
        # Codex rows carry no per-request branch: attribution is unknown, the repository is not.
        repository = checkouts.repository(cwd) if cwd and checkouts.top(cwd) else None
        if identity is not None and identity in capture.known:
            capture.counts["duplicates"] += 1
            continue
        capture.add(request, "main", None, None, (repository, None, "unknown"), identity)
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
        if isinstance(saved, dict) and isinstance(saved.get("session_id"), str):
            session = safe_session(saved["session_id"])
    capture = Capture(runtime, session, known_ids(directory, runtime, session))
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
    source.add_argument("--transcripts", metavar="DIR", help="a directory of transcripts (every direct .jsonl)")
    parser.add_argument("--runtime", choices=RUNTIMES, default="claude")
    parser.add_argument("--cwd", metavar="DIR", help="the checkout the session ran in, for repository and branch (default: the hook's cwd, else the current directory)")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    return parser


def cmd_capture(argv: list[str]) -> int:
    args = capture_parser().parse_args(argv)
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
        mains = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".jsonl")
    else:
        raise LedgerError("give --hook-input, --transcript or --transcripts")
    cwd = cwd or os.getcwd()
    directory = ledger_dir(cwd, True)
    summaries = []
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
    for summary in summaries:
        if args.json:
            print(json.dumps(summary, sort_keys=True))
        else:
            print("capture: {runtime} session={session} new={new} duplicates={duplicates} "
                  "unidentified={unidentified} conflicts={conflicts} bytes_read={bytes_read}".format(**summary))
    return status


def log_failure(error: BaseException, cwd: str | None) -> None:
    """The hook path has nowhere to print: leave one line, type and message only, in the ledger directory."""
    with contextlib.suppress(Exception):
        directory = ledger_dir(cwd, True)
        with open(directory / "capture.log", "a", encoding="utf-8") as handle:
            handle.write(f"{format_time(datetime.now(timezone.utc))} capture failed: "
                         f"{type(error).__name__}: {redact(str(error))[:200]}\n")


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


def assign_task(repository: str | None, branch: str | None, moment: datetime | None,
                pulls: dict[tuple[str, str], list[dict[str, Any]]], now: datetime) -> tuple[str, int | None]:
    """('pr', number) | ('ambiguous', None) | ('none', None) for a known repository and branch.

    Among the pull requests of the repository and head ref, in creation order, the request belongs
    to the first whose close time (or now, while open) is at or after the request's time. If that
    first one is open and another is open too, the request is ambiguous."""
    candidates = pulls.get((repository or "", branch or ""), [])
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
                pulls.setdefault((entry.get("repository", ""), pull["head_ref"]), []).append({
                    "number": pull["number"], "created": created, "closed": parse_time(pull.get("closed_at"))})
    for rows in pulls.values():
        rows.sort(key=lambda p: (p["created"], p["number"]))
    return pulls


# ---------------------------------------------------------------- report

def day_range(since: str, until: str, tz_name: str | None) -> tuple[datetime, datetime, str]:
    zone: Any = timezone.utc
    label = "UTC"
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            zone, label = ZoneInfo(tz_name), tz_name
        except Exception as error:  # noqa: BLE001 - zoneinfo raises several types
            raise LedgerError(f"unknown time zone: {tz_name}") from error
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
    """(originals, fixers) as (repository or None, number) from `plumb-ledger rework --json`.
    Accepts a list of numbers or of objects with number / pr / original (+ fixed_by / fix)."""
    originals: set[tuple[str | None, int]] = set()
    fixers: set[tuple[str | None, int]] = set()
    repo = data.get("repository") if isinstance(data, dict) and isinstance(data.get("repository"), str) else None
    # `plumb-ledger rework --json` lists them under reworked_changes (reworked is the count).
    rows = (data.get("reworked_changes", data.get("reworked")) if isinstance(data, dict) else data)
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, int) and not isinstance(row, bool):
            originals.add((repo, row))
        elif isinstance(row, dict):
            row_repo = row.get("repository") if isinstance(row.get("repository"), str) else repo
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
                landed.add((row.get("repository") or "", row["number"]))
    return landed


def build_report(records: list[dict[str, Any]], pulls: dict[tuple[str, str], list[dict[str, Any]]] | None,
                 versions: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Pure: records in, the report's numbers out. Every Decimal is rendered with str()."""
    zero = Decimal(0)
    total = zero
    priced = unknown_cost = unknown_attribution = ambiguous = no_pr = unknown_time = 0
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

    for record in records:
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
        repository, branch = record["repository"], record["branch"]
        if repository is None or branch is None:
            unknown_attribution += 1
            task = "unknown attribution"
        elif pulls is None:
            task = f"{repository} @ {branch}"
        else:
            kind, number = assign_task(repository, branch, moment, pulls, now)
            if kind == "pr":
                task = f"{repository}#{number}"
            elif kind == "ambiguous":
                ambiguous += 1
                task = "ambiguous"
            else:
                no_pr += 1
                task = "no pull request"
        bump(by_task, task, cost)
        bump(by_model, record["model"] or "unknown model", cost)
        role = "main" if record["role"] == "main" else f"subagent:{record['agent_type'] or 'unknown'}"
        bump(by_role, role, cost)
    return {
        "requests": len(records), "priced": priced, "total_cost": total, "frontier_cost": frontier,
        "by_task": by_task, "by_model": by_model, "by_role": by_role, "by_token_kind": by_kind,
        "unknown": {"cost": unknown_cost, "attribution": unknown_attribution, "ambiguous": ambiguous,
                    "no_pull_request": no_pr, "time": unknown_time},
    }


def render_table(table: dict[str, dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    rows = [{"name": name, "cost": row["cost"], "requests": row["requests"], "unknown_cost": row["unknown_cost"]}
            for name, row in table.items()]
    rows.sort(key=lambda row: (-row["cost"], row["name"]))
    return rows[:limit] if limit else rows


def report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plumb-ledger report",
        description="The weekly cost report: total, by task (top 10), model, frontier share, role and "
                    "agent type, token kind; cost of reworked changes; what is unknown; coverage. Reads the "
                    "local records and the store's refs (fetched into a cache repository).")
    parser.add_argument("--since", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--until", required=True, metavar="YYYY-MM-DD", help="inclusive")
    parser.add_argument("--prs", action="append", default=[], metavar="FILE", help="output of `plumb-ledger prs` (repeatable, one per repository); without it tasks are repository @ branch")
    parser.add_argument("--changes", metavar="FILE", help="output of `plumb-ledger changes`: splits cost into landed and not landed pull requests")
    parser.add_argument("--rework", metavar="FILE", help="output of `plumb-ledger rework --json`: adds the cost of reworked changes")
    parser.add_argument("--store-cache", metavar="DIR", help="the cache repository for the store's refs (default: <ledger dir>/store-cache-<hash of the store URL>.git)")
    parser.add_argument("--ledger-dir", action="append", default=[], metavar="DIR", help="look here for local records (repeatable)")
    parser.add_argument("--timezone", metavar="ZONE", help="calendar days in this zone (default: ledger.timezone of the contract, else UTC)")
    parser.add_argument("--prices", metavar="FILE", default=str(PRICES_FILE), help=argparse.SUPPRESS)
    parser.add_argument("--now", metavar="ISO", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="print JSON (money as exact decimal strings)")
    return parser


def cmd_report(argv: list[str]) -> int:
    args = report_parser().parse_args(argv)
    tz_name = args.timezone or contract_timezone()
    start, end, label = day_range(args.since, args.until, tz_name)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    versions = load_prices(Path(args.prices))
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
    for record in merged:
        moment = parse_time(record["time"])
        if moment is not None and start <= moment < end:
            in_period.append(record)
    outside_time = sum(1 for record in merged if parse_time(record["time"]) is None)
    pulls = load_prs(args.prs) if args.prs else None
    result = build_report(in_period, pulls, versions, now)
    period_ids = {record["id"] for record in in_period if record["id"]}
    result["unknown"]["unidentified"] = sum(1 for record in in_period if record["id"] is None)
    result["unknown"]["id_conflicts"] = len(conflicts & period_ids)
    result["unknown"]["time"] = outside_time
    pending_records = len(pending)
    result["coverage"] = {
        "pending_sessions": pending_sessions, "pending_records": pending_records, "store": store_status.split(":")[0],
        "store_detail": store_status, "complete": pending_records == 0 and store_status in ("unset", "ok"),
        "note": "cloud sessions are not covered (ledger.store is unset)" if not store else "",
    }
    result["period"] = {"since": args.since, "until": args.until, "timezone": label}
    if args.changes:
        landed = landed_numbers(args.changes)
        split = {"landed": Decimal(0), "not_landed": Decimal(0)}
        for name, row in result["by_task"].items():
            match = re.fullmatch(r"(.+)#(\d+)", name)
            if match:
                is_landed = any(repo in ("", match.group(1)) and number == int(match.group(2)) for repo, number in landed)
                split["landed" if is_landed else "not_landed"] += row["cost"]
        result["landed_split"] = split
    if args.rework:
        originals, fixers = rework_numbers(load_json(args.rework, "--rework"))

        def task_cost(wanted: set[tuple[str | None, int]]) -> Decimal:
            sum_cost = Decimal(0)
            for name, row in result["by_task"].items():
                match = re.fullmatch(r"(.+)#(\d+)", name)
                if match and any(repo in (None, match.group(1)) and number == int(match.group(2)) for repo, number in wanted):
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
    print("\ncoverage: " + ("complete" if coverage["complete"] else "INCOMPLETE"))
    print(f"  pending export: {coverage['pending_records']} requests in {coverage['pending_sessions']} session(s)")
    print(f"  store: {coverage['store_detail']}" + (f" ({coverage['note']})" if coverage["note"] else ""))


# ---------------------------------------------------------------- entry

COMMANDS = {"capture": cmd_capture, "export": cmd_export, "prs": cmd_prs, "report": cmd_report}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print("usage: plumb-ledger capture|export|prs|report [options]", file=sys.stderr)
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
