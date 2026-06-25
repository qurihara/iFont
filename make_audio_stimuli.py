"""
Generate the AUDITORY analog of the F1 subtractive stills: "音声もやもや".

The visual F1 model superimposes all candidate kana and raises the target's
opacity (k = target/distractor opacity ratio). The audio analog mixes the
read-aloud audio of all candidate kana into a chorus and raises the target's
AMPLITUDE, with the SAME k-grid and the SAME k formula:

    target amplitude      = r/100
    each non-target       = (1 - r/100) / N
    mix(t) = a_target * x_T + a_other * Σ_{c != T} x_c
    k = a_target / a_other = N * r / (100 - r)     (identical to the visual k)

  k = ∞  (r = 100) -> only the target plays, clear   (catch trial)
  k = 0  (r = 0)   -> equal chorus of all candidates, no target advantage

Because N differs per q_set (83 for 全字 / 47 for 競技かるた), the same
(char, k) renders a different mix per q_set — generated separately, just
like the visual stills.

Base recordings are synthesised once with macOS `say -v <VOICE>` and cached
under audio_base_<voice>/. The voice is swappable (--voice) and recorded in
the output path / stimulus hash so different voices never collide.

Output:
    audio_stimuli_<VOICE>_<QSET>/k<idx>/<char>.mp3
    (11 k-levels × |set| chars = 924 for 'all', 528 for 'karuta')

Requires: macOS `say`, `ffmpeg` on PATH, numpy.

Usage:
    python make_audio_stimuli.py                      # voice=Kyoko, qset=all
    python make_audio_stimuli.py --qset all karuta
    python make_audio_stimuli.py --voice Otoya --qset karuta
"""

import argparse
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

import ifont_common as C

ROOT = Path(__file__).resolve().parent

DEFAULT_VOICE = "Kyoko"     # macOS ja_JP voice
SR = 24000                  # mono sample rate
SILENCE_THRESH = 0.02       # relative-to-peak amplitude for silence trimming
REF_RMS = 0.10              # each base clip normalised to this RMS before mixing
OUT_RMS = 0.12              # final mix RMS target
PEAK_LIMIT = 0.97           # hard peak ceiling after RMS normalisation


# ---- WAV I/O (stdlib only) ------------------------------------------------

def read_wav_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        n = w.getnframes()
        raw = w.readframes(n)
        ch = w.getnchannels()
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x


def write_wav_mono(path: Path, x: np.ndarray, sr: int = SR) -> None:
    xi = np.clip(x, -1.0, 1.0)
    xi = (xi * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(xi.tobytes())


# ---- Signal helpers -------------------------------------------------------

def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x * x)) + 1e-12)


def normalize_rms(x: np.ndarray, target: float) -> np.ndarray:
    return x * (target / rms(x))


def trim_silence(x: np.ndarray, thresh_rel: float = SILENCE_THRESH) -> np.ndarray:
    if x.size == 0:
        return x
    peak = float(np.max(np.abs(x))) + 1e-12
    mask = np.abs(x) > thresh_rel * peak
    if not mask.any():
        return x
    i0 = int(np.argmax(mask))
    i1 = int(len(mask) - np.argmax(mask[::-1]))
    return x[i0:i1]


# ---- Base synthesis (say -> aiff -> ffmpeg wav) ---------------------------

def synth_base(char: str, voice: str, cache_dir: Path) -> np.ndarray:
    """Return the trimmed, RMS-normalised base waveform for one kana,
    caching the processed wav under cache_dir/<char>.wav."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    wav_path = cache_dir / f"{char}.wav"
    if wav_path.exists():
        return read_wav_mono(wav_path)

    with tempfile.TemporaryDirectory() as td:
        aiff = Path(td) / "x.aiff"
        raw_wav = Path(td) / "x.wav"
        subprocess.run(["say", "-v", voice, "-o", str(aiff), char],
                       check=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
             "-ac", "1", "-ar", str(SR), str(raw_wav)],
            check=True)
        x = read_wav_mono(raw_wav)

    x = trim_silence(x)
    x = normalize_rms(x, REF_RMS)
    write_wav_mono(wav_path, x)
    return x


def load_bases(chars: list, voice: str) -> dict:
    cache_dir = ROOT / f"audio_base_{voice}"
    bases = {}
    for ch in chars:
        bases[ch] = synth_base(ch, voice, cache_dir)
    # Pad all to common length (onset-aligned at start).
    max_len = max(len(b) for b in bases.values())
    for ch in chars:
        b = bases[ch]
        if len(b) < max_len:
            bases[ch] = np.pad(b, (0, max_len - len(b)))
    return bases, max_len


# ---- Mixing ---------------------------------------------------------------

def mix_chorus(bases: dict, sum_all: np.ndarray, target: str,
               r: float, n: int) -> np.ndarray:
    """音声もやもや: a_target * x_T + a_other * Σ_{c!=T} x_c, RMS-normalised."""
    a_target = r / 100.0
    a_other = (1.0 - a_target) / n
    # = (a_target - a_other) * x_T + a_other * Σ_all
    mix = (a_target - a_other) * bases[target] + a_other * sum_all
    mix = normalize_rms(mix, OUT_RMS)
    peak = float(np.max(np.abs(mix))) + 1e-12
    if peak > PEAK_LIMIT:
        mix = mix * (PEAK_LIMIT / peak)
    return mix


def wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
         "-codec:a", "libmp3lame", "-q:a", "5", str(mp3_path)],
        check=True)


# ---- Driver ---------------------------------------------------------------

def generate_for(voice: str, q_set: str, limit: int | None = None) -> int:
    if q_set not in C.CHARSET_FOR:
        print(f"Unknown q_set: {q_set}", file=sys.stderr)
        return 1

    chars = C.CHARSET_FOR[q_set]
    if limit:
        chars = chars[:limit]
    n = C.n_distractors(q_set)        # full N for the set (mix uses all candidates)
    out_root = ROOT / f"audio_stimuli_{voice}_{q_set}"

    print(f"Voice: {voice}  q_set: {q_set}  (N={C.n_distractors(q_set)}, "
          f"chars={len(chars)}{' [LIMITED]' if limit else ''})")
    print(f"Output: {out_root.name}")
    print(f"k-grid: {[C.k_str(k) for k in C.K_GRID]} -> "
          f"{len(C.K_GRID) * len(chars)} mp3s\n")

    t0 = time.time()
    # The chorus always mixes the FULL candidate set for this q_set, even when
    # --limit restricts which targets we render (so a limited run is still a
    # faithful preview of the real mix).
    full_chars = C.CHARSET_FOR[q_set]
    bases, _ = load_bases(full_chars, voice)
    sum_all = np.zeros_like(next(iter(bases.values())))
    for ch in full_chars:
        sum_all += bases[ch]
    print(f"  synthesised/loaded {len(bases)} base clips in {time.time()-t0:.1f}s")

    t0 = time.time()
    count = 0
    with tempfile.TemporaryDirectory() as td:
        tmp_wav = Path(td) / "m.wav"
        for idx, k in enumerate(C.K_GRID):
            r = C.k_to_r(k, n)
            k_dir = out_root / C.k_label(idx)
            k_dir.mkdir(parents=True, exist_ok=True)
            for target in chars:
                mix = mix_chorus(bases, sum_all, target, r, n)
                write_wav_mono(tmp_wav, mix)
                wav_to_mp3(tmp_wav, k_dir / f"{target}.mp3")
                count += 1
    print(f"  generated {count} mp3s in {time.time()-t0:.1f}s")
    print(f"Done. Output at {out_root}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default=DEFAULT_VOICE,
                    help=f"macOS say voice (default: {DEFAULT_VOICE})")
    ap.add_argument("--qset", nargs="+", default=["all"],
                    choices=list(C.Q_SETS),
                    help="Question set(s) to generate (default: all)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Render only the first N target chars (preview/testing)")
    args = ap.parse_args()

    rc = 0
    for q in args.qset:
        rc = generate_for(args.voice, q, args.limit) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
