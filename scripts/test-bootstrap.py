#!/usr/bin/env python3
"""Regression suite for plumb-bootstrap (scripts/bootstrap.sh) on a private HOME and stub commands.

    python3 -B scripts/test-bootstrap.py

One `ok` / `NG` line per case; exit 1 when any case is NG. `claude` and `codex` are stubs on PATH
(a plugin list that does or does not hold plumb@plumb; a login status that does or does not succeed),
the store is a local bare repository, and plumb-doctor runs in its selftest mode (PLUMB_IN_SELFTEST=1,
which skips its two slow blocks). Nothing leaves the machine and no real config is read.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
BOOTSTRAP = PLUGIN / "bin" / "plumb-bootstrap"
CONFIG_SH = HERE / "plumb-config.sh"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-bootstrap-test-"))
FAILED: list[str] = []
SECRET = "SECRET-TOKEN-7c1e"
BEGIN, END = "# >>> plumb-bootstrap", "# <<< plumb-bootstrap"


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


class Sandbox:
    """A private HOME and config, and a stubs directory first on PATH."""

    def __init__(self, name: str, plumb_installed: bool = True, codex: str | None = "ok") -> None:
        self.root = ROOT / name
        self.stubs = self.root / "stubs"
        self.stubs.mkdir(parents=True)
        (self.root / "home").mkdir()
        self.config = self.root / "home" / ".claude" / "plumb" / "config"  # parent is created by the script
        self.set_plugins(plumb_installed)
        (self.stubs / "claude").write_text(
            f'#!/bin/sh\nif [ "$1 $2 $3" = "plugin list --json" ]; then cat "{self.root}/plugins.json"; exit 0; fi\nexit 1\n')
        (self.stubs / "claude").chmod(0o755)
        if codex:
            self.set_codex(codex)
        self.env = {**os.environ, "HOME": str(self.root / "home"), "PLUMB_CONFIG": str(self.config),
                    "PATH": f"{self.stubs}:{os.environ['PATH']}", "PLUMB_IN_SELFTEST": "1",
                    "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                    "PLUMB_LEDGER_DIR": str(self.root / "ledger"), "ANTHROPIC_API_KEY": SECRET}
        self.env.pop("CODEX_THREAD_ID", None)

    def set_plugins(self, installed: bool) -> None:
        rows = [{"id": "finance@synced", "version": "1.3.0", "scope": "synced", "enabled": True, "installPath": "/x"}]
        if installed:
            rows.append({"id": "plumb@plumb", "version": "0.17.0", "scope": "user", "enabled": True, "installPath": "/y"})
        (self.root / "plugins.json").write_text(json.dumps(rows))

    def set_codex(self, mode: str) -> None:
        """mode ok: `login status` exits 0; out: exits 1. Either way it prints a token, which must never reach the output."""
        code = 0 if mode == "ok" else 1
        (self.stubs / "codex").write_text(
            f'#!/bin/sh\nif [ "$1 $2" = "login status" ]; then echo "Logged in using an API key - {SECRET}"; exit {code}; fi\nexit 0\n')
        (self.stubs / "codex").chmod(0o755)

    def run(self, *args: str, extra_env: dict | None = None):
        out = subprocess.run([str(BOOTSTRAP), *args], capture_output=True, text=True, cwd=self.root,
                             env={**self.env, **(extra_env or {})}, timeout=300)
        return out.returncode, out.stdout, out.stderr

    def read(self) -> str:
        return self.config.read_text()

    def value(self, key: str) -> str:
        out = subprocess.run(["bash", str(CONFIG_SH), key], capture_output=True, text=True, env=self.env)
        return out.stdout.rstrip("\n")


def lines_of(stdout: str, level: str) -> list[str]:
    return [l for l in stdout.splitlines() if l.startswith(f"  {level:<4} ")]


def bare_store(sb: Sandbox) -> Path:
    store = sb.root / "store.git"
    subprocess.run(["git", "init", "--bare", "-q", str(store)], check=True)
    return store


# ---------------------------------------------------------------- the managed block

@case("a missing config file and directory are created, with the given keys in one managed block")
def _():
    sb = Sandbox("create")
    assert not sb.config.parent.exists()
    code, out, err = sb.run("--capture", "on", "--export", "on-stop", "--judge", "codex exec", "--store", "/srv/ledger.git")
    assert code == 0, (code, out, err)
    text = sb.read()
    lines = text.splitlines()
    assert lines[0] == BEGIN and lines[-1] == END, text
    body = [l for l in lines[1:-1] if not l.startswith("#")]
    assert body == ["ledger.store = /srv/ledger.git", "ledger.capture = on", "ledger.export = on-stop",
                    "role.judge = codex exec"], body
    assert [sb.value(k) for k in ("ledger.store", "ledger.capture", "ledger.export", "role.judge")] == [
        "/srv/ledger.git", "on", "on-stop", "codex exec"]


@case("a second run with the same arguments leaves the file byte-identical, with and without other lines")
def _():
    args = ("--capture", "on", "--export", "on-stop", "--judge", "codex exec")
    for name, before in (("idem-empty", None), ("idem-lines", "role.bulk = x\n\n# mine\nstack.tool = gh-stack\n"),
                         ("idem-no-newline", "role.bulk = x")):
        sb = Sandbox(name)
        if before is not None:
            sb.config.parent.mkdir(parents=True)
            sb.config.write_text(before)
        assert sb.run(*args)[0] == 0
        first = sb.read().encode()
        code, out, _ = sb.run(*args)
        assert code == 0 and sb.read().encode() == first, f"{name}: the second run changed the file"
        assert "unchanged" in out, out
        if before is not None:
            assert sb.value("role.bulk") == "x"


@case("only the block is replaced: every other line stays, in order, wherever the block was")
def _():
    sb = Sandbox("replace")
    sb.config.parent.mkdir(parents=True)
    sb.config.write_text("# owner header\nrole.bulk = bulk-cmd\n\n"
                         f"{BEGIN}\nledger.capture = off\nrole.judge = stale\n{END}\n\n"
                         "pane.driver = herdr run   # keep\n\n\nstack.tool = gh-stack\n")
    assert sb.run("--capture", "on")[0] == 0
    text = sb.read()
    assert text.count(BEGIN) == 1 and text.count(END) == 1 and "stale" not in text and "ledger.capture = off" not in text, text
    outside = [l for l in text.splitlines() if l and not l.startswith("#") and "=" in l and l.split("=")[0].strip() not in ("ledger.capture",)]
    assert outside == ["role.bulk = bulk-cmd", "pane.driver = herdr run   # keep", "stack.tool = gh-stack"], outside
    assert "# owner header" in text
    assert [sb.value(k) for k in ("ledger.capture", "role.bulk", "pane.driver", "stack.tool", "role.judge")] == [
        "on", "bulk-cmd", "herdr run", "gh-stack", ""]
    # The owner's lines keep their order and their blank lines, apart from the block's own spot.
    rest = [l for l in text.splitlines() if l not in ("",)]
    assert rest.index("role.bulk = bulk-cmd") < rest.index("pane.driver = herdr run   # keep") < rest.index("stack.tool = gh-stack")


@case("a key also written outside the block is reported and the block's value is the one plumb-config reads")
def _():
    for name, before in (("dup-before", "ledger.capture = off\nrole.bulk = b\n"), ("dup-after", "role.bulk = b\nledger.capture = off\n")):
        sb = Sandbox(name)
        sb.config.parent.mkdir(parents=True)
        sb.config.write_text(before)
        code, out, _ = sb.run("--capture", "on", "--judge", "codex exec")
        assert code == 0, out
        assert any("ledger.capture" in l and "outside" in l for l in lines_of(out, "--")), out
        assert not any("role.judge" in l and "outside" in l for l in lines_of(out, "--")), out
        assert sb.value("ledger.capture") == "on", f"{name}: the block lost to the line outside it"
        assert sb.value("role.bulk") == "b"
        assert "ledger.capture = off" in sb.read(), "the owner's own line must stay"
        code, out2, _ = sb.run("--capture", "on", "--judge", "codex exec")
        assert any("ledger.capture" in l and "outside" in l for l in lines_of(out2, "--")), "reported again on the next run"


@case("a block without its closing line is refused and the file is left untouched")
def _():
    sb = Sandbox("unterminated")
    sb.config.parent.mkdir(parents=True)
    original = f"role.bulk = x\n{BEGIN}\nledger.capture = off\nrole.judge = y\n"
    sb.config.write_text(original)
    code, out, _ = sb.run("--capture", "on")
    assert code == 0 and sb.read() == original, (code, sb.read())
    assert any("config" in l and END in l for l in lines_of(out, "NG")), out
    code, _, _ = sb.run("--capture", "on", "--strict")
    assert code == 1


@case("values that the config format would cut are quoted and read back exactly")
def _():
    sb = Sandbox("quoting")
    judge = "codex exec -c 'model=x' # not a comment"
    assert sb.run("--judge", judge)[0] == 0
    assert sb.value("role.judge") == judge, sb.value("role.judge")
    judge2 = 'wrapper --flag "a b" # tail'
    assert sb.run("--judge", judge2)[0] == 0
    assert sb.value("role.judge") == judge2, sb.value("role.judge")
    code, out, err = sb.run("--judge", "x \"a\" 'b' # c")
    assert code == 2, (code, out, err)


@case("with no keys given the config is neither created nor touched")
def _():
    sb = Sandbox("nokeys")
    code, out, _ = sb.run()
    assert code == 0 and not sb.config.exists(), (code, out)
    sb.config.parent.mkdir(parents=True)
    sb.config.write_text("role.bulk = x\n")
    assert sb.run()[0] == 0 and sb.read() == "role.bulk = x\n"


# ---------------------------------------------------------------- the checks

@case("plumb installed prints its version; not installed is NG; claude missing from PATH is NG")
def _():
    sb = Sandbox("installed")
    code, out, _ = sb.run()
    assert code == 0 and any("plumb@plumb" in l and "0.17.0" in l for l in lines_of(out, "ok")), out
    sb.set_plugins(False)
    code, out, _ = sb.run()
    assert code == 0 and any("plumb@plumb is not installed" in l for l in lines_of(out, "NG")), out
    (sb.stubs / "claude").unlink()
    # Keep git, bash and python3 reachable but hide any real claude.
    bin_dir = sb.root / "bin-no-claude"
    bin_dir.mkdir()
    for tool in ("bash", "git", "python3", "awk", "sed", "cat", "cmp", "tail", "mktemp", "dirname", "mkdir", "rm", "timeout", "tr", "env", "sh", "grep", "head"):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    code, out, _ = sb.run(extra_env={"PATH": str(bin_dir)})
    assert code == 0 and any("claude is not on PATH" in l for l in lines_of(out, "NG")), out


@case("the judge: codex logged in is ok, logged out is NG, missing is NG, another command only has to resolve, unset is --")
def _():
    sb = Sandbox("judge")
    code, out, _ = sb.run("--judge", "codex exec --sandbox read-only")
    assert any("role.judge" in l and "logged in" in l for l in lines_of(out, "ok")), out
    assert SECRET not in out, "codex login status output reached the output"
    sb.set_codex("out")
    code, out, _ = sb.run("--judge", "codex exec")
    assert code == 0 and any("role.judge" in l and "not logged in" in l for l in lines_of(out, "NG")), out
    assert SECRET not in out
    code, out, _ = sb.run("--judge", "no-such-judge-cmd --x")
    assert any("no-such-judge-cmd is not on PATH" in l for l in lines_of(out, "NG")), out
    code, out, _ = sb.run("--judge", "git --version")
    assert any("role.judge: git resolves" in l for l in lines_of(out, "ok")), out
    (sb.stubs / "codex").unlink()
    shutil.rmtree(sb.config.parent)
    code, out, _ = sb.run()
    assert any("role.judge: unset" in l for l in lines_of(out, "--")), out


@case("the store: a reachable one is ok, an unreachable one is NG, unset is --, and no credential is printed")
def _():
    sb = Sandbox("store")
    store = bare_store(sb)
    code, out, _ = sb.run("--store", str(store))
    assert any("ledger.store answers" in l for l in lines_of(out, "ok")), out
    code, out, err = sb.run("--store", str(sb.root / "missing.git"))
    assert code == 0 and any(l.startswith("  NG   ledger.store") for l in out.splitlines()), out
    url = f"http://deploy:{SECRET}@127.0.0.1:9/private/ledger.git"
    code, out, err = sb.run("--store", url)
    assert code == 0 and any(l.startswith("  NG   ledger.store") for l in out.splitlines()), out
    assert SECRET not in out and SECRET not in err, (out, err)
    shutil.rmtree(sb.config.parent)
    code, out, _ = sb.run()
    assert any("ledger.store: unset" in l for l in lines_of(out, "--")), out


@case("plumb-doctor's overall line is printed alone")
def _():
    sb = Sandbox("doctor")
    code, out, _ = sb.run()
    doctor = [l for l in out.splitlines() if "plumb-doctor:" in l]
    assert len(doctor) == 1 and ("healthy" in doctor[0] or "needs attention" in doctor[0]), doctor
    assert "— " not in out and "plumb doctor:" not in out, "more than the last line of doctor leaked"


@case("exit 0 with NG lines; --strict exits 1 exactly when there is an NG line")
def _():
    sb = Sandbox("strict", plumb_installed=False)
    code, out, _ = sb.run("--capture", "on")
    assert code == 0 and lines_of(out, "NG"), (code, out)
    code, out, _ = sb.run("--capture", "on", "--strict")
    assert code == 1 and lines_of(out, "NG"), (code, out)
    sb.set_plugins(True)
    code, out, _ = sb.run("--capture", "on", "--strict")
    assert code == (1 if lines_of(out, "NG") else 0), (code, out)
    code, out, _ = sb.run("--capture", "on")
    assert code == 0, (code, out)


# ---------------------------------------------------------------- usage and secrets

@case("usage errors exit 2 and write nothing; --help exits 0")
def _():
    sb = Sandbox("usage")
    for args in (["--bogus"], ["--store"], ["--store", ""], ["--capture", "maybe"], ["--export", "sometimes"],
                 ["--judge"], ["--capture", "on", "stray"], ["--judge", "a\nb"], ["--store=", "--capture", "on"]):
        code, out, err = sb.run(*args)
        assert code == 2 and err, (args, code, out, err)
        assert not sb.config.exists(), f"{args} wrote the config"
    code, out, err = sb.run("--help")
    assert code == 0 and out.startswith("usage: plumb-bootstrap") and "--strict" in out, (code, out)
    code, out, err = sb.run("--capture=on", "--export=manual")
    assert code == 0 and sb.value("ledger.capture") == "on" and sb.value("ledger.export") == "manual", (code, out)


@case("config values come from the command line only; the environment's secrets are never read or printed")
def _():
    sb = Sandbox("env")
    env = {"PLUMB_STORE": f"https://x:{SECRET}@example.invalid/a.git", "LEDGER_STORE": "x", "STORE": "x", "JUDGE": "x"}
    code, out, err = sb.run("--capture", "on", extra_env=env)
    assert code == 0
    assert SECRET not in out + err + sb.read(), "an environment value reached the output or the config"
    assert sb.value("ledger.store") == "" and sb.value("role.judge") == ""
    # A credential given on the command line is written (that is what was asked) but never echoed.
    url = f"https://deploy:{SECRET}@example.invalid/ledger.git"
    code, out, err = sb.run("--store", url, "--capture", "on")
    assert SECRET not in out + err, (out, err)
    assert SECRET not in subprocess.run(["bash", "-c", f'bash "{BOOTSTRAP}" --help'], capture_output=True, text=True, env=sb.env).stdout


shutil.rmtree(ROOT, ignore_errors=True)
print()
if FAILED:
    print(f"{len(FAILED)} case(s) NG")
    sys.exit(1)
print("all ok")
