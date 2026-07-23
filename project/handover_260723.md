# iFont 開発の引き継ぎ（2026-07-23）

共同研究者（丸山さん）が **実験サイトの開発** と **CLIツールの開発** を自分で進められるようにするための、
セットアップ手順と現状の引き継ぎをまとめる。プロジェクトの全履歴は同じ `project/` フォルダの
[project_log_260723.md](project_log_260723.md) にある（Cosenseの全内容をMarkdown化したもの）。

---

## 0. このプロジェクトは何か（30秒）

競技かるたの読み上げのように、視覚（字幕）と聴覚（音声）で「同じ理解しやすさ」になる
インクルーシブ字幕を作る研究である。中核は、かな1文字ごとに「視覚の見分けやすさ」と
「聴覚の聞き取りやすさ」を測って対応づける変換 g である。成果物は次の3つに分かれる。

- **実験サイト**（`experiment/`）: クラウドソーシングで g を測るためのWebページ群。
  GitHub Pages で公開している。
- **CLIツール**（`ifont_tool/`）: テキストを入れると、字幕と音声が同期した動画（mp4）を
  出力するコマンドライン。論文で「iFont動画生成CLIツール」として言及している。
- **論文と資料**（ルートの `.docx`、`docs/`、この `project/`）。

---

## 1. 全体像とフォルダ構成

| 場所 | 中身 |
|---|---|
| `experiment/` | 実験サイト（HTML/JS）。本番課題・パイロット・出力サンプル・刺激データ |
| `experiment/tools/` | 刺激プールやサンプルの生成・検証スクリプト（Python） |
| `two_char_audio/` | 音声刺激プールのビルダー（`build_1char_pool.py` 等）。VOICEVOX を使う |
| `ifont_tool/` | CLIツール本体（`ifont` パッケージ）と MCP サーバ |
| `gas/code.gs` | 回答をGoogleスプレッドシートに保存するGoogle Apps Script |
| `docs/` | 設計メモ・事前登録ドラフト・セッション設計（Markdown） |
| `fonts/` | 同梱フォント（BIZ UD明朝/ゴシック等） |
| `project/` | 非コード資料（スライド・関連研究・図版・パイロット結果）とこの引き継ぎ |
| ルートの `.docx` | 論文草稿（`iFont論文草稿_想定結果版_….docx`）と関連研究の草稿 |

**GitHubリポジトリは公開（PUBLIC）である**。倫理審査書類・参考資料など氏名や未公表内容を含む
ファイルは **git に入れていない**。それらは Google Drive の共有フォルダ
（この作業フォルダ `share/google_desktop_share/iFont`）にあり、Drive の共有で受け渡す。
公開リポジトリに個人情報や未公表資料を push しないよう注意すること。

---

## 2. 開発環境のセットアップ

### 2.1 前提ソフト（macОS想定・Homebrew）

```bash
# ffmpeg（動画・音声の変換に必須）
brew install ffmpeg
# LibreOffice（docx→PDF変換で使用。論文編集の確認に）
brew install --cask libreoffice
# Node.js（実験JSの構文チェック node --check に使う。任意）
brew install node
# git は Xcode Command Line Tools 等で入っている前提
```

### 2.2 Python 環境

現在このMacでは、Google Drive の外（`~/Desktop/claude_work/ifont_env/`）に2つの仮想環境を置いている
（Drive上だと動作が不安定なため外に退避している）。丸山さんの環境では、下記のパッケージを入れた
仮想環境を1つ作れば足りる（分ける必要はない）。

```bash
python3 -m venv ~/ifont_env           # 置き場所は任意。Drive の外を推奨
source ~/ifont_env/bin/activate
pip install numpy praat-parselmouth Pillow python-docx pymupdf pikepdf
```

- `numpy` / `praat-parselmouth`: 音声のF0・音量などの解析（刺激プールの品質管理、サンプルの検証）
- `Pillow`: 動画フレームの描画（CLIツール、サンプル動画）
- `python-docx` / `pymupdf` / `pikepdf`: 論文docxの編集・PDF化・確認（必須ではない）

参考: 現在のこのMacの構成は `bigram_venv`（numpy/parselmouth）と `root_venv`（Pillow/docx）に
分かれているが、上記のように1つにまとめてよい。

### 2.3 VOICEVOX（音声合成エンジン）

実声の音声合成（刺激プールの再生成、CLIツールの `--engine voicevox`、かるたサンプル）に必要。
既定のトーン合成だけなら不要。

1. VOICEVOX 公式（https://voicevox.hiro-sabo.com/）から macOS 版アプリを入れて起動する。
   起動するとローカルに合成サーバが立つ（`http://localhost:50021`）。
2. 疎通確認:
   ```bash
   curl http://localhost:50021/version
   ```
3. 本プロジェクトの本番話者は **東北きりたん（speaker=108）・音高B3**。
   （全127スタイルを実測して選定した。詳細は project_log の話者選定の節）

> このMacでは `~/Desktop/claude_work/ifont_env/voicevox_setup/macos-arm64/run` にエンジン本体を
> 置いてコマンド起動しているが、丸山さんは公式アプリを起動する方式で問題ない。

### 2.4 フォント

CLIツールの動画は同梱の `fonts/BIZUDGothic-Regular.ttf` / `BIZUDMincho-Regular.ttf` を使う（追加インストール不要）。
音声解析・サンプル生成の一部で macOS 標準の「ヒラギノ明朝 ProN」「ヒラギノ角ゴシック W3」を使う箇所がある
（macOSなら標準で入っている）。

---

## 3. 実験サイトの開発

### 3.1 構成と主要ページ

実験サイトは素の HTML+JS（フレームワークなし）。刺激データ（音声mp3・正解表・マニフェスト）を
fetch して動く。主要ページ:

- 本番課題: `experiment/audio1char.html`（聴覚1文字）, `visual1char.html`（視覚1文字）,
  `audio2char.html`（聴覚2文字）
- 乙課題（干渉判定）: `experiment/pilot_soa_audio.html`, `pilot_soa_visual2.html`
- 出力サンプル: `experiment/ifont_sample.html`（実声・かるた読み・動画埋め込み）

各ページの本番モードは URL に `?prod=1` を付けたとき（同意画面→課題→GAS保存→完了コード）。
`?prod` なしは研究者パイロット（サーバ未接続・記録なし）。共通配管は `experiment/prod_common.js`。

### 3.2 ローカルでの動作確認

fetch を使うので `file://` では動かない。ローカルサーバを立てて開く:

```bash
cd experiment
python3 -m http.server 8000
# ブラウザで http://localhost:8000/audio1char.html などを開く
```

乙課題の聴覚ページは正解表 `answer_key_merged.json`（git管理）を読む。
点検モードは URL 末尾に `?check=1`（本試行を消費せず刺激だけ確認できる）。

### 3.3 GitHub Pages への公開

**このリポジトリの `main` ブランチが GitHub Pages のソース**になっている。
`main` に push すれば数十秒〜数分で https://qurihara.github.io/iFont/ 配下に反映される。

```bash
git add experiment/audio1char.js          # 変更したファイルを個別に指定（下の注意参照）
git commit -m "説明"
git push origin main
# 反映確認（200が返る）
curl -s -o /dev/null -w "%{http_code}\n" https://qurihara.github.io/iFont/experiment/audio1char.html
```

### 3.4 刺激プール（音声mp3）の再生成

音声刺激は VOICEVOX から生成する。話者や音高、品質管理（VOT修正・ぱ行処方・音量均一化）は
`two_char_audio/build_1char_pool.py`（単音68字）と `build_2char_pool.py`（2文字）に焼き込んである。

```bash
# VOICEVOX を起動してから
python two_char_audio/build_1char_pool.py            # 単音プール（きりたんB3）を再生成
python experiment/tools/build_onsets.py              # 音響的開始位置・ゲインの再計測
```

- ハッシュ名は内容非依存なので、同じ設定なら同名で上書きされ、正解表もそのまま使える。
- 正解表は `experiment/answer_key_merged.json`（git管理・話者ID込みハッシュで多プール同居）。
  プール別の `answer_key_1char.json` / `answer_key_2char.json` は `.gitignore` で非公開。

### 3.5 回答の保存（GAS）

本番（`?prod=1`）の回答は `gas/code.gs` を Google Apps Script として配置し、ウェブアプリとして
デプロイして得た URL を各ページの `SUBMIT_URL` に貼ると保存される。手順は
`experiment/PRODUCTION.md` にある。**このデプロイは栗原さんのGoogleアカウント操作が要る。**

---

## 4. CLIツール（ifont_tool）の開発

### 4.1 インストールと基本

```bash
cd ifont_tool
pip install -e .          # ifont-render コマンドが入る
```

テキスト・音高・速度を入れると、字幕（時間ゲート提示＝画面中央の固定領域に1文字ずつ、
その音の区間で徐々に鮮明化）と音声が同期した mp4 を出力する。

```bash
# 自己完結のトーン合成（VOICEVOX不要）
ifont-render --text "ちはやふる" --pitch E4 --speed 5 --out out.mp4

# 実声（VOICEVOX起動下・東北きりたん）。表示字と読みを分け、句頭B3ほかE4
ifont-render --engine voicevox --speaker 108 \
  --text "はるすぎてなつきにけらししろたえの" \
  --pitch "B3,E4,E4,E4,E4,B3,..." --out kamiku.mp4
```

主なオプション: `--reading`（表示字と音を1対1で分離。は→ワ 等）, `--durations`（1モーラごとの
長さ＝伸ばし・余韻）, `--pause-after`（間合いの無音）, `--natural`（自然韻律）, `--speaker`,
`--label`。詳細は `ifont_tool/README.md` とヘルプ `ifont-render -h`。

### 4.2 モジュール構成

- `ifont/audio.py`: 音声合成（トーン / VOICEVOX設計提示=モーラ長・音高固定 / 自然韻律 / 無音挿入）
- `ifont/render.py`: フレーム描画（`render_frames_gated` = 時間ゲート提示）
- `ifont/cli.py`: コマンドライン。`build()` が本体
- `ifont/gmodel.py`: 変換 g のプレースホルダ（実データが出たら差し替え）
- `mcp_server/server.py`: LLM から操作する MCP サーバ（任意）

### 4.3 かるた読みサンプルの再生成

競技かるた公式ルール（5・3・1・6方式・大山札）に沿ったサンプル動画は、再現可能な
`experiment/tools/build_karuta_samples.py` で生成する（下の句と上の句を別合成して間合いで連結、
伸ばし・余韻・F0補正・強制有声化・音量平滑化を含む）。VOICEVOX 起動下で:

```bash
python experiment/tools/build_karuta_samples.py            # サンプル2本を再生成
python experiment/tools/build_karuta_samples.py --check    # 音響指標の自己測定
```

---

## 5. リポジトリ運用の注意

- **Google Drive（DriveFS）越しなので、`git status` のような全走査は非常に遅い**。
  `git add` は対象パスを個別に指定し、ログや特定ファイルの読み書きは問題なく速い。
  巨大な未使用フォルダ（旧 `stroke_mask_images/`）は `.gitignore` 済み。
- **公開リポジトリなので、個人情報・未公表資料を push しない**。倫理審査書類・参考資料は
  Drive 共有で受け渡す（git には入れない方針）。
- コミットメッセージは日本語で、何を・なぜ変えたかを書く運用。

---

## 6. 現状の到達点（2026-07-23）

- **話者・刺激は確定・凍結**。東北きりたん（108）・B3、ぱ行の字ごと処方、VOT修正、音量均一化まで
  焼き込み済み。単音68字・2文字5184対のプールを本番化してデプロイ済み。
- **乙課題（干渉判定）の設計が確定**。二段階の非劣性判定（第一段 聴覚60名・視覚40名・δ=8pt、
  保留時のみ 130/80 へ増員・δ=5pt、各段片側2.5%）。事前登録ドラフト `docs/prereg_interference.md`、
  セッション設計・予算 `docs/session_design.md`（総額10万円）。
- **パイロットは研究者2名で干渉なしの方向**（合算で頭打ち70.8% vs S=200も70.8%、差0.0pt）。
- **出力サンプルとCLIツール**を実声・時間ゲート提示に拡張し、クイズ・百人一首・かるた公式ルール
  （5・3・1・6・大山札）のサンプル動画をサイトに公開済み。
- **論文**（想定結果版 docx）は変更履歴で、話者選定・刺激品質管理・非劣性の枠組み（δの正当化・
  Lakens/CONSORT引用）・二段階判定・表2の予算・図5/図10を反映済み。

---

## 7. 次にやること（引き継ぎ時点で未着手・PI判断待ち）

**本番前の実装課題:**
1. frac課題への乙式改善（クリック開始・教示・出題の配り方）の移植。
2. 視覚課題の実測タイミング記録（`actual_soa` 等）を `visual1char` にも入れ、GAS保存
   （`gas/code.gs` の soa_trials シート）に `actual_*` と `env` の列を追加する
   （現状は本番保存でこれらが列挙漏れで捨てられている）。
3. 品質処方（VOT・DSP・音量均一化）の「連続合成」への移植と検証（文章スケールの音声。
   2026-07-21の検証で最重要の残課題と判定。VOICEVOXは決定論的なので「測って補正」する工程になる）。
4. frac課題の本番化（`prod_common.js` を流用）。GASデプロイ（栗原）。

**PIの判断待ち:**
- 視覚1文字の提示アルゴリズムを1種に確定（仮置き fade）。
- 論文の残る細部（図4のベースライン点・旧表2の空行骨格・図番号の出現順。最終の変更履歴受理は
  MS Word で行う）。
- 倫理審査の承認（本実験の開始ゲート）。

**分担の慣行（記録として）:** 分析・統括は上位の推論、実装は実装向けのモデル/エージェントで、
という運用をしてきた。丸山さんの環境では自由に決めてよい。
