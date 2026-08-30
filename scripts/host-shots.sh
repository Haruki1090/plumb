#!/usr/bin/env bash
# PR に貼る画面を、リポジトリの履歴を汚さずにホストする。
#
#   host-shots.sh --branch <ref> [--pair BEFORE AFTER [LABEL]]... [--file PATH [LABEL]]...
#
# やること:
#   1. --pair は before/after を左右に並べ、上端にラベルを焼いた 1 枚に合成する
#   2. 全部の画像を **親を持たない orphan コミット**にして push する
#   3. PR 本文へそのまま貼れる Markdown を stdout に出す
#
# **撮影はしない。**撮るのは画面ごとに違う。ここは撮った後だけを引き受ける。
#
# なぜ orphan か: develop / main の履歴に画像が入らず、CI も走らない。
# なぜ github.com/<owner>/<repo>/raw/ か: private リポでは raw.githubusercontent.com は
# セッション Cookie が乗らず 404 になる。github.com オリジンなら表示される。
#
# 主なオプション:
#   --branch <ref>    置き場のブランチ名（例 assets/sidebar-20260830）。必須
#   --pair A B [L]    左右合成して 1 枚にする。L は Markdown の alt（既定は合成名）
#   --file P [L]      合成せずそのまま置く
#   --repo <dir>      対象リポジトリ（既定: cwd のトップレベル）
#   --message <msg>   コミットメッセージ
#   --compress        1MB 超の PNG を減色して縮める（**before/after に同じ処理を掛ける**）
#   --force           同名ブランチが既にあっても上書きする
#   --dry-run         合成と Markdown だけ出して push しない
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
      [ $# -ge 3 ] || die "--pair は BEFORE AFTER [LABEL] を取る"
      PAIR_B+=("$2"); PAIR_A+=("$3"); shift 3
      if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then PAIR_L+=("$1"); shift; else PAIR_L+=(""); fi
      ;;
    --file)
      [ $# -ge 2 ] || die "--file は PATH [LABEL] を取る"
      FILE_P+=("$2"); shift 2
      if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then FILE_L+=("$1"); shift; else FILE_L+=(""); fi
      ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done

[ -n "$BRANCH" ] || die "--branch は必須"
case "$BRANCH" in assets/*) ;; *) printf 'host-shots: 警告 — ブランチ名は assets/ 始まりを勧める（%s）\n' "$BRANCH" >&2 ;; esac

[ -n "$REPO" ] || REPO=$(git rev-parse --show-toplevel 2>/dev/null) || die "git リポジトリの中で実行する"
REPO=$(cd "$REPO" && pwd)

ORIGIN=$(git -C "$REPO" remote get-url origin 2>/dev/null) || die "origin が無い"
# git@github.com:owner/repo.git / https://github.com/owner/repo.git のどちらも受ける
case "$ORIGIN" in
  git@github.com:*|https://github.com/*|ssh://git@github.com/*) ;;
  *) die "origin が GitHub ではない。/raw/ 経路の URL は作れない: $ORIGIN" ;;
esac
SLUG=$(printf '%s' "$ORIGIN" \
  | sed -e 's#^git@github.com:##' -e 's#^ssh://git@github.com/##' -e 's#^https://github.com/##' -e 's#\.git$##')
case "$SLUG" in */*/*|*/) die "origin から owner/repo を取り出せない: $ORIGIN" ;; */*) ;; *) die "origin から owner/repo を取り出せない: $ORIGIN" ;; esac

MAGICK=""
if command -v magick >/dev/null 2>&1; then MAGICK=magick
elif command -v convert >/dev/null 2>&1; then MAGICK=convert; fi

# ImageMagick は -font を明示しないと macOS で
# "unable to read font ''" で落ちる。既定フォントを解決しない。
FONTOPT=()
for f in /System/Library/Fonts/Supplemental/Arial.ttf \
         /System/Library/Fonts/Helvetica.ttc \
         /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf; do
  [ -f "$f" ] && { FONTOPT=(-font "$f"); break; }
done
[ ${#FONTOPT[@]} -gt 0 ] || printf 'host-shots: 警告 — フォントが見つからない。ラベルの焼き込みが落ちるかもしれない\n' >&2

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# 置く物: 表示名と実体パスの対
NAMES=(); PATHS=(); ALTS=()

add() { NAMES+=("$1"); PATHS+=("$2"); ALTS+=("$3"); }

# ---- 合成 -------------------------------------------------------------
i=0
while [ $i -lt ${#PAIR_B[@]} ]; do
  b="${PAIR_B[$i]}"; a="${PAIR_A[$i]}"; l="${PAIR_L[$i]}"
  [ -f "$b" ] || die "見つからない: $b"
  [ -f "$a" ] || die "見つからない: $a"
  [ -n "$MAGICK" ] || die "ImageMagick が無い。--pair は使えない（brew install imagemagick）"

  stem=$(basename "$b"); stem="${stem%.*}"
  stem="${stem#before-}"; stem="${stem#before_}"
  out="$WORK/compare-$stem.png"

  for v in before after; do
    src="$b"; [ "$v" = after ] && src="$a"
    "$MAGICK" "$src" -resize x900 \
      -background '#111827' -fill white ${FONTOPT[@]+"${FONTOPT[@]}"} -pointsize 26 \
      -gravity north -splice 0x44 -annotate +0+10 "$v" "$WORK/lbl-$v-$stem.png" \
      || die "ラベル焼き込みに失敗: $src"
  done
  # +smush は間に隙間を入れて横に並べる。境界の 16px が「別の画像」と読ませる。
  "$MAGICK" "$WORK/lbl-before-$stem.png" "$WORK/lbl-after-$stem.png" \
    -background '#374151' +smush 16 "$out" || die "合成に失敗: $stem"

  add "compare-$stem.png" "$out" "${l:-$stem の比較}"
  i=$((i + 1))
done

# ---- そのまま置く物 ---------------------------------------------------
i=0
while [ $i -lt ${#FILE_P[@]} ]; do
  p="${FILE_P[$i]}"; l="${FILE_L[$i]}"
  [ -f "$p" ] || die "見つからない: $p"
  n=$(basename "$p")
  add "$n" "$(cd "$(dirname "$p")" && pwd)/$n" "${l:-${n%.*}}"
  i=$((i + 1))
done

[ ${#NAMES[@]} -gt 0 ] || die "置く物が無い。--pair か --file を渡す"

# ---- 大きさ -----------------------------------------------------------
i=0
while [ $i -lt ${#NAMES[@]} ]; do
  sz=$(wc -c < "${PATHS[$i]}" | tr -d ' ')
  if [ "$sz" -gt 1000000 ]; then
    if [ "$COMPRESS" = 1 ] && [ -n "$MAGICK" ]; then
      c="$WORK/small-${NAMES[$i]}"
      "$MAGICK" "${PATHS[$i]}" -resize 1800x -colors 200 "PNG8:$c" && PATHS[$i]="$c"
      printf 'host-shots: 縮めた %s: %s → %s bytes\n' "${NAMES[$i]}" "$sz" "$(wc -c < "$c" | tr -d ' ')" >&2
    else
      printf 'host-shots: 警告 — %s は %s bytes。--compress を検討する\n' "${NAMES[$i]}" "$sz" >&2
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
  printf 'host-shots: --dry-run（push しない）。合成物は %s\n' "$WORK" >&2
  # trap で消えるので、確認したいならここでコピーしておく
  cp "$WORK"/compare-*.png . 2>/dev/null && printf 'host-shots: compare-*.png を cwd に置いた\n' >&2
  emit_md
  exit 0
fi

# ---- orphan コミット --------------------------------------------------
if [ "$FORCE" != 1 ] && git -C "$REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  die "ローカルに $BRANCH が既にある。別名にするか --force"
fi

# hash-object -w はリポジトリのオブジェクト DB に書く。**必ず -C でリポジトリを指す。**
ENTRIES=""
i=0
while [ $i -lt ${#NAMES[@]} ]; do
  h=$(git -C "$REPO" hash-object -w "${PATHS[$i]}") || die "hash-object 失敗: ${PATHS[$i]}"
  ENTRIES="${ENTRIES}100644 blob ${h}	${NAMES[$i]}
"
  i=$((i + 1))
done

TREE=$(printf '%s' "$ENTRIES" | git -C "$REPO" mktree) || die "mktree 失敗"
# -p を付けない = 親の無い orphan コミット。既存の履歴と一切つながらない。
COMMIT=$(printf '%s\n' "${MSG:-chore(assets): PR 用のスクリーンショット}" \
  | git -C "$REPO" commit-tree "$TREE") || die "commit-tree 失敗"
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
