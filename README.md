# インクルーシブ字幕用 — ひらがな ストロークランダムピクセルマスキング画像

「字幕の表示パラメータ p% ≈ 視覚的認識確率 p%」を目指す研究の刺激素材。
各ひらがな1文字について、フォントのストローク画素から p% をランダムに選んで表示した PNG を生成する。

## 文字セット (84字)

- 清音 46字
- 濁音 20字 (が…ぼ)
- 半濁音 5字 (ぱ…ぽ)
- 小書き 10字 (ぁぃぅぇぉっゃゅょゎ)
- 古語 2字 (ゐゑ)
- その他 1字 (ゔ)

## フォント

`fonts/MPLUSRounded1c-Regular.ttf`
M PLUS Rounded 1c Regular — SIL Open Font License 1.1
出典: https://github.com/coz-m/MPLUS_FONTS

## 画像仕様

- 256 × 256 px, グレースケール PNG
- 背景 白 (255), 文字 黒 (0)
- フォントサイズ 200 px
- ストローク判定: 輝度 ≤ 128

## マスキング手法

1. 各文字を一度ビットマップ化し、輝度≤128 の画素を「ストローク画素」として抽出 (N画素)
2. `random.Random(seed=f"stroke-mask:{文字}")` で N画素を完全ランダムに並べ替え
3. p ∈ [0,100] について、先頭から `round(N * p / 100)` 画素のみを黒で描画
4. 各 p は累積的に画素が増える ⇒ 同じ文字の p% と (p+1)% は monotonic

文字ごとに 1 度シャッフルすることで、p の昇順で段階的に「明瞭になっていくアニメーション」として再生可能。
seed が文字依存で固定なので、同じファイルは何度生成しても同一。

## 出力

```
stroke_mask_images/
├── trial/   (6字 × 7段階 = 42枚, 動作確認用)
└── full/    (84字 × 101段階 = 8,484枚)
        ├── あ/p000.png ... p100.png
        ├── ...
        └── ゔ/
```

各文字のストローク画素数 N は `stroke_counts.csv` に記録。

## 再生成

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install Pillow numpy
.venv/bin/python generate.py
```

生成時間: 約15秒 (M シリーズ Mac で実測)。

## 想定する次ステップ

- 視覚版 Kikiwake で「p% 表示 → 認識率」曲線を実測
- 音声側 Kikiwake のμ,σ (または ECDF) と対応付けて字幕フェードイン関数 f(t) を設計
- 文字間ストローク画素数 N の差分 (`stroke_counts.csv`) を等面積化する拡張

---

# 視覚版 Kikiwake 実験 (減算 F1, BIZ UDGothic)

`experiment/` 配下に jsPsych 製の実験ページ、`gas/` に Google Apps Script スニペット、
ルートに刺激生成スクリプト (`make_subtractive_stills.py`, `build_stimulus_pool.py`) を配置。

## 刺激プール再生成

1. `make_subtractive_stills.py` の冒頭で `FONT_TAG` を選ぶ (デフォルト `bizudgothic`)。
2. F1 静止画を 11×84=924 枚生成:
   ```bash
   .venv/bin/python make_subtractive_stills.py
   ```
   → `subtractive_stills_<FONT_TAG>/r000-r100/<char>.png`
3. ハッシュ化 + manifest 生成 (`SECRET_SALT` は秘匿):
   ```bash
   .venv/bin/python build_stimulus_pool.py --salt "<your-secret>"
   ```
   → `experiment/stimuli/<hash>.png` × 924, `experiment/manifest.json`, `answer_key.json`

`answer_key.json` は `.gitignore` 済み (リポジトリに含めない)。
別フォントに差し替える際は `FONT_TAG` を変更して再ビルド (ハッシュも変わるので過去データと混ざらない)。

## バックエンド (Google Apps Script)

`gas/code.gs` をスクリプトエディタに貼り付け、Script Properties に以下を設定:
- `SPREADSHEET_ID`: 結果保存用 Google Sheet の ID
- `ANSWER_KEY`: 生成した `answer_key.json` の中身を貼り付け

「Deploy → New deployment → Web app (Anyone)」で `/exec` URL を取得し、
`experiment/experiment.js` 冒頭の `SUBMIT_URL` に設定。

## GitHub Pages デプロイ

リポジトリの Settings → Pages で:
- Source: Deploy from a branch
- Branch: `main` / Folder: `/ (root)`

公開後、実験URL は:
```
https://qurihara.github.io/iFont/experiment/?worker_id={WORKER_ID}
```
Yahoo!クラウドソーシング側で `{WORKER_ID}` を埋め込む形にする。

## ローカル動作確認

```bash
.venv/bin/python -m http.server 8765 --directory experiment
# → http://localhost:8765/?worker_id=test
```
SUBMIT_URL が空のままだと送信スキップ (コンソールに warn なし)。
