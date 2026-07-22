#!/usr/bin/env python3
"""Compare 5% gate RMS levels before and after the acoustic-onset fix."""

import array
import io
import json
import math
import subprocess
import sys
import wave
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = EXPERIMENT_DIR / "audio1char_manifest.json"
ANSWER_KEY_PATH = EXPERIMENT_DIR / "answer_key_merged.json"
STIMULI_DIR = EXPERIMENT_DIR / "audio1char_stimuli"


def load_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def decode_mp3(path):
    command = [
        "ffmpeg", "-v", "error", "-i", str(path), "-f", "wav",
        "-acodec", "pcm_s16le", "-ac", "1", "pipe:1",
    ]
    try:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg コマンドが見つかりません") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpegによるデコードに失敗しました: {path}: {detail}") from exc

    with wave.open(io.BytesIO(result.stdout), "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise RuntimeError(f"想定外のWAV形式です: {path}")
        sample_rate = wav.getframerate()
        samples = array.array("h", wav.readframes(wav.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    return sample_rate, samples


def window_dbfs(samples, sample_rate, start_s, duration_s, gain=1.0):
    start = round(start_s * sample_rate)
    length = max(0, round(duration_s * sample_rate))
    window = samples[start:start + length]
    if not window:
        return -math.inf
    mean_square = sum((sample * gain) ** 2 for sample in window) / len(window)
    rms = math.sqrt(mean_square) / 32768.0
    return 20 * math.log10(rms) if rms else -math.inf


def format_dbfs(value):
    return "-inf" if math.isinf(value) and value < 0 else f"{value:.2f}"


def main():
    manifest = load_json(MANIFEST_PATH)
    answer_key = load_json(ANSWER_KEY_PATH)
    id_to_kana = {
        key.split("|")[1]: value["char"]
        for key, value in answer_key.items()
        if key.startswith("audio1char|") and value.get("pool") == "cand108"
    }

    old_silent = 0
    new_silent = 0
    stimuli = manifest.get("stimuli", [])
    print("id\tかな\t旧dBFS\t新dBFS")
    for stim in stimuli:
        stim_id = stim["id"]
        kana = id_to_kana.get(stim_id)
        if kana is None:
            raise RuntimeError(f"id={stim_id!r}: cand108 のかな対応がありません")
        if "gate_onset_ms" not in stim or "gate_gain" not in stim:
            raise RuntimeError(f"id={stim_id!r}: gate_onset_ms または gate_gain がありません")

        sample_rate, samples = decode_mp3(STIMULI_DIR / stim["file"])
        char_onset = stim["char_onset_s"]
        char_duration = stim["char_dur_s"]
        onset_s = stim["gate_onset_ms"] / 1000
        old_dbfs = window_dbfs(samples, sample_rate, char_onset, char_duration * 0.05)
        new_dbfs = window_dbfs(
            samples,
            sample_rate,
            char_onset + onset_s,
            (char_duration - onset_s) * 0.05,
            stim["gate_gain"],
        )
        old_silent += old_dbfs < -50
        new_silent += new_dbfs < -50
        print(f"{stim_id}\t{kana}\t{format_dbfs(old_dbfs)}\t{format_dbfs(new_dbfs)}")

    total = len(stimuli)
    print(f"-50dBFS未満(実質無音)の窓の数: 旧={old_silent}/{total} 新={new_silent}/{total}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"エラー: {error}", file=sys.stderr)
        raise SystemExit(1)
