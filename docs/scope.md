# plumb が持たないもの

plumb は pstack（`github.com/cursor/plugins` の `pstack/`、MIT）の型を出発点にしている。
原本のプレイブックは 23 本、plumb には 13 本ある。

**差の内訳を残す。**「まだ手が回っていない」と「意図して置かない」は別物で、
記録が無いと後から区別できなくなる。**この文書は謝辞でもある** — plumb がどこから
来て、どこで別のものになったかがここに書いてある。

## 移した（11 本）

原本の依存が薄く、既存資産に無い語彙を持つもの。本文はこの環境向けに日本語で書き直した。

`investigation` `runtime-forensics` `trace-forensics` `perf-issue` `hillclimb`
`refactoring` `prototype` `pause-safely` `session-pickup` `worktree-cleanup`
`autonomous-run`（**バッチ3で下記の判断を撤回して追加**）

## 畳んだ（3 本 → 2 本）

| 原本 | plumb | 理由 |
|---|---|---|
| `opening-a-pr` | `playbooks/opening-a-pr.md` | PR 記述規約（Why / Scope / Tradeoffs / Blast Radius / Verification）は既存資産に無い。Graphite 依存を `gh` に置き換えた |
| `babysit` + `shipping` | `playbooks/landing-a-stack.md` | **`gh stack merge` が atomic（all-or-nothing）**なので、原本の後半が丸ごと消える。順に排水されるキューを見張る手順、途中で触らない規律、merge-when-ready を仕込んだか確かめる手順、`autoMergeRequest` を証拠に読まない警告——**全部 Graphite の逐次マージ由来**。天井を正しく選ぶことに集約された |

## 移さなかった（9 本）

### 無い機械に乗っている（6 本）

`autopilot-full` `autopilot-stack` `orchestrate` `multi-phase-plan` `eval` `visual-parity`

Cursor cloud agent、Graphite、レビュー bot、`cursor-team-kit` の操作スキル群、
専用の CLI と watcher が前提。**しかも原本で最長の 6 本**なので、
移植ではなく全面的な再著述になる。

加えて `orchestrate` は原本自身がこう書いている——実測で、30 分・12 ユニットの仕事に
この儀式を被せたら着地 1 件、素のエージェントは 12 件全部着地した、と。
**個人が単独で回す規模で使う型ではない。**

**この 6 本のうち 2 本は、既存資産への転送ではなく機能欠落である。**そう書いておく。

| 型 | 何が引き継がれ、何が落ちたか |
|---|---|
| `eval` | 引き継いだのは**判定役を別ファミリーに置く**ことだけ（`docs/role-map.md`、`plumb:interrogate`）。**盲検の規則は無い**——候補に評価語・rubric・他候補の存在を見せない、ディレクトリ名を無害化する、判定役はラベルだけを見る。**plumb はエージェントの振る舞いを評価する型を持っていない。**必要になったらここから作る |
| `visual-parity` | 引き継いだのは**変更前を先に撮る**ことと**基準をいじらない**ことだけ（`playbooks/opening-a-pr.md` の UI 節）。**pixel diff の回帰ハーネスも、差分ゼロという合格条件も無い。**目視のスクリーンショットは「見た目が変わっていない」の証明にならない。**それを承知で目視に留めている** |

**この 2 行を消してはいけない。**消すと、欠落が「転送済み」に見える。

### 既存資産と二重になる（当初 4 本 → 現在 3 本）

| 原本 | 既にあるもの |
|---|---|
| `feature` | `superpowers`（brainstorming → writing-plans → subagent-driven-development） |
| `bug-fix` | `superpowers:systematic-debugging` と TDD のループ |
| `authoring-a-skill` | Claude Code の skill 作成の作法と `claude plugin validate` |
| ~~`autonomous-run`~~ | **2026-08-29 に撤回して移植した。**`/loop` と `ScheduleWakeup` は**機構**（いつ起きるか）で、終了述語・最小変更・取り消し・途中発見の扱い・停滞≠停止という**規律を持っていない**。`hillclimb` は単一指標の場合しか覆わない |

**移すと正本が二重になる。**バッチ1で `docs/plan.md` が古い第二の正本になり、
後から来たエージェントが修正を全部巻き戻しかけた。同じ失敗を作らないための判断。

ルータの「plumb が型を持たないもの」の表が、**残り 3 本**の行き先を明示している。
**穴ではなく、意図した転送。**

**`autonomous-run` はこの節から出た。**2026-08-29 に撤回して移植済み
（`playbooks/autonomous-run.md`、ルータの「続ける」節に掲載）。
**これを二重の正本とみなして消さないこと。**`/loop` は機構で、規律を持っていなかった。

## bun は入れない（2026-08-29 に決定を撤回）

バッチ0で「bun を入れる」と決めたのは、pstack の TypeScript 資産を移す前提だった。
**その前提が消えたので撤回する。**実測した内訳がこれ。

| 資産 | 行数 | 誰のためのものか |
|---|---|---|
| `scripts/orch/` | 2,819 | `orchestrate`。**移さないと決めた型** |
| `scripts/watch-pr/` | 3,392 | `babysit` のキュー監視。**`gh stack merge` が atomic なので不要になった** |
| `scripts/check-plan.mjs` | 186 | `multi-phase-plan`。**移さないと決めた型** |
| `scripts/worktree-audit.sh` | 86 | `worktree-cleanup`。**移した型** |
| `show-me-your-work/scripts/log.sh` | 40 | 決定ログ。`hillclimb` が要求している |

**TypeScript 約 6,400 行は、全部わたしが移さないと決めた型のためのものだった。**
生きているのは shell 2 本・126 行だけで、どちらも bash で動く。
**使わないランタイムを入れる理由が残っていない。**

2 本は書き直して `scripts/` に入れた。`worktree-audit.sh` は
既定ブランチの決め打ちをやめ、トランスクリプトのパスをこの環境に合わせ、
**作り直せる ignore 済みファイルを除外する**ようにした（除外しないと
毎回「確認せよ」としか言わず、本物の `.env` が 34 個の `__pycache__` に紛れる）。

## 後で見直す条件

- `gh` に stack の watcher が入ったら、`landing-a-stack` の CI 分類節を機械に寄せられる
- 走らせる規模が「1セッションで終わらない」域に入ったら、`orchestrate` の
  ブリーフ雛形と liveness の節だけは取りに戻る価値がある（儀式ではなく、その 2 節だけ）
