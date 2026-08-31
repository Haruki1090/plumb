#!/usr/bin/env bash
# Take inventory of worktrees. Read-only. It deletes nothing.
# Deletion stays behind the human gate in playbooks/worktree-cleanup.md.
#
# Usage: scripts/worktree-audit.sh [repo-path]   (defaults to the current repository)
#
# This machine has several worktree roots (docs/path-map.md).
# git worktree list returns everything registered, whichever root it sits under.
set -u

repo="${1:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$repo" ] && { echo "run this inside a git repository, or pass the repository path" >&2; exit 1; }
cd "$repo" 2>/dev/null || { echo "cannot cd: $repo" >&2; exit 1; }
git rev-parse --show-toplevel >/dev/null 2>&1 \
  || { echo "not a git repository: $repo" >&2; exit 1; }

main_wt=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')

# Guess neither the default branch nor the remote.
# Match the repository gh is looking at against the local remotes by URL.
# Match on the name alone and something merged into a fork's main is misread as landing upstream.
base_ref=""
gh_url=$(gh repo view --json url -q .url 2>/dev/null || true)
def=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || true)
if [ -n "$gh_url" ] && [ -n "$def" ]; then
  # git@host:o/r / https://host/o/r / ssh://git@host/o/r / ssh://git@host:22/o/r
  norm() { printf '%s' "$1" \
    | sed -E 's#^ssh://[^/]+/##; s#^git@[^:]+:##; s#^https?://[^/]+/##; s#/+$##; s#\.git$##'; }
  want=$(norm "$gh_url")
  for r in $(git remote); do
    [ "$(norm "$(git remote get-url "$r" 2>/dev/null)")" = "$want" ] || continue
    if git show-ref --verify --quiet "refs/remotes/$r/$def"; then base_ref="$r/$def"
    elif git fetch --quiet "$r" "$def" 2>/dev/null; then base_ref="FETCH_HEAD"; fi
    break
  done
fi
[ -z "$base_ref" ] && echo "warn: cannot determine the default branch of the target repository. The MERGED column will read ?" >&2

prs=$(mktemp); KEEP=$(mktemp); REGEN=$(mktemp)
gh pr list --author "@me" --state all --limit 1000 \
  --json number,state,headRefName 2>/dev/null > "$prs" || echo "[]" > "$prs"
now=$(date +%s)

printf "SIZE\tAGE\tMERGED\tDIRTY\tIGNORED\tREMOTE\tPR\tLAST_CHAT\tBUCKET\tWORKTREE\n"

git worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r wt; do
  [ "$wt" = "$main_wt" ] && continue

  size=$(du -sh "$wt" 2>/dev/null | awk '{print $1}')
  head=$(git -C "$wt" rev-parse HEAD 2>/dev/null)
  head_ts=$(git -C "$wt" log -1 --format='%ct' HEAD 2>/dev/null || echo 0)
  age=$([ "$head_ts" -gt 0 ] 2>/dev/null && echo "$(( (now - head_ts) / 86400 ))d" || echo "?")

  # A squash merge never becomes an ancestor of main, so the PR's state is the real signal.
  if [ -n "$base_ref" ]; then
    git merge-base --is-ancestor "$head" "$base_ref" 2>/dev/null && merged=YES || merged=no
  else merged="?"; fi

  porcelain=$(git -C "$wt" status --porcelain 2>/dev/null)
  if [ -z "$porcelain" ]; then dirty=clean
  elif printf '%s\n' "$porcelain" | grep -qv '^??'; then
    dirty="wip:$(printf '%s\n' "$porcelain" | grep -cv '^??')"
  else dirty="scratch:$(printf '%s\n' "$porcelain" | grep -c '^??')"; fi

  # Split what is ignored into what can be rebuilt and what cannot.
  # A fully ignored directory collapses into the single line `!! build/`, so excluding it only
  # hides what is inside. **Do not hide it: count it separately and print the names.**
  keep=0; regen=0; keeplist=""; regenlist=""
  while IFS= read -r ip; do
    [ -z "$ip" ] && continue
    b=$(basename "${ip%/}")
    case "$b" in
      __pycache__|.venv|venv|node_modules|.next|.nuxt|dist|build|target|.turbo|.gradle| \
      .pytest_cache|.mypy_cache|.ruff_cache|.dart_tool|coverage|.cache|DerivedData| \
      .terraform|.hypothesis|.tox|.gradle|next-env.d.ts|*.tsbuildinfo|*.egg-info)
        regen=$((regen+1)); regenlist="$regenlist $ip" ;;
      *) keep=$((keep+1)); keeplist="$keeplist $ip" ;;
    esac
  done < <(git -C "$wt" status --porcelain --ignored 2>/dev/null | grep '^!!' | sed 's/^!! //')
  if [ "$keep" -eq 0 ] && [ "$regen" -eq 0 ]; then ign="-"
  elif [ "$keep" -eq 0 ]; then ign="regen:$regen"
  else ign="keep:$keep/regen:$regen"; fi
  [ "$keep" -gt 0 ] && printf '%s\t%s\n' "$wt" "$keeplist" >> "$KEEP"
  [ "$regen" -gt 0 ] && printf '%s\t%s\n' "$wt" "$regenlist" >> "$REGEN"

  branch=$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "")
  if [ -z "$branch" ]; then remote=detached
  elif up=$(git -C "$wt" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null); then
    [ "$(git -C "$wt" rev-parse "$up" 2>/dev/null)" = "$head" ] \
      && remote=pushed \
      || remote="ahead$(git -C "$wt" rev-list --count "$up..HEAD" 2>/dev/null)"
  else remote=no-remote; fi

  pr=$([ -n "$branch" ] && jq -r --arg b "$branch" \
    '.[] | select(.headRefName==$b) | "#\(.number)/\(.state)"' "$prs" 2>/dev/null | head -1)
  [ -z "$pr" ] && pr="-"

  # Sessions are stored under a slug per cwd (docs/path-map.md).
  # A session opened inside a worktree stays under that worktree's slug.
  # Look only at the main repository's slug and a worktree still in use is misread as "no chat".
  last="-"; last_ts=0
  for base in "$main_wt" "$wt"; do
    # The slug turns every non-alphanumeric character into - (docs/path-map.md).
    # Replace only / and you lose the sessions that live under .herdr or .claude.
    d="$HOME/.claude/projects/$(printf '%s' "$base" | sed 's#[^A-Za-z0-9]#-#g')"
    [ -d "$d" ] || continue
    if command -v rg >/dev/null 2>&1; then
      hits=$(rg -l -e "${wt}/" -e "${wt}\"" "$d" 2>/dev/null)
    else
      hits=$(grep -rl -e "${wt}/" -e "${wt}\"" "$d" 2>/dev/null)
    fi
    f=$(printf '%s\n' "$hits" | grep -v '^$' | xargs stat -f '%m %N' 2>/dev/null | sort -rn | head -1)
    [ -z "$f" ] && continue
    t=$(echo "$f" | awk '{print $1}')
    [ "$t" -gt "$last_ts" ] 2>/dev/null && { last_ts=$t; last=$(date -r "$t" '+%Y-%m-%d' 2>/dev/null); }
  done
  recent=$([ "$last_ts" -gt 0 ] 2>/dev/null && [ $(( (now - last_ts) / 86400 )) -le 4 ] && echo yes || echo no)

  # The bucket is advice, not permission (playbook step 2).
  # safe only when it is clean, merged and unused. Keep it consistent with step 4.
  case "$dirty" in wip:*) bucket=hold-wip ;; *)
    case "$pr" in *OPEN*) bucket=hold-open-pr ;; *)
      if [ "$keep" -gt 0 ]; then bucket=verify-ignored
      elif [ "$dirty" != clean ]; then bucket=verify-scratch
      elif [ "$recent" = yes ]; then bucket=verify-recent-chat
      elif [ "$regen" -gt 0 ]; then bucket=check-regen
      elif [ "$merged" = YES ] || [ "$pr" != "-" ]; then bucket=safe
      else bucket=review; fi ;;
    esac ;;
  esac

  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$size" "$age" "$merged" "$dirty" "$ign" "$remote" "$pr" "$last" "$bucket" "$wt"
done | sort -t$'\t' -k1,1 -rh

dump() {
  [ -s "$1" ] || return 0
  echo; echo "$2"
  while IFS=$'\t' read -r w items; do
    printf '  %s\n' "${w/#$HOME/~}"
    for i in $items; do printf '    %s\n' "$i"; done
  done < "$1"
}
dump "$KEEP"  "ignored and unrecoverable (from here on the judgment is a human's job):"
dump "$REGEN" "ignored and excluded as rebuildable (a collapsed directory's contents were never looked at):"

rm -f "$prs" "$KEEP" "$REGEN"
