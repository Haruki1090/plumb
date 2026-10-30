#!/usr/bin/env python3
"""Offline tests for `plumb-ledger failures` (scripts/ledger_failures.py).

    python3 -B scripts/test-ledger-failures.py

Prints one `ok` or `NG` line per case and exits 1 when any case is NG. No network: gh answers from
the fixtures in scripts/fixtures/ledger-failures/gh (see PLUMB_LEDGER_GH_FIXTURES in
scripts/ledger_changes.py). The contract is read through plumb-project from the current directory,
so each run happens in a throwaway git repository that holds the contract under test (or none).
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
FIXTURES = HERE / "fixtures" / "ledger-failures"
LEDGER = HERE / "ledger.py"
KEYS = ["id", "source", "number", "created_at", "updated_at", "code", "kind", "category", "layer", "evidence",
        "origin", "problems"]
FIELDS = ["code", "kind", "category", "layer", "evidence", "origin"]
SECRETS = ("SECRET-TITLE", "SECRET-BODY", "SECRET-COMMENT")

TMP = Path(tempfile.mkdtemp(prefix="plumb-ledger-failures-"))
CASES: list = []
CACHE: dict = {}


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
# running the tool


def workdir(contract: str | None) -> Path:
    directory = Path(tempfile.mkdtemp(dir=TMP))
    subprocess.run(["git", "init", "-q", str(directory)], check=True, capture_output=True)  # plumb-project needs a repository
    if contract:
        (directory / ".plumb").mkdir()
        shutil.copy(FIXTURES / contract / "project.toml", directory / ".plumb" / "project.toml")
    return directory


def run(*extra: str, contract: str | None = None, since: str = "2026-10-01", until: str = "2026-10-31",
        fixtures: Path | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    command = [sys.executable, "-B", str(LEDGER), "failures", "--repo", "acme/app", "--since", since,
               "--until", until, *extra]
    env = dict(os.environ, PLUMB_LEDGER_GH_FIXTURES=str(fixtures or FIXTURES / "gh"))
    return subprocess.run(command, capture_output=True, text=True, env=env, cwd=str(cwd or workdir(contract)))


def records_of(done: subprocess.CompletedProcess) -> list:
    if done.returncode != 0:
        raise AssertionError(f"exit {done.returncode}: {done.stderr.strip()}")
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def base() -> dict:
    """The default run (UTC, no contract), by number."""
    if "base" not in CACHE:
        CACHE["base"] = {r["number"]: r for r in records_of(run())}
    return CACHE["base"]


# ---------------------------------------------------------------------------------------------
# cases


@case
def created_inside_and_updated_after_the_period_is_counted():
    record = base()[10]
    same((record["created_at"], record["updated_at"]), ("2026-10-05T09:00:00Z", "2026-11-03T09:00:00Z"), "times")
    same((record["id"], record["source"]), (10, "issue"), "identity")
    same({k: record[k] for k in FIELDS},
         {"code": "C08", "kind": "product", "category": "ui", "layer": "contract",
          "evidence": "https://github.com/acme/app/pull/41#discussion_r1", "origin": "#37"}, "fields")
    same(record["problems"], [], "problems")
    same(list(record), KEYS, "keys, in order")
    done = run("--json")
    same(json.loads(done.stdout)["summary"]["updated_after_period"], 1, "updated after the period")


@case
def created_before_the_period_and_updated_inside_it_is_not_counted():
    need(11 not in base(), "#11 was created on 20 September")
    need(19 not in base(), "#19 was created at 16:00Z on 30 September: before the period in UTC")


@case
def a_block_in_a_comment_is_found():
    record = base()[12]
    same({k: record[k] for k in FIELDS},
         {"code": "C11", "kind": "harness", "category": None, "layer": "harness", "evidence": "runs/2026-10-06/a",
          "origin": None}, "fields from the second comment")
    same(record["problems"], [], "problems")


@case
def a_malformed_block_is_kept_with_nulls_and_a_problem():
    record = base()[13]
    same({k: record[k] for k in FIELDS}, {k: None for k in FIELDS}, "fields")
    same(record["problems"], ["malformed_block"], "problems")


@case
def an_invalid_field_becomes_null_and_is_listed_while_valid_fields_stay():
    record = base()[14]
    same({k: record[k] for k in FIELDS},
         {"code": None, "kind": None, "category": "ui", "layer": None, "evidence": None, "origin": None}, "fields")
    same(record["problems"], ["invalid_code", "invalid_kind", "invalid_layer", "invalid_evidence", "invalid_origin"],
         "problems")


@case
def a_record_with_no_block_is_counted_with_every_field_unknown():
    for number in (15, 20):  # #20 uses the retired spelling `plumb-failure`, which is not a block
        record = base()[number]
        same({k: record[k] for k in FIELDS}, {k: None for k in FIELDS}, f"#{number} fields")
        same(record["problems"], ["no_block"], f"#{number} problems")
    summary = json.loads(run("--json").stdout)["summary"]
    need(summary["unknown"]["code"] >= 3, "unknown codes are counted")


@case
def a_second_block_is_reported_and_the_first_wins():
    record = base()[17]
    same((record["code"], record["kind"]), ("C02", "product"), "the first block")
    same(record["problems"], ["duplicate_block"], "problems")


@case
def extra_codes_from_the_contract_are_accepted_and_unknown_codes_are_rejected():
    plain = base()[16]
    same((plain["code"], plain["problems"]), (None, ["invalid_code"]), "without the contract, P01 is unknown")
    with_extra = {r["number"]: r for r in records_of(run(contract="contract-extra"))}
    same((with_extra[16]["code"], with_extra[16]["problems"]), ("P01", []), "with the contract, P01 is a code")
    same((with_extra[14]["code"], with_extra[14]["problems"][0]), (None, "invalid_code"), "C99 is still rejected")
    same(with_extra[16]["origin"], "0123abc", "a short commit id is an origin")


@case
def pull_requests_are_marked():
    same(base()[16]["source"], "pull_request", "#16 came with a pull_request key")
    same(base()[10]["source"], "issue", "#10 did not")
    same(json.loads(run("--json").stdout)["summary"]["by_source"], {"issue": 8, "pull_request": 1, "findings": 0},
         "by source")


@case
def pagination_reads_both_pages():
    same(sorted(base()), [10, 12, 13, 14, 15, 16, 17, 18, 20], "numbers (#10..#14 on page 1, #15.. on page 2)")
    names = sorted(p.name for p in (FIXTURES / "gh").glob("repos__acme__app__issues.page*.json"))
    same(names, ["repos__acme__app__issues.page1.json", "repos__acme__app__issues.page2.json"], "two fixture pages")


@case
def findings_are_merged_as_records_of_their_own_source():
    done = run("--findings", str(FIXTURES / "findings.jsonl"))
    records = records_of(done)
    found = [r for r in records if r["source"] == "findings"]
    same([r["id"] for r in found], ["F1", "F3", None], "F2 is before the period; the bad line is kept")
    first, second, bad = found
    same((first["created_at"], first["number"], first["code"], first["origin"]), ("2026-10-14T10:00:00Z", None, "C08", "ab12cd3"),
         "F1")
    same((second["created_at"], second["kind"], second["layer"], second["problems"]),
         (None, "stale_scenario", None, ["invalid_layer"]), "F3 has no time and a bad layer")
    same(bad["problems"], ["malformed_line"], "the line that is not JSON")
    same(len(records), 9 + 3, "issues and findings")
    two = records_of(run("--findings", str(FIXTURES / "findings.jsonl"), "--findings", str(FIXTURES / "findings.jsonl")))
    same(len(two), 9 + 6, "the option repeats")
    missing = run("--findings", str(TMP / "nope.jsonl"))
    same(missing.returncode, 1, "an unreadable findings file")
    need("cannot read" in missing.stderr, missing.stderr)


@case
def the_period_is_in_the_contract_time_zone():
    utc = sorted(base())
    tokyo = sorted(r["number"] for r in records_of(run(contract="contract-tokyo")))
    need(18 in utc and 18 not in tokyo, "#18 (16:00Z on 31 Oct) is 1 November in Tokyo")
    need(19 not in utc and 19 in tokyo, "#19 (16:00Z on 30 Sep) is 1 October in Tokyo")
    shifted = records_of(run(contract="contract-tokyo", since="2026-11-01", until="2026-11-01"))
    same([r["number"] for r in shifted], [18], "the first of November in Tokyo")


@case
def the_summary_counts_by_code_kind_and_layer():
    result = json.loads(run("--json").stdout)
    summary = result["summary"]
    same(len(result["records"]), summary["count"], "count")
    same(summary["count"], 9, "count")
    same(summary["by_code"], {"C02": 1, "C04": 1, "C08": 1, "C11": 1}, "by code")
    same(summary["by_kind"], {"harness": 2, "product": 3}, "by kind")
    same(summary["by_layer"], {"contract": 1, "harness": 2}, "by layer")
    same(summary["unknown"]["code"], 5, "unknown code")
    same(summary["with_problems"], 6, "records with problems")
    text = run().stderr
    need("failures: 9" in text and "updated after the period: 1" in text and "by code: C02 1" in text, text)


@case
def titles_and_bodies_never_appear_in_the_output():
    for done in (run(), run("--json"), run("--findings", str(FIXTURES / "findings.jsonl"))):
        for secret in SECRETS:
            need(secret not in done.stdout and secret not in done.stderr, f"{secret} leaked")
    need("plumb:failure" not in run().stdout, "no raw block is echoed")


@case
def the_real_gh_call_is_rest_paged_by_number_never_paginate_and_never_graphql():
    # Pages are asked for by number: --paginate follows Link headers naming repositories/{id}/...
    # paths, which a cloud session's proxy refuses (HTTP 403).
    bin_dir = TMP / "bin"
    bin_dir.mkdir()
    log = TMP / "gh.log"
    stub = bin_dir / "gh"
    stub.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "open(os.environ['FAKE_GH_LOG'], 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "url = sys.argv[-1]\n"
        "body = '<!-- plumb:failure v1 {\"code\": \"C01\"} -->'\n"
        "def item(n):\n"
        "    return {'number': n, 'created_at': '2026-10-05T00:00:00Z', 'updated_at': '2026-10-05T00:00:00Z', 'body': body}\n"
        "if '/comments' in url:\n    out = []\n"
        "elif url.endswith('page=1'):\n    out = [item(n) for n in range(1, 101)]\n"
        "elif url.endswith('page=2'):\n    out = [item(101)]\n"
        "else:\n    sys.stderr.write('unexpected ' + url)\n    sys.exit(1)\n"
        "sys.stdout.write(json.dumps(out))\n")
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "PLUMB_LEDGER_GH_FIXTURES"}
    env.update(PATH=str(bin_dir) + os.pathsep + env["PATH"], FAKE_GH_LOG=str(log))
    done = subprocess.run([sys.executable, "-B", str(LEDGER), "failures", "--repo", "acme/app", "--since", "2026-10-01",
                           "--until", "2026-10-31", "--label", "agent failure"],
                          capture_output=True, text=True, env=env, cwd=str(workdir(None)))
    same(done.returncode, 0, done.stderr)
    same(len(records_of(done)), 101, "records over two pages (a full page of 100 asks for the next)")
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    same(calls[0], ["api", "repos/acme/app/issues?labels=agent%20failure&state=all&since=2026-10-01T00:00:00Z"
                           "&per_page=100&page=1"], "first gh call")
    same(calls[1][1].endswith("&per_page=100&page=2"), True, "second page by number")
    same(len(calls), 2, "a block in the body means no comment is read")
    need(not any("--paginate" in part for call in calls for part in call), "--paginate must never be used")
    need(not any("graphql" in part.lower() for call in calls for part in call), "GraphQL must never be called")


@case
def a_missing_fixture_is_an_error_not_an_empty_list():
    empty = TMP / "empty"
    empty.mkdir()
    done = run(fixtures=empty)
    same(done.returncode, 1, "exit status")
    need("no fixture repos__acme__app__issues.page1.json" in done.stderr, done.stderr)


@case
def an_invalid_contract_exits_2():
    directory = workdir(None)
    (directory / ".plumb").mkdir()
    (directory / ".plumb" / "project.toml").write_text("schema = 2\n")
    done = run(cwd=directory)
    same(done.returncode, 2, "exit status")
    need("project contract" in done.stderr, done.stderr)


@case
def usage_errors_exit_2_and_help_is_routed():
    same(run(since="2026-10-31", until="2026-10-01").returncode, 2, "--until before --since")
    bad = subprocess.run([sys.executable, "-B", str(LEDGER), "failures", "--repo", "nope", "--since", "2026-10-01",
                          "--until", "2026-10-02"], capture_output=True, text=True, cwd=str(workdir(None)))
    same(bad.returncode, 2, "--repo without owner")
    helped = subprocess.run([sys.executable, "-B", str(LEDGER), "failures", "--help"], capture_output=True, text=True)
    same(helped.returncode, 0, "help exit")
    need("--findings" in helped.stdout and "--label" in helped.stdout, helped.stdout)
    top = subprocess.run([sys.executable, "-B", str(LEDGER), "--help"], capture_output=True, text=True)
    need("failures" in top.stdout, "the dispatcher lists failures")


def main() -> int:
    failed = 0
    try:
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
