#!/usr/bin/env python3
"""
単音と流暢発音の乖離を MCD + DTW で網羅計算
==========================================
単音だけ路線の検証。各かなを「単独で発話した単音」と「語中(2文字目)で発話した音」で
どれだけ音響的に違うかを、メル・ケプストラム歪み(MCD)を DTW で整列させて測る。
明瞭性サーベイ(docs/intelligibility_metrics_survey.md)が乖離の主指標として推奨した方法。

音高の交絡を消すため、単音側は 2文字目と同じ音高 E4 の1文字プールを使う。
比較する区間は、どちらも母音・子音を含むモーラ本体(単音は char_onset..+char_dur、
語中は c2_onset..+c2_dur)を切り出したものにする。

入力:
- 単音(E4): acoustic_analysis/audio1char_E4_manifest.json + audio1char_E4_stimuli/ + _answerkey.json
- 語中: /tmp/snap_2char_manifest.json + /tmp/snap_2char_answerkey.json + experiment/audio2char_stimuli/
  (本番salt再生成の前に取ったdev-saltスナップショット。mp3の中身は本番と同一)

出力: acoustic_analysis/mcd_divergence_result.json
実行: bigram_coverage/.venv/bin/python acoustic_analysis/analyze_mcd_divergence.py [LIMIT]
"""
import json, os, sys, tempfile, math, statistics
import numpy as np, soundfile as sf
from pymcd.mcd import Calculate_MCD

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "two_char_audio"))
import ifont_common as ic

E4_MAN = os.path.join(HERE, "audio1char_E4_manifest.json")
E4_AK  = os.path.join(HERE, "audio1char_E4_answerkey.json")
E4_DIR = os.path.join(HERE, "audio1char_E4_stimuli")
TC_MAN = "/tmp/snap_2char_manifest.json"
TC_AK  = "/tmp/snap_2char_answerkey.json"
TC_DIR = os.path.join(REPO, "experiment", "audio2char_stimuli")
OUT    = os.path.join(HERE, "mcd_divergence_result.json")

# かなの調音クラス(共調音解析 docs/coarticulation_analysis.md の分類に合わせる)
CLASS = {}
for grp, chars in {
    "母音": "あいうえお",
    "半母音": "やゆよわ",
    "撥音": "ん",
    "無声破裂": "かきくけこたてとぱぴぷぺぽ",
    "無声摩擦": "さしすせそはひふへほ",
    "破擦無声": "ちつ",
    "有声破裂": "がぎぐげごだぢづでどばびぶべぼ",
    "有声摩擦": "ざじずぜぞ",
    "その他": "らりるれろまみむめもなにぬねのゔ",
}.items():
    for c in chars:
        CLASS[c] = grp

mcd_dtw = Calculate_MCD("dtw")


def slice_to_wav(src, t0, dur, dst):
    a, sr = sf.read(src)
    if a.ndim > 1:
        a = a[:, 0]
    i0 = max(0, int(t0 * sr)); i1 = min(len(a), int((t0 + dur) * sr))
    seg = a[i0:i1]
    if len(seg) < int(0.02 * sr):   # 20ms 未満は測れない
        return False
    sf.write(dst, seg, sr)
    return True


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    tmp = tempfile.mkdtemp(prefix="mcd_")

    # 単音(E4)のモーラ本体を切り出す
    e4 = json.load(open(E4_MAN)); e4ak = json.load(open(E4_AK))
    id2char = {k.split("|")[1]: v["char"] for k, v in e4ak.items()}
    iso = {}
    for s in e4["stimuli"]:
        ch = id2char[s["id"]]
        dst = os.path.join(tmp, f"iso_{ord(ch)}.wav")
        if slice_to_wav(os.path.join(E4_DIR, s["file"]), s["char_onset_s"], s["char_dur_s"], dst):
            iso[ch] = dst
    print(f"単音(E4) 切り出し {len(iso)}字", file=sys.stderr, flush=True)

    # 語中 C2 と単音の MCD
    man = json.load(open(TC_MAN)); ak = json.load(open(TC_AK))
    id2meta = {s["id"]: s for s in man["stimuli"]}
    ctx = os.path.join(tmp, "ctx.wav")
    records = []          # (c1, c2, mcd)
    n = skip = 0
    items = list(ak.items())
    if limit:
        items = items[:limit]
    for key, v in items:
        sid = key.split("|")[1]; meta = id2meta.get(sid)
        c1, c2 = v["c1"], v["c2"]
        if meta is None or c2 not in iso:
            skip += 1; continue
        if not slice_to_wav(os.path.join(TC_DIR, meta["file"]),
                            meta["c2_onset_s"], meta["c2_dur_s"], ctx):
            skip += 1; continue
        try:
            mcd = mcd_dtw.calculate_mcd(iso[c2], ctx)
        except Exception:
            skip += 1; continue
        records.append((c1, c2, float(mcd)))
        n += 1
        if n % 500 == 0:
            print(f"  ...{n}/{len(items)} (skip {skip})", file=sys.stderr, flush=True)

    # 参照スケール: 単音どうし(別のかな)の MCD を決定的にサンプル
    chars = [c for c in ic.AUDIO_ALL if c in iso]
    ref = []
    for i, x in enumerate(chars):
        for off in (1, 7, 13, 23, 37, 53):     # 決定的に散らす
            y = chars[(i + off) % len(chars)]
            if y == x:
                continue
            try:
                ref.append(mcd_dtw.calculate_mcd(iso[x], iso[y]))
            except Exception:
                pass
    # 自分自身(サニティ、ほぼ0のはず)
    self_mcd = []
    for x in chars[:8]:
        try:
            self_mcd.append(mcd_dtw.calculate_mcd(iso[x], iso[x]))
        except Exception:
            pass

    # 集計
    def stats(xs):
        xs = sorted(xs)
        if not xs:
            return None
        return dict(n=len(xs), mean=round(statistics.mean(xs), 3),
                    median=round(statistics.median(xs), 3),
                    p10=round(xs[len(xs)//10], 3), p90=round(xs[len(xs)*9//10], 3),
                    min=round(xs[0], 3), max=round(xs[-1], 3))

    per_char, per_class = {}, {}
    for c1, c2, m in records:
        per_char.setdefault(c2, []).append(m)
        per_class.setdefault(CLASS.get(c2, "その他"), []).append(m)

    result = dict(
        method="MCD (mel-cepstral distortion) + DTW, pymcd, 単音E4 vs 語中C2",
        n_pairs=len(records), n_skip=skip,
        overall=stats([m for _, _, m in records]),
        reference_between_char=stats(ref),
        sanity_self=stats(self_mcd),
        per_class={k: stats(v) for k, v in sorted(per_class.items(),
                    key=lambda kv: -statistics.mean(kv[1]))},
        per_char_mean=dict(sorted(((c, round(statistics.mean(v), 3)) for c, v in per_char.items()),
                                  key=lambda kv: -kv[1])),
    )
    json.dump(result, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"完了: {len(records)}対 (skip {skip}) -> {OUT}", file=sys.stderr)
    print(json.dumps(result["overall"], ensure_ascii=False), file=sys.stderr)
    print("参照(単音どうし別字):", json.dumps(result["reference_between_char"], ensure_ascii=False), file=sys.stderr)
    print("自己サニティ:", json.dumps(result["sanity_self"], ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
