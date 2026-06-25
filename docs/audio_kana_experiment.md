# 聴覚版実験 — f_audio_kana の測定ツール

視覚版（F1 もやもや・k グリッド）の**聴覚アナログ**。コンテキストのない「かな」1文字を
劣化音声で呈示し、50音表から識別させて `f_audio_kana(k)`（明瞭度→認識率）を測る。
得られた `f_audio_kana` を `f_visual_kana` と対応づけて変換関数 g を作るのが目的
（→ `docs/notation_and_karuta_estimation.md`）。

## 劣化モデル：音声もやもや（chorus-k）

視覚 F1 が「全候補かなを重畳し、ターゲットの不透明度 r を上げる」のに対し、聴覚版は
**全候補かなの読み上げ音声を同時再生（合唱）し、ターゲットの振幅を上げる**。

```
mix(t) = a_target · x_T + a_other · Σ_{c≠T} x_c
a_target = r/100 ,  a_other = (1 − r/100)/N
k = a_target / a_other = N·r/(100 − r)        ← 視覚と同一の k 式・同一 k グリッド
```

- k = ∞ (r=100): ターゲット単独・クリア（キャッチ試行）
- k = 0 (r=0): 全候補の等量合唱、ターゲットの優位なし
- N は q_set 依存（全字 83 / 競技かるた 47）→ 同じ (char,k) でも q_set ごとに別ミックス

**同じ k で「音と光どちらが識別しやすいか」を直接比較できる**のが利点。視覚 F1 の
「候補集合から浮かび上がる」認知メタファーを音で再現したもの。

数値検証（'あ', karuta）: ターゲットとの相関は k=∞ で +0.998 → k=64 +0.99 → k=16 +0.91
→ k=4 +0.48 → k=0 −0.01 と単調減少。視覚 F1 と対応した明瞭度勾配を確認済み。

## パイプライン（視覚版と並行）

| 役割 | 視覚 | 聴覚（本ツール） |
|---|---|---|
| 刺激生成 | make_subtractive_stills.py | **make_audio_stimuli.py** |
| プール構築 | build_stimulus_pool.py | **build_audio_pool.py** |
| クライアント | experiment/index.html + experiment.js | **experiment/audio.html + audio.js** |
| マニフェスト | experiment/manifest.json | **experiment/audio_manifest.json** |
| 刺激ファイル | experiment/stimuli/<hash>.png | **experiment/audio_stimuli/<hash>.mp3** |
| 正答キー | answer_key.json（共有・.gitignore） | 同左に **merge**（modality 付き） |
| バックエンド | gas/code.gs（modality 列対応） | 同左 |

共有定数（文字セット・k グリッド・k↔r）は `ifont_common.py`。

## 音源

macOS `say -v Kyoko`（ja_JP）で各かなを合成 → `audio_base_Kyoko/<char>.wav` にキャッシュ。
無音トリム + RMS 正規化して合唱ミックスの素材にする。**声は差替可**（`--voice Otoya` 等。
voice はパス・ハッシュに含まれるので別声と衝突しない）。

## 再生成手順

```bash
# 1. 音声刺激を生成 (all 924 + karuta 528 = 1452 mp3)
.venv/bin/python make_audio_stimuli.py --qset all karuta
#    (初回は say で 84 base を合成 ~25s。以降キャッシュ)

# 2. ハッシュ化プール + audio_manifest + answer_key(merge)
.venv/bin/python build_audio_pool.py --salt "$SECRET_SALT" --qset all karuta
```

`answer_key.json` は視覚プールと共有。視覚 → 音声 の順（または任意順）で build すれば
音声エントリが merge される（ハッシュは `audio|voice|...` 接頭辞で視覚と衝突しない）。

## クライアント仕様

- 刺激は `<audio>`。試行開始時に1回 autoplay、「▶ 音をきく / もう一度」で**何度でも再生可**
  （持続表示される視覚画像のアナログ）。再生回数 `replays` を記録・送信し、後で品質フィルタに使える。
- 回答は視覚版と同一の固定50音表グリッド。q_set は audio.js の `Q_SET`（all / karuta）。
- キャッチ＝ k=∞。完了コード・GAS 送信は視覚版と同じ。
- 倫理承認・本番デプロイ前は `audio.html` も noindex。

## 公開 URL（Pages 有効・noindex）

- 視覚版: https://qurihara.github.io/iFont/experiment/index.html
- 聴覚版: https://qurihara.github.io/iFont/experiment/audio.html

## 本番デプロイ時の注意

コミット済みプールは dev salt（`.env` の値）で生成。本番は固定 salt で
`build_stimulus_pool` と `build_audio_pool` を再実行し、merge 後の `answer_key.json` を
GAS の ANSWER_KEY プロパティへ。`SUBMIT_URL` を audio.js / experiment.js 両方に設定。

## 将来の拡張（karuta 推定との接続）

本ツールの chorus-k は「単独かなの明瞭度」を測る（f_visual_kana と最大限比較可能）。
一方 f_visual_karuta 推定で必要な「音声の連続的・部分的供給」を厳密に扱うなら、
**時間ゲーティング（かな音声を τ まで再生して識別）** という別軸の聴覚劣化も将来候補。
現時点では chorus-k で g（文字レベル変換）を確立することを優先。
