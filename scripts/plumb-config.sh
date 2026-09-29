#!/usr/bin/env bash
# Resolve per-user configuration in one place. Per-repository configuration belongs to
# plumb-path.sh and is a separate thing. Mix them and "which target I prefer" scatters across
# every project.
#
#   plumb-config.sh <key> [default]
#
# It lives at ~/.claude/plumb/config (override with PLUMB_CONFIG). The format is plain key = value.
# A line whose first non-blank character is # is a comment. So is the rest of a line after
# whitespace followed by # (`role.judge = codex exec   # another family`). A value wrapped in
# matching double or single quotes loses the quotes and keeps everything inside them, # included.
#
#   role.judge   = <command>
#   role.bulk    = <command>
#   role.implementer = <command>   started in a pane through pane.driver (docs/role-map.md)
#   pane.driver  = <command>
#   stack.tool   = gh-stack
#   role.explorer.model     = <model>   the one key whose value is a model name; it lives here so
#                                        that no document has to carry one (docs/role-map.md)
#   role.implementer.model  = <model>   the same, for the implementer's Task fallback
#   cost.session_budget_usd = <usd>     expected spend for one session; plumb-statusline-cost
#                                        colours the running cost at 50 / 80 / 100 % of it
#   cost.jpy_per_usd        = <rate>    adds a yen figure beside the dollar one
#
# **"Not configured" is not an error.** Unset still exits 0 and returns the default.
# Exit 1 here and every caller ends up writing || true, which hides the real failures.
#
# **An empty value (`key = ` with nothing on the right) means the same as unset.** No separate
# meaning is assigned to it. The role and pane keys mean "the main session stands in" when unset,
# the model key means "inherit", and the cost keys mean "do not show it", so an empty value has
# no need to carry "explicitly disabled".
set -uo pipefail

usage() { echo "usage: plumb-config <key> [default]   (reads \${PLUMB_CONFIG:-~/.claude/plumb/config})"; }
case "${1:-}" in -h|--help) usage; exit 0 ;; esac
key="${1:-}"
def="${2:-}"
[ -n "$key" ] || { usage >&2; exit 2; }

file="${PLUMB_CONFIG:-$HOME/.claude/plumb/config}"
val=""
if [ -f "$file" ]; then
  # Match the key as a literal, not as a regular expression. Assemble it into a sed pattern and a
  # key holding [ or * gets reinterpreted as a bracket expression and matches an unrelated line.
  val=$(awk -v k="$key" '
    { line = $0; sub(/\r$/, "", line); sub(/^[[:space:]]+/, "", line) }
    index(line, k) == 1 {
      rest = substr(line, length(k) + 1)
      sub(/^[[:space:]]*/, "", rest)
      if (substr(rest, 1, 1) == "=") {
        sub(/^=[[:space:]]*/, "", rest)
        q = substr(rest, 1, 1)
        e = 0
        if (q == "\"" || q == "\047") e = index(substr(rest, 2), q)
        if (e > 0) {
          rest = substr(rest, 2, e - 1)       # quoted: keep the inside verbatim
        } else {
          if (substr(rest, 1, 1) == "#") rest = ""
          sub(/[[:space:]]+#.*$/, "", rest)   # trailing comment
          sub(/[[:space:]]+$/, "", rest)
        }
        print rest
        exit
      }
    }' "$file")
fi

printf '%s\n' "${val:-$def}"
