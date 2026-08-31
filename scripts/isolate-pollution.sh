#!/usr/bin/env bash
# Isolate the polluter, one at a time, when each case passes alone but the set fails together.
#
#   isolate-pollution.sh <command that detects the residue> <command that runs one case> <target>...
#
# The detecting command returns 0 when the residue is present (`test -e .git`, say).
# The running command is executed with one target appended to it.
#
# Examples:
#   isolate-pollution.sh 'test -e .git' 'npm test' src/a.test.ts src/b.test.ts
#   isolate-pollution.sh 'ls /tmp/lock* >/dev/null 2>&1' 'pytest -q' tests/*.py
#
# Residue that was already there makes the first case look guilty. Fail on it first and check.
set -uo pipefail

[ "$#" -ge 3 ] || {
  printf 'usage: isolate-pollution.sh <residue check> <command that runs one case> <target>...\n' >&2
  exit 2
}
check="$1"; runner="$2"; shift 2

polluted() { eval "$check" >/dev/null 2>&1; }

if polluted; then
  printf 'the residue is there before anything ran. Clear it and start again: %s\n' "$check" >&2
  exit 2
fi

total=$#; i=0
for target in "$@"; do
  i=$((i + 1))
  printf '[%d/%d] %s\n' "$i" "$total" "$target"
  eval "$runner \"\$target\"" >/dev/null 2>&1
  if polluted; then
    printf '\npolluter: %s\n' "$target"
    printf 'the check that fired: %s\n' "$check"
    exit 1
  fi
done

printf '\nran %d cases alone and no residue appeared.\n' "$total"
printf 'it may only appear under a particular order or in parallel. Suspect how you run them.\n'
exit 0
