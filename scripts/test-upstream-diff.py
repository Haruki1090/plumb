#!/usr/bin/env python3
"""Regression suite for `plumb-upstream-diff`, on a synthetic upstream only.

    python3 -B scripts/test-upstream-diff.py

One `ok` / `NG` line per case; exit 1 when any case is NG. Everything runs offline under tempfile.mkdtemp():
the forge is a function here, or a fake `gh` program placed first on PATH, and every file, skill, playbook and
agent name is made up. The real NOTICE and docs/scope.md are only read by the one case that checks the shipped
NOTICE line parses.
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
_spec = importlib.util.spec_from_file_location("upstream_diff", HERE / "upstream-diff.py")
ud = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ud)

BIN = PLUGIN / "bin" / "plumb-upstream-diff"
ROOT = Path(tempfile.mkdtemp(prefix="plumb-upstream-diff-test-"))
FAILED: list[str] = []
HEAD = "0123456789abcdef0123456789abcdef01234567"
LINE = "Upstream last read: acme/widgets@abc1234 path kit version 1.2.3 on 2026-03-04"
NOTICE_TEXT = f"kit\n\nsome paragraph\n\n{LINE}\n\nmore text\n"
NOTICE = ud.parse_notice(NOTICE_TEXT)


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

def entry(name: str, status: str = "modified", old: str | None = None) -> dict:
    raw = {"filename": name, "status": status, "additions": 1, "deletions": 0}
    if old:
        raw["previous_filename"] = old
    return raw


def blob(path: str) -> dict:
    return {"path": path, "type": "blob", "sha": "f" * 40}


def tree_of(*paths: str) -> list[dict]:
    return [blob(p) for p in paths] + [{"path": "kit/skills", "type": "tree", "sha": "e" * 40}]


UPSTREAM_TREE = tree_of(
    "README.md", "kit/README.md", "kit/skills/alpha-tool/SKILL.md", "kit/skills/alpha-tool/references/notes.md",
    "kit/skills/gamma-tool/SKILL.md", "kit/skills/principle-keep-it-small/SKILL.md", "kit/skills/principle-count-twice/SKILL.md",
    "kit/skills/hub/SKILL.md", "kit/skills/hub/playbooks/first-aid.md", "kit/skills/hub/playbooks/cleanup.md",
    "kit/skills/hub/scripts/run.sh", "kit/agents/scribe.md", "kit/agents/scout.md", "kit/agents/notes.txt",
    "kit/docs/guide/README.md", "kit/docs/guide/01-start.md", "kit/docs/guide/02-middle.md", "kit/docs/guide/images/a.jpg",
    "other-kit/skills/zeta-tool/SKILL.md")
SCOPE = ("alpha-tool is ported. hub keeps `first-aid`. keep-it-small was rewritten. scribe is folded.\n"
         "gamma-tool-two is something else; principle-count-twice is spelled with its prefix here.\n")


def run_main(argv: list[str], gh=None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    original = ud.run_gh
    if gh is not None:
        ud.run_gh = gh
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ud.main(argv)
    finally:
        ud.run_gh = original
    return code, out.getvalue(), err.getvalue()


def forge(files: list | None = None, tree: list | None = None, head: str = HEAD, fail: bool = False, page: int = ud.PAGE_SIZE):
    """A forge in a function: the head SHA, the paginated compare and the tree."""
    calls: list[list[str]] = []

    def gh(args, cwd, timeout):
        calls.append(list(args))
        if fail:
            return subprocess.CompletedProcess(args, 1, "", "boom")
        endpoint = args[-1]
        if "/commits/HEAD" in endpoint:
            return subprocess.CompletedProcess(args, 0, head + "\n", "")
        if "/compare/" in endpoint:
            number = int(endpoint.rsplit("page=", 1)[1])
            chunk = (files or [])[(number - 1) * page:number * page]
            return subprocess.CompletedProcess(args, 0, json.dumps({"status": "ahead", "files": chunk}), "")
        if "/git/trees/" in endpoint:
            return subprocess.CompletedProcess(args, 0, json.dumps({"sha": head, "tree": tree or [], "truncated": False}), "")
        return subprocess.CompletedProcess(args, 1, "", "unknown endpoint")

    gh.calls = calls
    return gh


def write(name: str, text: str) -> str:
    path = ROOT / name
    path.write_text(text)
    return str(path)


# ---------------------------------------------------------------- NOTICE line

@case("notice: the line is parsed into repo, commit, path, version and date wherever it sits")
def _():
    assert NOTICE == {"repo": "acme/widgets", "commit": "abc1234", "path": "kit", "version": "1.2.3", "date": "2026-03-04"}, NOTICE
    nested = ud.parse_notice("x\nUpstream last read: o/r@" + HEAD + " path a/b/c version 0.15.46 on 2026-11-23\n")
    assert nested["path"] == "a/b/c" and nested["commit"] == HEAD and nested["version"] == "0.15.46", nested


@case("notice: the line shipped in NOTICE parses and names the upstream the text above it names")
def _():
    info = ud.parse_notice((PLUGIN / "NOTICE").read_text())
    assert info["repo"] == "cursor/plugins" and info["path"] == "pstack" and len(info["commit"]) >= 7, info


@case("notice: a missing line is an error that names the marker")
def _():
    for text in ("", "plumb\n\nno such line\n", " Upstream last read: acme/widgets@abc1234 path kit version 1 on 2026-03-04\n"):
        try:
            ud.parse_notice(text)
        except ud.NoticeError as error:
            assert "Upstream last read:" in str(error), error
        else:
            raise AssertionError(f"accepted {text!r}")


@case("notice: a malformed line, a bad date, a path escaping the repository and a second line are all errors")
def _():
    bad = [
        "Upstream last read: acme/widgets@abc1234 path kit version 1.2.3",  # no date
        "Upstream last read: acme/widgets@abc12 path kit version 1.2.3 on 2026-03-04",  # commit too short
        "Upstream last read: acme/widgets@ABC1234 path kit version 1.2.3 on 2026-03-04",  # not lowercase hex
        "Upstream last read: widgets@abc1234 path kit version 1.2.3 on 2026-03-04",  # no owner
        "Upstream last read: acme/widgets@abc1234 path kit version 1.2.3 on 2026-13-40",  # not a calendar date
        "Upstream last read: acme/widgets@abc1234 path ../kit version 1.2.3 on 2026-03-04",  # leaves the repository
        "Upstream last read: acme/widgets@abc1234 path kit/../x version 1.2.3 on 2026-03-04",
        "Upstream last read: acme/widgets@abc1234 path kit version 1.2.3 on 2026-03-04 extra",
        "Upstream last read: acme/widgets@abc1234  path kit version 1.2.3 on 2026-03-04",
        LINE + "\n" + LINE,
    ]
    for text in bad:
        try:
            ud.parse_notice(text + "\n")
        except ud.NoticeError:
            continue
        raise AssertionError(f"accepted {text!r}")


# ---------------------------------------------------------------- grouping and statuses

@case("classify: skills, playbooks, principles, agents, docs and other")
def _():
    expect = {"skills/alpha-tool/SKILL.md": "skills", "skills/alpha-tool/references/notes.md": "skills",
              "skills/hub/playbooks/first-aid.md": "playbooks", "skills/principle-keep-it-small/SKILL.md": "principles",
              "agents/scribe.md": "agents", "docs/guide/01-start.md": "docs", "README.md": "other", "plugin.json": "other",
              "skills/loose.md": "other", "automations/x/playbooks/y.md": "playbooks", "assets/logo.png": "other"}
    for rel, group in expect.items():
        assert ud.classify(rel) == group, (rel, ud.classify(rel))


@case("changes: grouped in the stated order, sorted inside a group, every status kept")
def _():
    files = [entry("kit/README.md"), entry("kit/docs/guide/01-start.md", "added"), entry("kit/agents/scribe.md", "removed"),
             entry("kit/skills/principle-keep-it-small/SKILL.md"), entry("kit/skills/hub/playbooks/first-aid.md", "added"),
             entry("kit/skills/zeta/SKILL.md", "added"), entry("kit/skills/alpha-tool/SKILL.md"), entry("kit/skills/hub/playbooks/cleanup.md")]
    rows = ud.changes_from_files(files, "kit")
    got = [(r["group"], r["status"], r["path"]) for r in rows]
    assert got == [
        ("skills", "modified", "kit/skills/alpha-tool/SKILL.md"), ("skills", "added", "kit/skills/zeta/SKILL.md"),
        ("playbooks", "modified", "kit/skills/hub/playbooks/cleanup.md"), ("playbooks", "added", "kit/skills/hub/playbooks/first-aid.md"),
        ("principles", "modified", "kit/skills/principle-keep-it-small/SKILL.md"), ("agents", "removed", "kit/agents/scribe.md"),
        ("docs", "added", "kit/docs/guide/01-start.md"), ("other", "modified", "kit/README.md")], got


@case("changes: a rename carries the old name and shows old -> new; copied and changed map to known statuses")
def _():
    files = [entry("kit/skills/new-name/SKILL.md", "renamed", old="kit/skills/old-name/SKILL.md"),
             entry("kit/agents/b.md", "copied"), entry("kit/agents/c.md", "changed")]
    rows = ud.changes_from_files(files, "kit")
    assert rows[0] == {"group": "skills", "status": "renamed", "path": "kit/skills/new-name/SKILL.md",
                       "previous_path": "kit/skills/old-name/SKILL.md"}, rows
    assert [(r["status"], r["previous_path"]) for r in rows[1:]] == [("added", None), ("modified", None)], rows
    doc = ud.build_changes(NOTICE, HEAD, files)
    assert "renamed\tkit/skills/old-name/SKILL.md -> kit/skills/new-name/SKILL.md" in ud.render_changes(doc).splitlines()


@case("changes: a rename across the boundary counts when either name is under the path")
def _():
    into = ud.changes_from_files([entry("kit/docs/a.md", "renamed", old="elsewhere/a.md")], "kit")
    out = ud.changes_from_files([entry("elsewhere/b.md", "renamed", old="kit/agents/b.md")], "kit")
    assert [(r["group"], r["status"]) for r in into] == [("docs", "renamed")], into
    assert [(r["group"], r["status"]) for r in out] == [("agents", "renamed")], out


@case("changes: files outside the path are ignored, including a sibling directory that shares the prefix")
def _():
    files = [entry("other/skills/x/SKILL.md"), entry("kit-extra/skills/x/SKILL.md"), entry("kit"), entry("README.md"),
             entry("kit/skills/x/SKILL.md"), "not a dict", {"status": "added"}, {"filename": 3}]
    rows = ud.changes_from_files(files, "kit")
    assert [r["path"] for r in rows] == ["kit/skills/x/SKILL.md"], rows


@case("render: group headings, tab-separated rows and a summary with counts and the head SHA")
def _():
    files = [entry("kit/skills/a/SKILL.md"), entry("kit/skills/b/SKILL.md", "added"), entry("kit/agents/c.md", "removed")]
    text = ud.render_changes(ud.build_changes(NOTICE, HEAD, files))
    lines = text.splitlines()
    assert lines[:3] == ["# skills (2)", "modified\tkit/skills/a/SKILL.md", "added\tkit/skills/b/SKILL.md"], lines
    assert lines[3:5] == ["# agents (1)", "removed\tkit/agents/c.md"], lines
    assert lines[-1] == (f"upstream: 3 files changed under kit since abc1234 (skills 2, playbooks 0, principles 0, agents 1, "
                         f"docs 0, other 0); head {HEAD}"), lines[-1]
    assert not any(line.startswith("# docs") for line in lines), "an empty group is not printed"


@case("render: nothing changed under the path prints the one-line answer, even when files changed elsewhere")
def _():
    for files in ([], [entry("README.md"), entry("elsewhere/x.md")]):
        text = ud.render_changes(ud.build_changes(NOTICE, HEAD, files))
        assert text == "upstream: no changes under kit since abc1234", text
    assert ud.render_changes(ud.build_changes(NOTICE, HEAD, [entry("README.md"), entry("kit/README.md")])).splitlines()[0] == "# other (1)", \
        "one file under the path is a change, so the answer above is not a constant"


@case("render: a control character in a forge path never reaches the terminal")
def _():
    text = ud.render_changes(ud.build_changes(NOTICE, HEAD, [entry("kit/skills/a\x1b[2J\nb/SKILL.md")]))
    assert "\x1b" not in text and text.splitlines()[1] == "modified\tkit/skills/a?[2J?b/SKILL.md", repr(text)


# ---------------------------------------------------------------- the forge

@contextlib.contextmanager
def page_size(size: int):
    saved, ud.PAGE_SIZE = ud.PAGE_SIZE, size
    try:
        yield
    finally:
        ud.PAGE_SIZE = saved


@case("fetch_files: pages are followed until a short page, and the compare names the resolved head")
def _():
    files = [entry(f"kit/docs/f{i:03}.md") for i in range(25)]
    with page_size(10):
        gh = forge(files=files, page=10)
        got = ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18, gh=gh)
    assert got == files and len(gh.calls) == 3, (len(got), gh.calls)
    assert gh.calls[0][-1] == f"repos/acme/widgets/compare/abc1234...{HEAD}?per_page=10&page=1", gh.calls[0]
    one = forge(files=files[:5])
    assert ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18, gh=one) == files[:5] and len(one.calls) == 1


@case("fetch_files: a page that is exactly full asks for the next one and stops on the empty page")
def _():
    files = [entry(f"kit/docs/f{i:03}.md") for i in range(20)]
    with page_size(10):
        gh = forge(files=files, page=10)
        assert ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18, gh=gh) == files and len(gh.calls) == 3, gh.calls


def first_page_forge(files: list, later: dict | None = None):
    """The compare as the forge serves it in practice: every file on page 1 (capped at 300), and on later pages no
    `files` at all (or whatever `later` says)."""
    calls: list[list[str]] = []

    def gh(args, cwd, timeout):
        calls.append(list(args))
        endpoint = args[-1]
        if "/commits/HEAD" in endpoint:
            return subprocess.CompletedProcess(args, 0, HEAD + "\n", "")
        if "/compare/" in endpoint:
            if endpoint.endswith("page=1"):
                return subprocess.CompletedProcess(args, 0, json.dumps({"status": "ahead", "files": files[:ud.FILES_CAP]}), "")
            return subprocess.CompletedProcess(args, 0, json.dumps(later if later is not None else {"status": "ahead", "total_commits": 4}), "")
        return subprocess.CompletedProcess(args, 1, "", "unknown endpoint")

    gh.calls = calls
    return gh


@case("fetch_files: a later page with no `files` key or an empty list ends the pagination; the answer is not `unavailable`")
def _():
    files = [entry(f"kit/docs/f{i:03}.md") for i in range(150)]
    for later in (None, {"files": []}, {"files": None}):
        gh = first_page_forge(files, later)
        assert ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18, gh=gh) == files and len(gh.calls) == 2, (later, gh.calls)
        code, out, _ = run_main(["--notice", write("notice-p2", NOTICE_TEXT), "--json"], first_page_forge(files, later))
        doc = json.loads(out)
        assert code == 0 and doc["remote"] == "ok" and doc["total"] == 150 and doc["truncated"] is False, (later, doc)
        assert "truncated" not in ud.render_changes(doc), "a complete list must not claim to be cut"
    gh = first_page_forge(files, {"files": "not a list"})
    try:
        ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18, gh=gh)
    except ValueError:
        pass
    else:
        raise AssertionError("a later page whose files is not a list was accepted")


@case("truncated: at the forge's 300-file cap the summary line and the JSON say so; the list is never shown as complete")
def _():
    notice = write("notice-cap", NOTICE_TEXT)
    note = "list truncated by the forge at 300 files; read the rest in a clone"
    files = [entry(f"kit/docs/f{i:03}.md") for i in range(300)]
    gh = first_page_forge(files)
    assert ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18, gh=gh) == files and len(gh.calls) == 1, "no page 2 at the cap"
    code, out, _ = run_main(["--notice", notice], first_page_forge(files))
    lines = out.splitlines()
    assert code == 0 and lines[-1].startswith("upstream: 300 files changed under kit since abc1234") and lines[-1].endswith(note), lines[-1]
    code, out, _ = run_main(["--notice", notice, "--json"], first_page_forge(files))
    doc = json.loads(out)
    assert code == 0 and doc["remote"] == "ok" and doc["truncated"] is True and doc["total"] == 300, doc
    just_under = files[:299]
    code, out, _ = run_main(["--notice", notice, "--json"], first_page_forge(just_under))
    assert json.loads(out)["truncated"] is False and note not in ud.render_changes(json.loads(out)), out
    # nothing in the listed 300 is under the path: "no changes" would be a claim about files the forge did not list
    elsewhere = [entry(f"elsewhere/f{i:03}.md") for i in range(300)]
    code, out, _ = run_main(["--notice", notice], first_page_forge(elsewhere))
    assert out.strip() != "upstream: no changes under kit since abc1234" and note in out and out.startswith("upstream: no changes"), out
    code, out, _ = run_main(["--notice", notice, "--json"], first_page_forge(elsewhere))
    doc = json.loads(out)
    assert doc["changes"] == [] and doc["truncated"] is True, doc
    # a forge that does return files on later pages is read to the cap and no further
    with page_size(100):
        many = [entry(f"kit/docs/f{i:03}.md") for i in range(450)]
        paged = forge(files=many, page=100)
        got = ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18, gh=paged)
    assert len(got) == 300 and len(paged.calls) == 3, (len(got), paged.calls)


@case("fetch: an error, a head that is not a SHA, an answer with no files and a cut-short tree all raise ValueError")
def _():
    def raises(call):
        try:
            call()
        except ValueError:
            return
        raise AssertionError("did not raise")

    raises(lambda: ud.fetch_head("acme/widgets", 1e18, gh=forge(fail=True)))
    raises(lambda: ud.fetch_head("acme/widgets", 1e18, gh=forge(head="not-a-sha")))
    raises(lambda: ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18, gh=forge(fail=True)))
    raises(lambda: ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18,
                                  gh=lambda a, c, t: subprocess.CompletedProcess(a, 0, "[]", "")))
    raises(lambda: ud.fetch_files("acme/widgets", "abc1234", HEAD, 1e18,
                                  gh=lambda a, c, t: subprocess.CompletedProcess(a, 0, "not json", "")))
    raises(lambda: ud.fetch_tree("acme/widgets", HEAD, 1e18,
                                 gh=lambda a, c, t: subprocess.CompletedProcess(a, 0, json.dumps({"tree": [], "truncated": True}), "")))


# ---------------------------------------------------------------- --unrecorded

@case("unrecorded names: skills, playbooks, principles (prefix stripped), agents and guide pages; nothing else")
def _():
    got = [(n["kind"], n["name"], n["label"]) for n in ud.unrecorded_names(UPSTREAM_TREE, "kit")]
    assert got == [("skill", "alpha-tool", "alpha-tool"), ("skill", "gamma-tool", "gamma-tool"), ("skill", "hub", "hub"),
                   ("playbook", "cleanup", "cleanup"), ("playbook", "first-aid", "first-aid"),
                   ("principle", "count-twice", "principle-count-twice"), ("principle", "keep-it-small", "principle-keep-it-small"),
                   ("agent", "scout", "scout"), ("agent", "scribe", "scribe"),
                   ("guide", "01-start", "01-start"), ("guide", "02-middle", "02-middle")]
    names = {(k, n) for k, n, _ in got}
    assert ("guide", "README") not in names and ("agent", "notes") not in names and ("skill", "zeta-tool") not in names, got
    assert {k for k, _, _ in got} == {"skill", "playbook", "principle", "agent", "guide"}, got
    assert len(got) == 11, got


@case("unrecorded: a name that occurs nowhere in scope.md is listed; one that occurs as a whole name is not")
def _():
    doc = ud.build_unrecorded(NOTICE, HEAD, UPSTREAM_TREE, SCOPE)
    listed = {(n["kind"], n["name"]) for n in doc["unrecorded"]}
    assert listed == {("skill", "gamma-tool"), ("playbook", "cleanup"), ("principle", "principle-count-twice"), ("agent", "scout"),
                      ("guide", "01-start"), ("guide", "02-middle")}, listed
    assert doc["checked"] == 11 and doc["counts"] == {"skill": 1, "playbook": 1, "principle": 1, "agent": 1, "guide": 2}, doc
    # `alpha-tool` (skill), `hub`, `first-aid` (playbook), `keep-it-small` (principle) and `scribe` (agent) are recorded.
    assert ("skill", "alpha-tool") not in listed and ("playbook", "first-aid") not in listed


@case("unrecorded: a name only inside a longer word or hyphenated name does not count as recorded")
def _():
    assert ud.mentioned("hub", "the hub is here") and ud.mentioned("hub", "`hub`.") and ud.mentioned("a-b", "x a-b, y")
    assert not ud.mentioned("hub", "github") and not ud.mentioned("hub", "hub-two") and not ud.mentioned("hub", "two-hub")
    assert not ud.mentioned("count-twice", "recount-twice") and ud.mentioned("count-twice", "principle-count-twice") is False


@case("unrecorded: everything recorded prints the one-line answer; the table is `kind<TAB>name` plus a summary")
def _():
    all_names = " ".join(n["name"] for n in ud.unrecorded_names(UPSTREAM_TREE, "kit"))
    done = ud.build_unrecorded(NOTICE, HEAD, UPSTREAM_TREE, all_names)
    assert done["unrecorded"] == [] and ud.render_unrecorded(done) == (
        f"upstream: every one of 11 names under kit is in docs/scope.md (head {HEAD})"), ud.render_unrecorded(done)
    lines = ud.render_unrecorded(ud.build_unrecorded(NOTICE, HEAD, UPSTREAM_TREE, SCOPE)).splitlines()
    assert lines[0] == "skill\tgamma-tool" and "principle\tprinciple-count-twice" in lines and "guide\t01-start" in lines, lines
    assert lines[-1] == (f"upstream: 6 of 11 names under kit are not in docs/scope.md (skill 1, playbook 1, principle 1, agent 1, "
                         f"guide 2); head {HEAD}"), lines[-1]


# ---------------------------------------------------------------- the command

@case("command: end to end on a synthetic forge, text and --json, and the compare uses the resolved head")
def _():
    notice = write("notice-ok", NOTICE_TEXT)
    files = [entry("kit/skills/a/SKILL.md", "added"), entry("kit/skills/n/SKILL.md", "renamed", old="kit/skills/o/SKILL.md"),
             entry("elsewhere/x.md"), entry("kit/agents/scribe.md", "removed"), entry("kit/README.md")]
    gh = forge(files=files)
    code, out, err = run_main(["--notice", notice], gh)
    assert code == 0 and err == "" and out.splitlines()[0] == "# skills (2)", (code, out, err)
    assert "# agents (1)" in out.splitlines() and "# other (1)" in out.splitlines() and "# docs (1)" not in out.splitlines(), out
    assert gh.calls[0][-1].endswith("/commits/HEAD") and f"abc1234...{HEAD}" in gh.calls[1][-1], gh.calls
    code, out, _ = run_main(["--notice", notice, "--json"], forge(files=files))
    doc = json.loads(out)
    assert code == 0 and doc["remote"] == "ok" and doc["repo"] == "acme/widgets" and doc["path"] == "kit", doc
    assert doc["since"] == "abc1234" and doc["head"] == HEAD and doc["version"] == "1.2.3" and doc["read_on"] == "2026-03-04", doc
    assert doc["total"] == 4 and doc["counts"] == {"skills": 2, "playbooks": 0, "principles": 0, "agents": 1, "docs": 0, "other": 1}, doc
    assert doc["changes"][1] == {"group": "skills", "status": "renamed", "path": "kit/skills/n/SKILL.md",
                                 "previous_path": "kit/skills/o/SKILL.md"}, doc["changes"]
    code, out, _ = run_main(["--notice", notice], forge(files=[]))
    assert code == 0 and out.strip() == "upstream: no changes under kit since abc1234", out
    code, out, _ = run_main(["--notice", notice, "--json"], forge(files=[entry("README.md")]))
    doc = json.loads(out)
    assert doc["changes"] == [] and doc["total"] == 0 and doc["remote"] == "ok", doc


@case("command: --unrecorded end to end, text and --json, against a synthetic scope.md")
def _():
    notice, scope = write("notice-u", NOTICE_TEXT), write("scope-u.md", SCOPE)
    code, out, err = run_main(["--notice", notice, "--scope", scope, "--unrecorded"], forge(tree=UPSTREAM_TREE))
    assert code == 0 and err == "" and "skill\tgamma-tool" in out.splitlines() and "agent\tscout" in out.splitlines(), (code, out, err)
    code, out, _ = run_main(["--notice", notice, "--scope", scope, "--unrecorded", "--json"], forge(tree=UPSTREAM_TREE))
    doc = json.loads(out)
    assert code == 0 and doc["remote"] == "ok" and doc["head"] == HEAD and doc["checked"] == 11, doc
    assert doc["unrecorded"][0] == {"kind": "skill", "name": "gamma-tool"} and set(doc["counts"]) == set(ud.KINDS), doc
    assert set(doc) == {"remote", "repo", "path", "head", "checked", "unrecorded", "counts"}, sorted(doc)


@case("command: a missing or malformed NOTICE line, or an unreadable file, is exit 2 with a message and no traceback")
def _():
    for name, text in (("notice-none", "plumb\n"), ("notice-bad", "Upstream last read: acme/widgets@abc1234 path kit\n")):
        code, out, err = run_main(["--notice", write(name, text)], forge())
        assert code == 2 and out == "" and "Upstream last read:" in err and "Traceback" not in err, (code, out, err)
    code, out, err = run_main(["--notice", str(ROOT / "absent")], forge())
    assert code == 2 and out == "" and "cannot read" in err, (code, out, err)
    code, out, err = run_main(["--notice", write("notice-s", NOTICE_TEXT), "--scope", str(ROOT / "absent.md"), "--unrecorded"], forge())
    assert code == 2 and out == "" and "cannot read" in err, (code, out, err)


@case("command: gh missing, failing or answering garbage is `remote: unavailable` and exit 0, in text and in JSON, for both views")
def _():
    notice, scope = write("notice-g", NOTICE_TEXT), write("scope-g.md", SCOPE)

    def missing(args, cwd, timeout):
        raise FileNotFoundError("gh")

    def slow(args, cwd, timeout):
        raise subprocess.TimeoutExpired(args, timeout)

    def garbage(args, cwd, timeout):
        return subprocess.CompletedProcess(args, 0, "<html>rate limit</html>", "")

    for gh in (missing, slow, garbage, forge(fail=True)):
        for extra in ([], ["--unrecorded"]):
            code, out, err = run_main(["--notice", notice, "--scope", scope, *extra], gh)
            assert code == 0 and out.strip() == "remote: unavailable" and "Traceback" not in err, (code, out, err)
            code, out, _ = run_main(["--notice", notice, "--scope", scope, "--json", *extra], gh)
            doc = json.loads(out)
            assert code == 0 and doc["remote"] == "unavailable" and doc["repo"] == "acme/widgets" and "changes" not in doc \
                and "unrecorded" not in doc, doc


@case("command: it writes nothing, neither NOTICE nor scope.md nor the working directory")
def _():
    notice, scope = write("notice-w", NOTICE_TEXT), write("scope-w.md", SCOPE)
    before = (Path(notice).read_bytes(), Path(scope).read_bytes(), sorted(p.name for p in ROOT.iterdir()))
    run_main(["--notice", notice, "--scope", scope], forge(files=[entry("kit/skills/a/SKILL.md")]))
    run_main(["--notice", notice, "--scope", scope, "--unrecorded", "--json"], forge(tree=UPSTREAM_TREE))
    assert (Path(notice).read_bytes(), Path(scope).read_bytes(), sorted(p.name for p in ROOT.iterdir())) == before


# ---------------------------------------------------------------- the wrapper, with a fake gh program first on PATH

FAKE_GH = '''#!{python}
import json, os, sys
d = os.environ["FAKE_GH_DIR"]
if os.path.exists(os.path.join(d, "fail")):
    sys.exit(1)
endpoint = sys.argv[-1]
if "/commits/HEAD" in endpoint:
    print(open(os.path.join(d, "head")).read().strip())
elif "/compare/" in endpoint:
    files = json.load(open(os.path.join(d, "files.json")))
    print(json.dumps({{"status": "ahead", "files": files}}))
elif "/git/trees/" in endpoint:
    print(json.dumps({{"tree": json.load(open(os.path.join(d, "tree.json"))), "truncated": False}}))
else:
    sys.exit(1)
'''


def fake_env(name: str, files: list | None = None, tree: list | None = None, fail: bool = False) -> dict:
    base = ROOT / name
    (base / "bin").mkdir(parents=True)
    (base / "bin" / "gh").write_text(FAKE_GH.format(python=sys.executable))
    (base / "bin" / "gh").chmod(0o755)
    (base / "head").write_text(HEAD)
    (base / "files.json").write_text(json.dumps(files or []))
    (base / "tree.json").write_text(json.dumps(tree or []))
    if fail:
        (base / "fail").write_text("")
    return {**os.environ, "PATH": f"{base / 'bin'}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_DIR": str(base)}


@case("wrapper: through a symlink and a fake gh on PATH, both views and --json work and write nothing to stderr")
def _():
    assert os.access(BIN, os.X_OK)
    link = ROOT / "plumb-upstream-diff"
    link.symlink_to(BIN)
    notice, scope = write("notice-cli", NOTICE_TEXT), write("scope-cli.md", SCOPE)
    env = fake_env("fake1", files=[entry("kit/agents/scribe.md", "modified"), entry("kit/docs/guide/01-start.md", "added")],
                   tree=UPSTREAM_TREE)
    out = subprocess.run([str(link), "--notice", notice], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and out.stderr == "" and "modified\tkit/agents/scribe.md" in out.stdout.splitlines(), out
    out = subprocess.run([str(link), "--notice", notice, "--json"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and json.loads(out.stdout)["total"] == 2, out
    out = subprocess.run([str(link), "--notice", notice, "--scope", scope, "--unrecorded", "--json"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and json.loads(out.stdout)["unrecorded"][0]["name"] == "gamma-tool", out


@case("wrapper: a failing gh and no gh at all are `remote: unavailable`; bad usage is exit 2")
def _():
    notice = write("notice-cli2", NOTICE_TEXT)
    script = str(HERE / "upstream-diff.py")
    out = subprocess.run([sys.executable, script, "--notice", notice], capture_output=True, text=True, env=fake_env("fake2", fail=True))
    assert out.returncode == 0 and out.stdout.strip() == "remote: unavailable" and out.stderr == "", out
    nogh = subprocess.run([sys.executable, script, "--notice", notice, "--json"], capture_output=True, text=True,
                          env={**os.environ, "PATH": str(ROOT / "empty")})
    assert nogh.returncode == 0 and json.loads(nogh.stdout)["remote"] == "unavailable" and "Traceback" not in nogh.stderr, nogh
    bad = subprocess.run([sys.executable, script, "--bogus"], capture_output=True, text=True)
    assert bad.returncode == 2 and "usage" in bad.stderr and "Traceback" not in bad.stderr, bad
    none = subprocess.run([sys.executable, script, "--notice", write("notice-cli3", "plumb\n")], capture_output=True, text=True)
    assert none.returncode == 2 and "Upstream last read:" in none.stderr, none


@case("wrapper: it runs python with -B and leaves no bytecode in the install")
def _():
    install = ROOT / "install"
    shutil.copytree(PLUGIN / "bin", install / "bin")
    shutil.copytree(HERE, install / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    assert "exec python3 -B " in (install / "bin" / "plumb-upstream-diff").read_text()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    done = subprocess.run([str(install / "bin" / "plumb-upstream-diff"), "--help"], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done
    leftover = sorted(str(p.relative_to(install)) for p in install.rglob("__pycache__")) + sorted(str(p) for p in install.rglob("*.pyc"))
    assert leftover == [], leftover


shutil.rmtree(ROOT, ignore_errors=True)
if FAILED:
    print(f"\n{len(FAILED)} case(s) failed")
    sys.exit(1)
print("\nall cases ok")
