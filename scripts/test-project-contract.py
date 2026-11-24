#!/usr/bin/env python3
"""Regression suite for the `repo.production_branches` key and the `code_policy.rule` kinds of the project contract.

    python3 -B scripts/test-project-contract.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Each case writes a contract into a temporary
git repository and runs `bin/plumb-project` there. Needs Python 3.11+ (tomllib); without it the suite
prints `skip` and exits 0, as the other contract cases do.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
BIN = PLUGIN / "bin" / "plumb-project"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-project-contract-test-"))
REPO = ROOT / "repo"
FAILED: list = []


def run(*args: str) -> tuple:
    done = subprocess.run([str(BIN), *args], cwd=REPO, capture_output=True, text=True)
    return done.returncode, done.stdout.rstrip("\n"), done.stderr.rstrip("\n")


def write(body: str) -> None:
    (REPO / ".plumb").mkdir(exist_ok=True)
    (REPO / ".plumb" / "project.toml").write_text("schema = 1\n" + body + "\n", encoding="utf-8")


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {name}")
    else:
        print(f"  NG   {name}: {detail}")
        FAILED.append(name)


def main() -> int:
    try:
        import tomllib  # noqa: F401
    except ImportError:
        print("skip: this python3 has no tomllib")
        return 0
    REPO.mkdir()
    subprocess.run(["git", "init", "-q", str(REPO)], check=True)

    write('[repo]\nproduction_branches = ["main", "release/1.x"]')
    code, out, err = run("repo.production_branches")
    check("a list of branch names prints one per line", (code, out, err) == (0, "main\nrelease/1.x", ""), repr((code, out, err)))
    code, out, err = run("--json", "repo.production_branches")
    answer = json.loads(out) if out else {}
    check("--json carries the list", answer.get("outcome") == "set" and answer.get("value") == ["main", "release/1.x"], out)
    code, out, err = run("--json")
    check("--json without a key carries it in the whole contract",
          json.loads(out)["value"]["repo"]["production_branches"] == ["main", "release/1.x"], out)
    code, out, err = run("--enforce", "repo.production_branches")
    check("--enforce returns the list", (code, out) == (0, "main\nrelease/1.x"), repr((code, out)))
    code, out, err = run("repo.base_branch")
    check("the key is not reported as unknown and does not disturb its sibling", (code, out, err) == (0, "", ""), repr((code, out, err)))

    write('[repo]\nbase_branch = "develop"')
    code, out, err = run("repo.production_branches")
    check("absent key prints nothing and exits 0", (code, out, err) == (0, "", ""), repr((code, out, err)))
    code, out, err = run("--json", "repo.production_branches")
    answer = json.loads(out)
    check("--json for an absent key is absent", answer["outcome"] == "absent" and answer["value"] is None, out)

    write('[repo]\nproduction_branches = []')
    code, out, err = run("--json", "repo.production_branches")
    answer = json.loads(out)
    check("an empty list is valid and set (no branch is production)", (code, answer["outcome"], answer["value"]) == (0, "set", []), out)
    code, out, err = run("repo.production_branches")
    check("an empty list prints nothing in the plain form", (code, out, err) == (0, "", ""), repr((code, out, err)))

    for label, body, key in (
        ("a string instead of an array", '[repo]\nproduction_branches = "main"', "repo.production_branches"),
        ("a number instead of an array", '[repo]\nproduction_branches = 3', "repo.production_branches"),
        ("a table instead of an array", '[repo]\nproduction_branches = { a = "b" }', "repo.production_branches"),
        ("a non-string element", '[repo]\nproduction_branches = ["main", 1]', "repo.production_branches[1]"),
        ("an empty string element", '[repo]\nproduction_branches = ["main", ""]', "repo.production_branches[1]"),
        ("an empty first element", '[repo]\nproduction_branches = [""]', "repo.production_branches[0]"),
    ):
        write(body)
        code, out, err = run("repo.base_branch")
        check(f"{label} is invalid and names {key}",
              code == 2 and out == "" and err.startswith(f"plumb-project: invalid: {key}: "), repr((code, out, err)))

    write('[repo]\nproduction_branches = ["main"]\nweird = 1')
    code, out, err = run("repo.production_branches")
    check("other unknown repo keys still warn, and this one does not",
          code == 0 and out == "main" and "warning: unknown key repo.weird" in err and "production_branches" not in err, repr((code, out, err)))

    def rule(body: str) -> str:
        return f'[code_policy]\nmode = "report"\n[[code_policy.rule]]\nid = "r"\n{body}'

    for label, body in (
        ("comment-block with min_lines 4", 'kind = "comment-block"\nmin_lines = 4'),
        ("comment-block with min_lines 2", 'kind = "comment-block"\nmin_lines = 2'),
        ("commented-code without keys", 'kind = "commented-code"'),
    ):
        write(rule(body))
        code, out, err = run("code_policy.mode")
        check(f"{label} is valid and warns about nothing", (code, out, err) == (0, "report", ""), repr((code, out, err)))

    for label, body, key in (
        ("comment-block without min_lines", 'kind = "comment-block"', "code_policy.rule[0].min_lines"),
        ("min_lines 1", 'kind = "comment-block"\nmin_lines = 1', "code_policy.rule[0].min_lines"),
        ("min_lines 0", 'kind = "comment-block"\nmin_lines = 0', "code_policy.rule[0].min_lines"),
        ("a boolean min_lines", 'kind = "comment-block"\nmin_lines = true', "code_policy.rule[0].min_lines"),
        ("a string min_lines", 'kind = "comment-block"\nmin_lines = "4"', "code_policy.rule[0].min_lines"),
        ("a float min_lines", 'kind = "comment-block"\nmin_lines = 4.0', "code_policy.rule[0].min_lines"),
        ("an unknown kind", 'kind = "comment-blocks"', "code_policy.rule[0].kind"),
    ):
        write(rule(body))
        code, out, err = run("code_policy.mode")
        check(f"{label} is invalid and names {key}",
              code == 2 and out == "" and err.startswith(f"plumb-project: invalid: {key}: "), repr((code, out, err)))

    for kind in ('comment', 'commented-code'):
        write(rule(f'kind = "{kind}"\nmin_lines = 4'))
        code, out, err = run("code_policy.mode")
        check(f"min_lines on a {kind} rule is only a warning",
              code == 0 and out == "report" and "warning: unknown key code_policy.rule[0].min_lines" in err, repr((code, out, err)))
    write(rule('kind = "pattern"\npattern = "x"\nmin_lines = 4'))
    code, out, err = run("code_policy.mode")
    check("min_lines on a pattern rule is only a warning",
          code == 0 and "warning: unknown key code_policy.rule[0].min_lines" in err, repr((code, out, err)))

    shutil.rmtree(ROOT, ignore_errors=True)
    print(f"{len(FAILED)} NG" if FAILED else "all ok")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
