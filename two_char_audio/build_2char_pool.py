#!/usr/bin/env python3
"""
2文字課題の刺激プール生成 v2 (2026-07-02 の設計改訂に対応)
==========================================================
設計改訂の要点:
- 競技かるたの語彙に限定しない。1文字目も2文字目も全72字(音声で区別可能なかな)から
  ランダムに選ぶ。プールは 72×72 = 5,184 対の総当たり。
- 音高は競技かるたの読みの規定に基づき固定: 1文字目 B3(246.94Hz)、2文字目 E4(329.63Hz)。
  VOICEVOX の mora.pitch は ln(F0)。ボコーダの癖で実測がずれるため、ファイルごとに
  実測し、50セントを超えるずれは1回補正して作り直す。実測F0は answer_key に記録する。
- 提示速度も規定に基づき1文字 0.2秒 (子音長は自然値を残し母音長で合計を合わせる)。
- 話者は四国めたん(番号2)。検証(verify_b3e4.py)で B3/E4 の再現誤差が最小だった。
- 通常ありえない連接の扱い: 全対を含める。Tatoeba コーパスでの連接頻度を共変量として
  answer_key に記録し、除外や層別はあとから出題側・解析側で選べるようにする。

出力:
- experiment/audio2char_stimuli/<hash>.mp3   全長音声(C1 0.2s + C2 0.2s + 前後余白0.1s)
- experiment/audio2char_manifest.json        公開メタ(回答なし。C2開始時刻と長さ=ゲート用)
- experiment/answer_key_2char.json           非公開(c1/c2/実測F0/連接頻度)。GASに貼る用

実行: parselmouth が要るので bigram_coverage の venv で
  bigram_coverage/.venv/bin/python two_char_audio/build_2char_pool.py
"""
import json, os, sys, io, wave, math, hashlib, subprocess, argparse, pickle
import urllib.request, urllib.parse
import numpy as np
import parselmouth

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
import ifont_common as ic

ENGINE = os.environ.get("VOICEVOX_ENGINE", "http://127.0.0.1:50021")
B3 = 246.94          # 1文字目の音高(Hz)
E4 = 329.63          # 2文字目の音高(Hz)
MORA_DUR = 0.2       # 1文字の提示時間(秒)。競技かるたの規定
SPEAKER = 2          # 四国めたん / ノーマル。verify_b3e4.py で選定
CORRECT_CENTS = 50   # このセントを超えるずれは1回補正して再合成
FREQ_PKL = os.path.join(REPO, "bigram_coverage", "freq.pkl")


def post(path, params=None, body=None):
    url = ENGINE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    return urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=h, method="POST"), timeout=60).read()


def get(path):
    with urllib.request.urlopen(ENGINE + path, timeout=30) as r:
        return json.loads(r.read())


def load_salt():
    env = os.path.join(REPO, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.strip().startswith("SECRET_SALT"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("SECRET_SALT", "dev_2char_salt")


def to_kata(s):
    """ひらがなをカタカナに変換する。VOICEVOX は単独の「は」「へ」を助詞として
    /wa/ /e/ と読むので、カタカナ(ハ・ヘ)で問い合わせて正しい /ha/ /he/ を得る。
    「を」はカタカナ(ヲ)でも /o/ のままで正しい。"""
    return "".join(chr(ord(c) + 0x60) if 0x3041 <= ord(c) <= 0x3096 else c for c in s)


def load_bigram_freq():
    """Tatoeba 由来のかな連接頻度 (bigram_coverage/freq.pkl の corp_char)。無ければ空。"""
    try:
        d = pickle.load(open(FREQ_PKL, "rb"))
        return d["corp_char"]
    except Exception:
        return {}


def set_mora(m, pitch_ln, dur):
    m = dict(m)
    c = m.get("consonant_length") or 0.0
    if c > dur - 0.04:
        c = dur - 0.04
        m["consonant_length"] = c
    m["vowel_length"] = dur - c
    m["pitch"] = pitch_ln
    return m


def build_query(m1_raw, m2_raw, base_q, p1_ln, p2_ln, c2_cmul=1.0):
    m1 = set_mora(m1_raw, p1_ln, MORA_DUR)
    m2r = dict(m2_raw)
    if c2_cmul != 1.0 and m2r.get("consonant_length"):   # C2の無声破裂音のVOT修正
        m2r["consonant_length"] = m2r["consonant_length"] * c2_cmul
    m2 = set_mora(m2r, p2_ln, MORA_DUR)
    q = dict(base_q)
    q["accent_phrases"] = [{"moras": [m1, m2], "accent": 2,
                            "pause_mora": None, "is_interrogative": False}]
    for k, v in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0,
                     volumeScale=1.0, prePhonemeLength=0.1, postPhonemeLength=0.1).items():
        q[k] = v
    return q, m1, m2


def med_f0(wav_bytes, t0, t1, floor=170, ceiling=400):
    # floor/ceiling は B3(247)・E4(330)を含む狭域にする。
    # 広く取ると parselmouth が半分の周期(サブハーモニック)を拾い、
    # 実測が1オクターブ下(例: ま=126Hz)に落ちて音高補正が暴走するため
    # (2026-07-17 の不具合修正。以前は 120/500)。
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    pp = parselmouth.Sound(x, fr).to_pitch(0.005, floor, ceiling)
    f = pp.selected_array["frequency"]; t = pp.xs()
    v = [f[i] for i in range(len(t)) if t0 <= t[i] <= t1 and f[i] > 0]
    return float(np.median(v)) if v else float("nan")


def measure(wav, q, m1, m2):
    on = q["prePhonemeLength"] + (m1.get("consonant_length") or 0) + m1["vowel_length"]
    c2c = m2.get("consonant_length") or 0
    f1 = med_f0(wav, q["prePhonemeLength"] + 0.05, on - 0.02)
    f2 = med_f0(wav, on + c2c + 0.03, on + c2c + m2["vowel_length"] - 0.02)
    return f1, f2


def cents(a, b):
    return 1200 * math.log2(a / b) if (a > 0 and b > 0) else float("nan")


# ====== C2(回答対象モーラ)の無声破裂音の品質管理 (2026-07-18, 1文字プールと同基準) ======
# 連続2モーラでもC2のVOT(破裂→声が出るまで)は短く(4〜28ms)、有声(た→だ)に聞こえる。
# C2の子音長を伸ばしてVOTを自然域(25〜45ms)に戻す。ぱ行はPI試聴で確定した処方(1文字と同じ)を
# 適用: ぱ=短VOT+両唇傾斜、ぴ/ぺ=子音長x2.5、ぷ=x1.75+気息増幅+低域除去。
# ぽは連続では前モーラC1が閉鎖を与えるので、1文字のオッポ切り出しでなくラダー(子音長延長)で足りる。
VOICELESS_STOPS = {"p", "py", "t", "k", "ky"}
VOT_TARGET_MS = 25
VOT_CMULS = [1.0, 1.5, 2.0, 2.5, 3.0]
PA_ROW_C2 = {
    "ぱ": dict(cmul=1.0,  dsp=dict(tilt=True, boost_db=0.0, lowcut=False)),
    "ぴ": dict(cmul=2.5,  dsp=None),
    "ぷ": dict(cmul=1.75, dsp=dict(tilt=True, boost_db=9.0, lowcut=True)),
    "ぺ": dict(cmul=2.5,  dsp=None),
}


def _wav_np(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def _np_wav(x, fr):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _burst_voicing(seg, fr, f0_lo=220, f0_hi=460):
    ms = max(1, int(fr / 1000)); n = len(seg) // ms - 4
    if n < 8:
        return 0, 25.0
    env = [20 * math.log10(max(float(np.sqrt(np.mean(seg[i*ms:(i+1)*ms]**2))), 1e-7)) for i in range(n)]
    burst = max(range(n - 2), key=lambda i: env[i+2] - env[i])
    try:
        pp = parselmouth.Sound(seg, fr).to_pitch(0.002, f0_lo, f0_hi)
        f = pp.selected_array["frequency"]; t = pp.xs()
        vt = [t[i] * 1000 for i in range(len(t)) if f[i] > 0]
        v0 = vt[0] if vt else burst + 25
    except Exception:
        v0 = burst + 25
    return burst, v0


def c2_vot_ms(wav_bytes, c2_onset_s, c2_dur_s):
    x, fr = _wav_np(wav_bytes)
    seg = x[int(c2_onset_s * fr): int((c2_onset_s + c2_dur_s + 0.03) * fr)]
    b, v = _burst_voicing(seg, fr)
    return v - b


def apply_dsp_c2(wav_bytes, c2_onset_s, dsp):
    """C2の破裂〜有声化の区間に処方(両唇傾斜/増幅/低域除去)をかける。境界3msクロスフェード。"""
    if not dsp:
        return wav_bytes
    x, fr = _wav_np(wav_bytes)
    base = int(c2_onset_s * fr)
    b, v = _burst_voicing(x[base:], fr)
    a = max(0, base + int((b - 2) / 1000 * fr))
    bnd = min(len(x), base + int((v + 2) / 1000 * fr))
    if bnd - a < 32:
        return wav_bytes
    part = x[a:bnd].copy()
    F = np.fft.rfft(part); fq = np.fft.rfftfreq(len(part), 1.0 / fr)
    g = np.full_like(fq, 10 ** (dsp.get("boost_db", 0.0) / 20.0))
    if dsp.get("tilt"):
        att = np.zeros_like(fq); m = fq > 700
        att[m] = np.maximum(-10.0 * np.log2(fq[m] / 700.0), -18.0)
        g *= 10 ** (att / 20.0)
    if dsp.get("lowcut"):
        g *= np.where(fq < 250, 10 ** (-18.0 / 20.0), 1.0)
    filt = np.fft.irfft(F * g, n=len(part))
    xf = max(8, int(0.003 * fr)); w = 0.5 * (1 - np.cos(np.pi * np.arange(xf) / xf))
    filt[:xf] = part[:xf] * (1 - w) + filt[:xf] * w
    filt[-xf:] = filt[-xf:] * (1 - w) + part[-xf:] * w
    x[a:bnd] = filt
    return _np_wav(x, fr)


VOT_CTX = ["あ", "ん", "ら", "お"]   # C2のVOTを測る先行文脈(母音・撥音・流音)。文脈でVOTが変わるため複数で測る


def precompute_c2_recipe(moras, base_q, speaker):
    """各無声破裂音がC2のときの処方(cmul・DSP)を決める。ぱ行は確定処方、他はVOTラダー。
    子音長倍率はC2字の性質でほぼ決まるので、複数のC1文脈(VOT_CTX)で測り、
    文脈間の中央VOTが自然域(VOT_TARGET_MS)に届く最小cmulを全ペアに使い回す。"""
    p1, p2 = math.log(B3), math.log(E4)
    ctxs = [c for c in VOT_CTX if c in moras]
    recipe = {}
    for ch, m in moras.items():
        if m.get("consonant") not in VOICELESS_STOPS:
            continue
        if ch in PA_ROW_C2:
            recipe[ch] = dict(PA_ROW_C2[ch], vot_ms=None, method="prescribed")
            continue
        # 各cmulの文脈間中央VOTを測る。目標到達なら最小のcmulを採用。
        # どのcmulでも届かない字(た・て・と等: VOICEVOXが延長分を閉鎖の無音に充てVOTが伸びない)は、
        # 母音を無駄に削らないよう、中央VOTが最大になるcmulを選ぶ(多くはx1.0)。
        trials = []
        hit = None
        for cm in VOT_CMULS:
            vots = []
            for c1 in ctxs:
                q, m1, m2 = build_query(moras[c1], m, base_q, p1, p2, c2_cmul=cm)
                wav = post("/synthesis", {"speaker": speaker}, q)
                c2on = q["prePhonemeLength"] + (m1.get("consonant_length") or 0) + m1["vowel_length"]
                c2dur = (m2.get("consonant_length") or 0) + m2["vowel_length"]
                v = c2_vot_ms(wav, c2on, c2dur)
                if v == v:
                    vots.append(v)
            med = float(np.median(vots)) if vots else float("nan")
            trials.append((cm, med))
            if med == med and med >= VOT_TARGET_MS:
                hit = (cm, med)
                break
        if hit:
            recipe[ch] = dict(cmul=hit[0], dsp=None, vot_ms=round(hit[1], 1), method="vot-ladder")
        else:
            valid = [(cm, md) for cm, md in trials if md == md]
            cm, md = max(valid, key=lambda t: t[1]) if valid else (1.0, float("nan"))
            recipe[ch] = dict(cmul=cm, dsp=None, vot_ms=(round(md, 1) if md == md else None),
                              method="vot-best-effort")
    return recipe


def wav_to_mp3(wav_bytes):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", "pipe:0", "-codec:a", "libmp3lame", "-q:a", "4",
                        "-f", "mp3", "pipe:1"],
                       input=wav_bytes, stdout=subprocess.PIPE, check=True)
    return p.stdout


def mp3_to_wav(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", path, "-f", "wav", "pipe:1"],
                       stdout=subprocess.PIPE, check=True)
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", type=int, default=SPEAKER)
    ap.add_argument("--out", default=os.path.join(REPO, "experiment", "audio2char_stimuli"))
    ap.add_argument("--manifest", default=os.path.join(REPO, "experiment", "audio2char_manifest.json"))
    ap.add_argument("--answerkey", default=os.path.join(REPO, "experiment", "answer_key_2char.json"))
    ap.add_argument("--limit", type=int, default=None, help="先頭N対だけ(動作確認用)")
    ap.add_argument("--resume", action="store_true",
                    help="既存の mp3 は再合成せず、実測だけやり直して manifest に載せる")
    args = ap.parse_args()

    try:
        ver = get("/version")
    except Exception as e:
        sys.exit(f"VOICEVOX エンジンに接続できない({ENGINE}): {e}")
    chars = list(ic.AUDIO_ALL)
    pairs = [(a, b) for a in chars for b in chars]
    if args.limit:
        pairs = pairs[:args.limit]
    print(f"VOICEVOX {ver} / speaker={args.speaker} / {len(chars)}字 全対 {len(pairs)} / "
          f"B3={B3}Hz E4={E4}Hz / 1モーラ{MORA_DUR}s", file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    salt = load_salt()
    bigram_freq = load_bigram_freq()
    p1_base, p2_base = math.log(B3), math.log(E4)

    # 各かなの素のモーラを1回だけ取得
    moras, base_q = {}, None
    for k in chars:
        q = json.loads(post("/audio_query", {"text": to_kata(k), "speaker": args.speaker}))
        moras[k] = q["accent_phrases"][0]["moras"][0]
        if base_q is None:
            base_q = q

    # C2の無声破裂音の処方(cmul・DSP)を先に決める(C1=あで一度だけ測り全ペアに使い回す)
    c2_recipe = precompute_c2_recipe(moras, base_q, args.speaker)
    print("C2処方(無声破裂音): " + ", ".join(
        f"{c}=x{r['cmul']}" + ("+DSP" if r.get("dsp") else "") for c, r in c2_recipe.items()),
        file=sys.stderr)

    manifest, answer_key = [], {}
    n = n_corrected = n_resumed = 0
    for (c1, c2) in pairs:
        sid = hashlib.sha1(f"{salt}|{c1}{c2}|b3e4|{args.speaker}".encode()).hexdigest()[:20]
        mp3_path = os.path.join(args.out, sid + ".mp3")
        rec = c2_recipe.get(c2)
        cm = rec["cmul"] if rec else 1.0
        dsp = rec.get("dsp") if rec else None
        q, m1, m2 = build_query(moras[c1], moras[c2], base_q, p1_base, p2_base, c2_cmul=cm)
        c2_onset = q["prePhonemeLength"] + (m1.get("consonant_length") or 0) + m1["vowel_length"]
        if args.resume and os.path.exists(mp3_path):
            # 再開: 既存 mp3 から実測だけやり直す(補正の有無は記録できないので None)
            wav = mp3_to_wav(mp3_path)
            f1, f2 = measure(wav, q, m1, m2)
            corrected = None
            n_resumed += 1
        else:
            wav = post("/synthesis", {"speaker": args.speaker}, q)
            f1, f2 = measure(wav, q, m1, m2)
            e1, e2 = cents(f1, B3), cents(f2, E4)
            corrected = False
            if (not math.isnan(e1) and abs(e1) > CORRECT_CENTS) or \
               (not math.isnan(e2) and abs(e2) > CORRECT_CENTS):
                adj1 = p1_base + (math.log(B3) - math.log(f1)) if f1 > 0 else p1_base
                adj2 = p2_base + (math.log(E4) - math.log(f2)) if f2 > 0 else p2_base
                q, m1, m2 = build_query(moras[c1], moras[c2], base_q, adj1, adj2, c2_cmul=cm)
                wav = post("/synthesis", {"speaker": args.speaker}, q)
                f1, f2 = measure(wav, q, m1, m2)
                corrected = True
                n_corrected += 1
            if dsp:   # ぱ・ぷ: C2の破裂の音色を両唇らしく補正(1文字プールと同じ処方)
                wav = apply_dsp_c2(wav, c2_onset, dsp)
            with open(mp3_path, "wb") as f:
                f.write(wav_to_mp3(wav))
        c2_dur = (m2.get("consonant_length") or 0) + m2["vowel_length"]
        manifest.append(dict(
            id=sid, file=sid + ".mp3",
            c2_onset_s=round(c2_onset, 4), c2_dur_s=round(c2_dur, 4),
            sr=q.get("outputSamplingRate", 24000),
            q_set="all", modality="audio2char",
        ))
        answer_key["audio2char|" + sid] = dict(
            c1=c1, c2=c2, target=c2,
            f0_c1_hz=(round(f1, 1) if not math.isnan(f1) else None),
            f0_c2_hz=(round(f2, 1) if not math.isnan(f2) else None),
            corrected=corrected,
            c2_recipe=(rec["method"] if rec else None),
            c2_cmul=(rec["cmul"] if rec else None),
            bigram_freq=int(bigram_freq.get((c1, c2), 0)),
        )
        n += 1
        if n % 250 == 0:
            print(f"  ...{n}/{len(pairs)} (補正 {n_corrected} / 再開流用 {n_resumed})",
                  file=sys.stderr, flush=True)

    pub = dict(modality="audio2char", q_set="all", speaker=args.speaker,
               pitch_scheme="B3-E4", mora_dur_s=MORA_DUR,
               count=len(manifest), stimuli=manifest)
    json.dump(pub, open(args.manifest, "w"), ensure_ascii=False, indent=1)
    json.dump(answer_key, open(args.answerkey, "w"), ensure_ascii=False, indent=1)
    print(f"完了: {n} 音声 (補正 {n_corrected} / 再開流用 {n_resumed}) -> {args.out}", file=sys.stderr)
    print(f"  manifest(公開) {len(manifest)} 件 -> {args.manifest}", file=sys.stderr)
    print(f"  answer_key(非公開) {len(answer_key)} 件 -> {args.answerkey}", file=sys.stderr)


if __name__ == "__main__":
    main()
