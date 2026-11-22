#!/usr/bin/env python3
"""Record cockpit lane events and apply their guard rules."""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

from cockpit import (
    ROUTE_LOG, Invalid, answer, append, demote_after, git, git_path, history, kind_info, new_event,
    next_timestamp, nonempty, parser, positive_int, read_events, resolve, run_cli, run_directory,
    run_root, store_name, subcommand, transaction,
)
from cockpit_brief import brief_path, one_line, problems, read_spec, render
from cockpit_state import outside_range, reconcile, replay, rows, sync_view, tsv


def hold(args, reasons, *, context="", **data):
    message = "hold: " + "; ".join(f"{code}: {detail}" for code, detail in reasons.items())
    return answer(args, "hold", {**data, "reasons": reasons}, codes=reasons, status=1, message=message + context)


def revision(repo, ref):
    return git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode("ascii").strip()


def checkout_for(repo, worktree):
    repo = Path(repo or Path.cwd())
    directory = git_path(worktree or repo, "--show-toplevel")
    common_args = ("--path-format=absolute", "--git-common-dir")
    if not git_path(repo, *common_args).samefile(git_path(directory, *common_args)):
        raise Invalid("the lane worktree must belong to this repository")
    return directory


def require_ancestor(directory, base, head):
    ancestor = git(directory, "merge-base", base, head, allowed=(0, 1)).decode("ascii").strip()
    if ancestor != base:
        raise Invalid(f"base {base} is not an ancestor of HEAD {head}")


def paths_from(output):
    return {os.fsdecode(path) for path in output.split(b"\0") if path}


def inventory(directory, store):
    # Without exclusion options, Git includes ignored entries in the untracked listing.
    paths = paths_from(git(directory, "ls-files", "--others", "-z", "--"))
    if store != directory and store.is_relative_to(directory):
        relative = store.relative_to(directory).as_posix()
        return {path for path in paths if path != relative and not path.startswith(relative + "/")}
    return paths


def collected(repo, lane, store):
    attempt = lane.current
    directory = checkout_for(repo, Path(attempt.worktree))
    head = revision(directory, "HEAD")
    require_ancestor(directory, attempt.base, head)
    diff = ("diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--ignore-submodules=none")
    tracked = git(directory, *diff, "--") + git(directory, *diff, "--cached", "--")
    untracked = inventory(directory, store).symmetric_difference(attempt.inventory)
    changed = git(directory, *diff, f"{attempt.base}..{head}", "--")
    paths = sorted(paths_from(changed + tracked) | untracked)
    if revision(directory, "HEAD") != head:
        raise Invalid("the lane worktree head moved during collection")
    data = {"attempt": len(lane.attempts), "head": head, "changed_paths": paths, "report": lane.report,
            "uncommitted": bool(tracked or untracked)}
    if outside := outside_range(paths, lane.allow_paths):
        # The scope violation and its single route miss are the same durable write.
        data.update(verdict="miss", reason="out-of-range", demote_after=demote_after(), outside_paths=outside)
    return data


def active_locks(states):
    locks = {}
    for run, (lanes, _) in states.items():
        for lane in lanes.values():
            if lane.state in ("running", "collected"):
                for name in lane.locks:
                    locks[name] = (run, lane.name)
    return locks


def sync_locks(root, states):
    # Directory locks are a projection. Replaying before a start also catches an interrupted write
    # that committed its event before creating the directory.
    directory = root / "locks"
    directory.mkdir(exist_ok=True)
    active = active_locks(states)
    declared = {name for lanes, _ in states.values() for lane in lanes.values() for name in lane.locks}
    for name in sorted(declared):
        path = directory / name
        if name in active:
            path.mkdir(exist_ok=True)
        elif path.is_dir():
            path.rmdir()


def apply(args, logs, states, lanes, works, directory):
    action = args.action
    name = args.lane
    if action == "add":
        work_id = one_line(args.work, "work")
        previous = lanes.get(name)
        if previous and (args.rev is None or previous.work != work_id or previous.state not in ("ready", "reviewed")):
            raise Invalid("a brief revision needs a new --rev, the same work, and no active or closed attempt")
        spec = read_spec(args.spec)
        brief = brief_path(directory, name, args.rev)
        if any(event["type"] in ("lane-added", "brief-registered") and event["data"]["brief"] == str(brief)
               for event in logs[directory.name]):
            raise Invalid("brief revision already registered")
        brief_text = render(name, spec)
        if not brief.is_file() or brief.read_bytes() != brief_text.encode("utf-8"):
            raise Invalid("generate the lane brief from this spec before adding the lane")
        data = {"kind": spec["kind"], "brief": str(brief), "allow_paths": spec["allow_paths"],
                "acceptance": [item["id"] for item in spec["acceptance"]], "locks": spec["locks"],
                "report": spec["report_path"], "brief_digest": sha256(brief_text.encode("utf-8")).hexdigest()}
        if args.rev is not None:
            data["rev"] = args.rev
        return "brief-registered" if previous else "lane-added", work_id, data

    if name not in lanes:
        raise Invalid(f"unknown lane: {name}")
    lane = lanes[name]
    attempt_number = len(lane.attempts)
    attempt = lane.current
    if action in ("observe", "adjudicate", "abandon"):
        stale = (not attempt or args.attempt != attempt_number or attempt.abandoned or lane.brief_seq > attempt.seq)
        if not stale and action != "abandon" and attempt.head:
            stale = args.head not in (None, attempt.head)
            if not stale:
                worktree = checkout_for(args.repo, Path(attempt.worktree))
                stale = revision(worktree, "HEAD") != attempt.head
        if stale:
            return hold(args, {"stale-attempt": "use the latest attempt and its collected head"},
                        attempt=attempt_number, head=attempt.head if attempt else None)
    if lane.closed:
        raise Invalid(f"lane is closed: {name}")
    work = works[lane.work]
    reasons = work.reasons()
    if action in ("start", "close") and reasons:
        return hold(args, reasons)
    if action == "start":
        if lane.state not in ("ready", "reviewed"):
            raise Invalid("finish the current attempt before starting another")
        brief_bytes = Path(lane.brief).read_bytes()
        if lane.brief_digest and sha256(brief_bytes).hexdigest() != lane.brief_digest:
            return hold(args, {"stale-brief": "regenerate the brief from the registered spec"})
        issues = problems(brief_bytes.decode("utf-8"))
        if issues:
            return hold(args, {"invalid-brief": "; ".join(issues)})
        occupied = active_locks(states)
        conflicts = [f"{lock} ({'/'.join(occupied[lock])})" for lock in lane.locks if lock in occupied]
        if conflicts:
            return hold(args, {"resource-busy": ", ".join(conflicts)})
        route = resolve(lane.kind, logs)
        worktree = checkout_for(args.repo, args.worktree)
        head = revision(worktree, "HEAD")
        base = revision(worktree, args.base) if args.base else attempt.base if attempt else head
        if attempt and base != attempt.base:
            raise Invalid("a retry must keep the lane's original base")
        require_ancestor(worktree, base, head)
        data = {
            "attempt": attempt_number + 1, "role": route["role"], "command": route["command"],
            "worktree": str(worktree), "base": base, "inventory": sorted(inventory(worktree, directory.parent.parent)),
        }
        if work.last_resume:
            data["resume"] = work.last_resume
        return "attempt-started", lane.work, data
    if action == "collect":
        if lane.state != "running":
            raise Invalid("collect requires a running attempt")
        return "attempt-collected", lane.work, collected(args.repo, lane, directory.parent.parent)
    if action == "abandon":
        if lane.state not in ("running", "collected"):
            raise Invalid("abandon requires a running or collected attempt")
        data = {"attempt": attempt_number, "verdict": "miss" if args.miss else "inconclusive",
                "reason": nonempty(args.reason, "reason"), "demote_after": demote_after()}
        return "abandoned", lane.work, data
    if action == "resume":
        fields = {key: (getattr(args, key) or "").strip() for key in ("diagnosis", "hypothesis", "test")}
        if not reasons:
            raise Invalid("resume requires a held lane")
        if any(not value or value == work.last_resume.get(key) for key, value in fields.items()):
            return hold(args, {"stale-brief": "give a new diagnosis, hypothesis and distinguishing test"})
        if work.unclassified:
            return hold(args, {"unclassified": reasons["unclassified"]})
        return "resumed", lane.work, fields
    if not attempt or not attempt.head or attempt.abandoned:
        raise Invalid(f"{action} requires a collected attempt")
    if action == "observe":
        if args.ac not in lane.acceptance:
            raise Invalid(f"unknown acceptance item: {args.ac}")
        data = {"attempt": attempt_number, "head": attempt.head, "ac": args.ac, "result": args.result}
        if args.cause is not None:
            data["cause"] = nonempty(args.cause, "cause")
        return "observed", lane.work, data
    if action == "adjudicate":
        if attempt.verdict:
            raise Invalid(f"attempt already adjudicated: {attempt.verdict}")
        return "adjudicated", lane.work, {"attempt": attempt_number, "head": attempt.head, "verdict": args.verdict,
                                         "reason": nonempty(args.reason, "reason"), "demote_after": demote_after()}
    if lane.brief_seq > attempt.seq:
        return hold(args, {"stale-brief": "start an attempt with the current brief revision"})
    if attempt.outside:
        return hold(args, {"out-of-range": "the collected attempt exceeded its registered range"})
    missing = [ac for ac in lane.acceptance if attempt.observations.get(ac) != "pass"]
    if missing:
        return hold(args, {"acceptance-incomplete": "missing passes on the collected head: " + ", ".join(missing)},
                    missing=missing)
    if attempt.uncommitted:
        return hold(args, {"uncommitted-edits": "collection found uncommitted paths"})
    if not attempt.verdict:
        raise Invalid("close requires an adjudicated attempt")
    if args.head is not None and args.head != attempt.head:
        raise Invalid("closing head must match the collected commit")
    return "closed", lane.work, {"head": attempt.head}


def event_answer(args, event, events):
    event_type, name, data = (event[key] for key in ("type", "lane", "data"))
    message = f"{event_type}: {name}"
    if event_type == "attempt-collected":
        context = f' (attempt {data["attempt"]}, head {data["head"]})'
        if data.get("verdict") == "miss":
            outside = data.get("outside_paths")
            if outside is None:
                lanes, _ = replay(events[:event["seq"] - 1])
                outside = outside_range(data["changed_paths"], lanes[name].allow_paths)
            return hold(args, {"out-of-range": "paths outside the brief: " + ", ".join(outside)},
                        context=context, event=event)
        message += context
    elif event_type == "attempt-started":
        message += f' (attempt {data["attempt"]}, {data["role"]}): {data["command"] or "main session does it"}'
    elif event_type == "route-reset":
        message = f'route reset: {data["kind"]}'
    return answer(args, "ok", event, message=message)


def write(args, root):
    action = args.action
    reset = action == "route-reset"
    directory = None if reset else run_directory(root, args.run)
    if getattr(args, "event_id", None) is not None:
        args.event_id = nonempty(args.event_id, "event id")
    with transaction(root, write=True):
        logs = history(root)
        states = reconcile(root, logs)
        sync_locks(root, states)
        if reset:
            log = logs.get(ROUTE_LOG, [])
            if existing := next((event for event in log if event["event_id"] == args.event_id), None):
                return event_answer(args, existing, log)
            event = new_event(log, next_timestamp(logs), "route-reset", "", "", {"kind": args.kind}, args.event_id)
            append(root / ROUTE_LOG, event)
            return event_answer(args, event, log)

        if action == "init":
            directory.mkdir(exist_ok=True)
            (directory / "briefs").mkdir(exist_ok=True)
            (directory / "events.jsonl").touch(exist_ok=True)
            if args.run not in states:
                sync_view(directory, {}, {})
            return answer(args, "ok", {"run": args.run, "path": str(directory)}, message=str(directory))

        if args.run not in states:
            raise Invalid(f"run is not initialized: {args.run}")
        events = logs[args.run]
        lanes, works = states[args.run]
        if existing := next((event for event in events if event["event_id"] == args.event_id), None):
            return event_answer(args, existing, events)
        result = apply(args, logs, states, lanes, works, directory)
        if isinstance(result, int):
            return result
        event_type, work, data = result
        event = new_event(events, next_timestamp(logs), event_type, args.lane, work, data, args.event_id)
        states[args.run] = replay([*events, event])
        append(directory / "events.jsonl", event)
        sync_view(directory, *states[args.run])
        sync_locks(root, states)
        return event_answer(args, event, events)


def main(args):
    if args.action == "route-reset":
        kind_info(args.kind)
    else:
        args.run = run_directory(Path(), args.run).name
    if hasattr(args, "lane"):
        args.lane = store_name(args.lane, "lane")
    if getattr(args, "rev", None) is not None:
        args.rev = store_name(args.rev, "rev")
    if hasattr(args, "attempt"):
        positive_int(args.attempt, "attempt")
    root = run_root(args.repo)
    if args.action not in ("guard", "status"):
        return write(args, root)
    directory = run_directory(root, args.run)
    with transaction(root) as locked:
        if not locked or not (directory / "events.jsonl").is_file():
            raise Invalid(f"run is not initialized: {args.run}")
        if args.action == "status":
            lanes, works = reconcile(root, history(root))[args.run]
        else:
            lanes, works = replay(read_events(directory / "events.jsonl"))
    if args.action == "status":
        view = rows(lanes, works)
        return answer(args, "ok", {"lanes": view}, message=tsv(view).rstrip("\n"))
    if args.lane not in lanes:
        raise Invalid(f"unknown lane: {args.lane}")
    lane = lanes[args.lane]
    if lane.closed:
        return hold(args, {"closed": "the lane is closed"})
    reasons = works[lane.work].reasons()
    return hold(args, reasons) if reasons else answer(args, "allow")


def command_line():
    cli = parser("plumb-lane", __doc__)
    commands = cli.add_subparsers(dest="action", required=True)
    command_help = {
        "init": "Initialize a run", "add": "Add a lane from its brief specification",
        "start": "Apply the guard and record the next attempt", "collect": "Collect the current worktree head and paths",
        "observe": "Record one acceptance result", "adjudicate": "Record a route verdict",
        "abandon": "End an unfinished attempt and release its resource locks",
        "guard": "Read the work's current hold reasons", "resume": "Resume with a new diagnosis, hypothesis and test",
        "close": "Close a lane whose acceptance items passed", "status": "Print the derived lane table",
        "route-reset": "Clear the repository's route demotion for a kind",
    }
    options = {name: subcommand(commands, name, help_text) for name, help_text in command_help.items()}
    for name, command in options.items():
        if name != "route-reset":
            command.add_argument("--run", required=True)
        if name not in ("init", "status", "route-reset"):
            command.add_argument("--lane", required=True)
        if name not in ("init", "guard", "status"):
            command.add_argument("--event-id", help="idempotency key for this event (default: generated)")
    options["add"].add_argument("--work", required=True, help="stable work identifier, shared by lanes on the same work")
    options["add"].add_argument("--spec", required=True, type=Path)
    options["add"].add_argument("--rev", help="brief revision to register")
    options["start"].add_argument("--worktree", type=Path, help="lane worktree (default: repository checkout)")
    options["start"].add_argument("--base", help="starting revision (default: HEAD on first start, then the original base)")
    options["observe"].add_argument("--ac", required=True, help="acceptance item identifier")
    options["observe"].add_argument("--result", choices=("pass", "fail"), required=True)
    options["observe"].add_argument("--cause", help="stable cause identifier for a failed observation")
    options["adjudicate"].add_argument("--verdict", choices=("hit", "miss", "inconclusive"), required=True)
    options["adjudicate"].add_argument("--reason", required=True)
    for action in ("observe", "adjudicate", "abandon"):
        options[action].add_argument("--attempt", type=int, required=True, help="attempt number from start or collect")
    for action in ("observe", "adjudicate"):
        options[action].add_argument("--head", help="commit checked, from collect")
    options["abandon"].add_argument("--reason", required=True)
    options["abandon"].add_argument("--miss", action="store_true", help="count this abandonment as a route miss")
    options["resume"].add_argument("--diagnosis")
    options["resume"].add_argument("--hypothesis")
    options["resume"].add_argument("--test", help="distinguishing test")
    options["close"].add_argument("--head", help="require this collected commit")
    options["route-reset"].add_argument("kind")
    return cli


if __name__ == "__main__":
    raise SystemExit(run_cli(command_line(), main))
