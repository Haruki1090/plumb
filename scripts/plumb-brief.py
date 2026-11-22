#!/usr/bin/env python3
"""Generate or check a cockpit lane brief."""

from hashlib import sha256
from pathlib import Path

from cockpit import (
    Invalid, answer, history, parser, replace_text, run_cli, run_directory, run_root, store_name, subcommand,
    transaction,
)
from cockpit_brief import brief_path, problems, read_spec, render, worker_instruction
from cockpit_state import reconcile


def main(args):
    if args.action == "check":
        issues = problems(args.brief.read_text(encoding="utf-8"))
        if issues:
            return answer(args, "hold", {"issues": issues}, codes=["invalid-brief"], status=1,
                          message="\n".join(issues))
        return answer(args, "ok", message="brief is complete")

    lane = store_name(args.lane, "lane")
    rev = store_name(args.rev, "rev") if args.rev is not None else None
    root = run_root(args.repo)
    directory = run_directory(root, args.run)
    path = brief_path(directory, lane, rev)
    with transaction(root, write=True):
        logs = history(root)
        states = reconcile(root, logs)
        if directory.name not in states:
            raise Invalid("run is not initialized")
        if args.action == "refresh":
            current = states[directory.name][0].get(lane)
            if not current:
                raise Invalid(f"unknown lane: {lane}")
            original = Path(current.brief).read_bytes()
            if sha256(original).hexdigest() != current.brief_digest:
                raise Invalid("the registered brief digest does not match")
            _, separator, body = original.decode("utf-8").partition("\n")
            brief = worker_instruction() + separator + body
        else:
            brief = render(lane, read_spec(args.spec))
        if issues := problems(brief):
            raise Invalid("; ".join(issues))
        registered = next((event["data"] for event in logs[directory.name]
                           if event["type"] in ("lane-added", "brief-registered")
                           and event["data"]["brief"] == str(path)), None)
        if registered and sha256(brief.encode("utf-8")).hexdigest() != registered["brief_digest"]:
            raise Invalid("registered brief is immutable; choose a new --rev and add it")
        if not path.is_file() or path.read_bytes() != brief.encode("utf-8"):
            if registered:
                raise Invalid("the registered brief is missing or its digest does not match")
            path.parent.mkdir(exist_ok=True)
            replace_text(path, brief)
    return answer(args, "ok", {"path": str(path)}, message=str(path))


if __name__ == "__main__":
    cli = parser("plumb-brief", __doc__)
    commands = cli.add_subparsers(dest="action", required=True)
    new = subcommand(commands, "new", "Generate a brief from a JSON specification")
    refresh = subcommand(commands, "refresh", "Generate a new revision of a registered brief after a plugin move")
    for command in (new, refresh):
        command.add_argument("--run", required=True)
        command.add_argument("--lane", required=True)
        command.add_argument("--rev", required=command is refresh)
    new.add_argument("--spec", type=Path, required=True)
    subcommand(commands, "check", "Check the sections, acceptance commands and report path",
               repo=False).add_argument("brief", type=Path)
    raise SystemExit(run_cli(cli, main))
