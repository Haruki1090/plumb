#!/usr/bin/env bash
# Append one row to a decision log (TSV). It is the memory of a long-running job.
#
# The caller decides the columns. Every playbook needs different ones, so nothing is fixed here.
#   first time:  decision-log.sh <logfile> --header <column name>...
#   after that:  decision-log.sh <logfile> <value>...
#
# Example (playbooks/hillclimb.md):
#   decision-log.sh run.tsv --header id hypothesis change before after delta test verdict notes
#   decision-log.sh run.tsv 1 "drop X from the startup path" "defer init" 1200 940 -260 green adopted ""
#
# Mark where a run begins, so several runs can share one log (needs a header with 2+ columns):
#   decision-log.sh <logfile> --start "<label>"
#   One row: ts, the literal `start` in the first caller column, the label in the second, the rest empty.
#
# Check the evidence a run wrote down (writes nothing, calls no model):
#   decision-log.sh <logfile> --audit [--repo DIR] [--all] [--no-remote] [--json]
#   Looks at the rows after the last `start` row (the whole file with none, or with --all). Every commit,
#   pull request and file named in a cell is resolved by machine: git cat-file, gh pr view, the file system.
#   Each reference is resolved, missing or unchecked (no gh, no network, --no-remote, not a repository).
#   Prints one line per reference, a summary and the count of rows that name nothing. Exit 1 when any
#   reference is missing. --repo defaults to the git top level of the current directory.
#
# Keep it outside the tree (under gitignore), so it survives a revert.
set -euo pipefail

case "${1:-}" in
  -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
esac
[ "$#" -ge 2 ] || { printf 'usage: decision-log.sh <logfile> [--header] <value>...\n' >&2; exit 1; }
logfile="$1"; shift

# The audit only reads. Hand over before the directory is created below.
if [ "${1:-}" = "--audit" ]; then
  shift
  exec python3 -B "$(cd -P "$(dirname "$0")" && pwd)/decision-log-audit.py" "$logfile" "$@"
fi

logdir="$(dirname "$logfile")"
[ -n "$logdir" ] && [ "$logdir" != "." ] && [ ! -d "$logdir" ] && mkdir -p "$logdir"

# Flatten tabs and newlines to keep one cell on one line. On top of that, neutralise the leading
# characters a spreadsheet reads as a formula (= + - @) by quoting them. The evidence column can
# hold a PR title or generated prose, so no formula should run when someone opens the file.
clean() {
  local v
  v=$(printf '%s' "$1" | tr '\t\n\r' '   ')
  # Let a bare number through. Quoting -260 turns the metric column into text in a spreadsheet,
  # and sorting and charting both stop working.
  case "$v" in
    ''|*[!0-9.+-]*|*[!0-9]*[+-]*) ;;
    *) printf '%s' "$v"; return ;;
  esac
  case "$v" in
    =*|+*|-*|@*) printf "'%s" "$v" ;;
    *) printf '%s' "$v" ;;
  esac
}
row() {
  local out="" first=1
  for v in "$@"; do
    [ $first -eq 1 ] && first=0 || out="$out	"
    out="$out$(clean "$v")"
  done
  printf '%s\n' "$out"
}

ncols() { head -1 "$1" | awk -F'\t' '{print NF}'; }

if [ "${1:-}" = "--header" ]; then
  shift
  [ "$#" -ge 1 ] || { printf -- '--header needs column names\n' >&2; exit 1; }
  # **Never overwrite an existing log.** This file exists to survive a revert, so wiping the whole
  # history because someone fired the initialisation again on resume would be an accident.
  if [ -f "$logfile" ]; then
    want=$({ printf 'ts\t'; row "$@"; })
    have=$(head -1 "$logfile")
    [ "$want" = "$have" ] && exit 0
    printf '%s already exists with a different header. Doing nothing rather than destroying it.\n' "$logfile" >&2
    printf '  existing: %s\n  given:    %s\n' "$have" "$want" >&2
    exit 1
  fi
  { printf 'ts\t'; row "$@"; } > "$logfile"
  exit 0
fi

[ -f "$logfile" ] || { printf '%s has no header. Declare the columns with --header first\n' "$logfile" >&2; exit 1; }

if [ "${1:-}" = "--start" ]; then
  [ "$#" -eq 2 ] || { printf -- '--start takes exactly one label\n' >&2; exit 1; }
  # ts + two caller columns at least: the literal `start` and the label.
  cols=$(ncols "$logfile")
  [ "$cols" -ge 3 ] || {
    printf '%s has %d caller column(s). --start needs at least 2 (it writes `start` and the label)\n' "$logfile" "$(( cols - 1 ))" >&2
    exit 1
  }
  args=(start "$2")
  i=2; while [ "$i" -lt $(( cols - 1 )) ]; do args+=(""); i=$(( i + 1 )); done
  { printf '%s\t' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; row "${args[@]}"; } >> "$logfile"
  exit 0
fi

# A row with the wrong number of columns breaks the TSV. Since the columns are free-form, stop here.
# The tool adds ts itself, so state the count as the caller sees it.
want=$(( $(ncols "$logfile") - 1 )); got=$#
[ "$got" -eq "$want" ] || {
  printf 'column count does not match (header has %d / %d were given; ts is automatic): %s\n' "$want" "$got" "$logfile" >&2
  printf '  header: %s\n' "$(head -1 "$logfile")" >&2
  exit 1
}
{ printf '%s\t' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; row "$@"; } >> "$logfile"
