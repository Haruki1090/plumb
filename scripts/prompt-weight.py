#!/usr/bin/env python3
"""Weigh the user-controlled part of the fixed prompt.

`plumb-session-audit` prints `first request p50`: the context the very first request of a session
carries before any work has happened. That number is one figure in the transcript and cannot be
split there. This script lists the files the runtime loads into that first request — instruction
files, the memory index, session-start hooks, enabled plugins' skill and agent listings, user
skills, MCP server declarations — with their bytes and a byte-derived token estimate, so the owner
can see which part of the fixed head is theirs to cut.

It never executes a hook and never prints file contents. The runtime's own system prompt and
tool schemas are not visible from the filesystem and are not counted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DESCRIPTION_RE = re.compile(r"^description:\s*(.*)$", re.MULTILINE)


def token_estimate(data: bytes) -> int:
    ascii_bytes = sum(1 for b in data if b < 0x80)
    return round(ascii_bytes / 4 + (len(data) - ascii_bytes) / 3)


def row(component: str, path: Path | str, data: bytes, note: str = "") -> dict[str, Any]:
    return {
        "component": component,
        "path": str(path),
        "bytes": len(data),
        "tokens_est": token_estimate(data),
        "note": note,
    }


def read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def frontmatter_descriptions(paths: list[Path]) -> bytes:
    """The listing cost of skills or agents is their description lines, not their bodies."""
    out = b""
    for path in paths:
        data = read_bytes(path)
        if data is None:
            continue
        head = data[:4096].decode("utf-8", errors="replace")
        match = DESCRIPTION_RE.search(head)
        if match:
            out += match.group(1).encode("utf-8") + b"\n"
    return out


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def project_slug(project: Path) -> str:
    # The same rule docs/path-map.md records: every non-alphanumeric character becomes "-".
    return re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))


def session_start_commands(hooks: Any) -> list[str]:
    commands: list[str] = []
    if not isinstance(hooks, dict):
        return commands
    for entry in hooks.get("SessionStart") or []:
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks") or []:
            if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                commands.append(hook["command"])
    return commands


def collect(home: Path, project: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    claude = home / ".claude"

    for component, path in (
        ("instructions (global)", claude / "CLAUDE.md"),
        ("instructions (project)", project / "CLAUDE.md"),
        ("instructions (project .claude)", project / ".claude" / "CLAUDE.md"),
        ("memory index", claude / "projects" / project_slug(project) / "memory" / "MEMORY.md"),
    ):
        data = read_bytes(path)
        if data is not None:
            rows.append(row(component, path, data))

    settings = load_json(claude / "settings.json")
    settings = settings if isinstance(settings, dict) else {}
    commands = session_start_commands(settings.get("hooks"))
    if commands:
        rows.append(row("session-start hooks (settings)", claude / "settings.json",
                        "\n".join(commands).encode("utf-8"),
                        f"{len(commands)} command(s); not executed, output size unknown"))

    enabled = settings.get("enabledPlugins")
    enabled = enabled if isinstance(enabled, dict) else {}
    installed = load_json(claude / "plugins" / "installed_plugins.json")
    installed = installed.get("plugins") if isinstance(installed, dict) else None
    installed = installed if isinstance(installed, dict) else {}
    for name, on in sorted(enabled.items()):
        if on is not True:
            continue
        entries = installed.get(name)
        entry = entries[0] if isinstance(entries, list) and entries else None
        root = Path(entry["installPath"]) if isinstance(entry, dict) and isinstance(entry.get("installPath"), str) else None
        if root is None or not root.is_dir():
            rows.append(row(f"plugin {name}", "(install path not found)", b"", "enabled but not installed"))
            continue
        skills = sorted(root.glob("skills/*/SKILL.md"))
        agents = sorted(root.glob("agents/*.md"))
        listing = frontmatter_descriptions(skills) + frontmatter_descriptions(agents)
        notes = [f"{len(skills)} skill(s)", f"{len(agents)} agent(s)"]
        hooks = load_json(root / "hooks" / "hooks.json")
        hook_commands = session_start_commands(hooks.get("hooks") if isinstance(hooks, dict) else None)
        if hook_commands:
            notes.append(f"{len(hook_commands)} session-start hook(s); not executed")
        mcp = load_json(root / ".mcp.json")
        servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
        if isinstance(servers, dict) and servers:
            notes.append(f"{len(servers)} MCP server(s); tool schemas not counted")
        rows.append(row(f"plugin {name}", root, listing, "; ".join(notes)))

    user_skills = sorted((claude / "skills").glob("*/SKILL.md"))
    if user_skills:
        rows.append(row("user skills (listing)", claude / "skills",
                        frontmatter_descriptions(user_skills), f"{len(user_skills)} skill(s)"))

    claude_json = load_json(home / ".claude.json")
    if isinstance(claude_json, dict):
        names = sorted((claude_json.get("mcpServers") or {}).keys()) if isinstance(claude_json.get("mcpServers"), dict) else []
        projects = claude_json.get("projects")
        if isinstance(projects, dict):
            entry = projects.get(str(project.resolve()))
            if isinstance(entry, dict) and isinstance(entry.get("mcpServers"), dict):
                names += sorted(entry["mcpServers"].keys())
        if names:
            rows.append(row("MCP servers (declared)", home / ".claude.json",
                            "\n".join(names).encode("utf-8"),
                            f"{len(names)} server(s); tool schemas not counted"))

    rows.sort(key=lambda r: (-r["bytes"], r["component"]))
    return rows


def print_text(rows: list[dict[str, Any]], total: dict[str, int]) -> None:
    width = max([len(r["component"]) for r in rows] + [len("component")])
    print(f"{'component':<{width}}  {'bytes':>8}  {'~tokens':>8}  note")
    for r in rows:
        print(f"{r['component']:<{width}}  {r['bytes']:>8,}  {r['tokens_est']:>8,}  {r['note']}")
    print(f"{'total':<{width}}  {total['bytes']:>8,}  {total['tokens_est']:>8,}")
    print("estimate: tokens are byte-derived; the runtime's own prompt and tool schemas are not visible here")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="weigh the user-controlled part of the fixed prompt")
    parser.add_argument("--home", default=str(Path.home()), help="home directory (default: $HOME)")
    parser.add_argument("--project", default=".", help="project directory (default: cwd)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)

    home = Path(args.home).expanduser()
    project = Path(args.project).expanduser()
    rows = collect(home, project)
    total = {"bytes": sum(r["bytes"] for r in rows), "tokens_est": sum(r["tokens_est"] for r in rows)}
    if args.json:
        json.dump({"home": str(home), "project": str(project.resolve()), "rows": rows, "total": total,
                   "estimate": "byte-derived; runtime prompt and tool schemas not counted"},
                  sys.stdout, indent=2)
        print()
    else:
        print_text(rows, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
