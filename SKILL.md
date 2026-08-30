---
name: plumb
description: plumb の入口。原則を名前で呼べる索引を持ち、非自明な仕事に規律を当てる。「plumb で」「原則に沿って」「鉛直を出してから」と言われたとき、および rigor が要る仕事に使う。
---

# plumb

## 使い方

非自明な仕事を始めるとき、**最初の todo は「下の原則索引を読む」**にする。
索引で当たった原則は、**その本文を全文読んでから**適用する。

**適用した原則は、返答の中で「その原則が変えた具体的な判断」と一緒に名指しする。**
判断の伴わない引用は、葉を読まなかった証拠として扱う。

## 実行先

役割ごとの実行先は `docs/role-map.md` が正本。本文にモデル名を書かない。

| 役割 | 実行先 |
|---|---|
| 本線 | いま動いている Claude Code |
| 実装役 | `Task`（`model` を書かない）。差分を出し、本線がレビューする |
| 探索役 | `Task`（`model` を書かない）。差分を出さない |
| 判定役 | `role.judge`（未設定なら本線が代行し、そう言う） |
| 量産役 | `role.bulk`（未設定なら本線が順に処理する） |

**非自明な仕事では、判定役の todo を必ず立てる。**やるかどうかを決める前に、まず行を作る。

その行は次のどちらかでしか閉じられない。

- 実行する
- `skip: <理由>` を付けて残す

**行を作らずに済ませることはできない。**消すこともできない。省略はできるが、黙ってはできない。
判定役の行が無い todo リストは、それ自体が規律違反の印になる。

## 型の索引

仕事の形が下のどれかなら、**その型を全文読んでから始める**。
型は原則を名指す。名指された原則は葉のスキルを全文読む。

### 調べる（コードを変えない）

| 仕事 | 型 |
|---|---|
| どう動くか・なぜこうか・本当に大丈夫か・どちらを採るか | `playbooks/investigation.md` |
| 生きたプロセスが漏れる・回り続ける・遅い | `playbooks/runtime-forensics.md` |
| 落ちてきた profile / trace / spindump / heapsnapshot を読む | `playbooks/trace-forensics.md` |

### 変える

| 仕事 | 型 |
|---|---|
| 遅いのを一発直す | `playbooks/perf-issue.md` |
| 一つの指標を継続的に押し下げる | `playbooks/hillclimb.md` |
| 振る舞いを変えずに構造を変える | `playbooks/refactoring.md` |
| **これから作るものの形を決める**（何を作るかがまだ決まっていない） | `playbooks/shaping-the-work.md` |
| **承認された形を、他人が実行できる手順にする** | `playbooks/writing-a-plan.md` |
| 設計判断を、捨てる実装で買う | `playbooks/prototype.md` |
| 独立した仕事を、並列の役に配る | `playbooks/fan-out.md` |

### 出す

| 仕事 | 型 |
|---|---|
| **ブランチを締める**（merge / PR / 残す のどれにするか決める） | `playbooks/closing-a-branch.md` |
| PR を出す | `playbooks/opening-a-pr.md` |
| 緑にして落とす | `playbooks/landing-a-stack.md` |

### 続ける

| 仕事 | 型 |
|---|---|
| 寝ている間も走らせ続ける・終わるまで回す | `playbooks/autonomous-run.md` |
| 安全に中断する・圧縮が近い | `playbooks/pause-safely.md` |
| 他のセッションの続きを引き継ぐ | `playbooks/session-pickup.md` |
| 隔離した作業場を作る | `playbooks/worktree-setup.md` |
| worktree とディスクを掃除する | `playbooks/worktree-cleanup.md` |

### 見る・保つ

| 仕事 | 型 |
|---|---|
| PR をレビューする（承認する側として） | `plumb:pr-review` |
| **レビューを頼み、返ってきた指摘に応じる**（著者として） | `playbooks/being-reviewed.md` |
| そのレビューに別ファミリーの軸を足す | `plumb:interrogate` |
| plumb が主張する環境がまだ実在するか見る | `plumb:doctor` |

### 決める・設計する

| 仕事 | 型 |
|---|---|
| 実行グラフを引く（5シグナル中2つ以上） | `plumb:graph` |
| **分岐のある判断を持ち主に返す**（選択肢が2つ以上あり、選び方で作るものが変わる） | `plumb:decision-brief` |

### plumb が型を持たないもの

**バグを直す**は既存の資産が持っている。
ここに同じものを置くと正本が二重になるので、**置いていない**。
**機能を作る・計画を書く**は plumb 自身の型になった（`playbooks/shaping-the-work.md` →
`playbooks/writing-a-plan.md`）。上の「変える」節から入る。

| 仕事 | どこへ |
|---|---|
| **バグを直す** | `superpowers:systematic-debugging` → TDD のループ。**設計から始めない** |
| **スキルを書く・直す** | Claude Code の skill 作成の作法 → `claude plugin validate` → `plumb:doctor` |
| 誰に投げるか | `docs/role-map.md` |
| ペイン・他エージェントの制御 | `pane.driver` が指すもの（未設定なら前面で実行する） |
| 起こし方の機構（いつ起きるか） | `/loop` と `ScheduleWakeup`。**規律は `playbooks/autonomous-run.md`** |

移植しなかった原本の型と、その理由は `docs/scope.md`。

## 成果物の置き場

**パスを組み立てない。道具に訊く。**

`plumb-*` は `bin/` の薄いラッパで、インストール時に Claude Code が全プラグインの
`bin/` を PATH に足すので、素の名前でどこからでも呼べる。

```bash
plumb-path spec      # 承認された設計
plumb-path plan      # 実行中の計画
plumb-path history   # 終わった計画
plumb-path run       # 台帳・決定ログ・ブリーフ
plumb-path spec --mkdir   # 無ければ作る
```

既定は `<リポジトリ直下>/.plumb/`。`PLUMB_ROOT` か `.plumb/config` の `root=` で変えられる。
**散文にパスを書くと、片方だけ古くなる**（**principle-encode-lessons-in-structure**）。

### spec と plan は格が違う

| | 何か | 寿命 |
|---|---|---|
| **spec** | 終了状態・受け入れ条件・なぜこの手か・却下した案 | **正本。**承認の対象で、変更には再承認が要る。追跡する |
| **plan** | ファイル・シグネチャ・**テストコード**・コミットの刻み方 | **使い捨て。**実行開始と同時に古くなる。追跡するが、終わったら落とす |

**「何が通れば完成か」は spec。「どのテストをどう書くか」は plan。**
同じテストの話でも、判定基準と実装は別の文書に置く。

`run/` は追跡しない（`.plumb/.gitignore`）。台帳と決定ログは作業の跡であって正本ではない。
**逆に specs と plans は必ず追跡する。**working tree と一緒に消える正本は正本ではない。

### 終わった plan は凍結して落とす

**完了した plan を `plans/` に残さない。**バッチ1で、Task 1 の時点で凍結された
`docs/plan.md` が現行と 18 行ずれたまま「これをタスク順に実行せよ」というヘッダを掲げて残り、
**後から来た者がそれを実行すれば、その日の修正が全部巻き戻る**状態になっていた。

`history/` へ移し、先頭にこれを置く。

```markdown
> **これは履歴。実行しない。**
> 現在の正本は <正本のパス>。**この文書と食い違ったら、正本が正しい。**
> 現在の正本に同期させない——同期させると、二重の正本が復活する。
```

**危険を止めているのはディレクトリ名ではなく、このヘッダ。**移すだけで済ませない。

### 既存の `docs/superpowers/`

`superpowers` を使ってきたリポジトリには `docs/superpowers/specs|plans` が残っている。
**一括では移さない。**リポジトリごとに判断する。
移していないリポジトリでは、**古いものは `docs/superpowers/` にある**ことを前提に探す。

## 原則索引

**原則はスキルではない。**`principles/<名前>.md` に素の文書として置いてある
（`principle-prove-it-works` なら `principles/prove-it-works.md`）。

スキルにしていないのは、**単独で発火させないため**。フラグで止めると、
索引から開く経路まで一緒に塞がる（2026-08-29 に実際そうなっていた）。
**構造で止めれば、入口はここだけになり、しかも開ける。**

適用する原則は Read で全文読む。要約で済ませない。

### 中核

- **principle-laziness-protocol** — 削除と最小の変更に倒す。リファクタ時、抽象を足したくなったとき
- **principle-foundational-thinking** — ロジックの前に中核の型とデータ構造を決める
- **principle-redesign-from-first-principles** — 新しい要件を、初日からの前提だったかのように設計し直す
- **principle-subtract-before-you-add** — 先に死んだ重さを取り除き、簡単になった土台の上に建てる
- **principle-minimize-reader-load** — 問いと答えの間の層と、読み手が頭に持つ隠れ状態を数える
- **principle-outcome-oriented-execution** — 移行は目標の設計に収束させる。使い捨ての互換層を残さない
- **principle-experience-first** — 実装の都合より使う人の体験を採る
- **principle-exhaust-the-design-space** — 前例のない判断では 2〜3 個の競合案を作って比べる
- **principle-build-the-lever** — 手でやらず、やる道具・証明する道具を作る。道具がレビュアーの再実行できる成果物になる

### アーキテクチャ

- **principle-model-the-domain** — 散らばった条件分岐ではなく、構造にドメインを表す
- **principle-boundary-discipline** — ガードは境界に集める。内側の型は信じる
- **principle-type-system-discipline** — 不正な状態を表現不能にする。ブランド型を付け、境界で外部データをパースし、コンパイラに嘘をつかず、バリアントを網羅し、正典スキーマから導出する
- **principle-make-operations-idempotent** — 途中まで走った後でも同じ終状態に収束させる
- **principle-migrate-callers-then-delete-legacy-apis** — 呼び出し側の移行と旧 API の削除を同じ波でやる
- **principle-separate-before-serializing-shared-state** — 共有をまず消す。直列化は本物の不変条件があるときだけ

### 検証

- **principle-prove-it-works** — 実物で検証する。代理指標や「ビルドが通った」で済ませない
- **principle-fix-root-causes** — 症状を根本原因まで辿る。先に再現させる
- **principle-sequence-verifiable-units** — 各単位を検証してから次へ進む。順序自体がレビュアーへの証明になる
- **principle-gate-claims-on-evidence** — 「終わった」と書く直前に関門を置く。走らせていないなら主張しない

### 委譲

- **principle-guard-the-context-window** — 大きな出力・長いファイル・繰り返しの読み・fan-out の計画で文脈が埋まるとき。かさばるものはサブエージェントに回し、本線には要約だけを置く
- **principle-never-block-on-the-human** — 元に戻せる作業は進めて、結果を見せて直してもらう

### メタ

- **principle-encode-lessons-in-structure** — 同じ指示を 2 度書いていたら、文章ではなく lint や検査やスクリプトにする
