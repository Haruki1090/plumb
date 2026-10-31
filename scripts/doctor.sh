#!/usr/bin/env bash
# plumb doctor — checks whether the environment the documents claim still exists.
# check-harness.sh looks at the inside for consistency; this looks at the seam with the outside.
# Usage: scripts/doctor.sh [plugin-root]
set -uo pipefail

case "${1:-}" in
  -h|--help)
    cat <<'EOF'
usage: plumb-doctor [plugin-root]

Checks that the environment plumb's documents describe still exists on this machine.
  ok  present and working
  --  unset, optional, or cannot check here (never a failure)
  NG  broken; the exit status is 1
PLUMB_RUNTIME=claude|codex picks the runtime (default: detect).
Run it from Claude Code's Bash tool, through the doctor skill, or as <plugin-root>/bin/plumb-doctor.
EOF
    exit 0 ;;
esac

root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
CLAUDE="$HOME/.claude"
runtime=${PLUMB_RUNTIME:-auto}
if [ "$runtime" = auto ]; then
  if [ -n "${CODEX_THREAD_ID:-}" ]; then runtime=codex; else runtime=claude; fi
fi
case "$runtime" in
  claude|codex) ;;
  *) printf 'usage: PLUMB_RUNTIME=auto|claude|codex plumb-doctor [plugin-root]\n' >&2; exit 2 ;;
esac
fail=0
note() { printf '  %-4s %s\n' "$1" "$2"; }
bad()  { note "NG" "$1"; fail=1; }
bounded() { local secs=$1; shift; if command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"; else "$@"; fi; }

echo "plumb doctor: $root"
note "--" "runtime: $runtime (override with PLUMB_RUNTIME)"

# 1. Inside consistency (delegated to check-harness. Do not write it twice)
echo "— inside"
# selftest runs doctor a dozen times to test its other blocks, and the release gate runs
# check-harness on its own, so a doctor started by selftest does not repeat it (about 2 s each).
if [ -n "${PLUMB_IN_SELFTEST:-}" ]; then
  note "--" "cross-cutting rules: skipped, called from selftest"
elif bash "$root/scripts/check-harness.sh" "$root" >/dev/null 2>&1; then
  note "ok" "cross-cutting rules (check-harness.sh)"
else
  bad "the cross-cutting rules are failing. Run scripts/check-harness.sh directly to see what"
fi

# When selftest called us, do not call back. That is mutual recursion.
if [ -n "${PLUMB_IN_SELFTEST:-}" ]; then
  note "--" "script behaviour: skipped, called from selftest"
# Quick mode: doctor answers "is the install broken", so the slow suites (5 MB stress bodies, the
# ledger's latency and concurrency cases) stay in the full selftest. Measured 2026-10-30: the full
# selftest took 71 s, near a runtime's two-minute command limit when doctor runs inside a session.
elif PLUMB_SELFTEST_QUICK=1 bash "$root/scripts/selftest.sh" "$root" >/dev/null 2>&1; then
  note "ok" "script behaviour (selftest.sh, quick; the full run is scripts/selftest.sh)"
else
  bad "selftest is failing. Run scripts/selftest.sh directly to see what"
fi

# 2. Routing targets. **Keep required and optional apart.**
#    Without git and gh, the playbooks do not work at all. Everything else is needed only once
#    you configure it. Report "you do not have it" as "it is broken" and the first experience
#    of plumb becomes "it is broken".
echo "— routing targets"
for c in git gh; do
  command -v "$c" >/dev/null 2>&1 && note "ok" "$c" || bad "$c is not on PATH (every plumb playbook assumes it)"
done
# python3 is used by plumb-pr-drift (skills/pr-review/scripts/pr-drift.sh),
# plumb-session-audit (scripts/session-audit.py), plumb-bench-extract and plumb-bench-score.
# No other playbook assumes it, so it does not rank as required alongside git and gh. To keep the
# first experience from reading as "broken" for someone without it, missing stays an info line (--).
command -v python3 >/dev/null 2>&1 \
  && note "ok" "python3" \
  || note "--" "python3 is not on PATH (needed only when you use plumb-pr-drift, plumb-session-audit, plumb-bench-extract or plumb-bench-score)"

cfg() { bash "$root/scripts/plumb-config.sh" "$1" ""; }
keys="role.judge role.bulk role.implementer pane.driver"
# Codex does not read role.implementer (docs/openai-runtime.md); a Claude-only command must not fail it.
[ "$runtime" = codex ] && keys="role.judge role.bulk pane.driver"
for k in $keys; do
  v=$(cfg "$k")
  if [ -z "$v" ]; then
    [ "$k" = role.implementer ] \
      && note "--" "$k: unset (a subagent stands in)" \
      || note "--" "$k: unset (the main session stands in)"
  else
    # The value is a command line (`codex exec`, `herdr run`); only its first word has to be on PATH.
    set -f; set -- $v; set +f
    if ! command -v "$1" >/dev/null 2>&1; then
      bad "$k = $v is configured but $1 is not on PATH"
    else
      case "$1" in
        codex|*/codex)
          # A resolving codex that is logged out fails on its first call. Only the exit status is
          # used: what login status prints may name an account.
          if bounded 30 "$1" login status >/dev/null 2>&1; then
            note "ok" "$k = $v (logged in)"
          else
            bad "$k = $v: $1 is not logged in (run: codex login --device-auth)"
          fi ;;
        *) note "ok" "$k = $v" ;;
      esac
    fi
  fi
done

st=$(cfg stack.tool)
if [ -z "$st" ]; then
  note "--" "stack.tool: unset (landing-a-stack falls back to plain gh pr merge)"
elif [ "$st" = "gh-stack" ]; then
  gh extension list 2>/dev/null | grep -q 'gh stack' \
    && note "ok" "stack.tool = gh-stack" \
    || bad "stack.tool = gh-stack but the gh extension is not installed"
else
  command -v "$st" >/dev/null 2>&1 && note "ok" "stack.tool = $st" || bad "stack.tool = $st is not on PATH"
fi

# 2b. The project contract (docs/project-contract.md): <checkout>/.plumb/project.toml.
#     Absent is normal ("none"), not a failure: most repositories have no contract. A file that
#     exists but does not parse is NG, because every consumer treats a broken contract as invalid
#     for all keys. plumb-project does the validating; this block only reports what it says.
#     A verify command is checked by its first word: with a / it is a file relative to the
#     repository top level (absolute paths as-is) and must be executable; without one it must be on
#     PATH, which is how it will be run. verify.thresholds is a path and must be a file.
echo "— contract"
contract_keys="repo.base_branch rework.required_authors rework.lookahead_days ledger.classify ledger.timezone verify.lookup verify.up verify.down verify.scenarios verify.thresholds failure.extra_codes"
cmd_resolves() { # <command line> <repository top level>
  local first path
  read -r first _ <<<"$1"
  [ -n "$first" ] || return 1
  case "$first" in
    */*)
      case "$first" in /*) path=$first ;; *) path="$2/$first" ;; esac
      [ -f "$path" ] && [ -x "$path" ] ;;
    *) command -v "$first" >/dev/null 2>&1 ;;
  esac
}
if ! cpath=$(bash "$root/scripts/plumb-path.sh" project 2>/dev/null); then
  note "--" "contract: cannot check (outside a git repository. Run doctor inside the repository you mean)"
elif [ ! -e "$cpath" ] && [ ! -L "$cpath" ]; then
  note "--" "contract: none"
elif ! command -v python3 >/dev/null 2>&1; then
  note "--" "contract: skipped, python3 is not on PATH"
else
  ctop=${cpath%/.plumb/project.toml}
  # Line 1: the outcome. Line 2: its message. Then, for a valid file, <set|unset><TAB><key><TAB><value>.
  cinfo=$(python3 "$root/scripts/plumb-project.py" --json 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    outcome, message = str(d["outcome"]), str(d["message"]).replace("\n", " ")
except (ValueError, KeyError, TypeError):
    print("broken"); print("")
    sys.exit(0)
print(outcome); print(message)
if outcome == "set":
    for key in sys.argv[1:]:
        node = d["value"]
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            print("unset\t" + key + "\t")
        else:
            text = node if isinstance(node, str) else json.dumps(node)
            print("set\t" + key + "\t" + text.replace("\n", " "))
' $contract_keys)
  {
    IFS= read -r coutcome
    IFS= read -r cmessage
    case "$coutcome" in
      unavailable) note "--" "contract: skipped, Python 3.11+ (tomllib) is unavailable" ;;
      invalid)     bad "$cmessage" ;;
      set)
        while IFS=$'\t' read -r cstate ckey cval; do
          if [ "$cstate" = unset ]; then
            note "--" "$ckey"
          else
            case "$ckey" in
              verify.lookup|verify.up|verify.down)
                if cmd_resolves "$cval" "$ctop"; then
                  note "ok" "$ckey"
                else
                  read -r cfirst _ <<<"$cval"
                  bad "$ckey: ${cfirst:-(empty)} does not resolve (not on PATH, or not an executable file under the repository top level)"
                fi ;;
              verify.thresholds)
                case "$cval" in /*) cfile=$cval ;; *) cfile="$ctop/$cval" ;; esac
                if [ -f "$cfile" ]; then
                  note "ok" "$ckey"
                else
                  bad "$ckey: ${cval:-(empty)} is not a file (a path relative to the repository top level, or absolute)"
                fi ;;
              *) note "ok" "$ckey" ;;
            esac
          fi
        done ;;
      absent) note "--" "contract: none" ;;
      *) bad "contract: plumb-project gave no usable answer; run plumb-project --json" ;;
    esac
  } <<<"$cinfo"
fi

# 2c. The work ledger (docs/ledger.md): is capture on, and does the store answer.
#     Both are opt-in, so "off" and "unset" are `--`, never a failure. A store that is set but does
#     not answer is NG; the reason is git's first line with any credentials in the URL masked
#     (plumb-ledger export --check does the masking).
echo "— ledger"
lcap=$(cfg ledger.capture)
case "$lcap" in
  on)  note "ok" "ledger.capture = on (the Stop hook records requests in the background)" ;;
  ""|off) note "--" "ledger.capture: off (set ledger.capture = on to record requests)" ;;
  *)   bad "ledger.capture = $lcap (expected on or off; capture stays off)" ;;
esac
lstore=$(cfg ledger.store)
if [ -z "$lstore" ]; then
  note "--" "ledger.store: unset (records stay local; cloud sessions are not covered)"
elif ! command -v python3 >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
  note "--" "ledger.store: cannot check (python3 and git are needed)"
else
  lcheck=$(python3 "$root/scripts/ledger.py" export --check 2>&1); lcode=$?
  if [ "$lcode" -eq 0 ]; then
    note "ok" "ledger.store answers (git ls-remote)"
  else
    bad "ledger.store: ${lcheck#NG }"
  fi
fi

# ledger.export: manual (the default) pushes only on `plumb-ledger export`; on-stop pushes each
# turn's new records from the Stop hook, which needs a store and capture on.
lexp=$(cfg ledger.export)
case "$lexp" in
  ""|manual) note "--" "ledger.export: manual (run plumb-ledger export to push; set ledger.export = on-stop to push at the end of every turn)" ;;
  on-stop)
    if [ -z "$lstore" ] || [ "$lcap" != on ]; then
      bad "ledger.export = on-stop needs ledger.store set and ledger.capture = on (nothing is pushed otherwise)"
    else
      note "ok" "ledger.export = on-stop (the Stop hook pushes each turn's new records in the background)"
    fi ;;
  *) bad "ledger.export = $lexp (expected manual or on-stop; export stays manual)" ;;
esac

# 3. There is no dependency on an outside plugin.
#    Until 2026-08-30, plumb's router forwarded "fix a bug" and "run a plan task by task" to
#    superpowers, and doctor checked whether that existed.
#    Once those 5 playbooks were rewritten in plumb's own vocabulary, **the dependency count hit
#    zero**, so the check goes with it.
#    Keeping "ok if installed, `--` if not" was an option, but **that reads as though a dependency
#    is still there.** Not checking for a dependency that does not exist is the correct state of
#    this tool (**principle-subtract-before-you-add**).
#    The other candidates (agent-routing, graph-engineering, pr-review) are already bundled or
#    forwarded instead.

# 3b. Do the 6 bundled pr-review agents exist (body text -> file)
#     If an agent the pr-review skill names disappears, the refutation stage loses what it calls
#     and nobody notices. Extraction only picks up candidates in the body form (`pr-xxx` in
#     backticks), so the short name of bin/plumb-pr-drift — `pr-drift`, which is not an agent —
#     looks identical. Measured on 2026-08-30.
#     Drop a candidate from the agent test when it exists as a bin/plumb-<name> command.
echo "— bundled agents"
while IFS= read -r name; do
  [ -z "$name" ] && continue
  [ -f "$root/bin/plumb-$name" ] && continue
  if [ -f "$root/agents/$name.md" ]; then note "ok" "agents/$name.md"
  else bad "agents/$name.md is missing (skills/pr-review/SKILL.md names it)"; fi
done < <(grep -oE '`(plumb:)?pr-[a-z-]+`' "$root/skills/pr-review/SKILL.md" | tr -d '`' | sed 's/^plumb://' | sort -u)

# 3c. Is there an agent sitting in agents/ that nobody names (file -> body text)
#     check-harness's rule 8 (the playbook and principle index) looks both ways, but agents were
#     only ever checked in 3b's one direction (does what the body names exist). One direction
#     means you can add an agent and quietly leave an orphan file nobody ever calls.
#     Any skill may name an agent (pr-review names its bundled reviewers, verify its verifier),
#     so every skills/*/SKILL.md is searched.
for f in "$root"/agents/*.md; do
  [ -f "$f" ] || continue
  n=$(basename "$f" .md)
  grep -qE "\`(plumb:)?$n\`" "$root"/skills/*/SKILL.md \
    || bad "no body text names agents/$n.md (orphan agent)"
done

# 4. Do the callers an agent names exist
#    The ~/.claude/agents/*.md read here are not bundled by plumb — they are your own. The more
#    someone uses plumb the more agents they accumulate, so it is wrong for plumb's doctor to go
#    NG over how a private agent happens to be written. Do not raise fail; just report the count
#    (the contents are useful to the owner, so the check itself stays).
if [ "$runtime" = claude ]; then
echo "— the agents on your side (your own ~/.claude/agents/. plumb does not bundle these)"
orphan=0
for f in "$CLAUDE"/agents/*.md; do
  [ -f "$f" ] || continue
  while IFS= read -r name; do
    [ -f "$CLAUDE/skills/$name/SKILL.md" ] || {
      note "--" "$(basename "$f" .md) points at a \"$name skill\" that is nowhere to be found (your own agent. Nothing to do with plumb)"
      orphan=$((orphan+1)); }
  done < <(grep -oE '`?[a-z][a-z0-9-]+`? skill' "$f" | tr -d '`' | sed 's/ skill//' | sort -u)
done
note "--" "dangling private agents: ${orphan}"
fi

# 5. Do the paths path-map claims exist
echo "— paths"
if [ "$runtime" = claude ]; then
  # Claude Code creates projects/ on its first session. Before that, "missing" means "not yet".
  [ -d "$CLAUDE/projects" ] && note "ok" "~/.claude/projects/" \
    || note "--" "~/.claude/projects/ not created yet (Claude Code makes it on the first session)"
else
  note "--" "Claude paths are not required by the Codex runtime"
fi
roots=$(git worktree list 2>/dev/null | wc -l | tr -d ' ')
note "--" "worktrees git worktree list can see: ${roots}"
for d in "$HOME/.herdr/worktrees" "$HOME/.codex/worktrees"; do
  [ -d "$d" ] && note "--" "worktree root present: ${d/#$HOME/~}"
done

# 5b. Can the artifact location be resolved
#     plumb-path.sh resolves from the git repository at cwd. Run doctor from outside a git
#     repository and the answer is "cannot check", not "broken" — putting bin/ on PATH lets you
#     call plumb-doctor from anywhere, which makes this easier to hit.
echo "— where the artifacts go"
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  note "--" "cannot check (outside a git repository. Run doctor inside the repository you mean)"
elif r=$(bash "$root/scripts/plumb-path.sh" root 2>/dev/null); then
  note "ok" "resolves (${r/#$HOME/~})"
  # Have the tracked side and the discarded side been swapped?
  # If specs is ignored, the source of truth disappears with the working tree.
  if [ -d "$r" ]; then
    # A trailing-slash pattern matches no directory that does not exist.
    # Do not report "not created yet" as "tracked".
    # run/ resolves through the main worktree (plumb-path --help), so ask plumb-path for it.
    rr=$(bash "$root/scripts/plumb-path.sh" run 2>/dev/null || printf '%s' "$r/run")
    if [ ! -d "$rr" ]; then
      note "--" "run/: not created yet (it gets created with --mkdir when you use it)"
    elif git -C "$(dirname "$rr")" check-ignore -q "$rr" 2>/dev/null; then
      note "ok" "run/ is untracked"
    else
      bad "run/ is tracked (the ledger gets mixed into the source of truth)"
    fi
    for k in specs plans; do
      if [ ! -d "$r/$k" ]; then
        note "--" "$k/: not created yet"
      elif git -C "$(dirname "$r")" check-ignore -q "$r/$k" 2>/dev/null; then
        bad "$k/ is ignored (the source of truth disappears with the working tree)"
      else
        note "ok" "$k/ is tracked"
      fi
    done
  else
    note "--" "nothing at this location yet (it gets created with --mkdir when you use it)"
    note "--" "specs/: not created yet"
    note "--" "plans/: not created yet"
  fi
else
  bad "scripts/plumb-path.sh cannot resolve"
fi

# 6. Is it loaded as a plugin
#    claude not being on PATH is "cannot check", not "broken". Confuse the two and an environment
#    that simply does not use claude as a CLI goes NG.
echo "— loading"
if [ "$runtime" = codex ]; then
  if ! command -v codex >/dev/null 2>&1; then
    note "--" "Codex plugin loading: cannot check (codex is not on PATH)"
  elif ! command -v python3 >/dev/null 2>&1; then
    note "--" "Codex plugin loading: cannot check (python3 is needed to parse JSON)"
  elif plugins=$(codex plugin list --json); then
    if printf '%s\n' "$plugins" | python3 -c 'import json, sys
try:
    data = json.load(sys.stdin)
    installed = data["installed"]
    assert isinstance(installed, list)
    present = any(p.get("name") == "plumb" and p.get("installed") is True
                  and p.get("enabled") is True for p in installed)
except (ValueError, KeyError, TypeError, AttributeError, AssertionError):
    sys.exit(2)
sys.exit(0 if present else 1)
'; then
      note "ok" "enabled Codex plugin: plumb"
    else
      bad "cannot verify enabled Codex plugin plumb; inspect codex plugin list --json"
    fi
  else
    bad "codex plugin list --json failed"
  fi
  # The profile and custom agents are optional, so drift is information, never NG.
  codex_home=${CODEX_HOME:-"$HOME/.codex"}
  if [ ! -x "$root/bin/plumb-codex-install" ]; then
    :
  elif [ ! -e "$codex_home/plumb.config.toml" ]; then
    note "--" "optional Codex profile: not installed (\$plumb:setup adds it)"
  elif bash "$root/bin/plumb-codex-install" --user --check >/dev/null 2>&1; then
    note "ok" "optional Codex profile and agents match this plugin version"
  else
    note "--" "optional Codex profile or agents differ from this plugin version (rerun \$plumb:setup)"
  fi
elif ! command -v claude >/dev/null 2>&1; then
  note "--" "is plumb in the plugin list: cannot check (claude is not on PATH)"
elif claude plugin list 2>/dev/null | grep -q 'plumb'; then
  note "ok" "plumb is in the plugin list"
else
  bad "plumb does not show up in the plugin list. Check claude plugin list in a new session"
fi

echo
if [ $fail -eq 0 ]; then echo "  → healthy"; else echo "  → needs attention (the NG lines above)"; fi
exit $fail
