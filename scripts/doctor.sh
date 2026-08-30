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
# python3 は plumb-pr-drift（skills/pr-review/scripts/pr-drift.sh）だけが使う。
# 他の型は前提にしていないので git/gh と同列の必須にはしない。持っていない人の
# 初回体験を「壊れている」にしないため、無ければ情報行（--）に留める。
command -v python3 >/dev/null 2>&1 \
  && note "ok" "python3" \
  || note "--" "python3 が PATH に無い（plumb-pr-drift を使うときだけ必要）"

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

# 3. plumb が委譲先として名指す外部プラグインが実在するか
#    agent-routing・graph-engineering・pr-review・herdr はもう plumb のルータが名指していない
#    （graph・pr-review・interrogate・doctor は同梱して plumb:* になった。agent-routing は
#    docs/role-map.md への転送に替わった。herdr は pane.driver 経由になり、実行先を直接
#    名指さない規則＝ルール10の対象）。ここに残す価値があるのは本物の依存 superpowers だけ。
echo "— 依存プラグイン"
#    superpowers は marketplace 名の下に入る。README が案内する github.com/obra/superpowers
#    は公式（claude-plugins-official）とは別名で入るため、決め打ちの1パスだけを見ると
#    別名から入れた人を NG にする。marketplace 名に依存せず探す。
sp_found=0
for d in "$CLAUDE"/plugins/cache/*/superpowers "$CLAUDE/skills/superpowers"; do
  [ -d "$d" ] && { note "ok" "superpowers プラグイン（${d/#$HOME/~}）"; sp_found=1; break; }
done
[ "$sp_found" -eq 1 ] || bad "superpowers が見つからない（plumb の索引が委譲先にしている）"

# 3b. 同梱した agent 6 体が実在するか（本文 → 実体）
#     pr-review スキルが名指す agent が消えると、反証段の呼び出し先を失ったまま気付けない。
#     抽出は本文形式（backtick 付き `pr-xxx`）で候補を拾うだけなので、`pr-drift` のような
#     bin/plumb-pr-drift の略称（agent ではない）も同じ形に見えてしまう。2026-08-30 に実測。
#     候補が bin/plumb-<name> コマンドとして実在する場合は agent 判定から外す。
echo "— 同梱 agent"
while IFS= read -r name; do
  [ -z "$name" ] && continue
  [ -f "$root/bin/plumb-$name" ] && continue
  if [ -f "$root/agents/$name.md" ]; then note "ok" "agents/$name.md"
  else bad "agents/$name.md が無い（skills/pr-review/SKILL.md が名指している）"; fi
done < <(grep -oE '`pr-[a-z-]+`' "$root/skills/pr-review/SKILL.md" | tr -d '`' | sort -u)

# 3c. agents/ に置いたのに、誰からも名指されていない agent は無いか（実体 → 本文）
#     check-harness のルール8（プレイブック/原則の索引）は本文↔実体を両方向見ているが、
#     agent はここまで 3b の一方向（本文が指す先の実在）しか見ていなかった。片方向だと
#     agent を足しただけで、誰にも呼ばれない孤児ファイルが静かに残っても気付けない。
for f in "$root"/agents/*.md; do
  [ -f "$f" ] || continue
  n=$(basename "$f" .md)
  grep -q "\`$n\`" "$root/skills/pr-review/SKILL.md" \
    || bad "agents/$n.md を名指す本文が無い（孤児 agent）"
done

# 4. agent が名指す呼び出し元が実在するか
#    ここで見る ~/.claude/agents/*.md は plumb が同梱するものではなく、あなた自身が
#    置いた私物。plumb を使う人ほど agent を増やすため、私物 agent の書き方次第で
#    plumb の doctor が NG になるのは筋が違う。fail は立てず、件数だけ報告する
#    （中身は持ち主にとって有用な情報なので検査自体は残す）。
echo "— agent の呼び出し元（あなたの ~/.claude/agents/ 私物。plumb は同梱していない）"
orphan=0
for f in "$CLAUDE"/agents/*.md; do
  [ -f "$f" ] || continue
  while IFS= read -r name; do
    [ -f "$CLAUDE/skills/$name/SKILL.md" ] || {
      note "--" "$(basename "$f" .md) が指す「$name スキル」が見当たらない（あなたの私物 agent。plumb には無関係）"
      orphan=$((orphan+1)); }
  done < <(grep -oE '`?[a-z][a-z0-9-]+`? スキル' "$f" | tr -d '`' | sed 's/ スキル//' | sort -u)
done
note "--" "宙吊りの private agent: ${orphan} 件"

# 5. path-map が主張するパスが実在するか
echo "— パス"
[ -d "$CLAUDE/projects" ] && note "ok" "~/.claude/projects/" || bad "~/.claude/projects/ が無い"
roots=$(git worktree list 2>/dev/null | wc -l | tr -d ' ')
note "--" "git worktree list が見ている worktree: ${roots} 件"
for d in "$HOME/.herdr/worktrees" "$HOME/.codex/worktrees"; do
  [ -d "$d" ] && note "--" "worktree 根あり: ${d/#$HOME/~}"
done

# 5b. 成果物の置き場が解決できるか
#     plumb-path.sh は cwd の git リポジトリを起点に解決する。git リポジトリの外から
#     doctor を回すと「壊れている」のではなく「確認できない」——bin/ を入れると
#     どこからでも plumb-doctor を叩けるようになるぶん、ここを踏みやすくなった。
echo "— 成果物の置き場"
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  note "--" "確認できない（git リポジトリの外。対象リポジトリの中で doctor を回す）"
elif r=$(bash "$root/scripts/plumb-path.sh" root 2>/dev/null); then
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
