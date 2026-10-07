#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
synth_cards.py — 札セット(cards_jomo.json)の44札を、VOICEVOX(東北きりたん 108)で
通しで読み上げた音声に合成し、モーラ境界の時刻と音響的開始の実測を JSON に書き出す。

時間構造(上毛かるたの節回しの目安。公開動画の実測 project/jomo_reading_speed/README.md による)
  第一音(1モーラ目)        FIRST_MORA_S  = 0.200 秒
  本体(2モーラ目以降)      BODY_MORA_S   = 0.270 秒(子音と母音を同じ倍率で伸縮する一様の配り方)
  語尾の引き伸ばし         最後のモーラのあとに TAIL_MORAS 個の長音モーラ(ー)を足し、
                           合計 TAIL_TOTAL_S 秒以上の母音(または撥音)の持続にする。
                           1モーラの持続母音を 2 秒にすると VOICEVOX の F0 が揺れるため、
                           experiment/tools/build_karuta_samples.py と同じく短い ー の列で作る。
音高
  全モーラ B3(246.94 Hz)の一定音高。較正実験の1音刺激(audio1char: 発話先頭の音高 B3)と
  1モーラ目の条件をそろえるため。--pitch で "B3,E4,E4,..." のようにモーラごとに変えられる。
無声化の抑止
  VOICEVOX は文脈で母音を無声化する(audio_query の vowel が大文字 I/U になる)。
  1モーラ目が無声化すると聞き取りの課題にならないので、全モーラの母音を小文字にして有声で読ませる。
VOT の補正
  較正実験の1音刺激(experiment/audio1char_votfix_B3_108.json)では、発話先頭の破裂音の閉鎖と
  破裂が短すぎて聞こえないため、く・け・た・て・と の子音長を 2〜3 倍にしていた。
  通し読みでも1モーラ目は発話先頭なので、同じ倍率を1モーラ目だけに適用する(--no-votfix で止める)。
音響的開始の実測
  experiment/tools/build_onsets.py と同じ規則: 5 ms 枠の実効値が -63 dBFS を 15 ms 以上
  連続して超えた最初の点。ページはこの時刻を原点に打ち切る。
音量
  A特性の実効値(本体の区間)を札の中央値にそろえる(ピーク上限 0.85)。

出力(--out、既定 experiment/jomo/audio/)
  <札のかな>.wav           24 kHz・16 bit・モノラル(ページはこれを使う。mp3 は復号遅れが入るので使わない)
  <札のかな>.mp3           試聴用(64 kbps)
  cards_audio.json         札ごとの時刻(音響的開始、モーラ境界(名目と量子化後)、第一音の長さ、
                           総時間、音量の補正率、VOT 倍率)と合成の設定

使い方(VOICEVOX を起動しておく。http://127.0.0.1:50021)
  python3.11 experiment/jomo/synth_cards.py
  python3.11 experiment/jomo/synth_cards.py --only あ,い   # 一部の札だけ作り直す
"""
import argparse
import io
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "ifont_tool"))
from ifont.audio import _vv_query, _vv_synth, _flatten_moras, note_to_hz  # noqa: E402

HOST = "http://127.0.0.1:50021"
SPEAKER = 108                    # 東北きりたん(ノーマル)
SR = 24000                       # VOICEVOX の生成レート。リサンプルしない
FIRST_MORA_S = 0.200
BODY_MORA_S = 0.270
TAIL_MORAS = 7                   # 語尾に足す長音モーラの数
TAIL_MORA_S = 0.270              # 長音モーラ1つの長さ。7 × 0.27 + 最後のモーラ 0.27 = 2.16 秒
PRE_S = 0.05                     # 先頭の無音(prePhonemeLength)
POST_S = 0.15                    # 末尾の無音(postPhonemeLength)
FRAME_S = 256 / 24000.0          # VOICEVOX の音素長の量子化単位(10.667 ms)
VOTFIX_CMUL = {"く": 2.0, "け": 2.0, "た": 3.0, "て": 2.5, "と": 3.0}   # audio1char_votfix_B3_108.json と同じ
ONSET_DBFS = -63.0
SUSTAIN_MS = 15
FRAME_MS = 5
PEAK_CAP = 0.85


def a_weight(f):
    f = np.maximum(np.asarray(f, float), 1e-3)
    ra = (12194.0**2 * f**4) / ((f**2 + 20.6**2) *
          np.sqrt((f**2 + 107.7**2) * (f**2 + 737.9**2)) * (f**2 + 12194.0**2))
    ra1k = (12194.0**2 * 1000.0**4) / ((1000.0**2 + 20.6**2) *
            math.sqrt((1000.0**2 + 107.7**2) * (1000.0**2 + 737.9**2)) * (1000.0**2 + 12194.0**2))
    return ra / ra1k


def wav_to_np(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def np_to_wav(x, fr, path):
    y = np.clip(x, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes((y * 32767).astype("<i2").tobytes())


def find_onset_ms(x, fr):
    fl = max(1, int(FRAME_MS / 1000 * fr))
    n = len(x) // fl
    rms = np.sqrt(np.mean(x[:n * fl].reshape(n, fl) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-7))
    need = max(1, int(SUSTAIN_MS / FRAME_MS))
    for i in range(len(db) - need + 1):
        if np.all(db[i:i + need] > ONSET_DBFS):
            return i * FRAME_MS
    return None


def a_rms(x, fr):
    spec = np.fft.rfft(x * np.hanning(len(x)))
    f = np.fft.rfftfreq(len(x), 1.0 / fr)
    p = np.abs(spec) ** 2 * a_weight(f) ** 2
    return math.sqrt(p.sum() / (len(x) ** 2) * 2)


def q_frames(sec):
    """VOICEVOX が音素長をフレーム(10.667 ms)に丸めたあとの長さ(秒)。"""
    return round(sec / FRAME_S) * FRAME_S


def wait_voicevox(timeout_s=60):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(HOST + "/version", timeout=2) as r:
                return r.read().decode()
        except Exception:
            if time.time() - t0 < 2:
                subprocess.run(["open", "-a", "VOICEVOX"], check=False)
            time.sleep(2)
    return None


_mora_cache = {}


def _single_mora(txt, prev=None, nxt=None):
    """1モーラの音素(consonant/vowel)を VOICEVOX から得る。単独で1モーラに読めない字(っ など)は
    前後のモーラを付けて問い合わせ、真ん中を取る。"""
    key = (txt, prev, nxt)
    if key in _mora_cache:
        return dict(_mora_cache[key])
    q = _vv_query(txt, SPEAKER, HOST)
    ms = _flatten_moras(q)
    if len(ms) != 1:
        ctx = (prev or "") + txt + (nxt or "")
        q = _vv_query(ctx, SPEAKER, HOST)
        ms = _flatten_moras(q)
        want = 1 + (1 if prev else 0) + (1 if nxt else 0)
        if len(ms) != want:
            raise RuntimeError(f"モーラ「{txt}」を音素に分けられない({ctx} → {[m['text'] for m in ms]})")
        ms = [ms[1 if prev else 0]]
    _mora_cache[key] = dict(ms[0])
    return dict(ms[0])


def query_moras(card, moras_txt):
    """読みの全体を1回問い合わせ、モーラ数が札の moras と一致すればそれを使う。
    一致しないとき(例: 「いでゆ」を「デュ」と1モーラに読む)は、モーラごとに問い合わせて組み立てる。
    どちらの場合も長さ・音高はあとで全モーラ固定するので、エンジンの文脈依存の長さは使わない。"""
    q = _vv_query("".join(moras_txt), SPEAKER, HOST)
    ms = _flatten_moras(q)
    ok = len(ms) == len(moras_txt) and not any(ap.get("pause_mora") for ap in q["accent_phrases"])
    if not ok:
        print(f"  {card['id']}: 全体の問い合わせではモーラ数 {len(ms)}({''.join(m['text'] for m in ms)})が合わないので、モーラごとに組み立てる")
        ms = []
        for i, t in enumerate(moras_txt):
            if t == "ー":
                p = dict(ms[-1]); p["text"] = "ー"; p["consonant"] = None; p["consonant_length"] = None
                p["vowel_length"] = 0.1
                ms.append(p)
            else:
                prev = moras_txt[i - 1] if i > 0 and moras_txt[i - 1] != "ー" else None
                nxt = moras_txt[i + 1] if i + 1 < len(moras_txt) and moras_txt[i + 1] != "ー" else None
                ms.append(_single_mora(t, prev, nxt))
    return q, ms


def synth_card(card, pitches_hz, votfix):
    moras_txt = card["moras"]
    n = len(moras_txt)
    q, moras = query_moras(card, moras_txt + ["ー"] * TAIL_MORAS)
    durs, cmul_used = [], 1.0
    out = []
    for i, m in enumerate(moras):
        m = dict(m)
        if i == 0:
            dur = FIRST_MORA_S
        elif i < n:
            dur = BODY_MORA_S
        else:
            dur = TAIL_MORA_S
        c = m.get("consonant_length") or 0.0
        v = m.get("vowel_length") or 0.0
        if i == 0 and votfix and card["first_sound"] in VOTFIX_CMUL and c:
            cmul_used = VOTFIX_CMUL[card["first_sound"]]
            c = c * cmul_used
        if i == 0:
            # 1モーラ目: 子音は(補正後の長さを保ち)上限 dur-0.04、残りを母音に充てる
            if c > dur - 0.04:
                c = dur - 0.04
            if m.get("consonant") is not None:
                m["consonant_length"] = c
            m["vowel_length"] = dur - c
        else:
            # 本体: 子音と母音を同じ倍率で伸縮する(一様の配り方)
            tot = c + v
            if tot > 0 and m.get("consonant") is not None:
                k = dur / tot
                m["consonant_length"] = c * k
                m["vowel_length"] = v * k
            else:
                m["vowel_length"] = dur
        m["vowel"] = m["vowel"].lower() if m["vowel"] != "N" else "N"   # 無声化を止める
        m["pitch"] = math.log(float(pitches_hz[min(i, len(pitches_hz) - 1)]))
        durs.append(((m.get("consonant_length") or 0.0), m["vowel_length"]))
        out.append(m)
    q["accent_phrases"] = [{"moras": out, "accent": 1, "pause_mora": None, "is_interrogative": False}]
    q.update(dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0, volumeScale=1.0,
                  prePhonemeLength=PRE_S, postPhonemeLength=POST_S, outputSamplingRate=SR,
                  outputStereo=False))
    wav = _vv_synth(q, SPEAKER, HOST)
    # 名目のモーラ境界と、フレーム量子化後の境界(ファイル先頭からの秒)
    nominal, quant = [], []
    t_n = PRE_S
    t_q = q_frames(PRE_S)
    for (c, v) in durs:
        nominal.append(t_n); quant.append(t_q)
        t_n += c + v
        t_q += (q_frames(c) if c else 0.0) + q_frames(v)
    nominal.append(t_n); quant.append(t_q)     # 末尾(最後の長音モーラの終わり)
    return wav, nominal, quant, cmul_used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", default=os.path.join(HERE, "cards_jomo.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "audio"))
    ap.add_argument("--pitch", default="B3", help="音階名。カンマ区切りでモーラごとに指定可(例 B3,E4)")
    ap.add_argument("--only", default="", help="作り直す札のかな(カンマ区切り)")
    ap.add_argument("--no-votfix", action="store_true")
    ap.add_argument("--no-mp3", action="store_true")
    args = ap.parse_args()

    ver = wait_voicevox()
    if ver is None:
        print("VOICEVOX が起動していない(http://127.0.0.1:50021 に応答なし)。`open -a VOICEVOX` のあと再実行する。")
        sys.exit(2)
    print("VOICEVOX", ver)
    pitches = [note_to_hz(p.strip()) for p in args.pitch.split(",")]
    cardset = json.load(open(args.cards, encoding="utf-8"))
    only = set(s for s in args.only.split(",") if s)
    os.makedirs(args.out, exist_ok=True)
    out_json = os.path.join(args.out, "cards_audio.json")
    doc = json.load(open(out_json, encoding="utf-8")) if (only and os.path.exists(out_json)) else {}
    items = dict(doc.get("items", {}))

    raw = {}
    for card in cardset["cards"]:
        if only and card["id"] not in only:
            continue
        wav, nominal, quant, cmul = synth_card(card, pitches, not args.no_votfix)
        x, fr = wav_to_np(wav)
        assert fr == SR
        onset_ms = find_onset_ms(x, fr)
        if onset_ms is None:
            raise RuntimeError(f"{card['id']}: 音響的開始が見つからない")
        n = card["n_moras"]
        body_end = quant[n]                       # 最後の本体モーラの終わり(語尾の引き伸ばしの始まり)
        seg = x[int(onset_ms / 1000 * fr):int(body_end * fr)]
        raw[card["id"]] = dict(x=x, fr=fr, onset_ms=onset_ms, nominal=nominal, quant=quant, cmul=cmul,
                               arms=a_rms(seg, fr), card=card)
        print(f"{card['id']} 合成 {len(x)/fr:.2f}s 音響的開始 {onset_ms}ms 1モーラ目の量子化長 {1000*(quant[1]-quant[0]):.1f}ms")

    med = float(np.median([r["arms"] for r in raw.values()])) if raw else None
    if only and doc.get("params", {}).get("arms_median"):
        med = doc["params"]["arms_median"]      # 一部だけ作り直すときは既存の基準にそろえる
    for cid, r in raw.items():
        gain = med / r["arms"] if r["arms"] > 0 else 1.0
        y = r["x"] * gain
        peak = float(np.max(np.abs(y)))
        if peak > PEAK_CAP:
            gain *= PEAK_CAP / peak
            y = r["x"] * gain
        wav_path = os.path.join(args.out, cid + ".wav")
        np_to_wav(y, r["fr"], wav_path)
        if not args.no_mp3:
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav_path,
                            "-codec:a", "libmp3lame", "-b:a", "64k", os.path.join(args.out, cid + ".mp3")], check=True)
        card = r["card"]
        n = card["n_moras"]
        q_ms = [round(t * 1000, 3) for t in r["quant"]]
        items[cid] = dict(
            file=cid + ".wav", sr=r["fr"], duration_s=round(len(y) / r["fr"], 4),
            n_moras=n, moras=card["moras"], first_sound=card["first_sound"],
            acoustic_onset_ms=r["onset_ms"],
            mora_onsets_ms=q_ms[:n],                 # 本体モーラの開始(ファイル先頭から。量子化後)
            body_end_ms=q_ms[n],                     # 最後の本体モーラの終わり=語尾の引き伸ばしの開始
            tail_end_ms=q_ms[-1],
            mora_onsets_nominal_ms=[round(t * 1000, 3) for t in r["nominal"][:n]],
            # 音響的開始を原点にした本体モーラの境界(2モーラ目以降の開始)。文字側の提示で使う。
            mora_onsets_rel_ms=[round(t - r["onset_ms"], 3) for t in q_ms[1:n]],
            first_mora_ms=round(q_ms[1] - r["onset_ms"], 3),
            first_mora_nominal_ms=round(FIRST_MORA_S * 1000, 1),
            votfix_cmul=r["cmul"], gain=round(gain, 4),
        )
    first = [it["first_mora_ms"] for it in items.values()]
    durs = [it["duration_s"] for it in items.values()]
    doc = dict(
        set_id=cardset["set_id"], speaker=SPEAKER, speaker_name="東北きりたん(ノーマル)", voicevox_version=ver,
        params=dict(pitch=args.pitch, first_mora_s=FIRST_MORA_S, body_mora_s=BODY_MORA_S,
                    tail_moras=TAIL_MORAS, tail_mora_s=TAIL_MORA_S, tail_total_s=round(BODY_MORA_S + TAIL_MORAS * TAIL_MORA_S, 3),
                    pre_s=PRE_S, post_s=POST_S, sr=SR, votfix=(not args.no_votfix), votfix_cmul=VOTFIX_CMUL,
                    onset_rule=dict(dbfs=ONSET_DBFS, sustain_ms=SUSTAIN_MS, frame_ms=FRAME_MS),
                    arms_median=med),
        summary=dict(n=len(items), first_mora_ms=dict(min=min(first), median=float(np.median(first)), max=max(first)),
                     duration_s=dict(min=min(durs), median=float(np.median(durs)), max=max(durs)),
                     generated_at=time.strftime("%Y-%m-%d %H:%M:%S")),
        items=items)
    json.dump(doc, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(doc["summary"], ensure_ascii=False))
    print("書き出し先:", args.out)


if __name__ == "__main__":
    main()
