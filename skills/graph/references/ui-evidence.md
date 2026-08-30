# UI 変更のスクリーンショットを PR に載せる

SKILL.md 手順10 の実務。**フロントエンド・UI に触れたグラフの成果物には、画面を貼る（努力義務）。**

先に結論だけ:

1. **変更前は先に押さえる。** 実装後には存在しない。撮り忘れたら `git archive` で戻す
2. 撮影は**ヘッドレス Chrome**。実機検証ノードのついでに撮る
3. リポジトリに入れるなら **WebP に変換**。PNG のままは重い
4. **プライベートリポジトリでは `raw.githubusercontent.com` は表示されない。** `github.com/.../blob/<SHA>/...?raw=true` を使う
5. **GitHub には PR 本文へ画像をアップロードする API が無い。** 自動でやるならリポジトリにコミットする以外に道はほぼない

## 何を撮るか

その変更の主張が伝わる最小限でよい。全画面を並べるとかえって読まれない。

| 撮るもの | なぜ |
| --- | --- |
| 変更前 → 変更後 | 片方だけでは「何が変わったか」が読み取れない。UI 変更のレビューは差分ではなく比較 |
| 状態の分岐 | ロール別・空状態・エラー時。実装が分けているものは、分けたことが伝わるように分けて見せる |
| 導線の着地先 | リンクを張り替えたなら、意図した場所に着くところまで。遷移元だけでは検証にならない |

逆に**撮らなくていいもの**: 変わっていない画面、同じ変更の別解像度、装飾だけのバリエーション。

## 1. 変更前を確保する

実装を始める前に撮るのが一番安い。撮り忘れたら、変更前のコミットを展開して撮る。

```bash
# 変更前のコミットから、対象ディレクトリだけ /tmp へ展開する
git archive <before-sha> path/to/app | tar -x -C /tmp/before --strip-components=2
```

`git stash` や `git checkout` で作業ツリーを巻き戻す方法は取らない。**並列で走っているノードを巻き添えにする**。展開先を分けるのが安全。

## 2. 撮る

静的モックなら HTTP で配信してヘッドレス Chrome。`file://` は localStorage が使えないことがあるので避ける。

```bash
cd /tmp/before && python3 -m http.server 8942 &
cd path/to/app && python3 -m http.server 8941 &
```

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=2 --user-data-dir=/tmp/cp_01 \
  --virtual-time-budget=3500 --window-size=1440,1560 \
  --screenshot=/tmp/shots/01.png "http://localhost:8941/page.html"
```

- `--force-device-scale-factor=2` — 2倍で撮って後で縮小すると文字が締まる
- `--window-size` の高さ — **ページ全体が入る高さを指定する**。足りないと下が切れる。切れたら高さを増やして撮り直し
- `--user-data-dir` は撮影ごとに変える。使い回すとプロファイルのロック待ちで固まる
- `--virtual-time-budget` はフォント読み込み待ち

**ヘッドレス Chrome は撮影後も終了しないことがある。** そのまま待つとシェルがタイムアウトするので、バックグラウンドで起動して「ファイルができたら kill」する:

```bash
( "$CHROME" ... --screenshot="$OUT" "$URL" >/dev/null 2>&1 ) &
P=$!; for i in $(seq 1 25); do sleep 1; [ -s "$OUT" ] && break; done
sleep 1; kill $P 2>/dev/null
```

### 状態を切り替えて撮る

localStorage で状態を持つアプリなら、状態を書いてリダイレクトするだけのページを配信ディレクトリに置く（撮影後に消す）。

```html
<!doctype html><meta charset="utf-8"><script>
var q=new URLSearchParams(location.search);
localStorage.setItem("<key>", JSON.stringify({ role: q.get("role") }));
location.replace(q.get("to"));
</script>
```

`__role.html?role=VIEWER&to=page.html` で撮れる。ブラウザ自動化ツールで毎回 localStorage を書いてリロードするより速く、再現性がある。

## 3. 軽くする

リポジトリに入れるなら WebP。実測で PNG の 1/5 になる。

```bash
sips -Z 1440 shot.png --out shot.png     # 2倍で撮ったものを等倍へ
cwebp -q 82 shot.png -o shot.webp        # 300KB → 60KB 程度
```

UI のスクリーンショットに JPEG は使わない（文字がにじむ）。WebP は GitHub の Markdown で表示できる。

## 4. どこに置くか

**GitHub には PR 本文・コメントへ画像をアップロードする公開 API が無い。** `user-images.githubusercontent.com` への投稿は Web UI 専用の非公開エンドポイントなので、`gh` からは叩けない。ブラウザ自動化も、ツール側のアップロード制限に阻まれることがある。

| 方法 | 可否 | 備考 |
| --- | --- | --- |
| リポジトリにコミット | ○ | 自動でやるなら実質これ一択 |
| Web UI にドラッグ&ドロップ | ○ | 人間なら速い。リポジトリは汚れない |
| `gh release upload` | △ | プライベートなら結局認証が要る。スクショのためにリリースを切るのは筋が悪い |
| Gist / 外部ホスティング | ✗ | 非公開の画面を外に出すことになる |

コミットする場合、**そのリポジトリに画像が1つも無いなら、それは新しい前例になる**。黙って入れない。

- 置き場所は、その画面のソースの隣（`mocks/<release>/screenshots/` など）
- **同ディレクトリに README を置く** — 撮り方のコマンドと一覧。これが無いと後任には由来不明のバイナリになる
- ファイル所有権リストや親 README があるなら、そこからリンクする
- PR 本文に「不要なら消せます」と書いて、判断を相手に残す

## 5. 本文に貼る

**プライベートリポジトリでは `raw.githubusercontent.com` の画像は表示されない**（認証が通らず壊れたリンクになる）。次を使う:

```markdown
![説明](https://github.com/<owner>/<repo>/blob/<commit-sha>/path/to/shot.webp?raw=true)
```

- **ブランチ名ではなくコミット SHA** を入れる。マージ後にブランチを消してもリンクが切れない
- 画像をコミット → `git push` → SHA を取る → `gh pr edit --body-file` の順。SHA が要るので本文更新は後

貼ったら**必ずブラウザで表示を確認する**。壊れていても Markdown としては通るので、確認しないと気付けない。

### 日本語での Markdown の罠

`…の中でも**「メーカー」タブ**に…` のように、**日本語や括弧に直接くっつけた `**` は太字にならない**（CommonMark の flanking 規則）。前後に半角スペースを入れる。

GitHub は `#11` を Issue/PR 番号として自動リンクする。**Figma のコメント番号など、GitHub 以外の採番を書くときは `` `#11` `` とコードスパンにする**。しないと無関係な PR へのリンクになる。

## グラフ上の置き場所

撮影専用ノードを作らない。**実機を触る検証ノードの責務に含める**（同じ画面を二度開くだけ）。

グラフ定義書には「## 成果の見せ方」として、撮る画面・変更前の確保方法・どの検証ノードで撮るかを一行ずつ書く。**変更前の確保は barrier 側**（実装が始まる前）に置くのが安全。
