#!/usr/bin/env python3
"""
新仕様の検証: 絶対音高 B3→E4・1モーラ0.2秒 を VOICEVOX で実現できるか
=====================================================================
競技かるたの読みの規定に合わせ、1文字目を B3(246.94Hz)、2文字目を E4(329.63Hz) に固定する。
VOICEVOX の mora.pitch は ln(F0) なので設定値は ln(246.94)=5.509 / ln(329.63)=5.798。
ただしボコーダは話者の自然な音域から離れた設定を圧縮するので、実測とずれる。
そこで複数話者で「設定どおり」「1回補正(設定に ln(目標/実測) を加算して再合成)」の
実測F0を測り、どの話者が絶対音高に忠実かを調べる。あわせて1モーラ0.2秒の実現も確認する。

実行: bigram_coverage の venv (parselmouth入り) で
  bigram_coverage/.venv/bin/python two_char_audio/verify_b3e4.py
"""
import json, os, sys, io, wave, math, urllib.request, urllib.parse
import numpy as np
import parselmouth

ENGINE = os.environ.get("VOICEVOX_ENGINE", "http://127.0.0.1:50021")
B3 = 246.94
E4 = 329.63
MORA_DUR = 0.2      # 競技かるたの提示速度: 1文字0.2秒

SPEAKERS = [
    (11, "玄野武宏(男)"),
    (13, "青山龍星(男)"),
    (2,  "四国めたん(女)"),
    (8,  "春日部つむぎ(女)"),
    (9,  "波音リツ(女低め)"),
]
PAIRS = [("あ", "き"), ("は", "な"), ("た", "ま")]


def post(path, params=None, body=None):
    url = ENGINE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    return urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=h, method="POST"), timeout=60).read()


def single(k, spk):
    q = json.loads(post("/audio_query", {"text": k, "speaker": spk}))
    return q["accent_phrases"][0]["moras"][0], q


def set_mora(m, pitch_ln, dur):
    """モーラのピッチを絶対値(ln F0)に、合計時間を dur 秒に設定する。
    子音長は自然値を残し、母音長で合計を合わせる(最低0.04秒は確保)。"""
    m = dict(m)
    c = m.get("consonant_length") or 0.0
    if c > dur - 0.04:
        c = dur - 0.04
        m["consonant_length"] = c
    m["vowel_length"] = dur - c
    m["pitch"] = pitch_ln
    return m


def build(c1, c2, spk, p1_ln, p2_ln):
    m1, bq = single(c1, spk)
    m2, _ = single(c2, spk)
    m1 = set_mora(m1, p1_ln, MORA_DUR)
    m2 = set_mora(m2, p2_ln, MORA_DUR)
    q = dict(bq)
    q["accent_phrases"] = [{"moras": [m1, m2], "accent": 2,
                            "pause_mora": None, "is_interrogative": False}]
    for k, v in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0,
                     volumeScale=1.0, prePhonemeLength=0.1, postPhonemeLength=0.1).items():
        q[k] = v
    return q, m1, m2


def synth(q, spk):
    return post("/synthesis", {"speaker": spk}, q)


def med_f0(wav_bytes, t0, t1, floor=120, ceiling=500):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    pp = parselmouth.Sound(x, fr).to_pitch(0.005, floor, ceiling)
    f = pp.selected_array["frequency"]; t = pp.xs()
    v = [f[i] for i in range(len(t)) if t0 <= t[i] <= t1 and f[i] > 0]
    return float(np.median(v)) if v else float("nan"), len(x) / fr


def measure(wav, q, m1, m2):
    on = q["prePhonemeLength"] + (m1.get("consonant_length") or 0) + m1["vowel_length"]
    c2c = (m2.get("consonant_length") or 0)
    f1, total = med_f0(wav, q["prePhonemeLength"] + 0.05, on - 0.02)
    f2, _ = med_f0(wav, on + c2c + 0.03, on + c2c + m2["vowel_length"] - 0.02)
    return f1, f2, total


def cents(a, b):
    return 1200 * math.log2(a / b) if (a > 0 and b > 0) else float("nan")


def main():
    p1, p2 = math.log(B3), math.log(E4)
    print(f"目標: C1={B3}Hz(B3) C2={E4}Hz(E4)  設定 ln: {p1:.4f}/{p2:.4f}  1モーラ{MORA_DUR}s")
    print(f"{'話者':<16} {'対':<4} {'素のC1':>7} {'素のC2':>7} | {'補正後C1':>7} {'補正後C2':>7} | 誤差(セント) C1/C2")
    for spk, name in SPEAKERS:
        errs = []
        for (c1, c2) in PAIRS:
            q, m1, m2 = build(c1, c2, spk, p1, p2)
            wav = synth(q, spk)
            f1a, f2a, _ = measure(wav, q, m1, m2)
            # 1回補正: 実測との差をlnで足し込む
            adj1 = p1 + (math.log(B3) - math.log(f1a)) if f1a > 0 else p1
            adj2 = p2 + (math.log(E4) - math.log(f2a)) if f2a > 0 else p2
            q2, m1b, m2b = build(c1, c2, spk, adj1, adj2)
            wav2 = synth(q2, spk)
            f1b, f2b, total = measure(wav2, q2, m1b, m2b)
            e1, e2 = cents(f1b, B3), cents(f2b, E4)
            errs.append((abs(e1), abs(e2)))
            print(f"{name:<16} {c1}{c2:<3} {f1a:7.0f} {f2a:7.0f} | {f1b:7.0f} {f2b:7.0f} | {e1:+5.0f} / {e2:+5.0f}  (全長{total*1000:.0f}ms)")
        m = np.mean([e for pr in errs for e in pr])
        print(f"  -> {name} 補正後の平均絶対誤差 {m:.0f} セント")


if __name__ == "__main__":
    main()
