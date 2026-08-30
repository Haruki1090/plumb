# plumb が持たないもの

plumb は pstack（`github.com/cursor/plugins` の `pstack/`、MIT）の型を出発点にしている。
**pstack 由来は 13 本**で、その内訳が下の表。**残りは pstack から来ていない**
（下の「pstack の外から書いたもの」）。

**2026-08-31 に、逐語で残っていた最後の資産が無くなった。**原則 22 本のうち 21 本は
pstack の英語本文がそのまま入っていたが、全部 plumb の言葉で書き直した（466 → 1,010 行）。
**訳ではない**——上流は「この原則はどんな失敗を防ぐために在るのか」を掴むためだけに読み、
閉じてから、**なぜ守れないのかという機構**と**守れたかを後から判定する方法**を書いた。
英語の名前だけは残している。型 22 本が本文中でその名前を名指しているため。
**この時点で、pstack から逐語で引き継いでいるものは 0 になった。**

**原本の本数は「どう数えるか」で変わる。**原本の README は本文で「22 個のプレイブック」と
書き、その数の表を掲げているが、実体の `skills/poteto-mode/playbooks/` には 23 個の
ファイルがある——`opening-a-pr.md` が実在するのに README の一覧表から漏れている
（2026-08-30 に `github.com/cursor/plugins` を実測して確認）。
下の内訳（移した 11 ＋ 畳んだ 3 ＋ 移さなかった 9 ＝ 23）は**ディレクトリの実体**を
数えたもので、README の 22 ではなく 23 と一致する。

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

### 既存資産と二重になる（当初 4 本 → 現在 1 本）

**この節は 2026-08-30 にほぼ空になった。**残っているのは `authoring-a-skill` だけで、
他の 3 本は「既存資産が持っている」という前提そのものを取り下げて書き下ろした。

| 原本 | 既にあるもの |
|---|---|
| ~~`feature`~~ | **2026-08-30 に撤回して書き下ろした。**`playbooks/shaping-the-work.md` → `playbooks/writing-a-plan.md` |
| ~~`bug-fix`~~ | **2026-08-30 に撤回して書き下ろした。**`playbooks/fixing-a-bug.md` ＋ `playbooks/writing-tests.md` |
| `authoring-a-skill` | Claude Code の skill 作成の作法と `claude plugin validate` |
| ~~`autonomous-run`~~ | **2026-08-29 に撤回して移植した。**`/loop` と `ScheduleWakeup` は**機構**（いつ起きるか）で、終了述語・最小変更・取り消し・途中発見の扱い・停滞≠停止という**規律を持っていない**。`hillclimb` は単一指標の場合しか覆わない |

**移すと正本が二重になる。**バッチ1で `docs/plan.md` が古い第二の正本になり、
後から来たエージェントが修正を全部巻き戻しかけた。同じ失敗を作らないための判断。

ルータの「plumb が型を持たないもの」の表に残っているのは `authoring-a-skill` の 1 行だけ。
**外部のプラグインへ転送する行は、もう一つも無い。**

**`feature` もこの節から出た。**2026-08-30 に「作る前に形を決める型」と「形を手順にする型」を
plumb の語彙で書き下ろした（下の表）。**移植ではないので、上の内訳の本数には数えない。**

**`autonomous-run` はこの節から出た。**2026-08-29 に撤回して移植済み
（`playbooks/autonomous-run.md`、ルータの「続ける」節に掲載）。
**これを二重の正本とみなして消さないこと。**`/loop` は機構で、規律を持っていなかった。

## pstack の外から書いたもの（9 本 + 原則 1 本 + 道具 1 本）

**pstack には無く、既存資産が別の形で持っていた問題**を、plumb の語彙で書き下ろした分。
移植ではないので、上の内訳の外に置く。

| plumb | 何を引き受けたか | plumb で足したもの |
|---|---|---|
| `playbooks/closing-a-branch.md` | 作り終えた作業の行き先（merge / PR / 残す）を持ち主に決めてもらう | 隔離を畳む規律は `worktree-cleanup.md` が正本のままで、**ここには書き写さない**。三択に「捨てる」を混ぜない |
| `playbooks/worktree-setup.md` | 隔離した作業場を作る | 置き場は `docs/path-map.md` が正本（**根が複数系統ある**）。**ignore されたものが複製されない**ことを、cleanup 側の関門の裏返しとして明示 |
| `playbooks/fan-out.md` | 独立した仕事を並列の役に配る | 役割は `docs/role-map.md` の `role.bulk`（未設定なら可視スキップ）。独立の判定を **principle-separate-before-serializing-shared-state** に接続 |
| `playbooks/shaping-the-work.md` | 作る前に形を決め、持ち主に渡して承認を取る | **止まる線を `principle-never-block-on-the-human` の中に引いた**——形（何を作るか）は止め、手（どう作るか）は止めない。**門は節ごとではなく1回**に畳み、待っている間も分岐に依存しない作業は進める。訊く前に `playbooks/prototype.md` で買える分岐は買う |
| `playbooks/writing-a-plan.md` | 承認された形を、他人が実行できる手順にする | 置き場は `plumb-path plan` が正本。**spec と plan の格の違いと凍結の規律は SKILL.md が持つので、ここには書き写さない。**全体制約を spec から逐語で写す例外に、**実装役が spec を開かないから**という理由を付けた |
| `playbooks/running-a-plan.md` | 計画をタスク単位で着地させる（配る／本線が刻む の両方） | **上限を 5 周から 3 周に縮めた**（1〜2 周は同じ役、3 周目は別の役、打ち止め）。**起点コミットをシェル変数ではなく台帳の列に持たせた**——変数は文脈の圧縮を跨がない。モデル選択の節は落とした（`docs/role-map.md` の領分）。workspace の作成機構も足していない（`plumb-path run` が持っている） |
| `playbooks/fixing-a-bug.md` | 再現を先に取り、症状から根本原因まで遡って直す | **`defense-in-depth`（全層に検査を撒く）を採らなかった**——**principle-boundary-discipline**（ガードは境界に集める・内側の型は信じる）と正面から衝突する。手順 6 では境界を締める側に倒し、**そう書いた**。時間で待たない検証と汚染源の切り分けは残し、道具は言語非依存に書き直した |
| `playbooks/writing-tests.md` | テスト自体の中身。赤を見ていないテストは何も守っていない | **守らないテストに 5 つの名前を与えて禁じた**（空振り／鏡／写し／代役への確認／緩めたテスト）。最後に「**製品側を一箇所壊して、どのテストが落ちるかを言う**」を置いた——主張ではなく判定できる形にするため |
| `playbooks/being-reviewed.md` | 著者としてレビューを頼み、指摘に応じる | **頼む側と受ける側を 1 本にまとめた。**返す形を `plumb:pr-review` と同じ**二軸**（確度 × ブロッキング性）で頼み、1 軸 severity を持ち込まない |
| `principles/gate-claims-on-evidence.md` | 完了を主張する前に関門を通す | **方法は `prove-it-works` が持っている。**この原則が持つのは**発火点**だけで、二重の正本にしない |

**書き下ろした原則は frontmatter に `origin: plumb` を持つ。**`NOTICE` は
「principles/ の何本が pstack の逐語複製か」を主張しており、その本数は
`scripts/check-harness.sh` のルール 13 が実体と突き合わせる。**印を付け忘れても、
NOTICE を直し忘れても、どちらでも赤くなる**（**principle-encode-lessons-in-structure**）。
2026-08-31 以降、この数は 22 / 0 で固定されている。

**同じ形の腐りが README にもあった。**「the 13 playbooks」（実体 22）、
「Twenty-one principles」（実体 22）。NOTICE はルール 13 が守っていたのに、
README は誰も見ていなかった。**ルール 14 を足して、本数の食い違いと綴り字の両方で
発火することを実測した**（数字で書く規約にしたのは、綴り字を機械が読めないため）。

## 原則の書き直しで、上流から意図して落としたもの

| 落としたもの | 理由 |
|---|---|
| `Why:` → `The pattern:` → `Applications:` の定型構成 | **なぞると訳になる。**原則ごとに、その原則が壊れる形に合わせて節を組み直した |
| 言語別イディオムの網羅（`type-system-discipline` の 7 パターン列挙など） | plumb は言語を選ばない。**「印と直し方」に反転**させ、例は plumb の実務に差し替えた |
| 上流が挙げた実例 | **plumb の実例に置き換えた**（`plumb-worktree-audit`、`plumb:doctor`、台帳の件数、承認済み×差し戻しなど） |
| `Prime directive:` のような固有の言い回し | 訳すと翻案になる |

**逆に足したもの**は、どの原則にも共通して 2 つ。**なぜ守れないのかという機構**——
「気を付ける」で守れる原則は原則ではないので、破られる原因を一段掘った。
そして**判定**——守れたかを後から言える問い・関門・数え方。
この 2 つを足したので、行数は上流より増えている。**短くすることは目標ではない。**

道具も 1 本増えた。`scripts/isolate-pollution.sh`（`plumb-isolate-pollution`）は
「単独では通るのに、まとめると落ちる」ときの汚染源を一件ずつ切り分ける。
**上流の同種のスクリプトは npm 決め打ちで、しかも走らせる前から残骸が在ると
最初の一件を犯人として報告する。**判定コマンドと実行コマンドを引数に取る形に書き直し、
**事前汚染は exit 2 で落とす**ようにした（無実の一件を犯人にしない）。

**落としたもの**は、それぞれの型が既に別の形で持っているか、この環境に無い機械に乗っていた
手順（menu の定型文、開始時の口上、severity の三段階、承認の合言葉、`.worktrees/` 決め打ち、
言語ランタイム別の自動セットアップ）。**要らないと判断して落とした**のであって、
未着手ではない。

`shaping-the-work` で落としたもの: **ブラウザ上の視覚コンパニオン**（別プロセスのサーバと
雛形一式）——plumb は `plumb:decision-brief`（HTML 1 枚 + 同じラベルの設問）と
`playbooks/prototype.md` を既に持っており、二つ目の見せ方の機構は要らない。
**spec / plan を別の役に読ませる雛形**——依頼の作法は `playbooks/being-reviewed.md`、
誰に頼むかは `docs/role-map.md` が正本。**工程図**と**開始時の口上**も落とした。

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
