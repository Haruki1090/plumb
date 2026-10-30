#!/usr/bin/env python3
"""Offline tests for `plumb-ledger changes` and `plumb-ledger rework` (scripts/ledger_changes.py).

    python3 -B scripts/test-ledger-changes.py

Prints one `ok` or `NG` line per case and exits 1 when any case is NG. No network: gh answers from
the fixtures in scripts/fixtures/ledger-changes/gh (see PLUMB_LEDGER_GH_FIXTURES in the module), and
the git history is built in throwaway repositories under tempfile.mkdtemp(). The fixture files carry
@NAME@ placeholders for commit ids, which only exist once the history is built.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = HERE / "fixtures" / "ledger-changes"
LEDGER = HERE / "ledger.py"

CLAUDE = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
CODEX = "Co-Authored-By: Codex <codex@openai.com>"
CURSOR = "Co-Authored-By: Cursor Agent <cursoragent@cursor.com>"
SESSION_A = "https://claude.ai/code/session_AAA"
SESSION_B = "https://claude.ai/code/session_BBB"
RECORD_KEYS = ["kind", "number", "author", "merged_at", "merge_commit", "landing", "head_ref", "created_at",
               "closed_at", "classes", "agents", "co_authors", "sessions", "attribution", "sources",
               "fixes_pr", "fixes_pr_error"]

spec = importlib.util.spec_from_file_location("ledger_changes", HERE / "ledger_changes.py")
module = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(HERE))
spec.loader.exec_module(module)

TMP = Path(tempfile.mkdtemp(prefix="plumb-ledger-changes-"))
GIT_ENV = dict(os.environ, HOME=str(TMP), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="Tester", GIT_AUTHOR_EMAIL="tester@example.com",
               GIT_COMMITTER_NAME="Tester", GIT_COMMITTER_EMAIL="tester@example.com")
CASES: list = []
WORLD: dict = {}


def case(function):
    CASES.append(function)
    return function


def need(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def same(actual, expected, what: str) -> None:
    if actual != expected:
        raise AssertionError(f"{what}: expected {expected!r}, got {actual!r}")


# ---------------------------------------------------------------------------------------------
# throwaway repositories


def git(cwd, *args: str, when: str | None = None, who: str | None = None) -> str:
    env = dict(GIT_ENV)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    if who:
        env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = who
    done = subprocess.run(["git", "-C", str(cwd), "-c", "commit.gpgsign=false", *args], env=env,
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def commit(repo: Path, path: str, message: str, when: str, who: str = "Tester") -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{path} {when}\n")
    git(repo, "add", path)
    git(repo, "commit", "-m", message, when=when, who=who)
    return git(repo, "rev-parse", "HEAD")


def build_world() -> None:
    origin = TMP / "origin.git"
    work = TMP / "work"
    git(TMP, "init", "--bare", "-b", "develop", str(origin))
    git(TMP, "init", "-b", "develop", str(work))
    shas: dict = {}
    shas["OLD"] = commit(work, "OLD.md", "chore: root", "2026-09-01T10:00:00+0000")
    shas["C0"] = commit(work, "README.md", "chore: init", "2026-09-20T10:00:00+0000")
    shas["D1"] = commit(work, "docs/direct.md", f"docs: direct tweak\n\n{CLAUDE}", "2026-10-02T10:00:00+0000", "Dana")
    # #1 lands as a merge commit
    git(work, "checkout", "-b", "feat/m")
    shas["A1"] = commit(work, "frontend/a.ts", f"feat: m1\n\n{CLAUDE}\nClaude-Session: {SESSION_A}", "2026-10-03T09:00:00+0000")
    shas["A2"] = commit(work, "docs/m.md", f"docs: m2\n\n{CODEX}", "2026-10-03T11:00:00+0000")
    git(work, "checkout", "develop")
    git(work, "merge", "--no-ff", "feat/m", "-m", "Merge pull request #1 from acme/feat/m", when="2026-10-04T10:00:00+0000")
    shas["M1"] = git(work, "rev-parse", "HEAD")
    # #2 lands as a squash: one new commit whose message holds none of the pull request's trailers
    git(work, "checkout", "-b", "feat/s")
    shas["S1"] = commit(work, "frontend/s.ts", f"feat: s1\n\n{CLAUDE}", "2026-10-05T09:00:00+0000")
    shas["S2"] = commit(work, "src/s.py", f"fix: s2\n\n{CURSOR}", "2026-10-05T11:00:00+0000")
    git(work, "checkout", "develop")
    git(work, "merge", "--squash", "feat/s")
    git(work, "commit", "-m", "feat: s (#2)", when="2026-10-06T10:00:00+0000")
    shas["SQ"] = git(work, "rev-parse", "HEAD")
    # #3 lands as a rebase: the commits are rewritten, so their ids change but their messages do not
    git(work, "checkout", "-b", "feat/r")
    shas["R1"] = commit(work, "src/r1.py", f"feat: r1\n\n{CODEX}", "2026-10-07T09:00:00+0000")
    shas["R2"] = commit(work, "src/r2.py", "feat: r2", "2026-10-07T11:00:00+0000")
    git(work, "checkout", "develop")
    git(work, "cherry-pick", shas["R1"], shas["R2"], when="2026-10-08T10:00:00+0000")
    shas["R2P"] = git(work, "rev-parse", "HEAD")
    shas["R1P"] = git(work, "rev-parse", "HEAD~1")
    # #4 lands as a merge commit; the pull request has three commits, the fixture returns two
    git(work, "checkout", "-b", "feat/x")
    shas["X1"] = commit(work, "frontend/x.ts", f"feat: x1\n\n{CLAUDE}\nClaude-Session: {SESSION_B}", "2026-10-09T09:00:00+0000")
    shas["X2"] = commit(work, "docs/x.md", "chore: x2", "2026-10-09T10:00:00+0000")
    shas["X3"] = commit(work, "src/x.py", f"feat: x3\n\n{CURSOR}", "2026-10-09T11:00:00+0000")
    git(work, "checkout", "develop")
    git(work, "merge", "--no-ff", "feat/x", "-m", "Merge pull request #4 from acme/feat/x", when="2026-10-10T10:00:00+0000")
    shas["M4"] = git(work, "rev-parse", "HEAD")
    shas["D2"] = commit(work, "src/d2.py", "fix: direct two", "2026-10-12T10:00:00+0000", "Eve")
    # 01:00 on 1 November in Tokyo: outside the period there, inside it in UTC
    shas["D3"] = commit(work, "src/d3.py", "chore: after the period in Tokyo", "2026-10-31T16:00:00+0000", "Dana")
    git(work, "remote", "add", "origin", f"file://{origin}")
    git(work, "push", "origin", "develop")

    gh = TMP / "gh"
    shutil.copytree(FIXTURES / "gh", gh)
    for path in gh.glob("*.json"):
        text = path.read_text()
        for name, sha in shas.items():
            text = text.replace(f"@{name}@", sha)
        path.write_text(text)

    chain = git(work, "rev-list", "--first-parent", "--count", "develop")
    WORLD.update(shas=shas, gh=gh, origin=origin, full=TMP / "full", plain=TMP / "plain",
                 shallow=TMP / "shallow", reach=TMP / "reach")
    for name, extra in (("full", []), ("plain", []), ("shallow", ["--depth", "2"]),
                        ("reach", ["--depth", str(int(chain) - 1)])):
        git(TMP, "clone", "-q", *extra, f"file://{origin}", str(WORLD[name]))
    (WORLD["full"] / ".plumb").mkdir()
    shutil.copy(FIXTURES / "contract" / "project.toml", WORLD["full"] / ".plumb" / "project.toml")


# ---------------------------------------------------------------------------------------------
# running the tool


def run_changes(clone: Path, *extra: str, fixtures: Path | None = None) -> subprocess.CompletedProcess:
    command = [sys.executable, "-B", str(LEDGER), "changes", "--repo", "acme/app", "--since", "2026-10-01",
               "--until", "2026-10-31", "--clone", str(clone), *extra]
    env = dict(os.environ, PLUMB_LEDGER_GH_FIXTURES=str(fixtures or WORLD["gh"]))
    return subprocess.run(command, capture_output=True, text=True, env=env, cwd=str(TMP))


def records_of(done: subprocess.CompletedProcess) -> list:
    if done.returncode != 0:
        raise AssertionError(f"exit {done.returncode}: {done.stderr.strip()}")
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def full_run() -> subprocess.CompletedProcess:
    if "full_done" not in WORLD:
        WORLD["full_done"] = run_changes(WORLD["full"])
    return WORLD["full_done"]


def pulls() -> dict:
    return {r["number"]: r for r in records_of(full_run()) if r["kind"] == "pull_request"}


def directs(done: subprocess.CompletedProcess) -> list:
    return [r for r in records_of(done) if r["kind"] == "direct"]


# ---------------------------------------------------------------------------------------------
# changes


@case
def merge_landing_yields_the_pull_requests_trailers():
    record = pulls()[1]
    same(record["landing"], "merge", "landing")
    same(record["merge_commit"], WORLD["shas"]["M1"], "merge_commit")
    same(record["agents"], ["claude", "codex"], "agents")
    same(record["co_authors"], ["Claude Opus 5.5 <noreply@anthropic.com>", "Codex <codex@openai.com>"], "co_authors")
    same(record["sessions"], [SESSION_A], "sessions")
    same((record["attribution"], record["sources"]), ("complete", ["pulls_commits"]), "attribution, sources")
    same((record["author"], record["head_ref"], record["merged_at"]), ("alice", "feat/m", "2026-10-04T10:00:00Z"), "identity")


@case
def squash_landing_yields_the_pull_requests_trailers():
    record = pulls()[2]
    same(record["landing"], "squash", "landing")
    same(record["merge_commit"], WORLD["shas"]["SQ"], "merge_commit")
    same(record["agents"], ["claude", "cursor"], "agents")
    same(record["co_authors"], ["Claude Opus 5.5 <noreply@anthropic.com>", "Cursor Agent <cursoragent@cursor.com>"], "co_authors")
    same((record["attribution"], record["sources"]), ("complete", ["pulls_commits"]), "attribution, sources")


@case
def rebase_landing_yields_the_pull_requests_trailers():
    record = pulls()[3]
    same(record["landing"], "rebase", "landing")
    same(record["merge_commit"], WORLD["shas"]["R2P"], "merge_commit")
    need(WORLD["shas"]["R1"] != WORLD["shas"]["R1P"], "the rebase fixture must rewrite the commits")
    same(record["agents"], ["codex"], "agents")
    same(record["co_authors"], ["Codex <codex@openai.com>"], "co_authors")
    same(record["attribution"], "complete", "attribution")


@case
def commit_count_mismatch_is_incomplete_and_lists_both_sources():
    record = pulls()[4]
    same(record["landing"], "merge", "landing")
    same(record["attribution"], "incomplete", "attribution")
    same(record["sources"], ["pulls_commits", "landed_history"], "sources")
    # x3 is not in the REST answer: only the landed history can name the third agent
    same(record["agents"], ["claude", "cursor"], "agents")
    same(record["sessions"], [SESSION_B], "sessions")


@case
def pagination_reads_every_page_of_every_list():
    done = full_run()
    same(sorted(pulls()), [1, 2, 3, 4, 7], "pull requests (the list has two pages; #1 is on page 2)")
    names = sorted(p.name for p in WORLD["gh"].glob("*.json"))
    for stem in ("pulls", "pulls__1__commits", "pulls__1__files"):
        need(f"repos__acme__app__{stem}.page1.json" in names and f"repos__acme__app__{stem}.page2.json" in names,
             f"fixture {stem} must have two pages")
    record = pulls()[1]
    need("Codex <codex@openai.com>" in record["co_authors"], "the commit on page 2 of #1 was read")
    need("docs" in record["classes"], "the file on page 2 of #1 was read")
    need(done.returncode == 0, "exit 0")


@case
def unmerged_and_out_of_period_pull_requests_are_left_out():
    numbers = sorted(pulls())
    need(5 not in numbers, "#5 was closed without merging")
    need(6 not in numbers, "#6 merged before the period")


@case
def direct_commits_exclude_everything_a_pull_request_landed():
    shas = WORLD["shas"]
    found = sorted(r["merge_commit"] for r in directs(full_run()))
    same(found, sorted([shas["D1"], shas["D2"]]), "direct commits")
    landed = {shas[k] for k in ("M1", "SQ", "R1P", "R2P", "M4")}
    need(not landed & set(found), "a landed commit was reported as direct")
    first = next(r for r in directs(full_run()) if r["merge_commit"] == shas["D1"])
    same((first["number"], first["author"], first["merged_at"], first["landing"]), (None, "Dana", "2026-10-02T10:00:00Z", None), "direct record")
    same((first["agents"], first["classes"], first["fixes_pr"]), (["claude"], ["docs"], None), "direct attribution and classes")


@case
def the_period_follows_ledger_timezone():
    shas = WORLD["shas"]
    tokyo = {r["merge_commit"] for r in directs(full_run())}
    need(shas["D3"] not in tokyo, "01:00 on 1 November in Tokyo is outside the period")
    utc = {r["merge_commit"] for r in directs(run_changes(WORLD["plain"]))}
    need(shas["D3"] in utc, "the same commit is inside the period in UTC")
    need(shas["C0"] not in utc and shas["C0"] not in tokyo, "a commit before the period is never listed")


@case
def classes_use_the_first_matching_rule_as_a_sorted_set():
    found = pulls()
    same(found[1]["classes"], ["docs", "frontend"], "#1 (frontend/a.ts beats **/*.ts)")
    same(found[2]["classes"], ["frontend", "unclassified"], "#2 (src/s.py matches no rule)")
    same(found[4]["classes"], ["docs", "frontend", "unclassified"], "#4")
    same(found[7]["classes"], ["docs", "typescript"], "#7 (README.md, tools/build.ts)")


@case
def without_classify_rules_every_change_is_unclassified_and_the_summary_says_so():
    done = run_changes(WORLD["plain"])
    for record in records_of(done):
        same(record["classes"], ["unclassified"], f"classes of {record['kind']} {record['number']}")
    need("the contract has no classify rules" in done.stderr, "summary line missing: " + done.stderr)


@case
def fixes_pr_is_parsed_with_the_check_fixes_grammar():
    found = pulls()
    same((found[1]["fixes_pr"], found[1]["fixes_pr_error"]), ([], None), "none")
    same((found[2]["fixes_pr"], found[2]["fixes_pr_error"]), ([11, 12], None), "two numbers; the commented-out line and CRLF are ignored")
    need(found[3]["fixes_pr"] is None and "itself" in found[3]["fixes_pr_error"], "self reference is an error: " + str(found[3]["fixes_pr_error"]))
    same((found[4]["fixes_pr"], found[4]["fixes_pr_error"]), (None, None), "no line is null without an error")
    need(found[7]["fixes_pr"] is None and "malformed" in found[7]["fixes_pr_error"], "malformed item: " + str(found[7]["fixes_pr_error"]))
    body = "Fixes-PR: none\nFixes-PR: #4\n"
    need(module.parse_fixes(body, 9)[1] and "more than one" in module.parse_fixes(body, 9)[1], "two lines are an error")
    same(module.parse_fixes(None, 9), (None, None), "no body")
    same(module.parse_fixes("Fixes-PR: #3 ,  #5\r\n", 9), ([3, 5], None), "blanks around items")


@case
def records_hold_only_the_documented_fields_and_no_body_text():
    done = full_run()
    for record in records_of(done):
        same(list(record), RECORD_KEYS, "field order")
    for secret in ("SECRET-BODY-SENTINEL", "Adds m.", "No line here.", "feat: m1", "chore: x2"):
        need(secret not in done.stdout and secret not in done.stderr, f"{secret!r} leaked into the output")


@case
def an_unknown_landing_is_null_and_counted():
    record = pulls()[7]
    same(record["landing"], None, "landing of a merge commit the clone does not have")
    same((record["agents"], record["attribution"], record["sources"]), (["other"], "complete", ["pulls_commits"]), "attribution")
    need("landing unknown 1" in full_run().stderr, "summary does not count it: " + full_run().stderr)


@case
def a_shallow_clone_short_of_the_period_exits_2_naming_the_depth():
    done = run_changes(WORLD["shallow"])
    same(done.returncode, 2, "exit status")
    need("depth 2" in done.stderr, "depth missing: " + done.stderr)
    need("git -C " in done.stderr and "fetch --shallow-since=2026-10-01" in done.stderr, "fetch command missing: " + done.stderr)
    same(done.stdout, "", "nothing is written when the history is short")


@case
def a_shallow_clone_that_reaches_the_period_is_read():
    need(git(WORLD["reach"], "rev-parse", "--is-shallow-repository") == "true", "the clone must really be shallow")
    done = run_changes(WORLD["reach"])
    same(sorted(r["number"] for r in records_of(done) if r["kind"] == "pull_request"), [1, 2, 3, 4, 7], "pull requests")


@case
def the_base_branch_defaults_to_the_repositorys_default_branch():
    other = TMP / "gh-main"
    shutil.copytree(WORLD["gh"], other)
    (other / "repos__acme__app.json").write_text('{"default_branch": "main"}\n')
    done = run_changes(WORLD["plain"], fixtures=other)
    same(done.returncode, 2, "exit status (the clone has no main)")
    need("origin/main" in done.stderr, "the default branch from the API was not used: " + done.stderr)
    same(records_of(run_changes(WORLD["plain"], "--base", "develop"))[0]["kind"], "direct", "--base develop")


@case
def a_missing_fixture_is_an_error_naming_the_endpoint():
    empty = TMP / "gh-empty"
    empty.mkdir()
    done = run_changes(WORLD["full"], fixtures=empty)
    same(done.returncode, 1, "exit status")
    need("no fixture repos__acme__app__pulls.page1.json" in done.stderr, done.stderr)


@case
def the_real_gh_call_is_rest_paged_by_number_and_joins_the_pages():
    # Pages are asked for by number, never with --paginate: --paginate follows Link headers naming
    # repositories/{id}/... paths, which a cloud session's proxy refuses (HTTP 403).
    bin_dir = TMP / "bin"
    bin_dir.mkdir()
    log = TMP / "gh.log"
    stub = bin_dir / "gh"
    stub.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                    "open(os.environ['FAKE_GH_LOG'], 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    "pages = {'1': [{'n': 1}, {'n': 2}], '2': [{'n': 3}, {'n': 4}], '3': [{'n': 5}]}\n"
                    "url = sys.argv[-1]\n"
                    "if 'page=' in url:\n    sys.stdout.write(json.dumps(pages[url.rsplit('page=', 1)[1]]))\n"
                    "else:\n    sys.stdout.write('{\"default_branch\": \"develop\"}')\n")
    stub.chmod(0o755)
    saved = dict(os.environ)
    try:
        os.environ.pop("PLUMB_LEDGER_GH_FIXTURES", None)
        os.environ.update(PATH=str(bin_dir) + os.pathsep + saved["PATH"], FAKE_GH_LOG=str(log))
        joined = module.gh_get("repos/o/r/pulls?state=closed&per_page=2", paginate=True)
        stopped = module.gh_get("repos/o/r/pulls?state=closed&per_page=2", paginate=True,
                                stop=lambda page: page[-1]["n"] >= 2)
        single = module.gh_get("repos/o/r")
    finally:
        os.environ.clear()
        os.environ.update(saved)
    same(joined, [{"n": i} for i in range(1, 6)], "pages joined until a short page")
    same(stopped, [{"n": 1}, {"n": 2}], "stop ends the walk after the page that satisfies it")
    same(single, {"default_branch": "develop"}, "single object")
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    same(calls[:3], [["api", "repos/o/r/pulls?state=closed&per_page=2&page=1"],
                     ["api", "repos/o/r/pulls?state=closed&per_page=2&page=2"],
                     ["api", "repos/o/r/pulls?state=closed&per_page=2&page=3"]], "gh arguments")
    need(not any("--paginate" in part for call in calls for part in call), "--paginate must never be used")
    need(not any("graphql" in part for call in calls for part in call), "GraphQL must never be called")


@case
def classify_globs_match_whole_paths():
    def hit(glob: str, path: str) -> bool:
        return bool(module.glob_to_regex(glob).fullmatch(path))

    need(hit("frontend/**", "frontend/src/a.ts"), "** crosses directories")
    need(not hit("frontend/**", "other/frontend/a.ts"), "anchored at the start")
    need(hit("*.md", "README.md") and not hit("*.md", "docs/x.md"), "* stops at /")
    need(hit("docs/**/*.md", "docs/x.md") and hit("docs/**/*.md", "docs/a/b.md"), "**/ may match no directory")
    need(hit("src/?.py", "src/a.py") and not hit("src/?.py", "src/ab.py"), "? is one character")
    need(hit("a.b", "a.b") and not hit("a.b", "axb"), "dots are literal")
    need(hit("v[12]/x", "v2/x") and not hit("v[12]/x", "v3/x"), "character class")


@case
def help_prints_usage_and_exits_0():
    for command in ("changes", "rework"):
        done = subprocess.run([str(ROOT / "bin" / "plumb-ledger"), command, "--help"], capture_output=True, text=True)
        same(done.returncode, 0, f"{command} --help exit status")
        need("usage:" in done.stdout and "--since" in done.stdout, f"{command} --help prints no usage")


@case
def missing_arguments_are_a_usage_error():
    done = subprocess.run([sys.executable, "-B", str(LEDGER), "changes", "--repo", "acme/app"], capture_output=True, text=True)
    same(done.returncode, 2, "exit status")


# ---------------------------------------------------------------------------------------------
# rework


def rework_repo() -> Path:
    if "rework" not in WORLD:
        repo = TMP / "rework"
        git(TMP, "init", "-b", "develop", str(repo))
        (repo / ".plumb").mkdir()
        shutil.copy(FIXTURES / "rework" / "project.toml", repo / ".plumb" / "project.toml")
        WORLD["rework"] = repo
    return WORLD["rework"]


def run_rework(*extra: str, repo: Path | None = None, now: str = "2026-10-30T00:00:00Z") -> subprocess.CompletedProcess:
    command = [sys.executable, "-B", str(LEDGER), "rework", "--changes", str(FIXTURES / "rework" / "changes.jsonl"),
               "--since", "2026-10-01", "--until", "2026-10-28", *extra]
    env = dict(os.environ, PLUMB_LEDGER_NOW=now)
    return subprocess.run(command, capture_output=True, text=True, env=env, cwd=str(repo or rework_repo()))


def rework_json(*extra: str) -> dict:
    done = run_rework("--json", *extra)
    if done.returncode != 0:
        raise AssertionError(f"exit {done.returncode}: {done.stderr.strip()}")
    return json.loads(done.stdout)


# Hand-computed from rework/changes.jsonl, period 2026-10-01..2026-10-28 (UTC), now 2026-10-30, 7 days:
#   cohort (author alice, any case, landed in the period): #10 #11 #12 #13 #14 #15 #16 #17 = 8
#   (#9 landed 28 Sep, #18 and the fixes are bob's, the two direct commits are never in the cohort)
#   reworked: #10 by #20; #11 and #12 both by #21 (one fix, two originals); #15 by #23, which landed on
#             29 Oct, after the period but inside #15's window = 4
#   clean:    #13 (its only listed fix, #19, landed before it), #14 (fixed by #22 fourteen days later,
#             outside the window), #17 = 3
#   pending:  #16 (landed 28 Oct, window open until 4 Nov) = 1
#   rate = 4 / (4 + 3) = 4/7 = 0.5714285714285714; readable Fixes-PR lines: all but #13 and #17 = 6 of 8
@case
def rework_rate_matches_the_hand_computed_value():
    result = rework_json()
    same((result["cohort"], result["reworked"], result["clean"], result["pending"]), (8, 4, 3, 1), "counts")
    same(result["rate_fraction"], "4/7", "rate as a fraction")
    same(result["rate"], 0.5714285714285714, "rate")
    same(result["rate_excludes_pending"], True, "pending is excluded and says so")
    same(result["pending_changes"], [16], "pending changes")
    same(result["clean_changes"], [13, 14, 17], "clean changes")


@case
def a_fix_listing_two_originals_counts_for_each():
    result = rework_json()
    same(result["reworked_changes"], [{"number": 10, "fixed_by": [20]}, {"number": 11, "fixed_by": [21]},
                                      {"number": 12, "fixed_by": [21]}, {"number": 15, "fixed_by": [23]}], "reworked")


@case
def a_fix_outside_the_period_counts_when_it_is_inside_the_window():
    result = rework_json()
    need(15 in [item["number"] for item in result["reworked_changes"]], "#15 is fixed by #23 on 29 October, after --until")
    need(14 not in [item["number"] for item in result["reworked_changes"]], "#22 is outside #14's window")


@case
def a_change_with_an_open_window_is_pending_not_clean():
    later = run_rework("--json", now="2026-11-30T00:00:00Z")
    result = json.loads(later.stdout)
    same((result["pending"], result["clean"]), (0, 4), "a month later the window of #16 has closed")
    same((result["rate_fraction"], result["rate"]), ("1/2", 0.5), "rate once nothing is pending: 4 reworked of 8")


@case
def the_lookahead_option_overrides_the_contract():
    result = rework_json("--lookahead-days", "20")
    # 14 is now fixed by #22 (14 days after it); 16 is still pending; 13 and 17 are clean: 5 / (5 + 2) = 5/7
    same((result["reworked"], result["clean"], result["pending"], result["rate_fraction"]), (5, 2, 1, "5/7"), "20 days")


@case
def readable_fixes_pr_share_and_direct_commits_are_reported():
    result = rework_json()
    same((result["readable_fixes_pr"], result["readable_fixes_pr_share"]), (6, 0.75), "readable Fixes-PR lines")
    same(result["direct_commits"], 2, "direct commits are counted apart")
    done = run_rework()
    need("rate: 4/7 = 57.1%" in done.stdout and "pending: 1" in done.stdout, done.stdout)
    need("left out of the rate" in done.stdout, "the text form must say pending is excluded")


@case
def an_invalid_contract_exits_2():
    repo = TMP / "rework-bad"
    git(TMP, "init", "-b", "develop", str(repo))
    (repo / ".plumb").mkdir()
    (repo / ".plumb" / "project.toml").write_text("schema = 2\n")
    done = run_rework(repo=repo)
    same(done.returncode, 2, "exit status")
    need("project contract" in done.stderr, done.stderr)


def main() -> int:
    failed = 0
    try:
        build_world()
        for function in CASES:
            name = function.__name__.replace("_", " ")
            try:
                function()
                print(f"ok   {name}")
            except Exception as error:  # a failing case is reported, the rest still run
                failed += 1
                detail = str(error) if isinstance(error, AssertionError) else "".join(traceback.format_exception_only(type(error), error)).strip()
                print(f"NG   {name}: {detail}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"{len(CASES)} cases, {failed} NG")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
