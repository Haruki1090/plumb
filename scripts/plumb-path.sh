#!/usr/bin/env bash
# plumb の成果物の置き場を1箇所で解決する。
#
#   plumb-path.sh <kind> [--mkdir] [repo]
#   kind: root | spec | plan | history | run
#
# 既定は <リポジトリ直下>/.plumb 。変えたいときの優先順位:
#   1. 環境変数 PLUMB_ROOT
#   2. <リポジトリ直下>/.plumb/config の root=<パス>（相対なら repo 起点）
#   3. 既定
#
# **散文にパスを書かない。**書くと片方だけ古くなる（2026-08-29 に 2 回踏んだ）。
set -euo pipefail

kind="${1:-}"; shift || true
mk=0; repo=""
for a in "$@"; do
  case "$a" in --mkdir) mk=1 ;; *) repo="$a" ;; esac
done
[ -n "$repo" ] || repo=$(git rev-parse --show-toplevel 2>/dev/null || true)
[ -n "$repo" ] || { echo "git リポジトリの中で実行するか、パスを渡してください" >&2; exit 1; }

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
  *) echo "使い方: plumb-path.sh root|spec|plan|history|run [--mkdir] [repo]" >&2; exit 2 ;;
esac

if [ "$mk" -eq 1 ]; then
  mkdir -p "$out"
  # run/ だけは追跡しない。台帳と決定ログは作業の跡であって正本ではない。
  # specs と plans は追跡する——working tree と一緒に消える正本は正本ではない。
  [ -f "$root/.gitignore" ] || printf 'run/\n' > "$root/.gitignore"
fi
printf '%s\n' "$out"
