#!/usr/bin/env python3
"""The work ledger and cost per task.

    plumb-ledger changes ...   one record per landed change (scripts/ledger_changes.py)
    plumb-ledger rework  ...   the rework rate over a period (scripts/ledger_changes.py)
    plumb-ledger capture ...   per-request records from transcripts (scripts/ledger_cost.py)
    plumb-ledger export  ...   push captured records to the owner's store (scripts/ledger_cost.py)
    plumb-ledger prs     ...   pull requests by head ref, for task assignment (scripts/ledger_cost.py)
    plumb-ledger report  ...   the weekly report (scripts/ledger_cost.py)

This file only dispatches. Each module owns its subcommands, options and help.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CHANGES = {"changes", "rework"}
COST = {"capture", "export", "prs", "report"}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    if argv[0] in CHANGES:
        import ledger_changes
        return ledger_changes.main(argv)
    if argv[0] in COST:
        import ledger_cost
        return ledger_cost.main(argv)
    print(f"plumb-ledger: unknown subcommand: {argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
