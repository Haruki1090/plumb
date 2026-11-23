#!/usr/bin/env python3
"""plumb-sidecar-agents-check: say which Codex agent files are stale against the agents/*.md they condense.

    plumb-sidecar-agents-check [--root DIR] [--update]

Every `.codex/agents/*.toml` starts with one comment line naming its source and the hash of that source:

    # source: agents/<name>.md sha256:<hex of the file's bytes>
    # source: none                      (the file has no source in agents/)

The toml text is a deliberate condensation of the source, so nothing here regenerates it. The check only
notices that the source changed after the condensation was last read. Prints one line per file as
`state<TAB>toml<TAB>source`:

  ok              the hash on the first line is the hash of the source now
  stale           the source exists and its hash differs; re-read it, bring the toml up to date, run --update
  no-source-line  the first line is missing or not one of the two forms above
  missing-source  the first line names an agents/ file that does not exist
  none            the first line declares `# source: none`
  unmapped        an agents/*.md that no toml names (the toml column is `-`)

Exit status: 0 when every file is ok or none and nothing is unmapped, 1 otherwise, 2 on a usage error.

`--update` rewrites only the first line of each stale file to the current hash and prints each file it
updated. It is the human's statement that the source was re-read; it never touches a file whose first line
is malformed. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

HEADER = re.compile(r"^# source: (?:(none)|(agents/[A-Za-z0-9._-]+\.md) sha256:([0-9a-f]{64}))$")
HINT = "  re-read the source, bring the condensed instructions up to date, then run with --update"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(toml: Path, root: Path) -> tuple[str, str]:
    """Return (state, source) for one toml; source is "-" when the file names none."""
    first = toml.read_bytes().split(b"\n", 1)[0].decode("utf-8", "replace")
    found = HEADER.match(first)
    if not found:
        return "no-source-line", "-"
    if found.group(1):
        return "none", "-"
    source = found.group(2)
    target = root / source
    if not target.is_file():
        return "missing-source", source
    return ("ok" if sha256(target) == found.group(3) else "stale"), source


def rewrite_first_line(toml: Path, source: str, digest: str) -> None:
    data = toml.read_bytes()
    _, newline, rest = data.partition(b"\n")
    toml.write_bytes(f"# source: {source} sha256:{digest}".encode() + newline + rest)


def main(argv: list[str]) -> int:
    default_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(prog="plumb-sidecar-agents-check", description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=default_root, help="repository root (default: this checkout)")
    parser.add_argument("--update", action="store_true", help="rewrite the first line of each stale file to the current hash")
    args = parser.parse_args(argv)
    root = args.root
    agents_dir = root / ".codex" / "agents"
    if not agents_dir.is_dir():
        print(f"plumb-sidecar-agents-check: not a directory: {agents_dir}", file=sys.stderr)
        return 2

    bad = False
    named: set[str] = set()
    for toml in sorted(agents_dir.glob("*.toml")):
        state, source = classify(toml, root)
        label = toml.relative_to(root).as_posix()
        if source != "-":
            named.add(source)
        if state == "stale" and args.update:
            rewrite_first_line(toml, source, sha256(root / source))
            print(f"updated\t{label}\t{source}")
            continue
        print(f"{state}\t{label}\t{source}")
        if state == "stale":
            print(HINT)
        if state not in ("ok", "none"):
            bad = True
    for source in sorted((root / "agents").glob("*.md")):
        label = source.relative_to(root).as_posix()
        if label not in named:
            print(f"unmapped\t-\t{label}")
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
