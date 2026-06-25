# 不採用: 音声もやもや（chorus-k）モデル

ここにある音声刺激と生成器は **f_audio_kana の chorus-k モデル**（全候補かなを合唱で重畳し、
ターゲットの振幅を上げる、視覚 F1 の聴覚アナログ）。**2026-06 に不採用**となり、
**単音の時間ゲーティング（truncation）モデル**に置き換えた（リポジトリ直下の
`make_audio_stimuli.py` / `docs/audio_kana_experiment.md` を参照）。

データは記録として保存しているが、本実験では使用しない。

## 不採用の理由
- 合唱で多数の音を混ぜるため解釈が複雑。
- 単音を「発話のどこまで聞いたら識別できるか（再生終了時刻を小刻みに変える）」で測る方が、
  - 単純で解釈しやすい、
  - Kikiwake（読みをどこまで聞いたら歌が分かるか）の単音版そのもの、
  - f_visual_karuta 推定で必要な「音声の連続的・部分供給」と直結する。

## 中身
- `make_audio_chorus.py` — 合唱ミックス生成器（旧 make_audio_stimuli.py）
- `build_audio_chorus_pool.py` — 旧 build_audio_pool.py
- `audio_stimuli_Kyoko_all/`, `audio_stimuli_Kyoko_karuta/` — 合唱 mp3（all 924 + karuta 528）

数値検証では chorus-k のターゲット相関が k=∞ で 0.998 → k=0 で −0.01 と単調減少しており
モデル自体は妥当に機能していた（不採用は設計方針の変更による）。
