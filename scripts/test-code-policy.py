#!/usr/bin/env python3
"""Regression suite for plumb-code-policy on throwaway git repositories.

    python3 -B scripts/test-code-policy.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline under
tempfile.TemporaryDirectory(): the fixture under scripts/fixtures/code-policy/ is committed into fresh
repositories (the base commit, then the head commit on a feature branch), the contract variants
are written here, and the report runs through bin/plumb-code-policy. No network, no other
checkout is read.
"""
from __future__ import annotations

import errno
import json
import os
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
TEMP = tempfile.TemporaryDirectory(prefix="plumb-code-policy-test-")
ROOT = Path(TEMP.name)
FAILED: list = []
IDENTITY = ["-c", "user.name=selftest", "-c", "user.email=code-policy@users.noreply.github.com",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
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


def policy_repo(name: str, files: dict, contract: str = CONTRACT) -> Path:
    repo = make_repo(name)
    write(repo, ".plumb/project.toml", contract)
    for path, contents in files.items():
        write(repo, path, contents)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "feature")
    return repo


def run_cli(cwd: Path, *args: str):
    return subprocess.run([str(CLI), *args], cwd=str(cwd), capture_output=True, text=True, timeout=300)


def project_cli(cwd: Path, *args: str):
    return subprocess.run([str(PROJECT_CLI), *args], cwd=str(cwd), capture_output=True, text=True, timeout=60)


def run_instrumented(repo: Path, preamble: str, *args: str):
    code = ('import os, runpy, subprocess, sys\n' + preamble + '\n'
            f'sys.argv = {["plumb-code-policy", *args]!r}\n'
            f'runpy.run_path({str(SCRIPT)!r}, run_name="__main__")\n')
    return subprocess.run([sys.executable, "-B", "-c", code], cwd=repo,
                          capture_output=True, text=True, timeout=60)


def json_findings(done, exit_code=0) -> list:
    assert done.returncode == exit_code, (done.returncode, done.stdout, done.stderr)
    return json.loads(done.stdout)["findings"]


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


@case("committed findings use worktree line numbers after uncommitted deletions and reversions")
def _():
    repo = policy_repo("worktree-offset", {
        "src/position.ts": "const a = 1;\nconst b = 2;\n// existing\n",
        "src/reverted.ts": "const original = 0;\n",
    })
    write(repo, "src/position.ts", "const a = 1;\nconst b = 2;\n// introduced\n// existing\n")
    write(repo, "src/reverted.ts", "// gone before the report\n")
    commit(repo, "head")
    write(repo, "src/position.ts", "const b = 2;\n// introduced\n// existing\n")
    write(repo, "src/reverted.ts", "const original = 0;\n")
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert rows == [{"rule": "no-new-comment", "path": "src/position.ts", "line": 2,
                     "excerpt": "// introduced"}], rows


@case("changed paths preserve spaces, quotes, non-ASCII and line delimiters")
def _():
    names = ('src/space and "quote".ts', 'src/space only.ts', 'src/日本語.ts', 'src/tab\tand\nnewline.ts')
    repo = policy_repo("path-bytes", {name: "const original = 0;\n" for name in names})
    git(repo, "config", "core.quotePath", "true")
    for name in names:
        write(repo, name, "const original = 0;\n// added\n")
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert {(row["path"], row["line"], row["excerpt"]) for row in rows} == {
        (name, 2, "// added") for name in names
    }, rows


@case("scope globs match bracket classes within a segment")
def _():
    contract = CONTRACT.replace('["src/**/*.ts", "src/**/*.tsx"]', '["src/**/*.[jt]sx"]')
    contract = contract.replace("**/*.test.*", "**/skip.test.[jt]sx")
    repo = policy_repo("glob-class", {}, contract)
    for name in ("src/keep.jsx", "src/nested/keep.tsx", "src/skip.test.jsx",
                 "src/nested/skip.test.tsx", "src/other.test.tsx", "src/out.css"):
        write(repo, name, "// added\n")
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [row["path"] for row in rows] == [
        "src/keep.jsx", "src/nested/keep.tsx", "src/other.test.tsx",
    ], rows


@case("terminal globstar spans paths with newline bytes")
def _():
    contract = CONTRACT.replace('["src/**/*.ts", "src/**/*.tsx"]', '["src/**"]')
    names = ("src/line\nbreak.ts", "src/sub\ndir/regular.ts", "src2/out.ts")
    repo = policy_repo("globstar", {name: "old\n" for name in names}, contract)
    for name in names:
        write(repo, name, "// added\n")
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [row["path"] for row in rows] == list(names[:2]), rows


@case("binary and -diff attributes still produce tracked findings")
def _():
    repo = policy_repo("binary-attributes", {"src/a.ts": "old\n"}, contract_with(mode="enforce"))
    write(repo, "src/a.ts", "const data = 1;\n// added\n")
    for attrs in ("*.ts binary", "*.ts -diff"):
        write(repo, ".gitattributes", attrs + "\n")
        rows = json_findings(run_cli(repo, "report", "--json"), exit_code=1)
        assert rows == [{"rule": "no-new-comment", "path": "src/a.ts", "line": 2,
                         "excerpt": "// added"}], (attrs, rows)


@case("tracked rules use patch text after Git converts the worktree encoding")
def _():
    repo = policy_repo("worktree-encoding", {})
    write(repo, ".gitattributes", "*.ts working-tree-encoding=UTF-16LE\n")
    (repo / "src").mkdir()
    path = repo / "src" / "a.ts"
    path.write_bytes("const old = 0;\n".encode("utf-16-le"))
    commit(repo, "encoded base")
    git(repo, "branch", "-f", "main", "HEAD")
    path.write_bytes("const old = 0;\n// added\n".encode("utf-16-le"))
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert rows == [{"rule": "no-new-comment", "path": "src/a.ts", "line": 2,
                     "excerpt": "// added"}], rows


@case("tracked findings retain the patch line and excerpt after a worktree edit")
def _():
    repo = policy_repo("patch-snapshot", {"src/a.ts": "old\n"})
    write(repo, "src/a.ts", "const a = 1;\n// captured\n")
    done = run_instrumented(repo, '''
from pathlib import Path
run = subprocess.run
path = Path("src/a.ts")
def edit_after_diff(command, *args, **kwargs):
    result = run(command, *args, **kwargs)
    if command[0] == "git" and "--patch" in command:
        path.write_text("// shifted\\nconst a = 1;\\n// captured\\n")
    return result
subprocess.run = edit_after_diff

import builtins
def guard(original):
    def reject_reopen(source, *args, **kwargs):
        if not isinstance(source, int) and Path(os.fsdecode(source)).resolve() == path.resolve():
            raise AssertionError("tracked source was opened a second time")
        return original(source, *args, **kwargs)
    return reject_reopen
os.open = guard(os.open)
builtins.open = guard(builtins.open)
''', "report", "--json")
    rows = json_findings(done)
    assert rows == [{"rule": "no-new-comment", "path": "src/a.ts", "line": 2,
                     "excerpt": "// captured"}], rows


@case("hunk counts keep header-like source lines in their own file")
def _():
    repo = policy_repo("hunk-counts", {"src/a.ts": "const a = 1;\nold\nconst b = 2;\n",
                                       "src/z.ts": "const z = 1;\n"})
    write(repo, "src/a.ts", "const a = 1;\n++ counter\n// after fake file header\nconst b = 2;\n// after second hunk")
    write(repo, "src/z.ts", "const z = 1;\n// in next file\n")
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [(row["path"], row["line"]) for row in rows] == [
        ("src/a.ts", 3), ("src/a.ts", 5), ("src/z.ts", 2)
    ], rows


@case("an incomplete hunk exits 2 instead of returning a partial scan")
def _():
    repo = policy_repo("truncated-patch", {"src/a.ts": "old\n"})
    write(repo, "src/a.ts", "// first\n// second\n")
    done = run_instrumented(repo, '''
run = subprocess.run
def truncate_patch(command, *args, **kwargs):
    result = run(command, *args, **kwargs)
    if command[0] == "git" and "--patch" in command:
        marker = b"+// second\\n"
        assert result.stdout.endswith(marker), result.stdout
        result.stdout = result.stdout[:-len(marker)]
    return result
subprocess.run = truncate_patch
''', "report", "--json")
    assert (done.returncode, done.stdout) == (2, ""), (done.returncode, done.stdout, done.stderr)
    assert "Git diff" in done.stderr, done.stderr


@case("a pure rename adds no finding and an edited rename adds only its new line")
def _():
    kept = "// existing\n" + "\n".join(f"const item{i} = {i};" for i in range(20)) + "\n"
    repo = policy_repo("renames", {"src/pure.ts": kept, "src/edit.ts": kept.replace("item", "other")})
    git(repo, "config", "diff.renames", "false")
    git(repo, "mv", "src/pure.ts", "src/pure renamed.ts")
    git(repo, "mv", "src/edit.ts", 'src/edited "rename".ts')
    write(repo, 'src/edited "rename".ts', kept.replace("item", "other") + "// added\n")
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [(row["path"], row["line"], row["excerpt"]) for row in rows] == [
        ('src/edited "rename".ts', 22, "// added")
    ], rows


@case("only regular files are scanned and symlinks and gitlinks are listed")
def _():
    repo = policy_repo("file-types", {"src/regular-to-link.ts": "old\n", "src/deleted.ts": "// deleted\n"})
    outside = ROOT / "outside.ts"
    outside.write_text("// outside contents\n")
    (repo / "src/link-to-regular.ts").symlink_to(outside)
    (repo / "src/tracked-link.ts").symlink_to("old-target")
    commit(repo, "add symlinks")
    git(repo, "branch", "-f", "main", "HEAD")
    (repo / "src/deleted.ts").unlink()
    for name in ("regular-to-link.ts", "tracked-link.ts"):
        path = repo / "src" / name
        path.unlink()
        path.symlink_to(outside)
    (repo / "src/untracked-link.ts").symlink_to(outside)
    (repo / "src/link-to-regular.ts").unlink()
    write(repo, "src/link-to-regular.ts", "// new regular contents\n")
    target = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{target},src/module.ts")
    (repo / "src/module.ts").mkdir()
    embedded = repo / "src/embedded.ts"
    embedded.mkdir()
    git(embedded, "init", "-q")
    done = run_cli(repo, "report", "--json")
    rows = json_findings(done)
    assert [(row["path"], row["excerpt"]) for row in rows] == [
        ("src/link-to-regular.ts", "// new regular contents")
    ], rows
    assert set(done.stderr.splitlines()) == {
        "skip: symlink 'src/regular-to-link.ts'", "skip: symlink 'src/tracked-link.ts'",
        "skip: symlink 'src/untracked-link.ts'", "skip: gitlink 'src/module.ts'",
        "skip: non-regular file 'src/embedded.ts'",
    }, done.stderr


@case("enforce reports non-regular paths and honors rule-specific exceptions")
def _():
    exceptions = ".plumb/code-policy-exceptions.tsv"
    contract = contract_with(f'exceptions = "{exceptions}"', mode="enforce")
    repo = policy_repo("non-regular", {"src/normal.ts": "old\n"}, contract)
    (repo / "src" / "link.ts").symlink_to("normal.ts")
    git(repo, "add", "src/link.ts")
    git(repo, "config", "core.symlinks", "false")
    (repo / "src" / "link.ts").unlink()
    write(repo, "src/link.ts", "normal.ts")
    (repo / "src" / "new-link.ts").symlink_to("normal.ts")
    (repo / "tools").mkdir()
    (repo / "tools" / "out.ts").symlink_to("outside")
    target = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{target},src/module.ts")
    (repo / "src" / "module.ts").mkdir()
    embedded = repo / "src" / "embedded.ts"
    embedded.mkdir()
    git(embedded, "init", "-q")
    write(repo, exceptions, "no-new-comment\tsrc/link.ts\tDifferent rule\n")

    done = run_cli(repo, "report", "--json")
    rows = json_findings(done, exit_code=1)
    expected = [
        {"rule": "non-regular", "path": f"src/{name}", "line": 0, "excerpt": kind}
        for name, kind in (("embedded.ts", "non-regular file"), ("link.ts", "symlink"),
                           ("module.ts", "gitlink"), ("new-link.ts", "symlink"))
    ]
    assert rows == expected, rows
    assert json.loads(done.stdout)["counts"] == {rule: 0 for rule in EXPECTED_COUNTS} | {"non-regular": 4}
    assert done.stderr == "", done.stderr
    text_report = run_cli(repo, "report")
    assert text_report.returncode == 1, (text_report.returncode, text_report.stdout, text_report.stderr)
    assert "summary: non-regular 4" in text_report.stdout.splitlines(), text_report.stdout

    write(repo, exceptions, "non-regular\tsrc/link.ts\tApproved symlink\n")
    rows = json_findings(run_cli(repo, "report", "--json"), exit_code=1)
    assert rows == [row for row in expected if row["path"] != "src/link.ts"], rows

    write(repo, exceptions, "".join(f"non-regular\t{row['path']}\tApproved path\n" for row in expected))
    assert json_findings(run_cli(repo, "report", "--json")) == []


@case("benign stderr stays visible while Git output is scanned")
def _():
    repo = policy_repo("git-diagnostics", {"src/a.ts": "old\n"}, contract_with(mode="enforce"))
    write(repo, "src/a.ts", "// added\n")
    done = run_instrumented(repo, '''
run = subprocess.run
def with_warning(command, *args, **kwargs):
    result = run(command, *args, **kwargs)
    if command[0] == "git":
        result.stderr += f"warning: benign diagnostic from {command[1]}\\n".encode()
    return result
subprocess.run = with_warning
''', "report", "--json")
    rows = json_findings(done, exit_code=1)
    assert rows == [{"rule": "no-new-comment", "path": "src/a.ts", "line": 1, "excerpt": "// added"}], rows
    assert done.stderr.splitlines() == [
        f"warning: benign diagnostic from {command}"
        for command in ("rev-parse", "rev-parse", "merge-base", "-c", "ls-files")
    ], done.stderr


@case("an untracked enumeration failure cannot produce a clean report")
def _():
    repo = policy_repo("enumeration-error", {}, contract_with(mode="enforce"))
    for exit_code, diagnostic in ((2, b"warning: could not open directory"),
                                  (0, b"warning: could not open directory"),
                                  (0, b"warning: unable to access 'src/.gitignore'"),
                                  (128, b"fatal: fixture enumeration failed")):
        done = run_instrumented(repo, f'''
run = subprocess.run
def fail_untracked(command, *args, **kwargs):
    if command[:2] == ["git", "ls-files"]:
        return subprocess.CompletedProcess(command, {exit_code}, b"", {diagnostic!r})
    return run(command, *args, **kwargs)
subprocess.run = fail_untracked
''', "report", "--json")
        assert (done.returncode, done.stdout) == (2, ""), (exit_code, done.returncode, done.stdout, done.stderr)
        assert "untracked" in done.stderr, done.stderr
        assert diagnostic.decode() in done.stderr, done.stderr


@case("lstat or read failures in tracked and untracked files exit 2 after scope filtering")
def _():
    repo = policy_repo("read-error", {"src/tracked.ts": "const old = 0;\n"}, contract_with(mode="enforce"))
    write(repo, "src/tracked.ts", "// tracked\n")
    write(repo, "src/untracked.ts", "// untracked\n")
    write(repo, "tools/untracked.ts", "// out of scope\n")
    for api in ("lstat", "open"):
        for path in ("src/tracked.ts", "src/untracked.ts", "tools/untracked.ts"):
            done = run_instrumented(repo, f'''
import builtins
blocked = os.fsencode(os.path.abspath({path!r}))
run = subprocess.run
def deny_git_read(command, *args, **kwargs):
    if {api!r} == "open" and {path!r} == "src/tracked.ts" and command[0] == "git" and "--patch" in command:
        return subprocess.CompletedProcess(command, 128, b"", b"error: src/tracked.ts: fixture denied access")
    return run(command, *args, **kwargs)
subprocess.run = deny_git_read
def guard(original):
    def deny(path, *args, **kwargs):
        if not isinstance(path, int) and os.fsencode(path) == blocked:
            raise PermissionError("fixture denied access")
        return original(path, *args, **kwargs)
    return deny
os.{api} = guard(os.{api})
if {api!r} == "open":
    builtins.open = guard(builtins.open)
''', "report", "--json")
            if path.startswith("src/"):
                assert (done.returncode, done.stdout) == (2, ""), (api, path, done.returncode, done.stdout, done.stderr)
                assert path in done.stderr, done.stderr
            else:
                assert len(json_findings(done, exit_code=1)) == 2, done.stdout


@case("Git output stays in bytes and only in-scope source is decoded")
def _():
    repo = policy_repo("source-encoding", {"src/a.ts": "old\n", "tools/bytes.txt": "old\n"})
    (repo / "tools/bytes.txt").write_bytes(b"outside \xff\n")
    (repo / "src/a.ts").write_bytes(b"// inside \xff\n")
    # Some filesystems reject undecodable path bytes. Where supported, cover them too.
    raw_path = b"src/name-\xff.ts"
    try:
        with open(os.fsencode(repo) + b"/" + raw_path, "wb") as handle:
            handle.write(b"// raw name\n")
    except OSError as error:
        if error.errno not in (errno.EINVAL, errno.EILSEQ, errno.EPERM):
            raise
        expected = []
    else:
        expected = [(os.fsdecode(raw_path), "// raw name")]
        git(repo, "add", "--", os.fsdecode(raw_path))
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [(row["path"], row["excerpt"]) for row in rows] == [("src/a.ts", "// inside �"), *expected], rows


@case("source line numbers use LF and strip CR only in CRLF")
def _():
    contract = CONTRACT + '[[code_policy.rule]]\nid = "end-anchor"\nkind = "pattern"\npattern = "END$"\n'
    repo = policy_repo("physical-lines", {"src/a.ts": "old\n"}, contract)
    (repo / "src/a.ts").write_bytes('const s = "a\u2028b // still quoted";\r\n// second\r\nEND\r\n'.encode())
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [(row["rule"], row["line"], row["excerpt"]) for row in rows] == [
        ("no-new-comment", 2, "// second"), ("end-anchor", 3, "END")
    ], rows


@case("tracked and untracked source retain a bare CR at end of file and scan after NUL")
def _():
    contract = CONTRACT + '[[code_policy.rule]]\nid = "bare-cr"\nkind = "pattern"\npattern = \'END\\r$\'\n'
    repo = policy_repo("bare-cr", {"src/tracked.ts": "old\n"}, contract)
    for path in ("src/tracked.ts", "src/untracked.ts"):
        (repo / path).write_bytes(b'const data = "\0";\n// second\nEND\r')
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [(row["path"], row["rule"], row["line"]) for row in rows] == [
        (path, rule, line)
        for path in ("src/tracked.ts", "src/untracked.ts")
        for rule, line in (("no-new-comment", 2), ("bare-cr", 3))
    ], rows


@case("the comment scan is line-local and only standalone directives are allowed")
def _():
    repo = fixture_repo("kinds")
    kinds = (FIXTURE / "kinds.tsx").read_text()
    write(repo, "src/kinds.tsx", kinds)      # untracked: every line is newly introduced
    done = run_cli(repo, "report")
    assert done.returncode == 0, (done.returncode, done.stderr)
    rows = sorted(row for row in findings_of(done.stdout) if row[1] == "src/kinds.tsx")

    def line_of(snippet: str) -> int:
        return next(i for i, l in enumerate(kinds.splitlines(), 1) if snippet in l)

    expected = ("SPDX-License-Identifier", "ordinary leading comment", "/**", "ordinary note", "a jsx comment counts",
                "this one is a real finding", "inline directive", "unfinished //",
                "template continuation //", "// inside regex")
    assert rows == sorted(("no-new-comment", "src/kinds.tsx", line_of(snippet)) for snippet in expected), rows
    write(repo, "src/shebang.ts", "#!/usr/bin/env -S tool https://example.invalid\n")
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [(row["line"], row["rule"]) for row in rows if row["path"] == "src/shebang.ts"] == [
        (1, "no-new-comment")
    ], rows


@case("an unfinished block at EOF has no extra physical line")
def _():
    pattern_only = (CONTRACT.split("[[code_policy.rule]]", 1)[0]
                    + '[[code_policy.rule]]\nid = "block-start"\nkind = "pattern"\npattern = "unfinished"\n')
    repo = policy_repo("unterminated-block", {"src/a.ts": "const x = 0;\n"}, pattern_only)
    for ending in ("", "\n"):
        write(repo, "src/a.ts", f"const x = 0;\n/* unfinished{ending}")
        rows = json_findings(run_cli(repo, "report", "--json"))
        assert [(row["rule"], row["line"], row["excerpt"]) for row in rows] == [
            ("block-start", 2, "/* unfinished")
        ], rows


@case("the default directive includes standalone JSX and an empty list disables it")
def _():
    repo = policy_repo("directives", {})
    write(repo, "src/a.tsx", "// prettier-ignore\n/* prettier-ignore */\n  {/* prettier-ignore */}\n"
                             "doWork(); // prettier-ignore\n/* prettier-ignore */ /* more */\n")
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [row["line"] for row in rows] == [4, 5], rows
    write(repo, ".plumb/project.toml", contract_with("allow_directives = []"))
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [row["line"] for row in rows] == [1, 2, 3, 4, 5], rows


@case("the documented effect pattern has the same boundaries when the checker runs it")
def _():
    docs = (PLUGIN / "docs" / "project-contract.md").read_text()
    example = re.search(r"(?m)^pattern = ('[^']+')$", docs)
    assert example, "the contract example must include an effect pattern"
    examples = re.findall(r"(?m)^\| `([^`]+)`[^|]*\| (yes|no) \|$", docs)
    assert examples, "the effect pattern must have runnable examples"
    contract = ('schema = 1\n[code_policy]\n[[code_policy.rule]]\nid = "no-new-effect"\n'
                f'kind = "pattern"\npattern = {example[1]}\n')
    repo = policy_repo("documented-pattern", {}, contract)
    write(repo, "src/examples.ts", "\n".join(line for line, _ in examples) + "\n")
    rows = json_findings(run_cli(repo, "report", "--json"))
    assert [(row["line"], row["excerpt"]) for row in rows] == [
        (number, line) for number, (line, matched) in enumerate(examples, 1) if matched == "yes"
    ], rows


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
    assert done.stdout.splitlines() == ["clean", "summary: no-new-comment 0",
                                       "summary: no-new-effect 0", "summary: no-new-suppression 0"], done.stdout


@case("an exceptions row suppresses its rule in that path, and only there")
def _():
    repo = fixture_repo("exceptions")
    write(repo, ".plumb/project.toml", contract_with('exceptions = ".plumb/code-policy-exceptions.tsv"'))
    shutil.copyfile(FIXTURE / "exceptions" / "exceptions.tsv", repo / ".plumb" / "code-policy-exceptions.tsv")
    write(repo, "src/other.ts", "const value = 0;\n// still report this path\n")
    done = run_cli(repo, "report")
    assert done.returncode == 0, (done.returncode, done.stderr)
    rows = findings_of(done.stdout)
    expected = {row for row in EXPECTED if row[0] != "no-new-comment"}
    assert rows == expected | {("no-new-comment", "src/other.ts", 2)}, rows
    assert counts_of(done.stdout) == {"no-new-comment": 1, "no-new-effect": 2, "no-new-suppression": 1}


@case("an exceptions row without a reason is invalid, and so is a configured file that is not there")
def _():
    repo = fixture_repo("bad-exceptions")
    write(repo, ".plumb/project.toml", contract_with('exceptions = ".plumb/code-policy-exceptions.tsv"'))
    done = run_cli(repo, "report")
    assert done.returncode == 2 and done.stdout == "", (done.returncode, done.stdout)
    assert "does not exist" in done.stderr, done.stderr
    empty_reason = (FIXTURE / "exceptions" / "empty-reason.tsv").read_text()
    for row in (empty_reason, "\n\t\t\n"):
        write(repo, ".plumb/code-policy-exceptions.tsv", row)
        done = run_cli(repo, "report")
        assert (done.returncode, done.stdout) == (2, ""), (repr(row), done.returncode, done.stdout)
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
    work = make_repo("remote-default")
    write(work, ".plumb/project.toml", CONTRACT)
    write(work, "src/a.ts", "const a = 1;\n")
    commit(work, "base")
    git(work, "checkout", "-q", "-b", "release")
    write(work, "src/a.ts", "const a = 1;\n// on the remote default branch\n")
    commit(work, "release")
    git(work, "update-ref", "refs/remotes/origin/release", "HEAD")
    git(work, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/release")
    git(work, "checkout", "-q", "main")
    write(work, "src/main-only.ts", "const main = 1;\n")
    commit(work, "advance main independently")
    git(work, "checkout", "-q", "-b", "feature", "release")
    write(work, "src/feature.ts", "// on feature\n")
    commit(work, "feature")
    for flags, expected in (((), {("no-new-comment", "src/feature.ts", 1)}),
                            (("--base", "main"), {("no-new-comment", "src/feature.ts", 1),
                                                  ("no-new-comment", "src/a.ts", 2)})):
        done = run_cli(work, "report", *flags)
        assert done.returncode == 0, (done.returncode, done.stderr)
        assert findings_of(done.stdout) == expected, (flags, done.stdout)

    alone = make_repo("trunk")
    write(alone, ".plumb/project.toml", CONTRACT)
    write(alone, "src/a.tsx", "export const a = 1;\n")
    commit(alone, "base")
    git(alone, "branch", "-m", "trunk")      # no main and no origin: nothing to diff against
    done = run_cli(alone, "report")
    assert done.returncode == 2, (done.returncode, done.stdout)
    assert "cannot resolve the base main" in done.stderr, done.stderr


@case("--worktree scans proposed changes with the trusted contract and exceptions")
def _():
    trusted = make_repo("trusted")
    exceptions = ".plumb/code-policy-exceptions.tsv"
    write(trusted, ".plumb/project.toml", contract_with(f'exceptions = "{exceptions}"', mode="enforce"))
    write(trusted, exceptions, "no-new-comment\tsrc/allowed.ts\ttrusted reason\n")
    commit(trusted, "trusted base")
    proposed = ROOT / "proposed"
    git(ROOT, "clone", "-q", "--local", str(trusted), str(proposed))
    git(proposed, "checkout", "-q", "-b", "feature")
    write(proposed, ".plumb/project.toml", contract_with(mode="off"))
    write(proposed, exceptions, "no-new-comment\tsrc/blocked.ts\tproposed exception\n")
    write(proposed, "src/blocked.ts", "// blocked\n")
    write(proposed, "src/allowed.ts", "// allowed\n")
    commit(proposed, "proposed policy changes")
    assert run_cli(proposed, "report").stdout.strip() == "skip: code_policy mode is off"
    rows = json_findings(run_cli(trusted, "report", "--base", "main", "--worktree", str(proposed), "--json"), 1)
    assert rows == [{"rule": "no-new-comment", "path": "src/blocked.ts", "line": 1,
                     "excerpt": "// blocked"}], rows


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


@case("a misspelled rules key warns through both readers without a rule array")
def _():
    repo = policy_repo("misspelled-rules", {}, 'schema = 1\n[code_policy]\nrules = []\n')
    for done in (project_cli(repo, "code_policy"), run_cli(repo, "report")):
        assert done.returncode == 0, (done.returncode, done.stderr)
        assert "warning: unknown key code_policy.rules" in done.stderr, done.stderr


@case("both readers preserve line separators in the checkout path")
def _():
    for leaf in ("checkout\nsegment", "checkout\u2028segment", "checkout\rsegment", "checkout-ending-lf\n"):
        repo = policy_repo("contract-path", {})
        repo = repo.rename(ROOT / leaf)
        write(repo, "src/a.ts", "// added\n")
        done = project_cli(repo, "code_policy.mode")
        assert (done.returncode, done.stdout) == (0, "report\n"), (leaf, done.returncode, done.stdout, done.stderr)
        rows = json_findings(run_cli(repo, "report", "--json"))
        assert [row["path"] for row in rows] == ["src/a.ts"], (leaf, rows)

        write(repo, ".plumb/project.toml", 'schema = 1\n[code_policy]\nmode = "loud"\n')
        for done in (project_cli(repo, "code_policy.mode"), run_cli(repo, "report", "--json")):
            assert (done.returncode, done.stdout) == (2, ""), (leaf, done.returncode, done.stdout, done.stderr)
            assert "code_policy.mode" in done.stderr, (leaf, done.stderr)


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


@case("duplicate or reserved IDs and regex overflow are invalid for both readers")
def _():
    repo = policy_repo("invalid-rules", {})
    for suffix, key, reason in (
        ('id = "no-new-comment"\nkind = "comment"\n', "code_policy.rule[3].id", "no-new-comment"),
        ('id = "non-regular"\nkind = "comment"\n', "code_policy.rule[3].id", "reserved"),
        ('id = "overflow"\nkind = "pattern"\npattern = "a{5000000000}"\n',
         "code_policy.rule[3].pattern", "regular expression"),
    ):
        write(repo, ".plumb/project.toml", CONTRACT + "\n[[code_policy.rule]]\n" + suffix)
        for done in (project_cli(repo, "code_policy.mode"), run_cli(repo, "report")):
            assert (done.returncode, done.stdout) == (2, ""), (key, done.returncode, done.stdout, done.stderr)
            assert key in done.stderr and reason in done.stderr, (key, done.stderr)


@case("a Python without tomllib is unavailable (exit 3), with or without a contract")
def _():
    repo = make_repo("unavailable")
    for has_contract in (True, False):
        if has_contract:
            write(repo, ".plumb/project.toml", CONTRACT)
        else:
            (repo / ".plumb/project.toml").unlink()
        done = run_instrumented(repo, 'sys.modules["tomllib"] = None', "report")
        assert (done.returncode, done.stdout) == (3, ""), (has_contract, done.returncode, done.stdout, done.stderr)
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
