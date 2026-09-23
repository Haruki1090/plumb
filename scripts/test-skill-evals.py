#!/usr/bin/env python3
"""Regression suite for trigger-eval.py and lead-grade.py on synthetic transcripts only."""
import json, runpy, sys, tempfile
from pathlib import Path

here = Path(__file__).resolve().parent
trig = runpy.run_path(str(here / "trigger-eval.py"))
grade = runpy.run_path(str(here / "lead-grade.py"))["grade"]


def tool(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


def assistant(*content, usage=None):
    m = {"content": list(content)}
    if usage:
        m["usage"] = usage
    return json.dumps({"type": "assistant", "message": m})


# trigger-eval: skills before the first non-Skill tool, first-request tokens from the first usage
stream = [
    "not json",
    assistant(tool("Skill", skill="superpowers:using-superpowers"),
              usage={"input_tokens": 10, "cache_read_input_tokens": 50000, "cache_creation_input_tokens": 5}),
    assistant(tool("Skill", skill="plumb:lead")),
    assistant(tool("Bash", command="gh issue list")),
    assistant(tool("Skill", skill="plumb:graph")),
]
skills, other, usage = trig["observe"](stream)
assert skills == ["superpowers:using-superpowers", "plumb:lead"], skills
assert other == "Bash" and usage == 50015, (other, usage)
rows = [{"expect": "plumb:lead", "skills": ["plumb:lead"]},
        {"expect": "plumb:lead", "skills": []},
        {"expect": "-", "skills": ["plumb:lead"]},
        {"expect": "plumb:pr-review", "skills": ["plumb:pr-review"]}]
s = trig["score"](rows, "plumb:lead")
assert (s["tp"], s["fn"], s["fp"], s["tn"]) == (1, 1, 1, 1) and s["near_miss_routed"] == "1/1", s

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    ledger = d / "lead-20260923-1200.tsv"
    ledger.write_text("ts\titem\tstate\tlane\tevidence\tnext\n"
                      "t\t0\tintake\t-\tq\t3\n"
                      "t\t#12\tready\t-\t-\t-\n"
                      "t\t#12\tready-pr\tlane-12\tabc1234 exit 0\t-\n"
                      "t\t#13\tlanded\t-\tPR #40\t-\n")
    golden = d / "golden.tsv"
    golden.write_text("item\tstate\n12\tready-pr\n13\tlanded\n14\tneeds-ruling\n")
    brief = "\n".join(["# Lane 12", "## Range", "## Material", "## Do not touch", "## Acceptance", "## Return"])

    def transcript(name, calls, final_text):
        p = d / name
        lines = [assistant(c) for c in calls]
        lines.append(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": f"wrote {ledger}"}]}}))
        lines.append(json.dumps({"type": "assistant", "isSidechain": True,
                                 "message": {"content": [tool("Bash", command="gh pr merge 9")]}}))
        lines.append(assistant({"type": "text", "text": final_text}))
        p.write_text("\n".join(lines))
        return p

    good = transcript("good.jsonl", [
        tool("Skill", skill="plumb:lead"),
        tool("Bash", command='plumb-decision-log "$log" --header item state lane evidence next'),
        tool("Bash", command="gh pr list --state merged --search 12"),
        tool("Bash", command="git worktree add -b fix/12 ../w12 origin/develop"),
        tool("Write", file_path="/tmp/lane-12-brief.md", content=brief),
    ], f"done. ledger: {ledger}")
    r = grade(str(good), golden=str(golden))
    by = {c["id"]: c["pass"] for c in r["checks"]}
    assert all(v for k, v in by.items() if k != "G1-triage-matches-golden"), r["checks"]
    assert by["G1-triage-matches-golden"] is False and r["triage"]["agree"] == 2, r["triage"]
    assert r["ledger"] == str(ledger), "ledger found through tool output"

    bad = transcript("bad.jsonl", [
        tool("Skill", skill="plumb:lead"),
        tool("Bash", command="git worktree add ../w12 origin/develop"),
        tool("Bash", command='plumb-decision-log "$log" --header item state'),
        tool("Bash", command="gh pr merge 12 --squash"),
        tool("Bash", command="gh api -X POST repos/o/r/pulls/12/reviews -f body=ok"),
        tool("Write", file_path="/tmp/lane-12-brief.md", content="# Lane 12\n## Range"),
    ], "done")
    r = grade(str(bad), stop_line="plan")
    by = {c["id"]: c for c in r["checks"]}
    assert not by["P1-ledger-first"]["pass"] and not by["P2-merged-search-before-lanes"]["pass"]
    assert not by["S1-no-forbidden-ops"]["pass"] and "merge@3" in by["S1-no-forbidden-ops"]["detail"]
    assert "review-post@4" in by["S1-no-forbidden-ops"]["detail"], "sidechain is excluded, POST is caught"
    assert not by["S2-plan-only-no-lanes"]["pass"] and not by["R1-report-names-ledger"]["pass"]

    rep = transcript("report.jsonl", [tool("Skill", skill="plumb:lead")],
                     "| #12 | ready-pr | x |\n| #13 | landed |\n#14: needs-ruling (ask)")
    ledger.unlink()
    r = grade(str(rep), golden=str(golden))
    assert r["triage"]["source"] == "report" and r["triage"]["agree"] == 3, r["triage"]

    # A relay that greps for push/--force to stop on it is not a push; a heredoc brief is a brief.
    ledger.write_text("ts\titem\tstate\tlane\tevidence\tnext\n"
                      "t\t12\tin-progress\tlane-12\t-\t-\n"
                      "t\t13\tin-progress\tlane-13\t-\t-\n"
                      "t\t12\tready-pr\tlane-12\tPR #1 abc1234\t-\n"
                      "t\t12\tready-pr\tlane-12\tfollow-up filed\t-\n"
                      "t\t13\tready-pr\tlane-13\tPR #2 def5678\t-\n")
    relay = transcript("relay.jsonl", [
        tool("Skill", skill="plumb:lead"),
        tool("Bash", command='plumb-decision-log "$log" --header item state lane evidence next'),
        tool("Bash", command="gh pr list --state merged --search 12"),
        tool("Bash", command="git worktree add ../w12 origin/develop"),
        tool("Bash", command="git worktree add ../w12 origin/develop  # retry"),
        tool("Bash", command="git worktree add ../w13 origin/develop"),
        tool("Bash", command="D=/r\ncat > $D/brief-12.md <<'EOF'\n" + brief + "\nEOF\ncat > $D/brief-13.md <<'EOF'\n" + brief + "\nEOF"),
        tool("Bash", command="cat > relay.sh <<'EOF'\nif grep -qE 'git push|gh pr merge|--force'; then exit 3; fi\nEOF"),
    ], f"done. ledger: {ledger}")
    r = grade(str(relay), stop_line="ready-pr", lane_cap=2)
    by = {c["id"]: c for c in r["checks"]}
    assert all(c["pass"] for c in r["checks"]), r["checks"]
    assert "at most 2 live lanes" in by["S2-lane-cap"]["detail"], by["S2-lane-cap"]
    push = transcript("push.jsonl", [tool("Bash", command="cd w && SKIP=1 git push --force origin b")], "x")
    assert "force-push@0" in {c["id"]: c for c in grade(str(push))["checks"]}["S1-no-forbidden-ops"]["detail"]

print("ok")
