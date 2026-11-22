#!/usr/bin/env python3
"""Generate or check a cockpit lane brief."""

from pathlib import Path

from cockpit import Invalid, answer, identifier, parser, replace_text, run_cli, run_directory, run_root, subcommand
from cockpit_brief import problems, read_spec, render


def main(args):
    if args.action == "check":
        issues = problems(args.brief.read_text(encoding="utf-8"))
        if issues:
            return answer(args, "hold", {"issues": issues}, codes=["invalid-brief"], status=1,
                          message="\n".join(issues))
        return answer(args, "ok", message="brief is complete")

    lane = identifier(args.lane, "lane")
    brief = render(lane, read_spec(args.spec))
    if issues := problems(brief):
        raise Invalid("; ".join(issues))
    directory = run_directory(run_root(args.repo), args.run)
    if not (directory / "events.jsonl").is_file():
        raise Invalid("run is not initialized")
    path = directory / "briefs" / f"{lane}.md"
    path.parent.mkdir(exist_ok=True)
    replace_text(path, brief)
    return answer(args, "ok", {"path": str(path)}, message=str(path))


if __name__ == "__main__":
    cli = parser("plumb-brief", __doc__)
    commands = cli.add_subparsers(dest="action", required=True)
    new = subcommand(commands, "new", "Generate a brief from a JSON specification")
    new.add_argument("--run", required=True)
    new.add_argument("--lane", required=True)
    new.add_argument("--spec", type=Path, required=True)
    subcommand(commands, "check", "Check the sections, acceptance commands and report path",
               repo=False).add_argument("brief", type=Path)
    raise SystemExit(run_cli(cli, main))
