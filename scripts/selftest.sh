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
printf 'role.judge = codex\nrole.bulk   =  cursor-agent  \n' > "$cfg"

# session-audit has eight assertions. python3 is optional, so missing it makes all eight visible
# skips instead of turning doctor's informational dependency into a failure.
if command -v python3 >/dev/null 2>&1; then
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
    --ctx-threshold 100 --tool-threshold 100)
  audit_json=$("$root/bin/plumb-session-audit" --transcripts "$audit_dir" --all \
    --ctx-threshold 100 --tool-threshold 100 --json)
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
ok = (counts == {"CTX-P90-OVER": 1, "TOOL-RESULT-OVER": 1, "IDLE-REBUILD": 1}
      and r["tool_results"] == {"over_percent": 33.3, "over_threshold": 1, "total": 3}
      and r["idle"] == {"cache_rebuilt_after": 1, "gaps": 1}
      and sessions["clean-session"]["context_p90"] == 41001
      and sessions["clean-session"]["main_context_p90"] == 61
      and sessions["clean-session"]["flags"] == [])
print("ok" if ok else "wrong")' "$audit_json_file")
  eq "session-audit isolates main-chain flags and measures tool results as UTF-8 bytes" "$flag_check" "ok"

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
  for audit_assertion in 1 2 3 4 5 6 7 8; do
    printf '  %-4s %s\n' "--" "python3 not on PATH, session-audit assertions skipped"
  done
fi

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

out=$(HOME="$fake_home" PATH="$sandbox:/usr/bin:/bin:/usr/sbin:/sbin" PLUMB_IN_SELFTEST=1 PLUMB_CONFIG=/nonexistent \
      bash "$root/scripts/doctor.sh" "$root" 2>&1)
ng_count=$(printf '%s\n' "$out" | grep -c '^  NG ' || true)
eq "NG count from doctor in a bare environment" "$ng_count" "0"

if [ $fail -eq 0 ]; then echo "  → passed"; else echo "  → failed"; fi
exit $fail
