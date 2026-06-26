#!/usr/bin/env python3
"""
競技かるた限定 2文字課題の刺激を VOICEVOX で生成する試作 (作業3)
=================================================================

統一モデルの1試行は「先行文脈 C1 → ターゲット C2、C2 を時間ゲート」。
ここでは C1 を1文字目、C2 を2文字目とし、清音46字の範囲で作る。

このスクリプトがやること:
- ローカルの VOICEVOX エンジン (既定 http://127.0.0.1:50021) に話しかけて音声を合成する。
- 各かなを単体で /audio_query して、正しいモーラ(子音・母音の音素と長さ)を取得する。
  それを2つ並べて2モーラの発話を組み立てるので、辞書にない任意のかな対でも誤読しない。
- モーラごとの pitch を上書きして、競技かるた風の「1→2文字目の音程上昇」を
  あり(rise)・なし(flat)の2条件で作り分ける。
- 合成後、AudioQuery のモーラ長から C2 の開始時刻を厳密に計算し、C2 部分だけを
  frac%(0〜100) で時間ゲートする。C1 は常に全提示。MFA は不要(合成なので境界が既知)。
- 設定した pitch と、実際に合成された基本周波数(F0)の対応(較正)も測れるよう、
  各刺激のメタ情報(C2開始時刻・モーラ長・設定pitch)を manifest に残す。

注意: VOICEVOX の pitch は絶対周波数(ヘルツ)ではない対数F0系の数値。
      物理量(半音など)で管理したい場合は、出力WAVのF0を測って較正表を作る(別途)。
"""
import json, os, sys, wave, struct, argparse, urllib.request, urllib.parse, hashlib, math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ifont_common as ic

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.environ.get("VOICEVOX_ENGINE", "http://127.0.0.1:50021")

# --- ピッチ条件 ---
# 較正で判明: VOICEVOX の mora.pitch は自然対数の基本周波数 ln(F0)。
#   F0[Hz] = exp(pitch)。半音(周波数比 2^(1/12)) の上げ幅は Δpitch = ln(2)/12 ≈ 0.0578。
# 競技かるたの読みは「1文字目と2文字目の間で音程が上がる」。
# 基準(base)は話者の自然な高さ(1文字目を単体合成したときの pitch)を使い、話者に依存しない。
#   flat: 1文字目も2文字目も base (音程上昇なし)
#   rise: 1文字目は base、2文字目は base + RISE_SEMITONES 半音 (音程上昇あり)
# 較正(calibrate_pitch.py)で判明: ニューラルボコーダが小さなピッチの振れを圧縮するため、
# 設定値より実測の上げ幅は小さい。設定0〜4半音はほぼ潰れ、設定8半音以上でほぼ1:1。
# 設定8半音で実測およそ6半音(5度弱、競技かるたらしい上昇)が頑健に得られる。
# ただしかな対による分散は±1〜1.5半音あり、厳密な一様性が要るなら対ごとの較正かWORLD再合成。
RISE_SEMITONES = 8.0  # 設定値。実測およそ6半音。実験で振る独立変数
SEMITONE = math.log(2) / 12.0
PITCH_CONDS = ("flat", "rise")

FADE_MS = 6.0  # ゲート切断点の短いフェードアウト(クリック音防止)


def _post(path, params=None, body=None):
    url = ENGINE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _get(path):
    with urllib.request.urlopen(ENGINE + path, timeout=30) as r:
        return json.loads(r.read())


def list_speakers():
    return _get("/speakers")


def single_mora(kana, speaker):
    """かな1文字を audio_query して、その唯一のモーラ object を取り出す。"""
    raw = _post("/audio_query", params={"text": kana, "speaker": speaker})
    q = json.loads(raw)
    moras = []
    for ap in q["accent_phrases"]:
        moras.extend(ap["moras"])
        if ap.get("pause_mora"):
            pass  # 文末ポーズは無視
    if not moras:
        raise RuntimeError(f"モーラが得られない: {kana!r}")
    return moras[0], q  # 先頭モーラと、全体パラメータ参照用の query


def build_query(c1, c2, speaker, cond, rise_semitones=RISE_SEMITONES):
    """c1,c2 を2モーラにした AudioQuery を作り、各モーラの pitch を上書きする。
    base は1文字目を単体合成したときの自然な pitch(=ln F0)。話者非依存。"""
    m1, base_q = single_mora(c1, speaker)
    m2, _ = single_mora(c2, speaker)
    m1 = dict(m1); m2 = dict(m2)
    base = m1["pitch"]  # 話者の自然な高さ(ln F0)
    if base <= 0:       # 無声化などで0のときは c2 側か既定値で代替
        base = m2["pitch"] if m2["pitch"] > 0 else 4.7
    delta = rise_semitones * SEMITONE
    p1 = base
    p2 = base if cond == "flat" else base + delta
    m1["pitch"] = p1
    m2["pitch"] = p2
    pitch_pair = (p1, p2)
    q = dict(base_q)
    q["accent_phrases"] = [{
        "moras": [m1, m2],
        "accent": 2,            # 平板寄り。pitch を直接指定するのでアクセント型の影響は小さい
        "pause_mora": None,
        "is_interrogative": False,
    }]
    # 明示した pitch をそのまま反映させたいので、抑揚や全体ピッチの係数は中立にする
    q["speedScale"] = 1.0
    q["pitchScale"] = 0.0
    q["intonationScale"] = 1.0
    q["volumeScale"] = 1.0
    q["prePhonemeLength"] = 0.1
    q["postPhonemeLength"] = 0.1
    return q, m1, m2, pitch_pair


def synth_wav(query, speaker):
    raw = _post("/synthesis", params={"speaker": speaker}, body=query)
    return raw  # WAV(RIFF) bytes


def wav_to_np(wav_bytes):
    import io
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        nch, sw, fr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        frames = w.readframes(n)
    assert sw == 2, "16bit前提"
    x = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1)
    return x, fr


def np_to_wav(x, fr):
    import io
    x = np.clip(x, -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes(x.tobytes())
    return buf.getvalue()


def gate_c2(x, fr, c2_onset_s, c2_dur_s, frac):
    """C1 を全提示し、C2 を frac%(0..100) まで残して以降を無音化(短フェード付き)。"""
    cut_s = c2_onset_s + (frac / 100.0) * c2_dur_s
    cut = int(round(cut_s * fr))
    y = x.copy()
    if cut < len(y):
        fade = int(fr * FADE_MS / 1000.0)
        a = max(0, cut - fade)
        if cut > a:
            y[a:cut] *= np.linspace(1.0, 0.0, cut - a)
        y[cut:] = 0.0
    # 末尾の無音を少し残してから切り詰める
    tail = min(len(y), cut + int(0.05 * fr))
    return y[:tail]


def mora_dur(m):
    return (m.get("consonant_length") or 0.0) + (m.get("vowel_length") or 0.0)


def generate(pairs, speaker, fracs, out_dir, conds=PITCH_CONDS,
             rise_semitones=RISE_SEMITONES):
    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    for (c1, c2) in pairs:
        for cond_name in conds:
            q, m1, m2, pitch_pair = build_query(c1, c2, speaker, cond_name, rise_semitones)
            wav = synth_wav(q, speaker)
            x, fr = wav_to_np(wav)
            c2_onset = q["prePhonemeLength"] + mora_dur(m1)
            c2_dur = mora_dur(m2)
            for frac in fracs:
                y = gate_c2(x, fr, c2_onset, c2_dur, frac)
                key = f"{c1}{c2}_{cond_name}_f{int(frac):03d}"
                sid = hashlib.sha1(f"{key}_{speaker}".encode()).hexdigest()[:16]
                path = os.path.join(out_dir, sid + ".wav")
                with open(path, "wb") as f:
                    f.write(np_to_wav(y, fr))
                manifest.append(dict(
                    id=sid, file=sid + ".wav", c1=c1, c2=c2, target=c2,
                    pitch_cond=cond_name, pitch_m1=round(pitch_pair[0], 4),
                    pitch_m2=round(pitch_pair[1], 4),
                    f0_m1_hz=round(math.exp(pitch_pair[0]), 1),
                    f0_m2_hz=round(math.exp(pitch_pair[1]), 1),
                    rise_semitones=(0.0 if cond_name == "flat" else rise_semitones),
                    frac=frac, c2_onset_s=round(c2_onset, 4), c2_dur_s=round(c2_dur, 4),
                    sr=fr, speaker=speaker, q_set="karuta", modality="audio2char",
                ))
        print(f"  生成: {c1}{c2}", file=sys.stderr)
    json.dump(manifest, open(os.path.join(out_dir, "manifest.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"manifest {len(manifest)} 件 -> {out_dir}/manifest.json", file=sys.stderr)
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", type=int, default=None, help="話者(スタイル)ID。未指定なら一覧表示")
    ap.add_argument("--samples", action="store_true", help="少数のサンプルだけ生成(試聴用)")
    ap.add_argument("--out", default=os.path.join(HERE, "stimuli_2char"))
    ap.add_argument("--fracs", default=None, help="カンマ区切りのfrac。未指定はifont_common.FRAC_GRID")
    args = ap.parse_args()

    try:
        ver = _get("/version")
    except Exception as e:
        sys.exit(f"VOICEVOX エンジンに接続できない({ENGINE}): {e}\n  先にエンジンを起動すること。")
    print(f"VOICEVOX engine version {ver}", file=sys.stderr)

    if args.speaker is None:
        print("話者一覧(--speaker に style.id を指定):", file=sys.stderr)
        for s in list_speakers():
            for st in s["styles"]:
                print(f"  id={st['id']:>3}  {s['name']} / {st['name']}", file=sys.stderr)
        return

    fracs = ([float(x) for x in args.fracs.split(",")] if args.fracs
             else list(ic.FRAC_GRID))
    if args.samples:
        pairs = [("あ", "き"), ("き", "ぱ") if "ぱ" in ic.KARUTA_CHARS else ("き", "の"),
                 ("わ", "た")]
        pairs = [(a, b) for (a, b) in pairs]
        fracs = [0, 50, 100]
        print(f"サンプル生成: pairs={pairs} fracs={fracs}", file=sys.stderr)
    else:
        kar = list(ic.KARUTA_CHARS)
        # 試作: 全 46x46 ではなく、百人一首・上句に実在する隣接対だけにすると現実的だが、
        # ここでは試作のため少数の代表対に絞る(本番は実在対 or 設計に従って拡張)。
        pairs = [("あ", "き"), ("な", "に"), ("わ", "た"), ("ち", "は"), ("こ", "の")]
    generate(pairs, args.speaker, fracs, args.out)


if __name__ == "__main__":
    main()
