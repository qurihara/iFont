#!/usr/bin/env python3
"""
流暢性の体感デモ: 単音0.2秒の連結 対 通常の流暢な読み上げ
========================================================
文「みなさんこんにちは。きょうもよいてんきですね。」を、次の2通りで音声化する。
  1) 単音0.2秒の連結: 各モーラを、音高 B3・0.2秒・前の文字の影響を受けない読み方
     (カタカナ問い合わせ。は→/ha/, へ→/he/)で合成し、間を空けずにつなぐ。
     ＝ 単音だけ路線でこの文を読むとどう聞こえるか。
  2) 通常の流暢な読み上げ: VOICEVOX にそのまま文を読ませる(共調音・韻律あり)。

出力は acoustic_analysis/fluency_demo/ に wav で置く。
実行: bigram_coverage/.venv/bin/python acoustic_analysis/make_fluency_demo.py
"""
import os, sys, io, math, wave, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "two_char_audio"))
import build_2char_pool as b2

TEXT = "みなさんこんにちは。きょうもよいてんきですね。"
SPEAKER = b2.SPEAKER
B3 = b2.B3
MORA_DUR = 0.2
SMALL = "ゃゅょぁぃぅぇぉゎ"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fluency_demo")


def to_morae(s):
    """文をモーラ単位のリストに。小書き(ゃゅょ等)は前のモーラに結合。句点はポーズ。"""
    out = []
    for ch in s:
        if ch in "。、 　":
            out.append(("gap", ch))
        elif ch in SMALL and out and out[-1][0] == "mora":
            out[-1] = ("mora", out[-1][1] + ch)
        else:
            out.append(("mora", ch))
    return out


def wav_np(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def synth_mora(unit):
    """モーラ単位を、音高 B3・約0.2秒で合成した波形(と sr)。前後の余白は最小。"""
    q = json.loads(b2.post("/audio_query", {"text": b2.to_kata(unit), "speaker": SPEAKER}))
    moras = [m for ap in q["accent_phrases"] for m in ap["moras"]]
    for m in moras:
        nm = b2.set_mora(m, math.log(B3), MORA_DUR / max(1, len(moras)))
        m.update(nm)
    for k, v in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0, volumeScale=1.0,
                     prePhonemeLength=0.0, postPhonemeLength=0.0).items():
        q[k] = v
    wav = b2.post("/synthesis", {"speaker": SPEAKER}, q)
    return wav_np(wav)


def save_wav(path, x, fr):
    x = np.clip(x * 32768, -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes(x.tobytes())


def main():
    b2.get("/version")
    os.makedirs(OUT, exist_ok=True)
    units = to_morae(TEXT)

    # 1) 単音0.2秒の連結
    sr = None
    pieces = []
    fade = None
    for typ, val in units:
        if typ == "gap":
            if sr:
                pieces.append(np.zeros(int(0.18 * sr)))     # 句点は少し長めの無音
            continue
        x, fr = synth_mora(val)
        sr = fr
        if fade is None:
            fade = max(1, int(sr * 0.004))
        # つなぎ目のクリック防止に前後を短くフェード
        x = x.copy()
        x[:fade] *= np.linspace(0, 1, fade)
        x[-fade:] *= np.linspace(1, 0, fade)
        pieces.append(x)
    mono = np.concatenate(pieces)
    save_wav(os.path.join(OUT, "monophone_0.2s.wav"), mono, sr)
    print(f"単音0.2秒連結: {len(mono)/sr:.1f}秒 -> {OUT}/monophone_0.2s.wav "
          f"(モーラ数 {sum(1 for t,_ in units if t=='mora')})", file=sys.stderr)

    # 2) 通常の流暢な読み上げ
    q = json.loads(b2.post("/audio_query", {"text": TEXT, "speaker": SPEAKER}))
    wav = b2.post("/synthesis", {"speaker": SPEAKER}, q)
    x, fr = wav_np(wav)
    save_wav(os.path.join(OUT, "fluent_natural.wav"), x, fr)
    print(f"通常の流暢な読み上げ: {len(x)/fr:.1f}秒 -> {OUT}/fluent_natural.wav", file=sys.stderr)

    # mp3 も作る(共有しやすいように)
    for name in ("monophone_0.2s", "fluent_natural"):
        with open(os.path.join(OUT, name + ".wav"), "rb") as f:
            wavb = f.read()
        with open(os.path.join(OUT, name + ".mp3"), "wb") as f:
            f.write(b2.wav_to_mp3(wavb))
    print(f"mp3 も書き出した -> {OUT}/", file=sys.stderr)


if __name__ == "__main__":
    main()
