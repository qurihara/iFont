# 聴覚版実験 — f_audio_kana の測定ツール（単音 時間ゲーティング）

視覚版（F1 もやもや・k グリッド）の**聴覚アナログ**。コンテキストのない「かな」1文字を
**発話の途中まで（再生終了時刻を小刻みに変えて）**呈示し、50音表から識別させて
`f_audio_kana(frac)`（聞いた割合→認識率）を測る。得られた `f_audio_kana` を
`f_visual_kana` と対応づけて変換関数 g を作るのが目的
（→ `docs/notation_and_karuta_estimation.md`）。

## 統一モデル：「文脈 C1 → ターゲット C2、C2 を時間ゲート」

1試行は本質的に **「先行文脈 C1 → ターゲット C2、C2 を発話の frac% まで聞いて識別」**。
**単音課題は C1=∅（文脈なし＝発話の先頭位置）の特殊ケース**。

- **C1=∅（現状・本ツール）**：MFA 不要。発話/語の先頭位置 baseline。
- **C1≠∅（phase-2・要 MFA）**：ランダムな先行かな。実テキストの大半はこちらで、
  コアーティキュレーション（前音素で次の現れ方が変わる）を反映。**ゃゅょ・っ も C1≠∅
  でのみ意味を持つ**（`きゃ` vs `きや`、`かっ` の促音）。kikiwake の MFA で C2 境界を取る。

実テキストでは文脈ありが主役なので、C1=∅ baseline は「先頭位置」の限定ケースと位置づける。

## モダリティ別 文字セット（2026-06 設計レビュー）

孤立提示で degenerate になる文字はモダリティで異なる（`ifont_common.py`）：

| | all | karuta | 除外/理由 |
|---|---|---|---|
| **VISUAL** | 78 | 48 | ぁぃぅぇぉゎ のみ除外（外来語専用）。**ゃゅょ・っ・ゐゑ は distinct glyph として維持**（小字可読性こそ測りたい対象） |
| **AUDIO（単音 C1=∅）** | 72 | 46 | 清音46+濁20+半5+ゔ。ゐゑ→いえ / ゃゅょ→やゆよ / っ=無音 / 小書き母音→母音 は孤立で区別不能 → 除外（C1≠∅ 2文字 or 基底文字代用で回収） |

外来語等で ぁぃぅぇぉゎ が出る場合は、表示/読みとも**通常サイズの同字**で代用（実運用時の方針）。

## 採用モデル：単音 時間ゲーティング（truncation, = C1=∅）

> 旧「音声もやもや（chorus-k）」は **不採用**（→ `archive/DEPRECATED.md`）。多数の音を
> 合唱で混ぜるため解釈が複雑だった。単音を「発話のどこまで聞いたら分かるか」で測る方が、
> 単純・解釈容易で、Kikiwake（読みをどこまで聞いたら歌が分かるか）の単音版そのものであり、
> f_visual_karuta 推定で必要な「音声の連続的・部分供給」と直結する。

```
voiced region [t0, t1]  (発話の onset..offset)
frac ∈ {0,5,...,100}%   そのかなを [t0, t0 + frac/100·(t1-t0)] まで再生
                        (末尾に短いフェードを掛けクリック音を回避)
frac = 0   -> 無音（chance アンカー）
frac = 100 -> 完全なクリア音声（キャッチ試行）
```

- **割合（発話長の%）ベース**：かなごとに発話長が違うため、絶対 ms ではなく割合で揃える。
  f_visual_kana の 0→100% と対称。
- **21段階（5%刻み）**：`ifont_common.py` の `FRAC_GRID` で定義。粒度の再調整はここ1か所。
- 切り出しは**候補集合に依存しない**ので 1 つのプール（84字×21=1764）で all/karuta 両方に対応。
  回答グリッドと γ だけが q_set で変わる。

長さ検証：各 frac で再生長が単調増加、frac=100 で完全音声になることを確認済み。

## パイプライン（視覚版と並行・ifont_common.py 共有）

| 役割 | 視覚 | 聴覚（本ツール） |
|---|---|---|
| 刺激生成 | make_subtractive_stills.py | **make_audio_stimuli.py** |
| プール構築 | build_stimulus_pool.py | **build_audio_pool.py** |
| クライアント | experiment/index.html + experiment.js | **experiment/audio.html + audio.js** |
| マニフェスト | experiment/manifest.json | **experiment/audio_manifest.json** |
| 刺激ファイル | experiment/stimuli/<hash>.png | **experiment/audio_stimuli/<hash>.mp3** |
| 正答キー | answer_key.json（共有・.gitignore） | 同左に **merge**（modality 付き） |
| バックエンド | gas/code.gs（k* / frac* 両対応） | 同左 |

## 音源と onset/offset 検出

macOS `say -v Kyoko`（ja_JP）で各かなを合成 → `audio_base_Kyoko/<char>.wav` にキャッシュ。
**声は差替可**（`--voice`。voice は出力パス・ハッシュに含まれ別声と衝突しない）。

現状の voiced 区間 [onset, offset] は **RMS 閾値トリム**で検出している。
**TODO（精緻化）**: kikiwake のレポジトリにある **MFA（Montreal Forced Aligner）** で
単語/音素境界を取り、真の発話 onset から割合を測る方式に差し替える。RMS トリムは
無音を落とすだけなので概ね妥当だが、子音の弱い立ち上がり等は MFA の方が正確。

## 再生成手順

```bash
# 1. 音声刺激を生成 (84字 × 21段階 = 1764 mp3)
.venv/bin/python make_audio_stimuli.py
#    (初回は say で 84 base を合成 ~30s。以降キャッシュ)

# 2. ハッシュ化プール + audio_manifest + answer_key(merge)
.venv/bin/python build_audio_pool.py --salt "$SECRET_SALT"
```

`build_audio_pool.py` は実行時に既存 answer_key の **古い audio エントリを除去**してから
truncation エントリを merge する（視覚エントリは温存）。ハッシュは `audiotrunc|voice|...`
接頭辞で視覚と衝突しない。

## クライアント仕様

- 刺激は事前に切り出し済みの `<audio>` mp3。試行開始時に1回 autoplay、
  「▶ 音をきく / もう一度」で**何度でも再生可**（持続表示される視覚画像のアナログ）。
  再生回数 `replays` を記録・送信し品質フィルタに使える。
- 回答は視覚版と同一の固定50音表グリッド。q_set は audio.js の `Q_SET`（all / karuta）。
  刺激は `q_sets` タグでフィルタ（karuta 字は all/karuta 両方に出る）。
- キャッチ＝ frac=100。完了コード・GAS 送信は視覚版と同じ。承認前は noindex。

## セルフパイロット

`experiment/pilot_audio.html` — Web Audio で base を **任意 frac で live 切り出し再生**。
Inspect（target + frac 連続スライダ + 再生）／ Trial（ランダム + 50音グリッド + 即時判定 +
2P logistic 回帰 + CSV）。視覚 pilot.html の聴覚アナログ。

## 公開 URL（Pages 有効・noindex）

- 視覚版本実験: https://qurihara.github.io/iFont/experiment/index.html
- 聴覚版本実験: https://qurihara.github.io/iFont/experiment/audio.html
- 聴覚パイロット: https://qurihara.github.io/iFont/experiment/pilot_audio.html

## 1人あたり試行数（視覚版との比較）

1人あたりは両モダリティとも **N_TRIALS=200（≈20分）で同じ**。違うのはプール密度：

| | 視覚 | 音声 truncation(21段階) |
|---|---|---|
| cell 数 | 11×84 = 924 | 21×84 = 1764 |
| 100人時 obs/cell | ≈21.6 | ≈11.3 |
| level 集約 obs/level | ≈1815 | ≈952（十分） |

per-(char,frac) を視覚並み密度にしたいなら参加者を約2倍、または段階を 11 に減らす
（`FRAC_GRID` を変更）。まず 21 段階で取得し密度を見て調整する方針。

## 本番デプロイ時の注意

コミット済みプールは dev salt。本番は固定 salt で `build_stimulus_pool`（視覚）と
`build_audio_pool`（音声）を再実行し、merge 後の `answer_key.json` を GAS の ANSWER_KEY へ。
`SUBMIT_URL` を experiment.js / audio.js 両方に設定。
