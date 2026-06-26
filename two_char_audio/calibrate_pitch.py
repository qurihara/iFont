#!/usr/bin/env python3
"""
ピッチ較正: 「設定した上げ幅(半音)」と「実際に合成された上げ幅(半音)」の対応を測る。
=====================================================================================
VOICEVOX の mora.pitch は ln(F0)。ただしニューラルボコーダが短い2モーラ区間のピッチの
振れを圧縮するため、設定どおりの半音上昇にはならない。ここでは設定値を振って複数のかな対で
実測し、設定→実測の対応(圧縮率)を出す。これにより、実験で狙った実測上昇量を得るための
設定値を決められる。

parselmouth(Praat) を使うので bigram_coverage の venv で実行する:
  bigram_coverage/.venv/bin/python two_char_audio/calibrate_pitch.py --speaker 11
"""
import json, os, sys, io, wave, argparse, urllib.request, urllib.parse, math
import numpy as np
import parselmouth

ENGINE = os.environ.get("VOICEVOX_ENGINE", "http://127.0.0.1:50021")
SEMITONE = math.log(2) / 12.0


def post(path, params=None, body=None):
    url = ENGINE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    return urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=h, method="POST"), timeout=60).read()


def single(k, spk):
    q = json.loads(post("/audio_query", {"text": k, "speaker": spk}))
    return q["accent_phrases"][0]["moras"][0], q


def build(c1, c2, p1, p2, spk):
    m1, bq = single(c1, spk); m2, _ = single(c2, spk)
    m1 = dict(m1); m2 = dict(m2); m1["pitch"] = p1; m2["pitch"] = p2
    q = dict(bq)
    q["accent_phrases"] = [{"moras": [m1, m2], "accent": 2,
                            "pause_mora": None, "is_interrogative": False}]
    for k, v in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0,
                     volumeScale=1.0, prePhonemeLength=0.1, postPhonemeLength=0.1).items():
        q[k] = v
    return q, m1, m2


def med_f0(wav, t0, t1, floor=70, ceiling=200):
    with wave.open(io.BytesIO(wav), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    pp = parselmouth.Sound(x, fr).to_pitch(0.005, floor, ceiling)
    f = pp.selected_array["frequency"]; t = pp.xs()
    v = [f[i] for i in range(len(t)) if t0 <= t[i] <= t1 and f[i] > 0]
    return float(np.median(v)) if v else float("nan")


def realized_rise(c1, c2, set_semitones, spk):
    """c2 を set_semitones 上げて合成し、実測の上昇量(半音)を返す。"""
    m1n, _ = single(c1, spk)
    base = m1n["pitch"] if m1n["pitch"] > 0 else 4.7
    q, m1, m2 = build(c1, c2, base, base + set_semitones * SEMITONE, spk)
    wav = post("/synthesis", {"speaker": spk}, q)
    on = q["prePhonemeLength"] + (m1.get("consonant_length") or 0) + m1["vowel_length"]
    dur2 = (m2.get("consonant_length") or 0) + m2["vowel_length"]
    f1 = med_f0(wav, 0.15, on - 0.04)
    f2 = med_f0(wav, on + 0.05, on + dur2 * 0.7)
    return 12 * math.log2(f2 / f1) if (f1 > 0 and f2 > 0) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", type=int, default=11)
    args = ap.parse_args()
    pairs = [("あ", "き"), ("き", "の"), ("わ", "た"), ("ち", "は"),
             ("こ", "の"), ("な", "に"), ("た", "か"), ("み", "よ")]
    set_vals = [0, 2, 4, 6, 8, 10, 12]
    print(f"話者 {args.speaker}。設定上げ幅(半音) → 実測上げ幅(半音、{len(pairs)}対の平均±SD)")
    table = []
    for s in set_vals:
        rr = [realized_rise(c1, c2, s, args.speaker) for (c1, c2) in pairs]
        rr = [x for x in rr if not math.isnan(x)]
        mean, sd = float(np.mean(rr)), float(np.std(rr))
        table.append((s, mean, sd))
        print(f"  設定 {s:>2} 半音 → 実測 {mean:+.2f} ± {sd:.2f} 半音")
    # 線形あてはめ(原点付近): realized ≈ slope * set
    xs = np.array([t[0] for t in table]); ys = np.array([t[1] for t in table])
    slope = float((xs * ys).sum() / (xs * xs).sum())
    print(f"\n圧縮率(実測/設定) ≈ {slope:.2f}。狙った実測上げ幅 r 半音を得る設定値は約 {1/slope:.2f}×r 半音。")
    print("例: 実測3半音 ≈ 設定 {:.1f}半音 / 実測5半音 ≈ 設定 {:.1f}半音".format(3/slope, 5/slope))
    json.dump(dict(speaker=args.speaker, pairs=["".join(p) for p in pairs],
                   set_vs_realized=table, slope=slope),
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "pitch_calibration.json"), "w"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
