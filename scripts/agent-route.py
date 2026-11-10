#!/usr/bin/env python3
"""PreToolUse hook for the Agent tool: give an Explore call the model `role.explorer.model` names.

Claude Code runs a built-in Explore subagent on the main session's model, and the
CLAUDE_CODE_SUBAGENT_MODEL environment variable does not change it. A PreToolUse hook can: it
answers with `updatedInput`, the whole tool input plus a `model`, and Claude Code runs the call
with that. See docs/role-map.md.

Reads the hook JSON on stdin. Acts only when all of these hold, and otherwise prints nothing and
exits 0 (it never blocks, delays or changes any other Agent call):

  - tool_input.subagent_type is "Explore"
  - tool_input has no model (a model the caller chose wins)
  - role.explorer.model (scripts/plumb-config.sh, which honours PLUMB_CONFIG) is an alias the
    Agent tool accepts: sonnet, opus, haiku or fable

No permissionDecision is written: the hook changes the model, not whether the call is allowed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ALIASES = ("sonnet", "opus", "haiku", "fable")
HERE = os.path.dirname(os.path.abspath(__file__))


def explorer_model() -> str:
    try:
        out = subprocess.run(["bash", os.path.join(HERE, "plumb-config.sh"), "role.explorer.model", ""],
                             capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def main() -> int:
    try:
        data = json.load(sys.stdin)
        tool_input = data["tool_input"]
        if not isinstance(tool_input, dict) or tool_input.get("subagent_type") != "Explore" or "model" in tool_input:
            return 0
        model = explorer_model()
        if model not in ALIASES:
            return 0
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {**tool_input, "model": model},
        }}))
    except Exception:  # noqa: BLE001 - a hook must never fail an Agent call
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
