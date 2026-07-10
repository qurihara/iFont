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


def synth_tones(n_chars: int, pitch_hz: float, char_dur: float,
                rise: bool = False, sr: int = 44100):
    """1文字ずつトーンを並べた音を作る（float リスト）。

    rise=True のとき、競技かるた風に1文字目を完全4度下げ(B3→E4 等)、2文字目以降を pitch_hz にする。
    """
    samples = []
    for i in range(n_chars):
        f = pitch_hz
        if rise and i == 0:
            f = pitch_hz * 2 ** (-5 / 12.0)  # 完全4度下
        m = int(char_dur * sr)
        for k in range(m):
            t = k / sr
            # 立ち上がり・減衰の窓（クリック音を避ける）
            env = min(1.0, t / 0.02, (char_dur - t) / 0.04)
            env = max(0.0, env)
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
