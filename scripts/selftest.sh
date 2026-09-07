#!/usr/bin/env bash
# Pin down how plumb's scripts behave. check-harness looks at whether the documents agree;
# this looks at what the scripts return. doctor calls it from the "inside".
set -uo pipefail
root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
fail=0
ok()  { printf '  %-4s %s\n' "ok" "$1"; }
ng()  { printf '  %-4s %s\n' "NG" "$1"; fail=1; }
eq()  { [ "$2" = "$3" ] && ok "$1" || ng "$1 (expected [$3] / measured [$2])"; }

echo "plumb selftest: $root"

cfg=$(mktemp)
sandbox_root=$(mktemp -d)
trap 'rm -f "$cfg"; rm -rf "$sandbox_root"' EXIT
printf 'role.judge = codex\nrole.bulk   =  cursor-agent  \nrole.explorer.model = tier-x\n' > "$cfg"
eq "plumb-config resolves role.explorer.model" "$(PLUMB_CONFIG=$cfg "$root/bin/plumb-config" role.explorer.model)" "tier-x"
eq "plumb-config leaves cost.session_budget_usd empty when unset" "$(PLUMB_CONFIG=$cfg "$root/bin/plumb-config" cost.session_budget_usd)" ""

# Session-audit checks use synthetic transcripts and never read private session content.
if command -v python3 >/dev/null 2>&1; then
  percentile_check=$(python3 -B -c 'import runpy, sys
p = runpy.run_path(sys.argv[1])["percentile"]
assert p(range(1, 11), .9) == 9
assert p(range(1, 21), .9) == 18
assert p(range(1, 11), .5) == 5
assert p([7], .9) == 7 and p([], .9) is None
print("ok")' "$root/scripts/session-audit.py" 2>/dev/null)
  eq "session-audit uses nearest-rank percentiles at exact boundaries" "$percentile_check" "ok"
  unsupported_dir="$sandbox_root/unsupported-session"
  mkdir -p "$unsupported_dir"
  printf '%s\n' '{"type":"response_item","payload":{"type":"message","role":"assistant"}}' \
    > "$unsupported_dir/session.jsonl"
  "$root/bin/plumb-session-audit" --transcripts "$unsupported_dir" --all --json >/dev/null 2>&1
  eq "session-audit refuses zero recognized usage instead of reporting free work" "$?" "2"
  printf '%s\n' '{"type":"assistant","message":{"usage":{}}}' > "$unsupported_dir/session.jsonl"
  "$root/bin/plumb-session-audit" --transcripts "$unsupported_dir" --all --json >/dev/null 2>&1
  eq "session-audit refuses an empty usage object" "$?" "2"
  printf '%s\n' '{"type":"assistant","message":{"usage":{"input_tokens":10,"output_tokens":2}}}' \
    > "$unsupported_dir/session.jsonl"
  partial_totals=$("$root/bin/plumb-session-audit" --transcripts "$unsupported_dir" --all --json \
    | python3 -c 'import json, sys
t = json.load(sys.stdin)["token_totals"]
print("ok" if t == {"input":10,"output":2,"cache_read":None,"cache_creation":None} else "wrong")')
  eq "session-audit preserves missing cost fields as unavailable" "$partial_totals" "ok"
  printf '%s\n' \
    '{"type":"assistant","message":{"usage":{"input_tokens":10,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens":7,"output_tokens_details":{"thinking_tokens":2},"cache_creation":{"ephemeral_1h_input_tokens":5,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","message":{"usage":{"input_tokens":10}}}' > "$unsupported_dir/session.jsonl"
  partial_display=$("$root/bin/plumb-session-audit" --transcripts "$unsupported_dir" --all --json \
    | python3 -c 'import json, sys
r = json.load(sys.stdin)
assert all(v is None for v in r["output_tokens"].values())
assert all(v is None for v in r["cache_creation"].values())
print("ok")' 2>/dev/null)
  eq "session-audit display metrics do not present partial sums as totals" "$partial_display" "ok"
  audit_dir="$sandbox_root/session-audit"
  mkdir -p "$audit_dir/clean-session/subagents"
  large_tool_result=$(printf '%*s' 110 '')
  unicode_tool_result=$(printf '\343\201\202%.0s' {1..30})
  printf '%s\n' \
    '{"type":"user","message":{"content":"first human prompt"}}' \
    '{"type":"assistant","requestId":"shared-request","timestamp":"2026-09-02T00:00:00Z","sessionId":"clean-session","isSidechain":false,"message":{"id":"message-split","model":"unsafe/model name","usage":{"input_tokens":50,"cache_creation_input_tokens":0,"cache_read_input_tokens":11,"output_tokens":10,"output_tokens_details":{"thinking_tokens":2},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","requestId":"shared-request","timestamp":"2026-09-02T00:00:00Z","sessionId":"clean-session","isSidechain":false,"message":{"id":"message-split","model":"unsafe/model name","usage":{"input_tokens":50,"cache_creation_input_tokens":0,"cache_read_input_tokens":11,"output_tokens":10,"output_tokens_details":{"thinking_tokens":2},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","requestId":"shared-request","timestamp":"2026-09-02T00:00:00Z","sessionId":"clean-session","isSidechain":false,"message":{"id":"message-split","model":"unsafe/model name","usage":{"input_tokens":50,"cache_creation_input_tokens":0,"cache_read_input_tokens":11,"output_tokens":10,"output_tokens_details":{"thinking_tokens":2},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","timestamp":"2026-09-02T00:01:00Z","sessionId":"clean-session","isSidechain":false,"message":{"id":"message-fallback","model":"alpha","usage":{"input_tokens":40,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":7,"output_tokens_details":{"thinking_tokens":1},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","timestamp":"2026-09-02T00:01:00Z","sessionId":"clean-session","isSidechain":false,"message":{"id":"message-fallback","model":"alpha","usage":{"input_tokens":40,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":7,"output_tokens_details":{"thinking_tokens":1},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","timestamp":"2026-09-02T00:02:00Z","sessionId":"clean-session","isSidechain":false,"message":{"model":"alpha","usage":{"input_tokens":30,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":3,"output_tokens_details":{"thinking_tokens":1},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","timestamp":"2026-09-02T00:03:00Z","sessionId":"clean-session","isSidechain":false,"message":{"model":"alpha","usage":{"input_tokens":20,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":4,"output_tokens_details":{"thinking_tokens":1},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","requestId":"synthetic-request","timestamp":"2026-09-02T00:04:00Z","sessionId":"clean-session","isSidechain":false,"message":{"id":"synthetic-message","model":"<synthetic>","usage":{"input_tokens":999,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":99,"output_tokens_details":{"thinking_tokens":99},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","requestId":"synthetic-request","timestamp":"2026-09-02T00:04:00Z","sessionId":"clean-session","isSidechain":false,"message":{"id":"synthetic-message","model":"<synthetic>","usage":{"input_tokens":999,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":99,"output_tokens_details":{"thinking_tokens":99},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","requestId":"synthetic-request","timestamp":"2026-09-02T00:04:00Z","sessionId":"clean-session","isSidechain":false,"message":{"id":"synthetic-message","model":"<synthetic>","usage":{"input_tokens":999,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":99,"output_tokens_details":{"thinking_tokens":99},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","requestId":"direct-sidechain","timestamp":"2026-09-02T02:30:00Z","sessionId":"clean-session","isSidechain":true,"message":{"id":"direct-sidechain-message","model":"beta","usage":{"input_tokens":20000,"cache_creation_input_tokens":21001,"cache_read_input_tokens":0,"output_tokens":5,"output_tokens_details":{"thinking_tokens":1},"cache_creation":{"ephemeral_1h_input_tokens":21001,"ephemeral_5m_input_tokens":0}}}}' \
    > "$audit_dir/clean-session.jsonl"
  printf '%s\n' \
    '{"type":"assistant","timestamp":"2026-09-02T00:30:00Z","sessionId":"clean-session","isSidechain":true,"message":{"id":"sidechain-message","model":"beta","usage":{"input_tokens":10000,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":5,"output_tokens_details":{"thinking_tokens":1},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    > "$audit_dir/clean-session/subagents/agent-fixture.jsonl"
  printf '%s\n' \
    '{"type":"user","message":{"content":[{"type":"text","text":"second human prompt"}]}}' \
    "{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"tool_result\",\"content\":\"$large_tool_result\"}]}}" \
    "{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"tool_result\",\"content\":\"$unicode_tool_result\"}]}}" \
    '{"type":"user","message":{"content":[{"type":"text","text":"not a human turn"},{"type":"tool_result","content":"small"}]}}' \
    'not json' \
    '{"type":"assistant","requestId":"shared-request","timestamp":"2026-09-02T00:00:00Z","sessionId":"flagged-session","isSidechain":false,"message":{"id":"flagged-first","model":"alpha","usage":{"input_tokens":50,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":10,"output_tokens_details":{"thinking_tokens":2},"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}' \
    '{"type":"assistant","requestId":"flagged-second","timestamp":"2026-09-02T01:01:01Z","sessionId":"flagged-session","isSidechain":false,"message":{"id":"flagged-second-message","model":"alpha","usage":{"input_tokens":50,"cache_creation_input_tokens":21001,"cache_read_input_tokens":0,"output_tokens":10,"output_tokens_details":{"thinking_tokens":2},"cache_creation":{"ephemeral_1h_input_tokens":21001,"ephemeral_5m_input_tokens":0}}}}' \
    > "$audit_dir/flagged-session.jsonl"

  audit_out=$("$root/bin/plumb-session-audit" --transcripts "$audit_dir" --all \
    --ctx-threshold 100 --tool-threshold 100 --first-threshold 60)
  audit_json=$("$root/bin/plumb-session-audit" --transcripts "$audit_dir" --all \
    --ctx-threshold 100 --tool-threshold 100 --first-threshold 60 --json)
  audit_text_file="$sandbox_root/audit.txt"
  audit_json_file="$sandbox_root/audit.json"
  printf '%s\n' "$audit_out" > "$audit_text_file"
  printf '%s\n' "$audit_json" > "$audit_json_file"

  printf '%s\n' "$audit_out" | grep -q \
    'sessions=2  records=14  requests=8  synthetic=3  turns=2  skipped_lines=1' \
    && ok "session-audit distinguishes sessions, records, requests, synthetic records, and turns" \
    || ng "session-audit summary counts are wrong: [$audit_out]"

  dedup_check=$(python3 -c 'import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
sessions = {s["session_id"]: s for s in r["sessions"]}
ok = (r["request_count"] == 8 and r["output_tokens"]["total"] == 54
      and r["token_totals"] == {"input": 30240, "cache_read": 11,
                                 "cache_creation": 42002, "output": 54}
      and sessions["clean-session"]["record_count"] == 12
      and sessions["clean-session"]["request_count"] == 6
      and sessions["clean-session"]["synthetic_count"] == 3
      and sessions["clean-session"]["token_totals"]
          == {"input": 30140, "cache_read": 11, "cache_creation": 21001, "output": 34}
      and sessions["flagged-session"]["token_totals"]
          == {"input": 100, "cache_read": 0, "cache_creation": 21001, "output": 20})
print("ok" if ok else "wrong")' "$audit_json_file")
  eq "session-audit deduplicates usage and preserves both fallback levels" "$dedup_check" "ok"

  flag_check=$(python3 -c 'import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
sessions = {s["session_id"]: s for s in r["sessions"]}
counts = {name: next(iter(value.values())) for name, value in r["flags"].items()}
ok = (counts == {"CTX-P90-OVER": 1, "TOOL-RESULT-OVER": 1, "IDLE-REBUILD": 1, "FIRST-REQUEST-OVER": 1}
      and r["tool_results"] == {"over_percent": 33.3, "over_threshold": 1, "total": 3}
      and r["idle"] == {"cache_rebuilt_after": 1, "gaps": 1}
      and sessions["clean-session"]["context_p90"] == 41001
      and sessions["clean-session"]["main_context_p90"] == 61
      and sessions["clean-session"]["flags"] == ["FIRST-REQUEST-OVER"]
      and sessions["flagged-session"]["first_context"] == 50)
print("ok" if ok else "wrong")' "$audit_json_file")
  eq "session-audit isolates main-chain flags, flags the first request, and measures tool results as UTF-8 bytes" "$flag_check" "ok"

  if printf '%s\n' "$audit_out" | grep -q 'unsafe?model?name: 1' \
      && ! printf '%s\n' "$audit_out" | grep -q 'unsafe/model name' \
      && python3 -c 'import json, sys; r=json.load(open(sys.argv[1])); raise SystemExit(0 if r["models"]["main"].get("unsafe/model name") == 1 else 1)' "$audit_json_file"; then
    ok "session-audit sanitizes text model labels and preserves raw JSON labels"
  else
    ng "session-audit model sanitization or raw JSON label is wrong: [$audit_out]"
  fi

  "$root/bin/plumb-session-audit" --transcripts "$audit_dir" --all --ctx-threshold 100 \
    --tool-threshold 100 --strict >/dev/null 2>&1
  eq "session-audit strict mode fires" "$?" "1"

  json_check=$(python3 -c 'import json, re, sys
text = open(sys.argv[1], encoding="utf-8").read()
report = json.load(open(sys.argv[2], encoding="utf-8"))
def row(pattern):
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise SystemExit("missing text row: " + pattern)
    return tuple(float(value.replace(",", "")) for value in match.groups())
same = (
    row(r"sessions=([\d,]+)  records=([\d,]+)  requests=([\d,]+)  synthetic=([\d,]+)  turns=([\d,]+)  skipped_lines=([\d,]+)")
        == tuple(report[key] for key in ("session_count", "record_count", "request_count", "synthetic_count", "turn_count", "skipped_lines"))
    and row(r"work ratios\s+turns/session ([\d.]+)\s+requests/turn ([\d.]+)\s+requests/session ([\d.]+)")
        == tuple(report[key] for key in ("turns_per_session", "requests_per_turn", "requests_per_session"))
    and row(r"context/request\s+p50 ([\d,]+)\s+p90 ([\d,]+)\s+max ([\d,]+)")
        == tuple(report["context_per_request"][key] for key in ("p50", "p90", "max"))
    and row(r"context/request \(main\) p50 ([\d,]+)\s+p90 ([\d,]+)\s+max ([\d,]+)")
        == tuple(report["context_per_request_main"][key] for key in ("p50", "p90", "max"))
    and row(r"first request\s+p50 ([\d,]+)\s+max ([\d,]+)")
        == tuple(report["first_request"][key] for key in ("p50", "max"))
    and row(r"tool results\s+([\d,]+)\s+over \S+ ([\d,]+) \(([\d.]+)%\)")
        == (report["tool_results"]["total"], report["tool_results"]["over_threshold"], report["tool_results"]["over_percent"])
    and row(r"idle >\S+\s+([\d,]+)\s+cache rebuilt after ([\d,]+)")
        == (report["idle"]["gaps"], report["idle"]["cache_rebuilt_after"])
    and row(r"output tokens\s+([\d,]+)\s+thinking ([\d.]+)%")
        == (report["output_tokens"]["total"], round(report["output_tokens"]["thinking_percent"]))
)
print("same" if same else "different")' "$audit_text_file" "$audit_json_file")
  eq "session-audit JSON carries the text report numbers" "$json_check" "same"

  "$root/bin/plumb-session-audit" --project "$audit_dir" --all >/dev/null 2>&1
  implicit_code=$?
  eq "session-audit does not infer transcripts from a working directory" "$implicit_code" "2"

  format_dir="$sandbox_root/format-change"; mkdir -p "$format_dir"
  printf '%s\n' \
    '{"type":"assistant","requestId":"unknown-format","message":{"id":"unknown-message","usage_v2":{"input_tokens":1}}}' \
    > "$format_dir/unknown.jsonl"
  format_out=$("$root/bin/plumb-session-audit" --transcripts "$format_dir" --all 2>&1)
  format_code=$?
  if [ "$format_code" = 2 ] && printf '%s\n' "$format_out" | grep -q \
      'saw 1 assistant records and understood 0 - the transcript format may have changed'; then
    ok "session-audit fails closed when the transcript format changes"
  else
    ng "session-audit did not fail closed on an unknown format: code=$format_code output=[$format_out]"
  fi
else
  for audit_assertion in 1 2 3 4 5 6 7 8 9 10 11 12 13; do
    printf '  %-4s %s\n' "--" "python3 not on PATH, session-audit assertions skipped"
  done
fi

# bench-extract: pairing and diff parsing stay below the gh boundary, so these fixtures never
# touch the network. A separate fake-gh run proves that reviewed human work wins over a retry.
extract_fixture="$sandbox_root/extract-prs.json"
printf '%s\n' '[
  {"number":21,"title":"feature","body":"","mergedAt":"2026-01-01T00:00:00Z"},
  {"number":22,"title":"feature","body":"","mergedAt":"2026-01-02T00:00:00Z"},
  {"number":30,"title":"Fix: both regressions","body":"Repairs #21 and #22 (not issue #5).","mergedAt":"2026-01-03T00:00:00Z"}
]' > "$extract_fixture"
extract_unit=$(python3 -c 'import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("bench_extract", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
with open(sys.argv[2], encoding="utf-8") as source: prs = json.load(source)
pairs = module.find_pairs(prs, 20)
fix = """diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -8 +10,2 @@\n-old\n+new\n+line\ndiff --git a/docs.md b/docs.md\n--- a/docs.md\n+++ b/docs.md\n@@ -1 +1 @@\n-old\n+new\n"""
buggy = """diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\ndiff --git a/other.py b/other.py\n--- a/other.py\n+++ b/other.py\n@@ -1 +1 @@\n-old\n+new\n"""
hunks = module.filter_fix_hunks(fix, buggy, 30)
insertion = module.parse_diff_hunks("""diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -20,0 +22,2 @@\n+one\n+two\n""")["app.py"][0]
print("{}|{}|{}|{}|{}|{}|{}|{}|{}".format(
    len(pairs), len(hunks), hunks[0]["file"], *hunks[0]["lines"], *hunks[0]["fix_lines"],
    *insertion["lines"]))' \
  "$root/scripts/bench-extract.py" "$extract_fixture")
eq "bench-extract uses old-side truth coordinates, including pure insertions" "$extract_unit" "2|1|app.py|8|8|10|11|20|20"

extract_keep="$sandbox_root/extract-keep"; mkdir -p "$extract_keep/00021-00030"
printf '%s\n' '[{"file":"kept.py","lines":[7,8],"fix_lines":[9,10],"source":"fix#30","reviewed":false,"note":"human draft"}]' \
  > "$extract_keep/00021-00030/truth.json"
printf '%s\n' '{"repo":"example/repo","number":21,"sha":"fix-base","buggy_sha":"head","base_sha":"base","title":"feature","fixed_by":30,"grade":null}' \
  > "$extract_keep/00021-00030/pr.json"
keep_before=$(cksum "$extract_keep/00021-00030/truth.json")
fake_bin="$sandbox_root/bench-bin"; mkdir -p "$fake_bin"
fake_list="$sandbox_root/fake-list.json"
printf '%s\n' '[
  {"number":21,"title":"feature","body":"","baseRefOid":"base","headRefOid":"head","mergedAt":"2026-01-01T00:00:00Z"},
  {"number":30,"title":"fix regression","body":"Fixes #21","baseRefOid":"base2","headRefOid":"head2","mergedAt":"2026-01-02T00:00:00Z"}
]' > "$fake_list"
fake_diff="$sandbox_root/fake.diff"
printf '%s\n' \
  'diff --git a/kept.py b/kept.py' \
  '--- a/kept.py' \
  '+++ b/kept.py' \
  '@@ -7,2 +9,2 @@' \
  '-old' \
  '+new' > "$fake_diff"
printf '%s\n' '#!/bin/sh' \
  'if [ "$1 $2" = "pr list" ]; then /bin/cat "$BENCH_FAKE_LIST"; exit 0; fi' \
  'if [ "$1" = "api" ]; then printf "%s\n" "fix-merge-base"; exit 0; fi' \
  'if [ "$1 $2" = "pr diff" ]; then /bin/cat "$BENCH_FAKE_DIFF"; exit 0; fi' \
  'echo "unexpected gh call: $*" >&2; exit 19' > "$fake_bin/gh"
chmod +x "$fake_bin/gh"
keep_out=$(BENCH_FAKE_LIST="$fake_list" BENCH_FAKE_DIFF="$fake_diff" PATH="$fake_bin:$PATH" \
  "$root/bin/plumb-bench-extract" --repo example/repo --out "$extract_keep")
keep_after=$(cksum "$extract_keep/00021-00030/truth.json")
printf '%s\n' "$keep_out" | grep -q 'kept 00021-00030 (existing truth)' \
  && printf '%s\n' "$keep_out" | grep -q 'wrote 0 item(s), kept 1' \
  && [ "$keep_before" = "$keep_after" ] \
  && ok "bench-extract keeps an existing unreviewed truth at its stable pair id" \
  || ng "bench-extract rewrote an existing draft or used a positional id: [$keep_out]"

refresh_out=$(BENCH_FAKE_LIST="$fake_list" BENCH_FAKE_DIFF="$fake_diff" PATH="$fake_bin:$PATH" \
  "$root/bin/plumb-bench-extract" --repo example/repo --out "$extract_keep" --refresh 00021-00030)
refresh_check=$(python3 -c 'import json, sys
pr=json.load(open(sys.argv[1], encoding="utf-8")); truth=json.load(open(sys.argv[2], encoding="utf-8"))
ok=(pr["sha"] == "fix-merge-base" and pr["buggy_sha"] == "head"
    and truth[0]["lines"] == [7, 8] and truth[0]["fix_lines"] == [9, 10]
    and truth[0]["note"] == "" and truth[0]["reviewed"] is False)
print("ok" if ok else "wrong")' \
  "$extract_keep/00021-00030/pr.json" "$extract_keep/00021-00030/truth.json")
eq "bench-extract refreshes one unreviewed item in the fix-base coordinate system" "$refresh_check" "ok"

printf '%s\n' '[{"file":"kept.py","lines":[7,8],"fix_lines":[9,10],"source":"fix#30","reviewed":true,"note":"human work"}]' \
  > "$extract_keep/00021-00030/truth.json"
reviewed_before=$(cksum "$extract_keep/00021-00030/truth.json")
reviewed_out=$(BENCH_FAKE_LIST="$fake_list" BENCH_FAKE_DIFF="$fake_diff" PATH="$fake_bin:$PATH" \
  "$root/bin/plumb-bench-extract" --repo example/repo --out "$extract_keep" --refresh 00021-00030 2>&1)
reviewed_code=$?
reviewed_after=$(cksum "$extract_keep/00021-00030/truth.json")
if [ "$reviewed_code" = 2 ] && [ "$reviewed_before" = "$reviewed_after" ] \
    && printf '%s\n' "$reviewed_out" | grep -q 'refusing --refresh.*reviewed truth'; then
  ok "bench-extract refuses to refresh reviewed truth"
else
  ng "bench-extract refreshed reviewed truth or returned the wrong error: code=$reviewed_code output=[$reviewed_out]"
fi

# bench-score: one reviewed item has one hit, one missed truth entry, one BLOCK false positive,
# and one NOTE false positive. A second item is deliberately unpruned and must stay out of every
# denominator. Keeping both locations in the same file separates hunk from file granularity.
score_corpus="$sandbox_root/score-corpus"; score_run="$sandbox_root/score-run"
score_item="00021-00030"; unpruned_item="00022-00031"
mkdir -p "$score_corpus/$score_item" "$score_corpus/$unpruned_item" "$score_run/$score_item"
printf '%s\n' '{"repo":"example/repo","number":21,"sha":"head","base_sha":"base","title":"feature","fixed_by":30,"grade":"easy"}' \
  > "$score_corpus/$score_item/pr.json"
printf '%s\n' '[
  {"file":"app.py","lines":[10,12],"source":"fix#30","reviewed":true,"note":"first"},
  {"file":"app.py","lines":[100,102],"source":"fix#30","reviewed":true,"note":"second"}
]' > "$score_corpus/$score_item/truth.json"
printf '%s\n' '{"repo":"example/repo","number":22,"sha":"head2","base_sha":"base","title":"feature 2","fixed_by":31,"grade":null}' \
  > "$score_corpus/$unpruned_item/pr.json"
printf '%s\n' '[{"file":"later.py","lines":[1,1],"source":"fix#31","reviewed":false,"note":""}]' \
  > "$score_corpus/$unpruned_item/truth.json"
printf '%s\n' \
  '## Review result' \
  '### Blockers (BLOCK)' \
  '| # | Confidence | Where | How it breaks |' \
  '|---|---|---|---|' \
  '| 1 | CONFIRMED | `app.py:11` | hit |' \
  '| 2 | PLAUSIBLE | `app.py:90` | hunk false positive |' \
  '### Fix before merge (FIX)' \
  '| # | Confidence | Where | How it breaks |' \
  '|---|---|---|---|' \
  '### Recorded only (NOTE)' \
  '- `note.py:5` is a note false positive' \
  > "$score_run/$score_item/verdict.md"
printf '%s\n' '{"token_usage":{"input":100,"cache_read":20,"cache_creation":30,"output":10}}' \
  > "$score_run/$score_item/session.json"

hunk_text=$("$root/bin/plumb-bench-score" --corpus "$score_corpus" --run "demo=$score_run")
hunk_json=$("$root/bin/plumb-bench-score" --corpus "$score_corpus" --run "demo=$score_run" --json)
hunk_text_numbers=$(printf '%s\n' "$hunk_text" | awk '$1 == "demo" && $2 == "overall" {print $4 "/" $5 "/" $6 "/" $7 "/" $8 "/" $9 "/" $10 "/" $11}')
hunk_json_numbers=$(printf '%s\n' "$hunk_json" | python3 -c 'import json, sys
r=json.load(sys.stdin)["runs"][0]["overall"]
print("{:.3f}/{:.3f}/{:.3f}/{}/{}/{}/{:.0f}/{:.0f}".format(
    r["precision"], r["recall"], r["f1"], r["findings"], r["truth_entries"],
    r["matched"], r["tokens_per_review"], r["tokens_per_review_median"]))')
eq "bench-score hunk precision/recall/F1 and JSON parity" "$hunk_json_numbers" "0.500/0.500/0.500/2/2/1/160/160"
eq "bench-score text carries the JSON numbers" "$hunk_text_numbers" "$hunk_json_numbers"
printf '%s\n' "$hunk_text" | grep -q '^not pruned yet: 00022-00031$' \
  && ok "bench-score lists the item that is not pruned yet" || ng "bench-score hid the unpruned item: [$hunk_text]"

file_numbers=$("$root/bin/plumb-bench-score" --corpus "$score_corpus" --run "demo=$score_run" \
  --granularity file --json | python3 -c 'import json, sys
r=json.load(sys.stdin)["runs"][0]["overall"]
print("{:.3f}/{:.3f}/{:.3f}/{}".format(r["precision"], r["recall"], r["f1"], r["matched"]))')
eq "bench-score file granularity matches separate hunks in one file" "$file_numbers" "1.000/1.000/1.000/2"

note_numbers=$("$root/bin/plumb-bench-score" --corpus "$score_corpus" --run "demo=$score_run" \
  --include-note --json | python3 -c 'import json, sys
r=json.load(sys.stdin)["runs"][0]["overall"]
print("{:.4f}/{:.4f}/{:.4f}/{}".format(r["precision"], r["recall"], r["f1"], r["findings"]))')
eq "bench-score include-note adds the located NOTE finding" "$note_numbers" "0.3333/0.5000/0.4000/3"

score_tolerant_corpus="$sandbox_root/score-tolerant-corpus"
score_tolerant_run="$sandbox_root/score-tolerant-run"
template_item="00041-00042"; free_form_item="00043-00044"
mkdir -p "$score_tolerant_corpus/$template_item" "$score_tolerant_run/$template_item" \
  "$score_tolerant_corpus/$free_form_item" "$score_tolerant_run/$free_form_item"
printf '%s\n' '{"repo":"example/repo","number":41,"sha":"head","base_sha":"base","title":"template","fixed_by":42,"grade":"easy"}' \
  > "$score_tolerant_corpus/$template_item/pr.json"
printf '%s\n' '[{"file":"scripts/e2e-lib.mjs","lines":[45,49],"source":"fix#42","reviewed":true,"note":"middle location"}]' \
  > "$score_tolerant_corpus/$template_item/truth.json"
printf '%s\n' \
  '## Fix before merge (FIX):' \
  '| # | Confidence | Where | How it breaks |' \
  '|---|---|---|---|' \
  '| 1 | CONFIRMED | `scripts/e2e-core.mjs:184`, `scripts/e2e-lib.mjs:47`, `terraform/staging/README.md:160` | three places |' \
  > "$score_tolerant_run/$template_item/verdict.md"
printf '%s\n' '{"repo":"example/repo","number":43,"sha":"head","base_sha":"base","title":"free form","fixed_by":44,"grade":"easy"}' \
  > "$score_tolerant_corpus/$free_form_item/pr.json"
printf '%s\n' '[{"file":".github/workflows/pr-gate.yml","lines":[72,78],"source":"fix#44","reviewed":true,"note":"free form"}]' \
  > "$score_tolerant_corpus/$free_form_item/truth.json"
printf '%s\n' \
  '### F-1 — [CONFIRMED / **BLOCK**] first finding' \
  '| | |' \
  '| --- | --- |' \
  '| Where | `.github/workflows/pr-gate.yml:75`（regex）／ `.github/pull_request_template.md:23` |' \
  '| 確度 | CONFIRMED |' \
  '### F-2 — [PLAUSIBLE / FIX] second finding' \
  'This finding deliberately has no Where line.' \
  > "$score_tolerant_run/$free_form_item/verdict.md"
tolerant_numbers=$("$root/bin/plumb-bench-score" --corpus "$score_tolerant_corpus" \
  --run "tolerant=$score_tolerant_run" --json | python3 -c 'import json, sys
rows={row["id"]: row for row in json.load(sys.stdin)["runs"][0]["items"]}
print("{}/{}|{}/{}".format(rows["00041-00042"]["findings"], rows["00041-00042"]["matched"],
                         rows["00043-00044"]["findings"], rows["00043-00044"]["matched"]))')
eq "bench-score accepts multi-location level-2 sections and free-form findings" \
  "$tolerant_numbers" "1/1|2/1"

translated_item="00321-00332"
mkdir -p "$score_tolerant_corpus/$translated_item" "$score_tolerant_run/$translated_item"
printf '%s\n' '{"repo":"example/repo","number":321,"sha":"head","base_sha":"base","title":"translated table","fixed_by":332,"grade":"easy"}' \
  > "$score_tolerant_corpus/$translated_item/pr.json"
printf '%s\n' '[
  {"file":".github/workflows/pr-gate.yml","lines":[64,70],"source":"fix#332","reviewed":true,"note":"first translated row"},
  {"file":".github/workflows/pr-gate.yml","lines":[72,78],"source":"fix#332","reviewed":true,"note":"second translated row"}
]' > "$score_tolerant_corpus/$translated_item/truth.json"
printf '%s\n' \
  '## ブロッカー（BLOCK）' \
  '| # | 確度 | 箇所 | 壊れ方 |' \
  '|---|---|---|---|' \
  '| 1 | CONFIRMED | `.github/workflows/pr-gate.yml:60` | first |' \
  '## マージ前に直す（FIX）' \
  '| # | 確度 | 箇所 | 壊れ方 |' \
  '|---|---|---|---|' \
  '| 1 | CONFIRMED | `.github/workflows/pr-gate.yml:53-67` | second |' \
  > "$score_tolerant_run/$translated_item/verdict.md"
translated_numbers=$("$root/bin/plumb-bench-score" --corpus "$score_tolerant_corpus" \
  --run "tolerant=$score_tolerant_run" --json | python3 -c 'import json, sys
rows={row["id"]: row for row in json.load(sys.stdin)["runs"][0]["items"]}
row=rows["00321-00332"]
print("{}/{}".format(row["findings"], row["matched"]))')
eq "bench-score reads locations from translated tables without a Where column" \
  "$translated_numbers" "2/2"

summary_item="00225-00234"
mkdir -p "$score_tolerant_corpus/$summary_item" "$score_tolerant_run/$summary_item"
printf '%s\n' '{"repo":"example/repo","number":225,"sha":"head","base_sha":"base","title":"summary and details","fixed_by":234,"grade":"medium"}' \
  > "$score_tolerant_corpus/$summary_item/pr.json"
printf '%s\n' '[{"file":"frontend/src/lib/db/auth-repo.ts","lines":[10,12],"source":"fix#234","reviewed":true,"note":"one overlap"}]' \
  > "$score_tolerant_corpus/$summary_item/truth.json"
printf '%s\n' \
  '## 2. Findings' \
  '| # | 確度 | ブロッキング | 件名 | Where |' \
  '|---|---|---|---|---|' \
  '| F1 | CONFIRMED | FIX | first | `frontend/src/lib/db/auth-repo.ts:11` |' \
  '| F2 | CONFIRMED | BLOCK | second | `frontend/src/lib/db/repo.ts:20` |' \
  '| F3 | CONFIRMED | FIX | third | `frontend/src/lib/db/repo.ts:30` |' \
  '| F4 | CONFIRMED | FIX | fourth | `frontend/src/db/migrations/0028.sql:40` / `terraform/production/cloudrun.tf:41` |' \
  '| F5 | CONFIRMED | FIX | fifth | `frontend/src/app/admin/tenant.tsx:50` |' \
  '### F1 — first' \
  '- **Where**: `frontend/src/lib/db/auth-repo.ts:11`' \
  '### F-2 — second' \
  '* Where - `frontend/src/lib/db/repo.ts:20`' \
  '### f 3 — third' \
  '| Where | `frontend/src/lib/db/repo.ts:30` |' \
  '### F4 — fourth' \
  'Where: `frontend/src/db/migrations/0028.sql:40` / `terraform/production/cloudrun.tf:41`' \
  '### f-5 — fifth' \
  '- __Where__: `frontend/src/app/admin/tenant.tsx:50`' \
  '## 3. NOTE（記録のみ・今回は直さない）' \
  '| # | 内容 | Where |' \
  '|---|---|---|' \
  '| N1 | first note | `notes/one.md:1` |' \
  '| N2 | says FIX but remains a note | `notes/two.md:2` |' \
  '| N3 | third note | `notes/three.md:3` |' \
  '### N1 — first note detail' \
  '- **Where**: `notes/one.md:1`' \
  > "$score_tolerant_run/$summary_item/verdict.md"
summary_numbers=$(
  "$root/bin/plumb-bench-score" --corpus "$score_tolerant_corpus" \
    --run "tolerant=$score_tolerant_run" --json | python3 -c 'import json, sys
rows={row["id"]: row for row in json.load(sys.stdin)["runs"][0]["items"]}
row=rows["00225-00234"]
print("{}/{}".format(row["findings"], row["matched"]), end="")'
  "$root/bin/plumb-bench-score" --corpus "$score_tolerant_corpus" \
    --run "tolerant=$score_tolerant_run" --include-note --json | python3 -c 'import json, sys
rows={row["id"]: row for row in json.load(sys.stdin)["runs"][0]["items"]}
row=rows["00225-00234"]
print("|{}/{}".format(row["findings"], row["matched"]))'
)
eq "bench-score deduplicates 00225-shaped tables and headings while gating NOTE rows" \
  "$summary_numbers" "5/1|8/1"

table_rules_item="00045-00046"
mkdir -p "$score_tolerant_corpus/$table_rules_item" "$score_tolerant_run/$table_rules_item"
printf '%s\n' '{"repo":"example/repo","number":45,"sha":"head","base_sha":"base","title":"table rules","fixed_by":46,"grade":"easy"}' \
  > "$score_tolerant_corpus/$table_rules_item/pr.json"
printf '%s\n' '[{"file":"target.py","lines":[4,6],"source":"fix#46","reviewed":true,"note":"severity row"}]' \
  > "$score_tolerant_corpus/$table_rules_item/truth.json"
printf '%s\n' \
  '## Context' \
  '| Status | wHeRe |' \
  '|---|---|' \
  '| BLOCK | `target.py:5` |' \
  '| informational | `context.md:2` |' \
  '## Findings from scan' \
  '| Detail | Where |' \
  '|---|---|' \
  '| no severity word | `finding.py:3` |' \
  '## Appendix NOTE' \
  '| Status | Where |' \
  '|---|---|' \
  '| FIX | `note-table.md:4` |' \
  '### N-1 — numbered note' \
  'Where: `note-heading.md:5`' \
  > "$score_tolerant_run/$table_rules_item/verdict.md"
table_rule_numbers=$(
  "$root/bin/plumb-bench-score" --corpus "$score_tolerant_corpus" \
    --run "tolerant=$score_tolerant_run" --json | python3 -c 'import json, sys
rows={row["id"]: row for row in json.load(sys.stdin)["runs"][0]["items"]}
row=rows["00045-00046"]
print("{}/{}".format(row["findings"], row["matched"]), end="")'
  "$root/bin/plumb-bench-score" --corpus "$score_tolerant_corpus" \
    --run "tolerant=$score_tolerant_run" --include-note --json | python3 -c 'import json, sys
rows={row["id"]: row for row in json.load(sys.stdin)["runs"][0]["items"]}
row=rows["00045-00046"]
print("|{}/{}".format(row["findings"], row["matched"]))'
)
eq "bench-score applies generic table headings, row severity, and numbered NOTE rules" \
  "$table_rule_numbers" "2/1|5/1"

pareto_noisy="$sandbox_root/pareto-noisy"; pareto_tie="$sandbox_root/pareto-tie"
pareto_outlier="$sandbox_root/pareto-outlier"
pareto_uncosted="$sandbox_root/pareto-uncosted"; missing_run="$sandbox_root/missing-run"
mkdir -p "$pareto_noisy/$score_item" "$pareto_tie/$score_item" \
  "$pareto_outlier/$score_item" "$pareto_uncosted/$score_item" "$missing_run/$score_item"
printf '%s\n' \
  '### Blockers (BLOCK)' \
  '| # | Confidence | Where | How it breaks |' \
  '|---|---|---|---|' \
  '| 1 | CONFIRMED | `app.py:11` | hit |' \
  '| 2 | PLAUSIBLE | `app.py:70` | false positive |' \
  '| 3 | PLAUSIBLE | `other.py:1` | false positive |' \
  '### Fix before merge (FIX)' \
  '| # | Confidence | Where | How it breaks |' \
  '|---|---|---|---|' \
  > "$pareto_noisy/$score_item/verdict.md"
cp "$score_run/$score_item/session.json" "$pareto_noisy/$score_item/session.json"
cp "$score_run/$score_item/verdict.md" "$pareto_tie/$score_item/verdict.md"
cp "$score_run/$score_item/session.json" "$pareto_tie/$score_item/session.json"
printf '%s\n' \
  '### Blockers (BLOCK)' \
  '| # | Confidence | Where | How it breaks |' \
  '|---|---|---|---|' \
  '| 1 | CONFIRMED | `app.py:11` | first hit |' \
  '| 2 | CONFIRMED | `app.py:101` | second hit |' \
  '### Fix before merge (FIX)' \
  '| # | Confidence | Where | How it breaks |' \
  '|---|---|---|---|' \
  > "$pareto_uncosted/$score_item/verdict.md"
printf '%s\n' '{"token_totals":{"input":100,"cache_creation":30,"output":10}}' \
  > "$pareto_uncosted/$score_item/session.json"

# Give the Pareto comparison three reviews per run. The outlier run has a higher mean than demo
# but a lower median, so it belongs on the frontier only when median tokens/review drives cost.
pareto_item_two="00031-00032"; pareto_item_three="00033-00034"
for item in "$pareto_item_two" "$pareto_item_three"; do
  mkdir -p "$score_corpus/$item" "$score_run/$item" "$pareto_noisy/$item" \
    "$pareto_tie/$item" "$pareto_outlier/$item" "$pareto_uncosted/$item"
  cp "$score_corpus/$score_item/pr.json" "$score_corpus/$item/pr.json"
  cp "$score_corpus/$score_item/truth.json" "$score_corpus/$item/truth.json"
  cp "$score_run/$score_item/verdict.md" "$score_run/$item/verdict.md"
  cp "$score_run/$score_item/session.json" "$score_run/$item/session.json"
  cp "$pareto_noisy/$score_item/verdict.md" "$pareto_noisy/$item/verdict.md"
  cp "$pareto_noisy/$score_item/session.json" "$pareto_noisy/$item/session.json"
  cp "$pareto_tie/$score_item/verdict.md" "$pareto_tie/$item/verdict.md"
  cp "$pareto_tie/$score_item/session.json" "$pareto_tie/$item/session.json"
  cp "$pareto_uncosted/$score_item/verdict.md" "$pareto_uncosted/$item/verdict.md"
  cp "$pareto_uncosted/$score_item/session.json" "$pareto_uncosted/$item/session.json"
done
for item in "$score_item" "$pareto_item_two" "$pareto_item_three"; do
  cp "$score_run/$score_item/verdict.md" "$pareto_outlier/$item/verdict.md"
done
printf '%s\n' '{"token_usage":{"input":1000,"cache_read":0,"cache_creation":0,"output":0}}' \
  > "$pareto_outlier/$score_item/session.json"
for item in "$pareto_item_two" "$pareto_item_three"; do
  printf '%s\n' '{"token_usage":{"input":10,"cache_read":0,"cache_creation":0,"output":0}}' \
    > "$pareto_outlier/$item/session.json"
done

pareto_out=$("$root/bin/plumb-bench-score" --corpus "$score_corpus" \
  --run "demo=$score_run" --run "noisy=$pareto_noisy" --run "tie=$pareto_tie" \
  --run "outlier=$pareto_outlier" --run "uncosted=$pareto_uncosted")
pareto_json=$("$root/bin/plumb-bench-score" --corpus "$score_corpus" \
  --run "demo=$score_run" --run "noisy=$pareto_noisy" --run "tie=$pareto_tie" \
  --run "outlier=$pareto_outlier" --run "uncosted=$pareto_uncosted" --json)
pareto_median_check=$(printf '%s\n' "$pareto_json" | python3 -c 'import json, sys
r=json.load(sys.stdin)
runs={run["name"]: run["overall"] for run in r["runs"]}
outlier=runs["outlier"]
ok=(outlier["tokens_per_review"] > runs["demo"]["tokens_per_review"]
    and outlier["tokens_per_review_median"] < runs["demo"]["tokens_per_review_median"]
    and r["pareto"] == ["outlier"])
print("ok" if ok else "wrong")')
if printf '%s\n' "$pareto_out" | grep -q '^pareto: outlier (by median tokens/review)$' \
    && printf '%s\n' "$pareto_out" | grep -q \
      '^not compared: uncosted (tokens/review unavailable; token_totals missing cache_read)$' \
    && [ "$pareto_median_check" = "ok" ]; then
  ok "bench-score uses median cost for Pareto despite an inflated mean"
else
  ng "bench-score Pareto disclosure is wrong: [$pareto_out]"
fi

rm -rf "$score_corpus/$pareto_item_two" "$score_corpus/$pareto_item_three"

missing_out=$("$root/bin/plumb-bench-score" --corpus "$score_corpus" --run "missing=$missing_run" 2>&1)
missing_code=$?
if [ "$missing_code" = 0 ] && printf '%s\n' "$missing_out" | grep -q \
    '^no verdict: missing/00021-00030$' && printf '%s\n' "$missing_out" | grep -Eq \
    '^missing[[:space:]]+overall[[:space:]]+all[[:space:]]+0\.000[[:space:]]+0\.000[[:space:]]+0\.000[[:space:]]+0[[:space:]]+2[[:space:]]+0'; then
  ok "bench-score lists a missing verdict and scores it as zero findings"
else
  ng "bench-score mishandled a missing verdict: code=$missing_code output=[$missing_out]"
fi

unpruned="$sandbox_root/unpruned-corpus"; mkdir -p "$unpruned/$unpruned_item"
cp "$score_corpus/$unpruned_item/pr.json" "$score_corpus/$unpruned_item/truth.json" "$unpruned/$unpruned_item/"
"$root/bin/plumb-bench-score" --corpus "$unpruned" --run "demo=$score_run" >/dev/null 2>&1
eq "bench-score refuses a fully unpruned corpus with exit 2" "$?" "2"

# A key that is configured returns its value
eq "a configured key" "$(PLUMB_CONFIG="$cfg" bash "$root/scripts/plumb-config.sh" role.judge)" "codex"
# Whitespace around the value is stripped
eq "whitespace is stripped" "$(PLUMB_CONFIG="$cfg" bash "$root/scripts/plumb-config.sh" role.bulk)" "cursor-agent"
# An unset key returns the default
eq "unset returns the default" "$(PLUMB_CONFIG="$cfg" bash "$root/scripts/plumb-config.sh" pane.driver none)" "none"
# With no config file it still returns the default and does not exit abnormally
eq "the default even with no file" "$(PLUMB_CONFIG=/nonexistent bash "$root/scripts/plumb-config.sh" role.judge none)" "none"
PLUMB_CONFIG=/nonexistent bash "$root/scripts/plumb-config.sh" role.judge >/dev/null 2>&1 \
  && ok "exit 0 even with no file" || ng "exited abnormally with no file"
# A key holding regex metacharacters does not mismatch onto another line
eq "a key with metacharacters does not mismatch" "$(PLUMB_CONFIG="$cfg" bash "$root/scripts/plumb-config.sh" 'role.[judge' DEFAULT)" "DEFAULT"

# Codex installation is additive and idempotent. Exercise it only against the temporary home.
codex_home="$sandbox_root/codex-home"
CODEX_HOME="$codex_home" "$root/bin/plumb-codex-install" --user >/dev/null 2>&1
eq "Codex user profile is installed" "$?" "0"
cmp -s "$root/.codex/config.toml" "$codex_home/plumb.config.toml" \
  && ok "Codex profile matches the project source" \
  || ng "Codex profile differs from the project source"
installed_agents=$(find "$codex_home/agents" -name '*.toml' -type f | wc -l | tr -d ' ')
eq "Codex custom agents are installed" "$installed_agents" "10"
CODEX_HOME="$codex_home" "$root/bin/plumb-codex-install" --user --check >/dev/null 2>&1
eq "Codex install check accepts an exact installation" "$?" "0"
CODEX_HOME="$codex_home" "$root/bin/plumb-codex-install" --user >/dev/null 2>&1
eq "Codex installer is idempotent" "$?" "0"
printf '# local change\n' >> "$codex_home/agents/plumb-explorer.toml"
CODEX_HOME="$codex_home" "$root/bin/plumb-codex-install" --user >/dev/null 2>&1
eq "Codex installer refuses a differing destination" "$?" "1"
CODEX_HOME="$codex_home" "$root/bin/plumb-codex-install" --user --force >/dev/null 2>&1
eq "Codex installer force restores plumb-owned files" "$?" "0"
cmp -s "$root/.codex/agents/plumb-explorer.toml" "$codex_home/agents/plumb-explorer.toml" \
  && ok "Codex force install restored the agent" \
  || ng "Codex force install did not restore the agent"

# The optional setup entrypoint is loaded from an installed plugin, not from the source checkout a
# person happened to clone. Recreate that package shape and execute the setup skill's own adapter
# against a clean Codex home. If the skill moves without its adapter or installer, or packaging omits
# any part of that path, this test goes red.
plugin_copy="$sandbox_root/plugin-cache/plumb/plumb/0.7.0"
setup_home="$sandbox_root/setup-home"
if [ -f "$root/skills/setup/SKILL.md" ]; then
  mkdir -p "$plugin_copy/skills" "$plugin_copy/bin"
  cp -R "$root/skills/setup" "$plugin_copy/skills/setup"
  cp -R "$root/.codex" "$plugin_copy/.codex"
  cp "$root/bin/plumb-codex-install" "$plugin_copy/bin/plumb-codex-install"
  setup_adapter="$plugin_copy/skills/setup/scripts/install.sh"
  CODEX_HOME="$setup_home" "$setup_adapter" --user >/dev/null 2>&1
  setup_code=$?
  if [ -x "$setup_adapter" ] \
      && [ "$setup_code" = 0 ] \
      && cmp -s "$plugin_copy/.codex/config.toml" "$setup_home/plumb.config.toml" \
      && [ "$(find "$setup_home/agents" -name '*.toml' -type f | wc -l | tr -d ' ')" = 10 ]; then
    ok "installed-plugin setup resolves and installs the optional Codex sidecar"
  else
    ng "installed-plugin setup failed: code=$setup_code"
  fi
else
  ng "installed-plugin setup skill is missing"
fi

# Preflight must make a conflicting install all-or-nothing, and --force must not follow a target link.
conflict_home="$sandbox_root/codex-conflict-home"
mkdir -p "$conflict_home"
printf '# owner configuration\n' > "$conflict_home/plumb.config.toml"
CODEX_HOME="$conflict_home" "$root/bin/plumb-codex-install" --user >/dev/null 2>&1
eq "Codex conflict fails before installation" "$?" "1"
[ ! -e "$conflict_home/agents/plumb-worker.toml" ] \
  && ok "Codex conflict leaves no mixed agent state" \
  || ng "Codex conflict installed agents before failing"

link_home="$sandbox_root/codex-link-home"
mkdir -p "$link_home"
external_config="$sandbox_root/external-codex-config"
printf '# external data\n' > "$external_config"
ln -s "$external_config" "$link_home/plumb.config.toml"
CODEX_HOME="$link_home" "$root/bin/plumb-codex-install" --user --force >/dev/null 2>&1
eq "Codex force install rejects a symbolic-link destination" "$?" "1"
eq "Codex force install leaves the link target untouched" "$(cat "$external_config")" "# external data"

directory_home="$sandbox_root/codex-directory-home"
mkdir -p "$directory_home/plumb.config.toml"
CODEX_HOME="$directory_home" "$root/bin/plumb-codex-install" --user --force >/dev/null 2>&1
eq "Codex force install rejects a directory destination" "$?" "1"
[ ! -e "$directory_home/plumb.config.toml/config.toml" ] \
  && ok "Codex directory destination receives no nested config" \
  || ng "Codex installer copied into a destination directory"

# Atomic per-file replacement means an interrupted run cannot leave a truncated target. Exact installed
# files plus a missing destination are the recoverable state; a normal rerun must converge from it.
rm "$codex_home/agents/plumb-worker.toml"
CODEX_HOME="$codex_home" "$root/bin/plumb-codex-install" --user >/dev/null 2>&1
eq "Codex install converges when one destination is missing" "$?" "0"
cmp -s "$root/.codex/agents/plumb-worker.toml" "$codex_home/agents/plumb-worker.toml" \
  && ok "Codex rerun restored the missing agent" \
  || ng "Codex rerun did not restore the missing agent"

project_install="$sandbox_root/codex-project"
mkdir -p "$project_install"
"$root/bin/plumb-codex-install" --project "$project_install" >/dev/null 2>&1
eq "Codex project configuration is installed" "$?" "0"
cmp -s "$root/.codex/config.toml" "$project_install/.codex/config.toml" \
  && ok "Codex project profile matches the source" \
  || ng "Codex project profile differs from the source"

# isolate-pollution: separating out "it passes alone but fails as a set".
# What matters is not **finding** the culprit but never silently returning 0 when it was not
# found and when the premise is broken (**principle-gate-claims-on-evidence**).
ipd="$sandbox_root/ip"; mkdir -p "$ipd"
mark="$ipd/MARK"
printf '#!/bin/sh\nexit 0\n' > "$ipd/clean.sh"
printf '#!/bin/sh\ntouch "%s"\n' "$mark" > "$ipd/dirty.sh"
printf '#!/bin/sh\ntouch "%s"\n' "$mark" > "$ipd/di rty.sh"   # a name with a space in it
ip() { ( cd "$ipd" && bash "$root/scripts/isolate-pollution.sh" "$@" ); }

rm -f "$mark"
out=$(ip "test -e $mark" sh clean.sh dirty.sh clean.sh); code=$?
eq "it identifies the polluter" "$code" "1"
printf '%s' "$out" | grep -q 'polluter: dirty.sh' \
  && ok "it prints the polluter's name" || ng "the polluter's name is not printed: [$out]"

rm -f "$mark"
ip "test -e $mark" sh clean.sh clean.sh >/dev/null 2>&1
eq "0 when there is no culprit" "$?" "0"

# Residue left over before the run makes the first case look guilty. Return 1 here and
# **an innocent case gets reported as the culprit.** A broken premise fails with a different code.
touch "$mark"
ip "test -e $mark" sh clean.sh >/dev/null 2>&1
eq "pre-existing pollution fails with 2" "$?" "2"
rm -f "$mark"

ip foo >/dev/null 2>&1
eq "too few arguments fails with 2" "$?" "2"

# Split a target name on its space and it runs an unrelated name and names the wrong culprit
rm -f "$mark"
out=$(ip "test -e $mark" sh clean.sh 'di rty.sh')
printf '%s' "$out" | grep -q 'polluter: di rty.sh' \
  && ok "it does not split a name with a space" || ng "it breaks on a name with a space: [$out]"

# Run doctor while imitating "the machine of someone who has none of this".
# Let only git and gh through; take the optional tools (codex / cursor-agent / herdr) off PATH.
# Do this on the bare PATH and, in an environment where those exist, it is vacuously true and the
# branch goes unverified.
sandbox="$sandbox_root/bin"; mkdir -p "$sandbox"
for c in git gh; do
  # `command -v` also picks up shell functions and aliases. `type -P` returns only the real file
  # on PATH. Fail to get the real file here and doctor runs with $c missing from the sandbox, and
  # **a broken premise in the test gets reported as a defect in doctor.** Fail in different words.
  p=$(type -P "$c" 2>/dev/null)
  if [ -n "$p" ] && [ -x "$p" ]; then
    ln -s "$p" "$sandbox/$c"
  else
    ng "cannot stage $c in the sandbox (not a defect in doctor: the premise of this test is broken)"
  fi
done

# Strip PATH but leave HOME alone and the owner's own ~/.claude (private agents and all) is always
# true, so the "someone who has none of this" branch goes unverified. Build a fake HOME and imitate
# **someone who installed plumb and nothing optional at all.**
# Until 2026-08-30 a superpowers directory was created here, because plumb checked for it as a
# dependency. **The dependencies are gone, so it comes out of what we imitate too.**
fake_home="$sandbox_root/home"
mkdir -p "$fake_home/.claude/projects" \
         "$fake_home/.claude/agents"

out=$(HOME="$fake_home" PATH="$sandbox:/usr/bin:/bin:/usr/sbin:/sbin" PLUMB_RUNTIME=claude PLUMB_IN_SELFTEST=1 PLUMB_CONFIG=/nonexistent \
      bash "$root/scripts/doctor.sh" "$root" 2>&1)
ng_count=$(printf '%s\n' "$out" | grep -c '^  NG ' || true)
eq "NG count from doctor in a bare environment" "$ng_count" "0"

# Codex-only users must not need a Claude installation. Test the CLI's structured installed list,
# including a disabled plugin and a similarly named plugin (neither is an enabled plumb install).
codex_only_home="$sandbox_root/codex-only-home"
mkdir -p "$codex_only_home"
printf '#!/bin/sh\nprintf '\''%%s\\n'\'' "$PLUMB_TEST_PLUGINS"\n' > "$sandbox/codex"
chmod +x "$sandbox/codex"
python_bin=$(type -P python3 2>/dev/null || true)
if [ -n "$python_bin" ]; then
  ln -s "$python_bin" "$sandbox/python3"
  codex_doctor() {
    HOME="$codex_only_home" PATH="$sandbox:/usr/bin:/bin:/usr/sbin:/sbin" \
      PLUMB_RUNTIME=codex PLUMB_IN_SELFTEST=1 PLUMB_CONFIG=/nonexistent \
      PLUMB_TEST_PLUGINS="$1" bash "$root/scripts/doctor.sh" "$root" 2>&1
  }
  out=$(codex_doctor '{"installed":[{"name":"plumb","installed":true,"enabled":true}]}'); code=$?
  eq "doctor accepts Codex-only installation without Claude directories" "$code" "0"
  printf '%s\n' "$out" | grep -q 'enabled Codex plugin: plumb' \
    && ok "doctor verifies Codex plugin enablement" || ng "doctor did not verify Codex loading"
  codex_doctor '{"installed":[{"name":"plumb","installed":true,"enabled":false}]}' >/dev/null
  eq "doctor rejects disabled Codex plugin" "$?" "1"
  codex_doctor '{"installed":[{"name":"plumb-extra","installed":true,"enabled":true}]}' >/dev/null
  eq "doctor rejects a similarly named Codex plugin" "$?" "1"
  codex_doctor '{broken' >/dev/null
  eq "doctor rejects malformed Codex plugin output" "$?" "1"
else
  printf '  %-4s %s\n' "--" "Codex loading fixtures skipped: python3 unavailable"
fi

# prompt-weight: a synthetic home with one enabled and one disabled plugin. Never the real one.
if command -v python3 >/dev/null 2>&1; then
  pw_home="$sandbox_root/pw-home"
  pw_plugin="$pw_home/.claude/plugins/cache/mk/on/1.0.0"
  mkdir -p "$pw_home/.claude/plugins" "$pw_plugin/skills/one" "$pw_plugin/hooks" "$pw_home/.claude/skills/mine" "$sandbox_root/pw-project"
  printf '# rules\nkeep it short\n' > "$pw_home/.claude/CLAUDE.md"
  printf -- '---\nname: one\ndescription: the one skill\n---\nbody that must not count\n' > "$pw_plugin/skills/one/SKILL.md"
  printf '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo must-not-run > %s/hook-ran"}]}]}}\n' "$sandbox_root" > "$pw_plugin/hooks/hooks.json"
  printf -- '---\nname: mine\ndescription: a user skill\n---\n' > "$pw_home/.claude/skills/mine/SKILL.md"
  printf '{"enabledPlugins":{"on@mk":true,"off@mk":false},"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo must-not-run-either"}]}]}}\n' > "$pw_home/.claude/settings.json"
  printf '{"version":1,"plugins":{"on@mk":[{"installPath":"%s"}],"off@mk":[{"installPath":"%s"}]}}\n' "$pw_plugin" "$pw_plugin" > "$pw_home/.claude/plugins/installed_plugins.json"
  mkdir -p "$sandbox_root/pw-project/.claude/skills/local-one"
  printf -- '---\nname: local-one\ndescription: a project skill\n---\nproject body must not count\n' > "$sandbox_root/pw-project/.claude/skills/local-one/SKILL.md"
  printf '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo project-hook-must-not-run"}]}]}}\n' > "$sandbox_root/pw-project/.claude/settings.json"
  pw_text=$("$root/bin/plumb-prompt-weight" --home "$pw_home" --project "$sandbox_root/pw-project")
  pw_code=$?
  pw_json=$("$root/bin/plumb-prompt-weight" --home "$pw_home" --project "$sandbox_root/pw-project" --json)
  pw_check=$(python3 -c 'import json, sys
r = json.loads(sys.argv[1]); text = sys.argv[2]
names = [row["component"] for row in r["rows"]]
on = next(row for row in r["rows"] if row["component"] == "plugin on@mk")
ok = ("plugin off@mk" not in names
      and on["bytes"] == len("the one skill\n") and "1 session-start hook(s); not executed" in on["note"]
      and "must not count" not in text and "the one skill" not in text
      and next(row for row in r["rows"] if row["component"] == "project skills (listing)")["bytes"] == len("a project skill\n")
      and any(row["component"] == "session-start hooks (project settings)" for row in r["rows"])
      and "must not count" not in text
      and r["total"]["bytes"] == sum(row["bytes"] for row in r["rows"])
      and "not executed" in text and text.rstrip().endswith("not visible here"))
print("ok" if ok else "wrong")' "$pw_json" "$pw_text")
  eq "prompt-weight exits 0 on a synthetic home" "$pw_code" "0"
  eq "prompt-weight lists enabled plugins and project skills, counts descriptions not bodies, and never prints contents" "$pw_check" "ok"
  [ -e "$sandbox_root/hook-ran" ] && ng "prompt-weight executed a session-start hook" || ok "prompt-weight never executes a hook"
  empty_home="$sandbox_root/pw-empty"; mkdir -p "$empty_home"
  "$root/bin/plumb-prompt-weight" --home "$empty_home" --project "$empty_home" >/dev/null 2>&1
  eq "prompt-weight exits 0 on an empty home" "$?" "0"
else
  printf '  %-4s %s\n' "--" "python3 not on PATH, prompt-weight assertions skipped"
fi

# statusline-cost: stdin JSON in, one segment out. Config through PLUMB_CONFIG only.
if command -v python3 >/dev/null 2>&1; then
  sl_cfg="$sandbox_root/sl-config"; : > "$sl_cfg"
  eq "statusline-cost prints the dollar figure" "$(printf '{"cost":{"total_cost_usd":1.5}}' | PLUMB_CONFIG=$sl_cfg "$root/bin/plumb-statusline-cost")" $'\033[1;37m$1.50\033[0m'
  printf 'cost.jpy_per_usd = 150\n' > "$sl_cfg"
  eq "statusline-cost adds yen when the rate is configured" "$(printf '{"cost":{"total_cost_usd":1.5}}' | PLUMB_CONFIG=$sl_cfg "$root/bin/plumb-statusline-cost")" $'\033[1;37m$1.50\033[0m \033[1;37m¥225\033[0m'
  printf 'cost.session_budget_usd = 30\n' > "$sl_cfg"
  sl_under=$(printf '{"cost":{"total_cost_usd":1.5}}' | PLUMB_CONFIG=$sl_cfg "$root/bin/plumb-statusline-cost")
  case "$sl_under" in *$'\033[1;37m'*'5%'*) ok "statusline-cost paints the under-50 band white";; *) ng "statusline-cost under-band colour wrong: [$sl_under]";; esac
  printf 'cost.session_budget_usd = 2\n' > "$sl_cfg"
  sl_out=$(printf '{"cost":{"total_cost_usd":1.5}}' | PLUMB_CONFIG=$sl_cfg "$root/bin/plumb-statusline-cost")
  case "$sl_out" in *'75%'*) ok "statusline-cost shows the budget percentage";; *) ng "statusline-cost budget percentage missing: [$sl_out]";; esac
  case "$sl_out" in *$'\033[33m'*) ok "statusline-cost colours the 50-79 band yellow";; *) ng "statusline-cost band colour missing: [$sl_out]";; esac
  sl_over=$(printf '{"cost":{"total_cost_usd":2.5}}' | PLUMB_CONFIG=$sl_cfg "$root/bin/plumb-statusline-cost")
  case "$sl_over" in *$'\033[1;31m'*'125%'*) ok "statusline-cost turns bold red at 100 percent";; *) ng "statusline-cost over-budget colour wrong: [$sl_over]";; esac
  sl_none=$(printf '{}' | PLUMB_CONFIG=$sl_cfg "$root/bin/plumb-statusline-cost"); sl_none_code=$?
  eq "statusline-cost prints nothing without a cost field" "$sl_none|$sl_none_code" "|0"
else
  printf '  %-4s %s\n' "--" "python3 not on PATH, statusline-cost assertions skipped"
fi

if command -v python3 >/dev/null 2>&1; then
  python3 -B "$root/scripts/test-efficiency.py" \
    && ok "runtime usage and quality/cost gate regression suite" \
    || ng "runtime usage and quality/cost gate regression suite"
else
  printf '  %-4s %s\n' "--" "efficiency regression suite skipped: python3 unavailable"
fi

if [ $fail -eq 0 ]; then echo "  → passed"; else echo "  → failed"; fi
exit $fail
