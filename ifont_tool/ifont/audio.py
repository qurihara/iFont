"""音声の生成。

既定は自己完結のトーン合成（音階=pitch のサイン波を1文字ずつ）。
--engine voicevox を指定し、ローカルに VOICEVOX エンジンが起動していれば、
合成音声(TTS)を用いる（任意・要エンジン）。
"""
import math
import struct
import wave
import urllib.request
import urllib.parse
import json

_NOTE = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4,
         "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
         "A#": 10, "BB": 10, "B": 11}


def note_to_hz(pitch: str) -> float:
    """音階名(例 'E4','B3','A#4')または数値(Hz)を周波数[Hz]に変換する。"""
    s = str(pitch).strip()
    try:
        return float(s)  # 数値ならそのまま Hz とみなす
    except ValueError:
        pass
    s = s.upper()
    # 末尾の数字(と符号)をオクターブとして切り出し、残りを音名(A, C#, BB=B♭ など)とする
    j = len(s)
    while j > 0 and (s[j - 1].isdigit() or s[j - 1] == "-"):
        j -= 1
    name, octave = s[:j], s[j:]
    if name not in _NOTE or octave == "":
        raise ValueError(f"音階が解釈できない: {pitch}")
    midi = 12 * (int(octave) + 1) + _NOTE[name]
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def build_pitch_list(pitch_arg, n_chars: int, rise: bool = False):
    """--pitch 引数から、1文字ごとの周波数[Hz]リストを作る。

    音高を1音ごとに自由設計できる。文脈のない単音の識別は基本周波数(F0)の広い変動に
    頑健であり(話者正規化)、一定音高で測った対応づけ g は音高を変えた実用提示にもそのまま生きる。
    そこで実験は一定音高(単一指定)で、実用(競技かるた等)は旋律(カンマ区切り)で、と使い分けられる。

    - 単一指定(例 'E4' や '330') は全文字に適用。--rise のときのみ1文字目を完全4度下(かるた風)にする。
    - カンマ区切り(例 'B3,E4,G4,E4,C4') は1音ごとに指定。足りなければ最後の音を繰り返し、多ければ切り詰める。
    """
    parts = [p.strip() for p in str(pitch_arg).split(",") if p.strip()]
    freqs = [note_to_hz(p) for p in parts]
    if len(freqs) <= 1:
        base = freqs[0] if freqs else note_to_hz("E4")
        if rise:
            return [base * 2 ** (-5 / 12.0) if i == 0 else base for i in range(n_chars)]
        return [base] * n_chars
    if len(freqs) < n_chars:
        freqs = freqs + [freqs[-1]] * (n_chars - len(freqs))
    return freqs[:n_chars]


def synth_tones(pitches_hz, char_dur: float, sr: int = 44100):
    """1文字ごとの周波数リスト pitches_hz を、1音ずつトーンにして並べた音を作る（float リスト）。"""
    samples = []
    for f in pitches_hz:
        m = int(char_dur * sr)
        for k in range(m):
            t = k / sr
            # 立ち上がり・減衰の窓（クリック音を避ける）
            env = max(0.0, min(1.0, t / 0.02, (char_dur - t) / 0.04))
            samples.append(0.5 * env * math.sin(2 * math.pi * f * t))
    return samples, sr


def synth_voicevox(text: str, speaker: int = 2, host: str = "http://127.0.0.1:50021",
                   speed: float = 1.0, sr: int = 44100):
    """VOICEVOX エンジン(ローカル)で TTS 合成する。エンジン未起動なら例外。"""
    q = urllib.parse.urlencode({"text": text, "speaker": speaker})
    with urllib.request.urlopen(f"{host}/audio_query?{q}", timeout=5) as r:
        query = json.load(r)
    query["speedScale"] = speed
    query["outputSamplingRate"] = sr
    data = json.dumps(query).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/synthesis?speaker={speaker}", data=data,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()  # WAV バイト列


def write_wav(samples, sr: int, path: str):
    """float(-1..1) のリストを16bit PCM WAV で書き出す。"""
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples)
        w.writeframes(frames)


def pad_wav_to(path: str, target_seconds: float):
    """WAV を target_seconds まで末尾に無音を足して延長する（映像長にそろえる）。"""
    with wave.open(path, "rb") as w:
        params = w.getparams()
        data = w.readframes(w.getnframes())
        sr = w.getframerate()
        nch = w.getnchannels()
        sw = w.getsampwidth()
    have = len(data) // (sw * nch)
    need = int(target_seconds * sr)
    if need > have:
        data += b"\x00" * ((need - have) * sw * nch)
        with wave.open(path, "wb") as w:
            w.setparams(params)
            w.writeframes(data)
