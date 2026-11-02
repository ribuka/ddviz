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

- PyInstaller（onedir）で exe を作り、`dist\ddviz\` に出力します。設定は `dist\ddviz\config\`、WebView2 の SDK のライセンスと通知（`LICENSE-WebView2-SDK.txt`・`NOTICE.txt`）は `ddviz.exe` の横に置かれます。ネットからは何も取りません。
- WebView2 のランタイムは同梱しません。`ddviz.exe` は、横に `webview2\` のフォルダ（固定版）があればそれを、無ければ PC にインストールされた WebView2 のランタイムを使います。
- 配布するときは `dist\ddviz` フォルダごと zip にして渡します。起動は `ddviz.exe` です。

### WebView2 の入っていない PC（Windows Server 2016 など）や共有の場所に置くとき

[docs/shared-install.md](docs/shared-install.md) を参照してください。
