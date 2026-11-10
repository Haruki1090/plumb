#!/usr/bin/env python3
"""Regression suite for the Agent PreToolUse hook (scripts/agent-route.py).

    python3 -B scripts/test-agent-route.py

One `ok` / `NG` line per case; exit 1 when any case is NG. The hook gets its JSON on stdin and
reads role.explorer.model from a throwaway config (PLUMB_CONFIG). No network and no `claude`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE / "agent-route.py"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-agent-route-test-"))
FAILED: list[str] = []


def case(name: str):
    def wrap(fn):
        try:
            fn()
        except AssertionError as error:
            FAILED.append(name)
            print(f"  NG   {name}: {error}")
        except Exception:  # noqa: BLE001 - a crashing case is a failing case
            FAILED.append(name)
            print(f"  NG   {name}: crashed\n{traceback.format_exc()}")
        else:
            print(f"  ok   {name}")
        return fn
    return wrap


def config(text: str | None) -> Path:
    """A config file holding `text` (None: a path that does not exist)."""
    path = ROOT / f"config-{len(list(ROOT.iterdir()))}"
    if text is not None:
        path.write_text(text)
    return path


def run(stdin: str, cfg: Path) -> tuple[int, str]:
    env = {**os.environ, "PLUMB_CONFIG": str(cfg)}
    out = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env, timeout=30)
    return out.returncode, out.stdout


def call(tool_input, cfg: Path) -> tuple[int, str]:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent"}
    if tool_input is not None:
        event["tool_input"] = tool_input
    return run(json.dumps(event), cfg)


def assert_silent(code: int, out: str) -> None:
    assert code == 0, f"exit {code}"
    assert out == "", f"printed {out!r}"


EXPLORE = {"subagent_type": "Explore", "prompt": "find the config loader", "description": "Find config",
           "run_in_background": True}


for alias in ("sonnet", "opus", "haiku", "fable"):
    @case(f"Explore without a model gets role.explorer.model = {alias}, the rest of the input kept, no permission decision")
    def _(alias=alias):
        code, out = call(EXPLORE, config(f"role.explorer.model = {alias}\n"))
        assert code == 0, code
        result = json.loads(out)
        assert list(result) == ["hookSpecificOutput"], result
        specific = result["hookSpecificOutput"]
        assert specific["hookEventName"] == "PreToolUse", specific
        assert specific["updatedInput"] == {**EXPLORE, "model": alias}, specific["updatedInput"]
        assert "permissionDecision" not in specific and "permissionDecision" not in result, result


@case("the other keys of the input (prompt, description, run_in_background) come back unchanged")
def _():
    code, out = call(EXPLORE, config("role.explorer.model = sonnet\n"))
    updated = json.loads(out)["hookSpecificOutput"]["updatedInput"]
    for key in ("prompt", "description", "run_in_background"):
        assert updated[key] == EXPLORE[key], (key, updated)
    assert set(updated) == set(EXPLORE) | {"model"}, updated


SONNET = config("role.explorer.model = sonnet\n")


@case("a call that already names a model is left alone")
def _():
    assert_silent(*call({**EXPLORE, "model": "opus"}, SONNET))


for kind in ("general-purpose", "Plan"):
    @case(f"subagent_type {kind} is left alone")
    def _(kind=kind):
        assert_silent(*call({**EXPLORE, "subagent_type": kind}, SONNET))


@case("a call with no subagent_type is left alone")
def _():
    assert_silent(*call({"prompt": "x", "description": "y"}, SONNET))


@case("role.explorer.model unset (empty config, missing file) does nothing")
def _():
    assert_silent(*call(EXPLORE, config("role.judge = codex exec\n")))
    assert_silent(*call(EXPLORE, config(None)))


@case("a value that is not an alias is not written")
def _():
    assert_silent(*call(EXPLORE, config("role.explorer.model = claude-x\n")))


@case("no tool_input does nothing")
def _():
    assert_silent(*call(None, SONNET))


@case("stdin that is not JSON, or is empty, does nothing and exits 0")
def _():
    assert_silent(*run("not json {", SONNET))
    assert_silent(*run("", SONNET))


@case("hooks.json points the PreToolUse matcher Agent at this script, which is executable")
def _():
    data = json.loads((HERE.parent / "hooks" / "hooks.json").read_text())
    entry = data["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Agent" and "scripts/agent-route.py" in entry["hooks"][0]["command"], entry
    assert os.access(HOOK, os.X_OK)


subprocess.run(["rm", "-rf", str(ROOT)])
print()
if FAILED:
    print(f"{len(FAILED)} case(s) NG")
    sys.exit(1)
print("all ok")
