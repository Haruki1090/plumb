#!/usr/bin/env bash
# plumb 横断ルール検証。レーンごとに解釈させず、ここに集約する。
# 使い方: scripts/check-harness.sh [plugin-root]
set -uo pipefail

root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
SKILLS_DIR="$root/skills"
ROOT_SKILL="$root/SKILL.md"
PB_DIR="$root/playbooks"
PR_DIR="$root/principles"
fail=0

note() { printf '  %-4s %s\n' "$1" "$2"; }
check() {
  if [ "$2" -eq "$3" ]; then note "ok" "$1（$2）"; else note "NG" "$1（期待 $3 / 実測 $2）"; fail=1; fi
}
# targets  = frontmatter を持つファイル（ルートの SKILL.md と skills/ 配下）
# bodies   = エージェントが読む本文すべて（targets + playbooks）。禁止語はこちらに効かせる
# docs/ と .git/ はどちらの対象でもない
targets() {
  find "$SKILLS_DIR" -name 'SKILL.md' 2>/dev/null
  [ -f "$ROOT_SKILL" ] && printf '%s\n' "$ROOT_SKILL"
}
playbooks() { find "$PB_DIR" -name '*.md' 2>/dev/null; }
principles() { find "$PR_DIR" -name '*.md' 2>/dev/null; }
bodies() { targets; playbooks; principles; }
# docs() と readme() はルール 11（bin/ 参照の実在）専用。bodies() には足さない——
# 既存ルール（禁止語チェックなど）の走査対象を広げると別の検査が壊れる。
docs_md() { find "$root/docs" -name '*.md' 2>/dev/null; }
readme() { [ -f "$root/README.md" ] && printf '%s\n' "$root/README.md"; }
bin_ref_sources() { bodies; docs_md; readme; }

echo "plumb harness check: $root"

# 0. 走査件数を必ず出す。0 件のまま「通過」するのを見逃さないため
scanned=$(targets | wc -l | tr -d ' ')
pbs=$(playbooks | wc -l | tr -d ' ')
prs=$(principles | wc -l | tr -d ' ')
note "--" "走査した SKILL.md: ${scanned} 件 / プレイブック: ${pbs} 件 / 原則: ${prs} 件"

# 1. 本文にモデル slug が無い
slug=0
while IFS= read -r f; do
  grep -qIE 'grok-[0-9]|gpt-[0-9]+(\.[0-9]+)?[a-z]*(-[a-z0-9.]+)*|claude-(opus|sonnet|haiku|fable)(-[0-9]+)+|claude-[0-9]+(-[0-9]+)*-(opus|sonnet|haiku|fable)|(^|[^A-Za-z0-9])o[0-9]+-[a-z]+|gemini-[0-9]+(\.[0-9]+)?-[a-z]+(-[a-z]+)*' "$f" \
    && { slug=$((slug+1)); note "NG" "モデル slug: ${f#$root/}"; }
done < <(bodies)
check "モデル slug を含むファイル" "$slug" 0

# 2. 本文に .cursor が無い
cur=0
while IFS= read -r f; do
  grep -qI '\.cursor' "$f" && { cur=$((cur+1)); note "NG" ".cursor: ${f#$root/}"; }
done < <(bodies)
check ".cursor を含むファイル" "$cur" 0

# 3. frontmatter に name と description がある
missing=0
while IFS= read -r f; do
  head -20 "$f" | grep -q '^name:' || { missing=$((missing+1)); note "NG" "name 欠落: ${f#$root/}"; }
  head -20 "$f" | grep -q '^description:' || { missing=$((missing+1)); note "NG" "description 欠落: ${f#$root/}"; }
done < <(targets)
check "frontmatter 欠落" "$missing" 0

# 4. 雛形の TODO が残っていない
todo=0
while IFS= read -r f; do
  head -20 "$f" | grep -q 'TODO' && { todo=$((todo+1)); note "NG" "TODO が残っている: ${f#$root/}"; }
done < <(targets)
check "TODO が残る frontmatter" "$todo" 0

# 5. 入口はモデルから開けること。原則はスキルではないこと
#    2026-08-29: disable-model-invocation をルータに当てたため、ハーネス全体が到達不能だった。
#    Skill ツールは「他の手段での代替」まで禁じるので、Read での迂回もできない。
dead=0
while IFS= read -r f; do
  grep -q '^disable-model-invocation' "$f" && { dead=$((dead+1)); note "NG" "スキルではないのに設定が残る: ${f#$root/}"; }
done < <(principles; playbooks)
check "死んだ設定が残る本文" "$dead" 0

blocked=0
while IFS= read -r f; do
  grep -q '^disable-model-invocation: *true' "$f" && { blocked=$((blocked+1)); note "NG" "モデルから開けない: ${f#$root/}"; }
done < <(targets)
check "モデルから開けないスキル" "$blocked" 0

# 6. 原則の description が日本語化されている（非 ASCII を 1 文字以上含む）
nojp=0
while IFS= read -r f; do
  desc=$(grep -m1 '^description:' "$f" || true)
  printf '%s' "$desc" | LC_ALL=C grep -qE '[^ -~]' || { nojp=$((nojp+1)); note "NG" "description が未翻訳: ${f#$root/}"; }
done < <(principles)
check "description が未翻訳の原則" "$nojp" 0

# 7. この環境に無い機械への依存が本文に残っていない
#    原本は Graphite / Cursor cloud / Bugbot / cursor-team-kit を前提にしている。
#    書き直しで消し忘れると、実行できない手順を指示する文書になる
ext=0
while IFS= read -r f; do
  hit=$(grep -oIE 'cursor-team-kit|Bugbot|control-ui|control-cli|/deslop|/no-comments|poteto|`gt`|gt submit|gt restack|gt track|gt sync|gt merge' "$f" | sort -u | tr '\n' ' ')
  [ -n "$hit" ] && { ext=$((ext+1)); note "NG" "無い機械への依存 [${hit%% }]: ${f#$root/}"; }
done < <(bodies)
check "この環境に無い機械を指す本文" "$ext" 0

# 7b. 本文が名指すスクリプトが実在する
#     「在るはずのものが無い」は grep でも lint でも出ない。2026-08-29 に 2 回踏んだ。
#     $(bodies) を素通しで grep の引数展開に渡すと、root にスペースが入るファイル名で
#     単語分割され、grep が「存在しないファイル」を渡されて黙って 0 件（誤って ok）になる。
#     1 ファイルずつ read で回し、パスをクオートしたまま grep に渡す。
miss=0
while IFS= read -r ref; do
  [ -f "$root/$ref" ] || { miss=$((miss+1)); note "NG" "本文が指すスクリプトが無い: $ref"; }
done < <(
  while IFS= read -r f; do
    grep -ohE 'scripts/[a-z0-9._/-]+\.(sh|mjs|ts|py)' "$f" 2>/dev/null
  done < <(bodies) | sort -u
)
check "実体の無いスクリプト参照" "$miss" 0

# 8. プレイブックとルータの索引が一致している（片方だけ足すと索引が嘘になる）
orphan=0; dangling=0
while IFS= read -r f; do
  grep -q "playbooks/$(basename "$f")" "$ROOT_SKILL" || { orphan=$((orphan+1)); note "NG" "索引に載っていない: playbooks/$(basename "$f")"; }
done < <(playbooks)
while IFS= read -r name; do
  [ -f "$PB_DIR/$name" ] || { dangling=$((dangling+1)); note "NG" "索引が指す実体が無い: playbooks/$name"; }
done < <(grep -oE 'playbooks/[a-z0-9-]+\.md' "$ROOT_SKILL" | sed 's|playbooks/||' | sort -u)
while IFS= read -r f; do
  n=$(basename "$f" .md)
  grep -q "principle-$n" "$ROOT_SKILL" || { orphan=$((orphan+1)); note "NG" "索引に載っていない: principles/$n.md"; }
done < <(principles)
while IFS= read -r name; do
  [ -f "$PR_DIR/$name.md" ] || { dangling=$((dangling+1)); note "NG" "索引が指す原則が無い: principles/$name.md"; }
done < <(grep -oE '\*\*principle-[a-z-]+\*\*' "$ROOT_SKILL" | sed -E 's/\*\*principle-([a-z-]+)\*\*/\1/' | sort -u)
check "索引に載っていない実体" "$orphan" 0
check "実体の無い索引行" "$dangling" 0

# 9. 公開できない固有名が残っていない
#    照合トークンはリポジトリの外に置く。ここにリテラルで書くと、消そうとしている
#    固有名そのものを公開物に載せることになる。
#    一覧が無ければ検査しない。ただし黙って通さず -- で出す（可視スキップ）。
# 走査の対象は「公開されるもの」= git が追跡しているもの。パスの許可リストにすると、
# 追跡対象が増えたときに穴が空く（2026-08-30、.plumb/plans が除外の内側にいて素通りした）。
everything() { git -C "$root" ls-files -z 2>/dev/null | tr '\0' '\n' | sed "s|^|$root/|"; }
tokens="${PLUMB_PRIVATE_TOKENS:-$HOME/.claude/plumb/private-tokens.txt}"
if [ ! -f "$tokens" ]; then
  note "--" "固有名の検査: トークン一覧が無いので省略（${tokens/#$HOME/~}）"
else
  priv=0
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    # git@github.com と noreply は個人の識別子ではなくインフラの表記なので除く
    hit=$(grep -oIEf "$tokens" "$f" 2>/dev/null \
          | grep -vxE 'git@github\.com|[a-z0-9-]+@users\.noreply\.github\.com' \
          | sort -u | tr '\n' ' ')
    [ -n "$hit" ] && { priv=$((priv+1)); note "NG" "公開できない固有名 [${hit%% }]: ${f#$root/}"; }
  done < <(everything)
  check "公開できない固有名を含むファイル" "$priv" 0
fi

# 10. 本文が実行先の道具を直接名指していない
#     名指すと、その道具を持っていない人にとって文書が嘘になる。実行先は
#     `~/.claude/plumb/config` が決め、本文は鍵（pane.driver など）を指す。
#     走査は bodies() だけ。docs/path-map.md は「どの道具がどこに worktree を置くか」の
#     事実であって命令ではなく、scripts/ はテスト値と doctor が見る外部スキル名なので対象外。
tool=0
while IFS= read -r f; do
  hit=$(grep -oIE 'herdr|cursor-agent|codex' "$f" | sort -u | tr '\n' ' ')
  [ -n "$hit" ] && { tool=$((tool+1)); note "NG" "実行先を直接名指している [${hit%% }]: ${f#$root/}"; }
done < <(bodies)
check "実行先を名指す本文" "$tool" 0

# 11. 本文が名指す plumb-* コマンドが bin/ に実在する
#     7b と同じ形。プラグインルートを指す変数は SKILL.md でしか展開されないため、
#     本文は bin/ のコマンド名を素で呼ぶ約束にした。名指した先が無いと exit 127 になる。
#     走査は bodies() だけでなく README.md と docs/ も含む——README がコマンド名を
#     持つ以上、そこだけ機械の外に置くのは筋が悪い（bodies() 自体は既存ルールが
#     使うので広げない。bin_ref_sources() をこのルール専用に別で持つ）。
BIN_DIR="$root/bin"
nobin=0
while IFS= read -r cmd; do
  [ -f "$BIN_DIR/$cmd" ] || { nobin=$((nobin+1)); note "NG" "本文が指す plumb-* コマンドが無い: bin/$cmd"; }
done < <(
  while IFS= read -r f; do
    grep -ohE '\bplumb-[a-z-]+\b' "$f" 2>/dev/null
  done < <(bin_ref_sources) | sort -u
)
check "実体の無い plumb-* コマンド参照" "$nobin" 0

if [ $fail -eq 0 ]; then echo "  → 通過（SKILL.md ${scanned} 件 / プレイブック ${pbs} 件 / 原則 ${prs} 件）"; else echo "  → 失敗"; fi
exit $fail
