#!/usr/bin/env python3
"""
audio1char_onsets.json を単音プールから作り直す
================================================
pilot_soa_audio.js(v1.8+)は、各クリップを「音響的開始」から切り出して再生し、
クリップ間の音量差を打ち消す。その 1文字ごとの
  acoustic_onset_ms … 文字の先頭(char_onset_s)から数えて、実際に音が始まるまでのms
  voiced_end_ms     … 母音の実効的な終端(記録用)
  gain              … 聞こえの大きさをそろえる残差の増幅率
を、実際の mp3 を解析して求める。

設計(2026-07-17 の作り直し):
- 開始検出は「敏感な絶対しきい値」。5msフレームのRMSが -58dBFS を 15ms 以上連続で
  超えた最初の点を開始とする。破裂音の無音閉鎖(≈-90dB)は飛ばし、鼻音・わたり音・
  はじき音のような弱い子音は保持する(以前の「最大値の8%」は母音まで食い込んで
  わ→あ・ば→あ を招いていた)。
- gain は A特性(耳の感度)で重みづけした実効値を中央値にそろえる。プール側で音量を
  均一化済みなので、この gain はほぼ1.0の微調整になるはず。

実行: parselmouth 等の入った venv で
  <venv>/bin/python experiment/tools/build_onsets.py
出力: experiment/audio1char_onsets.json
"""
import json, os, sys, io, wave, math, subprocess, argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", default=os.path.join(EXP, "audio1char_manifest.json"))
ap.add_argument("--answerkey", default=os.path.join(EXP, "answer_key_merged.json"),
                help="audio1char|<hash> 形式のキーを持つ正解表(merged でも 1char 単体でもよい)")
ap.add_argument("--stim", default=os.path.join(EXP, "audio1char_stimuli"))
ap.add_argument("--out", default=os.path.join(EXP, "audio1char_onsets.json"))
_args = ap.parse_args()
MANIFEST = _args.manifest
ANSWERKEY = _args.answerkey
STIM_DIR = _args.stim
OUT = _args.out

ONSET_DBFS = -63.0     # この実効レベルを超えたら「音あり」とみなす絶対しきい値。
                       # 合成の無音区間(破裂音の閉鎖)は約-90dBなので、-63は弱い子音
                       # (鼻音・はじき音・有声破裂の声・立上り)を保持しつつ閉鎖だけ飛ばす。
SUSTAIN_MS = 15        # しきい値超えがこのms連続して初めて開始と認める(スパイク除け)
FRAME_MS = 5
PEAK_CAP = 0.85        # 増幅後のピーク上限(クリップ防止)


def a_weight(f):
    f = np.maximum(np.asarray(f, float), 1e-3)
    ra = (12194.0**2 * f**4) / ((f**2 + 20.6**2) *
          np.sqrt((f**2 + 107.7**2) * (f**2 + 737.9**2)) * (f**2 + 12194.0**2))
    ra1k = (12194.0**2 * 1000.0**4) / ((1000.0**2 + 20.6**2) *
            math.sqrt((1000.0**2 + 107.7**2) * (1000.0**2 + 737.9**2)) * (1000.0**2 + 12194.0**2))
    return ra / ra1k


def decode(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", path, "-f", "wav", "pipe:1"],
                       stdout=subprocess.PIPE, check=True)
    with wave.open(io.BytesIO(p.stdout), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def frame_db(seg, fr):
    fl = max(1, int(FRAME_MS / 1000 * fr))
    n = len(seg) // fl
    rms = np.array([np.sqrt(np.mean(seg[i*fl:(i+1)*fl]**2)) for i in range(n)]) if n else np.array([0.0])
    return 20 * np.log10(np.maximum(rms, 1e-7)), fl


def find_onset_ms(seg, fr):
    db, fl = frame_db(seg, fr)
    need = max(1, int(SUSTAIN_MS / FRAME_MS))
    for i in range(len(db) - need + 1):
        if np.all(db[i:i+need] > ONSET_DBFS):
            return i * FRAME_MS
    return 0


def voiced_end_ms(seg, fr):
    db, fl = frame_db(seg, fr)
    idx = np.where(db > ONSET_DBFS)[0]
    return int(idx[-1] * FRAME_MS) if len(idx) else int(len(seg) / fr * 1000)


def aw_rms(seg, fr):
    if len(seg) < 64:
        return 1e-6
    fl = max(1, int(0.010 * fr)); n = len(seg) // fl
    rms = np.array([np.sqrt(np.mean(seg[i*fl:(i+1)*fl]**2)) for i in range(n)]) if n else np.array([0.0])
    thr = max(rms.max() * 0.08, 1e-4)
    mask = np.repeat(rms > thr, fl)[:len(seg)]
    v = seg[:len(mask)][mask]
    if len(v) < 64:
        return 1e-6
    F = np.fft.rfft(v * np.hanning(len(v)))
    freqs = np.fft.rfftfreq(len(v), 1.0 / fr)
    return float(np.sqrt(np.sum(np.abs(F * a_weight(freqs))**2)) / len(v) * math.sqrt(2))


def main():
    man = json.load(open(MANIFEST))
    akey = json.load(open(ANSWERKEY))
    id2char = {k.split("|")[1]: v["char"] for k, v in akey.items() if k.startswith("audio1char|")}
    stim = {}
    for s in man["stimuli"]:
        ch = id2char.get(s["id"])
        if ch:
            stim[ch] = s

    # 各文字: 音響的開始・母音終端・(切り出し後の)A特性RMS・ピーク
    rec = {}
    for ch, s in stim.items():
        x, fr = decode(os.path.join(STIM_DIR, s["file"]))
        a = int(s["char_onset_s"] * fr)
        b = int((s["char_onset_s"] + s["char_dur_s"]) * fr)
        seg = x[a:b] if b > a else x[a:]
        on = find_onset_ms(seg, fr)
        ve = voiced_end_ms(seg, fr)
        played = seg[int(on/1000*fr):]                     # 実際に再生される区間(開始以降)
        rec[ch] = dict(on=on, ve=ve, awrms=aw_rms(played, fr),
                       peak=float(np.abs(played).max()) if len(played) else 0.0)

    target = float(np.median([r["awrms"] for r in rec.values()]))
    onsets = {}
    for ch, r in rec.items():
        gain = target / max(r["awrms"], 1e-6)
        if r["peak"] * gain > PEAK_CAP:
            gain = PEAK_CAP / max(r["peak"], 1e-6)
        onsets[ch] = dict(acoustic_onset_ms=int(r["on"]),
                          voiced_end_ms=int(r["ve"]),
                          gain=round(gain, 3))
    json.dump(onsets, open(OUT, "w"), ensure_ascii=False, indent=1)

    gains = sorted(((ch, o["gain"]) for ch, o in onsets.items()), key=lambda t: -t[1])
    print(f"目標A特性RMS(中央値)={target:.5f}  出力={OUT}", file=sys.stderr)
    print(f"gainの範囲: {gains[-1][1]}〜{gains[0][1]}倍 (中央 {sorted(g for _,g in gains)[len(gains)//2]})",
          file=sys.stderr)
    print("gain上位:", ", ".join(f"{c}={g}" for c, g in gains[:6]), file=sys.stderr)
    print("開始が遅い音:", ", ".join(
        f"{c}={onsets[c]['acoustic_onset_ms']}ms" for c in
        sorted(onsets, key=lambda c: -onsets[c]['acoustic_onset_ms'])[:6]), file=sys.stderr)


if __name__ == "__main__":
    main()
