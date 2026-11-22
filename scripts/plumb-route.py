#!/usr/bin/env python3
"""Resolve a cockpit route from repository event history."""

from cockpit import answer, history, parser, resolve, run_cli, run_root, subcommand
from cockpit_state import validate_history


def main(args):
    root = run_root(args.repo)
    logs = history(root)
    validate_history(logs)
    route = resolve(args.kind, logs)
    launch = route["command"] or "main session does it"
    return answer(args, "ok", route, message=f'{route["role"]} ({route["why"]}): {launch}')


if __name__ == "__main__":
    cli = parser("plumb-route", __doc__)
    commands = cli.add_subparsers(required=True)
    subcommand(commands, "resolve", "Resolve the command for a work kind").add_argument("kind")
    raise SystemExit(run_cli(cli, main))
