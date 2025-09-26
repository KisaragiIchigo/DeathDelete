# DeathDelete

指定したファイル／フォルダを自動で削除できるツールです。
パスワード認証や放置タイマーを備え、意図したタイミングで安全に「消す」を実行します。
## Download

[https://github.com/KisaragiIchigo/DeathDelete/releases/tag/v0.1.0]


---

## 特長

* **ドラッグ＆ドロップで削除対象を登録**：`delset.exe` にファイル／フォルダを投げ込むだけでリスト化（暗号化保存）。
* **パスワード認証付き**：`MainApp.exe` 起動時にパスワード必須。**3回失敗で強制削除**を実行。
* **放置タイマー**：**72時間（3日）放置**でも自動的に削除を実行し、リスクを最小化。
* **暗号化による安全性**：

  * 削除リスト `yummy.ini` は `secret.key` で暗号化
  * 移動先フォルダ情報は `yummy_target.enc` に \*\*DPAPI（端末＆ユーザー紐づけ）\*\*で暗号化保存
* **タスク自動登録**：バッチを**管理者実行**すれば、ログオン時と3日ごとに `MainApp.exe` を自動起動。
* **運用に合わせた分離**：`MainApp.exe`（認証/制御）と `DeleteApp.exe`（実削除）を別配置OK。`DeleteApp.exe` のパスは GUI で指定可能。

---

## 基本操作

1. **`setup.exe` を起動**
   画面のボタンを上から順に押すだけで進められます。
2. **① パスワード設定**
   入力→内部でハッシュ化→環境変数 `PASSWORD_HASH` に登録。
   ※新しいターミナルを開き直すと反映されます。
3. **② 暗号鍵を生成（`encryption_key.exe`）**
   `secret.key` を作成。**これがないと `yummy.ini` を読み書きできません。**
4. **②.5 ファイル移動**
   `MainApp.exe` / `DeleteApp.exe` / `secret.key` を**任意のフォルダへ移動（コピーではなく移動）**。
   同時に、**`yummy_target.enc` が `delset.exe` と同じフォルダ**に作られ、移動先パスを暗号化記録します。
5. **③ 削除対象の作成（`delset.exe`）**
   画面にドラッグ＆ドロップで対象を追加。**「設定終了」**で `yummy.ini`（暗号化）が**移動先**に保存されます。
   `DeleteApp.exe` のパスもここで指定可（隠し場所推奨）。
6. **⑤ バッチ生成 → タスク登録**
   バッチを**管理者として実行**すると、タスクスケジューラに
   `MainApp_OnLogon_Task`（ログオン時）/ `MainApp_Recurring_Task`（3日ごと）が登録されます。

---

## 注意事項

* **`secret.key` は超重要**：紛失すると既存の `yummy.ini` を復号できません（再生成すると別鍵になります）。
* **`yummy_target.enc` は PC/ユーザーに依存**：他PCへ持ち出しても復号できません。新環境では②.5 をやり直してください。
* **バッチの実行は管理者権限で**：タスク登録が失敗する場合は管理者で再実行。
* **テスト推奨**：本番前にテスト用フォルダで3回誤パス→強制削除の挙動を確認してください。

---

## ファイル構成

```
DeathDelete/
├─ setup.exe                # セットアップGUI（①②②.5③⑤の進行）
├─ encryption_key.exe       # 暗号鍵 secret.key を作る
├─ delset.exe               # 削除対象の設定GUI（DnD対応）
├─ yummy_target.enc         # delset と同じ場所。移動先フォルダをDPAPIで暗号化保存
└─ (あなたが選んだ移動先フォルダ)/
   ├─ MainApp.exe           # 認証と全体制御（ログオン/3日ごとに起動）
   ├─ DeleteApp.exe         # 実削除の実行本体
   ├─ secret.key            # yummy.ini の暗号鍵（厳重保管）
   └─ yummy.ini             # 削除リスト（暗号化保存）
```

---

## ライセンス

MIT License ©️ 2025 KisaragiIchigo
