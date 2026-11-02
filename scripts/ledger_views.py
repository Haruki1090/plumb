"""Views of the ledger: time, cost and model per task, as tables in a directory.

    plumb-ledger views --since <day> --until <day> --out <dir> [--changes <jsonl>]... [--prs <json>]...
                       [--gap-minutes 30] [--repo <owner/name>] [--timezone <tz>]

Reads what `plumb-ledger report` reads (local records and the store's refs) and writes, under
--out only, README.md, tasks.md/.csv, days.md/.csv, models.md/.csv and sessions.csv. The Markdown
tables are for reading on GitHub (the 50 costliest rows); the CSV files hold every row. The same
records give the same bytes. Nothing is pushed: publishing is the caller's job.

Active time is measured per session, not per request. The requests of one session (the main
transcript and its subagents together) sorted by time form a timeline. Two consecutive requests at
most `gap` apart are one stretch of work: the interval between them is active and is credited to the
task of the later request. A longer gap is idle and counts nowhere; the first request of a stretch
adds nothing. Parallel sessions on one task each add their own time (it is effort, not calendar
time); the span (first to last request of the task) is shown beside it.

Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from ledger_cost import (LedgerError, TOKEN_FIELDS, add_source_arguments, canonical_repositories, contract_timezone,
                         day_range, format_time,
                         gather, load_prices, load_prs, money, parse_day, parse_time, place_request, price_request,
                         repo_key,
                         scope_period, session_map, zone_for)

DEFAULT_GAP_MINUTES = 30
TOP_ROWS = 50
FAMILIES = ("fable", "mythos", "opus", "sonnet", "haiku", "other")
GENERATED = ("README.md", "tasks.md", "tasks.csv", "days.md", "days.csv", "models.md", "models.csv", "sessions.csv")
STATE_ORDER = {"pull_request": 0, "branch": 1, "no_pull_request": 2, "ambiguous": 3, "unknown_attribution": 4}
STATE_LABEL = {"pull_request": "", "branch": "", "no_pull_request": "none", "ambiguous": "ambiguous",
               "unknown_attribution": "unknown"}
ZERO = Decimal(0)
MICRO = timedelta(microseconds=1)


# ---------------------------------------------------------------- active time

def active_credits(records: list[dict[str, Any]], gap: timedelta) -> list[timedelta]:
    """Per record (same positions as `records`), the interval it ends: the time since the previous
    request of its session when that is at most `gap`, else nothing. A record without a time
    is outside every timeline and gets nothing. Sessions are (runtime, session); the main transcript
    and its subagents share one, so requests in parallel do not count twice."""
    timelines: dict[tuple[str, str], list[tuple[datetime, int]]] = {}
    for index, record in enumerate(records):
        moment = parse_time(record["time"])
        if moment is not None:
            timelines.setdefault((record["runtime"], record["session"]), []).append((moment, index))
    credits = [timedelta(0)] * len(records)
    for rows in timelines.values():
        rows.sort()
        for (before, _), (after, index) in zip(rows, rows[1:]):
            if after - before <= gap:
                credits[index] = after - before
    return credits


# ---------------------------------------------------------------- formatting

def family_of(model: str | None) -> str:
    low = (model or "").lower()
    return next((name for name in FAMILIES[:-1] if name in low), "other")


def minutes_text(span: timedelta) -> str:
    """Minutes with one decimal, for CSV."""
    value = Decimal(span // MICRO) / Decimal(60_000_000)
    return format(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f")


def duration_text(span: timedelta) -> str:
    """Whole minutes for reading: 35m, 2h 05m, 3d 4h."""
    minutes = (span // MICRO + 30_000_000) // 60_000_000
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def fixed(value: Decimal | None) -> str:
    """Money for CSV: six decimals, no sign of rounding beyond that, empty when unknown."""
    if value is None:
        return ""
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")


def percent(part: Decimal, whole: Decimal) -> str:
    if not whole:
        return "n/a"
    return f"{(part / whole * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def md_cell(value: Any) -> str:
    """A table cell: a backslash and `|` are escaped and a line break becomes <br>, so that a value
    never ends the cell or the row."""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def md_table(headers: list[str], rows: list[list[Any]], right: set[int] | None = None) -> list[str]:
    right = right or set()
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---:" if i in right else "---" for i in range(len(headers))) + "|"]
    out += ["| " + " | ".join(md_cell(cell) for cell in row) + " |" for row in rows]
    return out


def csv_text(headers: list[str], rows: list[list[Any]]) -> str:
    """RFC 4180: comma-separated, CRLF, a field with a comma, quote or line break is quoted."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


# ---------------------------------------------------------------- accumulation

class Acc:
    """The sums of one row of a table."""

    def __init__(self) -> None:
        self.requests = 0
        self.unknown_cost = 0
        self.cost = ZERO
        self.family: dict[str, Decimal] = {}
        self.main = ZERO
        self.sub = ZERO
        self.active = timedelta(0)
        self.first: datetime | None = None
        self.last: datetime | None = None
        self.sessions: set[tuple[str, str]] = set()
        self.attribution: Counter[str] = Counter()
        self.heads: set[str] = set()
        self.repositories: set[str] = set()
        self.branches: set[str] = set()
        self.remotes: set[str] = set()
        self.pulls: set[str] = set()
        self.tokens: Counter[str] = Counter()

    def add(self, record: dict[str, Any], moment: datetime, amount: Decimal | None, active: timedelta) -> None:
        self.requests += 1
        self.active += active
        self.first = moment if self.first is None else min(self.first, moment)
        self.last = moment if self.last is None else max(self.last, moment)
        self.sessions.add((record["runtime"], record["session"]))
        if amount is None:
            self.unknown_cost += 1
        else:
            self.cost += amount
            name = family_of(record["model"])
            self.family[name] = self.family.get(name, ZERO) + amount
            if record["role"] == "main":
                self.main += amount
            else:
                self.sub += amount
        for key in TOKEN_FIELDS:
            if record[key] is not None:
                self.tokens[key] += record[key]

    @property
    def unpriced(self) -> bool:
        """Every request of the row has a cost that cannot be known: the row has no cost to show,
        which is not the same as a cost of zero."""
        return self.requests > 0 and self.unknown_cost == self.requests

    @property
    def span(self) -> timedelta:
        return (self.last - self.first) if self.first and self.last else timedelta(0)


def task_key(placed: Any, repository: str | None) -> tuple[str, str, str, int]:
    """(state, repository, head ref, pull request number) of where a request goes; `repository` is
    the spelling shown for the placed repository."""
    if placed.kind == "pr":
        return "pull_request", repository, "", placed.number
    if placed.kind == "branch":
        return "branch", repository, placed.branch, 0
    if placed.kind == "unknown":
        return "unknown_attribution", "", "", 0
    return ("ambiguous" if placed.kind == "ambiguous" else "no_pull_request"), repository, placed.branch, 0


def build(found: dict[str, Any], pulls: dict | None, sessions: Any, versions: list[dict[str, Any]], now: datetime,
          gap: timedelta, zone: Any, days: list[date]) -> dict[str, Any]:
    """Pure: the gathered records in, the rows of every table and the counts out."""
    merged = found["merged"]
    credits = active_credits(merged, gap)
    heads: dict[tuple[str, int], str] = {}
    for (repository, head), rows in (pulls or {}).items():
        for pull in rows:
            heads.setdefault((repo_key(repository), pull["number"]), head)

    tasks: dict[tuple[str, str, str, int], Acc] = {}
    models: dict[str, Acc] = {}
    per_day: dict[date, Acc] = {day: Acc() for day in days}
    per_session: dict[tuple[str, str], Acc] = {}
    counts: Counter[str] = Counter()
    total = Acc()
    placements = {index: place_request(merged[index], parse_time(merged[index]["time"]), pulls, now, sessions)
                  for index in found["in_period_index"]}
    spelling = canonical_repositories(placed.repository for placed in placements.values())
    for index in found["in_period_index"]:
        record = merged[index]
        moment = parse_time(record["time"])
        cost = price_request(record, versions)
        amount = sum(cost.values(), ZERO) if cost is not None else None
        placed = placements[index]
        repository = spelling.get(repo_key(placed.repository), placed.repository)
        key = task_key(placed, repository)
        counts["session_ambiguous"] += placed.session_ambiguous
        counts[key[0]] += 1
        counts["session_assigned"] += placed.via == "session"
        head = placed.head_ref or heads.get((repo_key(placed.repository), placed.number or 0))
        label = "session" if placed.via == "session" else record["attribution_source"]
        day = moment.astimezone(zone).date()
        session_key = (record["runtime"], record["session"])
        for acc in (total, tasks.setdefault(key, Acc()), models.setdefault(record["model"] or "unknown model", Acc()),
                    per_day.setdefault(day, Acc()), per_session.setdefault(session_key, Acc())):
            acc.add(record, moment, amount, credits[index])
        task = tasks[key]
        task.attribution[label] += 1
        if head and key[0] == "pull_request":
            task.heads.add(head)
        session = per_session[session_key]
        if record["remote_session"]:
            session.remotes.add(record["remote_session"])
        if record["repository"]:
            session.repositories.add(spelling.get(repo_key(record["repository"]), record["repository"]))
        if record["branch"]:
            session.branches.add(record["branch"])
        if key[0] == "pull_request":
            session.pulls.add(f"{repository}#{placed.number}")
    return {"total": total, "tasks": tasks, "models": models, "days": per_day, "sessions": per_session,
            "counts": counts}


# ---------------------------------------------------------------- tables

def pull_text(key: tuple[str, str, str, int]) -> str:
    return f"#{key[3]}" if key[0] == "pull_request" else STATE_LABEL[key[0]]


def family_cells(acc: Acc) -> list[str]:
    return [fixed(acc.family.get(name)) for name in FAMILIES]


def family_text(acc: Acc) -> str:
    parts = [(name, acc.family[name]) for name in FAMILIES if name in acc.family]
    return ", ".join(f"{name} {money(value)}" for name, value in sorted(parts, key=lambda p: (-p[1], p[0])))


def cost_text(acc: Acc, value: Decimal | None = None) -> str:
    """Markdown cost: `unpriced` when no request of the row has a price, else the sum of the priced
    ones and, when some are not, how many."""
    if acc.unpriced:
        return "unpriced"
    return money(acc.cost if value is None else value) + (f" (+{acc.unknown_cost} unpriced)" if acc.unknown_cost else "")


def cost_cell(acc: Acc, value: Decimal | None = None) -> str:
    """CSV cost: empty when no request of the row has a price."""
    return "" if acc.unpriced else fixed(acc.cost if value is None else value)


def task_order(item: tuple[tuple[str, str, str, int], Acc]) -> tuple:
    key, acc = item
    return (-acc.cost, STATE_ORDER[key[0]], key[1], key[2], key[3])


def attribution_text(acc: Acc) -> str:
    return " ".join(f"{name}:{count}" for name, count in sorted(acc.attribution.items()))


def tasks_tables(data: dict[str, Any]) -> tuple[list[str], list[list[Any]], list[str], list[list[Any]]]:
    ordered = sorted(data["tasks"].items(), key=task_order)
    csv_rows, md_rows = [], []
    for key, acc in ordered:
        head = key[2] or "; ".join(sorted(acc.heads))
        csv_rows.append([key[1], head, key[3] or "", key[0], attribution_text(acc), len(acc.sessions), acc.requests,
                         acc.unknown_cost, minutes_text(acc.active), minutes_text(acc.span), cost_cell(acc),
                         *family_cells(acc), cost_cell(acc, acc.main), cost_cell(acc, acc.sub),
                         format_time(acc.first), format_time(acc.last)])
        md_rows.append([key[1] or "-", head or "-", pull_text(key) or "-", attribution_text(acc), len(acc.sessions),
                        acc.requests, duration_text(acc.active), duration_text(acc.span), cost_text(acc),
                        family_text(acc) or "-",
                        "unpriced" if acc.unpriced else f"{money(acc.main)} / {money(acc.sub)}"])
    csv_headers = ["repository", "head_ref", "pull_request", "state", "attribution", "sessions", "requests",
                   "unknown_cost_requests", "active_minutes", "span_minutes", "cost_usd",
                   *[f"cost_{name}" for name in FAMILIES], "cost_main", "cost_subagent", "first_request", "last_request"]
    md_headers = ["Repository", "Head ref", "Pull request", "Attribution", "Sessions", "Requests", "Active", "Span",
                  "Cost", "By model family", "Main / subagent"]
    return csv_headers, csv_rows, md_headers, md_rows


def models_tables(data: dict[str, Any]) -> tuple[list[str], list[list[Any]], list[str], list[list[Any]]]:
    ordered = sorted(data["models"].items(), key=lambda item: (-item[1].cost, item[0]))
    whole = data["total"].cost
    csv_rows, md_rows = [], []
    for name, acc in ordered:
        share = fixed_share(acc.cost, whole)
        csv_rows.append([name, family_of(name), acc.requests, acc.unknown_cost, cost_cell(acc), "" if acc.unpriced else share,
                         *[acc.tokens[key] for key in TOKEN_FIELDS]])
        md_rows.append([name, acc.requests, cost_text(acc), "-" if acc.unpriced else percent(acc.cost, whole),
                        *[f"{acc.tokens[key]:,}" for key in TOKEN_FIELDS]])
    csv_headers = ["model", "family", "requests", "unknown_cost_requests", "cost_usd", "share", *TOKEN_FIELDS]
    md_headers = ["Model", "Requests", "Cost", "Share", "Input", "Output", "Cache read", "Cache write 5m", "Cache write 1h"]
    return csv_headers, csv_rows, md_headers, md_rows


def fixed_share(part: Decimal, whole: Decimal) -> str:
    return format((part / whole).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f") if whole else ""


def days_tables(data: dict[str, Any]) -> tuple[list[str], list[list[Any]], list[str], list[list[Any]]]:
    csv_rows, md_rows = [], []
    for day in sorted(data["days"]):
        acc = data["days"][day]
        csv_rows.append([day.isoformat(), acc.requests, acc.unknown_cost, minutes_text(acc.active), cost_cell(acc),
                         *family_cells(acc)])
        md_rows.append([day.isoformat(), acc.requests, duration_text(acc.active), cost_text(acc), family_text(acc) or "-"])
    csv_headers = ["date", "requests", "unknown_cost_requests", "active_minutes", "cost_usd",
                   *[f"cost_{name}" for name in FAMILIES]]
    md_headers = ["Day", "Requests", "Active", "Cost", "By model family"]
    return csv_headers, csv_rows, md_headers, md_rows


def sessions_csv(data: dict[str, Any]) -> str:
    rows = []
    for (runtime, session), acc in sorted(data["sessions"].items(), key=lambda item: (format_time(item[1].first), item[0])):
        rows.append([runtime, session, ";".join(sorted(acc.remotes)), ";".join(sorted(acc.repositories)),
                     ";".join(sorted(acc.branches)), format_time(acc.first), format_time(acc.last), acc.requests,
                     acc.unknown_cost, minutes_text(acc.active), cost_cell(acc), ";".join(sorted(acc.pulls))])
    return csv_text(["runtime", "session", "remote_session", "repositories", "branches", "first_request",
                     "last_request", "requests", "unknown_cost_requests", "active_minutes", "cost_usd",
                     "pull_requests"], rows)


def markdown_file(title: str, intro: list[str], headers: list[str], rows: list[list[Any]], csv_name: str,
                  right: set[int], keep_last: bool = False) -> str:
    """A table of at most TOP_ROWS rows (the first ones, or the last ones for rows in time order) and
    a line saying how many more the CSV holds."""
    shown = rows[-TOP_ROWS:] if keep_last else rows[:TOP_ROWS]
    rest = len(rows) - len(shown)
    if not rows:
        note = f"No rows. `{csv_name}` holds the same table."
    elif rest:
        note = f"{len(shown)} of {len(rows)} rows shown; {rest} more in `{csv_name}`."
    else:
        note = f"All {len(rows)} row{'' if len(rows) == 1 else 's'}; `{csv_name}` holds the same table."
    return "\n".join([f"# {title}", "", *intro, "", *md_table(headers, shown, right), "", note, ""])


def readme(data: dict[str, Any], found: dict[str, Any], args: Any, label: str, gap_minutes: int,
           pulls: dict | None, sessions: Any) -> str:
    total, counts = data["total"], data["counts"]
    unknown_cost = total.unknown_cost
    in_period = found["in_period"]
    ids = {record["id"] for record in in_period if record["id"]}
    scope = found["scope"]
    coverage = found["pending_records"] == 0 and found["store_status"] in ("unset", "ok")
    hours = (Decimal(total.active // MICRO) / Decimal(3_600_000_000)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if sessions is None:
        session_line = "skipped: no `--changes` given, so a request on the base branch or with an unknown branch stays unattributed."
    elif pulls is None:
        session_line = "skipped: `--changes` was given without `--prs`, so no branch is known to have no pull request."
    else:
        session_line = ("a request the branch rule leaves without a pull request goes to the one landed pull request "
                        "its cloud session produced; a session that produced several leaves it where it was.")
    lines = [
        "# Ledger views", "",
        f"Period {args.since} .. {args.until} (days in {label})"
        + (f", repository {scope['repository']} only" if scope else ", every repository") + ".",
        f"Active time: consecutive requests of one session at most {gap_minutes} minutes apart are one stretch of "
        f"work and the interval counts; a longer gap is idle and counts nowhere (`--gap-minutes`).",
        "Cost is list prices applied to recorded tokens. On a flat-rate plan it is not the bill; it compares tasks "
        "and models with each other. A request whose cost cannot be known is counted and never added as zero.", "",
        "## Totals", "",
        *md_table(["", ""], [
            ["Requests", f"{total.requests:,}"],
            ["Active time", f"{hours} h"],
            ["Cost", cost_text(total)],
            ["Requests with unknown cost (not in the cost)", f"{unknown_cost:,}"],
        ], {1}), "",
        "## Not attributed, not known", "",
        *md_table(["", "Requests"], [
            ["Unknown attribution (repository or branch unknown)", counts["unknown_attribution"]],
            ["Ambiguous (two open pull requests for the head ref)", counts["ambiguous"]],
            ["No pull request (the branch has none, or it is the base branch)", counts["no_pull_request"]],
            ["Moved to a pull request through their session", counts["session_assigned"]],
            ["Left in place: their session produced several pull requests", counts["session_ambiguous"]],
            ["Without an id", sum(1 for record in in_period if record["id"] is None)],
            ["With an id that has conflicting copies", len(found["conflicts"] & ids)],
            ["Without a time (in no table)", found["outside_time"]],
            *([["Left out: other repositories", scope["other_repositories"]],
               ["Left out: repository unknown", scope["unknown_repository"]]] if scope else []),
        ], {1}), "",
        f"Session attribution: {session_line}", "",
        "## Coverage", "",
        f"- {'Complete' if coverage else 'INCOMPLETE'}: {found['pending_records']:,} requests in "
        f"{found['pending_sessions']} session(s) are captured here but not exported yet.",
        f"- Store: {found['store_status']}"
        + ("" if found["store"] else " (`ledger.store` is unset; cloud sessions are not covered)") + ".", "",
        "## Tables", "",
        "- [tasks.md](tasks.md), [tasks.csv](tasks.csv): one row per task",
        "- [days.md](days.md), [days.csv](days.csv): one row per day",
        "- [models.md](models.md), [models.csv](models.csv): one row per model",
        "- [sessions.csv](sessions.csv): one row per session", ""]
    return "\n".join(lines)


def render(data: dict[str, Any], found: dict[str, Any], args: Any, label: str, gap_minutes: int, pulls: dict | None,
           sessions: Any) -> dict[str, str]:
    intro = [f"Period {args.since} .. {args.until} (days in {label}). Active time: gap {gap_minutes} minutes. "
             "Cost is list prices applied to recorded tokens; `unpriced` requests are counted, not added."]
    files = {"README.md": readme(data, found, args, label, gap_minutes, pulls, sessions)}
    csv_headers, csv_rows, md_headers, md_rows = tasks_tables(data)
    files["tasks.csv"] = csv_text(csv_headers, csv_rows)
    files["tasks.md"] = markdown_file("Tasks", intro + ["Sorted by cost."], md_headers, md_rows, "tasks.csv", {4, 5})
    csv_headers, csv_rows, md_headers, md_rows = days_tables(data)
    files["days.csv"] = csv_text(csv_headers, csv_rows)
    files["days.md"] = markdown_file("Days", intro + ["Oldest first."], md_headers, md_rows, "days.csv", {1}, keep_last=True)
    csv_headers, csv_rows, md_headers, md_rows = models_tables(data)
    files["models.csv"] = csv_text(csv_headers, csv_rows)
    files["models.md"] = markdown_file("Models", intro + ["Sorted by cost. Tokens are summed over the requests that report them."],
                                       md_headers, md_rows, "models.csv", {1, 3, 4, 5, 6, 7, 8})
    files["sessions.csv"] = sessions_csv(data)
    return files


# ---------------------------------------------------------------- command

def write_files(out: Path, files: dict[str, str]) -> None:
    """Replace the generated files under `out`, and only those: nothing else in it is touched, and
    nothing is written outside it (a file is written to a temporary name beside its target and
    renamed over it, so a link at the target is replaced, not followed)."""
    if out.exists() and not out.is_dir():
        raise LedgerError(f"--out is not a directory: {out}")
    try:
        out.mkdir(parents=True, exist_ok=True)
        for name in GENERATED:
            target = out / name
            temporary = out / f".{name}.{os.getpid()}.tmp"
            try:
                temporary.write_bytes(files[name].encode("utf-8"))
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()
    except OSError as error:
        raise LedgerError(f"cannot write under {out}: {type(error).__name__}") from error


def views_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plumb-ledger views",
        description="Write time, cost and model per task as Markdown and CSV tables under --out: README.md, "
                    "tasks, days and models (.md and .csv) and sessions.csv. Reads the local records and the "
                    "store like `report`. Writes nothing outside --out and never pushes.")
    add_source_arguments(parser)
    for action in parser._actions:   # views has its own default for the cache (below)
        if "--store-cache" in action.option_strings:
            action.help = ("the cache repository for the store's refs (default: a temporary directory, removed "
                           "when the command ends; nothing is written beside the local records)")
    parser.add_argument("--out", required=True, metavar="DIR", help="the directory the tables are written to (created if missing); only the generated files in it are replaced")
    parser.add_argument("--gap-minutes", type=int, default=DEFAULT_GAP_MINUTES, metavar="N",
                        help=f"two requests of one session at most this far apart are one stretch of work (default {DEFAULT_GAP_MINUTES})")
    return parser


def cmd_views(argv: list[str]) -> int:
    args = views_parser().parse_args(argv)
    if args.gap_minutes < 1:
        raise LedgerError("--gap-minutes must be at least 1")
    tz_name = args.timezone or contract_timezone()
    start, end, label = day_range(args.since, args.until, tz_name)
    zone, _ = zone_for(tz_name)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    versions = load_prices(Path(args.prices))
    with tempfile.TemporaryDirectory(prefix="plumb-ledger-views-") as scratch:
        # The store's refs are fetched into a cache repository. `report` keeps it beside the local
        # records; `views` writes only under --out, and a cache under --out would be committed with the
        # tables, so it lives in a scratch directory that is removed on exit, unless --store-cache names one.
        if not args.store_cache:
            args.store_cache = str(Path(scratch) / "store-cache.git")
        found = gather(args, start, end)
    pulls = load_prs(args.prs) if args.prs else None
    sessions = session_map(args.changes) if args.changes else None
    scope_period(found, args.repo, pulls, sessions, now)
    first, last = parse_day(args.since), parse_day(args.until)
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    data = build(found, pulls, sessions, versions, now, timedelta(minutes=args.gap_minutes), zone, days)
    files = render(data, found, args, label, args.gap_minutes, pulls, sessions)
    write_files(Path(args.out).expanduser(), files)
    print(f"views: {data['total'].requests} requests, {len(data['tasks'])} tasks, {len(files)} files -> {args.out}")
    return 0
