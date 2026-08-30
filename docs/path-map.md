# パス対応表

pstack 原本の Cursor 依存パスを、plumb では以下に置き換える。
本文に `.cursor` を書かない。この表が唯一の正本。

| 原本 | plumb | 備考 |
|---|---|---|
| `~/.cursor/rules/pstack-models.mdc` | 廃止 | モデル設定ファイルを持たない。役割対応表（`role-map.md`）に吸収する |
| `~/.cursor/projects/<slug>/agent-transcripts/<uuid>/<uuid>.jsonl` | `~/.claude/projects/<slug>/<uuid>.jsonl` | **平坦構造。**中間の `<uuid>/` ディレクトリは無い |
| スラッグの作り方（先頭の `/` を落とす） | **英数字以外を全部 `-` にする** | `/` も `.` も `_` も対象。`/Users/you/.herdr/x` → `-Users-you--herdr-x`（**ドットの分が連続ダッシュになる**）。`lv_slide_gen` → `lv-slide-gen`。2026-08-29 に実測（88 件すべてが `[-A-Za-z0-9]` のみ）。**`/` だけ置換すると、ドットを含むパスのセッションを丸ごと取り逃す** |
| `agent-transcripts/` ディレクトリ | `~/.claude/projects/<slug>/` | 専用ディレクトリは無く、スラッグ直下に `.jsonl` が並ぶ |
| `.cursor/skills/` | `.claude/skills/` | プロジェクトローカルのスキル |
| `~/.cursor/skills/` | `~/.claude/skills/` | ユーザーのスキル |
| `.cursor/skills/<handle>-mode/` `.cursor/skills/<handle>/<handle>-mode/SKILL.md` `.cursor/skills/**/*-mode/SKILL.md` `.cursor/skills/verify-<app>/` `.cursor/skills/verify-*/` | `.claude/skills/` 配下の対応パス | 上と同じ置換規則を、ワイルドカード・プレースホルダ入りのパスにも適用する |
| `.cursor/settings.json` | `.claude/settings.json` | |
| `.cursor/worktrees/<repo>/...` | **置換しない。`git worktree list` から読む** | 原本の主張が既に「手打ちのパスは取りこぼす」。この環境の worktree 根は複数系統に分かれるので、単一の置換先を書くと嘘になる。下の「注意」参照 |
| `~/.cursor/plugins/` | `~/.claude/skills/`（開発時に手で置く場合の設置場所） | pstack はプラグインとして `~/.cursor/plugins/` 配下に置かれていたが、plumb を手で `~/.claude/skills/plumb/` 配下に置くとそこが実体になる。**marketplace 経由でインストールした場合はここではなく `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` が実体になる**（本文からスクリプトを呼ぶときは相対パスではなく `${CLAUDE_PLUGIN_ROOT}` を使う） |
| `~/.cursor/projects/*/` `HOME/.cursor/projects/` | `~/.claude/projects/*/` | ワイルドカード表記のスラッグ一覧パス |
| `//api2.cursor.sh/automations/webhook/<id>` | 対象外 | Cursor のクラウド Webhook API。plumb はこの機能を持たない |
| `.cursor/automations/benny/` とその配下（`skills/`, `skills/triage-issue-reports/SKILL.md`, `skills/reproduce-and-fix-issues/SKILL.md`, `skills/setup-benny/SKILL.md`）、`<target-repository>/.cursor/automations/benny/` | 対象外 | benny は移植しない |
| `.cursor/benny/` とその配下（`routing.md`, `feature-map.md`, `configuration.yaml`） | 対象外 | benny は移植しない |
| `.cursor`（拡張子・パス構成要素を含まない裸の言及） | 対象外 | 原本で確認された唯一の出現は `automations/benny/skills/setup-benny/SKILL.md`（benny 配下）。benny は移植しないため、この行に独立した判断は要らない。benny 以外で新たに出現した場合のみ個別に判断する |

## 注意

- 「現在のワークスペースのトランスクリプト」を読ませる指示は、`~/.claude/projects/*/` を
  glob させない。他プロジェクトの私的なチャットを読むことになる。スラッグを確定してから開く。
- `~/.claude/history.jsonl` は別物（全セッションのコマンド履歴）。トランスクリプトと混同しない。
- **worktree のパスを手で組み立てない。**このマシンには根が複数ある（2026-08-29 実測）:
  `~/.cursor/worktrees/<repo>/`（Cursor Agent）、`~/.herdr/worktrees/<repo>/`（Herdr）、
  `~/.codex/worktrees/<id>/`（Codex）、そしてリポジトリ直下の `.claude/worktrees/<name>/`
  （Claude Code の `EnterWorktree`）。**`~/.claude/worktrees/` は存在しない** —
  Claude Code の worktree はホーム直下ではなくリポジトリ内に作られる。
  さらに `~/<任意>/<repo>-worktrees` のような手作りのものも混在する。
  列挙は必ず `git worktree list` から行う。原本 `worktree-cleanup.md` の指摘がそのまま当てはまる。
- 実測で判明した追加事実（表の範囲外の参考情報）: セッションがサブエージェントを使った場合、
  `~/.claude/projects/<slug>/<uuid>/subagents/agent-<id>.jsonl` という追加ディレクトリが
  メインの `<uuid>.jsonl` と同名で存在することがある（例: `3ae3dda1-633d-4bb1-9d0a-6b96dce014fe/subagents/`）。
  メインセッションのトランスクリプト自体は表のとおり平坦（`<slug>/<uuid>.jsonl`）だが、
  同じスラッグ直下に同名ディレクトリが並存しうる。pstack のトランスクリプト読み取りはメイン
  セッションが対象のため置換規則への影響は無いが、`<slug>/` 配下を `find`/`glob` する処理を
  書く場合はこの並存に注意する。
