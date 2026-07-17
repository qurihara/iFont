#!/usr/bin/env python3
"""
ぱ行の聞こえ調整・第2ラウンド: ぷ・ぽ の追加変種
=================================================
第1ラウンドの栗原の判定: ぱ=C・ぴ=A・ぺ=A で確定。ぷ(B/Cでもぐに近い)と
ぽ(全変種がごに聞こえる)が残った。

見立て: (1)ぷ・ぽの気息([ɸ]系)が弱すぎて無声の間として聞こえず、有声(ぐ・ご)に落ちる。
(2)VOT区間に母音の有声成分が漏れ込み、声の帯として知覚される。

追加変種(いずれも土台は第1ラウンドB=VOT15-25ms):
  D: B + 気息増幅(破裂〜有声化の区間を+9dB) + 両唇傾斜(700Hz以上-10dB/oct)
  E: 「ふ」の摩擦([ɸ]=両唇のpの自然な気息)を移植。破裂の直後に ふ の摩擦25msを挟み、
     その後に母音を接続する。VOTは約30msになる。
  F: D + 有声漏れ除去(VOT区間の250Hz未満を-18dB)

出力: experiment/ptuning/<字>_D.wav 等(第1ラウンドと同じ音量正規化)
実行: <venv>/bin/python experiment/tools/ptuning_round2.py  (VOICEVOX起動下)
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
ROUND1_B_CMUL = {"ぷ": 1.75, "ぽ": 3.0}   # 第1ラウンドBの倍率(meta.jsonと一致)


def q_raw(ch):
    return json.loads(b2.post("/audio_query", {"text": b2.to_kata(ch), "speaker": SPK}))


def synth(ch, cmul=1.0):
    q0 = q_raw(ch)
    m0 = dict(q0["accent_phrases"][0]["moras"][0])
    if m0.get("consonant_length"):
        m0["consonant_length"] = m0["consonant_length"] * cmul
    m = b2.set_mora(m0, P_B3, MD)
    q = dict(q0)
    q["accent_phrases"] = [{"moras": [m], "accent": 1, "pause_mora": None, "is_interrogative": False}]
    for kk, vv in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0,
                       volumeScale=1.0, prePhonemeLength=0.1, postPhonemeLength=0.1).items():
        q[kk] = vv
    wav = b2.post("/synthesis", {"speaker": SPK}, q)
    with wave.open(io.BytesIO(wav), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
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


def xfade_replace(seg, region, fr):
    """regionを3msクロスフェードでsegに書き戻すためのヘルパは各処理内で実施"""
    return seg


def region_fft_gain(seg, fr, t0_ms, t1_ms, gain_fn):
    a = max(0, int(t0_ms / 1000 * fr)); b = min(len(seg), int(t1_ms / 1000 * fr))
    if b - a < 32:
        return seg
    part = seg[a:b].copy()
    F = np.fft.rfft(part)
    fq = np.fft.rfftfreq(len(part), 1.0 / fr)
    F2 = F * gain_fn(fq)
    filt = np.fft.irfft(F2, n=len(part))
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


def lowcut(fq):
    att = np.where(fq < 250, -18.0, 0.0)
    return 10 ** (att / 20.0)


def variant_D(ch):
    seg, fr = synth(ch, ROUND1_B_CMUL[ch])
    b, v = burst_and_voicing(seg, fr)
    seg = region_fft_gain(seg, fr, b - 2, v + 2, lambda fq: bilabial_tilt(fq) * (10 ** (9 / 20.0)))
    return seg, fr


def variant_F(ch):
    seg, fr = synth(ch, ROUND1_B_CMUL[ch])
    b, v = burst_and_voicing(seg, fr)
    seg = region_fft_gain(seg, fr, b - 2, v + 2,
                          lambda fq: bilabial_tilt(fq) * lowcut(fq) * (10 ** (9 / 20.0)))
    return seg, fr


def fu_frication(asp_ms, fr_expect):
    """ふ の[ɸ]摩擦区間(音響開始〜有声化の間)を切り出す。短ければ繋いで伸ばす。
    注意: ふは摩擦音なので「最大の立ち上がり」は母音側に出る。開始は絶対しきい値で取る。"""
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
    while len(fric) < need:                      # 短ければ折り返して伸ばす
        fric = np.concatenate([fric, fric[::-1]])
    return fric[:need]


def variant_E(ch, asp_ms=25):
    """破裂直後に ふ の摩擦([ɸ]=両唇のpの自然な気息)を移植し、その後に母音を接続する。"""
    seg, fr = synth(ch, ROUND1_B_CMUL[ch])
    b, v = burst_and_voicing(seg, fr)
    asp = fu_frication(asp_ms, fr)
    # 摩擦のレベルは母音の実効値の35%(聞こえるが出過ぎない)
    vowel = seg[int((v + 5) / 1000 * fr): int((v + 60) / 1000 * fr)]
    target = max(float(np.sqrt(np.mean(vowel**2))) * 0.35, 0.015)
    asp *= target / max(float(np.sqrt(np.mean(asp**2))), 1e-6)
    xf = max(8, int(0.003 * fr))
    w = 0.5 * (1 - np.cos(np.pi * np.arange(xf) / xf))
    asp[:xf] *= w; asp[-xf:] *= w[::-1]
    burst_part = seg[:int((b + 6) / 1000 * fr)].copy()   # 閉鎖〜破裂+6ms
    vowel_part = seg[int((v - 2) / 1000 * fr):].copy()   # 有声化-2ms以降
    out = np.concatenate([burst_part, asp, vowel_part])
    # モーラ長0.2秒+余白に収まるよう末尾を切る(フェードつき)
    limit = int((MD + 0.02) * fr)
    if len(out) > limit:
        out = out[:limit]
        nf = int(0.008 * fr)
        out[-nf:] *= 0.5 * (1 + np.cos(np.pi * np.arange(nf) / nf))
    return out, fr


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
    for ch in ["ぷ", "ぽ"]:
        for tag, fn in [("D", variant_D), ("E", variant_E), ("F", variant_F)]:
            seg, fr = fn(ch)
            b, v = burst_and_voicing(seg, fr)
            save(f"{ch}_{tag}", seg, fr)
            print(f"{ch}_{tag}: 破裂={b}ms 有声化={v:.0f}ms VOT={v-b:.0f}ms", file=sys.stderr)
    print(f"完了 -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
