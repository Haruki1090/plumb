#!/usr/bin/env bash
# Build the three throwaway repositories the project-contract trials run in.
#   make-fixtures.sh <empty-dir> <your-github-login>
# Each repository has one landed commit and one uncommitted fix, so "open a PR for this fix" has
# something to describe. Nothing is pushed; there is no remote.
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: make-fixtures.sh <empty-dir> <github-login>" >&2; exit 2; }
out=$1 login=$2
mkdir -p "$out"
[ -z "$(ls -A "$out")" ] || { echo "make-fixtures: $out is not empty" >&2; exit 2; }

make_repo() { # <name> <contract text or empty>
  local d="$out/$1"
  mkdir -p "$d"
  git -C "$d" init -q -b main
  printf 'def total(items):\n    return sum(items[1:])\n' > "$d/cart.py"
  if [ -n "$2" ]; then mkdir -p "$d/.plumb"; printf '%s\n' "$2" > "$d/.plumb/project.toml"; fi
  git -C "$d" add -A
  git -C "$d" -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "feat: cart total (#12)"
  # The pending fix: #12 dropped the first item.
  printf 'def total(items):\n    return sum(items)\n' > "$d/cart.py"
}

make_repo set "schema = 1
[rework]
required_authors = [\"$login\"]"
make_repo absent ""
make_repo invalid "schema = 1
[verify]
up = 1"
echo "fixtures: $out/{set,absent,invalid}"
