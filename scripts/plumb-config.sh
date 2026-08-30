#!/usr/bin/env bash
# 利用者単位の設定を1箇所で解決する。リポジトリ単位の設定は plumb-path.sh の担当で、
# こちらとは別物。混ぜると「自分の実行先の好み」が案件ごとに散る。
#
#   plumb-config.sh <key> [既定値]
#
# 置き場は ~/.claude/plumb/config（PLUMB_CONFIG で差し替え可）。形式は key = value の平文。
#
#   role.judge   = <command>
#   role.bulk    = <command>
#   pane.driver  = <command>
#   stack.tool   = gh-stack
#
# **「設定していない」は異常ではない。**未設定でも exit 0 で既定値を返す。
# ここで exit 1 にすると、呼ぶ側が全部 || true を書くことになり、本物の失敗が見えなくなる。
#
# **空の値（`key = ` で右辺が無い）は「未設定」と同じ扱い。**別の意味を与えていない。
# 4 つの鍵はどれも未設定 = 本線が代行するなので、空値に「明示的に無効」を割り当てる必要が無い。
set -uo pipefail

key="${1:-}"
def="${2:-}"
[ -n "$key" ] || { echo "使い方: plumb-config.sh <key> [既定値]" >&2; exit 2; }

file="${PLUMB_CONFIG:-$HOME/.claude/plumb/config}"
val=""
if [ -f "$file" ]; then
  # 鍵は正規表現ではなくリテラルとして照合する。sed のパターンに組み立てると、
  # 鍵に [ や * が入ったときブラケット式として再解釈され、無関係な行に誤マッチする。
  val=$(awk -v k="$key" '
    { line = $0; sub(/^[[:space:]]+/, "", line) }
    index(line, k) == 1 {
      rest = substr(line, length(k) + 1)
      sub(/^[[:space:]]*/, "", rest)
      if (substr(rest, 1, 1) == "=") {
        sub(/^=[[:space:]]*/, "", rest)
        print rest
        exit
      }
    }' "$file")
  # 末尾の空白を落とす（行頭は awk が既に落としている）
  val="${val%"${val##*[![:space:]]}"}"
fi

printf '%s\n' "${val:-$def}"
