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
