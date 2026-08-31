#!/usr/bin/env bash
# Resolve where plumb's artifacts go, in one place.
#
#   plumb-path.sh <kind> [--mkdir] [repo]
#   kind: root | spec | plan | history | run
#
# The default is <repo root>/.plumb. To change it, in this order:
#   1. the PLUMB_ROOT environment variable
#   2. root=<path> in <repo root>/.plumb/config (a relative path resolves from repo)
#   3. the default
#
# **Do not spell paths out in prose.** Do it and one of the two copies goes stale (stepped on it
# twice on 2026-08-29).
set -euo pipefail

kind="${1:-}"; shift || true
mk=0; repo=""
for a in "$@"; do
  case "$a" in --mkdir) mk=1 ;; *) repo="$a" ;; esac
done
[ -n "$repo" ] || repo=$(git rev-parse --show-toplevel 2>/dev/null || true)
[ -n "$repo" ] || { echo "run this inside a git repository, or pass a path" >&2; exit 1; }

root="${PLUMB_ROOT:-}"
if [ -z "$root" ] && [ -f "$repo/.plumb/config" ]; then
  root=$(sed -nE 's/^[[:space:]]*root[[:space:]]*=[[:space:]]*(.+)$/\1/p' "$repo/.plumb/config" | head -1)
fi
[ -z "$root" ] && root="$repo/.plumb"
case "$root" in /*) ;; ~*) root="${root/#\~/$HOME}" ;; *) root="$repo/$root" ;; esac

case "$kind" in
  root)    out="$root" ;;
  spec)    out="$root/specs" ;;
  plan)    out="$root/plans" ;;
  history) out="$root/plans/history" ;;
  run)     out="$root/run" ;;
  *) echo "usage: plumb-path.sh root|spec|plan|history|run [--mkdir] [repo]" >&2; exit 2 ;;
esac

if [ "$mk" -eq 1 ]; then
  mkdir -p "$out"
  # run/ alone is not tracked. The ledger and the decision log are traces of the work, not the
  # source of truth. specs and plans are tracked — a source of truth that disappears with the
  # working tree is not a source of truth.
  [ -f "$root/.gitignore" ] || printf 'run/\n' > "$root/.gitignore"
fi
printf '%s\n' "$out"
