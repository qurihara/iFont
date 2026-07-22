#!/usr/bin/env python3
"""
1文字課題の刺激プール生成 (2文字課題の C1=∅ 特殊ケース)
========================================================
統一モデルの「単音課題 = 先行文脈なし(発話先頭)」にあたる。全72字(音声で区別可能な
かな)を、発話先頭の音高 B3 (246.94Hz)・1文字0.2秒で合成する。時間ゲート(truncation)は
再生時にブラウザ側で行うので、プールは 72 ファイルで済む。

build_2char_pool.py の関数を再利用する。実行は parselmouth の入った venv で:
  bigram_coverage/.venv/bin/python two_char_audio/build_1char_pool.py

出力:
- experiment/audio1char_stimuli/<hash>.mp3   1文字の合成音声(前後余白つき)
- experiment/audio1char_manifest.json        公開メタ(回答なし。文字の開始時刻と長さ=ゲート用)
- experiment/answer_key_1char.json           非公開(char/target/実測F0)。GASに貼る用
"""
import json, os, sys, math, hashlib, argparse, io, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_2char_pool as b2
sys.path.insert(0, b2.REPO)
import ifont_common as ic
import numpy as np

B3 = b2.B3
MORA_DUR = b2.MORA_DUR
REPO = b2.REPO
VOL_MIN, VOL_MAX = 0.3, 15.0   # 音量均一化のvolumeScaleの下限・上限(暴走防止)
# 出題(公開manifest)から外す同音字。お・じ・ず と同音、ゔ=ぶ。回答グリッドでも1ボタンに併記する。
AUDIO_MANIFEST_EXCLUDE = set("をぢづゔ")

# --- VOT自動修正 (2026-07-18) ---
# VOICEVOXは話者によって無声破裂音のVOT(破裂から声が出るまでの間)を5〜10msで合成することがあり、
# その場合ヒトには有声(ぷ→ぐ、と→ど)に聞こえる。自然な日本語の無声破裂音のVOTは約25〜45ms。
# 対策: 対象の子音についてVOTを実測し、不足なら子音長を伸ばして再合成する
# (東北きりたんの実測で、子音長x2〜x3でVOTが自然域に回復することを確認済み)。
VOT_TARGET_MS = 25
VOT_CMULS = [1.0, 2.0, 2.5, 3.0]                  # 子音長の倍率ラダー(順に試し、目標到達で打ち切り)
VOICELESS_STOPS = {"p", "py", "t", "k", "ky"}     # 対象(ch・tsの破擦音は自然な音なので対象外)

# --- ぱ行の字ごとの処方 (2026-07-18 PI試聴 ptuning.html 第1〜3ラウンドで確定) ---
# 一律のVOT目標では ぱ行が か行の時間構造に寄る(VOTは場所の手がかい: p<t<k)ため、
# 字ごとに耳で選んだ処方を適用する。操作はすべて音声学に根拠がある復元
# (VOTの自然域・両唇音の拡散した低域寄りの音色・[ɸ]気息・促音後の明瞭な解放)。
PRESCRIPTION_CMUL = {"ぱ": 1.0, "ぴ": 2.5, "ぷ": 1.75, "ぺ": 2.5}   # ぽは文脈合成(下記)
PRESCRIPTION_DSP = {
    # 破裂〜有声化の区間への処理: tilt=両唇傾斜(700Hz以上-10dB/oct,上限-18dB)
    # boost_db=区間の増幅 / lowcut=250Hz未満-18dB(有声成分の漏れ除去)
    "ぱ": dict(tilt=True, boost_db=0.0, lowcut=False),
    "ぷ": dict(tilt=True, boost_db=9.0, lowcut=True),
}
OPPO_SPLICE = {"ぽ": "オッポ"}   # 促音の後の明瞭な解放を文脈合成から切り出す


def wav_to_np(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def np_to_wav(x, fr):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _burst_and_voicing(seg, fr):
    import parselmouth
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


def apply_dsp(wav_bytes, char_onset_s, dsp):
    """文字の破裂〜有声化の区間に処方(傾斜/増幅/低域除去)をかける。境界3msクロスフェード。"""
    x, fr = wav_to_np(wav_bytes)
    a0 = int(char_onset_s * fr)
    b, v = _burst_and_voicing(x[a0:], fr)
    a = max(0, a0 + int((b - 2) / 1000 * fr))
    bnd = min(len(x), a0 + int((v + 2) / 1000 * fr))
    if bnd - a < 32:
        return wav_bytes
    part = x[a:bnd].copy()
    F = np.fft.rfft(part)
    fq = np.fft.rfftfreq(len(part), 1.0 / fr)
    g = np.full_like(fq, 10 ** (dsp.get("boost_db", 0.0) / 20.0))
    if dsp.get("tilt"):
        att = np.zeros_like(fq)
        m = fq > 700
        att[m] = np.maximum(-10.0 * np.log2(fq[m] / 700.0), -18.0)
        g *= 10 ** (att / 20.0)
    if dsp.get("lowcut"):
        g *= np.where(fq < 250, 10 ** (-18.0 / 20.0), 1.0)
    filt = np.fft.irfft(F * g, n=len(part))
    xf = max(8, int(0.003 * fr))
    w = 0.5 * (1 - np.cos(np.pi * np.arange(xf) / xf))
    filt[:xf] = part[:xf] * (1 - w) + filt[:xf] * w
    filt[-xf:] = filt[-xf:] * (1 - w) + part[-xf:] * w
    x[a:bnd] = filt
    return np_to_wav(x, fr)


def measure_vot_ms(wav_bytes, start_s, span_s=0.25, f0_lo=170, f0_hi=400):
    """破裂(1ms包絡の最大立ち上がり)から有声化(F0検出開始)までのms。測れなければnan。"""
    import parselmouth
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    seg = x[int(start_s * fr): int((start_s + span_s) * fr)]
    ms = max(1, int(fr / 1000))
    n = len(seg) // ms - 4
    if n < 10:
        return float("nan")
    env = [20 * math.log10(max(float(np.sqrt(np.mean(seg[i*ms:(i+1)*ms]**2))), 1e-7)) for i in range(n)]
    burst = max(range(n - 2), key=lambda i: env[i+2] - env[i])
    try:
        pp = parselmouth.Sound(seg, fr).to_pitch(0.002, f0_lo, f0_hi)
        f = pp.selected_array["frequency"]; t = pp.xs()
        voiced = [t[i] for i in range(len(t)) if f[i] > 0]
        if not voiced:
            return float("nan")
        return voiced[0] * 1000 - burst
    except Exception:
        return float("nan")


def _a_weight(f):
    """A特性(人の耳の感度)の振幅重み。1kHzで1になるよう正規化する。"""
    f = np.maximum(np.asarray(f, float), 1e-3)
    ra = (12194.0**2 * f**4) / ((f**2 + 20.6**2) *
          np.sqrt((f**2 + 107.7**2) * (f**2 + 737.9**2)) * (f**2 + 12194.0**2))
    ra1k = (12194.0**2 * 1000.0**4) / ((1000.0**2 + 20.6**2) *
            math.sqrt((1000.0**2 + 107.7**2) * (1000.0**2 + 737.9**2)) * (1000.0**2 + 12194.0**2))
    return ra / ra1k


def aweighted_rms(wav_bytes, onset_s, dur_s):
    """合成WAVの「文字部分」について、A特性で重みづけした実効値(=聞こえの大きさの近似)を返す。
    有音部だけを対象にするため、10msフレームのRMSがピークの8%を超える区間を集める。"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    a = int(onset_s * fr); b = int((onset_s + dur_s) * fr)
    seg = x[a:b] if b > a else x[a:]
    if len(seg) < 64:
        return 1e-6
    fl = max(1, int(0.010 * fr)); nfr = len(seg) // fl
    rms = np.array([np.sqrt(np.mean(seg[i*fl:(i+1)*fl]**2)) for i in range(nfr)]) if nfr else np.array([0.0])
    thr = max(rms.max() * 0.08, 1e-4)
    mask = np.repeat(rms > thr, fl)[:len(seg)]
    v = seg[:len(mask)][mask]
    if len(v) < 64:
        return 1e-6
    F = np.fft.rfft(v * np.hanning(len(v)))
    freqs = np.fft.rfftfreq(len(v), 1.0 / fr)
    Fw = F * _a_weight(freqs)
    return float(np.sqrt(np.sum(np.abs(Fw)**2)) / len(v) * math.sqrt(2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", type=int, default=b2.SPEAKER)
    ap.add_argument("--hz", type=float, default=B3,
                    help="1文字の音高(Hz)。既定は発話先頭の B3。分析用に E4=329.63 も作れる")
    ap.add_argument("--label", default="B3", help="ハッシュと pitch_scheme に使う音高ラベル")
    ap.add_argument("--out", default=os.path.join(REPO, "experiment", "audio1char_stimuli"))
    ap.add_argument("--manifest", default=os.path.join(REPO, "experiment", "audio1char_manifest.json"))
    ap.add_argument("--answerkey", default=os.path.join(REPO, "experiment", "answer_key_1char.json"))
    args = ap.parse_args()

    TARGET = args.hz
    label = args.label
    ver = b2.get("/version")
    chars = list(ic.AUDIO_ALL)
    print(f"VOICEVOX {ver} / speaker={args.speaker} / {len(chars)}字 / "
          f"{label}={TARGET}Hz / 1モーラ{MORA_DUR}s", file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    salt = b2.load_salt()
    p_base = math.log(TARGET)

    # 各かなの素のモーラと base_q を取得
    moras, base_q = {}, None
    for k in chars:
        q = json.loads(b2.post("/audio_query", {"text": b2.to_kata(k), "speaker": args.speaker}))
        moras[k] = q["accent_phrases"][0]["moras"][0]
        if base_q is None:
            base_q = q

    def synth_oppo(ch, pitch_ln, vol):
        """「オッポ」等の文脈合成から促音後のモーラを切り出し、単音と同じ体裁
        (前余白0.1s + 文字0.2s + 後余白0.1s)のWAVに再構成する。ぽ の処方I。"""
        text = OPPO_SPLICE[ch]
        q0 = json.loads(b2.post("/audio_query", {"text": b2.to_kata(text), "speaker": args.speaker}))
        ms_all = []
        for ap in q0["accent_phrases"]:
            ms_all.extend(ap["moras"])
        for m in ms_all:
            if m.get("pitch", 0) > 0:
                m["pitch"] = pitch_ln
        q = dict(q0)
        q["accent_phrases"] = [{"moras": ms_all, "accent": 1, "pause_mora": None, "is_interrogative": False}]
        for kk, vv in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0,
                           volumeScale=vol, prePhonemeLength=0.1, postPhonemeLength=0.1).items():
            q[kk] = vv
        wav = b2.post("/synthesis", {"speaker": args.speaker}, q)
        x, fr = wav_to_np(wav)
        t = q["prePhonemeLength"]
        for m in ms_all[:-1]:
            t += (m.get("consonant_length") or 0) + (m.get("vowel_length") or 0)
        a = int((t - 0.04) * fr)                       # 促音の閉鎖を40ms含める
        seg = x[a: a + int(MORA_DUR * fr)].copy()
        nf = int(0.008 * fr)
        seg[-nf:] *= 0.5 * (1 + np.cos(np.pi * np.arange(nf) / nf))
        pad = np.zeros(int(0.1 * fr))
        out = np.concatenate([pad, seg, pad])
        m_like = dict(consonant_length=0.06, vowel_length=MORA_DUR - 0.06, pitch=pitch_ln)
        q_like = dict(prePhonemeLength=0.1, outputSamplingRate=fr)
        return np_to_wav(out, fr), m_like, q_like

    def synth(ch, pitch_ln, vol, cmul=1.0):
        """1モーラを pitch_ln(対数F0)・volumeScale=vol・子音長cmul倍 で合成し、(wav, m, q) を返す。"""
        m0 = dict(moras[ch])
        if cmul != 1.0 and m0.get("consonant_length"):
            m0["consonant_length"] = m0["consonant_length"] * cmul
        m = b2.set_mora(m0, pitch_ln, MORA_DUR)
        q = dict(base_q)
        q["accent_phrases"] = [{"moras": [m], "accent": 1,
                                "pause_mora": None, "is_interrogative": False}]
        for kk, vv in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0,
                           volumeScale=vol, prePhonemeLength=0.1, postPhonemeLength=0.1).items():
            q[kk] = vv
        return b2.post("/synthesis", {"speaker": args.speaker}, q), m, q

    # --- 第0パス: 無声破裂音のVOT自動修正(冒頭のVOT_TARGET_MS参照) ---
    # ぱ行はPI試聴で確定した字ごとの処方(PRESCRIPTION_*)を優先し、ラダーは適用しない。
    votfix = {}   # ch -> dict(cmul, vot_ms)
    n_votfix = 0
    for ch in chars:
        if ch in OPPO_SPLICE:
            votfix[ch] = dict(cmul=None, vot_ms=None, method="oppo")
            continue
        if ch in PRESCRIPTION_CMUL:
            votfix[ch] = dict(cmul=PRESCRIPTION_CMUL[ch], vot_ms=None, method="prescribed")
            continue
        cons = moras[ch].get("consonant")
        if cons not in VOICELESS_STOPS:
            votfix[ch] = dict(cmul=1.0, vot_ms=None)
            continue
        best = None
        for cm in VOT_CMULS:
            wav, m, q = synth(ch, p_base, 1.0, cmul=cm)
            vot = measure_vot_ms(wav, q["prePhonemeLength"])
            best = dict(cmul=cm, vot_ms=(round(vot, 1) if vot == vot else None))
            if vot == vot and vot >= VOT_TARGET_MS:
                break
        votfix[ch] = best
        if best["cmul"] > 1.0:
            n_votfix += 1
    print(f"VOT修正: 子音長を伸ばした音 {n_votfix} 字 "
          + "(" + ", ".join(f"{c}=x{votfix[c]['cmul']}" for c in chars
                            if votfix[c].get("cmul") and votfix[c]["cmul"] > 1.0
                            and not votfix[c].get("method")) + ")",
          file=sys.stderr)
    print("ぱ行の処方: " + ", ".join(
        [f"{c}=x{PRESCRIPTION_CMUL[c]}" + ("+DSP" if c in PRESCRIPTION_DSP else "") for c in PRESCRIPTION_CMUL]
        + [f"{c}={t}切り出し" for c, t in OPPO_SPLICE.items()]), file=sys.stderr)

    def produce(ch, pitch_ln, vol):
        """処方込みで1文字を合成する(第1・第2パス共通)。(wav, m, q)を返す。"""
        if ch in OPPO_SPLICE:
            return synth_oppo(ch, pitch_ln, vol)
        wav, m, q = synth(ch, pitch_ln, vol, cmul=votfix[ch]["cmul"] or 1.0)
        if ch in PRESCRIPTION_DSP:
            wav = apply_dsp(wav, q["prePhonemeLength"], PRESCRIPTION_DSP[ch])
        return wav, m, q

    # --- 第1パス: 音高を確定し(必要なら1回補正)、素の聞こえの大きさ(A特性RMS)を測る ---
    # 目的: う・ん のように合成が病的に小さい音を、後段の過大増幅(=割れ)でなく
    #       合成時のvolumeScaleで底上げして均一化するための素データを集める。
    pass1 = {}   # ch -> dict(pitch_ln, m, awrms, f0, corrected)
    n_corrected = 0
    for ch in chars:
        pln = p_base
        wav, m, q = produce(ch, pln, 1.0)
        onset = q["prePhonemeLength"] + (m.get("consonant_length") or 0)
        f0 = b2.med_f0(wav, onset + 0.03, onset + m["vowel_length"] - 0.02)
        e = b2.cents(f0, TARGET) if f0 and not math.isnan(f0) else float("nan")
        corrected = False
        # ぽ(文脈切り出し)は音高補正のための単モーラ再合成ができないので、素の音高で使う
        if ch not in OPPO_SPLICE and not math.isnan(e) and abs(e) > b2.CORRECT_CENTS:
            pln = p_base + (math.log(TARGET) - math.log(f0))
            wav, m, q = produce(ch, pln, 1.0)
            onset = q["prePhonemeLength"] + (m.get("consonant_length") or 0)
            f0 = b2.med_f0(wav, onset + 0.03, onset + m["vowel_length"] - 0.02)
            corrected = True
            n_corrected += 1
        awrms = aweighted_rms(wav, q["prePhonemeLength"],
                              (m.get("consonant_length") or 0) + m["vowel_length"])
        pass1[ch] = dict(pitch_ln=pln, m=m, awrms=awrms, f0=f0, corrected=corrected)

    target_awrms = float(np.median([pass1[ch]["awrms"] for ch in chars]))
    print(f"聞こえの大きさの目標(A特性RMS中央値)={target_awrms:.5f}", file=sys.stderr)

    # --- 第2パス: 各モーラを volumeScale で目標の聞こえの大きさに合わせて再合成し保存 ---
    manifest, answer_key = [], {}
    n_boosted = 0
    for ch in chars:
        p = pass1[ch]
        vol = target_awrms / max(p["awrms"], 1e-6)
        vol = max(VOL_MIN, min(VOL_MAX, vol))
        if vol > 2.0:
            n_boosted += 1
        wav, m, q = produce(ch, p["pitch_ln"], vol)
        char_onset = q["prePhonemeLength"]                       # 前余白の直後 = 文字の開始
        char_dur = (m.get("consonant_length") or 0) + m["vowel_length"]
        sid = hashlib.sha1(f"{salt}|{ch}|{label}-1char|{args.speaker}".encode()).hexdigest()[:20]
        with open(os.path.join(args.out, sid + ".mp3"), "wb") as f:
            f.write(b2.wav_to_mp3(wav))
        # を・ぢ・づ は お・じ・ず と同音、ゔ は ぶ と区別されないため、出題(公開manifest)から外す。
        # mp3と正解表(answer_key)は全字ぶん残す(害はなく、別用途で参照しうる)。
        # 回答グリッドでも同音字は1ボタンに併記する(乙課題・frac聴覚で統一。2026-07-22 PI決定)。
        if ch not in AUDIO_MANIFEST_EXCLUDE:
            manifest.append(dict(
                id=sid, file=sid + ".mp3",
                char_onset_s=round(char_onset, 4), char_dur_s=round(char_dur, 4),
                sr=q.get("outputSamplingRate", 24000),
                q_set="all", modality="audio1char",
            ))
        answer_key["audio1char|" + sid] = dict(
            char=ch, target=ch,
            f0_hz=(round(p["f0"], 1) if p["f0"] and not math.isnan(p["f0"]) else None),
            corrected=p["corrected"], vol_scale=round(vol, 3),
            vot_cmul=votfix[ch].get("cmul"), vot_ms=votfix[ch].get("vot_ms"),
            recipe=votfix[ch].get("method", "vot-ladder" if votfix[ch].get("cmul", 1) != 1 else "plain"),
        )
    print(f"音量均一化: 2倍超に持ち上げた音 {n_boosted} 字", file=sys.stderr)
    # 2文字プールのビルダーが同じ修正を使えるよう、字→子音長倍率の表を書き出す
    votfix_path = os.path.join(REPO, "experiment", f"audio1char_votfix_{label}_{args.speaker}.json")
    json.dump({c: votfix[c]["cmul"] for c in chars
               if votfix[c].get("cmul") and votfix[c]["cmul"] != 1.0},
              open(votfix_path, "w"), ensure_ascii=False, indent=1)
    print(f"  VOT修正表 -> {votfix_path}", file=sys.stderr)

    pub = dict(modality="audio1char", q_set="all", speaker=args.speaker,
               pitch_scheme=label, mora_dur_s=MORA_DUR,
               count=len(manifest), stimuli=manifest)
    json.dump(pub, open(args.manifest, "w"), ensure_ascii=False, indent=1)
    json.dump(answer_key, open(args.answerkey, "w"), ensure_ascii=False, indent=1)
    print(f"完了: {len(manifest)} 音声 (補正 {n_corrected}) -> {args.out}", file=sys.stderr)
    print(f"  manifest {args.manifest} / answer_key {args.answerkey}", file=sys.stderr)


if __name__ == "__main__":
    main()
