#!/usr/bin/env bash
# plumb doctor — checks whether the environment the documents claim still exists.
# check-harness.sh looks at the inside for consistency; this looks at the seam with the outside.
# Usage: scripts/doctor.sh [plugin-root]
set -uo pipefail

root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
CLAUDE="$HOME/.claude"
fail=0
note() { printf '  %-4s %s\n' "$1" "$2"; }
bad()  { note "NG" "$1"; fail=1; }

echo "plumb doctor: $root"

# 1. Inside consistency (delegated to check-harness. Do not write it twice)
echo "— inside"
if bash "$root/scripts/check-harness.sh" "$root" >/dev/null 2>&1; then
  note "ok" "cross-cutting rules (check-harness.sh)"
else
  bad "the cross-cutting rules are failing. Run scripts/check-harness.sh directly to see what"
fi

# When selftest called us, do not call back. That is mutual recursion.
if [ -n "${PLUMB_IN_SELFTEST:-}" ]; then
  note "--" "script behaviour: skipped, called from selftest"
elif bash "$root/scripts/selftest.sh" "$root" >/dev/null 2>&1; then
  note "ok" "script behaviour (selftest.sh)"
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
# python3 is used by plumb-pr-drift (skills/pr-review/scripts/pr-drift.sh) alone.
# No other playbook assumes it, so it does not rank as required alongside git and gh. To keep the
# first experience from reading as "broken" for someone without it, missing stays an info line (--).
command -v python3 >/dev/null 2>&1 \
  && note "ok" "python3" \
  || note "--" "python3 is not on PATH (needed only when you use plumb-pr-drift)"

cfg() { bash "$root/scripts/plumb-config.sh" "$1" ""; }
for k in role.judge role.bulk pane.driver; do
  v=$(cfg "$k")
  if [ -z "$v" ]; then
    note "--" "$k: unset (the main session stands in)"
  elif command -v "$v" >/dev/null 2>&1; then
    note "ok" "$k = $v"
  else
    bad "$k = $v is configured but is not on PATH"
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

# 3b. Do the 6 bundled agents exist (body text -> file)
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
done < <(grep -oE '`pr-[a-z-]+`' "$root/skills/pr-review/SKILL.md" | tr -d '`' | sort -u)

# 3c. Is there an agent sitting in agents/ that nobody names (file -> body text)
#     check-harness's rule 8 (the playbook and principle index) looks both ways, but agents were
#     only ever checked in 3b's one direction (does what the body names exist). One direction
#     means you can add an agent and quietly leave an orphan file nobody ever calls.
for f in "$root"/agents/*.md; do
  [ -f "$f" ] || continue
  n=$(basename "$f" .md)
  grep -q "\`$n\`" "$root/skills/pr-review/SKILL.md" \
    || bad "no body text names agents/$n.md (orphan agent)"
done

# 4. Do the callers an agent names exist
#    The ~/.claude/agents/*.md read here are not bundled by plumb — they are your own. The more
#    someone uses plumb the more agents they accumulate, so it is wrong for plumb's doctor to go
#    NG over how a private agent happens to be written. Do not raise fail; just report the count
#    (the contents are useful to the owner, so the check itself stays).
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

# 5. Do the paths path-map claims exist
echo "— paths"
[ -d "$CLAUDE/projects" ] && note "ok" "~/.claude/projects/" || bad "~/.claude/projects/ is missing"
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
    if [ ! -d "$r/run" ]; then
      note "--" "run/: not created yet (it gets created with --mkdir when you use it)"
    elif git -C "$(dirname "$r")" check-ignore -q "$r/run" 2>/dev/null; then
      note "ok" "run/ is untracked"
    else
      bad "run/ is tracked (the ledger gets mixed into the source of truth)"
    fi
    for k in specs plans; do
      git -C "$(dirname "$r")" check-ignore -q "$r/$k" 2>/dev/null \
        && bad "$k/ is ignored (the source of truth disappears with the working tree)" \
        || note "ok" "$k/ is tracked"
    done
  else
    note "--" "nothing at this location yet (it gets created with --mkdir when you use it)"
  fi
else
  bad "scripts/plumb-path.sh cannot resolve"
fi

# 6. Is it loaded as a plugin
#    claude not being on PATH is "cannot check", not "broken". Confuse the two and an environment
#    that simply does not use claude as a CLI goes NG.
echo "— loading"
if ! command -v claude >/dev/null 2>&1; then
  note "--" "is plumb in the plugin list: cannot check (claude is not on PATH)"
elif claude plugin list 2>/dev/null | grep -q 'plumb'; then
  note "ok" "plumb is in the plugin list"
else
  bad "plumb does not show up in the plugin list. Check claude plugin list in a new session"
fi

echo
if [ $fail -eq 0 ]; then echo "  → healthy"; else echo "  → needs attention (the NG lines above)"; fi
exit $fail
