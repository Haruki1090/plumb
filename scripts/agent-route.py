#!/usr/bin/env python3
"""PreToolUse hook for the Agent tool: two independent behaviours, the second of them opt-in.

Claude Code runs a built-in Explore subagent on the main session's model, and the
CLAUDE_CODE_SUBAGENT_MODEL environment variable does not change it. A PreToolUse hook can: it
answers with `updatedInput`, the whole tool input plus whatever it changes, and Claude Code runs
the call with that. See docs/role-map.md.

Reads the hook JSON on stdin and prints nothing and exits 0 (it never blocks, delays or changes a
call) unless one of these applies. Both can apply to one call; then one `updatedInput` carries both.

1. Explorer model (on by default, only when role.explorer.model is set). All of these hold:
   - tool_input.subagent_type is "Explore"
   - tool_input has no model (a model the caller chose wins)
   - role.explorer.model (scripts/plumb-config.sh, which honours PLUMB_CONFIG) is an alias the
     Agent tool accepts: sonnet, opus, haiku or fable
   Then `model` is added.

2. Worker rules (off unless worker.rules.types is set). All of these hold:
   - worker.rules.types (scripts/plumb-config.sh) is a comma-separated list of subagent type
     names, and tool_input.subagent_type equals one of them exactly (names are trimmed; an unset
     or empty key means the feature is off and no call is touched)
   - tool_input.prompt is a string that does not already start with the marker line
   - docs/worker-rules.md exists in the plugin root this script sits in
   Then `prompt` becomes the marker line, a blank line, and the original prompt. The marker line
   is `Read <absolute path to docs/worker-rules.md> first; it binds this task.` Running it again
   on the result changes nothing. A rule the delegate must follow cannot depend on the coordinator
   remembering to paste it, which is why this is a hook (docs/role-map.md).

No permissionDecision is written: the hook changes the input, not whether the call is allowed.
Any exception means "print nothing, exit 0".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ALIASES = ("sonnet", "opus", "haiku", "fable")
HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(os.path.dirname(HERE), "docs", "worker-rules.md")
MARKER = f"Read {RULES} first; it binds this task."


def config(key: str) -> str:
    try:
        out = subprocess.run(["bash", os.path.join(HERE, "plumb-config.sh"), key, ""],
                             capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def explorer_model() -> str:
    return config("role.explorer.model")


def rules_types() -> set[str]:
    return {name.strip() for name in config("worker.rules.types").split(",") if name.strip()}


def main() -> int:
    try:
        data = json.load(sys.stdin)
        tool_input = data["tool_input"]
        if not isinstance(tool_input, dict):
            return 0
        updated = dict(tool_input)
        kind = tool_input.get("subagent_type")
        if kind == "Explore" and "model" not in tool_input:
            model = explorer_model()
            if model in ALIASES:
                updated["model"] = model
        prompt = tool_input.get("prompt")
        if (isinstance(kind, str) and isinstance(prompt, str) and not (prompt == MARKER or prompt.startswith(MARKER + "\n"))
                and os.path.isfile(RULES) and kind in rules_types()):
            updated["prompt"] = f"{MARKER}\n\n{prompt}"
        if updated == tool_input:
            return 0
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": updated,
        }}))
    except Exception:  # noqa: BLE001 - a hook must never fail an Agent call
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
