#!/usr/bin/env python3
"""Regression suite for plumb-code-policy on throwaway git repositories.

    python3 -B scripts/test-code-policy.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline under
tempfile.mkdtemp(): the fixture under scripts/fixtures/code-policy/ is committed into fresh
repositories (the base commit, then the head commit on a feature branch), the contract variants
are written here, and the report runs through bin/plumb-code-policy. No network, no other
checkout is read.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
FIXTURE = HERE / "fixtures" / "code-policy"
CLI = PLUGIN / "bin" / "plumb-code-policy"
PROJECT_CLI = PLUGIN / "bin" / "plumb-project"
SCRIPT = HERE / "plumb-code-policy.py"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-code-policy-test-"))
FAILED: list = []
IDENTITY = ["-c", "user.name=selftest", "-c", "user.email=code-policy@users.noreply.github.com",
            "-c", "commit.gpgsign=false"]
COUNTER = [0]

CONTRACT = (FIXTURE / "project.toml").read_text()
HEAD_LINES = (FIXTURE / "head" / "src" / "app.tsx").read_text().splitlines()


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


# ---------------------------------------------------------------- scaffolding

def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *IDENTITY, *args], cwd=str(repo), capture_output=True, text=True)
    assert done.returncode == 0, f"git {args[0]} failed: {done.stderr.strip()}"
    return done.stdout


def make_repo(name: str) -> Path:
    COUNTER[0] += 1
    repo = ROOT / f"{name}-{COUNTER[0]}"
    (repo / ".plumb").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    return repo


def write(repo: Path, rel: str, text: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def apply_tree(repo: Path, tree: str) -> None:
    source = FIXTURE / tree
    for path in sorted(source.rglob("*")):
        if path.is_file():
            target = repo / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def fixture_repo(name: str) -> Path:
    """The base commit on main, the head commit on a feature branch."""
    repo = make_repo(name)
    write(repo, ".plumb/project.toml", CONTRACT)
    apply_tree(repo, "base")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "feature")
    apply_tree(repo, "head")
    commit(repo, "head")
    return repo


def run_cli(cwd: Path, *args: str):
    return subprocess.run([str(CLI), *args], cwd=str(cwd), capture_output=True, text=True, timeout=300)


def project_cli(cwd: Path, *args: str):
    return subprocess.run([str(PROJECT_CLI), *args], cwd=str(cwd), capture_output=True, text=True, timeout=60)


def findings_of(stdout: str) -> set:
    """The `rule<TAB>path:line<TAB>excerpt` rows as (rule, path, line) tuples."""
    rows = set()
    for line in stdout.splitlines():
        if line.startswith("summary:"):
            break
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        path, _, number = parts[1].rpartition(":")
        rows.add((parts[0], path, int(number)))
    return rows


def counts_of(stdout: str) -> dict:
    found = {}
    for line in stdout.splitlines():
        match = re.match(r"summary: (\S+) (\d+)$", line)
        if match:
            found[match.group(1)] = int(match.group(2))
    return found


def contract_with(extra: str = "", mode: str = "report") -> str:
    body = CONTRACT.replace('mode = "report"', f'mode = "{mode}"')
    if extra:
        body = body.replace("[[code_policy.rule]]", f"{extra}\n[[code_policy.rule]]", 1)
    return body


def head_line(snippet: str) -> int:
    for index, line in enumerate(HEAD_LINES, 1):
        if snippet in line:
            return index
    raise AssertionError(f"the fixture no longer has a line holding: {snippet}")


MOVED = head_line("moved block comment")
ADDED_COMMENT = head_line("newly added line comment")
EFFECT = next(i for i, l in enumerate(HEAD_LINES, 1) if l.strip() == "useEffect(() => {")
REACT = head_line("React.useEffect")
ESLINT = head_line("eslint-disable-next-line")
EXPECTED = {
    ("no-new-comment", "src/app.tsx", MOVED),
    ("no-new-comment", "src/app.tsx", ADDED_COMMENT),
    ("no-new-effect", "src/app.tsx", EFFECT),
    ("no-new-effect", "src/app.tsx", REACT),
    ("no-new-comment", "src/app.tsx", ESLINT),
    ("no-new-suppression", "src/app.tsx", ESLINT),
}
EXPECTED_COUNTS = {"no-new-comment": 3, "no-new-effect": 2, "no-new-suppression": 1}


# ---------------------------------------------------------------- the report

@case("the report lists exactly the introduced findings: the moved block counted, the string and URL cases not")
def _():
    repo = fixture_repo("report")
    done = run_cli(repo, "report")
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert findings_of(done.stdout) == EXPECTED, (findings_of(done.stdout), EXPECTED)
    assert counts_of(done.stdout) == EXPECTED_COUNTS, counts_of(done.stdout)
    assert "note: moved lines count as added" in done.stdout, done.stdout
    assert "separator inside a string" not in done.stdout, "a string is not a comment"
    assert "example.invalid" not in done.stdout, "a URL inside a string is not a comment"
    assert "existing comment kept in place" not in done.stdout, "an unchanged line is not introduced"
    assert "skip.test.tsx" not in done.stdout, "an excluded path is out of scope"
    assert "gen.ts" not in done.stdout, "a path outside include is out of scope"


@case("uncommitted edits and untracked files in scope count as introduced")
def _():
    repo = fixture_repo("worktree")
    write(repo, "src/untracked.tsx",
          "export const untracked = true;\n// an untracked file's comment is newly introduced\n")
    write(repo, "src/app.tsx", (FIXTURE / "head" / "src" / "app.tsx").read_text() + "// an uncommitted trailing comment\n")
    done = run_cli(repo, "report")
    assert done.returncode == 0, (done.returncode, done.stderr)
    found = findings_of(done.stdout)
    appended = len(HEAD_LINES) + 1
    extra = {("no-new-comment", "src/untracked.tsx", 2), ("no-new-comment", "src/app.tsx", appended)}
    assert extra <= found, (sorted(found), sorted(extra))
    assert found - extra == EXPECTED, (sorted(found - extra), sorted(EXPECTED))


@case("the comment kind allows headers, doc-above-export and directives, and reads literals as literals")
def _():
    repo = fixture_repo("kinds")
    kinds = (FIXTURE / "kinds.tsx").read_text()
    write(repo, "src/kinds.tsx", kinds)      # untracked: every line is newly introduced
    done = run_cli(repo, "report")
    assert done.returncode == 0, (done.returncode, done.stderr)
    rows = sorted(row for row in findings_of(done.stdout) if row[1] == "src/kinds.tsx")

    def line_of(snippet: str) -> int:
        return next(i for i, l in enumerate(kinds.splitlines(), 1) if snippet in l)

    assert rows == [("no-new-comment", "src/kinds.tsx", line_of("a jsx comment counts")),
                    ("no-new-comment", "src/kinds.tsx", line_of("this one is a real finding"))], rows


@case("--json carries the outcome, the findings and a count per rule")
def _():
    repo = fixture_repo("json")
    done = run_cli(repo, "report", "--json")
    payload = json.loads(done.stdout)
    assert done.returncode == 0, (done.returncode, done.stderr)
    assert sorted(payload) == ["counts", "findings", "outcome", "schema"], sorted(payload)
    assert payload["schema"] == 1 and payload["outcome"] == "findings", payload
    assert payload["counts"] == EXPECTED_COUNTS, payload["counts"]
    assert {(f["rule"], f["path"], f["line"]) for f in payload["findings"]} == EXPECTED
    for finding in payload["findings"]:
        assert sorted(finding) == ["excerpt", "line", "path", "rule"], finding
        assert 0 < len(finding["excerpt"]) <= 80, finding


@case("--paths-from narrows the report to the listed paths")
def _():
    repo = fixture_repo("paths")
    write(repo, "src/untracked.tsx",
          "export const untracked = true;\n// an untracked file's comment is newly introduced\n")
    listing = ROOT / "paths.txt"
    listing.write_text("src/untracked.tsx\n")
    done = run_cli(repo, "report", "--paths-from", str(listing))
    assert done.returncode == 0, (done.returncode, done.stderr)
    assert findings_of(done.stdout) == {("no-new-comment", "src/untracked.tsx", 2)}, done.stdout
    done = run_cli(repo, "report", "--paths-from", str(ROOT / "not-there.txt"))
    assert done.returncode == 2, (done.returncode, done.stdout)


@case("mode=enforce exits 1 on findings and 0 when clean")
def _():
    repo = make_repo("enforce")
    write(repo, ".plumb/project.toml", contract_with(mode="enforce"))
    apply_tree(repo, "base")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "feature")
    apply_tree(repo, "head")
    commit(repo, "head")
    done = run_cli(repo, "report", "--base", "main")
    assert done.returncode == 1, (done.returncode, done.stdout, done.stderr)
    assert findings_of(done.stdout) == EXPECTED, done.stdout

    clean = make_repo("enforce-clean")
    write(clean, ".plumb/project.toml", contract_with(mode="enforce"))
    write(clean, "src/clean.tsx", "export const clean = 1;\n")
    commit(clean, "base")
    git(clean, "checkout", "-q", "-b", "feature")
    write(clean, "src/clean.tsx", "export const clean = 1;\nexport const more = 2;\n")
    commit(clean, "head")
    done = run_cli(clean, "report")
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert done.stdout.strip() == "clean", done.stdout


@case("an exceptions row suppresses its rule in that path, and only there")
def _():
    repo = fixture_repo("exceptions")
    write(repo, ".plumb/project.toml", contract_with('exceptions = ".plumb/code-policy-exceptions.tsv"'))
    shutil.copyfile(FIXTURE / "exceptions" / "exceptions.tsv", repo / ".plumb" / "code-policy-exceptions.tsv")
    done = run_cli(repo, "report")
    assert done.returncode == 0, (done.returncode, done.stderr)
    rows = findings_of(done.stdout)
    assert not any(rule == "no-new-comment" for rule, _, _ in rows), rows
    assert {rule for rule, _, _ in rows} == {"no-new-effect", "no-new-suppression"}, rows
    assert counts_of(done.stdout) == {"no-new-comment": 0, "no-new-effect": 2, "no-new-suppression": 1}


@case("an exceptions row without a reason is invalid, and so is a configured file that is not there")
def _():
    repo = fixture_repo("bad-exceptions")
    write(repo, ".plumb/project.toml", contract_with('exceptions = ".plumb/code-policy-exceptions.tsv"'))
    done = run_cli(repo, "report")
    assert done.returncode == 2 and done.stdout == "", (done.returncode, done.stdout)
    assert "does not exist" in done.stderr, done.stderr
    shutil.copyfile(FIXTURE / "exceptions" / "empty-reason.tsv", repo / ".plumb" / "code-policy-exceptions.tsv")
    done = run_cli(repo, "report")
    assert done.returncode == 2, (done.returncode, done.stdout)
    assert "non-empty reason" in done.stderr, done.stderr


@case("no contract, no [code_policy] table and mode = off are a visible skip with exit 0")
def _():
    repo = make_repo("skip")
    write(repo, "src/a.tsx", "// a comment that is never read\n")
    commit(repo, "base")
    done = run_cli(repo, "report")
    assert done.returncode == 0 and done.stdout.strip() == "skip: no code_policy", done.stdout
    done = run_cli(repo, "report", "--json")
    assert json.loads(done.stdout) == {"schema": 1, "outcome": "skip", "findings": [], "counts": {}}
    write(repo, ".plumb/project.toml", "schema = 1\n")
    done = run_cli(repo, "report")
    assert done.returncode == 0 and done.stdout.strip() == "skip: no code_policy", done.stdout
    write(repo, ".plumb/project.toml", contract_with(mode="off"))
    done = run_cli(repo, "report")
    assert done.returncode == 0 and done.stdout.startswith("skip:"), done.stdout


@case("the default base is origin/HEAD's target when a remote is configured, else main")
def _():
    upstream = make_repo("upstream")
    write(upstream, ".plumb/project.toml", CONTRACT)
    apply_tree(upstream, "base")
    commit(upstream, "base")
    COUNTER[0] += 1
    bare = ROOT / f"origin-bare-{COUNTER[0]}.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(upstream), str(bare)],
                   check=True, capture_output=True)
    work = ROOT / f"origin-work-{COUNTER[0]}"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True, capture_output=True)
    git(work, "checkout", "-q", "-b", "feature")
    apply_tree(work, "head")
    commit(work, "head")
    done = run_cli(work, "report")           # no --base
    assert done.returncode == 0, (done.returncode, done.stderr)
    assert findings_of(done.stdout) == EXPECTED, findings_of(done.stdout)

    alone = make_repo("trunk")
    write(alone, ".plumb/project.toml", CONTRACT)
    write(alone, "src/a.tsx", "export const a = 1;\n")
    commit(alone, "base")
    git(alone, "branch", "-m", "trunk")      # no main and no origin: nothing to diff against
    done = run_cli(alone, "report")
    assert done.returncode == 2, (done.returncode, done.stdout)
    assert "cannot resolve the base main" in done.stderr, done.stderr


# ---------------------------------------------------------------- the contract

@case("plumb-project validates [code_policy] instead of warning on it")
def _():
    repo = make_repo("validation")
    write(repo, ".plumb/project.toml", CONTRACT)
    done = project_cli(repo, "code_policy.mode")
    assert done.returncode == 0 and done.stdout.strip() == "report", (done.returncode, done.stdout, done.stderr)
    assert "unknown key code_policy" not in done.stderr, done.stderr
    done = project_cli(repo, "repo.base_branch")
    assert done.returncode == 0 and done.stderr == "", (done.returncode, done.stderr)
    done = project_cli(repo, "code_policy.rule")
    assert done.returncode == 0 and json.loads(done.stdout)[0]["id"] == "no-new-comment", done.stdout
    # unknown keys inside the table still warn, and never fail
    write(repo, ".plumb/project.toml", contract_with("nonsense = 1"))
    done = project_cli(repo, "code_policy.mode")
    assert done.returncode == 0, (done.returncode, done.stderr)
    assert "warning: unknown key code_policy.nonsense" in done.stderr, done.stderr


@case("a broken [code_policy] is invalid for both readers, and the message names the key")
def _():
    repo = make_repo("invalid")
    broken = [
        ('schema = 1\n[code_policy]\nmode = "loud"\n', "code_policy.mode"),
        ('schema = 1\n[code_policy]\nmode = 3\n', "code_policy.mode"),
        ('schema = 1\n[code_policy]\ninclude = "src"\n', "code_policy.include"),
        ('schema = 1\n[code_policy]\nexclude = ["a", 1]\n', "code_policy.exclude[1]"),
        ('schema = 1\n[code_policy]\nexceptions = 3\n', "code_policy.exceptions"),
        ('schema = 1\n[code_policy]\nallow_directives = "prettier-ignore"\n', "code_policy.allow_directives"),
        ('schema = 1\n[code_policy]\nrule = "x"\n', "code_policy.rule"),
        ('schema = 1\n[code_policy]\nrule = ["x"]\n', "code_policy.rule[0]"),
        ('schema = 1\n[code_policy]\n[[code_policy.rule]]\nid = "a"\n', "code_policy.rule[0].kind"),
        ('schema = 1\n[code_policy]\n[[code_policy.rule]]\nid = ""\nkind = "comment"\n', "code_policy.rule[0].id"),
        ('schema = 1\n[code_policy]\n[[code_policy.rule]]\nid = "a"\nkind = "regex"\n', "code_policy.rule[0].kind"),
        ('schema = 1\n[code_policy]\n[[code_policy.rule]]\nid = "a"\nkind = "pattern"\n', "code_policy.rule[0].pattern"),
        ('schema = 1\n[code_policy]\n[[code_policy.rule]]\nid = "a"\nkind = "pattern"\npattern = "("\n',
         "code_policy.rule[0].pattern"),
        ('schema = 1\n[code_policy]\nmode = "unterminated\n', ".plumb/project.toml"),
    ]
    for text, key in broken:
        write(repo, ".plumb/project.toml", text)
        done = project_cli(repo, "code_policy.mode")
        assert done.returncode == 2, (key, done.returncode, done.stderr)
        assert done.stderr.startswith(f"plumb-project: invalid: {key}"), (key, done.stderr)
        report = run_cli(repo, "report")
        assert report.returncode == 2, (key, report.returncode, report.stderr)
        assert report.stderr.startswith("plumb-code-policy: invalid:"), (key, report.stderr)


@case("a Python without tomllib is unavailable (exit 3), with or without a contract")
def _():
    repo = make_repo("unavailable")
    write(repo, ".plumb/project.toml", CONTRACT)
    done = subprocess.run(
        ["python3", "-c",
         'import os, runpy, sys\n'
         'sys.modules["tomllib"] = None\n'
         'sys.argv = ["plumb-code-policy", "report"]\n'
         f'runpy.run_path({str(SCRIPT)!r}, run_name="__main__")'],
        cwd=str(repo), capture_output=True, text=True, timeout=60)
    assert done.returncode == 3, (done.returncode, done.stdout, done.stderr)
    assert "tomllib" in done.stderr, done.stderr


@case("usage errors and an unreachable contract fail with exit 2")
def _():
    outside = ROOT
    done = run_cli(outside, "report")
    assert done.returncode == 2, (done.returncode, done.stdout)
    assert "git repository" in done.stderr, done.stderr
    repo = make_repo("usage")
    write(repo, ".plumb/project.toml", CONTRACT)
    for args in ((), ("check",), ("report", "--bogus"), ("report", "--base"), ("report", "--paths-from")):
        done = run_cli(repo, *args)
        assert done.returncode == 2, (args, done.returncode, done.stdout, done.stderr)


@case("--help prints usage and exits 0")
def _():
    done = subprocess.run([str(CLI), "--help"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.returncode
    assert done.stdout.startswith("usage: plumb-code-policy"), done.stdout[:60]


if FAILED:
    print(f"  → {len(FAILED)} NG")
    sys.exit(1)
print("  → passed")
