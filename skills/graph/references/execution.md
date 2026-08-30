# 実行手段

グラフ定義書ができた後、それを実際に動かすための対応表。環境は Claude Code を想定。

## 設計要素 → 実行手段

| 設計要素 | 実行手段 |
|---|---|
| ノード | サブエージェント1体、またはコードのステップ。中身の実装と検証は委譲する（SKILL.md「ノード層は委譲する」） |
| 並列レーン | `Workflow` の `parallel()` / `pipeline()`、または同一メッセージ内の複数 Agent 呼び出し |
| Barrier | `parallel()`（全部待つ）、または単純にフェーズを分けて直列に書く |
| Pipeline（barrier なし） | `Workflow` の `pipeline()` |
| Edge Contract | `agent()` の `schema` オプション（JSON Schema で強制、検証は呼び出し層で行われる） |
| Model Tiering | `agent()` の `model` / `effort` オプション |
| 作業場所の分離 | `isolation: 'worktree'`（**制約あり。下の「worktree の制約」を先に読む**） |
| Human Gate | 実行を止めて人に聞く。グラフの中に埋めない |
| 正本への反映 | 実行後に MCP ツール（Notion / GitHub 等）で書き戻す |

## Workflow ツールを使う場合

**前提**: `Workflow` はユーザーが明示的にマルチエージェント実行を求めた場合にのみ使う。「グラフを設計して」は設計の依頼であって、実行の依頼ではない。設計を見せて、実行するかは確認する。

構造の既定は `pipeline()`。`parallel()` は前段の全結果が同時に必要なときだけ。

```javascript
export const meta = {
  name: 'lane-and-verify',
  description: 'レーンごとに実装し、完了したものから独立に検証する',
  phases: [{ title: '実装' }, { title: '検証' }],
}

const results = await pipeline(
  LANES,
  lane => agent(lane.prompt, {
    label: `impl:${lane.id}`, phase: '実装',
    schema: NODE_OUTPUT,          // Edge Contract
    isolation: 'worktree',        // 共有資源以外の衝突を防ぐ
  }),
  (out, lane) => agent(
    `次の変更が ${lane.spec} を満たすか、否定を試みて判定せよ。迷えば refuted。`,
    { label: `verify:${lane.id}`, phase: '検証', schema: VERDICT, effort: 'high' }
  ).then(v => ({ lane: lane.id, out, verdict: v }))
)

return results.filter(Boolean).filter(r => !r.verdict.refuted)
```

要点:

- 検証は実装と**別の `agent()` 呼び出し**にする。同じエージェントに続けさせない
- `schema` を付けると戻り値が検証済みオブジェクトになる。パースを書かなくてよく、形が合わなければモデル側がリトライする
- `agent()` は落ちると `null` を返す。`.filter(Boolean)` してから使う（失敗隔離）
- `phase` を明示すると進捗表示のグループが安定する
- `isolation: 'worktree'` はセットアップコストがあるので、**並列でファイルを書き換えるときだけ**使う

## worktree の制約

`isolation: 'worktree'` を使う前に、そのノードが何を必要とするかを確認する。

- **gitignore されたファイルは複製されない。** `.env` / `.env.local` / ローカル専用ディレクトリは worktree に存在しない。これらを `env_file` として必須参照する `docker-compose.yml` は、**起動どころか config の解決で失敗する**
- **compose の project 名がディレクトリ名由来で変わる。** named volume が別物になるので、DB のデータもキャッシュも空から始まる。固定ポートを公開しているなら本体スタックと同時起動できない
- **lint / test の結果が本体と一致しないことがある。** gitignore されたディレクトリが無い分だけ warning が消える。worktree の結果をもって「ローカル CI が通った」と主張しない
- **グラフ定義書が gitignore 対象なら worktree から見えない。** ノードに渡すときは本体側の絶対パスを使う

したがって **worktree に入れてよいのは「ソースを編集して lint / test / build を回す」ノードまで**。コンテナ起動を伴う検証ノード（DB を触る・E2E）は worktree の外で走らせる。

## モデルと effort の指定

ノードを `playbooks/running-a-plan.md` に委譲する場合、**役の割り当ては `docs/role-map.md` が正本**で、
この文書はモデル名を持たない。以下は Workflow で直接組む場合の目安。

既定は「指定しない」。指定しなければ親セッションのモデルを継ぐ。

| ノードの役割 | 指定 |
|---|---|
| 抽出・分類・機械的変換 | `effort: 'low'`、必要なら軽量モデル |
| 実装・調査 | 指定しない（既定を継ぐ） |
| 検証・裁定・最終統合 | `effort: 'high'` 以上 |

確信がないなら指定しない。下げると検証がすり抜け、上げるとコストだけ増える。

## Workflow を使わない場合

グラフが小さい（3〜5ノード）なら、Workflow を組むより素直に書くほうが速い。

- 独立したノードは、**同一メッセージ内で複数の Agent 呼び出し**を並べれば同時に走る
- 直列でよいものは普通に順に実行する
- barrier は「フェーズを分けて書く」だけで実現できる

**グラフ設計の価値は実行手段に依らない。** 設計そのものが、衝突・判断待ち・検証漏れを事前に潰している。手で実行しても効果は出る。

## 長時間の実行に耐えさせる

出典: [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

コンテキストは必ず尽きるので、外部に状態を置く。

- **進捗ファイル** — 何が終わったかを外部ファイルに書く。新しいセッションはこれを読んで状況を把握する。コンテキストの記憶に頼らない
- **項目リストの更新は限定する** — 完了フラグの値だけを書き換えさせる。項目そのものを書き換えさせない。放っておくと要件が書き換わって「全部終わった」ことになる
- **セッション開始時の健全性確認** — 前回までの成果がまだ動くかを最初に確かめてから新しい作業に入る
- **こまめなコミット** — 説明的なメッセージで刻む。問題があれば戻せる
- **圧縮だけでは足りない** — コンテキスト圧縮は必要だが、それだけでは複数コンテキストにまたがる作業は成立しない。外部状態と併用する

## 再開

`Workflow` は `resumeFromRunId` で再開できる。スクリプトの変更されていない先頭部分はキャッシュから即座に返り、最初の変更点以降だけが再実行される。

再開前に、完了したはずのノードが**本当に中身のある結果を返していたか**を確認する。空の結果がキャッシュされていることがある。

## 決定論を保つための注意

- ワークフロースクリプト内で `Date.now()` / `Math.random()` / 引数なし `new Date()` は使えない（再開が壊れるため）。時刻は引数で渡すか、実行後に付与する
- ランダム性が要るときは、インデックスでプロンプトやラベルを変える
