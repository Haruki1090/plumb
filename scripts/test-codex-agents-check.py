#!/usr/bin/env python3
"""Regression suite for `plumb-sidecar-agents-check`, on synthetic checkouts in temp dirs plus one run on the real one.

    python3 -B scripts/test-codex-agents-check.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Every synthetic repository is built under
tempfile.mkdtemp() and removed at the end; nothing here writes to the real checkout.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import tomllib
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCRIPT = HERE / "codex-agents-check.py"
BIN = PLUGIN / "bin" / "plumb-sidecar-agents-check"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-codex-agents-test-"))
FAILED: list[str] = []
_counter = [0]

BODY = b'name = "plumb_demo"\ndescription = "A demo."\ndeveloper_instructions = """\nDo the thing.\n"""\n'


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


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_repo() -> Path:
    _counter[0] += 1
    repo = ROOT / f"repo{_counter[0]}"
    (repo / "agents").mkdir(parents=True)
    (repo / ".codex" / "agents").mkdir(parents=True)
    return repo


def put_source(repo: Path, name: str, data: bytes = b"# demo source\nOriginal.\n") -> bytes:
    (repo / "agents" / f"{name}.md").write_bytes(data)
    return data


def put_toml(repo: Path, name: str, first: str | None, body: bytes = BODY) -> Path:
    path = repo / ".codex" / "agents" / f"plumb-{name}.toml"
    path.write_bytes((first.encode() + b"\n" if first is not None else b"") + body)
    return path


def header(source: str, data: bytes) -> str:
    return f"# source: agents/{source}.md sha256:{digest(data)}"


def run(repo: Path, *args: str) -> tuple[int, list[list[str]], str]:
    done = subprocess.run([sys.executable, "-B", str(SCRIPT), "--root", str(repo), *args], capture_output=True, text=True)
    rows = [line.split("\t") for line in done.stdout.splitlines() if "\t" in line]
    return done.returncode, rows, done.stdout


def states(rows: list[list[str]]) -> dict[str, str]:
    return {row[1]: row[0] for row in rows}


@case("ok: a matching hash exits 0 and prints one tab-separated line")
def _():
    repo = make_repo()
    data = put_source(repo, "alpha")
    put_toml(repo, "alpha", header("alpha", data))
    code, rows, out = run(repo)
    assert code == 0, out
    assert rows == [["ok", ".codex/agents/plumb-alpha.toml", "agents/alpha.md"]], rows


@case("none: `# source: none` is accepted and exits 0")
def _():
    repo = make_repo()
    put_toml(repo, "loner", "# source: none")
    code, rows, out = run(repo)
    assert code == 0, out
    assert rows == [["none", ".codex/agents/plumb-loner.toml", "-"]], rows


@case("stale: a changed source exits 1, names both paths and prints the instruction")
def _():
    repo = make_repo()
    data = put_source(repo, "alpha")
    put_toml(repo, "alpha", header("alpha", data))
    (repo / "agents" / "alpha.md").write_bytes(data + b"x")
    code, rows, out = run(repo)
    assert code == 1, out
    assert rows == [["stale", ".codex/agents/plumb-alpha.toml", "agents/alpha.md"]], rows
    assert "re-read the source, bring the condensed instructions up to date, then run with --update" in out, out


@case("no-source-line: a toml with no comment on line one exits 1")
def _():
    repo = make_repo()
    put_source(repo, "alpha")
    put_toml(repo, "alpha", None)
    code, rows, out = run(repo)
    assert code == 1, out
    assert states(rows)[".codex/agents/plumb-alpha.toml"] == "no-source-line", rows


@case("no-source-line: a malformed hash, an empty file and a path outside agents/ are all malformed")
def _():
    repo = make_repo()
    data = put_source(repo, "alpha")
    put_toml(repo, "short", f"# source: agents/alpha.md sha256:{digest(data)[:10]}")
    put_toml(repo, "escape", f"# source: ../outside.md sha256:{digest(data)}")
    (repo / ".codex" / "agents" / "plumb-empty.toml").write_bytes(b"")
    code, rows, out = run(repo)
    got = states(rows)
    assert code == 1, out
    for name in ("short", "escape", "empty"):
        assert got[f".codex/agents/plumb-{name}.toml"] == "no-source-line", rows


@case("missing-source: a header naming an agents/ file that does not exist exits 1")
def _():
    repo = make_repo()
    put_toml(repo, "ghost", f"# source: agents/ghost.md sha256:{digest(b'x')}")
    code, rows, out = run(repo)
    assert code == 1, out
    assert rows == [["missing-source", ".codex/agents/plumb-ghost.toml", "agents/ghost.md"]], rows


@case("unmapped: an agents/*.md that no toml names exits 1")
def _():
    repo = make_repo()
    data = put_source(repo, "alpha")
    put_source(repo, "orphan")
    put_toml(repo, "alpha", header("alpha", data))
    code, rows, out = run(repo)
    assert code == 1, out
    assert ["unmapped", "-", "agents/orphan.md"] in rows, rows
    assert states(rows)[".codex/agents/plumb-alpha.toml"] == "ok", rows


@case("mixed: ok and none files do not hide a stale one in the same run")
def _():
    repo = make_repo()
    one = put_source(repo, "one")
    two = put_source(repo, "two")
    put_toml(repo, "one", header("one", one))
    put_toml(repo, "two", header("two", two))
    put_toml(repo, "loner", "# source: none")
    (repo / "agents" / "two.md").write_bytes(two + b"!")
    code, rows, out = run(repo)
    assert code == 1, out
    assert states(rows) == {
        ".codex/agents/plumb-one.toml": "ok",
        ".codex/agents/plumb-two.toml": "stale",
        ".codex/agents/plumb-loner.toml": "none",
    }, rows


@case("--update: a stale file becomes ok and the update is printed")
def _():
    repo = make_repo()
    data = put_source(repo, "alpha")
    path = put_toml(repo, "alpha", header("alpha", data))
    (repo / "agents" / "alpha.md").write_bytes(data + b"more\n")
    code, rows, out = run(repo, "--update")
    assert code == 0, out
    assert rows == [["updated", ".codex/agents/plumb-alpha.toml", "agents/alpha.md"]], rows
    new_data = (repo / "agents" / "alpha.md").read_bytes()
    assert path.read_bytes() == header("alpha", new_data).encode() + b"\n" + BODY, path.read_bytes()
    code, rows, out = run(repo)
    assert code == 0 and states(rows)[".codex/agents/plumb-alpha.toml"] == "ok", (code, out)


@case("--update: a malformed first line is left untouched and still fails")
def _():
    repo = make_repo()
    data = put_source(repo, "alpha")
    path = put_toml(repo, "alpha", f"# source: agents/alpha.md sha256:{digest(data)[:12]}")
    before = path.read_bytes()
    code, rows, out = run(repo, "--update")
    assert code == 1, out
    assert path.read_bytes() == before, "the malformed file was rewritten"
    assert states(rows)[".codex/agents/plumb-alpha.toml"] == "no-source-line", rows


@case("--update: files that are not stale stay byte-identical")
def _():
    repo = make_repo()
    one = put_source(repo, "one")
    two = put_source(repo, "two")
    ok_path = put_toml(repo, "one", header("one", one))
    stale_path = put_toml(repo, "two", header("two", two))
    none_path = put_toml(repo, "loner", "# source: none")
    missing_path = put_toml(repo, "ghost", f"# source: agents/ghost.md sha256:{digest(b'x')}")
    plain_path = put_toml(repo, "plain", None)
    kept = {p: p.read_bytes() for p in (ok_path, none_path, missing_path, plain_path)}
    (repo / "agents" / "two.md").write_bytes(two + b"changed")
    stale_before = stale_path.read_bytes()
    run(repo, "--update")
    for path, before in kept.items():
        assert path.read_bytes() == before, f"{path.name} changed"
    assert stale_path.read_bytes() != stale_before, "the stale file was not updated"
    assert stale_path.read_bytes().split(b"\n", 1)[1] == stale_before.split(b"\n", 1)[1], "more than the first line changed"


@case("the first-line comment leaves the body parseable with tomllib")
def _():
    repo = make_repo()
    data = put_source(repo, "alpha")
    path = put_toml(repo, "alpha", header("alpha", data))
    parsed = tomllib.loads(path.read_text())
    assert parsed["name"] == "plumb_demo" and parsed["developer_instructions"] == "Do the thing.\n", parsed
    (repo / "agents" / "alpha.md").write_bytes(data + b"x")
    run(repo, "--update")
    assert tomllib.loads(path.read_text())["name"] == "plumb_demo"


@case("usage: an unknown option and a root without .codex/agents exit 2")
def _():
    repo = make_repo()
    bad = subprocess.run([sys.executable, "-B", str(SCRIPT), "--bogus"], capture_output=True, text=True)
    assert bad.returncode == 2, bad
    empty = ROOT / "no-such-checkout"
    empty.mkdir()
    code, _, out = run(empty)
    assert code == 2, (code, out)


@case("the wrapper runs python3 -B and the script leaves no bytecode behind")
def _():
    assert "exec python3 -B " in BIN.read_text()
    done = subprocess.run([str(BIN), "--help"], capture_output=True, text=True)
    assert done.returncode == 0, done
    assert not list(HERE.glob("__pycache__/codex-agents-check*")), "bytecode was written"


@case("the real repository: every Codex agent file is ok or none and nothing is unmapped")
def _():
    done = subprocess.run([str(BIN)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert any(line.startswith("ok\t") for line in done.stdout.splitlines()), done.stdout


shutil.rmtree(ROOT, ignore_errors=True)
if FAILED:
    print(f"\n{len(FAILED)} case(s) failed")
    sys.exit(1)
print("\nall cases ok")
