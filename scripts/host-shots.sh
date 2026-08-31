#!/usr/bin/env bash
# Host the screenshots you paste into a PR without dirtying the repository's history.
#
#   host-shots.sh --branch <ref> [--pair BEFORE AFTER [LABEL]]... [--file PATH [LABEL]]...
#
# What it does:
#   1. --pair puts before and after side by side and burns a label along the top of one image
#   2. pushes every image as an **orphan commit with no parent**
#   3. prints Markdown to stdout that you paste straight into the PR body
#
# **It does not take the screenshots.** How you capture a screen differs every time. This picks
# up after the capture.
#
# Why orphan: no image enters develop or main's history, and CI does not run.
# Why github.com/<owner>/<repo>/raw/: on a private repository raw.githubusercontent.com carries no
# session cookie and returns 404. The github.com origin renders.
#
# The options that matter:
#   --branch <ref>    branch to park them on (e.g. assets/sidebar-20260830). Required
#   --pair A B [L]    compose the two side by side. L is the Markdown alt (default: composed name)
#   --file P [L]      park it as is, uncomposed
#   --repo <dir>      repository to work on (default: the toplevel of cwd)
#   --message <msg>   commit message
#   --compress        shrink a PNG over 1MB by reducing colors (**same treatment on before and after**)
#   --force           overwrite a branch of that name if it already exists
#   --dry-run         compose and print the Markdown, push nothing
set -euo pipefail

die() { printf 'host-shots: %s\n' "$*" >&2; exit 1; }

BRANCH=""; REPO=""; MSG=""; DRY=0; FORCE=0; COMPRESS=0
PAIR_B=(); PAIR_A=(); PAIR_L=(); FILE_P=(); FILE_L=()

while [ $# -gt 0 ]; do
  case "$1" in
    --branch)   BRANCH="${2:-}"; shift 2 ;;
    --repo)     REPO="${2:-}"; shift 2 ;;
    --message)  MSG="${2:-}"; shift 2 ;;
    --compress) COMPRESS=1; shift ;;
    --force)    FORCE=1; shift ;;
    --dry-run)  DRY=1; shift ;;
    --pair)
      [ $# -ge 3 ] || die "--pair takes BEFORE AFTER [LABEL]"
      PAIR_B+=("$2"); PAIR_A+=("$3"); shift 3
      if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then PAIR_L+=("$1"); shift; else PAIR_L+=(""); fi
      ;;
    --file)
      [ $# -ge 2 ] || die "--file takes PATH [LABEL]"
      FILE_P+=("$2"); shift 2
      if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then FILE_L+=("$1"); shift; else FILE_L+=(""); fi
      ;;
    # Print the header block and stop at the first line that is not a comment. A hard-coded
    # line range goes stale the moment an option is added, which is how this came to spill
    # `set -euo pipefail` and die() into --help.
    -h|--help) awk 'NR>1 && /^#/ {print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$BRANCH" ] || die "--branch is required"
case "$BRANCH" in assets/*) ;; *) printf 'host-shots: warning — name the branch under assets/ (%s)\n' "$BRANCH" >&2 ;; esac

[ -n "$REPO" ] || REPO=$(git rev-parse --show-toplevel 2>/dev/null) || die "run this inside a git repository"
REPO=$(cd "$REPO" && pwd)

ORIGIN=$(git -C "$REPO" remote get-url origin 2>/dev/null) || die "there is no origin"
# Accept both git@github.com:owner/repo.git and https://github.com/owner/repo.git
case "$ORIGIN" in
  git@github.com:*|https://github.com/*|ssh://git@github.com/*) ;;
  *) die "origin is not GitHub. The /raw/ URL cannot be built: $ORIGIN" ;;
esac
SLUG=$(printf '%s' "$ORIGIN" \
  | sed -e 's#^git@github.com:##' -e 's#^ssh://git@github.com/##' -e 's#^https://github.com/##' -e 's#\.git$##')
case "$SLUG" in */*/*|*/) die "cannot pull owner/repo out of origin: $ORIGIN" ;; */*) ;; *) die "cannot pull owner/repo out of origin: $ORIGIN" ;; esac

MAGICK=""
if command -v magick >/dev/null 2>&1; then MAGICK=magick
elif command -v convert >/dev/null 2>&1; then MAGICK=convert; fi

# Without an explicit -font, ImageMagick dies on macOS with
# "unable to read font ''". It does not resolve a default font.
FONTOPT=()
for f in /System/Library/Fonts/Supplemental/Arial.ttf \
         /System/Library/Fonts/Helvetica.ttc \
         /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf; do
  [ -f "$f" ] && { FONTOPT=(-font "$f"); break; }
done
[ ${#FONTOPT[@]} -gt 0 ] || printf 'host-shots: warning — no font found. Burning in the label may fail\n' >&2

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# What gets parked: display name paired with the real path
NAMES=(); PATHS=(); ALTS=()

add() { NAMES+=("$1"); PATHS+=("$2"); ALTS+=("$3"); }

# ---- compose ----------------------------------------------------------
i=0
while [ $i -lt ${#PAIR_B[@]} ]; do
  b="${PAIR_B[$i]}"; a="${PAIR_A[$i]}"; l="${PAIR_L[$i]}"
  [ -f "$b" ] || die "not found: $b"
  [ -f "$a" ] || die "not found: $a"
  [ -n "$MAGICK" ] || die "no ImageMagick. --pair is unavailable (brew install imagemagick)"

  stem=$(basename "$b"); stem="${stem%.*}"
  stem="${stem#before-}"; stem="${stem#before_}"
  out="$WORK/compare-$stem.png"

  for v in before after; do
    src="$b"; [ "$v" = after ] && src="$a"
    "$MAGICK" "$src" -resize x900 \
      -background '#111827' -fill white ${FONTOPT[@]+"${FONTOPT[@]}"} -pointsize 26 \
      -gravity north -splice 0x44 -annotate +0+10 "$v" "$WORK/lbl-$v-$stem.png" \
      || die "failed to burn in the label: $src"
  done
  # +smush leaves a gap between them as it joins them horizontally. The 16px seam is what makes
  # the eye read them as two separate images.
  "$MAGICK" "$WORK/lbl-before-$stem.png" "$WORK/lbl-after-$stem.png" \
    -background '#374151' +smush 16 "$out" || die "compose failed: $stem"

  add "compare-$stem.png" "$out" "${l:-$stem comparison}"
  i=$((i + 1))
done

# ---- parked as is -----------------------------------------------------
i=0
while [ $i -lt ${#FILE_P[@]} ]; do
  p="${FILE_P[$i]}"; l="${FILE_L[$i]}"
  [ -f "$p" ] || die "not found: $p"
  n=$(basename "$p")
  add "$n" "$(cd "$(dirname "$p")" && pwd)/$n" "${l:-${n%.*}}"
  i=$((i + 1))
done

[ ${#NAMES[@]} -gt 0 ] || die "nothing to park. Pass --pair or --file"

# ---- size -------------------------------------------------------------
i=0
while [ $i -lt ${#NAMES[@]} ]; do
  sz=$(wc -c < "${PATHS[$i]}" | tr -d ' ')
  if [ "$sz" -gt 1000000 ]; then
    if [ "$COMPRESS" = 1 ] && [ -n "$MAGICK" ]; then
      c="$WORK/small-${NAMES[$i]}"
      "$MAGICK" "${PATHS[$i]}" -resize 1800x -colors 200 "PNG8:$c" && PATHS[$i]="$c"
      printf 'host-shots: shrank %s: %s → %s bytes\n' "${NAMES[$i]}" "$sz" "$(wc -c < "$c" | tr -d ' ')" >&2
    else
      printf 'host-shots: warning — %s is %s bytes. Consider --compress\n' "${NAMES[$i]}" "$sz" >&2
    fi
  fi
  i=$((i + 1))
done

# ---- Markdown ---------------------------------------------------------
emit_md() {
  local i=0
  while [ $i -lt ${#NAMES[@]} ]; do
    printf '![%s](https://github.com/%s/raw/%s/%s)\n\n' \
      "${ALTS[$i]}" "$SLUG" "$BRANCH" "${NAMES[$i]}"
    i=$((i + 1))
  done
}

if [ "$DRY" = 1 ]; then
  printf 'host-shots: --dry-run (nothing is pushed). The composed files are in %s\n' "$WORK" >&2
  # The trap deletes them, so copy here if you want to look
  cp "$WORK"/compare-*.png . 2>/dev/null && printf 'host-shots: put compare-*.png in cwd\n' >&2
  emit_md
  exit 0
fi

# ---- orphan commit ----------------------------------------------------
if [ "$FORCE" != 1 ] && git -C "$REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  die "$BRANCH already exists locally. Pick another name or pass --force"
fi

# hash-object -w writes into the repository's object DB. **Always point at the repository with -C.**
ENTRIES=""
i=0
while [ $i -lt ${#NAMES[@]} ]; do
  h=$(git -C "$REPO" hash-object -w "${PATHS[$i]}") || die "hash-object failed: ${PATHS[$i]}"
  ENTRIES="${ENTRIES}100644 blob ${h}	${NAMES[$i]}
"
  i=$((i + 1))
done

TREE=$(printf '%s' "$ENTRIES" | git -C "$REPO" mktree) || die "mktree failed"
# No -p = an orphan commit with no parent. It connects to no existing history.
COMMIT=$(printf '%s\n' "${MSG:-chore(assets): screenshots for the PR}" \
  | git -C "$REPO" commit-tree "$TREE") || die "commit-tree failed"
git -C "$REPO" update-ref "refs/heads/$BRANCH" "$COMMIT"
if [ "$FORCE" = 1 ]; then
  git -C "$REPO" push -q --force origin "refs/heads/$BRANCH"
else
  git -C "$REPO" push -q origin "refs/heads/$BRANCH"
fi

printf 'host-shots: pushed %s (%s)\n' "$BRANCH" "$COMMIT" >&2
git -C "$REPO" ls-tree --name-only "refs/heads/$BRANCH" >&2
printf '\n' >&2

emit_md
