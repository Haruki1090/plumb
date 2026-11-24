#!/usr/bin/env python3
"""Regression suite for `plumb-enforcement`, on synthetic trees under a temporary directory.

    python3 -B scripts/test-enforcement.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Each case builds a small tree (a check-harness
script with numbered rules, a hooks file, a bin/ command, a Markdown file) and a table, then runs the real
`scripts/enforcement.py` over it. The last case runs it over this checkout's own table.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
TOOL = HERE / "enforcement.py"
WRAPPER = PLUGIN / "bin" / "plumb-enforcement"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-enforcement-test-"))
FAILED: list[str] = []
_counter = [0]

HEADER = "rule\tstated_in\tmechanism\tenforced_by"
GOOD = [
    ("Body text names no model slug.", "docs/doc.md#Second heading", "check", "check-harness rule 1"),
    ("Doctor fails on an orphan.", "docs/doc.md", "check", "scripts/doc.sh"),
    ("A finished session reaches the ledger.", "docs/doc.md#First heading", "hook", "hook Stop"),
    ("A delegate reads the worker rules first.", "docs/doc.md", "hook", "hook PreToolUse:Agent"),
    ("A state is read as one word.", "docs/doc.md", "command", "plumb-watch --json"),
    ("A claim is marked measured or guessed.", "docs/doc.md", "prose", "-"),
    ("A gap is never counted as a pass.", "docs/doc.md#Second heading", "prose", "-"),
]


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


def make_tree(rows: list[tuple[str, ...]] | None = None, *, header: str = HEADER, raw: list[str] | None = None,
              table: bool = True) -> Path:
    _counter[0] += 1
    root = ROOT / f"tree{_counter[0]}"
    for sub in ("docs", "scripts", "bin", "hooks"):
        (root / sub).mkdir(parents=True)
    (root / "docs" / "doc.md").write_text("# Title\n\n## First heading\n\ntext\n\n### Second heading\n\ntext\n")
    (root / "scripts" / "doc.sh").write_text("#!/bin/sh\n")
    (root / "scripts" / "check-harness.sh").write_text("# 0. first\n# 1. second\n# 7b. a sub-rule\nnot a rule\n")
    (root / "bin" / "plumb-watch").write_text("#!/bin/sh\n")
    (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "true"}]}],
        "PreToolUse": [{"matcher": "Agent", "hooks": [{"type": "command", "command": "true"}]}],
    }}))
    if table:
        lines = [header]
        lines += ["\t".join(row) for row in (GOOD if rows is None else rows)]
        lines += raw or []
        (root / "docs" / "enforcement.tsv").write_text("\n".join(lines) + "\n")
    return root


def run(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(TOOL), "--root", str(root), *flags],
                          capture_output=True, text=True)


def problems_of(root: Path) -> list[str]:
    done = run(root, "--check")
    assert done.stderr == "", done.stderr
    return [line for line in done.stdout.splitlines() if line]


def expect_problem(root: Path, fragment: str) -> None:
    found = problems_of(root)
    assert any(fragment in line for line in found), f"no problem containing {fragment!r} in {found}"
    assert run(root, "--check").returncode == 1


def good_with(row: tuple[str, ...]) -> Path:
    return make_tree(GOOD + [row])


@case("a valid table has no problems and exits 0 under --check")
def _():
    root = make_tree()
    done = run(root, "--check")
    assert (done.returncode, done.stdout) == (0, ""), (done.returncode, done.stdout)


@case("the summary line counts each mechanism")
def _():
    done = run(make_tree())
    assert done.returncode == 0, done
    first = done.stdout.splitlines()[0]
    assert first == "enforcement: 7 rules: check 2, hook 2, command 1, prose 2", first


@case("without --check the prose rows follow the summary as tab-separated lines")
def _():
    lines = run(make_tree()).stdout.splitlines()
    assert lines[1:] == [
        "prose\tdocs/doc.md\tA claim is marked measured or guessed.",
        "prose\tdocs/doc.md#Second heading\tA gap is never counted as a pass.",
    ], lines


@case("--json prints the table, the counts and no problems")
def _():
    done = run(make_tree(), "--json")
    data = json.loads(done.stdout)
    assert done.returncode == 0 and data["problems"] == [], done.stdout
    assert data["total"] == 7 and data["counts"] == {"check": 2, "hook": 2, "command": 1, "prose": 2}, data
    assert data["rules"][0] == {"rule": GOOD[0][0], "stated_in": GOOD[0][1], "mechanism": "check",
                                "enforced_by": "check-harness rule 1"}, data["rules"][0]


@case("--json carries a problem and exits 1")
def _():
    done = run(good_with(("Odd.", "docs/doc.md", "wish", "-")), "--json")
    data = json.loads(done.stdout)
    assert done.returncode == 1 and len(data["problems"]) == 1, done.stdout


@case("a missing table is a problem")
def _():
    expect_problem(make_tree(table=False), "docs/enforcement.tsv: missing")


@case("a wrong header is a problem")
def _():
    expect_problem(make_tree(header="rule\tstated_in\tmechanism"), "the header must be")


@case("a row with the wrong number of columns is a problem that names its line")
def _():
    root = make_tree(raw=["only\ttwo"])
    expect_problem(root, f"docs/enforcement.tsv:{len(GOOD) + 2}: expected 4 columns, found 2")


@case("an empty field is a problem")
def _():
    expect_problem(good_with(("Empty column.", "", "prose", "-")), "empty stated_in")


@case("an unknown mechanism is a problem")
def _():
    expect_problem(good_with(("Odd mechanism.", "docs/doc.md", "wish", "-")), "unknown mechanism 'wish'")


@case("a stated_in file that does not exist is a problem")
def _():
    expect_problem(good_with(("Nowhere.", "docs/gone.md", "prose", "-")), "no such file 'docs/gone.md'")


@case("a stated_in heading that is not in the file is a problem")
def _():
    expect_problem(good_with(("Wrong heading.", "docs/doc.md#Third heading", "prose", "-")),
                   "no heading containing 'Third heading'")


@case("a stated_in heading matches part of a heading line, ignoring case")
def _():
    assert problems_of(good_with(("Partial.", "docs/doc.md#second HEAD", "prose", "-"))) == []


@case("a stated_in heading on a file that is not Markdown is a problem")
def _():
    expect_problem(good_with(("Script heading.", "scripts/doc.sh#top", "prose", "-")), "needs a Markdown file")


@case("a check-harness rule with no matching comment is a problem")
def _():
    expect_problem(good_with(("No such rule.", "docs/doc.md", "check", "check-harness rule 9")),
                   "has no rule 9")


@case("a check-harness rule with a letter suffix resolves")
def _():
    assert problems_of(good_with(("Sub-rule.", "docs/doc.md", "check", "check-harness rule 7b"))) == []


@case("a comment that merely mentions a number is not a rule")
def _():
    root = good_with(("Mentioned only.", "docs/doc.md", "check", "check-harness rule 4"))
    (root / "scripts" / "check-harness.sh").write_text("# 0. first\n# see rule 4 for more\n# 1. second\n")
    expect_problem(root, "has no rule 4")


@case("a hook that is not in hooks.json is a problem")
def _():
    expect_problem(good_with(("No such hook.", "docs/doc.md", "hook", "hook SessionStart")),
                   "has no hook 'SessionStart'")


@case("a hook matcher that is not in hooks.json is a problem")
def _():
    expect_problem(good_with(("No such matcher.", "docs/doc.md", "hook", "hook PreToolUse:Bash")),
                   "has no hook 'PreToolUse:Bash'")


@case("an unreadable hooks.json is reported once")
def _():
    root = good_with(("Another hook.", "docs/doc.md", "hook", "hook Stop"))
    (root / "hooks" / "hooks.json").write_text("{broken")
    found = problems_of(root)
    assert sum("cannot read the hooks" in line for line in found) == 1, found


@case("a command that is not in bin/ is a problem")
def _():
    expect_problem(good_with(("No such command.", "docs/doc.md", "command", "plumb-gone")),
                   "bin/plumb-gone does not exist")


@case("an enforced_by path that does not exist is a problem")
def _():
    expect_problem(good_with(("No such script.", "docs/doc.md", "check", "scripts/gone.sh")),
                   "no such file 'scripts/gone.sh'")


@case("an enforced_by that fits no form is a problem")
def _():
    expect_problem(good_with(("Vague.", "docs/doc.md", "check", "the harness")), "is not 'check-harness rule N'")


@case("a prose row must have '-' as enforced_by")
def _():
    expect_problem(good_with(("Prose with a script.", "docs/doc.md", "prose", "scripts/doc.sh")),
                   "a prose rule has enforced_by '-'")


@case("a row that is not prose must name what enforces it")
def _():
    expect_problem(good_with(("Hollow check.", "docs/doc.md", "check", "-")), "names what enforces it")


@case("a mechanism that does not match the form of enforced_by is a problem")
def _():
    expect_problem(good_with(("Wrong mechanism.", "docs/doc.md", "command", "check-harness rule 0")),
                   "is mechanism check, not command")
    expect_problem(good_with(("Wrong mechanism.", "docs/doc.md", "check", "plumb-watch")),
                   "is mechanism command, not check")
    expect_problem(good_with(("Wrong mechanism.", "docs/doc.md", "check", "hook Stop")),
                   "is mechanism hook, not check")


@case("the same rule text twice is a problem, whatever its spacing and case")
def _():
    expect_problem(good_with(("body text names  no MODEL slug.", "docs/doc.md", "prose", "-")),
                   "duplicate rule text (first on line 2)")


@case("a bad --root is a usage error that exits 2")
def _():
    done = subprocess.run([sys.executable, "-B", str(TOOL), "--root", str(ROOT / "nowhere")],
                          capture_output=True, text=True)
    assert done.returncode == 2 and "not a directory" in done.stderr, done


@case("an unknown flag is a usage error that exits 2")
def _():
    done = run(make_tree(), "--nonsense")
    assert done.returncode == 2, done


@case("the wrapper runs python3 -B and passes its arguments through")
def _():
    assert "exec python3 -B " in WRAPPER.read_text()
    done = subprocess.run([str(WRAPPER), "--root", str(make_tree()), "--check"], capture_output=True, text=True)
    assert (done.returncode, done.stdout) == (0, ""), done


@case("this checkout's own table passes --check")
def _():
    done = run(PLUGIN, "--check")
    assert (done.returncode, done.stdout) == (0, ""), (done.returncode, done.stdout)
    summary = run(PLUGIN).stdout.splitlines()[0]
    assert summary.startswith("enforcement: ") and ", prose " in summary, summary


@case("this checkout's table has 50 to 120 rules, at least 20 of them prose")
def _():
    counts = json.loads(run(PLUGIN, "--json").stdout)["counts"]
    total = sum(counts.values())
    assert 50 <= total <= 120 and counts["prose"] >= 20, counts


shutil.rmtree(ROOT, ignore_errors=True)
if FAILED:
    print(f"\n{len(FAILED)} case(s) failed")
    sys.exit(1)
print("\nall cases ok")
