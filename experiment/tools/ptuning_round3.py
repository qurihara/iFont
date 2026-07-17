#!/usr/bin/env python3
"""
ぱ行の聞こえ調整・第3ラウンド: ぽ の追加変種
=============================================
判定済み: ぱ=C・ぴ=A・ぷ=F・ぺ=A。残るは ぽ (Eが善戦、F全然だめ)。

追加変種:
  G: Eの強化版。ふの摩擦([ɸ])移植を35msに延長・レベルを母音の50%に増強し、
     破裂6msにも両唇傾斜(700Hz以上-10dB/oct)をかける。
  H: 合格した「ぱ_C」の冒頭(閉鎖+破裂+気息)を移植し、ぽ の母音 /o/ に接続する。
     両唇と認められた冒頭をそのまま使う切り札。気息は/a/寄りの音色だが
     [ɸ]系の気息は母音の色が薄いので許容範囲とみる。
  I: 「オッポ」を文脈合成し、促音の後の ポ を切り出す。日本語で破裂が最も
     くっきり出る環境(長い閉鎖の後の解放)をVOICEVOX自身に作らせる。

出力: experiment/ptuning/ぽ_G.wav 等
実行: <venv>/bin/python experiment/tools/ptuning_round3.py  (VOICEVOX起動下)
"""
import json, os, sys, io, wave, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)
sys.path.insert(0, os.path.join(REPO, "two_char_audio"))
import build_2char_pool as b2
import parselmouth

SPK = 108
P_B3 = math.log(b2.B3)
MD = b2.MORA_DUR
OUT = os.path.join(EXP, "ptuning")
TARGET_AWRMS = 0.0345


def q_raw(text):
    return json.loads(b2.post("/audio_query", {"text": b2.to_kata(text), "speaker": SPK}))


def render(q):
    wav = b2.post("/synthesis", {"speaker": SPK}, q)
    with wave.open(io.BytesIO(wav), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def base_q(q):
    for kk, vv in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0,
                       volumeScale=1.0, prePhonemeLength=0.1, postPhonemeLength=0.1).items():
        q[kk] = vv
    return q


def synth(ch, cmul=1.0):
    q0 = q_raw(ch)
    m0 = dict(q0["accent_phrases"][0]["moras"][0])
    if m0.get("consonant_length"):
        m0["consonant_length"] = m0["consonant_length"] * cmul
    m = b2.set_mora(m0, P_B3, MD)
    q = base_q(dict(q0))
    q["accent_phrases"] = [{"moras": [m], "accent": 1, "pause_mora": None, "is_interrogative": False}]
    x, fr = render(q)
    a = int(0.1 * fr)
    dur = (m.get("consonant_length") or 0) + m["vowel_length"]
    return x[a:a + int((dur + 0.02) * fr)], fr


def burst_and_voicing(seg, fr):
    ms = max(1, int(fr / 1000))
    n = len(seg) // ms - 4
    env = [20 * math.log10(max(float(np.sqrt(np.mean(seg[i*ms:(i+1)*ms]**2))), 1e-7)) for i in range(n)]
    burst = max(range(n - 2), key=lambda i: env[i+2] - env[i])
    try:
        pp = parselmouth.Sound(seg, fr).to_pitch(0.002, 170, 400)
        f = pp.selected_array["frequency"]; t = pp.xs()
        voiced = [t[i] * 1000 for i in range(len(t)) if f[i] > 0]
        v0 = voiced[0] if voiced else burst + 25
    except Exception:
        v0 = burst + 25
    return burst, v0


def region_fft_gain(seg, fr, t0_ms, t1_ms, gain_fn):
    a = max(0, int(t0_ms / 1000 * fr)); b = min(len(seg), int(t1_ms / 1000 * fr))
    if b - a < 32:
        return seg
    part = seg[a:b].copy()
    F = np.fft.rfft(part)
    fq = np.fft.rfftfreq(len(part), 1.0 / fr)
    filt = np.fft.irfft(F * gain_fn(fq), n=len(part))
    xf = max(8, int(0.003 * fr))
    w = 0.5 * (1 - np.cos(np.pi * np.arange(xf) / xf))
    filt[:xf] = part[:xf] * (1 - w) + filt[:xf] * w
    filt[-xf:] = filt[-xf:] * (1 - w) + part[-xf:] * w
    out = seg.copy(); out[a:b] = filt
    return out


def bilabial_tilt(fq):
    att = np.zeros_like(fq)
    m = fq > 700
    att[m] = -10.0 * np.log2(fq[m] / 700.0)
    return 10 ** (np.maximum(att, -18.0) / 20.0)


def fu_frication(asp_ms, fr_expect):
    fu, fr = synth("ふ", 1.0)
    ms = max(1, int(fr / 1000))
    n = len(fu) // ms
    env = [20 * math.log10(max(float(np.sqrt(np.mean(fu[i*ms:(i+1)*ms]**2))), 1e-7)) for i in range(n)]
    on = next((i for i in range(n - 3) if all(e > -55 for e in env[i:i+3])), 0)
    pp = parselmouth.Sound(fu, fr).to_pitch(0.002, 170, 400)
    f = pp.selected_array["frequency"]; t = pp.xs()
    voiced = [t[i] * 1000 for i in range(len(t)) if f[i] > 0 and t[i] * 1000 > on]
    v0 = voiced[0] if voiced else on + 40
    a = int((on + 3) / 1000 * fr)
    bnd = int(max(on + 10, v0 - 4) / 1000 * fr)
    fric = fu[a:bnd].copy()
    need = int(asp_ms / 1000 * fr)
    while len(fric) < need:
        fric = np.concatenate([fric, fric[::-1]])
    return fric[:need]


def crossfade_concat(parts, fr, xf_ms=3):
    xf = max(8, int(xf_ms / 1000 * fr))
    out = parts[0]
    for p in parts[1:]:
        if len(out) < xf or len(p) < xf:
            out = np.concatenate([out, p]); continue
        w = 0.5 * (1 - np.cos(np.pi * np.arange(xf) / xf))
        mid = out[-xf:] * (1 - w) + p[:xf] * w
        out = np.concatenate([out[:-xf], mid, p[xf:]])
    return out


def fit_02(seg, fr):
    limit = int((MD + 0.02) * fr)
    if len(seg) > limit:
        seg = seg[:limit].copy()
        nf = int(0.008 * fr)
        seg[-nf:] *= 0.5 * (1 + np.cos(np.pi * np.arange(nf) / nf))
    return seg


def variant_G():
    """E強化: 気息35ms・母音の50%レベル、破裂にも両唇傾斜"""
    seg, fr = synth("ぽ", 3.0)
    b, v = burst_and_voicing(seg, fr)
    asp = fu_frication(35, fr)
    vowel_ref = seg[int((v + 5) / 1000 * fr): int((v + 60) / 1000 * fr)]
    target = max(float(np.sqrt(np.mean(vowel_ref**2))) * 0.5, 0.02)
    asp *= target / max(float(np.sqrt(np.mean(asp**2))), 1e-6)
    xf = max(8, int(0.003 * fr))
    w = 0.5 * (1 - np.cos(np.pi * np.arange(xf) / xf))
    asp[:xf] *= w; asp[-xf:] *= w[::-1]
    burst_part = seg[:int((b + 6) / 1000 * fr)].copy()
    vowel_part = seg[int((v - 2) / 1000 * fr):].copy()
    out = crossfade_concat([burst_part, asp, vowel_part], fr)
    out = region_fft_gain(out, fr, b - 2, b + 8, bilabial_tilt)
    return fit_02(out, fr), fr


def variant_H():
    """合格したぱ_C の冒頭(閉鎖+破裂+気息)を ぽ の母音に移植"""
    pa, fr = synth("ぱ", 1.0)
    pb, pv = burst_and_voicing(pa, fr)
    pa = region_fft_gain(pa, fr, pb - 2, pv + 2, bilabial_tilt)   # ぱ_Cと同じ補正
    head = pa[:int((pv - 2) / 1000 * fr)].copy()                  # 閉鎖〜気息(有声化直前まで)
    po, fr2 = synth("ぽ", 3.0)
    ob, ov = burst_and_voicing(po, fr2)
    vowel = po[int((ov - 2) / 1000 * fr2):].copy()
    # 気息レベルを ぽ 母音の40%に整える
    asp_seg = head[int((pb) / 1000 * fr):]
    vref = vowel[int(0.005 * fr2): int(0.06 * fr2)]
    if len(asp_seg) > 32 and len(vref) > 32:
        g = max(float(np.sqrt(np.mean(vref**2))) * 0.4, 0.02) / max(float(np.sqrt(np.mean(asp_seg**2))), 1e-6)
        head[int(pb / 1000 * fr):] *= min(g, 4.0)
    out = crossfade_concat([head, vowel], fr)
    return fit_02(out, fr), fr


def variant_I():
    """「オッポ」文脈合成から促音の後の ポ を切り出す(破裂が最も明瞭な環境)"""
    q0 = q_raw("オッポ")
    ms_all = []
    for ap in q0["accent_phrases"]:
        ms_all.extend(ap["moras"])
    # 全モーラをB3に。長さは自然のまま(ポの破裂を壊さない)
    for m in ms_all:
        if m.get("pitch", 0) > 0:
            m["pitch"] = P_B3
    q = base_q(dict(q0))
    q["accent_phrases"] = [{"moras": ms_all, "accent": 1, "pause_mora": None, "is_interrogative": False}]
    x, fr = render(q)
    # ポ の開始位置 = 前余白 + 先行モーラ長の累積
    t = q["prePhonemeLength"]
    for m in ms_all[:-1]:
        t += (m.get("consonant_length") or 0) + (m.get("vowel_length") or 0)
    po_m = ms_all[-1]
    a = int((t - 0.04) * fr)                     # 閉鎖を40ms含める
    seg = x[a: a + int((MD + 0.06) * fr)].copy()
    return fit_02(seg, fr), fr


def a_weight(f):
    f = np.maximum(np.asarray(f, float), 1e-3)
    ra = (12194.0**2 * f**4) / ((f**2 + 20.6**2) *
          np.sqrt((f**2 + 107.7**2) * (f**2 + 737.9**2)) * (f**2 + 12194.0**2))
    r1 = (12194.0**2 * 1000**4) / ((1000**2 + 20.6**2) *
          math.sqrt((1000**2 + 107.7**2) * (1000**2 + 737.9**2)) * (1000**2 + 12194.0**2))
    return ra / r1


def save(name, seg, fr):
    F = np.fft.rfft(seg * np.hanning(len(seg)))
    fq = np.fft.rfftfreq(len(seg), 1.0 / fr)
    aw = float(np.sqrt(np.sum(np.abs(F * a_weight(fq))**2)) / len(seg) * math.sqrt(2))
    g = TARGET_AWRMS / max(aw, 1e-6)
    peak = float(np.abs(seg).max())
    if peak * g > 0.9:
        g = 0.9 / peak
    seg = seg * g
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes((np.clip(seg, -1, 1) * 32767).astype("<i2").tobytes())


def main():
    os.makedirs(OUT, exist_ok=True)
    for tag, fn in [("G", variant_G), ("H", variant_H), ("I", variant_I)]:
        seg, fr = fn()
        b, v = burst_and_voicing(seg, fr)
        save(f"ぽ_{tag}", seg, fr)
        print(f"ぽ_{tag}: 破裂={b}ms 有声化={v:.0f}ms 長さ={len(seg)/fr*1000:.0f}ms", file=sys.stderr)
    print(f"完了 -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
