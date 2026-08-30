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

# PATH だけ剥いで HOME はそのままだと、持ち主自身の ~/.claude（superpowers 導入済み・
# 私物 agent あり）が常に真になり、「持っていない人」の分岐を検証できない。
# 偽 HOME を作り、「README のとおり superpowers を入れ、任意のツールは何も
# 持っていない人」を模す。marketplace 名は plumb が決め打ちしていないことを
# 確かめるため、公式（claude-plugins-official）とは違う名前を使う。
fake_home="$sandbox_root/home"
mkdir -p "$fake_home/.claude/projects" \
         "$fake_home/.claude/plugins/cache/obra/superpowers" \
         "$fake_home/.claude/agents"

out=$(HOME="$fake_home" PATH="$sandbox:/usr/bin:/bin:/usr/sbin:/sbin" PLUMB_IN_SELFTEST=1 PLUMB_CONFIG=/nonexistent \
      bash "$root/scripts/doctor.sh" "$root" 2>&1)
ng_count=$(printf '%s\n' "$out" | grep -c '^  NG ' || true)
eq "素の環境で doctor の NG" "$ng_count" "0"

if [ $fail -eq 0 ]; then echo "  → 通過"; else echo "  → 失敗"; fi
exit $fail
