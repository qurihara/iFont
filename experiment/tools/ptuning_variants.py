#!/usr/bin/env python3
"""
ぱ行の聞こえ調整: 変種を生成して聴き比べる
============================================
背景(2026-07-18): きりたんの無声破裂音はVOT欠損(5-10ms)で有声(ぐ・ご)に聞こえたため、
v3.1で一律「VOT>=25ms」に伸ばしたところ、今度は ぱ→か・ぺ→て・ぽ→こ と
「場所」の混同に変わった。日本語のVOTは両唇(p)が最も短く軟口蓋(k)が最も長い
(p約20ms < t約30ms < k約40-60ms)ので、一律の下限がぱ行をか行の時間構造に寄せた疑い。
さらに、きりたんのp破裂・気息のスペクトルは中域集中(軟口蓋的)で、両唇らしい
「拡散して低域寄り」になっていない。

生成する変種(ぱ・ぴ・ぷ・ぺ・ぽ 各3種+現行):
  A: 現行v3.1(VOT>=25msの長い気息)         … 基準
  B: VOT目標20ms(15-25msの窓に収める短い気息) … 両唇らしい時間構造
  C: B + 両唇フィルタ(破裂〜有声化の区間だけ700Hz以上を-10dB/octで減衰)
     … 中域集中の気息を、両唇らしい拡散・低域寄りの音色に補正
比較用に か・く・け・こ・て と ば行(ば・ぶ・べ・ぼ) も現行プールから並べる。

出力: experiment/ptuning/<name>.wav (すべて同じ聞こえの大きさに正規化)
実行: <venv>/bin/python experiment/tools/ptuning_variants.py  (VOICEVOX起動下)
"""
import json, os, sys, io, wave, math, subprocess
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
TARGET_AWRMS = 0.0345          # 現行プールの音量目標に合わせる
P_ROW = ["ぱ", "ぴ", "ぷ", "ぺ", "ぽ"]
REFS = ["か", "く", "け", "こ", "て", "ば", "ぶ", "べ", "ぼ"]
VOT_WINDOW = (15.0, 25.0)      # B/C変種のVOT目標窓(両唇の自然域)
CMULS = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]


def q_raw(ch):
    return json.loads(b2.post("/audio_query", {"text": b2.to_kata(ch), "speaker": SPK}))


def synth(ch, cmul):
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
        v0 = voiced[0] if voiced else float("nan")
    except Exception:
        v0 = float("nan")
    return burst, v0


def pick_cmul(ch):
    """VOTが窓(15-25ms)に収まる最小のcmulを選ぶ。無ければ20msに最も近いもの。"""
    best, best_dist = None, 1e9
    for cm in CMULS:
        seg, fr = synth(ch, cm)
        b, v = burst_and_voicing(seg, fr)
        vot = (v - b) if v == v else float("nan")
        if vot != vot:
            continue
        if VOT_WINDOW[0] <= vot <= VOT_WINDOW[1]:
            return cm, vot
        d = abs(vot - 20.0)
        if d < best_dist:
            best, best_dist, best_vot = cm, d, vot
    return best, best_vot


def bilabial_filter(seg, fr, t0_ms, t1_ms):
    """[t0,t1]msの区間に、700Hz以上を-10dB/octで減衰する傾斜(上限-18dB)をかける。
    境界は3msのレイズドコサインでクロスフェード。両唇破裂の「拡散・低域寄り」を模す。"""
    a = int(t0_ms / 1000 * fr); bnd = int(t1_ms / 1000 * fr)
    a = max(0, a); bnd = min(len(seg), bnd)
    if bnd - a < 32:
        return seg
    part = seg[a:bnd].copy()
    F = np.fft.rfft(part)
    fq = np.fft.rfftfreq(len(part), 1.0 / fr)
    att_db = np.zeros_like(fq)
    m = fq > 700
    att_db[m] = -10.0 * np.log2(fq[m] / 700.0)
    att_db = np.maximum(att_db, -18.0)
    filt = np.fft.irfft(F * (10 ** (att_db / 20.0)), n=len(part))
    xf = int(0.003 * fr)
    w = 0.5 * (1 - np.cos(np.pi * np.arange(xf) / xf))
    mixed = filt.copy()
    mixed[:xf] = part[:xf] * (1 - w) + filt[:xf] * w
    mixed[-xf:] = filt[-xf:] * (1 - w[::-1] * 0 + (1 - w))  # 端は原音に戻す
    mixed[-xf:] = filt[-xf:] * (1 - w) + part[-xf:] * w
    out = seg.copy()
    out[a:bnd] = mixed
    return out


def a_weight(f):
    f = np.maximum(np.asarray(f, float), 1e-3)
    ra = (12194.0**2 * f**4) / ((f**2 + 20.6**2) *
          np.sqrt((f**2 + 107.7**2) * (f**2 + 737.9**2)) * (f**2 + 12194.0**2))
    r1 = (12194.0**2 * 1000**4) / ((1000**2 + 20.6**2) *
          math.sqrt((1000**2 + 107.7**2) * (1000**2 + 737.9**2)) * (1000**2 + 12194.0**2))
    return ra / r1


def normalize(seg, fr):
    F = np.fft.rfft(seg * np.hanning(len(seg)))
    fq = np.fft.rfftfreq(len(seg), 1.0 / fr)
    aw = float(np.sqrt(np.sum(np.abs(F * a_weight(fq))**2)) / len(seg) * math.sqrt(2))
    g = TARGET_AWRMS / max(aw, 1e-6)
    peak = float(np.abs(seg).max())
    if peak * g > 0.9:
        g = 0.9 / peak
    return seg * g


def save(name, seg, fr):
    seg = normalize(seg, fr)
    path = os.path.join(OUT, name + ".wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes((np.clip(seg, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def from_pool(ch):
    """現行プール(v3.1のmp3)から文字部分を切り出す(gain適用)。"""
    man = json.load(open(os.path.join(EXP, "audio1char_manifest.json")))
    ak = json.load(open(os.path.join(EXP, "answer_key_1char.json")))
    ons = json.load(open(os.path.join(EXP, "audio1char_onsets.json")))
    id2char = {k.split("|")[1]: v["char"] for k, v in ak.items()}
    stim = {id2char[s["id"]]: s for s in man["stimuli"] if s["id"] in id2char}
    s = stim[ch]
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", os.path.join(EXP, "audio1char_stimuli", s["file"]),
                        "-f", "wav", "pipe:1"], stdout=subprocess.PIPE, check=True)
    with wave.open(io.BytesIO(r.stdout), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    a = int((s["char_onset_s"] + ons[ch]["acoustic_onset_ms"] / 1000) * fr)
    bnd = int((s["char_onset_s"] + s["char_dur_s"]) * fr)
    return x[a:bnd] * ons[ch]["gain"], fr


def main():
    os.makedirs(OUT, exist_ok=True)
    meta = {}
    for ch in P_ROW:
        # A: 現行v3.1
        seg, fr = from_pool(ch)
        save(f"{ch}_A", seg, fr)
        # B: VOT 15-25ms
        cm, vot = pick_cmul(ch)
        segB, fr = synth(ch, cm)
        b, v = burst_and_voicing(segB, fr)
        save(f"{ch}_B", segB, fr)
        # C: B + 両唇フィルタ(破裂-2ms 〜 有声化+2ms)
        segC = bilabial_filter(segB, fr, b - 2, (v if v == v else b + 25) + 2)
        save(f"{ch}_C", segC, fr)
        meta[ch] = dict(B_cmul=cm, B_vot_ms=round(vot, 1))
        print(f"{ch}: B=x{cm}(VOT{vot:.0f}ms) 生成OK", file=sys.stderr)
    for ch in REFS:
        seg, fr = from_pool(ch)
        save(f"ref_{ch}", seg, fr)
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), ensure_ascii=False, indent=1)
    print(f"完了 -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
