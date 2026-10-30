# 共有の場所に置くとき（Windows 10 系・Windows Server 2016）

Windows 10 系（Windows Server 2016 を含む）では、同梱の WebView2 のフォルダに、アプリのパッケージ（ALL APPLICATION PACKAGES と ALL RESTRICTED APPLICATION PACKAGES）の読み取りの権限が要ります。Windows 11 では要りません。

- 各ユーザーが自分のフォルダに展開して使うときは、何もしなくてかまいません。`ddviz.exe` が初回の起動で権限を付けます。
- 管理者が共有の場所（`C:\Program Files` など、一般ユーザーがアクセス許可を変えられない場所）に置くときは、置いた後に、管理者として開いたコマンド プロンプトか PowerShell で次を 1 回実行してください（パスは置いた場所に合わせます）。フォルダをコピーし直したときは、もう一度実行します。

```bat
icacls "C:\Program Files\ddviz\webview2" /grant "*S-1-15-2-2:(OI)(CI)(RX)" "*S-1-15-2-1:(OI)(CI)(RX)"
```

権限が無く、`ddviz.exe` からも付けられないときは、起動時にこのコマンド（実際のパス入り）をメッセージボックスで示して終了します。
