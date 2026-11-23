#!/usr/bin/env python3
"""Regression suite for `plumb-check-pr-body` and `plumb-pr-watch`, on synthetic bodies and a fake `gh` only.

    python3 -B scripts/test-pr-tools.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline under tempfile.mkdtemp():
the forge is a small program placed first on PATH, the clock and the sleep of the watch loop are replaced,
and every title, name and URL is made up. Nothing here reaches a real remote.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
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
sys.path.insert(0, str(HERE))


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


body_tool = load("check_pr_body", "check-pr-body.py")
watch_tool = load("pr_watch", "pr-watch.py")

BODY_BIN = PLUGIN / "bin" / "plumb-check-pr-body"
WATCH_BIN = PLUGIN / "bin" / "plumb-pr-watch"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-pr-tools-test-"))
FAILED: list[str] = []
_counter = [0]


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


def fresh_dir(label: str) -> Path:
    _counter[0] += 1
    path = ROOT / f"{label}{_counter[0]}"
    path.mkdir()
    return path


# ---------------------------------------------------------------- the fake gh

FAKE_GH = f"""#!{sys.executable}
import json, os, sys
d = os.environ["FAKE_GH_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a") as log:
    log.write(json.dumps(args) + "\\n")
if os.path.exists(os.path.join(d, "fail")):
    sys.stderr.write("boom\\n")
    sys.exit(1)
def pick(stem):
    counter = os.path.join(d, stem + ".count")
    n = int(open(counter).read()) + 1 if os.path.exists(counter) else 1
    open(counter, "w").write(str(n))
    for k in range(n, 0, -1):
        numbered = os.path.join(d, "%s-%d.json" % (stem, k))
        if os.path.exists(numbered):
            return numbered
    return os.path.join(d, stem + ".json")
if args[:2] == ["pr", "view"]:
    stem = "body" if args[args.index("--json") + 1] == "body" else "pr"
elif args[:2] == ["api", "graphql"]:
    stem = "threads"
else:
    sys.exit(3)
path = pick(stem)
sys.stdout.write(open(path).read() if os.path.exists(path) else "")
"""


class Forge:
    """A directory the fake gh reads: pr.json, pr-N.json (the Nth read), threads.json, body.json, `fail`."""

    def __init__(self) -> None:
        self.dir = fresh_dir("gh")
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        (self.bin / "gh").write_text(FAKE_GH)
        (self.bin / "gh").chmod(0o755)

    def put(self, name: str, value) -> "Forge":
        (self.dir / name).write_text(value if isinstance(value, str) else json.dumps(value))
        return self

    def calls(self) -> list[list[str]]:
        log = self.dir / "calls.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def env(self) -> dict[str, str]:
        return {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_DIR": str(self.dir)}


@contextlib.contextmanager
def environment(env: dict[str, str]):
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def run_module(module, argv: list[str], env: dict[str, str] | None = None, stdin: str = "") -> tuple[int, str, str]:
    """module.main(argv) in this process: (exit code, stdout, stderr). argparse's SystemExit is the exit code."""
    out, err = io.StringIO(), io.StringIO()
    saved_stdin = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(stdin.encode()))
    try:
        with environment(env or dict(os.environ)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = module.main(argv)
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else 1
    finally:
        sys.stdin = saved_stdin
    return code, out.getvalue(), err.getvalue()


# ================================================================ plumb-check-pr-body

GOOD = """## Why

The reason, in a sentence.

## Scope

- changes `thing_a` and `thing_b`

## Blast Radius

Touches only the new command.

## Verification

Ran the suite; it passed.
"""


def findings(body: str, **kwargs) -> list[tuple[str, str]]:
    return body_tool.check(body, body_tool.parse_headings(kwargs.pop("headings", None)),
                           body_tool.parse_aliases(kwargs.pop("aliases", None), body_tool.parse_headings(kwargs.get("headings"))),
                           **kwargs)


def rules(body: str, **kwargs) -> list[str]:
    return [rule for rule, _ in findings(body, **kwargs)]


def filler(count: int, prefix: str = "line") -> str:
    return "\n".join(f"{prefix} {i}" for i in range(count))


def fence(count: int, marker: str = "```") -> str:
    return marker + "\n" + filler(count, "log") + "\n" + marker


@case("body: the playbook's sections in order are clean, with or without Tradeoffs")
def _():
    assert findings(GOOD) == [], findings(GOOD)
    with_tradeoffs = GOOD.replace("## Blast Radius", "## Tradeoffs\n\nChose A over B.\n\n## Blast Radius")
    assert findings(with_tradeoffs) == [], findings(with_tradeoffs)


@case("too-long: more than --max-lines non-blank lines; blank lines and the limit itself do not trip it")
def _():
    non_blank = sum(1 for l in GOOD.splitlines() if l.strip())
    pad = lambda n: GOOD + "\n" + filler(n)  # noqa: E731
    assert "too-long" not in rules(pad(40 - non_blank)), "exactly 40 passes"
    assert rules(pad(41 - non_blank)) == ["too-long"], rules(pad(41 - non_blank))
    detail = findings(pad(60 - non_blank))[0][1]
    assert detail.startswith("60 non-blank lines") and "max 40" in detail, detail
    assert "too-long" not in rules(pad(40 - non_blank) + "\n\n\n\n"), "blank lines are not counted"
    assert "too-long" not in rules(pad(41 - non_blank), max_lines=41)
    assert rules(pad(5), max_lines=non_blank) == ["too-long"]


@case("too-long: fenced code does not count, a comment does not count, a table row does")
def _():
    long_fence = GOOD + "\n" + fence(80)
    assert rules(long_fence, max_block_lines=100) == [], rules(long_fence, max_block_lines=100)
    assert rules(long_fence + "\n~~~\n" + filler(60) + "\n~~~\n", max_block_lines=100) == []
    comment = GOOD + "\n<!--\n" + filler(80) + "\n-->\n"
    assert rules(comment) == [], rules(comment)
    table = GOOD + "\n" + "\n".join(f"| a{i} | b{i} |" for i in range(45))
    assert rules(table) == ["too-long"], rules(table)


@case("too-long: trailers and bare URLs at the end of the body do not count; a URL in the middle does")
def _():
    non_blank = sum(1 for l in GOOD.splitlines() if l.strip())
    room = 40 - non_blank
    full = GOOD + "\n" + filler(room)
    assert rules(full) == []
    tail = ("\nFixes-PR: none\nCo-Authored-By: Some Agent <noreply>\nClaude-Session: https://example.invalid/s/1\n"
            "Signed-off-by: A Person\nReviewed-by: Another\n"
            "Generated with [Some Tool](https://example.invalid/tool)\n\nhttps://example.invalid/session/9\n")
    assert rules(full + tail) == [], rules(full + tail)
    assert rules(full + "\nhttps://example.invalid/a\nhttps://example.invalid/b\n") == [], "trailing bare URLs"
    assert rules(full + "\nhttps://example.invalid/a\nmore prose\n") == ["too-long"], "a URL before prose is not at the end"
    assert rules(full + "\nfixes-pr: none\n") == [], "trailers are case-insensitive"
    middle = GOOD.replace("## Scope", "Fixes-PR: none\n\n## Scope")
    assert rules(middle + "\n" + filler(room)) == [], "a trailer anywhere does not count"
    assert rules(full + "\n<https://example.invalid/a>\n") == [], "an angle-bracket URL too"


@case("heading-missing: every absent required heading is named; case does not matter; H3 and prose do not count")
def _():
    assert findings("just words\n") == [("heading-missing", f"## {n}") for n in ("Why", "Scope", "Blast Radius", "Verification")]
    assert findings("") == findings("   \n\n") == [("heading-missing", f"## {n}") for n in ("Why", "Scope", "Blast Radius", "Verification")]
    lower = GOOD.replace("## Why", "## WHY").replace("## Blast Radius", "##   blast   radius  ")
    assert findings(lower) == [], findings(lower)
    h3 = GOOD.replace("## Scope", "### Scope")
    assert findings(h3) == [("heading-missing", "## Scope")], findings(h3)
    assert findings(GOOD.replace("## Verification", "Verification")) == [("heading-missing", "## Verification")]
    assert findings(GOOD.replace("## Why", "##Why")) == [("heading-missing", "## Why")], "no space is not a heading"
    assert findings(GOOD.replace("## Why", "## Why ##")) == [], "closing hashes are stripped"


@case("heading-missing: --heading replaces the list, NAME? is optional, --allow-alias accepts another text")
def _():
    body = "## Summary\n\ntext\n\n## Test plan\n\ntext\n"
    assert findings(body, headings=["Summary", "Test plan"]) == []
    assert findings(body, headings=["Summary", "Test plan", "Notes"]) == [("heading-missing", "## Notes")]
    assert findings(body, headings=["Summary", "Test plan", "Notes?"]) == []
    changed = GOOD.replace("## Scope", "## What changed")
    assert findings(changed) == [("heading-missing", "## Scope")]
    assert findings(changed, aliases=["Scope=what changed"]) == [], findings(changed, aliases=["Scope=what changed"])
    for bad in (["Nope=x"], ["no-equals"], ["Scope="], ["=x"]):
        try:
            body_tool.parse_aliases(bad, body_tool.parse_headings(None))
        except ValueError:
            continue
        raise AssertionError(f"alias {bad} was accepted")
    for bad in ([""], ["Why", "why"], ["?"]):
        try:
            body_tool.parse_headings(bad)
        except ValueError:
            continue
        raise AssertionError(f"headings {bad} were accepted")


@case("heading-order: a heading before one that should precede it; Tradeoffs between Scope and Blast Radius is right")
def _():
    swapped = ("## Scope\n\nx\n\n## Why\n\ny\n\n## Blast Radius\n\nz\n\n## Verification\n\nv\n")
    assert findings(swapped) == [("heading-order", "## Scope appears before ## Why")], findings(swapped)
    moved = GOOD + "\n## Why\n\nsecond\n"
    assert findings(moved) == [], "only the first occurrence counts"
    late = GOOD + "\n## Tradeoffs\n\nchoice\n"
    assert findings(late) == [("heading-order", "## Blast Radius appears before ## Tradeoffs")], findings(late)
    reverse = "\n\n".join(f"## {n}\n\ntext" for n in ("Verification", "Blast Radius", "Scope", "Why")) + "\n"
    assert findings(reverse) == [("heading-order", "## Scope appears before ## Why"),
                                 ("heading-order", "## Blast Radius appears before ## Scope"),
                                 ("heading-order", "## Verification appears before ## Blast Radius")], findings(reverse)
    only_order = "## Verification\n\nv\n\n## Why\n\nw\n"
    assert findings(only_order) == [("heading-missing", "## Scope"), ("heading-missing", "## Blast Radius"),
                                    ("heading-order", "## Verification appears before ## Why")], findings(only_order)


@case("long-block: a fenced block over --max-block-lines; backtick and tilde; unclosed; headings inside a fence are text")
def _():
    assert "long-block" not in rules(GOOD + "\n" + fence(15)), "exactly 15 passes"
    got = findings(GOOD + "\n" + fence(16))
    assert [r for r, _ in got] == ["long-block"] and "16 lines" in got[0][1] and "max 15" in got[0][1], got
    assert rules(GOOD + "\n" + fence(16, "~~~")) == ["long-block"]
    assert "long-block" not in rules(GOOD + "\n" + fence(16), max_block_lines=16)
    assert rules(GOOD + "\n```\n" + filler(20)) == ["long-block"], "an unclosed block runs to the end"
    two = GOOD + "\n" + fence(3) + "\n\n" + fence(20)
    assert rules(two) == ["long-block"] and findings(two)[0][1].startswith("line "), findings(two)
    nested = GOOD + "\n~~~\n```\n" + filler(20) + "\n```\n~~~\n"
    assert rules(nested) == ["long-block"], "a backtick fence inside a tilde block does not close it"
    longer = GOOD + "\n````\n```\n" + filler(5) + "\n```\n````\n"
    assert rules(longer) == [], rules(longer)
    hidden = "## Why\n\nw\n\n```\n## Scope\n## Blast Radius\n## Verification\n```\n"
    assert rules(hidden) == ["heading-missing"] * 3, "headings inside a fence are not headings"


@case("empty-section: a heading with nothing before the next one; trailers and a comment are not content")
def _():
    empty_middle = GOOD.replace("The reason, in a sentence.\n", "")
    assert findings(empty_middle) == [("empty-section", "## Why has nothing before the next heading")], findings(empty_middle)
    assert rules("## Why\n\nw\n\n## Scope\n\ns\n\n## Blast Radius\n\nb\n\n## Verification\n") == ["empty-section"], "the last section too"
    only_trailer = GOOD.replace("Ran the suite; it passed.\n", "\nFixes-PR: none\n")
    assert findings(only_trailer) == [("empty-section", "## Verification has nothing before the next heading")], findings(only_trailer)
    only_url = GOOD.replace("Ran the suite; it passed.\n", "https://example.invalid/log\n")
    assert rules(only_url) == ["empty-section"], "a URL ending the body is not content"
    only_comment = GOOD.replace("The reason, in a sentence.", "<!-- explain why -->")
    assert rules(only_comment) == ["empty-section"], rules(only_comment)
    sub = GOOD.replace("- changes `thing_a` and `thing_b`", "### Paths\n\n- a")
    assert findings(sub) == [], "a ### subsection is content"
    fenced = GOOD.replace("Ran the suite; it passed.", "```\nok\n```")
    assert findings(fenced) == [], "a fenced block is content"
    optional_empty = GOOD.replace("## Blast Radius", "## Tradeoffs\n\n## Blast Radius")
    assert rules(optional_empty) == ["empty-section"], "an optional heading that is present must not be empty"
    assert rules(GOOD.replace("## Blast Radius", "## Notes\n\n## Blast Radius")) == [], "headings outside the list are ignored"


@case("rule order: findings come out too-long, heading-missing, heading-order, long-block, empty-section")
def _():
    body = ("## Verification\n\nv\n\n## Why\n\n```\n" + filler(20) + "\n```\n" + filler(50) + "\n\n## Scope\n")
    assert rules(body) == ["too-long", "heading-missing", "heading-order", "long-block", "empty-section"], rules(body)


def write_body(text: str) -> str:
    path = fresh_dir("body") / "body.md"
    path.write_text(text)
    return str(path)


@case("command: clean body prints `pr-body: clean`, exit 0; findings print rule TAB detail then the count, exit 1")
def _():
    code, out, err = run_module(body_tool, ["--file", write_body(GOOD)])
    assert (code, out, err) == (0, "pr-body: clean\n", ""), (code, out, err)
    code, out, err = run_module(body_tool, ["--file", write_body("## Why\n\nw\n")])
    lines = out.splitlines()
    assert code == 1 and err == "", (code, err)
    assert lines == ["heading-missing\t## Scope", "heading-missing\t## Blast Radius", "heading-missing\t## Verification",
                     "pr-body: 3 findings"], lines
    code, out, _ = run_module(body_tool, ["--file", write_body(GOOD.replace("Ran the suite; it passed.", ""))])
    assert code == 1 and out.splitlines()[-1] == "pr-body: 1 findings", out


@case("command: --json has schema, outcome and findings; `-` and --file - read standard input")
def _():
    code, out, _ = run_module(body_tool, ["--json", "--file", write_body("")])
    doc = json.loads(out)
    assert code == 1 and doc["schema"] == 1 and doc["outcome"] == "findings", doc
    assert doc["findings"][0] == {"rule": "heading-missing", "detail": "## Why"} and len(doc["findings"]) == 4, doc
    code, out, _ = run_module(body_tool, ["--json", "-"], stdin=GOOD)
    assert code == 0 and json.loads(out) == {"schema": 1, "outcome": "clean", "findings": []}, out
    code, out, _ = run_module(body_tool, ["--file", "-"], stdin=GOOD + "\r\n")
    assert code == 0 and out == "pr-body: clean\n", out
    code, out, _ = run_module(body_tool, ["-"], stdin=GOOD.replace("\n", "\r\n"))
    assert code == 0, "CRLF bodies read the same"


@case("command: options reach the rules (--max-lines, --max-block-lines, --heading, --allow-alias)")
def _():
    path = write_body(GOOD + "\n" + fence(20))
    assert run_module(body_tool, ["--file", path])[0] == 1
    assert run_module(body_tool, ["--file", path, "--max-block-lines", "20"])[0] == 0
    assert run_module(body_tool, ["--file", path, "--max-block-lines", "20", "--max-lines", "5"])[0] == 1
    code, out, _ = run_module(body_tool, ["--file", write_body("## Summary\n\nx\n"), "--heading", "Summary"])
    assert (code, out) == (0, "pr-body: clean\n"), (code, out)
    code, out, _ = run_module(body_tool, ["--file", write_body(GOOD.replace("## Scope", "## What changed")),
                                          "--allow-alias", "Scope=What changed"])
    assert (code, out) == (0, "pr-body: clean\n"), (code, out)


@case("command: --pr reads the body through gh and passes --repo; a gh failure is exit 2, not findings")
def _():
    forge = Forge().put("body.json", {"body": GOOD})
    code, out, err = run_module(body_tool, ["--pr", "42", "--repo", "acme/widgets"], forge.env())
    assert (code, out) == (0, "pr-body: clean\n"), (code, out, err)
    assert forge.calls() == [["pr", "view", "42", "--json", "body", "--repo", "acme/widgets"]], forge.calls()
    forge.put("body.json", {"body": None})
    code, out, _ = run_module(body_tool, ["--pr", "42"], forge.env())
    assert code == 1 and out.splitlines()[-1] == "pr-body: 4 findings", out
    forge.put("body.json", "not json")
    code, out, err = run_module(body_tool, ["--pr", "42"], forge.env())
    assert code == 2 and out == "" and "pull request 42" in err and "Traceback" not in err, (code, out, err)
    forge.put("fail", "")
    code, out, err = run_module(body_tool, ["--pr", "42"], forge.env())
    assert code == 2 and out == "" and "could not read" in err, (code, out, err)
    code, out, err = run_module(body_tool, ["--pr", "42"], {**os.environ, "PATH": str(fresh_dir("empty"))})
    assert code == 2 and out == "" and "could not read" in err, "gh missing is an input error"


@case("command: usage and input errors exit 2 and print nothing on stdout")
def _():
    good = write_body(GOOD)
    bad = [[], ["--file", good, "--pr", "3"], ["--file", good, "-"], ["--pr", "0"], ["--pr", "x"], ["--file", good, "--max-lines", "-1"],
           ["--file", good, "--max-block-lines", "-1"], ["--file", good, "--allow-alias", "Nope=x"], ["--file", good, "--heading", ""],
           ["--file", str(ROOT / "no-such-file")], ["--file", str(ROOT)], ["--file", good, "--repo", "a/b"], ["--pr", "3", "--repo", "bad"],
           ["somefile"], ["--bogus"]]
    for argv in bad:
        code, out, err = run_module(body_tool, argv, {**os.environ, "PATH": str(fresh_dir("empty"))})
        assert code == 2 and out == "", (argv, code, out, err)
        assert "Traceback" not in err, (argv, err)


@case("command: it writes nothing (the working directory is unchanged) and the wrapper runs, through a symlink too")
def _():
    work = fresh_dir("work")
    path = write_body(GOOD)
    done = subprocess.run([str(BODY_BIN), "--file", path], capture_output=True, text=True, cwd=work)
    assert (done.returncode, done.stdout) == (0, "pr-body: clean\n") and list(work.iterdir()) == [], done
    link = fresh_dir("link") / "plumb-check-pr-body"
    link.symlink_to(BODY_BIN)
    done = subprocess.run([str(link), "-"], input="nothing here\n", capture_output=True, text=True, cwd=work)
    assert done.returncode == 1 and done.stdout.splitlines()[-1] == "pr-body: 4 findings", done
    assert os.access(BODY_BIN, os.X_OK) and list(work.iterdir()) == []


# ================================================================ plumb-pr-watch

def run(name: str = "build", conclusion: str = "SUCCESS", status: str = "COMPLETED") -> dict:
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def pr(**over) -> dict:
    base = {"number": 7, "state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "reviewDecision": "", "statusCheckRollup": [run("build"), run("lint")]}
    base.update(over)
    return {k: v for k, v in base.items() if v is not ...}


def threads(*resolved: bool, more: bool = False) -> dict:
    return {"pageInfo": {"hasNextPage": more}, "nodes": [{"isResolved": r} for r in resolved]}


QUIET = threads()


def state_of(pull: dict, thread=QUIET) -> str:
    return watch_tool.classify(pull, thread)[0]


@case("classify: one pull request per state, with the detail that explains it")
def _():
    assert watch_tool.classify(pr(state="MERGED"), QUIET) == ("merged", [])
    assert watch_tool.classify(pr(state="CLOSED"), QUIET) == ("closed", [])
    assert watch_tool.classify(pr(mergeable="CONFLICTING", mergeStateStatus="DIRTY"), QUIET) == ("conflicts", ["mergeable=conflicting", "merge=dirty"])
    assert watch_tool.classify(pr(), threads(True, False, False)) == ("threads", ["unresolved=2"])
    assert watch_tool.classify(pr(statusCheckRollup=[run("build"), run("lint", "FAILURE"), run("e2e", status="IN_PROGRESS", conclusion=None)]), QUIET) \
        == ("failing", ["failed=1", "pending=1", "names=lint"])
    assert watch_tool.classify(pr(statusCheckRollup=[run("build", status="IN_PROGRESS", conclusion=None), run("lint")]), QUIET) \
        == ("pending", ["checks_pending=1"])
    assert watch_tool.classify(pr(isDraft=True), QUIET) == ("draft", ["checks_passed=2"])
    assert watch_tool.classify(pr(), QUIET) == ("ready", ["checks_passed=2"])
    assert watch_tool.classify(pr(), threads(True, True)) == ("ready", ["checks_passed=2"])
    assert watch_tool.classify(pr(statusCheckRollup=[]), QUIET) == ("ready", ["checks_passed=0"]), "no checks at all is not a failure"


@case("classify: the order is merged, closed, conflicts, threads, failing, pending, draft, ready")
def _():
    everything = dict(mergeable="CONFLICTING", isDraft=True,
                      statusCheckRollup=[run("a", "FAILURE"), run("b", status="QUEUED", conclusion=None)])
    open_threads = threads(False)
    assert state_of(pr(state="MERGED", **everything), open_threads) == "merged"
    assert state_of(pr(state="CLOSED", **everything), open_threads) == "closed"
    assert state_of(pr(**everything), open_threads) == "conflicts"
    assert state_of(pr(**{**everything, "mergeable": "MERGEABLE"}), open_threads) == "threads"
    assert state_of(pr(**{**everything, "mergeable": "MERGEABLE"}), QUIET) == "failing"
    assert state_of(pr(isDraft=True, statusCheckRollup=[run("a", "FAILURE")]), QUIET) == "failing", "a failing draft is failing"
    assert state_of(pr(isDraft=True, statusCheckRollup=[run("b", status="QUEUED", conclusion=None)]), QUIET) == "pending"
    assert state_of(pr(isDraft=True), QUIET) == "draft"
    assert state_of(pr(), QUIET) == "ready"
    assert state_of(pr(mergeStateStatus="DIRTY")) == "conflicts", "DIRTY alone is a conflict"
    assert state_of(pr(statusCheckRollup=[run("a", "FAILURE")]), threads(False)) == "threads", "threads beat failing"
    assert state_of(pr(mergeable="UNKNOWN", statusCheckRollup=[run("a", "FAILURE")]), QUIET) == "failing", "a known failure is not hidden by an unknown field"
    assert dict(zip(("merged", "closed", "conflicts", "threads", "failing", "pending", "draft", "ready"), range(8)))  # the list above is the order


@case("classify: failing names are at most 5, in order, with the rest counted; control characters cannot split the line")
def _():
    runs = [run(f"job-{i}", "FAILURE") for i in range(8)]
    state, detail = watch_tool.classify(pr(statusCheckRollup=runs), QUIET)
    assert state == "failing" and detail == ["failed=8", "names=job-0, job-1, job-2, job-3, job-4 (+3 more)"], detail
    state, detail = watch_tool.classify(pr(statusCheckRollup=[run("bad\tname\nnext\x1b[2J", "FAILURE")]), QUIET)
    assert detail[-1] == "names=bad?name?next?[2J", detail
    state, detail = watch_tool.classify(pr(statusCheckRollup=[run(f"j{i}", "FAILURE") for i in range(5)]), QUIET)
    assert detail[-1] == "names=j0, j1, j2, j3, j4", "exactly five has no 'more'"


@case("classify: every check conclusion and status-context state")
def _():
    def with_rollup(*entries) -> str:
        return state_of(pr(statusCheckRollup=list(entries)))
    for good in ("SUCCESS", "NEUTRAL", "SKIPPED"):
        assert with_rollup(run(conclusion=good)) == "ready", good
    for bad in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"):
        assert with_rollup(run(conclusion=bad)) == "failing", bad
    for waiting in ("QUEUED", "IN_PROGRESS", "WAITING", "PENDING", "REQUESTED"):
        assert with_rollup(run(status=waiting, conclusion=None)) == "pending", waiting
    assert with_rollup(run(conclusion="STALE")) == "pending", "a conclusion that is not understood is not green"
    assert with_rollup(run(conclusion=None)) == "pending"
    assert with_rollup(run(status="SOMETHING_NEW", conclusion=None)) == "pending"
    status = lambda state, name="ci/legacy": {"__typename": "StatusContext", "context": name, "state": state}  # noqa: E731
    assert with_rollup(status("SUCCESS")) == "ready"
    assert with_rollup(status("FAILURE")) == with_rollup(status("ERROR")) == "failing"
    assert with_rollup(status("PENDING")) == with_rollup(status("EXPECTED")) == "pending"
    assert with_rollup(status("???")) == "pending"
    assert watch_tool.classify(pr(statusCheckRollup=[status("ERROR", "ci/legacy")]), QUIET)[1][-1] == "names=ci/legacy"
    assert with_rollup("junk") == with_rollup(None) == "pending"


@case("classify: an unknown or absent field is pending, never ready")
def _():
    for key in ("state", "isDraft", "mergeable", "mergeStateStatus", "statusCheckRollup"):
        got = state_of(pr(**{key: ...}))
        assert got == "pending", (key, got)
    for key, value in (("state", "SOMETHING"), ("state", None), ("isDraft", None), ("isDraft", "no"), ("mergeable", "UNKNOWN"),
                       ("mergeable", "MAYBE"), ("mergeable", None), ("mergeStateStatus", "UNKNOWN"), ("mergeStateStatus", ""),
                       ("mergeStateStatus", None), ("statusCheckRollup", None), ("statusCheckRollup", {})):
        got = state_of(pr(**{key: value}))
        assert got == "pending", (key, value, got)
    assert watch_tool.classify(pr(mergeable=...), QUIET)[1] == ["unknown=mergeable"]
    assert state_of(pr(), None) == "pending", "threads not known"
    assert watch_tool.classify(pr(), None) == ("pending", ["unknown=threads"])
    for odd in ({}, {"nodes": None}, {"nodes": [{}]}, {"nodes": [{"isResolved": "yes"}]}, {"pageInfo": {}}, "x", []):
        assert state_of(pr(), odd) == "pending", odd
    assert state_of(pr(), threads(True, True, more=True)) == "pending", "a second page of threads may hold an unresolved one"
    assert state_of(pr(), threads(True, False, more=True)) == "threads", "a known unresolved thread needs no second page"
    assert state_of(pr(), {"nodes": []}) == "pending", "no pageInfo is not 'no more pages'"
    for junk in (None, [], "ready", 3):
        assert watch_tool.classify(junk, QUIET)[0] == "pending", junk
    assert watch_tool.classify({}, QUIET)[0] == "pending"
    assert all(state_of(pr(**{k: ...}), t) != "ready" for k in ("state", "isDraft", "mergeable", "mergeStateStatus", "statusCheckRollup")
               for t in (None, QUIET))


@case("classify: ready names a review decision and a merge state that need a person; clean ones add nothing")
def _():
    assert watch_tool.classify(pr(reviewDecision="REVIEW_REQUIRED", mergeStateStatus="BLOCKED"), QUIET) \
        == ("ready", ["checks_passed=2", "review=review_required", "merge=blocked"])
    assert watch_tool.classify(pr(reviewDecision="APPROVED"), QUIET) == ("ready", ["checks_passed=2", "review=approved"])
    assert watch_tool.classify(pr(mergeStateStatus="BEHIND"), QUIET)[1] == ["checks_passed=2", "merge=behind"]


def watch_env(forge: Forge) -> dict[str, str]:
    return forge.env()


def cli(forge: Forge, argv: list[str]) -> tuple[int, str, str]:
    return run_module(watch_tool, argv, watch_env(forge))


@case("command: each state prints one word (then tab detail) and its exit code")
def _():
    table = [
        ("merged", pr(state="MERGED"), QUIET, 0, "merged"),
        ("closed", pr(state="CLOSED"), QUIET, 6, "closed"),
        ("conflicts", pr(mergeable="CONFLICTING"), QUIET, 3, "conflicts\tmergeable=conflicting\tmerge=clean"),
        ("threads", pr(), {"pageInfo": {"hasNextPage": False}, "nodes": [{"isResolved": False}]}, 4, "threads\tunresolved=1"),
        ("failing", pr(statusCheckRollup=[run("lint", "FAILURE")]), QUIET, 5, "failing\tfailed=1\tnames=lint"),
        ("pending", pr(statusCheckRollup=[run("build", status="QUEUED", conclusion=None)]), QUIET, 7, "pending\tchecks_pending=1"),
        ("draft", pr(isDraft=True), QUIET, 8, "draft\tchecks_passed=2"),
        ("ready", pr(), QUIET, 0, "ready\tchecks_passed=2"),
    ]
    for state, pull, thread, expected_code, expected_line in table:
        forge = Forge().put("pr.json", pull).put("threads.json", {"data": {"repository": {"pullRequest": {"reviewThreads": thread}}}})
        code, out, err = cli(forge, ["7"])
        assert (code, out.rstrip("\n"), err) == (expected_code, expected_line, ""), (state, code, out, err)
        assert out.count("\n") == 1 and out.rstrip("\n").split("\t")[0] == state, (state, out)
        assert len(forge.calls()) == (1 if state in ("merged", "closed", "conflicts") else 2), (state, forge.calls())


@case("command: the exit codes are distinct where the states are, and 1 and 2 are left to the usage error")
def _():
    codes = watch_tool.EXIT
    assert codes == {"merged": 0, "closed": 6, "conflicts": 3, "threads": 4, "failing": 5, "pending": 7, "draft": 8, "ready": 0,
                     "unavailable": 9}, codes


@case("command: one pr view and one graphql call, read-only, with --repo or the :owner/:repo placeholders")
def _():
    thread_answer = {"data": {"repository": {"pullRequest": {"reviewThreads": QUIET}}}}
    forge = Forge().put("pr.json", pr()).put("threads.json", thread_answer)
    cli(forge, ["7"])
    first, second = forge.calls()
    assert first == ["pr", "view", "7", "--json", watch_tool.PR_FIELDS], first
    assert second[:2] == ["api", "graphql"] and "owner=:owner" in second and "name=:repo" in second and "number=7" in second, second
    assert "reviewThreads" in " ".join(second) and "mutation" not in " ".join(second).lower(), second
    forge = Forge().put("pr.json", pr()).put("threads.json", thread_answer)
    cli(forge, ["7", "--repo", "acme/widgets"])
    first, second = forge.calls()
    assert first[-2:] == ["--repo", "acme/widgets"] and "owner=acme" in second and "name=widgets" in second, forge.calls()
    for field in ("state", "isDraft", "mergeable", "mergeStateStatus", "reviewDecision", "statusCheckRollup"):
        assert field in watch_tool.PR_FIELDS.split(","), field


@case("command: a threads answer that cannot be read is pending, not ready")
def _():
    for answer in ("{}", '{"data": null}', '{"data": {"repository": null}}', '{"data": {"repository": {"pullRequest": null}}}'):
        forge = Forge().put("pr.json", pr()).put("threads.json", answer)
        code, out, _ = cli(forge, ["7"])
        assert (code, out) == (7, "pending\tunknown=threads\n"), (answer, code, out)


@case("command: --json carries the state, the exit code and the detail")
def _():
    forge = Forge().put("pr.json", pr(statusCheckRollup=[run("lint", "FAILURE")])).put("threads.json", {"data": {"repository": {"pullRequest": {"reviewThreads": QUIET}}}})
    code, out, _ = cli(forge, ["7", "--json"])
    assert code == 5 and json.loads(out) == {"schema": 1, "remote": "ok", "number": 7, "state": "failing", "exit": 5,
                                              "detail": ["failed=1", "names=lint"]}, out


@case("command: gh missing, failing, or answering garbage is `remote: unavailable`, exit 9, in text and JSON")
def _():
    nogh = {**os.environ, "PATH": str(fresh_dir("empty"))}
    code, out, err = run_module(watch_tool, ["7"], nogh)
    assert (code, out.strip(), "Traceback" in err) == (9, "remote: unavailable", False), (code, out, err)
    code, out, _ = run_module(watch_tool, ["7", "--json"], nogh)
    assert code == 9 and json.loads(out) == {"schema": 1, "remote": "unavailable", "state": None, "exit": 9}, out
    forge = Forge().put("fail", "")
    assert cli(forge, ["7"])[:2] == (9, "remote: unavailable\n")
    forge = Forge().put("pr.json", "not json")
    assert cli(forge, ["7"])[:2] == (9, "remote: unavailable\n")
    forge = Forge().put("pr.json", pr())  # the pull request reads, the threads call returns nothing at all
    assert cli(forge, ["7"])[:2] == (9, "remote: unavailable\n"), "an empty answer is not JSON"
    forge = Forge().put("pr.json", "")
    assert cli(forge, ["7"])[0] == 9
    for state in ("MERGED", "OPEN"):
        assert "ready" not in cli(Forge().put("fail", ""), ["7"])[1], state


class Clock:
    """A fake clock: `pause` advances it and records what was slept."""

    def __init__(self) -> None:
        self.now, self.sleeps = 1000.0, []

    def __call__(self) -> float:
        return self.now

    def pause(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@contextlib.contextmanager
def fake_clock():
    clock = Clock()
    saved = watch_tool.clock, watch_tool.pause
    watch_tool.clock, watch_tool.pause = clock, clock.pause
    try:
        yield clock
    finally:
        watch_tool.clock, watch_tool.pause = saved


def waiting_forge(*states: dict) -> Forge:
    forge = Forge().put("threads.json", {"data": {"repository": {"pullRequest": {"reviewThreads": QUIET}}}})
    for n, pull in enumerate(states, start=1):
        forge.put(f"pr-{n}.json", pull)
    return forge


RUNNING = pr(statusCheckRollup=[run("build", status="IN_PROGRESS", conclusion=None)])


@case("wait: reads again every --interval until the state is not pending, then prints it")
def _():
    forge = waiting_forge(RUNNING, RUNNING, pr())
    with fake_clock() as clock:
        code, out, _ = cli(forge, ["7", "--wait", "600", "--interval", "45"])
    assert (code, out) == (0, "ready\tchecks_passed=2\n"), (code, out)
    assert clock.sleeps == [45, 45], clock.sleeps
    assert len([c for c in forge.calls() if c[:2] == ["pr", "view"]]) == 3
    forge = waiting_forge(RUNNING, pr(statusCheckRollup=[run("lint", "FAILURE")]))
    with fake_clock() as clock:
        code, out, _ = cli(forge, ["7", "--wait", "600"])
    assert code == 5 and clock.sleeps == [60], (code, out, clock.sleeps)
    forge = waiting_forge(pr())
    with fake_clock() as clock:
        code, _, _ = cli(forge, ["7", "--wait", "600"])
    assert code == 0 and clock.sleeps == [], "a state that is not pending is returned at once"


@case("wait: on timeout it prints pending with `timeout` in the detail and exits 7; the last sleep is cut to the deadline")
def _():
    forge = waiting_forge(RUNNING)
    with fake_clock() as clock:
        code, out, _ = cli(forge, ["7", "--wait", "100", "--interval", "60"])
    assert (code, out) == (7, "pending\tchecks_pending=1\ttimeout\n"), (code, out)
    assert clock.sleeps == [60, 40], clock.sleeps
    assert len([c for c in forge.calls() if c[:2] == ["pr", "view"]]) == 3, "a read at the deadline, then the answer"
    forge = waiting_forge(RUNNING)
    with fake_clock() as clock:
        code, out, _ = cli(forge, ["7", "--wait", "0"])
    assert (code, out, clock.sleeps) == (7, "pending\tchecks_pending=1\ttimeout\n", []), (code, out, clock.sleeps)
    forge = waiting_forge(RUNNING)
    with fake_clock() as clock:
        code, out, _ = cli(forge, ["7", "--wait", "30", "--json"])
    assert code == 7 and json.loads(out)["detail"] == ["checks_pending=1", "timeout"] and clock.sleeps == [30], (out, clock.sleeps)


@case("wait: without --wait it reads once, sleeps never and adds no `timeout`")
def _():
    forge = waiting_forge(RUNNING, pr())
    with fake_clock() as clock:
        code, out, _ = cli(forge, ["7"])
    assert (code, out, clock.sleeps) == (7, "pending\tchecks_pending=1\n", []), (code, out, clock.sleeps)
    assert len([c for c in forge.calls() if c[:2] == ["pr", "view"]]) == 1


@case("wait: gh going away mid-wait is exit 9; a pending state that never resolves is never read as ready")
def _():
    forge = waiting_forge(RUNNING)
    with fake_clock() as clock:
        original = watch_tool.pause

        def break_gh(seconds):
            clock.pause(seconds)
            (forge.dir / "fail").write_text("")
        watch_tool.pause = break_gh
        try:
            code, out, _ = cli(forge, ["7", "--wait", "600"])
        finally:
            watch_tool.pause = original
    assert (code, out) == (9, "remote: unavailable\n"), (code, out)
    unknown = waiting_forge(pr(mergeable="UNKNOWN"))
    with fake_clock():
        code, out, _ = cli(unknown, ["7", "--wait", "120"])
    assert code == 7 and out == "pending\tunknown=mergeable\ttimeout\n", (code, out)


@case("wait: the pure loop takes a fake read, clock and sleep and does not touch gh")
def _():
    answers = iter([("pending", ["x"]), ("pending", ["x"]), ("threads", ["unresolved=1"])])
    with fake_clock() as clock:
        got = watch_tool.watch(lambda: next(answers), wait=500, interval=30)
    assert got == ("threads", ["unresolved=1"]) and clock.sleeps == [30, 30], (got, clock.sleeps)
    with fake_clock() as clock:
        got = watch_tool.watch(lambda: ("pending", []), wait=10, interval=30)
    assert got == ("pending", ["timeout"]) and clock.sleeps == [10], (got, clock.sleeps)


@case("command: bad usage exits 2: no number, interval under 30, negative wait, bad repo, zero number")
def _():
    forge = Forge().put("pr.json", pr())
    for argv in ([], ["x"], ["0"], ["-3"], ["7", "--interval", "29"], ["7", "--interval", "0", "--wait", "5"], ["7", "--wait", "-1"],
                 ["7", "--repo", "nope"], ["7", "--repo", "a/b/c"], ["7", "--bogus"]):
        code, out, err = cli(forge, argv)
        assert code == 2 and out == "" and "Traceback" not in err, (argv, code, out, err)
    assert forge.calls() == [], "usage errors never reach the forge"
    assert cli(forge, ["7", "--interval", "30"])[0] in (0, 4, 5, 7, 8, 9), "30 is the minimum, allowed"


@case("command: the wrapper runs through a symlink with a fake gh first on PATH; nothing is written to the working directory")
def _():
    forge = Forge().put("pr.json", pr()).put("threads.json", {"data": {"repository": {"pullRequest": {"reviewThreads": QUIET}}}})
    link = fresh_dir("link") / "plumb-pr-watch"
    link.symlink_to(WATCH_BIN)
    work = fresh_dir("work")
    done = subprocess.run([str(link), "7"], capture_output=True, text=True, cwd=work, env=forge.env())
    assert (done.returncode, done.stdout, done.stderr) == (0, "ready\tchecks_passed=2\n", ""), done
    assert list(work.iterdir()) == [], "it writes nothing"
    forge.put("pr.json", pr(state="CLOSED"))
    done = subprocess.run([str(WATCH_BIN), "7"], capture_output=True, text=True, cwd=work, env=forge.env())
    assert (done.returncode, done.stdout) == (6, "closed\n"), done
    bare = fresh_dir("bare")  # a PATH with what the wrapper needs and no gh
    for tool, real in (("bash", shutil.which("bash")), ("dirname", shutil.which("dirname")), ("python3", sys.executable)):
        (bare / tool).symlink_to(real)
    done = subprocess.run([str(WATCH_BIN), "7"], capture_output=True, text=True, cwd=work, env={**os.environ, "PATH": str(bare)})
    assert (done.returncode, done.stdout.strip()) == (9, "remote: unavailable"), done
    assert os.access(WATCH_BIN, os.X_OK)


shutil.rmtree(ROOT, ignore_errors=True)
if FAILED:
    print(f"\n{len(FAILED)} case(s) failed")
    sys.exit(1)
print("\nall cases ok")
