#!/usr/bin/env bash
# plumb のスクリプトの振る舞いを固定する。check-harness が「文書の整合」を見るのに対し、
# こちらは「スクリプトが何を返すか」を見る。doctor の「内側」から呼ばれる。
set -uo pipefail
root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
fail=0
ok()  { printf '  %-4s %s\n' "ok" "$1"; }
ng()  { printf '  %-4s %s\n' "NG" "$1"; fail=1; }
eq()  { [ "$2" = "$3" ] && ok "$1" || ng "$1（期待 [$3] / 実測 [$2]）"; }

echo "plumb selftest: $root"

cfg=$(mktemp)
sandbox_root=$(mktemp -d)
trap 'rm -f "$cfg"; rm -rf "$sandbox_root"' EXIT
printf 'role.judge = codex\nrole.bulk   =  cursor-agent  \n' > "$cfg"

# 設定がある鍵は値を返す
eq "設定した鍵" "$(PLUMB_CONFIG="$cfg" bash "$root/scripts/plumb-config.sh" role.judge)" "codex"
# 値の前後の空白は落とす
eq "空白を落とす" "$(PLUMB_CONFIG="$cfg" bash "$root/scripts/plumb-config.sh" role.bulk)" "cursor-agent"
# 未設定の鍵は既定値
eq "未設定は既定値" "$(PLUMB_CONFIG="$cfg" bash "$root/scripts/plumb-config.sh" pane.driver none)" "none"
# 設定ファイルが無くても既定値を返し、異常終了しない
eq "ファイル無しでも既定値" "$(PLUMB_CONFIG=/nonexistent bash "$root/scripts/plumb-config.sh" role.judge none)" "none"
PLUMB_CONFIG=/nonexistent bash "$root/scripts/plumb-config.sh" role.judge >/dev/null 2>&1 \
  && ok "ファイル無しでも exit 0" || ng "ファイル無しで異常終了した"
# 鍵に正規表現メタ文字が入っても、別の行に誤マッチしない
eq "メタ文字の鍵は誤マッチしない" "$(PLUMB_CONFIG="$cfg" bash "$root/scripts/plumb-config.sh" 'role.[judge' DEFAULT)" "DEFAULT"

# isolate-pollution: 「単独では通るのに、まとめると落ちる」の切り分け。
# 犯人を **見つけること**より、見つけられなかったときと前提が壊れているときに
# 黙って 0 を返さないことが要（**principle-gate-claims-on-evidence**）。
ipd="$sandbox_root/ip"; mkdir -p "$ipd"
mark="$ipd/MARK"
printf '#!/bin/sh\nexit 0\n' > "$ipd/clean.sh"
printf '#!/bin/sh\ntouch "%s"\n' "$mark" > "$ipd/dirty.sh"
printf '#!/bin/sh\ntouch "%s"\n' "$mark" > "$ipd/di rty.sh"   # 空白入りの名前
ip() { ( cd "$ipd" && bash "$root/scripts/isolate-pollution.sh" "$@" ); }

rm -f "$mark"
out=$(ip "test -e $mark" sh clean.sh dirty.sh clean.sh); code=$?
eq "汚染源を特定する" "$code" "1"
printf '%s' "$out" | grep -q '汚染源: dirty.sh' \
  && ok "汚染源の名前を出す" || ng "汚染源の名前が出ていない: [$out]"

rm -f "$mark"
ip "test -e $mark" sh clean.sh clean.sh >/dev/null 2>&1
eq "犯人が居なければ 0" "$?" "0"

# 走らせる前から残骸が在ると、最初の一件が犯人に見える。ここを 1 で返すと
# **無実の一件が犯人として報告される。**前提の破損は別の終了コードで落とす。
touch "$mark"
ip "test -e $mark" sh clean.sh >/dev/null 2>&1
eq "事前汚染は 2 で落ちる" "$?" "2"
rm -f "$mark"

ip foo >/dev/null 2>&1
eq "引数不足は 2 で落ちる" "$?" "2"

# 対象名の空白で分割されると、無関係な名前を走らせて誤った犯人を指す
rm -f "$mark"
out=$(ip "test -e $mark" sh clean.sh 'di rty.sh')
printf '%s' "$out" | grep -q '汚染源: di rty.sh' \
  && ok "空白入りの名前を割らない" || ng "空白入りの名前で壊れる: [$out]"

# 「持っていない人の手元」を模して doctor を走らせる。
# git と gh だけを通し、任意ツール（codex / cursor-agent / herdr）は PATH から外す。
# ここを素の PATH でやると、これらが実在する環境では恒真になって分岐を検証できない。
sandbox="$sandbox_root/bin"; mkdir -p "$sandbox"
for c in git gh; do
  # `command -v` はシェル関数やエイリアスも拾う。`type -P` は PATH 上の実体だけを返す。
  # ここで実体を取り損ねると、サンドボックスに $c が無いまま doctor が走り、
  # **テストの前提の破損が doctor の欠陥として報告される。**別の言葉で落とす。
  p=$(type -P "$c" 2>/dev/null)
  if [ -n "$p" ] && [ -x "$p" ]; then
    ln -s "$p" "$sandbox/$c"
  else
    ng "サンドボックスに $c を用意できない（doctor の欠陥ではなく、このテストの前提が壊れている）"
  fi
done

# PATH だけ剥いで HOME はそのままだと、持ち主自身の ~/.claude（私物 agent あり）が
# 常に真になり、「持っていない人」の分岐を検証できない。偽 HOME を作り、
# **plumb を入れただけで、任意のツールは何も持っていない人**を模す。
# 2026-08-30 まではここに superpowers のディレクトリを作っていた。plumb がそれを
# 依存として検査していたから。**依存が 0 になったので、模す前提からも外す。**
fake_home="$sandbox_root/home"
mkdir -p "$fake_home/.claude/projects" \
         "$fake_home/.claude/agents"

out=$(HOME="$fake_home" PATH="$sandbox:/usr/bin:/bin:/usr/sbin:/sbin" PLUMB_IN_SELFTEST=1 PLUMB_CONFIG=/nonexistent \
      bash "$root/scripts/doctor.sh" "$root" 2>&1)
ng_count=$(printf '%s\n' "$out" | grep -c '^  NG ' || true)
eq "素の環境で doctor の NG" "$ng_count" "0"

if [ $fail -eq 0 ]; then echo "  → 通過"; else echo "  → 失敗"; fi
exit $fail
