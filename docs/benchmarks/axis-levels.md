# カテゴリの軸の水準数の計測（Issue #102）

X / Y のカテゴリの軸の水準数を増やしたときの時間・メモリ・画面の負荷を測り、上限の方針を決めた記録。決定と集約した表は `docs/spec.md` の「カテゴリの軸の水準の上限と目盛りの間引き」と「カテゴリの軸の水準数」にある。

1. 変更前（2026-11-07、コミット `aa54b91`）：上限を変えずにワーカー・Chrome・WebView2 を測った（計測のときだけ `max_levels` を 2,000,000 に上げ、全ケースで同じ値を使った）。この結果でユーザーと方針を決めた（X / Y 専用の上限 `plot.max_axis_levels` を既定 100 万で作り、目盛りを間引く）。
2. 変更後（2026-11-08）：既定の設定のまま、同じデータで Chrome と WebView2 の画面を測った。

## 1. 変更前の計測（2026-11-07）

### 計測計画の見直し（ユーザーと合意）

Issue の計画は、X/Y と Color/Overlay/facet を同じ条件で分けて比べる点、ケースごとに新しいワーカーで 3 回測る点、停止条件、Chrome と WebView2 の区別のどれも、判断に必要なので維持した。次の点を変えた。

- **追加**：100 万水準（100 万行がすべて別の値。ID の列に相当）。上限を撤廃すると置けてしまう最悪のケースで、上限の根拠だった 143GiB の失敗に相当する。
- **縮小**：1 億行は 420 水準の 1 系統だけ（行数への依存の傾きは 1000 万行までで分かる）。Chrome の操作は 420 水準と 10,000 水準について、ズーム 1 回・ホバー 1 回・目盛り・範囲選択・フィルタを確かめた（範囲選択とフィルタは API で行数を突き合わせた。100 水準以下の操作は既存の E2E が見ている）。段ごとの時間には既存の計時が無いため、代表ケースだけ、別の 1 回で cProfile を取った（3 回の計測には入れていない）。
- **結果の置き場所**：この Issue のコメント（spec は実装ブランチで書く）。

### 条件

- PC：AMD Ryzen 5 7600X3D（6 コア）、物理メモリ 31.1GB（計測時の空きは約 7.5GiB）、Windows 11 Pro 26200。コミット `aa54b91`（main）。polars 2.1.0、numpy 2.5.4、fastapi 0.162.0、uvicorn 0.54.0、plotly.js 4.1.1、Playwright 1.63.0、Chrome 156.0.8078.76（ヘッドレス）、WebView2 Evergreen 156.0.4314.58（pywebview 6.2.1）。
- データ（`gen.py`、seed 102）：100 万行。`x` と `y` は正規分布の Float64。`xc{n}` と `yc{n}`（n = 100、101、420、1,000、10,000、100,000、1,000,000）は `L0`〜`L{n-1}` の短い文字列で、各水準の行数は均等（`arange(rows) % n` を並べ替えたもの）。`yc{n}` は `xc{n}` と独立に並べ替えた。両方に置いたとき実際に出る水準の組は、100 で 10,000、101 で 10,201、420 で 175,802、1,000 で 632,303、10,000 で 995,159。ほかに `c10`、`o10`、`g10`（10 水準）、偏りのある `sk10000`（全水準が 1 行以上、残りの行は u⁴ で低い番号に偏る。1 水準の行数は最大 98,600、中央値 44、最小 12。上位 1% の水準で 31% の行）、最小例の `month`（`1990-01`〜`2024-12` の 420 種類の文字列）と `period`（その番号の Float64）。1000 万行（`xc100`、`xc420`、`xc10000`）と 1 億行（`xc420`）は別のファイルにした。zstd、行グループは 100 万行、45MB／191MB／1.6GB。
- ワーカー（`bench_api.py`）：1 回ごとに UI サーバーを新しく起動し（新しいワーカー、Job Object のメモリ上限は物理メモリの半分のまま）、`POST /api/plot` を 1200×900 で送った。列キャッシュは共有で、ケースごとに最初の 1 回（warm。列の変換を含むことがある）を分け、続く 3 回の中央値［最小–最大］を出した。task は応答の `meta.task_seconds`（サーバーから見たタスク全体）。RSS とコミットは 50ms ごとの子プロセスの最大値。停止条件：1 回 120 秒、プロセスツリーの RSS が物理メモリの 40% 超、OS の空きメモリが 2GiB 未満。同じ系統で失敗したら、それより重いケースは実施しない。
  - **task の約 1 秒は水準によらない固定の分**：サーバーを毎回起動し直したため、タスクは待機中のワーカーが polars を読み込み終わるのを待つ。cProfile では、xcat-100 の集約そのものは約 0.16 秒だった。比べるときは 1 秒を超える分を見る。
- 画面（`bench_page.py`）：Chrome は描画領域 1200×900、1 回ごとに新しいページ。列を D&D で置き、最後のドロップ（箱ひげ図は点を外すクリック）から描き終わるまでを測った。値は画面の `#info`（fetch と newPlot）、50ms を超えるロングタスク（PerformanceObserver）、描画後の DOM ノード数と JS ヒープ（`--enable-precise-memory-info`）、描かれた目盛りのラベルの数と、隣と重なるラベルの数。WebView2 は開発環境の `uv run -m ddviz` を `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=…` で起動し、Playwright の `connect_over_cdp` で同じ測り方をした。窓が既定の大きさのため、描画領域は 771×719。
- OS のファイルキャッシュは温まった状態（同じファイルを続けて読んでいる）。初回の列変換は warm 列の括弧内の値（convert 秒）。

### ワーカー（100 万行、1200×900。1000 万行と 1 億行は名前に明記）

| case | task s | worker peak RSS GiB | commit GiB | response | warm (convert s) |
|---|---|---|---|---|---|
| xcat-100 | 1.13 [1.00–1.14] | 0.32 [0.32–0.32] | 1.07 [1.04–1.09] | 3KB | 0.95 (0.30) |
| ycat-100 | 1.11 [1.10–1.23] | 0.30 [0.27–0.32] | 0.99 [0.89–1.01] | 3KB | 0.24 (0.97) |
| both-100 | 1.26 [1.18–1.28] | 0.41 [0.38–0.42] | 1.09 [1.08–1.11] | 175KB | 0.27 (0.98) |
| box-100 | 1.11 [1.09–1.16] | 0.50 [0.47–0.51] | 2.54 [2.52–2.55] | 14KB | 1.20 (0.00) |
| xcat-101 | 1.44 [1.09–1.69] | 0.31 [0.27–0.32] | 0.95 [0.95–1.07] | 3KB | 0.21 (1.01) |
| ycat-101 | 1.07 [1.05–1.15] | 0.33 [0.31–0.33] | 0.98 [0.92–1.06] | 3KB | 1.09 (0.00) |
| both-101 | 1.19 [1.16–1.26] | 0.37 [0.34–0.41] | 1.08 [1.01–1.11] | 177KB | 0.26 (1.06) |
| box-101 | 1.22 [1.10–1.30] | 0.51 [0.45–0.52] | 2.49 [2.48–2.52] | 14KB | 1.17 (0.00) |
| xcat-420 | 1.13 [1.06–1.16] | 0.35 [0.33–0.35] | 1.08 [1.07–1.10] | 9KB | 0.30 (1.05) |
| ycat-420 | 1.08 [1.06–1.08] | 0.36 [0.36–0.37] | 1.05 [1.05–1.07] | 9KB | 1.08 (0.00) |
| both-420 | 失敗 {"detail":"ValueError: 同じ座標に重なる点の集まりが 172,387 個あり、上限の 100,000 個を超えるため描けない。フィルタで行を絞るか、別の列を使 | 0.51 | | | |
| box-420 | 1.16 [1.15–1.23] | 0.51 [0.44–0.51] | 2.55 [2.51–2.56] | 54KB | 1.16 (0.02) |
| xcat-1000 | 1.11 [1.06–1.18] | 0.38 [0.37–0.38] | 1.11 [1.05–1.12] | 18KB | 0.24 (0.94) |
| ycat-1000 | 1.12 [1.07–1.12] | 0.39 [0.39–0.40] | 1.08 [1.07–1.11] | 19KB | 1.09 (0.00) |
| both-1000 | 未実施（同系統の軽いケースが失敗） | | | | |
| box-1000 | 1.13 [1.13–1.15] | 0.53 [0.52–0.54] | 2.57 [2.56–2.58] | 126KB | 1.15 (0.00) |
| xcat-10000 | 1.13 [1.11–1.15] | 0.41 [0.41–0.42] | 1.13 [1.12–1.15] | 185KB | 0.36 (0.91) |
| ycat-10000 | 1.21 [1.13–1.37] | 0.42 [0.41–0.42] | 1.13 [1.12–1.16] | 204KB | 1.14 (0.00) |
| both-10000 | 未実施（同系統の軽いケースが失敗） | | | | |
| box-10000 | 1.65 [1.60–1.74] | 0.53 [0.53–0.57] | 2.61 [2.61–2.63] | 1263KB | 1.65 (0.00) |
| xcat-100000 | 1.69 [1.59–1.76] | 0.50 [0.49–0.51] | 1.25 [1.24–1.27] | 2031KB | 0.80 (1.02) |
| ycat-100000 | 1.62 [1.60–1.63] | 0.50 [0.50–0.51] | 1.24 [1.21–1.26] | 2401KB | 1.60 (0.00) |
| both-100000 | 未実施（同系統の軽いケースが失敗） | | | | |
| box-100000 | 6.95 [6.94–6.96] | 0.81 [0.80–0.83] | 2.91 [2.90–2.93] | 12864KB | 6.89 (0.00) |
| xcat-1000000 | 8.19 [8.13–8.27] | 0.96 [0.94–0.97] | 1.55 [1.55–1.56] | 22246KB | 7.06 (0.95) |
| ycat-1000000 | 7.97 [7.91–8.00] | 0.97 [0.93–1.00] | 1.57 [1.55–1.57] | 26131KB | 7.96 (0.01) |
| both-1000000 | 未実施（同系統の軽いケースが失敗） | | | | |
| box-1000000 | 24.31 [24.28–24.60] | 1.79 [1.79–1.81] | 2.45 [2.45–2.46] | 130685KB | 24.16 (0.00) |
| color-100 | 1.40 [1.39–1.42] | 0.42 [0.41–0.43] | 1.04 [1.03–1.06] | 5KB | 1.38 (0.01) |
| overlay-100 | 1.40 [1.39–1.41] | 0.41 [0.41–0.44] | 1.03 [1.01–1.05] | 5KB | 1.39 (0.00) |
| groupx-100 | 1.10 [1.09–1.13] | 0.42 [0.39–0.43] | 1.09 [1.08–1.11] | 84KB | 1.15 (0.00) |
| color-420 | 2.20 [2.20–2.23] | 0.43 [0.42–0.44] | 1.05 [1.01–1.07] | 15KB | 2.07 (0.00) |
| overlay-420 | 2.15 [2.13–2.20] | 0.44 [0.43–0.44] | 1.06 [1.04–1.07] | 15KB | 2.26 (0.00) |
| groupx-420 | 1.41 [1.40–1.44] | 0.58 [0.58–0.58] | 1.20 [1.19–1.22] | 352KB | 1.40 (0.00) |
| color-1000 | 3.29 [3.27–3.30] | 0.44 [0.44–0.45] | 1.07 [1.06–1.07] | 33KB | 3.30 (0.00) |
| overlay-1000 | 3.30 [3.28–3.34] | 0.45 [0.43–0.46] | 1.05 [1.04–1.06] | 33KB | 3.30 (0.00) |
| groupx-1000 | 1.90 [1.86–1.90] | 0.83 [0.80–0.88] | 1.54 [1.53–1.56] | 839KB | 1.91 (0.00) |
| xcat10m-100 | 1.67 [1.61–1.73] | 1.10 [1.07–1.15] | 1.85 [1.83–1.87] | 3KB | 1.54 (0.22) |
| xcat10m-420 | 1.62 [1.62–1.66] | 1.38 [1.33–1.44] | 2.36 [2.18–2.41] | 9KB | 0.76 (1.05) |
| xcat10m-10000 | 1.80 [1.76–1.82] | 1.44 [1.44–1.45] | 2.36 [2.35–2.36] | 185KB | 1.00 (0.95) |
| xcat100m-420 | 16.26 [15.96–16.42] | 2.32 [2.21–2.60] | 3.27 [3.26–3.76] | 9KB | 16.03 (1.05) |
| xcat-420+c10 | 1.19 [1.19–1.22] | 0.52 [0.52–0.53] | 1.16 [1.16–1.19] | 9KB | 0.35 (0.92) |
| xcat-420+c10o10 | 1.59 [1.59–1.61] | 0.59 [0.59–0.60] | 1.20 [1.18–1.23] | 15KB | 0.75 (0.92) |
| xcat-420+gx10 | 1.09 [1.07–1.12] | 0.45 [0.42–0.46] | 1.14 [1.14–1.16] | 52KB | 0.27 (0.92) |
| xcat-10000+c10 | 1.30 [1.25–1.31] | 0.56 [0.49–0.57] | 1.17 [1.16–1.18] | 186KB | 1.23 (0.01) |
| xcat-10000+c10o10 | 1.70 [1.69–1.75] | 0.61 [0.59–0.63] | 1.23 [1.21–1.26] | 192KB | 1.64 (0.00) |
| xcat-10000+gx10 | 1.17 [1.14–1.17] | 0.45 [0.44–0.46] | 1.18 [1.17–1.18] | 1150KB | 1.15 (0.00) |
| xcat-skew10000 | 1.11 [1.11–1.12] | 0.39 [0.38–0.40] | 1.18 [1.16–1.20] | 185KB | 0.33 (0.93) |
| month-period | 1.11 [1.10–1.14] | 0.30 [0.29–0.37] | 0.94 [0.94–1.04] | 18KB | 0.18 (0.98) |
| month-box | 1.08 [1.05–1.13] | 0.51 [0.51–0.53] | 2.56 [2.55–2.64] | 55KB | 1.15 (0.00) |

xcat = X カテゴリ／Y 数値の点、ycat = X 数値／Y カテゴリの点、both = 両軸カテゴリの点、box = X カテゴリ／Y 数値の箱ひげ図（点なし）。color／overlay／groupx = X、Y が数値で、同じ水準の列をその役割に置いた。`+c10` などは 10 水準の列を足したもの。

段ごとの内訳（cProfile、各 1 回。プロファイラの分だけ遅い）：

| ケース | 集約全体 | 水準を数える段（`_overview`） | うち水準の自然順の並べ替え（`natural_key`。水準ごとの Python） | 箱の統計（`box_stats`。うち群ごとの `_ranks`） | 結果のファイル（`manifest.write`） | 系列の画像層（`spread`＋`encode_mask`） |
|---|---|---|---|---|---|---|
| xcat-1000000 | 11.6s | 11.0s | 6.9s | - | 0.6s | - |
| box-1000000 | 25.7s | 11.5s | 7.2s | 7.9s（3.3s） | 8.6s | - |
| color-1000 | 約 2.5s | 小 | 小 | - | 小 | 1.5s＋0.6s（1000 層） |

### 画面：Chrome（描画領域 1200×900、3 回の中央値［最小–最大］）

| case | stage | fetch ms | newPlot ms | long tasks (n / total ms / max) | DOM | heap MB | ticks (overlapping) |
|---|---|---|---|---|---|---|---|
| xcat-100 | 1200×900 | 949 [949–968] | 93 [93–95] | 1 / 93 [93–95] / 95 | 547 | 17 [17–17] | 100 (99) |
| ycat-100 | 1200×900 | 171 [164–171] | 89 [87–90] | 1 / 90 [88–91] / 91 | 559 | 17 [17–17] | 100 (99) |
| both-100 | 1200×900 | 236 [235–250] | 166 [165–177] | 2 / 305 [299–316] / 178 | 732 | 18 [18–18] | 100 (99) |
| box-100 | 1200×900 | 853 [820–858] | 71 [71–93] | 1 / 71 [71–93] / 93 | 547 | 18 [18–18] | 100 (99) |
| xcat-101 | 1200×900 | 907 [905–917] | 94 [94–96] | 1 / 94 [94–96] / 96 | 549 | 18 [18–18] | 101 (100) |
| ycat-101 | 1200×900 | 166 [161–195] | 90 [89–91] | 1 / 91 [91–92] / 92 | 561 | 18 [18–18] | 101 (100) |
| both-101 | 1200×900 | 256 [244–262] | 169 [169–181] | 2 / 308 [307–329] / 182 | 736 | 18 [18–18] | 101 (100) |
| box-101 | 1200×900 | 850 [792–858] | 86 [74–92] | 1 / 86 [74–92] / 92 | 549 | 20 [19–20] | 101 (100) |
| xcat-420 | 1200×900 | 929 [919–942] | 1193 [1192–1246] | 1 / 1193 [1193–1246] / 1246 | 1187 | 18 [18–19] | 420 (419) |
| ycat-420 | 1200×900 | 186 [184–197] | 841 [826–850] | 1 / 842 [827–851] / 851 | 1199 | 20 [19–20] | 420 (419) |
| both-420 | 断られた（ワーカーと同じ、重なる点の集まりの上限） |||||||
| box-420 | 1200×900 | 260 [259–263] | 1163 [1160–1193] | 1 / 1163 [1160–1193] / 1193 | 1187 | 16 [16–16] | 420 (419) |
| xcat-1000 | 1200×900 | 947 [945–962] | 6731 [6626–6760] | 1 / 6731 [6626–6760] / 6760 | 2347 | 21 [18–22] | 1000 (999) |
| ycat-1000 | 1200×900 | 215 [208–219] | 4380 [4362–4478] | 1 / 4381 [4364–4479] / 4479 | 2359 | 18 [17–18] | 1000 (999) |
| both-1000 | 断られた（同上） |||||||
| box-1000 | 1200×900 | 298 [296–300] | 6465 [6439–6505] | 1 / 6466 [6440–6506] / 6506 | 2347 | 20 [18–20] | 1000 (999) |
| xcat-10000 | 失敗 TimeoutError: Page.wait_for_function: Timeout 120000ms exceeded. |||||||
| ycat-10000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| both-10000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| box-10000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| xcat-100000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| ycat-100000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| both-100000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| box-100000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| xcat-1000000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| ycat-1000000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| both-1000000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| box-1000000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| color-100 | 1200×900 | 1341 [1331–1362] | 10 [9–12] | 1 / 72 [72–87] / 87 | 778 | 17 [17–17] | 9 (0) |
| overlay-100 | 1200×900 | 1351 [1340–1363] | 10 [10–11] | 1 / 71 [69–72] / 72 | 778 | 17 [17–17] | 9 (0) |
| groupx-100 | 16179×883 | 1083 [1064–1084] | 250 [248–297] | 1 / 284 [280–330] / 330 | 26888 | 44 [44–46] | 0 (0) |
| color-420 | 1200×900 | 2157 [2048–2229] | 37 [16–40] | 2 / 333 [54–344] / 288 | 2058 | 20 [20–21] | 9 (0) |
| overlay-420 | 1200×900 | 2065 [2035–2169] | 17 [16–18] | 2 / 344 [334–352] / 297 | 2058 | 21 [21–21] | 9 (0) |
| groupx-420 | 67699×883 | 1367 [128–1381] | 3176 [30–3237] | 2 / 3687 [0–3732] / 3644 | 380808 | 302 [19–303] | 0 (0) |
| color-1000 | 1200×900 | 3191 [125–3404] | 29 [27–42] | 1 / 122 [122–180] / 122 | 4378 | 23 [23–24] | 9 (0) |
| overlay-1000 | 1200×900 | 3228 [3219–3258] | 21 [21–24] | 2 / 173 [120–181] / 130 | 4378 | 24 [24–24] | 9 (0) |
| groupx-1000 | 161079×883 | 1871 [1274–1910] | 18946 [18750–19026] | 2 / 21562 [21238–21596] / 21132 | 2066288 | 1308 [1307–1311] | 0 (0) |
| xcat-420+c10 | 1200×900 | 312 [309–319] | 1253 [1218–1271] | 1 / 1254 [1219–1272] / 1272 | 1231 | 16 [16–16] | 420 (419) |
| xcat-420+c10o10 | 1200×900 | 1578 [1549–1583] | 1269 [1266–1282] | 2 / 1361 [1353–1362] / 1284 | 1285 | 19 [19–20] | 420 (419) |
| xcat-420+gx10 | 1689×883 | 251 [251–266] | 27 [27–33] | 0 / 0 [0–0] / 0 | 5248 | 17 [17–17] | 0 (0) |
| xcat-10000+c10 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| xcat-10000+c10o10 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| xcat-10000+gx10 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| xcat-skew10000 | 未実施（xcat-10000 が 120 秒で打ち切りのため） |||||||
| month-period | 1200×900 | 983 [974–1071] | 1216 [1204–1234] | 1 / 1217 [1205–1234] / 1234 | 1199 | 18 [18–18] | 420 (419) |
| month-box | 1200×900 | 253 [250–271] | 1176 [1155–1181] | 1 / 1176 [1155–1181] / 1181 | 1187 | 16 [16–16] | 420 (419) |

- groupx の描画領域が広いのは、パネルの並びが横にスクロールするため（100 パネルで幅 16,179px）。
- 操作の確認（xcat-420、Chrome）：
  - ズーム：帯 10〜19 に合わせると、`/api/view` は 0.07 秒、23,810 行（10 水準 × 2,381 行で一致）。
  - ホバー：帯 14 の上で水準 `L14` が出た。行番号の行も `L14` で一致。
  - 範囲選択：帯 10〜19 を囲むと 23,810 行で、データから数えた行数と一致。
  - フィルタ：50 水準に絞ると 119,050 行で一致した。ただし、軸には 420 本の帯がそのまま残る。水準はフィルタの前の行から数えるため。
  - 空白・欠落・水準の取り違えは見つからなかった。xcat-10000 は描画が終わらないため確かめていない。

### 画面：WebView2（アプリの窓、描画領域 771×719、3 回）

| case | stage | fetch ms | newPlot ms | long tasks (n / total ms / max) | DOM | heap MB | ticks (overlapping) |
|---|---|---|---|---|---|---|---|
| xcat-100 | 771×719 | 1222 [887–1245] | 150 [105–151] | 1 / 150 [106–152] / 152 | 548 | 25 [20–29] | 100 (99) |
| box-100 | 771×719 | 819 [794–825] | 91 [80–125] | 1 / 91 [80–126] / 126 | 548 | 35 [28–49] | 100 (99) |
| xcat-420 | 771×719 | 906 [893–1099] | 1310 [1279–1434] | 1 / 1310 [1279–1434] / 1434 | 1188 | 27 [24–38] | 420 (419) |
| box-420 | 771×719 | 286 [285–307] | 1232 [1210–1339] | 1 / 1232 [1210–1339] / 1339 | 1188 | 40 [27–45] | 420 (419) |
| month-period | 771×719 | 1015 [961–1170] | 1369 [1342–1393] | 1 / 1369 [1342–1393] / 1393 | 1200 | 33 [27–37] | 420 (419) |
| month-box | 771×719 | 289 [285–293] | 1259 [1193–1282] | 1 / 1259 [1194–1282] / 1282 | 1188 | 61 [50–75] | 420 (419) |

- 10,000 水準は WebView2 では測っていない。Chrome で 120 秒以内に描き終わらなかったため（下の「画面の負荷」）。
- WebView2 の窓は既定の大きさのままで、描画領域が Chrome（1200×900）より小さい。そのため数値はそのまま比べられないが、420 水準の newPlot は 1.2〜1.4 秒で、Chrome と同じ程度だった。

### 分かったこと

**1. ワーカー：X/Y の水準数はほとんど効かない。100 を境に急に増える負荷は無い**

- 100 と 101 の差は誤差の範囲（xcat 1.13 秒と 1.44［1.09–1.69］秒、ピークはどちらも 0.3GiB）。
- 10,000 水準までは、約 1 秒の固定の分と変わらない。100,000 水準で +0.6 秒、1,000,000 水準（全行が別の値）で約 8 秒、ピーク RSS 0.96GiB、コミット 1.55GiB。上限の根拠になった 143GiB のような確保は、X/Y では起きない。X/Y の位置は帯の番号を数値の軸として扱い、系列の画像層を増やさないため。
- 増える分は水準の数に比例する。水準の自然順の並べ替え（`natural_key`、水準ごとに Python で処理）と、応答の大きさ（全水準の目盛り。1,000,000 水準で 22MB）。
- 箱ひげ図は箱の数に比例する。100,000 水準で 7.0 秒、1,000,000 水準で 24 秒・1.8GiB・応答 130MB。時間は箱の統計（群ごとの Python）と結果のファイルの書き出しにかかる。
- 行数：1000 万行では 100〜10,000 水準でどれも 1.6〜1.8 秒・1.1〜1.4GiB。1 億行・420 水準で 16.3 秒・2.3GiB。水準数と行数が掛け算で効く様子は無い。
- 系列・パネルとの組合せ：420 水準と 10,000 水準に Color 10、Color 10 × Overlay 10、Group X 10 をそれぞれ足しても、増える分は水準数によらない（+c10o10 は 1.59 秒と 1.70 秒）。
- 偏りのある 10,000 水準も、均等の場合と同じ（1.11 秒）。

**2. Color／Overlay／facet は系列やパネルの数に比例して重くなり、X/Y とは仕組みが違う**

- Color と Overlay は、系列ごとに 1200×900 の画像層を 1 枚ずつ作る。そのため、水準 100 で 1.4 秒、420 で 2.2 秒、1,000 で 3.3 秒（1000 層の `spread` と PNG で約 2 秒）。100 万行・1200×900 ではメモリは増えなかった（0.4GiB）。
- Group X は、ワーカーでは軽い（1,000 パネルで 1.9 秒・0.8GiB）。重いのは画面で、DOM が 100 パネルで 2.7 万、420 で 38 万、1,000 で 207 万になり、1,000 パネルでは newPlot が 19 秒、ヒープが 1.3GB。
- X/Y と同じ上限で守る必要があるのは系列とパネルの側で、今回の計測でも負荷の形が違った。

**3. 両軸がカテゴリの点は、水準の上限より先に、既存の「重なる点の集まり」の上限（10 万個、`MAX_PILES`）で止まる**

- 101 水準では 10,201 組で描けた。420 水準では出現する組が 175,802 あり、「同じ座標に重なる点の集まりが 172,387 個」で断られた（ワーカーでも Chrome でも同じ）。1,000 水準以上は同じ理由で実施していない。
- 両軸がカテゴリのときの守りは、この上限が担っている。

**4. 画面の負荷：目盛りのラベルの描画が水準数のほぼ 2 乗で増え、1,000 水準を超えると実用にならない**

- サーバーは全水準を `tickmode: "array"` の `tickvals`／`ticktext` で plotly に渡す（`server/figure.py:153`）。newPlot は 1 つのロングタスクになり、その長さは 100 水準で 93ms、420 で 1.2 秒、1,000 で 6.7 秒（420→1,000 での指数は約 2.0）。
- 10,000 水準は 120 秒以内に描き終わらなかった。2 乗で外挿すると約 11 分で、その間ページが固まり操作できない。Chrome の 10,000 水準以上と WebView2 の 10,000 水準は、このため実施していない。
- Y に置いた場合も同じ形（420 で 0.84 秒、1,000 で 4.4 秒）。箱ひげ図も、点の場合と同じ目盛りのコストがかかる。
- Group X 10 パネルに 420 水準を置くとラベルが描かれず（目盛りのラベル 0 個）、newPlot は 27ms だった。重いのは目盛りのラベルだと裏付けられる。
- 計測に使ったコードを補う推定：plotly が配列の目盛りを全部 DOM に置き、重なりの判定をする処理が 2 乗になるとみられる。JS のプロファイルは取っていない。

**5. 目盛りの読みやすさ（性能とは別の問題）**

- 1200px に 100 水準以上を並べると、どのラベルも帯の幅に合わせて「…」に縮められ、名前は読めない（100 水準でも同じ。帯は約 9px）。
- 帯 10 本までズームしても、ラベルは「…」のままだった。ラベルを縮めるのは全体図のときだけで、ズームで作り直されないため。水準の名前はホバーでしか分からない。
- 目盛りの間引きやスクロールは対象外なので、記録だけにする。

**6. 今の上限 100 は、フィルタで回避できない**（ユーザーの `month` の例に直接かかわる）

- 既定の上限 100 で `month`（420 水準）を X に置き、フィルタで 50 水準に絞っても、部分一致で「1990」（12 水準）に絞っても、「month は 420 個」で断られる。Color に置いても同じ。
- 水準はフィルタの前の行から数える（`compute/aggregate.py` `_overview` のコメント。1 億行でのメモリのため）。そのため、エラーメッセージの「フィルタで水準を絞るか」という案内は、今の動作と合っていない。
- 上限を引き上げて描いた場合も、50 水準に絞ったあと軸に 420 本の帯が残る（上の操作の確認）。

### 測れていない範囲

- 両軸カテゴリの 1,000 水準以上（重なる点の集まりの上限で止まる）。
- 画面の 10,000 水準以上（xcat-10000 の打ち切りだけ記録した）、偏りのある 10,000 水準の画面、10,000 水準での操作の確認。
- Color／Overlay／Group X の 1,000 水準超（対象外）。
- 1 億行は 420 水準だけ。長い文字列のラベル。
- WebView2 の 1200×900（窓の大きさを変えていない）。
- 目盛りのコストの JS 側の内訳。
- OS のファイルキャッシュが冷えた状態。


## 2. 変更後の画面（2026-11-08）

X / Y の上限を `plot.max_axis_levels`（既定 100 万）に分け、カテゴリの軸の目盛りをページで間引いた後（`docs/spec.md`「カテゴリの軸の水準の上限と目盛りの間引き」）、設定は既定のまま（上限を引き上げずに）同じデータで画面を測った。

- 条件：同じ PC。コミットはこの変更（ブランチ `orca/issue-102`、親は `82e4726`）。データは `gen_after.py`（下。1 の `gen.py` の 100 万行のうち、`x`、`y`、`xc100`〜`xc1000000`、`month`、`period` を同じ seed 102 で作る。各水準の行数は均等、zstd、行グループ 100 万行、30MB）。
- Chrome 156.0.8078.76（ヘッドレス、描画領域 1200×900）は `bench_page_after.py`、WebView2 は開発環境の `uv run -m ddviz` の窓（既定の大きさ、描画領域 769×717、`Edg/157.0.0.0`）に `bench_wv2_after.py` で CDP からつないだ。測り方は 1 の `bench_page.py` と同じ（最後のドロップ、または箱ひげ図で点を外すクリックから描き終わるまで。値は `#info` の fetch と newPlot、50ms を超えるロングタスク、DOM、ヒープ、描かれた目盛りのラベルの数・隣と重なる数・「…」で切られた数）。1 回ごとに新しいページ、3 回の中央値［最小–最大］。fetch は `POST /api/plot` の往復（ワーカーの集約を含む）。

### Chrome（描画領域 1200×900）

| case | fetch ms | newPlot ms | long tasks max ms | DOM | heap MB | ticks（重なり、切れ） | 応答 |
|---|---|---|---|---|---|---|---|
| xcat-100 | 465 [424–700] | 26 [20–28] | 0 | 367 | 17 | 34（0、0） | 2KB |
| ycat-100 | 198 [164–591] | 49 [48–69] | 51 [50–72] | 411 | 19 | 50（0、0） | 2KB |
| box-100 | 347 [335–395] | 11 [11–15] | 0 | 367 | 19 | 34（0、0） | 13KB |
| xcat-420 | 418 [407–638] | 20 [20–24] | 0 | 355 | 19 | 28（0、0） | 5KB |
| ycat-420 | 183 [179–186] | 49 [47–49] | 50 [0–51] | 405 | 18 | 47（0、0） | 5KB |
| box-420 | 354 [324–365] | 11 [10–14] | 0 | 355 | 18 | 28（0、0） | 50KB |
| xcat-1000 | 450 [426–691] | 19 [18–21] | 0 | 357 | 19 | 29（0、0） | 9KB |
| ycat-1000 | 210 [209–302] | 49 [48–72] | 51 [0–74] | 411 | 19 | 50（0、0） | 9KB |
| box-1000 | 315 [280–375] | 12 [10–16] | 0 | 357 | 20 | 29（0、0） | 117KB |
| xcat-10000 | 543 [500–691] | 18 [16–19] | 0 | 347 | 19 | 24（0、0） | 79KB |
| ycat-10000 | 271 [256–280] | 51 [50–54] | 52 [52–56] | 413 | 19 | 51（0、0） | 79KB |
| box-10000 | 878 [835–883] | 9 [8–9] | 0 | 347 | 23 | 24（0、0） | 1.2MB |
| xcat-100000 | 1,154 [970–1,494] | 15 [15–16] | 0 | 341 | 21 | 21（0、0） | 0.9MB |
| ycat-100000 | 786 [766–798] | 55 [50–56] | 56 [52–58] | 413 | 22 | 51（0、45） | 0.9MB |
| box-100000 | 6,351 [6,292–7,014] | 10 [10–11] | 1,258 [1,254–1,420] | 341 | 27 | 21（0、0） | 11.7MB |
| xcat-1000000 | 7,333 [7,326–7,445] | 14 [13–16] | 83 [76–92] | 335 | 50 | 18（0、0） | 9.7MB |
| ycat-1000000 | 7,122 [7,025–7,257] | 48 [47–50] | 79 [74–81] | 413 | 56 | 51（0、50） | 9.7MB |
| box-1000000 | 27,467 [27,219–27,914] | 49 [48–50] | 1,096 [1,093–1,112] | 335 | 366 | 18（0、0） | 118MB |
| month-period | 404 [373–617] | 16 [15–17] | 0 | 347 | 19 | 18（0、0） | 14KB |
| month-box | 341 [328–373] | 7 [7–7] | 0 | 335 | 18 | 18（0、0） | 51KB |

- ズーム・パン（xcat-420、xcat-10000、xcat-1000000）：`Plotly.relayout` で帯 10〜19 に合わせると、10 本の目盛りに `L10`〜`L19` がすべて出るまで 0.014〜0.061 秒、続いて帯 110〜119 へのパンも 0.009〜0.060 秒。ロングタスクは無し。表示範囲の集約の結果を待たずに出る。
- 目盛り：水準数によらず 18〜51 本で、隣と重なるラベルは無い。X のラベルは水準の名前そのまま（`month` は 2 年おきの `1990-01`、`1992-01`…）。Y のラベルは左の余白（44px）で切れ、`L19607` のような 6 文字以上は「L196…」になる（ycat-100000、ycat-1000000 の「切れ」。`1990-01` も Y では切れる。左の余白は変えていない）。
- 変更前（1 の表）との比較：newPlot は 420 水準で 1,193 → 20ms、1,000 水準で 6,731 → 19ms、10,000 水準で 120 秒超（打ち切り）→ 18ms。DOM は 420 水準で 1,187 → 355。応答は全水準の目盛りの文字列が無くなり、xcat-1000000 で 22MB → 9.7MB。
- 残る重さ：箱ひげ図は箱の数（水準数）に比例する応答と集約で重い。100,000 水準で応答 11.7MB・fetch 6.4 秒・JSON の解釈とみられる 1.3 秒のロングタスク、1,000,000 水準で応答 118MB・fetch 27 秒・1.1 秒のロングタスク・ヒープ 366MB。点の 1,000,000 水準は fetch 7.3 秒（ワーカーの水準の並べ替えと応答の水準の名前。1 の「分かったこと」）。10,000 水準までは、点も箱ひげ図も 1 秒以内。

### WebView2（アプリの窓、描画領域 769×717）

| case | fetch ms | newPlot ms | long tasks max ms | DOM | heap MB | ticks（重なり） |
|---|---|---|---|---|---|---|
| xcat-100 | 448 [425–594] | 14 [12–14] | 0 | 340 | 24 | 20（0） |
| box-100 | 337 [334–337] | 7 [7–8] | 0 | 340 | 25 | 20（0） |
| xcat-420 | 465 [415–605] | 10 [10–11] | 0 | 336 | 35 | 18（0） |
| box-420 | 384 [354–386] | 9 [9–10] | 0 | 336 | 36 | 18（0） |
| xcat-10000 | 469 [465–670] | 9 [9–9] | 0 | 330 | 35 | 15（0） |
| box-10000 | 821 [820–877] | 6 [6–6] | 0 | 330 | 41 | 15（0） |
| month-period | 482 [420–615] | 10 [9–11] | 0 | 334 | 40 | 11（0） |
| month-box | 355 [307–359] | 7 [6–7] | 0 | 322 | 47 | 11（0） |

- ズーム・パン（xcat-420、xcat-10000）：帯 10〜19 の名前が 0.008〜0.014 秒で出た。
- 変更前の WebView2（1 の表、描画領域 771×719）の newPlot は、420 水準で 1,310ms、`month` で 1,369ms だった。10,000 水準は変更前は測れなかった（Chrome で描き終わらないため）。
- 100,000 水準以上は WebView2 では測っていない（Chrome で水準数によらない newPlot を確かめ、重さは箱ひげ図の応答とワーカーに移ったため）。

### 測れていない範囲（変更後）

- 100 万水準を超える列（上限で断る）。両軸カテゴリは、1 と同じく重なる点の集まりの上限（`MAX_PILES`）で 420 水準から断られる。
- 長い文字列の水準での間引き（E2E の 3 水準の長い水準と、`month` の 7 文字だけ）。
- Windows の表示スケール 150%・200% の WebView2。

## 再現

### 1. 変更前

`tmp/102-axis-levels/` に下のスクリプトを置き、次の順に実行した。スクリプトはコミット `aa54b91` の API（`create_app` の引数など）に合わせてある。

1. `uv run tmp/102-axis-levels/gen.py`
2. `uv run --with psutil --with httpx tmp/102-axis-levels/bench_api.py`（`--profile <ケース名>…` で cProfile。ワーカーを `prof_worker.py` に差し替える）
3. `uv run --with psutil --with httpx tmp/102-axis-levels/bench_page.py chrome`
4. WebView2 は `config/settings.toml` の `max_levels` を一時的に上げ、上の環境変数を付けて `uv run -m ddviz <d1m.parquet>` を起動してから、`bench_page.py webview2 9333 <ケース名>…` を実行する。

注意：

- `bench_page.py` の打ち切りには、120 秒の待ちに加えて 170 秒の見張りを付け、固まった Chrome のプロセスを止める。固まったページを閉じようとすると、Playwright が戻ってこないため。
- 別の ddviz（exe）の窓が開いていると、WebView2 のデータフォルダを取り合って起動に失敗する（0x8007139F）。

一時ファイルは作業後に削除した。

<details><summary>gen.py</summary>

```python
"""Synthetic data of Issue #102: categorical axis columns with 100 to 1,000,000 levels.
"""

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

OUT = Path(__file__).parent / "data"
SEED = 102
GROUP = 1_000_000  # row group size
LEVELS = [100, 101, 420, 1000, 10_000, 100_000, 1_000_000]


def uniform(rng, rows, n):
    """Each level the same number of rows (+-1), in random order."""
    return rng.permutation(np.arange(rows) % n)


def labels(n):
    return pl.Series([f"L{i}" for i in range(n)], dtype=pl.String)


def months():
    return pl.Series(
        [f"{y}-{m:02d}" for y in range(1990, 2025) for m in range(1, 13)], dtype=pl.String
    )


def write(frame, name, meta):
    path = OUT / name
    frame.write_parquet(path, compression="zstd", row_group_size=GROUP, statistics=True)
    meta[name] = {
        "rows": frame.height,
        "columns": {c: str(t) for c, t in frame.schema.items()},
        "bytes": path.stat().st_size,
    }
    print(name, meta[name]["bytes"], flush=True)


def main(which):
    OUT.mkdir(exist_ok=True)
    meta_path = OUT / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    rng = np.random.default_rng(SEED)
    if "1m" in which:
        rows = 1_000_000
        cols = {"x": rng.normal(size=rows), "y": rng.normal(size=rows)}
        frame = pl.DataFrame(cols)
        extra = {}
        for n in LEVELS:
            names = labels(n)
            xi, yi = uniform(rng, rows, n), uniform(rng, rows, n)
            extra[f"xc{n}"] = names.gather(xi)
            extra[f"yc{n}"] = names.gather(yi)
            meta[f"pairs{n}"] = int(np.unique(xi.astype(np.int64) * n + yi).size)
        for k in ("c10", "o10", "g10"):
            extra[k] = labels(10).gather(rng.integers(0, 10, rows))
        # Skewed 10,000 levels: every level once, the rest ~ u^4 (low indices crowded).
        rest = (10_000 * rng.random(rows - 10_000) ** 4).astype(np.int64)
        skew = rng.permutation(np.concatenate([np.arange(10_000), rest]))
        extra["sk10000"] = labels(10_000).gather(skew)
        counts = np.bincount(skew, minlength=10_000)
        meta["skew10000"] = {
            "max": int(counts.max()),
            "median": float(np.median(counts)),
            "min": int(counts.min()),
            "top1pct_share": float(np.sort(counts)[-100:].sum() / rows),
        }
        # Minimal example of the issue: period numeric, month 420 strings.
        mi = rng.integers(0, 420, rows)
        extra["month"] = months().gather(mi)
        extra["period"] = mi.astype(np.float64)
        write(frame.with_columns(**extra), "d1m.parquet", meta)
    if "10m" in which:
        rows = 10_000_000
        frame = pl.DataFrame({"x": rng.normal(size=rows), "y": rng.normal(size=rows)})
        frame = frame.with_columns(
            **{f"xc{n}": labels(n).gather(uniform(rng, rows, n)) for n in (100, 420, 10_000)}
        )
        write(frame, "d10m.parquet", meta)
    if "100m" in which:
        rows = 100_000_000
        frame = pl.DataFrame(
            {
                "x": rng.normal(size=rows).astype(np.float64),
                "y": rng.normal(size=rows).astype(np.float64),
                "xc420": labels(420).gather(uniform(rng, rows, 420)),
            }
        )
        write(frame, "d100m.parquet", meta)
    meta["seed"] = SEED
    meta["row_group"] = GROUP
    meta["compression"] = "zstd"
    meta["polars"] = pl.__version__
    meta_path.write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:] or ["1m", "10m", "100m"])
```

</details>

<details><summary>bench_api.py</summary>

```python
"""Worker benchmark of Issue #102: POST /api/plot on a fresh in-process server per run.

    uv run --with psutil --with httpx tmp/102-axis-levels/bench_api.py [group ...] [--profile]

Each run starts a new server (new workers, max_levels raised for every
case alike) on a shared column cache: the first run of a case is the
warm-up (it may convert columns), then 3 measured runs. A monitor thread
sums the RSS of this process tree; it kills the workers past 40% of the
physical memory or under 2GiB free. A request is given up after 120s.
"""

import json
import statistics
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import httpx
import psutil
import uvicorn

import ddviz.workers.runner as runner
from ddviz.server.app import create_app
from ddviz.server.settings import Settings

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "results"
TOKEN = "bench"
CAP = 2_000_000
TIMEOUT = 120.0
PHYS = psutil.virtual_memory().total
RSS_STOP = 0.4 * PHYS
FREE_STOP = 2 * 2**30
W, H = 1200, 900
PROFILE = "--profile" in sys.argv


def enc(x, y, elements=("points",), **singles):
    e = {"x": [x], "y": [y], "elements": list(elements)}
    e.update({r: singles.get(r) for r in ("color", "overlay", "row", "col", "wrap")})
    return e


def cases():
    """(group, family, name, file, encoding); a family stops at its first failure."""
    out = []
    for n in (100, 101, 420, 1000, 10_000, 100_000, 1_000_000):
        out += [
            ("basic", "xcat", f"xcat-{n}", "d1m", enc(f"xc{n}", "y")),
            ("basic", "ycat", f"ycat-{n}", "d1m", enc("x", f"xc{n}")),
            ("basic", "both", f"both-{n}", "d1m", enc(f"xc{n}", f"yc{n}")),
            ("basic", "box", f"box-{n}", "d1m", enc(f"xc{n}", "y", ("box",))),
        ]
    for n in (100, 420, 1000):
        out += [
            ("roles", "color", f"color-{n}", "d1m", enc("x", "y", color=f"xc{n}")),
            ("roles", "overlay", f"overlay-{n}", "d1m", enc("x", "y", overlay=f"xc{n}")),
            ("roles", "groupx", f"groupx-{n}", "d1m", enc("x", "y", col=f"xc{n}")),
        ]
    for n in (100, 420, 10_000):
        out.append(("rows", f"10m-{n}", f"xcat10m-{n}", "d10m", enc(f"xc{n}", "y")))
    out.append(("rows", "100m", "xcat100m-420", "d100m", enc("xc420", "y")))
    for n in (420, 10_000):
        out += [
            ("mix", "c", f"xcat-{n}+c10", "d1m", enc(f"xc{n}", "y", color="c10")),
            ("mix", "co", f"xcat-{n}+c10o10", "d1m", enc(f"xc{n}", "y", color="c10", overlay="o10")),
            ("mix", "g", f"xcat-{n}+gx10", "d1m", enc(f"xc{n}", "y", col="g10")),
        ]
    out.append(("mix", "skew", "xcat-skew10000", "d1m", enc("sk10000", "y")))
    out.append(("mix", "month", "month-period", "d1m", enc("month", "period")))
    out.append(("mix", "monthbox", "month-box", "d1m", enc("month", "y", ("box",))))
    return out


class Monitor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.me = psutil.Process()
        self.stop_flag = threading.Event()
        self.tree_peak = 0
        self.worker_peak = 0
        self.commit_peak = 0
        self.free_min = psutil.virtual_memory().available
        self.killed = None

    def run(self):
        while not self.stop_flag.is_set():
            try:
                kids = self.me.children(recursive=True)
                tree = self.me.memory_info().rss
                for k in kids:
                    try:
                        m = k.memory_info()
                    except psutil.Error:
                        continue
                    tree += m.rss
                    self.worker_peak = max(self.worker_peak, m.rss)
                    self.commit_peak = max(self.commit_peak, getattr(m, "private", 0))
                self.tree_peak = max(self.tree_peak, tree)
                free = psutil.virtual_memory().available
                self.free_min = min(self.free_min, free)
                if self.killed is None and (tree > RSS_STOP or free < FREE_STOP):
                    self.killed = "rss>40%" if tree > RSS_STOP else "free<2GiB"
                    for k in kids:
                        try:
                            k.kill()
                        except psutil.Error:
                            pass
            except psutil.Error:
                pass
            time.sleep(0.05)


def serve(file, cache, root):
    settings = Settings()
    settings = replace(settings, plot=replace(settings.plot, max_levels=CAP))
    app = create_app([str(DATA / f"{file}.parquet")], False, root, cache, settings, TOKEN)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        thread.join(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, f"http://127.0.0.1:{port}"


def one_run(file, encoding, tag):
    root = OUT / "run" / tag
    root.mkdir(parents=True, exist_ok=True)
    server, thread, url = serve(file, OUT / "cache", root)
    mon = Monitor()
    mon.start()
    rec = {}
    try:
        with httpx.Client(base_url=url, timeout=TIMEOUT) as client:
            client.get(f"/?token={TOKEN}")
            body = {"encoding": encoding, "width": W, "height": H}
            started = time.perf_counter()
            while True:
                left = TIMEOUT - (time.perf_counter() - started)
                if left <= 0:
                    raise httpx.TimeoutException("total")
                r = client.post("/api/plot", json=body, timeout=left)
                if r.status_code == 409 and "converting" in r.text:
                    time.sleep(0.3)
                    continue
                break
            rec["wall"] = time.perf_counter() - started
            rec["status"] = r.status_code
            rec["bytes"] = len(r.content)
            if r.status_code == 200:
                meta = r.json()["meta"]
                rec["task"] = meta.get("task_seconds")
                rec["convert"] = meta.get("convert_seconds")
                rec["rows"] = meta.get("rows")
                rec["panels"] = len(meta.get("panels", []))
                imgs = meta.get("images") or []
                rec["images"] = len(imgs) if isinstance(imgs, list) else imgs
                # Image files: sum their sizes.
                total = 0
                for p in Path(root).rglob("*.png"):
                    total += p.stat().st_size
                rec["png_bytes"] = total
            else:
                rec["error"] = r.text[:300]
    except httpx.TimeoutException:
        rec["status"] = "timeout"
    except httpx.HTTPError as exc:
        rec["status"] = f"http-error {type(exc).__name__}"
    finally:
        if mon.killed:
            rec["status"] = f"stopped {mon.killed}"
        mon.stop_flag.set()
        mon.join()
        server.should_exit = True
        thread.join(60)
    rec.update(
        tree_peak_gib=mon.tree_peak / 2**30,
        worker_peak_gib=mon.worker_peak / 2**30,
        commit_peak_gib=mon.commit_peak / 2**30,
        free_min_gib=mon.free_min / 2**30,
    )
    return rec


def ok(rec):
    return rec.get("status") == 200


def main():
    groups = [a for a in sys.argv[1:] if not a.startswith("--")]
    OUT.mkdir(exist_ok=True)
    log = OUT / ("profile.jsonl" if PROFILE else "api.jsonl")
    done = set()
    if log.exists():
        done = {json.loads(line)["name"] for line in log.read_text().splitlines()}
    if PROFILE:
        prof = HERE / "prof_worker.py"
        runner.worker_command = lambda: [sys.executable, str(prof)]
    failed = set()
    for group, family, name, file, encoding in cases():
        if groups and group not in groups and name not in groups:
            continue
        if name in done:
            continue
        result = {"group": group, "family": family, "name": name, "file": file}
        if (group, family) in failed:
            result["skipped"] = "lighter case of the family failed"
        else:
            if PROFILE:
                import os

                os.environ["BENCH_PROF"] = str(OUT / "prof" / f"{name}.prof")
                (OUT / "prof").mkdir(exist_ok=True)
                result["warm"] = one_run(file, encoding, f"{name}-p")
            else:
                warm = one_run(file, encoding, f"{name}-w")
                result["warm"] = warm
                runs = []
                if ok(warm):
                    for i in range(3):
                        runs.append(one_run(file, encoding, f"{name}-{i}"))
                        if not ok(runs[-1]):
                            break
                result["runs"] = runs
                good = [r for r in runs if ok(r)]
                if len(good) == 3:
                    for k in ("task", "wall", "worker_peak_gib", "commit_peak_gib"):
                        v = [r[k] for r in good]
                        result[k] = [statistics.median(v), min(v), max(v)]
                    result["bytes"] = good[0]["bytes"]
            if not ok(result["warm"]) or len(result.get("runs", [1, 1, 1])) < 3 or not all(
                ok(r) for r in result.get("runs", [])
            ):
                failed.add((group, family))
        with log.open("a") as f:
            f.write(json.dumps(result) + "\n")
        brief = {k: result.get(k) for k in ("task", "worker_peak_gib", "bytes", "skipped")}
        print(name, result["warm"].get("status") if "warm" in result else "-", brief, flush=True)


if __name__ == "__main__":
    main()
```

</details>

<details><summary>bench_page.py</summary>

```python
"""Page benchmark of Issue #102 in Chrome (in-process server) or WebView2 (the app window over CDP).

    uv run --with psutil --with httpx tmp/102-axis-levels/bench_page.py chrome [case ...]
    uv run --with psutil --with httpx tmp/102-axis-levels/bench_page.py webview2 <port> [case ...]

Chrome: a fresh page per run, 3 runs per case, stage 1200 x 900. The last
drop (or the last element click) of a case is the draw measured: the
page's own timings (#info), long tasks over 50ms from it, DOM nodes and JS
heap after it, and the tick labels drawn with their overlaps. For 420 and
10,000 levels it also zooms, hovers, selects and filters, and checks them.
"""

import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import polars as pl
from playwright.sync_api import Page, expect, sync_playwright

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "results"
TOKEN = "bench"
CAP = 2_000_000
WAIT = 120_000

LONG = """() => { window.__long = []; new PerformanceObserver((l) => {
  for (const e of l.getEntries()) window.__long.push(e.duration); }).observe({ type: "longtask", buffered: true }); }"""
SETTLED = """() => { const t = document.querySelector("#status").textContent;
  return (t.includes("行") && !t.includes("集約中")) || document.querySelector("#status").classList.contains("error") || t.includes("描けない"); }"""
IDLE = """() => !document.querySelector("#status").textContent.includes("集約中")"""
METRICS = """(axis) => {
  const info = JSON.parse(document.getElementById("info").textContent || "{}");
  const long = window.__long || [];
  const ticks = [...document.querySelectorAll(`#plot .${axis}tick text`)];
  const boxes = ticks.map((t) => t.getBoundingClientRect());
  let overlaps = 0;
  for (let i = 1; i < boxes.length; i++) {
    const a = boxes[i - 1], b = boxes[i];
    if (a.right > b.left && b.right > a.left && a.bottom > b.top && b.bottom > a.top) overlaps++;
  }
  const stage = document.getElementById("plot").getBoundingClientRect();
  return { info, long_n: long.length, long_ms: Math.round(long.reduce((s, d) => s + d, 0)),
    long_max: Math.round(Math.max(0, ...long)), dom: document.querySelectorAll("*").length,
    heap_mb: performance.memory ? performance.memory.usedJSHeapSize / 2 ** 20 : null,
    ticks: ticks.length, tick_overlaps: overlaps, first_ticks: ticks.slice(0, 3).map((t) => t.textContent),
    status: document.querySelector("#status").textContent.slice(0, 200),
    stage: [Math.round(stage.width), Math.round(stage.height)] };
}"""

# (name, file, [(column, role)], box) -- the last drop is the draw measured.
def cases():
    out = []
    for n in (100, 101, 420, 1000, 10_000, 100_000, 1_000_000):
        out += [
            (f"xcat-{n}", [("y", "y"), (f"xc{n}", "x")], False),
            (f"ycat-{n}", [("x", "x"), (f"xc{n}", "y")], False),
            (f"both-{n}", [(f"yc{n}", "y"), (f"xc{n}", "x")], False),
            (f"box-{n}", [("y", "y"), (f"xc{n}", "x")], True),
        ]
    for n in (100, 420, 1000):
        for role, name in (("color", "color"), ("overlay", "overlay"), ("col", "groupx")):
            out.append((f"{name}-{n}", [("x", "x"), ("y", "y"), (f"xc{n}", role)], False))
    for n in (420, 10_000):
        out.append((f"xcat-{n}+c10", [("y", "y"), ("c10", "color"), (f"xc{n}", "x")], False))
        out.append(
            (f"xcat-{n}+c10o10", [("y", "y"), ("c10", "color"), ("o10", "overlay"), (f"xc{n}", "x")], False)
        )
        out.append((f"xcat-{n}+gx10", [("y", "y"), ("g10", "col"), (f"xc{n}", "x")], False))
    out.append(("xcat-skew10000", [("y", "y"), ("sk10000", "x")], False))
    out.append(("month-period", [("period", "y"), ("month", "x")], False))
    out.append(("month-box", [("y", "y"), ("month", "x")], True))
    return out


def drop(page: Page, column: str, role: str) -> None:
    source = page.locator("#columns .column").filter(has=page.get_by_text(column, exact=True))
    zone = page.locator(f'.zone[data-role="{role}"]')
    source.drag_to(zone)
    expect(zone.locator(".chip-name")).to_have_text(column)


def settle(page: Page) -> float:
    started = time.perf_counter()
    page.wait_for_function(SETTLED, timeout=WAIT)
    return time.perf_counter() - started


def reset_long(page: Page) -> None:
    page.evaluate("() => { window.__long.length = 0; }")


def draw(page: Page, steps, box: bool) -> dict:
    page.wait_for_selector("#columns .column")
    for column, role in steps[:-1]:
        drop(page, column, role)
        page.wait_for_function(IDLE, timeout=WAIT)
    if box:
        drop(page, *steps[-1])
        settle(page)
        icons = page.locator("#elements .element")
        icons.nth(1).click()
        settle(page)
        reset_long(page)
        icons.nth(0).click()
    else:
        reset_long(page)
        drop(page, *steps[-1])
    rec = {"settle_s": settle(page)}
    page.wait_for_timeout(500)  # images decode, long tasks land
    axis = "y" if steps[-1][1] == "y" else "x"
    rec.update(page.evaluate(METRICS, axis))
    return rec


def checks(page: Page, n: int) -> dict:
    """Zoom, hover, select and filter on a drawn xcat-n; each answer checked against the data."""
    out = {}
    levels = [f"L{i}" for i in range(n)]
    frame = pl.read_parquet(DATA / "d1m.parquet", columns=[f"xc{n}", "y"])
    # Zoom to bands 10..19 by plotly's relayout, as a box zoom ends.
    reset_long(page)
    started = time.perf_counter()
    page.evaluate("() => Plotly.relayout(document.getElementById('plot'), {'xaxis.range': [9.5, 19.5]})")
    page.wait_for_function(
        "() => document.querySelector('#status').textContent.includes('表示範囲')",
        timeout=WAIT,
    )
    page.wait_for_function(IDLE, timeout=WAIT)
    page.wait_for_timeout(800)
    out["zoom_s"] = round(time.perf_counter() - started, 2)
    out["zoom"] = page.evaluate(METRICS, "x")
    page.screenshot(path=str(OUT / f"zoom-{n}.png"))
    # Hover the painted pixel nearest the plot's middle; its level must be the band under it.
    pixel = page.evaluate(
        """() => { let best = null;
        for (const c of document.querySelectorAll("#plot canvas, #layers canvas")) {
          if (!c.width) continue; const g = c.getContext("2d", { willReadFrequently: true }); if (!g) continue;
          const d = g.getImageData(0, 0, c.width, c.height).data; const r = c.getBoundingClientRect();
          const cx = c.width / 2, cy = c.height / 2, s = r.width / c.width;
          for (let i = 3; i < d.length; i += 4) { if (!d[i]) continue; const p = (i - 3) / 4;
            const x = p % c.width, y = Math.floor(p / c.width), e = (x - cx) ** 2 + (y - cy) ** 2;
            if (!best || e < best.e) best = { x: r.left + (x + 0.5) * s, y: r.top + (y + 0.5) * s, e }; } }
        return best; }"""
    )
    if pixel:
        page.mouse.move(pixel["x"], pixel["y"])
        label = page.locator("#hover-label")
        try:
            expect(label).to_be_visible(timeout=10_000)
            lines = dict(l.split(": ", 1) for l in label.inner_text().splitlines() if ": " in l)
            band = page.evaluate(
                """(px) => { const gd = document.getElementById("plot"); const xa = gd._fullLayout.xaxis;
                return Math.round(xa.p2l(px - gd.getBoundingClientRect().left - xa._offset)); }""",
                pixel["x"],
            )
            got = lines.get(f"xc{n}")
            out["hover"] = {"level": got, "band": band, "ok": got == levels[band] if 0 <= band < n else False}
            row = lines.get("行番号")
            if row is not None and got is not None:
                out["hover"]["row_ok"] = frame[f"xc{n}"][int(row)] == got
        except AssertionError:
            out["hover"] = "no label"
    else:
        out["hover"] = "no painted pixel"
    # Select bands 10..19 of the result drawn (API, as the box select sends it).
    expected = frame.filter(pl.col(f"xc{n}").is_in(levels[10:20]) & pl.col("y").is_finite()).height
    sel = page.evaluate(
        """async () => { const i = JSON.parse(document.getElementById("info").textContent);
        const task = window.__task ?? null; return null; }"""
    )
    task = page.evaluate("() => document.querySelector('#status').textContent.match(/task (\\d+)/)?.[1]")
    if task:
        sel = page.evaluate(
            """async (task) => { const r = await fetch("/api/selection", { method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ task: Number(task), panel: 0, x_range: [9.5, 19.5], y_range: [-1e9, 1e9] }) });
              return [r.status, await r.json()]; }""",
            task,
        )
        out["select"] = {"status": sel[0], "rows": sel[1].get("rows"), "expected": expected,
                         "ok": sel[1].get("rows") == expected, "task_s": sel[1].get("task_seconds")}
    # Filter to 50 levels: the rows, and how many bands the axis keeps.
    kept = levels[:50]
    expected = frame.filter(pl.col(f"xc{n}").is_in(kept)).height
    fil = page.evaluate(
        """async ([col, kept]) => { const r = await fetch("/api/plot", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ encoding: { x: [col], y: ["y"], elements: ["points"] }, width: 1200, height: 900,
            filters: [{ column: col, levels: kept }] }) });
          const t = await r.json(); if (r.status !== 200) return [r.status, t];
          return [r.status, { rows: t.meta.rows, ticks: (t.figure.layout.xaxis.tickvals || []).length,
            range: t.figure.layout.xaxis.range }]; }""",
        [f"xc{n}", kept],
    )
    out["filter"] = {"status": fil[0], **(fil[1] if isinstance(fil[1], dict) else {}), "expected_rows": expected}
    return out


def kill_chrome():
    """Kill the Chrome processes this script started (a renderer frozen by plotly blocks Playwright)."""
    import psutil

    for k in psutil.Process().children(recursive=True):
        try:
            if k.name().lower() == "chrome.exe":
                k.kill()
        except psutil.Error:
            pass


def chrome(names):
    import uvicorn

    from ddviz.server.app import create_app
    from ddviz.server.settings import Settings

    log = OUT / "chrome.jsonl"
    done = {json.loads(l)["name"] for l in log.read_text().splitlines()} if log.exists() else set()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--enable-precise-memory-info"])
        failed = set()
        for name, steps, box in cases():
            if (names and name not in names) or name in done:
                continue
            family = name.rsplit("-", 1)[0] if name.split("-")[-1].isdigit() else name
            if family in failed or ("10000" in name and "xcat" in failed):
                with log.open("a") as f:
                    f.write(json.dumps({"name": name, "skipped": "lighter case failed"}) + "\n")
                continue
            file = "d1m"
            settings = Settings()
            settings = replace(settings, plot=replace(settings.plot, max_levels=CAP))
            root = OUT / "page" / name
            root.mkdir(parents=True, exist_ok=True)
            app = create_app([str(DATA / f"{file}.parquet")], False, root, OUT / "cache", settings, TOKEN)
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            while not server.started:
                thread.join(0.05)
            url = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
            result = {"name": name, "runs": []}
            try:
                for i in range(3):
                    # Stage 1200 x 900: the page's chrome takes 495 x 105.
                    page = browser.new_page(viewport={"width": 1695, "height": 1005})
                    dog = threading.Timer(170, kill_chrome)
                    dog.start()
                    page.add_init_script(f"({LONG})()")
                    try:
                        page.goto(f"{url}/?token={TOKEN}")
                        rec = draw(page, steps, box)
                        if i == 0:
                            page.screenshot(path=str(OUT / f"draw-{name}.png"))
                        if i == 0 and name.split("-")[0] == "xcat" and name.split("-")[1] in ("420", "10000") and "+" not in name:
                            result["checks"] = checks(page, int(name.split("-")[1]))
                    except Exception as exc:  # noqa: BLE001
                        rec = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                    dog.cancel()
                    if "error" in rec:
                        kill_chrome()
                        try:
                            browser.close()
                        except Exception:  # noqa: BLE001
                            pass
                        browser = p.chromium.launch(channel="chrome", args=["--enable-precise-memory-info"])
                    else:
                        page.close()
                    result["runs"].append(rec)
                    if "error" in rec:
                        failed.add(family)
                        break
            finally:
                server.should_exit = True
                thread.join(60)
            with log.open("a") as f:
                f.write(json.dumps(result) + "\n")
            r0 = result["runs"][-1]
            print(name, r0.get("error") or {k: r0.get(k) for k in ("settle_s", "long_ms", "dom", "ticks", "tick_overlaps")}, flush=True)
        browser.close()


def webview2(port, names):
    log = OUT / "webview2.jsonl"
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        page = next(pg for c in browser.contexts for pg in c.pages if "127.0.0.1" in pg.url)
        page.evaluate(f"({LONG})()")
        url = page.url.split("/?")[0].rstrip("/")
        for name, steps, box in cases():
            if name not in names:
                continue
            result = {"name": name, "runs": []}
            for _ in range(3):
                page.goto(url + "/")
                page.evaluate(f"({LONG})()")
                try:
                    rec = draw(page, steps, box)
                except Exception as exc:  # noqa: BLE001
                    rec = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                result["runs"].append(rec)
                if "error" in rec:
                    break
            result["ua"] = page.evaluate("() => navigator.userAgent")
            with log.open("a") as f:
                f.write(json.dumps(result) + "\n")
            r0 = result["runs"][-1]
            print(name, r0.get("error") or {k: r0.get(k) for k in ("settle_s", "long_ms", "dom", "ticks", "stage")}, flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "chrome":
        chrome(sys.argv[2:])
    else:
        webview2(int(sys.argv[2]), sys.argv[3:])
```

</details>

<details><summary>prof_worker.py</summary>

```python
"""A worker under cProfile: dumps its stats to $BENCH_PROF when its task ends (killed standby workers dump nothing)."""

import cProfile
import os
import sys

from ddviz.workers.worker import main

profile = cProfile.Profile()
code = profile.runcall(main)
profile.dump_stats(os.environ["BENCH_PROF"])
sys.exit(code)
```

</details>


### 2. 変更後

`tmp/<task>/` に下の 3 つを置き（`bench_wv2_after.py` は `bench_page_after.py` を `bench_page` として読むので、同じフォルダに `bench_page.py` の名前で置く）、次の順に実行した。

1. `uv run tmp/<task>/gen_after.py`
2. `uv run --with psutil tmp/<task>/bench_page.py`（Chrome。ケース名を並べると、そのケースだけ）
3. `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333` を付けて `uv run -m ddviz tmp/<task>/data/d1m.parquet` を起動し、`uv run --with psutil tmp/<task>/bench_wv2.py 9333 xcat-100 box-100 xcat-420 box-420 xcat-10000 box-10000 month-period month-box`。終わったら、起動したアプリをその PID のプロセスツリーごと止める。

一時ファイルは作業後に削除した。

<details><summary>gen_after.py</summary>

```python
"""Synthetic data of Issue #102 (as the measurement's gen.py, seed 102): 1M rows with categorical axis columns."""

from pathlib import Path

import numpy as np
import polars as pl

OUT = Path(__file__).parent / "data"
rows = 1_000_000
rng = np.random.default_rng(102)
OUT.mkdir(exist_ok=True)
cols = {"x": rng.normal(size=rows), "y": rng.normal(size=rows)}
for n in (100, 420, 1000, 10_000, 100_000, 1_000_000):
    names = pl.Series([f"L{i}" for i in range(n)], dtype=pl.String)
    cols[f"xc{n}"] = names.gather(rng.permutation(np.arange(rows) % n))
months = pl.Series([f"{y}-{m:02d}" for y in range(1990, 2025) for m in range(1, 13)])
mi = rng.integers(0, 420, rows)
cols["month"] = months.gather(mi)
cols["period"] = mi.astype(np.float64)
pl.DataFrame(cols).write_parquet(OUT / "d1m.parquet", compression="zstd", row_group_size=rows)
print((OUT / "d1m.parquet").stat().st_size)
```

</details>

<details><summary>bench_page_after.py</summary>

```python
"""Page benchmark of Issue #102 after the change: Chrome, stage 1200 x 900, default settings.

    uv run --with psutil tmp/issue-102/bench_page.py [case ...]

A fresh page per run, 3 runs per case. The last drop (or the click that
takes the points off for box plots) is the draw measured: the page's own
timings (#info), long tasks over 50ms, DOM nodes and JS heap after it, the
tick labels drawn and their overlaps. xcat-420, xcat-10000 and
xcat-1000000 also zoom to bands 10..19 and pan to 110..119, and check the
labels and the time until they show.
"""

import json
import statistics
import sys
import threading
import time
from pathlib import Path

import psutil
import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

from ddviz.server.app import create_app
from ddviz.server.settings import Settings

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "results"
TOKEN = "bench"
WAIT = 120_000

LONG = """() => { window.__long = []; new PerformanceObserver((l) => {
  for (const e of l.getEntries()) window.__long.push(e.duration); }).observe({ type: "longtask", buffered: true }); }"""
SETTLED = """() => { const s = document.querySelector("#status"); const t = s.textContent;
  return (t.includes("行") && !t.includes("集約中")) || s.classList.contains("error") || t.includes("描けない"); }"""
IDLE = """() => !document.querySelector("#status").textContent.includes("集約中")"""
METRICS = """(axis) => {
  const info = JSON.parse(document.getElementById("info").textContent || "{}");
  const long = window.__long || [];
  const ticks = [...document.querySelectorAll(`#plot .${axis}tick text`)];
  const boxes = ticks.map((t) => t.getBoundingClientRect());
  let overlaps = 0;
  for (let i = 1; i < boxes.length; i++) {
    const a = boxes[i - 1], b = boxes[i];
    if (a.right > b.left && b.right > a.left && a.bottom > b.top && b.bottom > a.top) overlaps++;
  }
  const stage = document.getElementById("plot").getBoundingClientRect();
  return { info, long_n: long.length, long_ms: Math.round(long.reduce((s, d) => s + d, 0)),
    long_max: Math.round(Math.max(0, ...long)), dom: document.querySelectorAll("*").length,
    heap_mb: performance.memory ? performance.memory.usedJSHeapSize / 2 ** 20 : null,
    ticks: ticks.length, tick_overlaps: overlaps, cut: ticks.filter((t) => t.textContent.endsWith("…")).length,
    first_ticks: ticks.slice(0, 3).map((t) => t.textContent),
    status: document.querySelector("#status").textContent.slice(0, 200),
    stage: [Math.round(stage.width), Math.round(stage.height)] };
}"""
LABELS = """(names) => { const t = [...document.querySelectorAll("#plot .xtick text")].map((e) => e.textContent);
  return t.length === names.length && t.every((s, i) => s === names[i]); }"""


def cases():
    out = []
    for n in (100, 420, 1000, 10_000, 100_000, 1_000_000):
        out += [
            (f"xcat-{n}", [("y", "y"), (f"xc{n}", "x")], False),
            (f"ycat-{n}", [("x", "x"), (f"xc{n}", "y")], False),
            (f"box-{n}", [("y", "y"), (f"xc{n}", "x")], True),
        ]
    out.append(("month-period", [("period", "y"), ("month", "x")], False))
    out.append(("month-box", [("y", "y"), ("month", "x")], True))
    return out


def drop(page: Page, column: str, role: str) -> None:
    source = page.locator("#columns .column").filter(has=page.get_by_text(column, exact=True))
    zone = page.locator(f'.zone[data-role="{role}"]')
    source.drag_to(zone)
    expect(zone.locator(".chip-name")).to_have_text(column)


def settle(page: Page) -> float:
    started = time.perf_counter()
    page.wait_for_function(SETTLED, timeout=WAIT)
    return time.perf_counter() - started


def reset_long(page: Page) -> None:
    page.evaluate("() => { window.__long.length = 0; }")


def draw(page: Page, steps, box: bool) -> dict:
    page.wait_for_selector("#columns .column")
    for column, role in steps[:-1]:
        drop(page, column, role)
        page.wait_for_function(IDLE, timeout=WAIT)
    if box:
        drop(page, *steps[-1])
        settle(page)
        icons = page.locator("#elements .element")
        icons.nth(1).click()
        settle(page)
        reset_long(page)
        icons.nth(0).click()
    else:
        reset_long(page)
        drop(page, *steps[-1])
    rec = {"settle_s": settle(page)}
    page.wait_for_timeout(500)
    axis = "y" if steps[-1][1] == "y" else "x"
    rec.update(page.evaluate(METRICS, axis))
    return rec


def zoom(page: Page, n: int) -> dict:
    """Zoom to bands 10..19, then pan to 110..119; the labels each time, and the long tasks."""
    out = {}
    for name, rng, names in (
        ("zoom", [9.5, 19.5], [f"L{i}" for i in range(10, 20)]),
        ("pan", [109.5, 119.5], [f"L{i}" for i in range(110, 120)]),
    ):
        reset_long(page)
        started = time.perf_counter()
        page.evaluate(f"() => Plotly.relayout(document.getElementById('plot'), {{'xaxis.range': {rng}}})")
        page.wait_for_function(LABELS, arg=names, timeout=WAIT)
        labels_s = time.perf_counter() - started
        page.wait_for_function(IDLE, timeout=WAIT)
        page.wait_for_timeout(500)
        m = page.evaluate(METRICS, "x")
        out[name] = {"labels_s": round(labels_s, 3), "long_ms": m["long_ms"], "long_max": m["long_max"],
                     "ticks": m["ticks"], "status": m["status"], "view_react_ms": m["info"].get("view_react_ms")}
    return out


def kill_chrome():
    """Kill the Chrome processes this script started (children of this process, by PID)."""
    for k in psutil.Process().children(recursive=True):
        try:
            if k.name().lower() == "chrome.exe":
                k.kill()
        except psutil.Error:
            pass


def main(names):
    OUT.mkdir(exist_ok=True)
    log = OUT / "chrome.jsonl"
    done = {json.loads(line)["name"] for line in log.read_text().splitlines()} if log.exists() else set()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--enable-precise-memory-info"])
        print("chrome", browser.version, flush=True)
        for name, steps, box in cases():
            if (names and name not in names) or name in done:
                continue
            root = OUT / "page" / name
            root.mkdir(parents=True, exist_ok=True)
            app = create_app(
                [str(DATA / "d1m.parquet")], False, root, OUT / "cache", OUT / "history", Settings(), TOKEN
            )
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            while not server.started:
                thread.join(0.05)
            url = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
            result = {"name": name, "runs": []}
            try:
                for i in range(3):
                    page = browser.new_page(viewport={"width": 1695, "height": 1005})
                    dog = threading.Timer(170, kill_chrome)
                    dog.start()
                    page.add_init_script(f"({LONG})()")
                    try:
                        page.goto(f"{url}/?token={TOKEN}")
                        rec = draw(page, steps, box)
                        if i == 0:
                            page.screenshot(path=str(OUT / f"draw-{name}.png"))
                        if i == 0 and name in ("xcat-420", "xcat-10000", "xcat-1000000"):
                            result["zoom"] = zoom(page, int(name.split("-")[1]))
                            page.screenshot(path=str(OUT / f"zoom-{name}.png"))
                    except Exception as exc:  # noqa: BLE001
                        rec = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                    dog.cancel()
                    if "error" in rec:
                        kill_chrome()
                        try:
                            browser.close()
                        except Exception:  # noqa: BLE001
                            pass
                        browser = p.chromium.launch(channel="chrome", args=["--enable-precise-memory-info"])
                    else:
                        page.close()
                    result["runs"].append(rec)
                    if "error" in rec:
                        break
            finally:
                server.should_exit = True
                thread.join(60)
            good = [r for r in result["runs"] if "error" not in r]
            if len(good) == 3:
                for k in ("fetch_ms", "newPlot_ms", "figure_kb", "task_s"):
                    v = [r["info"].get(k) for r in good]
                    result[k] = [statistics.median(v), min(v), max(v)]
                for k in ("long_ms", "long_max", "dom", "heap_mb", "ticks", "tick_overlaps", "cut"):
                    v = [r[k] for r in good]
                    result[k] = [statistics.median(v), min(v), max(v)]
            with log.open("a") as f:
                f.write(json.dumps(result) + "\n")
            r0 = result["runs"][-1]
            brief = {k: result.get(k) for k in ("fetch_ms", "newPlot_ms", "long_ms", "ticks", "tick_overlaps", "cut", "figure_kb")}
            print(name, r0.get("error") or brief, result.get("zoom", ""), flush=True)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
```

</details>

<details><summary>bench_wv2_after.py</summary>

```python
"""WebView2 page benchmark of Issue #102 after the change: the app window over CDP, 3 runs a case.

    set WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333
    uv run -m ddviz tmp/issue-102/data/d1m.parquet
    uv run --with psutil tmp/issue-102/bench_wv2.py 9333 xcat-100 box-100 ...
"""

import json
import statistics
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from bench_page import LONG, OUT, cases, draw, zoom  # noqa: E402


def main(port, names):
    log = OUT / "webview2.jsonl"
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        page = next(pg for c in browser.contexts for pg in c.pages if "127.0.0.1" in pg.url)
        url = page.url.split("/?")[0].rstrip("/")
        ua = page.evaluate("() => navigator.userAgent")
        print(ua, flush=True)
        for name, steps, box in cases():
            if name not in names:
                continue
            result = {"name": name, "runs": [], "ua": ua}
            for i in range(3):
                page.goto(url + "/")
                page.evaluate(f"({LONG})()")
                try:
                    rec = draw(page, steps, box)
                    if i == 0 and name in ("xcat-420", "xcat-10000"):
                        result["zoom"] = zoom(page, int(name.split("-")[1]))
                except Exception as exc:  # noqa: BLE001
                    rec = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                result["runs"].append(rec)
                if "error" in rec:
                    break
            good = [r for r in result["runs"] if "error" not in r]
            if len(good) == 3:
                for k in ("fetch_ms", "newPlot_ms", "figure_kb"):
                    v = [r["info"].get(k) for r in good]
                    result[k] = [statistics.median(v), min(v), max(v)]
                for k in ("long_ms", "long_max", "dom", "heap_mb", "ticks", "tick_overlaps", "cut"):
                    v = [r[k] for r in good]
                    result[k] = [statistics.median(v), min(v), max(v)]
                result["stage"] = good[0]["stage"]
            with log.open("a") as f:
                f.write(json.dumps(result) + "\n")
            r0 = result["runs"][-1]
            brief = {k: result.get(k) for k in ("fetch_ms", "newPlot_ms", "long_ms", "ticks", "tick_overlaps", "stage")}
            print(name, r0.get("error") or brief, result.get("zoom", ""), flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2:])
```

</details>
