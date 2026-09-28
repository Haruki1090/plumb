#!/usr/bin/env bash
# Resolve where plumb's artifacts go, in one place.
#
#   plumb-path.sh <kind> [--mkdir] [repo]
#   kind: root | spec | plan | history | run
#
# The default is <repo root>/.plumb. To change it, in this order:
#   1. the PLUMB_ROOT environment variable
#   2. root = <path> in <repo root>/.plumb/config (a relative path resolves from repo; the value
#      follows plumb-config's format: surrounding quotes and a trailing ` # comment` are dropped)
#   3. the default
#
# spec, plan and history are tracked, so they belong to the checkout you are in. run/ is not
# tracked, so a linked worktree resolves it through the main worktree (git's common dir): a ledger
# written from a worktree survives `git worktree remove`. Outside a git repository, only an
# absolute PLUMB_ROOT gives an answer.
#
# **Do not spell paths out in prose.** Do it and one of the two copies goes stale (stepped on it
# twice on 2026-08-29).
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: plumb-path root|spec|plan|history|run [--mkdir] [repo]

  root     <repo>/.plumb, or PLUMB_ROOT, or root = <path> in <repo>/.plumb/config
  spec     approved designs (tracked, per checkout)
  plan     plans being executed (tracked, per checkout)
  history  finished plans (tracked, per checkout)
  run      ledgers and decision logs (untracked; from a linked worktree it resolves
           through the main worktree, so it outlives the worktree)
  --mkdir  create the directory, and a .gitignore holding run/ beside it

Outside a git repository, pass a repo path or set PLUMB_ROOT to an absolute path.
USAGE
}

kind="${1:-}"; shift || true
case "$kind" in -h|--help) usage; exit 0 ;; esac
mk=0; repo=""
for a in "$@"; do
  case "$a" in --mkdir) mk=1 ;; -h|--help) usage; exit 0 ;; *) repo="$a" ;; esac
done
case "$kind" in root|spec|plan|history|run) ;; *) usage >&2; exit 2 ;; esac

[ -n "$repo" ] || repo=$(git rev-parse --show-toplevel 2>/dev/null || true)

# run/ outlives a linked worktree: resolve it from the main worktree. A bare repository or a
# submodule has no main working tree in the usual place, so it keeps the checkout it was given.
if [ "$kind" = run ] && [ -n "$repo" ]; then
  common=$(git -C "$repo" rev-parse --git-common-dir 2>/dev/null || true)
  if [ -n "$common" ]; then
    case "$common" in /*) ;; *) common="$repo/$common" ;; esac
    if [ "$(basename "$common")" = .git ] && [ -d "$common" ]; then
      repo=$(cd "$(dirname "$common")" && pwd -P)
    fi
  fi
fi

# Read root = <value> the way plumb-config reads a value: quotes kept verbatim inside, a trailing
# whitespace-then-# comment dropped.
config_root() {
  awk '
    { line = $0; sub(/\r$/, "", line) }
    line ~ /^[[:space:]]*root[[:space:]]*=/ {
      sub(/^[[:space:]]*root[[:space:]]*=[[:space:]]*/, "", line)
      q = substr(line, 1, 1); e = 0
      if (q == "\"" || q == "\047") e = index(substr(line, 2), q)
      if (e > 0) { line = substr(line, 2, e - 1) }
      else {
        if (substr(line, 1, 1) == "#") line = ""
        sub(/[[:space:]]+#.*$/, "", line); sub(/[[:space:]]+$/, "", line)
      }
      print line
      exit
    }' "$1"
}

root="${PLUMB_ROOT:-}"
if [ -z "$repo" ]; then
  case "$root" in
    /*|~*) ;;
    *) echo "run this inside a git repository, pass a repo path, or set PLUMB_ROOT to an absolute path" >&2; exit 1 ;;
  esac
fi
if [ -z "$root" ] && [ -f "$repo/.plumb/config" ]; then
  root=$(config_root "$repo/.plumb/config")
fi
[ -z "$root" ] && root="$repo/.plumb"
case "$root" in /*) ;; ~*) root="${root/#\~/$HOME}" ;; *) root="$repo/$root" ;; esac

case "$kind" in
  root)    out="$root" ;;
  spec)    out="$root/specs" ;;
  plan)    out="$root/plans" ;;
  history) out="$root/plans/history" ;;
  run)     out="$root/run" ;;
esac

if [ "$mk" -eq 1 ]; then
  mkdir -p "$out"
  # run/ alone is not tracked. The ledger and the decision log are traces of the work, not the
  # source of truth. specs and plans are tracked — a source of truth that disappears with the
  # working tree is not a source of truth.
  [ -f "$root/.gitignore" ] || printf 'run/\n' > "$root/.gitignore"
fi
printf '%s\n' "$out"
