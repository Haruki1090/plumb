#!/usr/bin/env bash
# 決定ログに1行足す（TSV）。長く走る仕事の記憶になる。
#
# 列は呼ぶ側が決める。型ごとに要る列が違うため、ここで固定しない。
#   初回:  decision-log.sh <logfile> --header <列名>...
#   以降:  decision-log.sh <logfile> <値>...
#
# 例（playbooks/hillclimb.md）:
#   decision-log.sh run.tsv --header id 仮説 変更 前 後 差 テスト 判定 備考
#   decision-log.sh run.tsv 1 "起動経路から X を外す" "defer init" 1200 940 -260 green 採用 ""
#
# ツリーの外（gitignore 下）に置くこと。取り消しを跨いで残るように。
set -euo pipefail

[ "$#" -ge 2 ] || { printf 'usage: decision-log.sh <logfile> [--header] <値>...\n' >&2; exit 1; }
logfile="$1"; shift

logdir="$(dirname "$logfile")"
[ -n "$logdir" ] && [ "$logdir" != "." ] && [ ! -d "$logdir" ] && mkdir -p "$logdir"

# タブと改行を潰して1セル1行に保つ。加えて、表計算が数式として解釈する
# 先頭文字（= + - @）を引用符で無害化する。根拠には PR タイトルや生成文が
# 入りうるので、開いた人の手元で式が走らないようにする。
clean() {
  local v
  v=$(printf '%s' "$1" | tr '\t\n\r' '   ')
  # 素の数値は素通し。-260 を引用符で潰すと、指標の列が表計算で
  # テキストになり、並べ替えもグラフも効かなくなる。
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
  [ "$#" -ge 1 ] || { printf -- '--header には列名が要ります\n' >&2; exit 1; }
  # **既存のログを上書きしない。**取り消しを跨いで残すためのファイルなので、
  # 再開時に初期化を撃ち直しただけで全履歴が消えるのは事故になる。
  if [ -f "$logfile" ]; then
    want=$({ printf 'ts\t'; row "$@"; })
    have=$(head -1 "$logfile")
    [ "$want" = "$have" ] && exit 0
    printf '%s は既にあり、見出しが違います。消したくないので何もしません。\n' "$logfile" >&2
    printf '  既存: %s\n  指定: %s\n' "$have" "$want" >&2
    exit 1
  fi
  { printf 'ts\t'; row "$@"; } > "$logfile"
  exit 0
fi

[ -f "$logfile" ] || { printf '%s に見出しがありません。先に --header で列を宣言してください\n' "$logfile" >&2; exit 1; }

# 列数が合わない行は TSV を壊す。自由列にした以上、ここで止める。
# ts は道具が付けるので、突き合わせは呼ぶ側から見た列数で言う。
want=$(( $(ncols "$logfile") - 1 )); got=$#
[ "$got" -eq "$want" ] || {
  printf '列数が合いません（見出しは %d 列 / 渡されたのは %d 列。ts は自動）: %s\n' "$want" "$got" "$logfile" >&2
  printf '  見出し: %s\n' "$(head -1 "$logfile")" >&2
  exit 1
}
{ printf '%s\t' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; row "$@"; } >> "$logfile"
