#!/usr/bin/env python3
"""Measure context use in Claude Code transcripts without printing their contents."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class AuditInputError(Exception):
    """An invalid or unavailable transcript input."""


def integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if not isinstance(value, float) or not math.isfinite(value) or value < 0:
        return None
    return int(value)


def percentile(values: Iterable[int], fraction: float) -> int | None:
    ordered = sorted(values)
    if not ordered:
        return None
    # Nearest-rank percentile: rank = ceil(p * n), converted to a zero-based index.
    # Keeping this as an observed token count,
    # rather than interpolating two requests, makes every number traceable to one real request.
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def timestamp_seconds(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def slug_for(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(os.path.expanduser(path)))


def direct_transcripts(directory: Path) -> list[Path]:
    return [path for path in directory.iterdir() if path.is_file() and path.suffix == ".jsonl"]


def resolve_input(project: str | None, transcripts: str | None) -> tuple[str, Path]:
    if transcripts is not None:
        directory = Path(transcripts).expanduser()
        if not directory.is_dir():
            raise AuditInputError(f"transcript directory not found: {directory}")
        return directory.name, directory.resolve()

    projects_root = Path.home() / ".claude" / "projects"
    if project is None:
        slug = slug_for(os.getcwd())
        candidates = [(slug, projects_root / slug)]
    else:
        candidates = []
        if re.fullmatch(r"[-A-Za-z0-9]+", project):
            candidates.append((project, projects_root / project))
        path_slug = slug_for(project)
        if not candidates or candidates[-1][0] != path_slug:
            candidates.append((path_slug, projects_root / path_slug))

    for label, directory in candidates:
        if directory.is_dir():
            return label, directory
    searched = ", ".join(str(directory) for _, directory in candidates)
    raise AuditInputError(f"project transcript directory not found (searched: {searched})")


def is_human_turn(record: dict[str, Any]) -> bool:
    if record.get("type") != "user":
        return False
    message = record.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return False
    has_text = any(isinstance(item, dict) and item.get("type") == "text" for item in content)
    has_tool_result = any(
        isinstance(item, dict) and item.get("type") == "tool_result" for item in content
    )
    return has_text and not has_tool_result


def assistant_request(record: dict[str, Any], sequence: int, chain: int) -> dict[str, Any] | None:
    if record.get("type") != "assistant":
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    if not any(integer(usage.get(key)) is not None for key in (
        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"
    )):
        return None

    context_parts = [
        integer(usage.get("input_tokens")),
        integer(usage.get("cache_creation_input_tokens")),
        integer(usage.get("cache_read_input_tokens")),
    ]
    context = sum(part for part in context_parts if part is not None) if any(
        part is not None for part in context_parts
    ) else None
    cache_creation = usage.get("cache_creation")
    if not isinstance(cache_creation, dict):
        cache_creation = {}
    output_details = usage.get("output_tokens_details")
    if not isinstance(output_details, dict):
        output_details = {}

    return {
        "sequence": sequence,
        "chain": chain,
        "timestamp": timestamp_seconds(record.get("timestamp")),
        "context": context,
        "input": integer(usage.get("input_tokens")),
        "cache_read": integer(usage.get("cache_read_input_tokens")),
        "cache_creation": integer(usage.get("cache_creation_input_tokens")),
        "output": integer(usage.get("output_tokens")),
        "thinking": integer(output_details.get("thinking_tokens")),
        "cache_1h": integer(cache_creation.get("ephemeral_1h_input_tokens")),
        "cache_5m": integer(cache_creation.get("ephemeral_5m_input_tokens")),
        "model": message.get("model") if isinstance(message.get("model"), str) else None,
        "sidechain": record.get("isSidechain") is True,
    }


def tool_result_sizes(record: dict[str, Any]) -> list[int]:
    if record.get("type") != "user":
        return []
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []

    sizes = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_result":
            result_content = item.get("content")
            if not isinstance(result_content, (str, list)):
                continue
            try:
                sizes.append(len(json.dumps(result_content, ensure_ascii=False).encode("utf-8")))
            except (TypeError, ValueError):
                continue
    return sizes


def transcript_paths(project_dir: Path, main_file: Path) -> list[Path]:
    paths = [main_file]
    subagents = project_dir / main_file.stem / "subagents"
    if subagents.is_dir():
        try:
            paths.extend(sorted(
                path for path in subagents.iterdir()
                if path.is_file() and path.name.startswith("agent-") and path.suffix == ".jsonl"
            ))
        except OSError:
            pass
    return paths


def read_session(project_dir: Path, main_file: Path, args: argparse.Namespace) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    sizes: list[int] = []
    skipped = 0
    sequence = 0
    record_count = 0
    understood_count = 0
    synthetic_count = 0
    turn_count = 0

    paths = transcript_paths(project_dir, main_file) if args.runtime == "claude" else [main_file]
    for chain, path in enumerate(paths):
        normalizer = None
        if args.runtime == "codex":
            from codex_audit import CodexNormalizer
            normalizer = CodexNormalizer()
        seen_requests: set[tuple[str, Any]] = set()
        with path.open("r", encoding="utf-8", errors="replace") as transcript:
            for line in transcript:
                sequence += 1
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    if normalizer is not None:
                        raise AuditInputError(f"invalid JSON in native transcript: {path.name}")
                    skipped += 1
                    continue
                if not isinstance(record, dict):
                    skipped += 1
                    continue
                if normalizer is not None:
                    try:
                        record = normalizer.accept(record)
                    except ValueError as error:
                        raise AuditInputError(f"{path.name}: {error}") from error
                    if record is None:
                        continue
                sizes.extend(tool_result_sizes(record))
                if chain == 0 and is_human_turn(record):
                    turn_count += 1
                if record.get("type") != "assistant":
                    continue

                record_count += 1
                message = record.get("message")
                is_synthetic = isinstance(message, dict) and message.get("model") == "<synthetic>"
                if is_synthetic:
                    synthetic_count += 1
                request_id = record.get("requestId")
                message_id = message.get("id") if isinstance(message, dict) else None
                if isinstance(request_id, str) and request_id:
                    request_key = ("request", request_id)
                elif isinstance(message_id, str) and message_id:
                    request_key = ("message", message_id)
                else:
                    request_key = ("record", sequence)
                if request_key in seen_requests:
                    continue
                seen_requests.add(request_key)

                request = assistant_request(record, sequence, chain)
                if request is None:
                    continue
                if normalizer is not None:
                    request["context"] = record["_native_context"]
                understood_count += 1
                if is_synthetic:
                    continue
                requests.append(request)

    def chronological(chain_requests: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            chain_requests,
            key=lambda request: (
                request["timestamp"] is None,
                request["timestamp"] if request["timestamp"] is not None else request["sequence"],
                request["sequence"],
            ),
        )

    main_requests = chronological(
        request for request in requests
        if request["chain"] == 0 and not request["sidechain"]
    )
    idle_gaps_count = 0
    idle_rebuilds_count = 0
    idle_comparisons = 0
    previous_timestamp = None
    for request in main_requests:
        current_timestamp = request["timestamp"]
        if current_timestamp is not None and previous_timestamp is not None:
            idle_comparisons += 1
            gap_minutes = (current_timestamp - previous_timestamp) / 60
            if gap_minutes > args.idle_minutes:
                idle_gaps_count += 1
                creation = request["cache_creation"]
                if creation is not None and creation > args.rebuild_threshold:
                    idle_rebuilds_count += 1
        if current_timestamp is not None:
            previous_timestamp = current_timestamp

    # Native cache-write counters do not establish the Claude TTL/rebuild semantics used above.
    if args.runtime == "codex":
        idle_comparisons = 0
    idle_gaps = idle_gaps_count if idle_comparisons else None
    idle_rebuilds = idle_rebuilds_count if idle_comparisons else None

    contexts = [request["context"] for request in requests if request["context"] is not None]
    main_contexts = [
        request["context"] for request in main_requests if request["context"] is not None
    ]
    first_context = main_requests[0]["context"] if main_requests else None
    context_p90 = percentile(contexts, 0.90)
    main_context_p90 = percentile(main_contexts, 0.90)
    over_tools = sum(size > args.tool_threshold for size in sizes)
    flags = []
    if main_context_p90 is not None and main_context_p90 > args.ctx_threshold:
        flags.append("CTX-P90-OVER")
    if over_tools:
        flags.append("TOOL-RESULT-OVER")
    if idle_rebuilds:
        flags.append("IDLE-REBUILD")
    if first_context is not None and first_context > args.first_threshold:
        flags.append("FIRST-REQUEST-OVER")

    return {
        "session_id": (normalizer.session_id or main_file.stem) if normalizer else main_file.stem,
        "requests": requests,
        "record_count": record_count,
        "request_count": len(requests),
        "understood_count": understood_count,
        "synthetic_count": synthetic_count,
        "turn_count": turn_count,
        "contexts": contexts,
        "main_contexts": main_contexts,
        "first_context": first_context,
        "context_p90": context_p90,
        "main_context_p90": main_context_p90,
        "tool_result_count": len(sizes),
        "tool_results_over": over_tools,
        "idle_comparisons": idle_comparisons,
        "idle_gaps": idle_gaps,
        "idle_rebuilds": idle_rebuilds,
        "skipped_lines": skipped,
        "flags": flags,
    }


def select_sessions(project_dir: Path, args: argparse.Namespace) -> list[Path]:
    files = direct_transcripts(project_dir)
    if args.session:
        wanted = args.session[:-6] if args.session.endswith(".jsonl") else args.session
        return [path for path in files if path.stem == wanted or (
            args.runtime == "codex" and re.fullmatch(r"[0-9a-f-]{36}", wanted)
            and path.stem.endswith("-" + wanted))]
    files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return files if args.all else files[: args.last]


def ratio(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def quotient(part: int, whole: int) -> float | None:
    return round(part / whole, 2) if whole else None


def complete_total(requests: list[dict[str, Any]], key: str) -> int | None:
    if not requests or any(request[key] is None for request in requests):
        return None
    return sum(request[key] for request in requests)


def token_totals(requests: Iterable[dict[str, Any]]) -> dict[str, int | None]:
    request_list = list(requests)
    return {
        key: complete_total(request_list, key)
        for key in ("input", "cache_read", "cache_creation", "output")
    }


def summarize(project: str, sessions: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    requests = [request for session in sessions for request in session["requests"]]
    contexts = [value for session in sessions for value in session["contexts"]]
    main_contexts = [value for session in sessions for value in session["main_contexts"]]
    first_contexts = [session["first_context"] for session in sessions if session["first_context"] is not None]
    output_total = complete_total(requests, "output")
    thinking_total = complete_total(requests, "thinking")
    cache_1h = complete_total(requests, "cache_1h")
    cache_5m = complete_total(requests, "cache_5m")
    main_models: Counter[str] = Counter()
    sidechain_models: Counter[str] = Counter()
    for request in requests:
        if request["model"] is not None:
            (sidechain_models if request["sidechain"] else main_models)[request["model"]] += 1

    ordered_sessions = sorted(
        sessions,
        key=lambda session: (
            session["main_context_p90"] is not None,
            session["main_context_p90"] if session["main_context_p90"] is not None else -1,
            session["session_id"],
        ),
        reverse=True,
    )
    session_count = len(sessions)
    record_count = sum(session["record_count"] for session in sessions)
    request_count = len(requests)
    synthetic_count = sum(session["synthetic_count"] for session in sessions)
    turn_count = sum(session["turn_count"] for session in sessions)
    tool_total = sum(session["tool_result_count"] for session in sessions)
    tool_over = sum(session["tool_results_over"] for session in sessions)
    has_idle_data = any(session["idle_comparisons"] for session in sessions)
    idle_gaps = sum(session["idle_gaps"] or 0 for session in sessions) if has_idle_data else None
    idle_rebuilds = sum(session["idle_rebuilds"] or 0 for session in sessions) if has_idle_data else None
    cache_total = cache_1h + cache_5m if cache_1h is not None and cache_5m is not None else None
    return {
        "project": project,
        "session_count": session_count,
        "record_count": record_count,
        "request_count": request_count,
        "synthetic_count": synthetic_count,
        "turn_count": turn_count,
        "turns_per_session": quotient(turn_count, session_count),
        "requests_per_turn": quotient(request_count, turn_count),
        "requests_per_session": quotient(request_count, session_count),
        "token_totals": token_totals(requests),
        "skipped_lines": sum(session["skipped_lines"] for session in sessions),
        "thresholds": {
            "context_tokens": args.ctx_threshold,
            "tool_result_bytes": args.tool_threshold,
            "first_request_tokens": args.first_threshold,
            "idle_minutes": args.idle_minutes,
            "rebuild_tokens": args.rebuild_threshold,
        },
        "context_per_request": {
            "p50": percentile(contexts, 0.50),
            "p90": percentile(contexts, 0.90),
            "max": max(contexts) if contexts else None,
        },
        "context_per_request_main": {
            "p50": percentile(main_contexts, 0.50),
            "p90": percentile(main_contexts, 0.90),
            "max": max(main_contexts) if main_contexts else None,
        },
        "first_request": {
            "p50": percentile(first_contexts, 0.50),
            "max": max(first_contexts) if first_contexts else None,
        },
        "tool_results": {
            "total": tool_total,
            "over_threshold": tool_over,
            "over_percent": ratio(tool_over, tool_total),
        },
        "idle": {
            "gaps": idle_gaps,
            "cache_rebuilt_after": idle_rebuilds,
        },
        "output_tokens": {
            "total": output_total,
            "thinking": thinking_total,
            "thinking_percent": ratio(thinking_total, output_total)
            if thinking_total is not None and output_total is not None else None,
        },
        "cache_creation": {
            "ephemeral_1h_input_tokens": cache_1h,
            "ephemeral_5m_input_tokens": cache_5m,
            "ephemeral_1h_percent": ratio(cache_1h, cache_total) if cache_total is not None else None,
            "ephemeral_5m_percent": ratio(cache_5m, cache_total) if cache_total is not None else None,
        },
        "models": {
            "main": dict(main_models.most_common()),
            "sidechain": dict(sidechain_models.most_common()),
        },
        "flags": {
            "CTX-P90-OVER": {
                "sessions": sum("CTX-P90-OVER" in session["flags"] for session in sessions)
            },
            "TOOL-RESULT-OVER": {
                "results": sum(session["tool_results_over"] for session in sessions)
            },
            "IDLE-REBUILD": {
                "sessions": sum("IDLE-REBUILD" in session["flags"] for session in sessions)
            },
            "FIRST-REQUEST-OVER": {
                "sessions": sum("FIRST-REQUEST-OVER" in session["flags"] for session in sessions)
            },
        },
        "sessions": [
            {
                "session_id": session["session_id"],
                "record_count": session["record_count"],
                "request_count": session["request_count"],
                "synthetic_count": session["synthetic_count"],
                "turn_count": session["turn_count"],
                "token_totals": token_totals(session["requests"]),
                "context_p90": session["context_p90"],
                "main_context_p90": session["main_context_p90"],
                "first_context": session["first_context"],
                "tool_results_over": session["tool_results_over"],
                "idle_rebuilds": session["idle_rebuilds"],
                "flags": session["flags"],
            }
            for session in ordered_sessions
        ],
    }


def display_number(value: int | None) -> str:
    return "--" if value is None else f"{value:,}"


def display_percent(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "--"
    return f"{value:.{decimals}f}%"


def display_ratio(value: float | None) -> str:
    return "--" if value is None else f"{value:.2f}"


def safe_model_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._:<>-]", "?", model)


def display_models(models: dict[str, int]) -> str:
    if not models:
        return "-  (none in these transcripts)"
    safe_models: Counter[str] = Counter()
    for model, count in models.items():
        safe_models[safe_model_name(model)] += count
    return "   ".join(f"{model}: {count:,}" for model, count in safe_models.most_common())


def threshold_kb(value: int) -> str:
    return f"{value / 1000:g}KB"


def print_text(report: dict[str, Any], args: argparse.Namespace) -> None:
    context = report["context_per_request"]
    main_context = report["context_per_request_main"]
    first = report["first_request"]
    tools = report["tool_results"]
    idle = report["idle"]
    output = report["output_tokens"]
    cache = report["cache_creation"]
    flags = report["flags"]
    tool_percent = ratio(tools["over_threshold"], tools["total"])

    print(
        f"plumb session-audit: {report['project']}  sessions={report['session_count']:,}  "
        f"records={report['record_count']:,}  requests={report['request_count']:,}  "
        f"synthetic={report['synthetic_count']:,}  turns={report['turn_count']:,}  "
        f"skipped_lines={report['skipped_lines']:,}"
    )
    print(
        f"work ratios       turns/session {display_ratio(report['turns_per_session'])}   "
        f"requests/turn {display_ratio(report['requests_per_turn'])}   "
        f"requests/session {display_ratio(report['requests_per_session'])}"
    )
    print(
        f"context/request   p50 {display_number(context['p50'])}   "
        f"p90 {display_number(context['p90'])}   max {display_number(context['max'])}"
    )
    print(
        f"context/request (main) p50 {display_number(main_context['p50'])}   "
        f"p90 {display_number(main_context['p90'])}   max {display_number(main_context['max'])}"
    )
    print(f"first request     p50 {display_number(first['p50'])}   max {display_number(first['max'])}")
    print(
        f"tool results      {tools['total']:,}   over {threshold_kb(args.tool_threshold)} "
        f"{tools['over_threshold']:,} ({display_percent(tool_percent, 1)})"
    )
    print(
        f"idle >{args.idle_minutes:g}m         {display_number(idle['gaps'])}       "
        f"cache rebuilt after {display_number(idle['cache_rebuilt_after'])}"
    )
    print(
        f"output tokens     {display_number(output['total'])}   "
        f"thinking {display_percent(output['thinking_percent'])}"
    )
    print(
        f"cache creation    1h {display_percent(cache['ephemeral_1h_percent'])}   "
        f"5m {display_percent(cache['ephemeral_5m_percent'])}"
    )
    print(f"model (main)      {display_models(report['models']['main'])}")
    print(f"model (sidechain) {display_models(report['models']['sidechain'])}")
    print()
    print("flags")
    print(
        f"  CTX-P90-OVER      {flags['CTX-P90-OVER']['sessions']:,} sessions   "
        f"p90 context above {args.ctx_threshold:,} - compact, or fold what you will not read again"
    )
    print(
        f"  TOOL-RESULT-OVER  {flags['TOOL-RESULT-OVER']['results']:,} results   "
        f"above {threshold_kb(args.tool_threshold)} - return a pointer, not the payload"
    )
    print(
        f"  IDLE-REBUILD      {flags['IDLE-REBUILD']['sessions']:,} sessions    "
        f"resumed after >{args.idle_minutes:g}m with a full cache rebuild - fold before you resume"
    )
    print(
        f"  FIRST-REQUEST-OVER {flags['FIRST-REQUEST-OVER']['sessions']:,} sessions   "
        f"first request above {args.first_threshold:,} tokens - weigh the fixed prompt with plumb-prompt-weight"
    )
    print()
    selection = "--all" if args.all else f"--session {args.session}" if args.session else f"--last {args.last}"
    print(f"per session (worst first, {selection})")
    print(
        f"  session   requests  ctx_p90  ctx_p90(main)  "
        f"tool>{threshold_kb(args.tool_threshold)}  idle_rebuilds  flags"
    )
    for session in report["sessions"]:
        session_id = session["session_id"][:8]
        flag_text = ",".join(session["flags"]) if session["flags"] else "--"
        print(
            f"  {session_id:<8}  {session['request_count']:>8,}  "
            f"{display_number(session['context_p90']):>7}  "
            f"{display_number(session['main_context_p90']):>13}  "
            f"{session['tool_results_over']:>14,}  "
            f"{display_number(session['idle_rebuilds']):>13}  {flag_text}"
        )


def normalized_argv(argv: list[str]) -> list[str]:
    """Let a slug beginning with '-' follow --project as shown in the public CLI."""
    known_options = {
        "--last", "--project", "--transcripts", "--session", "--all", "--json", "--strict",
        "--ctx-threshold", "--tool-threshold", "--idle-minutes", "--rebuild-threshold",
        "--runtime", "-h", "--help",
    }
    result = []
    index = 0
    while index < len(argv):
        if argv[index] in {"--project", "--transcripts"} and index + 1 < len(argv) \
                and argv[index + 1] not in known_options:
            result.append(f"{argv[index]}={argv[index + 1]}")
            index += 2
            continue
        result.append(argv[index])
        index += 1
    return result


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Audit context use in explicitly scoped Claude or Codex transcripts.",
        epilog=(
            "CTX-P90-OVER uses main-chain context only. IDLE-REBUILD uses main-chain requests "
            "only; subagent chains are not resumable sessions."
        ),
    )
    selection = command.add_mutually_exclusive_group()
    selection.add_argument("--last", type=int, help="audit the N most recently modified sessions (default: 10)")
    selection.add_argument("--session", help="audit one session UUID")
    selection.add_argument("--all", action="store_true", help="audit every session in this project")
    source = command.add_mutually_exclusive_group()
    source.add_argument("--project", help="project slug or working-directory path")
    source.add_argument("--transcripts", help="directory containing transcript .jsonl files")
    command.add_argument("--runtime", choices=("claude", "codex"), default="claude")
    command.add_argument("--json", action="store_true", help="print machine-readable JSON")
    command.add_argument("--strict", action="store_true", help="exit 1 when any flag fires")
    command.add_argument("--ctx-threshold", type=int, default=400000)
    command.add_argument("--tool-threshold", type=int, default=40000)
    command.add_argument("--first-threshold", type=int, default=50000,
                         help="flag a session whose first main-chain request exceeds this many tokens")
    command.add_argument("--idle-minutes", type=float, default=60)
    command.add_argument("--rebuild-threshold", type=int, default=20000)
    return command


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(normalized_argv(list(sys.argv[1:] if argv is None else argv)))
    if args.runtime == "codex" and args.transcripts is None:
        parser().error("Codex auditing requires an explicit --transcripts directory")
    if args.last is None:
        args.last = 10
    if args.last <= 0:
        parser().error("--last must be greater than zero")
    if args.ctx_threshold < 0 or args.tool_threshold < 0 or args.idle_minutes < 0 or args.rebuild_threshold < 0:
        parser().error("thresholds cannot be negative")

    project, project_dir = resolve_input(args.project, args.transcripts)
    selected = select_sessions(project_dir, args)
    if args.session and not selected:
        raise AuditInputError(f"session not found in project: {args.session}")

    sessions = []
    for main_file in selected:
        sessions.append(read_session(project_dir, main_file, args))
    if args.runtime == "codex" and len({s["session_id"] for s in sessions}) != len(sessions):
        raise AuditInputError("duplicate native session identity; supply each participant only once")

    record_count = sum(session["record_count"] for session in sessions)
    understood_count = sum(session["understood_count"] for session in sessions)
    if record_count and not understood_count:
        print(
            f"plumb-session-audit: saw {record_count} assistant records and understood 0 - "
            "the transcript format may have changed",
            file=sys.stderr,
        )
        return 2

    if not any(session["requests"] for session in sessions):
        raise AuditInputError(
            f"no recognized usage records; expected {args.runtime} transcripts, not an empty "
            "or unsupported session format"
        )

    report = summarize(project, sessions, args)
    report["runtime"] = args.runtime
    if args.runtime == "codex":
        report["measurement_notes"] = [
            "Usage comes from cumulative token_count snapshots, not duplicate per-response records.",
            "Input totals exclude cache-read and cache-write subsets; reasoning is included in output.",
            "Turns count task_started events. Cache TTL and idle rebuild metrics are unavailable.",
            "Only supplied transcript files are covered; include every review participant explicitly.",
        ]
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report, args)
    any_flags = any(value for count in report["flags"].values() for value in count.values())
    return 1 if args.strict and any_flags else 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except (AuditInputError, OSError) as error:
        print(f"plumb-session-audit: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - this is the CLI's defined unexpected-error boundary.
        print(f"plumb-session-audit: unexpected {type(error).__name__}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
