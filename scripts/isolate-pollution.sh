#!/usr/bin/env bash
# 「単独では通るのに、まとめると落ちる」ときの汚染源を一件ずつ切り分ける。
#
#   isolate-pollution.sh <残骸の判定コマンド> <一件を走らせるコマンド> <対象>...
#
# 判定コマンドは、残骸が在るとき 0 を返すこと（`test -e .git` など）。
# 走らせるコマンドは末尾に対象を1つ足して実行される。
#
# 例:
#   isolate-pollution.sh 'test -e .git' 'npm test' src/a.test.ts src/b.test.ts
#   isolate-pollution.sh 'ls /tmp/lock* >/dev/null 2>&1' 'pytest -q' tests/*.py
#
# 走らせる前から残骸が在ると、最初の一件が犯人に見える。先に落として確かめる。
set -uo pipefail

[ "$#" -ge 3 ] || {
  printf 'usage: isolate-pollution.sh <残骸の判定> <一件を走らせるコマンド> <対象>...\n' >&2
  exit 2
}
check="$1"; runner="$2"; shift 2

polluted() { eval "$check" >/dev/null 2>&1; }

if polluted; then
  printf '残骸が最初から在る。消してから走らせ直す: %s\n' "$check" >&2
  exit 2
fi

total=$#; i=0
for target in "$@"; do
  i=$((i + 1))
  printf '[%d/%d] %s\n' "$i" "$total" "$target"
  eval "$runner \"\$target\"" >/dev/null 2>&1
  if polluted; then
    printf '\n汚染源: %s\n' "$target"
    printf '判定に当たった: %s\n' "$check"
    exit 1
  fi
done

printf '\n%d 件を単独で走らせたが、残骸は出なかった。\n' "$total"
printf '順序か並列でだけ出る可能性がある。走らせ方を疑う。\n'
exit 0
