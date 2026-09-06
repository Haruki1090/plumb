#!/usr/bin/env python3
"""Print the session's running cost as one status-line segment.

Reads the status-line JSON the runtime pipes on stdin and prints `$<usd>`, the runtime's own
list-price estimate (`cost.total_cost_usd`). Two optional keys in the plumb config add to it:

    cost.jpy_per_usd        = 150    -> appends ¥<jpy>
    cost.session_budget_usd = 30     -> appends <pct>% of budget, coloured by band

Bands: under 50 % plain, 50-79 % yellow, 80-99 % magenta, 100 % and over bold red. The bands are
the 50 / 80 / 100 nudge points; the budget is the owner's expected spend for one session, not a
limit the runtime enforces. No cost in the JSON means no output and exit 0, so a status line that
appends this segment loses nothing when the field is absent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "plumb-config.sh"


def config(key: str) -> str:
    try:
        return subprocess.run(["bash", str(CONFIG), key], capture_output=True, text=True,
                              timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def number(text: str) -> float | None:
    try:
        return float(text) if text else None
    except ValueError:
        return None


def band(percent: float) -> str:
    if percent >= 100:
        return "1;31"
    if percent >= 80:
        return "35"
    if percent >= 50:
        return "33"
    return ""


def segment(data: object) -> str:
    cost = data.get("cost") if isinstance(data, dict) else None
    usd = cost.get("total_cost_usd") if isinstance(cost, dict) else None
    if not isinstance(usd, (int, float)) or isinstance(usd, bool):
        return ""
    parts = [f"${usd:.2f}"]
    rate = number(config("cost.jpy_per_usd"))
    if rate:
        parts.append(f"¥{round(usd * rate):,}")
    budget = number(config("cost.session_budget_usd"))
    if budget:
        percent = usd / budget * 100
        colour = band(percent)
        text = f"{percent:.0f}%"
        parts.append(f"\033[{colour}m{text}\033[0m" if colour else text)
    return " ".join(parts)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    out = segment(data)
    if out:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
