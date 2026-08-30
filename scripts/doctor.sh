#!/usr/bin/env bash
# plumb doctor — 文書が主張する「環境」が、いまも実在するかを見る。
# check-harness.sh が内側の整合を見るのに対し、こちらは外側との接点を見る。
# 使い方: scripts/doctor.sh [plugin-root]
set -uo pipefail

root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
CLAUDE="$HOME/.claude"
fail=0
note() { printf '  %-4s %s\n' "$1" "$2"; }
bad()  { note "NG" "$1"; fail=1; }

echo "plumb doctor: $root"

# 1. 内側の整合（check-harness に委譲。二重に書かない）
echo "— 内側"
if bash "$root/scripts/check-harness.sh" "$root" >/dev/null 2>&1; then
  note "ok" "横断ルール（check-harness.sh）"
else
  bad "横断ルールが落ちている。scripts/check-harness.sh を直接走らせて内容を見る"
fi

# selftest から呼ばれたときは呼び返さない。相互再帰になる。
if [ -n "${PLUMB_IN_SELFTEST:-}" ]; then
  note "--" "スクリプトの振る舞い: selftest から呼ばれているので省略"
elif bash "$root/scripts/selftest.sh" "$root" >/dev/null 2>&1; then
  note "ok" "スクリプトの振る舞い（selftest.sh）"
else
  bad "selftest が落ちている。scripts/selftest.sh を直接走らせて内容を見る"
fi

# 2. 実行先。**必須と任意を分ける。**
#    git と gh は無いと型そのものが成立しない。それ以外は設定したときだけ要る。
#    「持っていない」を「壊れている」と報告すると、初回の体験が「壊れている」になる。
echo "— 実行先"
for c in git gh; do
  command -v "$c" >/dev/null 2>&1 && note "ok" "$c" || bad "$c が PATH に無い（plumb の全ての型が前提にしている）"
done

cfg() { bash "$root/scripts/plumb-config.sh" "$1" ""; }
for k in role.judge role.bulk pane.driver; do
  v=$(cfg "$k")
  if [ -z "$v" ]; then
    note "--" "$k: 未設定（本線が代行する）"
  elif command -v "$v" >/dev/null 2>&1; then
    note "ok" "$k = $v"
  else
    bad "$k = $v と設定されているが PATH に無い"
  fi
done

st=$(cfg stack.tool)
if [ -z "$st" ]; then
  note "--" "stack.tool: 未設定（landing-a-stack は素の gh pr merge に落ちる）"
elif [ "$st" = "gh-stack" ]; then
  gh extension list 2>/dev/null | grep -q 'gh stack' \
    && note "ok" "stack.tool = gh-stack" \
    || bad "stack.tool = gh-stack だが gh の拡張が入っていない"
else
  command -v "$st" >/dev/null 2>&1 && note "ok" "stack.tool = $st" || bad "stack.tool = $st が PATH に無い"
fi

# 3. plumb が名指す外部スキルが実在するか
#    索引に書いたのに存在しないと、行き先の無い転送になる
echo "— 外部スキル"
for s in agent-routing graph-engineering herdr pr-review; do
  if [ -f "$CLAUDE/skills/$s/SKILL.md" ]; then note "ok" "$s"
  else note "--" "$s: 未導入（plumb の索引が任意の転送先として名指している）"; fi
done
[ -d "$CLAUDE/plugins/cache/claude-plugins-official/superpowers" ] \
  && note "ok" "superpowers プラグイン" \
  || bad "superpowers が見つからない（plumb の索引が委譲先にしている）"

# 4. agent が名指す呼び出し元が実在するか
#    2026-08-29 に実際に壊れていた: pr-* agent 6 体が、退避済みの pr-review を指していた
echo "— agent の呼び出し元"
orphan=0
for f in "$CLAUDE"/agents/*.md; do
  [ -f "$f" ] || continue
  while IFS= read -r name; do
    [ -f "$CLAUDE/skills/$name/SKILL.md" ] || {
      bad "$(basename "$f" .md) が指す「$name スキル」が無い"; orphan=$((orphan+1)); }
  done < <(grep -oE '`?[a-z][a-z0-9-]+`? スキル' "$f" | tr -d '`' | sed 's/ スキル//' | sort -u)
done
[ $orphan -eq 0 ] && note "ok" "宙吊りの agent（0）"

# 5. path-map が主張するパスが実在するか
echo "— パス"
[ -d "$CLAUDE/projects" ] && note "ok" "~/.claude/projects/" || bad "~/.claude/projects/ が無い"
roots=$(git worktree list 2>/dev/null | wc -l | tr -d ' ')
note "--" "git worktree list が見ている worktree: ${roots} 件"
for d in "$HOME/.herdr/worktrees" "$HOME/.codex/worktrees"; do
  [ -d "$d" ] && note "--" "worktree 根あり: ${d/#$HOME/~}"
done

# 5b. 成果物の置き場が解決できるか
echo "— 成果物の置き場"
if r=$(bash "$root/scripts/plumb-path.sh" root 2>/dev/null); then
  note "ok" "解決できる（${r/#$HOME/~}）"
  # 追跡する側と捨てる側が入れ替わっていないか。
  # specs が ignore されていたら、正本が working tree と一緒に消える。
  if [ -d "$r" ]; then
    # 存在しないディレクトリには末尾スラッシュのパターンが一致しない。
    # 「まだ作られていない」を「追跡されている」と報告しないこと。
    if [ ! -d "$r/run" ]; then
      note "--" "run/: まだ作られていない（使うときに --mkdir で作られる）"
    elif git -C "$(dirname "$r")" check-ignore -q "$r/run" 2>/dev/null; then
      note "ok" "run/ は追跡外"
    else
      bad "run/ が追跡されている（台帳が正本に混ざる）"
    fi
    for k in specs plans; do
      git -C "$(dirname "$r")" check-ignore -q "$r/$k" 2>/dev/null \
        && bad "$k/ が ignore されている（正本が working tree と一緒に消える）" \
        || note "ok" "$k/ は追跡対象"
    done
  else
    note "--" "この場所にはまだ実体が無い（使うときに --mkdir で作られる）"
  fi
else
  bad "scripts/plumb-path.sh が解決できない"
fi

# 6. プラグインとして読み込まれているか
#    claude が PATH に無いのは「確認できない」であって「壊れている」ではない。
#    ここを混同すると、claude を CLI として使わない環境まで NG になる。
echo "— 読み込み"
if ! command -v claude >/dev/null 2>&1; then
  note "--" "plumb がプラグイン一覧にあるか: 確認できない（claude が PATH に無い）"
elif claude plugin list 2>/dev/null | grep -q 'plumb'; then
  note "ok" "plumb がプラグイン一覧にある"
else
  bad "plumb がプラグイン一覧に出ない。新しいセッションで claude plugin list を確認する"
fi

echo
if [ $fail -eq 0 ]; then echo "  → 健全"; else echo "  → 要対応（上の NG）"; fi
exit $fail
