# iFont ツール（モックアップ）

**テキスト・音階・速度を入れると、字幕と音声再生が同期した動画（mp4）を出力する**コマンドラインツールと、
それを LLM から操作するための MCP サーバ。

論文「iFont: 視覚と聴覚の明瞭度を文字単位で対応づけるインクルーシブ字幕の枠組み」の中核アイデア
——各文字が、その文字の音が流れる区間の中で、文字単位の視聴覚対応（変換 g）に従って
徐々に鮮明化する（時間ゲート提示）——を、実際に動く形にしたものである。

> 本リポジトリの `g` は論文の想定結果版で用いた擬似データに基づくプレースホルダ（`ifont/gmodel.py`）。
> 実験で実データが得られたら、文字ごとの閾値テーブルに差し替える。

## インストール

```bash
cd ifont_tool
python -m pip install -e .            # CLI: ifont-render が入る
# 音声合成(TTS)を使う場合は VOICEVOX を別途起動（後述）。既定はトーン合成で不要。
# ffmpeg が必要（brew install ffmpeg など）。
```

## 使い方（CLI）

```bash
# 実験用: 一定音高(モノトーン)、毎秒5文字（0.2秒/文字）
ifont-render --text "ちはやふる" --pitch E4 --speed 5 --out out.mp4

# 実用: 1文字ごとに音高を設計(旋律)
ifont-render --text "ちはやふる" --pitch "B3,E4,G4,E4,C4" --speed 4 --out out.mp4

# 競技かるた風の音高上昇プリセット(1→2文字目で完全4度上げ)
ifont-render --text "ちはやふる" --pitch E4 --rise --out out.mp4
```

主なオプション:

| オプション | 意味 | 既定 |
|---|---|---|
| `--text` | 字幕・読み上げるテキスト | （必須） |
| `--pitch` | 音階名(E4, B3, A#4 …)/周波数[Hz]。**カンマ区切りで1文字ごとに指定可**(例 `B3,E4,G4`)。1つだけなら全文字に適用 | E4 |
| `--speed` | 1秒あたりの文字数（5=0.2秒/文字） | 5 |
| `--engine` | `tones`(自己完結) / `voicevox`(TTS, 要エンジン) | tones |
| `--rise` | 1→2文字目で音高を上げる（完全4度・競技かるた風プリセット） | オフ |
| `--out` | 出力mp4 | out.mp4 |

### 音高は1文字ごとに自由設計できる（設計上の根拠）

文脈のない単音の識別は、基本周波数(F0)の広い変動に頑健である（話者正規化）。したがって、
**一定音高（モノトーン）で測った文字単位の視聴覚対応 g は、音高を変えた実用提示にもそのまま生きる**。
そこで本ツールは、**実験は一定音高**（`--pitch E4` のように単一指定）で厳密に測り、
**実用（競技かるた等）は 1 文字ごとに音高を設計**（`--pitch "B3,E4,G4,…"`）できる設計とした。
極端に高い F0（概ね 350〜400Hz 超）はフォルマント弁別を粗くするため、常識的な音域に収めること。

生成例: [`examples/sample_monotone.mp4`](examples/sample_monotone.mp4)（一定音高）, [`examples/sample_melody.mp4`](examples/sample_melody.mp4)（旋律）

## MCP サーバ（LLM から操作）

```bash
python -m pip install -e ".[mcp]"
python mcp_server/server.py          # stdio で待受
```

MCP クライアント（Claude Desktop / Claude Code 等）に、このサーバを
`python /path/to/ifont_tool/mcp_server/server.py` として登録すると、
`render_inclusive_caption(text, pitch, speed, ...)` ツールが使える。

## 音声エンジン

- **tones（既定・自己完結）**: 音階=pitch のトーンを1文字ずつ鳴らす。エンジン不要で必ず動く。
- **voicevox（任意）**: ローカルの VOICEVOX エンジン（`http://127.0.0.1:50021`）に接続して TTS 合成する。
  エンジン本体は同梱しない（利用者が公式配布物を起動する）。

## ライセンス・帰属

- 本ツールのコード: MIT（`LICENSE`）。
- 字形: BIZ UDGothic（SIL OFL 1.1）。生成動画に字形が焼き込まれるのは OFL 上問題なく、動画の再配布に制限はない。
- 音声（VOICEVOX 使用時）: 話者ごとのクレジット（例「VOICEVOX:四国めたん」）と規約遵守が必要。
- 詳細は [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
