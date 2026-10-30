# ddviz

Parquet データからグラフを組み立てて可視化するアプリです。

## 特徴

- 直感的な操作
  - ドラッグ＆ドロップ操作でグラフを組み立てます。
- 省メモリ指向
  - 巨大なデータをメモリに載せません。

## 起動方法

[uv](https://docs.astral.sh/uv/) を使います。リポジトリのルートで実行してください。

```bash
uv run -m ddviz path/to/data.parquet
```

Parquet を指定しなければ、起動時にファイル選択ダイアログが開きます。

開発中にブラウザで使うときは `--port` を付けます。窓は開かず、そのポートで待ち受けます。起動ごとに作るトークン付きの URL（`http://127.0.0.1:<ポート>/?token=...`）が表示されるので、それをブラウザで開きます。トークンの無いリクエストは 403 で断ります。

```bash
uv run -m ddviz path/to/data.parquet --port 8000
```

## exe の作成方法

Windows のリポジトリのルートで実行します。

```bash
uv run --group build packaging/build.py
```

- 初回は WebView2 の固定版ランタイムをダウンロードし、Microsoft の署名を確かめてから `packaging/webview2/` に展開します（2 回目以降は再利用します）。
- PyInstaller（onedir）で exe を作り、`dist\ddviz\` に出力します。WebView2 のランタイムは `dist\ddviz\webview2\`、設定は `dist\ddviz\config\` に置かれます。
- 配布するときは `dist\ddviz` フォルダごと zip にして渡します。起動は `ddviz.exe` です。

### 共有の場所に置くとき

[docs/shared-install.md](docs/shared-install.md) を参照してください。
