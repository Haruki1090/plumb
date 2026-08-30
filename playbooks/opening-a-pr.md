# PR を出す

**この型は入口ではない。**

型の終わりで最初に通るのは `superpowers:finishing-a-development-branch`。
テストを通したうえで、**ローカルに merge するか / push して PR にするか / ブランチを残すかを
持ち主に選んでもらう**のはそちらの仕事で、**同じ判断をここで先取りしない**。

**PR を出すと決まってから、この型に入る。**
出すところまでが範囲。緑にして落とすのは `playbooks/landing-a-stack.md`。

## 隔離

main から切った worktree で作業する。置き場と根の系統は `docs/path-map.md`。
**同じブランチに複数の実装役を同時に置かない**（**principle-separate-before-serializing-shared-state**）。
関係ない作業で汚れているブランチなら、パッチを取り出し、新しい worktree に当て直す。

## コミット

**コミットは惜しまない。PR を出す前に、小さく順序付いたコミットに rebase する。**
各コミットは将来の PR だと思って作る——単体で着地でき、物語の順に並んでいる。
直前のコミットに属する修正は amend、切り離せるなら新しいコミット。

## タイトル

`type(scope): subject` の Conventional Commits。type は `feat` `fix` `docs` `refactor`
`test` `chore` `perf`。scope は変えた領域。subject は短く命令形。
**変更を担う実在のシンボルがあるなら名指す。**末尾に句点を付けない。

## 本文

**次の節を、この順で。空の節は落とす。**

| 節 | 書くこと |
|---|---|
| `## Why` | 意図と、なぜこの手が合うか |
| `## Scope` | **差分から読める事実だけ。**実在のシンボルとパスを名指す。リネームや付け替えは両側を書く。境界が問題になるなら、内と外を書く |
| `## Tradeoffs` | **本物の選択だけ。**無いなら節ごと落とす |
| `## Blast Radius` | 誰と何に触れるか。なぜ安全か、あるいはなぜ危ういか。この修正が無いと main が赤いままなら、その継続的な費用を書く |
| `## Verification` | **各検査をどう走らせ、どこまで厳密か。**実際の経路を名指す。コマンド名ではなく結果を書く |

主張を証明する画面や動画があるなら、節の後に添える。
**`## Summary` と `## Test plan` の定型は使わない。**コミット本文は subject を言い直さない。

## UI の画面を貼る

UI に触れたなら、**変更前と変更後の画面を貼る**。差分からは良し悪しが読めない。

**基準をいじらない。**変更前の画面が「おかしい」ように見えても、撮り直したり整えたりしない。
おかしいなら、そう報告して止まる。**基準を触った時点で、比較は比較でなくなる。**

### 変更前を作る

変更前は実装後には存在しない。**先に撮るか、戻して撮る。**

戻すときは**触ったファイルだけ**を base から取り出す。dev サーバは再起動しない——
HMR が拾う。ブランチを切り替えたりスタッシュしたりすると、周辺まで変わって比較にならない。

```bash
git checkout origin/develop -- <touched-file>   # 撮る
git checkout HEAD -- <touched-file>             # 撮り終えたら戻す
```

`git status` で**戻し忘れが無いこと**を確認してから次に進む。

### 撮る

**両方の画面で、次を全部同じにする。**片方だけ違えば、その差が「変更」として写る。

- ウィンドウと viewport の寸法（`resize_window` を先に1回）
- スクロール位置と、ログイン中のアカウント
- **データの状態**（ピン留め・件数・ソート）。片方にしか無いセクションは比較にならない
- **ポインタの位置。**撮る直前に対象から離れた座標へ `hover` する。
  さもないと hover 状態が片方だけに焼き付く

**開発用のオーバーレイを消す。**Next.js の `nextjs-portal` と、Claude in Chrome 自身の
`#claude-agent-glow-border` は撮影対象に重なる。**同じ CSS を両方の状態に当て、
当てたことを PR 本文に書く。**片方だけに当てたら基準をいじったのと同じ。

```js
let s = document.getElementById('__shot-style');
if (!s) { s = document.createElement('style'); s.id = '__shot-style'; document.head.appendChild(s); }
s.textContent = 'nextjs-portal, #claude-agent-glow-border { display:none !important; }';
```

全体は `computer` の `screenshot`、部分は `zoom` に region を渡して切り出す
（どちらも `save_to_disk: true`）。**全体と拡大の両方を撮る。**
全体だけでは変更点が小さすぎ、拡大だけでは周りとの関係が読めない。

### 合成して置く

`scripts/host-shots.sh` が、左右合成・**親を持たない orphan コミット**への push・
貼り付け用 Markdown の出力までを引き受ける。**撮影はしない。**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/host-shots.sh" --branch assets/<topic>-<yyyymmdd> \
  --pair before-expanded.png after-expanded.png "展開の比較" \
  --file before-full.png "変更前（全体）" --file after-full.png "変更後（全体）"
```

orphan にするのは、develop / main の履歴に画像を入れず CI も走らせないため。
URL は `https://github.com/<owner>/<repo>/raw/<branch>/<file>` の形だけを使う——
**private リポでは `raw.githubusercontent.com` はセッション Cookie が乗らず 404 になる。**
`--help` に残りのオプションがある。

### 本文に書く

**見た目で変わった点を箇条書きで明記する。**画像を貼っただけでは読み手が差を探す羽目になる。
差分からも読めない（`px-3` → `px-2` が「詰まった」に見えることは、コードからは分からない）。

**設計ドキュメントに実値の契約があるなら、突き合わせる。**
色のトークンを検査するテストは通っても、寸法は誰も見ていない。ずれたなら**要判断として本文に出す**。
黙って通すのも、この PR で直すのも、どちらも勝手に決めない。

**目視のスクリーンショットは「見た目が変わっていない」の証明にはならない**
（pixel diff のハーネスは plumb に無い。`docs/scope.md`）。変えていないつもりの箇所は、
そう書いて留保する。

## 大きさ

**大きい1本より、狭い5本。**独立な作業だけ main から切る。

## 出し方

**単独の PR**

```bash
gh pr create --draft=false        # 下書きで開かない
gh pr view <number>               # 状態を語る前に必ず読む
```

**積むなら、積む手順を実際に踏む**

「後続は積む」と書いて `gh pr create` を並べても、**スタックにはならない。**
GitHub 側の base 関係も、`gh stack` が見る metadata も、誰も作らないまま残る。
その状態では `playbooks/landing-a-stack.md` の最終手順に到達できない。

```bash
gh stack init                     # 既定ブランチを起点に新しいスタックを始める
gh stack init b1 b2 b3            # 既にあるブランチ群をスタックにする
gh stack add <branch>             # 一番上に積む
gh stack submit                   # 全ブランチを push して PR を作る／更新する
gh stack view --short             # 積めているかを目で確認する
```

**`gh stack view` がスタックを見つけられないなら、それは積めていない。**
出した気になって次に進まない。

**既に base 連鎖だけで積んである PR 群を、後からスタックにする**

`gh pr create` を base 指定で並べただけの列は、GitHub 側でスタックになっていない。
`gh stack link` は**ローカルの追跡状態を使わずに**、既存の PR を下から順に紐付ける。

```bash
gh stack link 421 422 423 424 425 426   # 下から上の順。既存の PR 番号だけを渡す
gh stack view --short                    # 紐付いたか確認する
```

> **渡すのは PR 番号だけにする。**ブランチ名を渡すと、
> **そのブランチを push し、PR が無ければ新規に作る。**
> 数値引数は「まず PR 番号、無ければブランチ名」として解決されるので、
> **確実にしたいなら PR の URL を渡す**（URL は常に PR として解決される）。
> スタック番号を先頭に置くと、既存スタックの上に追加する意味になる。

## 出した直後にやらないこと

**PR を出すことは、緑にする作業の開始ではない。**URL を出して、作り続ける。
フェーズかスタック全体を作り終えてから、持ち主に求められたときに
`playbooks/landing-a-stack.md` を1回だけ走らせる。
**PR ごとに緑にしに行くと、後の波が作り直すコミットに検査を使い潰し、作業自体が止まる。**

**返すもの:** PR の URL、タイトル、検証の節に書いた内容。
