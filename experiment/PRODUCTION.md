# 乙課題(較正)の本番化 — デプロイ手順

聴覚・視覚の乙課題を、クラウドソーシング(Yahoo!クラウドソーシング等)で実施できる本番仕様にした。
`?prod=1` を付けたときだけ「本番モード」になり、同意画面・各試行のサーバ保存・完了コードが有効になる。
`?prod` が無ければ従来どおり研究者パイロット(ローカルDL)として動く。

## 本番URL(デプロイ後)

- 聴覚乙: `.../experiment/pilot_soa_audio.html?prod=1&wid=<作業者ID>`
- 視覚乙: `.../experiment/pilot_soa_visual2.html?prod=1&wid=<作業者ID>`

`wid`(または `worker_id`)は各プラットフォームが受け渡す作業者IDのパラメータに合わせる。
点検モード(`?check=1`)や候補プール(`?pool=`)は本番モードと排他(点検が優先)。

## セットアップ(一度だけ)

1. **Googleスプレッドシートを作る**。URLからシートIDを控える。
2. スプレッドシートの「拡張機能 → Apps Script」に `gas/code.gs` を貼る。
3. 「プロジェクトの設定 → スクリプト プロパティ」に登録:
   - `SPREADSHEET_ID` = 上のシートID
   - `ANSWER_KEY` = `experiment/answer_key_merged.json` の全文
     (乙課題は正答をクライアントが送るため必須ではないが、frac系と共用のため貼っておく)
4. 「デプロイ → 新しいデプロイ → ウェブアプリ」:
   - 実行者: 自分 / アクセスできるユーザー: 全員
   - 発行された `/exec` URL を控える。
5. `experiment/prod_common.js` の `const SUBMIT_URL = ""` にその `/exec` URL を貼る。
   (空のままだと本番モードの画面は出るが送信はスキップする。ローカル確認用。)
6. コミットして GitHub Pages に反映。

## 保存されるデータ

- `soa_trials` シート: 1試行1行。`task`(soa_audio/soa_visual)・`S`・`c1/c2/c3`・`resp1/resp2`・
  `correct1/correct2`・`participant_id`・`worker_id`・`completion_code`・`version`・`speaker`。
- `soa_sessions` シート: セッション完了1行。集計値(byLevel)・所要秒・完了コード。
- frac系(audio1char等)の従来のper-trial保存(`trials`シート)はそのまま共存する。

## 未確定(統括判断が要る。実装はこの配管に定数を差し込むだけ)

- **セッション設計と予算**: 1人あたりの試行数(現状 各水準6問=42問)、必要人数、10万円枠での配分。
  `PER_LEVEL` と募集人数で決まる。→ 実験計画として別途決定。
- **干渉判定の事前登録ルール**: S=200 vs 頭打ち(450/700)の閾値・信頼区間・必要N。
- frac課題(聴覚1文字/2文字・視覚1文字)の本番化は次段(Stage 2)。
