# 別セッション・別PCでの再開手引き (2026-07-03 時点)

このプロジェクトを別のセッションや別のPCで続けるための手引き。とくに「コードやデータを再生成する必要があるか」に答える。

## まず結論（別PCで再開する場合）

- **コードは再生成しない。** すべてGitHub（qurihara/iFont, branch main）にあり、`git clone` で揃う。
- **コミット済みのデータも、そのまま clone で手に入る。** 具体的には、視覚の文字画像（experiment/base/）、聴覚2文字の刺激 experiment/audio2char_stimuli/（5,184個）と audio1char_stimuli/（72個）、それぞれの公開 manifest、bigram のコーパス（Tatoeba の bz2）などである。実験ページを見るだけなら、clone して experiment/ を静的配信すれば動く。
- **別PCで作り直す必要があるのは、次の3種類だけ。**
  1. Python の仮想環境とパッケージ（環境なので毎回作り直す）。
  2. VOICEVOX の合成エンジン本体（約1.8GB。音声を作り直すときだけ再入手）。
  3. Git 管理外にしている派生ファイル（answer_key、features.pkl、freq.pkl、E4版1文字プール、流暢性デモの音声など）。これらはスクリプトを実行すれば作り直せる。
- **重要**: いまコミットされている聴覚の刺激プールは、は・へ を助詞として誤って合成した**古い状態**で、しかも開発用の salt で作られている。**実験の前に、修正済みの生成器で作り直す必要がある**（下記「再生成が必要なもの」参照）。どのPCで作業するかに関わらず、これは必要な手順である。

## 置き場所

- 作業ディレクトリ: `/Users/kurihara/Dropbox/dev/inclusive_subtitle/インクルーシブ字幕作成`（別PCでは clone 先）。
- GitHub: https://github.com/qurihara/iFont （branch main、push 可）。
- ハブ: Cosense https://scrapbox.io/qurihara/iFont （読み書きは MCP の cosense-qurihara）。
- Kikiwake 資産（百人一首の読みなど、別リポジトリ）: このマシンでは `/Users/kurihara/Dropbox/dev/Kikiwake-tmp`。百人一首上句の現代かなは `Kikiwake-tmp/mfa_v3/modern_kana_kamigoku.json`。別PCには無いので、bigram 調査など Kikiwake を使う作業をするなら、このリポジトリも用意する。

## 環境の作り直し

- macOS Apple Silicon、Homebrew の Python 3.12 を想定。
- 仮想環境は2つある。
  - `.venv`（Pillow, numpy, imageio, imageio-ffmpeg）。視覚の画像・動画生成用。
  - `bigram_coverage/.venv`（fugashi, unidic-lite, jaconv, praat-parselmouth, librosa, opencv-python-headless）。かな解析・音響解析・音声の実測・可視化用。
- システムに ffmpeg（`brew install ffmpeg`）と 7z（`brew install p7zip`、エンジンの展開用）が要る。
- VOICEVOX エンジンは `voicevox_setup/macos-arm64/run`。無ければ GitHub の VOICEVOX/voicevox_engine のリリースから macos-arm64 の 7z を取得して展開し、`xattr -dr com.apple.quarantine` で隔離属性を外してから `./run --host 127.0.0.1 --port 50021` で起動する。

## 何がコミット済みで、何が Git 管理外か

コミット済み（clone で手に入る）: すべてのスクリプトと docs、experiment/ の各ページ、experiment/base/ の文字画像、experiment/audio2char_stimuli/ と audio1char_stimuli/ の mp3 と公開 manifest、bigram_coverage/ のスクリプトと Tatoeba の bz2 と結果 json。

Git 管理外（別PCには無い。再生成する）:
- 仮想環境（.venv, bigram_coverage/.venv）。
- VOICEVOX エンジン（voicevox_setup/、約1.8GB）。
- 秘密情報 `.env`（SECRET_SALT を含む）。この salt は独自値で、コミット済み刺激のファイル名（ハッシュ）はこの salt で作られている。
- 非公開の answer_key（answer_key.json, answer_key_2char.json, answer_key_1char.json）。GAS に貼る正解表。
- 派生キャッシュ: bigram_coverage/freq.pkl、acoustic_analysis/features.pkl、acoustic_analysis の E4版1文字プール（audio1char_E4_*）、acoustic_analysis/fluency_demo/ の音声。

## 再生成の手順（別PC・このPCどちらでも）

- **bigram の頻度 freq.pkl**: `bigram_coverage/.venv/bin/python bigram_coverage/analyze_bigram_coverage.py` を走らせると、コミット済みの bz2 から作り直される。
- **聴覚の刺激プール（要・エンジン起動）**: 実験の前に、修正済みの生成器で作り直す。
  - 2文字: `bigram_coverage/.venv/bin/python two_char_audio/build_2char_pool.py`。全72×72=5,184対。は・へ はカタカナ問い合わせで /ha/ /he/ と正しく読まれる（修正済み）。experiment/audio2char_stimuli/ と audio2char_manifest.json、非公開の answer_key_2char.json を作る。
  - 1文字: `bigram_coverage/.venv/bin/python two_char_audio/build_1char_pool.py`。音高 B3、72字。同様に修正済み。
  - salt について: 生成器は .env の SECRET_SALT を使い、無ければ既定の dev 値を使う。刺激とその answer_key は必ず同じ salt で同時に作られるので、salt を別PCへ運ばなくても、作り直せば刺激と answer_key は整合する。同じファイル名を再現したいときだけ .env を運ぶ。本番は固定 salt を決めて全部作り直す方針。
- **音響解析のキャッシュ features.pkl**: `acoustic_analysis/analyze_coarticulation.py` を走らせると、無ければ音声から作り直す（エンジンは不要、コミット済み mp3 を使う。ただし比較用の E4版1文字プールは要・エンジンで別途生成）。
- **E4版1文字プール（比較解析用・要エンジン）**: `two_char_audio/build_1char_pool.py --hz 329.63 --label E4 --out acoustic_analysis/audio1char_E4_stimuli --manifest ... --answerkey ...`。
- **流暢性デモ（要エンジン）**: `acoustic_analysis/make_fluency_demo.py`。

## いまの状態と、開いている判断・作業

- **設計の主軸（議論中の合意方向）**: 「単音だけ路線」を実用的なインクルーシブフォントの主軸にする。視覚と対称で単純、学びやすく、共調音による劣化も避けられる。流暢性は失う。2文字課題は「共調音をどれだけ捨てているか」を見積もる検証・限界づけの研究として残す。単音と流暢発音の乖離は、明瞭性の定量指標（docs/intelligibility_metrics_survey.md）で測る。単音だけなら B3→E4 の上昇輪郭も不要で、全文字を1つの明瞭な音高で出せばよい。
- **要修正（実験前）**: は・へ の合成バグ。生成器は修正済みだが、コミット済みプールは古いままなので作り直しが要る。
- **視覚の提示アルゴリズム**: 7種（fade/stroke/zoom/blur/moya/slideB/slideR）を実装済み。刺激強度の測定（docs/visual_stimulus_intensity.md）では、1/f 逸脱が高い stroke と動きの速い slide/zoom を高刺激として除外し、fade/blur/moya を残す方針。visual2char.js と visual1char.js の ALGO_LIST を採用セットに絞るのが次の作業（実装は検討材料として7種すべて残す）。
- **本実験の開始ゲート**: 倫理審査の承認（審議待ち）。承認後に、本番 salt でプール再生成、GAS デプロイ（answer_key 投入）、SUBMIT_URL 設定、noindex 解除。

## 次にやると決めていること・候補

- 単音と流暢発音の乖離を MCD＋DTW（pymcd）で網羅的に計算する（明瞭性サーベイの推奨）。
- は・へ 修正込みでプールを作り直す。
- 視覚の ALGO_LIST を絞る（PI がパイロットで体感して決める）。
- 論点として残っているもの: 平坦 E4→E4 の2字を作って、上昇輪郭の寄与を切り分けるか（単音路線を主軸にするなら優先度は下がる）。
