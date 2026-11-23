#!/usr/bin/env python3
"""Regression suite for the Agent PreToolUse hook (scripts/agent-route.py).

    python3 -B scripts/test-agent-route.py

One `ok` / `NG` line per case; exit 1 when any case is NG. The hook gets its JSON on stdin and
reads role.explorer.model and worker.rules.types from a throwaway config (PLUMB_CONFIG). No network
and no `claude`.
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


def run(stdin: str, cfg: Path, hook: Path = HOOK) -> tuple[int, str]:
    env = {**os.environ, "PLUMB_CONFIG": str(cfg)}
    out = subprocess.run([sys.executable, str(hook)], input=stdin, capture_output=True, text=True, env=env, timeout=30)
    return out.returncode, out.stdout


def call(tool_input, cfg: Path, hook: Path = HOOK) -> tuple[int, str]:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent"}
    if tool_input is not None:
        event["tool_input"] = tool_input
    return run(json.dumps(event), cfg, hook)


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


# ---- worker rules: opt-in through worker.rules.types ----

RULES = HERE.parent / "docs" / "worker-rules.md"
MARKER = f"Read {RULES} first; it binds this task."
WORKER = {"subagent_type": "implementer", "prompt": "add the flag", "description": "Add flag"}


def updated_input(out: str) -> dict:
    result = json.loads(out)
    assert list(result) == ["hookSpecificOutput"], result
    specific = result["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse" and "permissionDecision" not in specific, specific
    return specific["updatedInput"]


@case("the rules file the marker points at exists, at an absolute path")
def _():
    assert RULES.is_file() and RULES.is_absolute(), RULES


@case("worker.rules.types unset (no key, empty value, missing file): no call is touched, nothing is printed")
def _():
    for text in ("role.explorer.model = sonnet\n", "worker.rules.types =\n", "worker.rules.types = # none\n", None):
        cfg = config(text)
        for tool_input in (WORKER, {**WORKER, "subagent_type": "general-purpose"}, {"prompt": "x"}):
            assert_silent(*call(tool_input, cfg))


@case("a listed type gets the marker line, a blank line and the original prompt; the other keys are unchanged")
def _():
    code, out = call(WORKER, config("worker.rules.types = implementer\n"))
    assert code == 0, code
    got = updated_input(out)
    assert got == {**WORKER, "prompt": f"{MARKER}\n\n{WORKER['prompt']}"}, got


@case("a type that is not listed is left alone, and a name must match exactly (no prefix, no case folding)")
def _():
    cfg = config("worker.rules.types = implementer\n")
    for kind in ("general-purpose", "Plan", "implementer-2", "Implementer", "impl"):
        assert_silent(*call({**WORKER, "subagent_type": kind}, cfg))


@case("a prompt that already starts with the marker line is left alone (idempotent), and the result of a run is stable")
def _():
    cfg = config("worker.rules.types = implementer\n")
    assert_silent(*call({**WORKER, "prompt": f"{MARKER}\n\nadd the flag"}, cfg))
    once = updated_input(call(WORKER, cfg)[1])
    assert_silent(*call(once, cfg))
    assert once["prompt"].count(MARKER) == 1, once


@case("the marker has to start the prompt: a prompt that only mentions the line further on still gets one")
def _():
    prompt = f"note: {MARKER}"
    got = updated_input(call({**WORKER, "prompt": prompt}, config("worker.rules.types = implementer\n"))[1])
    assert got["prompt"] == f"{MARKER}\n\n{prompt}", got


@case("Explore listed in the key gets both the model and the marker in one updatedInput")
def _():
    got = updated_input(call(EXPLORE, config("role.explorer.model = haiku\nworker.rules.types = Explore\n"))[1])
    assert got == {**EXPLORE, "model": "haiku", "prompt": f"{MARKER}\n\n{EXPLORE['prompt']}"}, got


@case("Explore listed with no model configured, or with a model of its own, gets the marker only")
def _():
    got = updated_input(call(EXPLORE, config("worker.rules.types = Explore\n"))[1])
    assert got == {**EXPLORE, "prompt": f"{MARKER}\n\n{EXPLORE['prompt']}"}, got
    both = config("role.explorer.model = haiku\nworker.rules.types = Explore\n")
    got = updated_input(call({**EXPLORE, "model": "opus"}, both)[1])
    assert got["model"] == "opus" and got["prompt"].startswith(MARKER), got


@case("Explore not listed keeps only its model; a listed type is not given a model")
def _():
    cfg = config("role.explorer.model = haiku\nworker.rules.types = implementer\n")
    assert updated_input(call(EXPLORE, cfg)[1]) == {**EXPLORE, "model": "haiku"}
    assert "model" not in updated_input(call(WORKER, cfg)[1])


for text in ("worker.rules.types = implementer,Plan\n", "worker.rules.types =   Plan ,  implementer  \n",
             "worker.rules.types = ,Plan,, implementer,\n", 'worker.rules.types = "Plan, implementer"\n',
             "worker.rules.types = general-purpose, implementer, Plan  # lanes\n"):
    @case(f"several names with spaces, empty items, quotes or a comment are read: {text.strip()}")
    def _(text=text):
        cfg = config(text)
        for kind in ("implementer", "Plan"):
            got = updated_input(call({**WORKER, "subagent_type": kind}, cfg)[1])
            assert got["prompt"] == f"{MARKER}\n\n{WORKER['prompt']}", (kind, got)
        assert_silent(*call({**WORKER, "subagent_type": "Explore"}, cfg))


@case("a namespaced type name (plugin:agent) is matched as written")
def _():
    cfg = config("worker.rules.types = plumb:pr-refuter\n")
    assert updated_input(call({**WORKER, "subagent_type": "plumb:pr-refuter"}, cfg)[1])["prompt"].startswith(MARKER)
    assert_silent(*call({**WORKER, "subagent_type": "pr-refuter"}, cfg))


@case("a listed call with no prompt, or a prompt that is not a string, is left alone")
def _():
    cfg = config("worker.rules.types = implementer\n")
    assert_silent(*call({"subagent_type": "implementer", "description": "x"}, cfg))
    assert_silent(*call({"subagent_type": "implementer", "prompt": ["a"]}, cfg))
    assert_silent(*call({"subagent_type": "implementer", "prompt": None}, cfg))


@case("the rules file missing means no change to the prompt (a copy of the hook with no docs/ beside it); the model still goes in")
def _():
    plugin = ROOT / "plugin-without-rules"
    (plugin / "scripts").mkdir(parents=True)
    for name in ("agent-route.py", "plumb-config.sh"):
        (plugin / "scripts" / name).write_text((HERE / name).read_text())
    hook = plugin / "scripts" / "agent-route.py"
    cfg = config("role.explorer.model = sonnet\nworker.rules.types = implementer, Explore\n")
    assert_silent(*call(WORKER, cfg, hook))
    assert updated_input(call(EXPLORE, cfg, hook)[1]) == {**EXPLORE, "model": "sonnet"}


@case("malformed stdin or an odd tool_input with the key set does nothing and exits 0")
def _():
    cfg = config("worker.rules.types = implementer\n")
    for stdin in ("not json {", "", "[]", '{"tool_input": "implementer"}', '{"tool_input": null}'):
        assert_silent(*run(stdin, cfg))
    assert_silent(*call(None, cfg))
    assert_silent(*call({"subagent_type": ["implementer"], "prompt": "x"}, cfg))


HOOK_COMMAND ='python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent-route.py" || true'


@case("hooks.json points the PreToolUse matcher Agent at this script, which is executable")
def _():
    data = json.loads((HERE.parent / "hooks" / "hooks.json").read_text())
    entry = data["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Agent" and entry["hooks"] == [{"type": "command", "command": HOOK_COMMAND}], entry
    assert os.access(HOOK, os.X_OK)


@case("the hooks.json command exits 0 and prints nothing when the script does not exist (a PreToolUse exit 2 would stop the call)")
def _():
    data = json.loads((HERE.parent / "hooks" / "hooks.json").read_text())
    command = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    missing = ROOT / "no-such-plugin-root"
    assert not missing.exists()
    event = json.dumps({"tool_name": "Agent", "tool_input": EXPLORE})
    out = subprocess.run(["bash", "-c", command.replace("${CLAUDE_PLUGIN_ROOT}", str(missing))], input=event,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stdout == "", (out.returncode, out.stdout, out.stderr)
    # Control: the same command with the real plugin root does route the call.
    real = subprocess.run(["bash", "-c", command.replace("${CLAUDE_PLUGIN_ROOT}", str(HERE.parent))], input=event,
                          capture_output=True, text=True, timeout=30, env={**os.environ, "PLUMB_CONFIG": str(SONNET)})
    assert json.loads(real.stdout)["hookSpecificOutput"]["updatedInput"]["model"] == "sonnet", real


subprocess.run(["rm", "-rf", str(ROOT)])
print()
if FAILED:
    print(f"{len(FAILED)} case(s) NG")
    sys.exit(1)
print("all ok")
