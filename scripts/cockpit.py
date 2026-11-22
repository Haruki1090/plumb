"""Shared CLI, paths and route history for cockpit commands."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
REFERENCES = ROOT / "skills/cockpit/references"
ROUTE_LOG = "route-events.jsonl"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
STORE_NAME = re.compile(r"[a-z0-9_-]+", re.ASCII)
ATTEMPT_EVENTS = {"attempt-started", "attempt-collected", "observed", "adjudicated", "abandoned"}


class Invalid(ValueError):
    pass


class Unavailable(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Invalid(message)


def parser(name, description):
    cli = Parser(prog=name, description=description, allow_abbrev=False)
    cli.add_argument("--json", action="store_true", help="print the schema 1 JSON response")
    return cli


def subcommand(commands, name, help_text, *, repo=True):
    cli = commands.add_parser(name, help=help_text, description=help_text, allow_abbrev=False)
    cli.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print JSON")
    if repo:
        cli.add_argument("--repo", type=Path, help="repository checkout (default: current directory)")
    return cli


def answer(args, outcome, data=None, *, codes=(), status=0, message=None):
    if args.json:
        print(json.dumps({"schema": 1, "outcome": outcome, "reason_codes": list(codes), "data": data or {}}))
    else:
        print(message or outcome, file=sys.stderr if status >= 2 else sys.stdout)
    return status


def run_cli(cli, handler):
    try:
        args = cli.parse_args()
        return handler(args)
    except Exception as exc:
        status = 3 if isinstance(exc, Unavailable) else 2
        outcome = "unavailable" if status == 3 else "invalid"
        args = argparse.Namespace(json="--json" in sys.argv[1:])
        return answer(args, outcome, {"message": str(exc)}, status=status, message=f"{cli.prog}: {exc}")


def identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise Invalid(f"{field} must start with a letter or digit and contain only letters, digits, '.', '_' or '-'")
    return value


def store_name(value, field):
    if not isinstance(value, str) or not value.isascii() or not STORE_NAME.fullmatch(value.lower()):
        raise Invalid(f"{field} must contain only ASCII letters, digits, '_' or '-'")
    return value.lower()


def positive_int(value, field):
    if type(value) is not int or value < 1:
        raise Invalid(f"{field} must be a positive integer")
    return value


def nonempty(value, field):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise Invalid(f"{field} must be nonempty text")
    return value.strip()


def invoke(*args, cwd=None):
    try:
        result = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True)
    except FileNotFoundError as exc:
        raise Unavailable(f"{args[0]} is unavailable") from exc
    if result.returncode:
        detail = os.fsdecode(result.stderr).strip()
        raise Invalid(detail or f"{args[0]} exited {result.returncode}")
    return result.stdout


def git(repo, *args, allowed=(0,), overrides=None):
    # A lane path takes precedence over Git environment overrides inherited from the caller.
    env = {key: value for key, value in os.environ.items() if key not in {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_PREFIX",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    }}
    env.update(GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0")
    env.update(overrides or {})
    try:
        result = subprocess.run(["git", "-C", repo, "-c", "core.fsmonitor=false",
                                 "-c", "core.hooksPath=/dev/null", *args],
                                env=env, stdin=subprocess.DEVNULL, capture_output=True)
    except FileNotFoundError as exc:
        raise Unavailable("git is unavailable") from exc
    if result.returncode not in allowed:
        raise Invalid(os.fsdecode(result.stderr).strip() or f"git exited {result.returncode}")
    return result.stdout


def git_path(repo, *args):
    return Path(os.fsdecode(git(repo, "rev-parse", *args).rstrip(b"\n"))).resolve()


def run_root(repo):
    checkout = Path(repo or Path.cwd()).resolve(strict=True)
    if not checkout.is_dir():
        raise Invalid("repository path must be a directory")
    common = git_path(checkout, "--path-format=absolute", "--git-common-dir").stat()
    # Git lists the primary checkout first, including when its Git directory lives elsewhere.
    primary = git(checkout, "worktree", "list", "--porcelain", "-z").split(b"\0", 1)[0]
    primary = os.fsdecode(primary.removeprefix(b"worktree "))
    path = invoke("bash", str(ROOT / "scripts/plumb-path.sh"), "run", primary, cwd=checkout)
    return Path(os.fsdecode(path.rstrip(b"\n"))).resolve() / "cockpit" / f"{common.st_dev:x}-{common.st_ino:x}"


def run_directory(root, name):
    name = store_name(name, "run")
    if name == "locks":
        raise Invalid(f"the run name {name!r} is reserved")
    return root / name


def config(key, default=""):
    return os.fsdecode(invoke("bash", str(ROOT / "scripts/plumb-config.sh"), key, default)).rstrip("\n")


def kinds():
    with (REFERENCES / "kinds.tsv").open(encoding="utf-8", newline="") as handle:
        return {row["kind"]: row for row in csv.DictReader(handle, delimiter="\t")}


def kind_info(kind):
    options = kinds()
    if kind not in options:
        raise Invalid(f"unknown kind {kind!r}. Choose from: {', '.join(options)}")
    return options[kind]


def read_events(path, *, repair=False):
    events = []
    seen = set()
    with path.open("rb") as handle:
        offset = 0
        for line_number, line in enumerate(handle, 1):
            if not line.endswith(b"\n"):
                if repair:
                    with path.open("r+b") as output:
                        output.truncate(offset)
                        os.fsync(output.fileno())
                    print(f"recovered incomplete event in {path} at line {line_number}", file=sys.stderr)
                break
            offset += len(line)
            event_id = None
            try:
                event = json.loads(line.decode("utf-8"))
                event_id = event["event_id"]
                if not isinstance(event_id, str) or not event_id or not isinstance(event["data"], dict):
                    raise ValueError
                if any(not isinstance(event[key], str) for key in ("type", "lane", "work", "ts")):
                    raise ValueError
                positive_int(event["seq"], "seq")
                data = event["data"]
                if event["type"] in ATTEMPT_EVENTS:
                    positive_int(data["attempt"], "attempt")
                if "demote_after" in data:
                    positive_int(data["demote_after"], "demote_after")
                if "rev" in data:
                    store_name(data["rev"], "rev")
                if event_id in seen:
                    continue
                if event["seq"] != len(events) + 1:
                    raise Invalid("unexpected seq")
                event_time(event)
            except (KeyError, TypeError, ValueError) as exc:
                detail = f" ({event_id})" if event_id is not None else ""
                field = f": {exc}" if isinstance(exc, Invalid) else ""
                raise Invalid(f"invalid event{detail} in {path} at line {line_number}{field}") from exc
            events.append(event)
            seen.add(event_id)
    return events


def event_time(event):
    timestamp = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise Invalid("event timestamp needs a time zone")
    return timestamp


def history(root, *, repair=False):
    logs = {}
    if root.exists():
        for directory in sorted(root.iterdir()):
            path = directory / "events.jsonl"
            if directory.name.casefold() != "locks" and path.is_file():
                logs[directory.name] = read_events(path, repair=repair)
        reset = root / ROUTE_LOG
        if reset.exists():
            logs[ROUTE_LOG] = read_events(reset, repair=repair)
    return logs


def new_event(events, timestamp, event_type, lane, work, data, event_id=None):
    return {"seq": len(events) + 1, "event_id": event_id or uuid4().hex, "ts": timestamp.isoformat(),
            "type": event_type, "lane": lane, "work": work, "data": data}


def next_timestamp(logs):
    latest = max((event_time(event) for log in logs.values() for event in log), default=None)
    now = datetime.now(timezone.utc)
    return max(now, latest + timedelta(microseconds=1)) if latest else now


def append(path, event):
    with path.open("ab") as handle:
        handle.write((json.dumps(event) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def replace_text(path, content):
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


@contextmanager
def transaction(root):
    lock = root / ".writer-lock"
    root.mkdir(parents=True, exist_ok=True)
    with lock.open("ab") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if not (root / ".gitignore").exists():
            # Keep generated files out of collection even in a fresh checkout.
            replace_text(root / ".gitignore", "*\n")
        yield


def demote_after():
    value = config("cockpit.demote_after", "2")
    if not value.isascii() or not value.isdecimal() or int(value) < 1:
        raise Invalid("cockpit.demote_after must be a positive integer")
    return int(value)


def resolve(kind, logs):
    info = kind_info(kind)
    preferred = config(f"route.{kind}", info["default_role"])
    baseline = config(f"route.{kind}.baseline", info["default_baseline"])
    identifier(preferred, f"route.{kind}")
    identifier(baseline, f"route.{kind}.baseline")
    threshold = demote_after()

    # An adjudication is attributed to the role actually started on that attempt.
    decisions = []
    for run, events in logs.items():
        lanes, routes = {}, {}
        for event in events:
            data = event["data"]
            lane = event["lane"]
            if event["type"] in ("lane-added", "brief-registered"):
                lanes[lane] = data["kind"]
            elif event["type"] == "attempt-started":
                routes[lane, data["attempt"]] = (lanes[lane], data["role"])
            elif event["type"] == "route-reset" and data["kind"] == kind:
                decisions.append((event_time(event), run, event["seq"], "reset", threshold))
            elif event["type"] in ("adjudicated", "attempt-collected", "abandoned"):
                verdict = data.get("verdict")
                if verdict and routes.get((lane, data["attempt"])) == (kind, preferred):
                    decisions.append((event_time(event), run, event["seq"], verdict, data.get("demote_after", threshold)))

    misses = 0
    demoted = False
    for _, _, _, verdict, limit in sorted(decisions):
        if verdict == "reset":
            misses, demoted = 0, False
        elif verdict == "hit":
            misses = 0
        elif verdict == "miss":
            misses += 1
            demoted |= misses >= limit

    role = baseline if demoted else preferred
    why = "demoted" if demoted else "baseline" if preferred == baseline else "preferred"
    command = config(f"role.{role}")
    return {"kind": kind, "role": role, "command": command or None, "why": why if command else "unset",
            "demoted": demoted, "read_only": info["read_only"] == "true"}
