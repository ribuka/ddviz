# WebView2 の入っていない PC で使うとき（Windows Server 2016 など）

ddviz の zip には、WebView2 のランタイムは入っていません。`ddviz.exe` は、PC にインストールされた WebView2 のランタイム（Evergreen 版）を使います。Windows 11 と、更新の当たった Windows 10 には最初から入っているので、何もしなくてかまいません。

Windows Server 2016 など、WebView2 の入っていない PC では、管理者が WebView2 の固定版ランタイムを取り、`ddviz.exe` の横に置きます。`ddviz.exe` は、横に `webview2` のフォルダがあれば、インストール済みのランタイムより先にそれを使います。どちらも無いときは、起動時に入手方法をメッセージボックスで示して終了します。

## 固定版を置く

1. https://developer.microsoft.com/microsoft-edge/webview2/ の「Fixed Version」で、版と「x64」を選んで「Download」を押します。出てくる Microsoft の利用条件を読んで同意し、`.cab` を取ります。
   - 版は、Server 2016 で動く版を選びます（今は 156 系。ddviz のリポジトリの `docs/spec.md` の「未確認事項」の「Server 2016 で動く WebView2 固定版」を参照）。
2. 取った `.cab` を展開します（展開先のフォルダは先に作っておきます）。

   ```bat
   expand.exe <取った .cab> -F:* <展開先>
   ```

3. 展開先にできた `Microsoft.WebView2.FixedVersionRuntime.<版>.x64` のフォルダを、`webview2` という名前に変えて、`ddviz.exe` と同じフォルダに置きます。
4. 共有の場所に置いたときは、下の「共有の場所に置くとき」のとおり権限を付けます。
5. 固定版は、取った組織が Microsoft の利用条件に従って使います。固定版を組織の外へ配るときは、その組織が再配布者として Microsoft の条件に従います。

## 共有の場所に置くとき（Windows 10 系・Windows Server 2016）

Windows 10 系（Windows Server 2016 を含む）では、`webview2` のフォルダに、アプリのパッケージ（ALL APPLICATION PACKAGES と ALL RESTRICTED APPLICATION PACKAGES）の読み取りの権限が要ります。Windows 11 では要りません。

- 各ユーザーが自分のフォルダに展開して使うときは、何もしなくてかまいません。`ddviz.exe` が初回の起動で権限を付けます。
- 管理者が共有の場所（`C:\Program Files` など、一般ユーザーがアクセス許可を変えられない場所）に置くときは、置いた後に、管理者として開いたコマンド プロンプトか PowerShell で次を 1 回実行してください（パスは置いた場所に合わせます）。フォルダをコピーし直したときは、もう一度実行します。

```bat
icacls "C:\Program Files\ddviz\webview2" /grant "*S-1-15-2-2:(OI)(CI)(RX)" "*S-1-15-2-1:(OI)(CI)(RX)"
```

権限が無く、`ddviz.exe` からも付けられないときは、起動時にこのコマンド（実際のパス入り）をメッセージボックスで示して終了します。
