# ddviz

非常に大きな Parquet データを、列をドラッグ＆ドロップしてグラフを組み立てる操作で可視化するアプリです。

## 特徴

- 列をドラッグ＆ドロップで X/Y 軸・facet・color などに置くだけで、散布図を描けます。
- 巨大なデータもメモリに載せきらずに集約して描画するので、16GB RAM の PC でも動きます。ホバーで行ごとの値を確認でき、ズーム・パン・ローカルフィルタにも対応しています。
- WebView2 の固定版ランタイムを同梱したフォルダで配布するので、インストール不要でオフライン環境（Windows 11、Windows Server 2016）でも動きます。

## 起動方法

[uv](https://docs.astral.sh/uv/) を使います。リポジトリのルートで実行してください。

```bash
uv run -m ddviz path/to/data.parquet
```

Parquet を指定しなければ、起動時にファイル選択ダイアログが開きます。

開発中にブラウザで使うときは `--port` を付けます。窓は開かず、`http://127.0.0.1:<ポート>/` で待ち受けます。

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
