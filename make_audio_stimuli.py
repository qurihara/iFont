"""
Generate f_audio_kana stimuli — single-kana TEMPORAL GATING (truncation).

The ADOPTED auditory model (replaces the deprecated chorus model in
archive/). A clean read-aloud of one kana is truncated at frac% of its voiced
duration and the participant identifies it from the 50音 grid. This is the
single-kana analog of Kikiwake ("how much of the reading until you can tell"),
and pairs with f_visual_kana to build the audio↔visual transfer g.

  voiced region [t0, t1]  (onset..offset, via RMS trim for now; MFA later)
  for frac in FRAC_GRID:  play [t0, t0 + frac/100·(t1-t0)] with a short
                          fade-out to avoid a click at the cut.
  frac = 0   -> silence (chance anchor)
  frac = 100 -> full clean kana (catch)

Truncation does NOT depend on the candidate set, so a single pool of
84 × 21 = 1764 clips serves both q_sets; the response grid differs by q_set.

Base recordings are synthesised once with macOS `say -v <VOICE>` and cached
under audio_base_<voice>/ (shared with the chorus model / the pilot).

Output:
    audio_stimuli_trunc_<VOICE>/f<idx>/<char>.mp3   (84 × 21 = 1764)

TODO (refinement): replace the RMS onset/offset with MFA (Montreal Forced
Aligner) word/phone boundaries — kikiwake's repo has an MFA setup. The
truncation fractions would then be measured from the true speech onset.

Requires: macOS `say`, `ffmpeg`, numpy.

Usage:
    python make_audio_stimuli.py                 # voice=Kyoko
    python make_audio_stimuli.py --voice Otoya
    python make_audio_stimuli.py --limit 5       # first 5 chars (preview)
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

DEFAULT_VOICE = "Kyoko"
SR = 24000
SILENCE_THRESH = 0.02       # relative-to-peak amplitude for onset/offset
REF_RMS = 0.12              # normalise each clip to this RMS
FADE_MS = 8                 # fade-out length at the truncation cut (anti-click)


# ---- WAV I/O (stdlib) -----------------------------------------------------

def read_wav_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        n, ch = w.getnframes(), w.getnchannels()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x


def write_wav_mono(path: Path, x: np.ndarray, sr: int = SR) -> None:
    xi = (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(xi.tobytes())


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x * x)) + 1e-12)


def voiced_bounds(x: np.ndarray, thresh_rel: float = SILENCE_THRESH):
    """Return (i0, i1): first/last sample above thresh*peak (the voiced span)."""
    if x.size == 0:
        return 0, 0
    peak = float(np.max(np.abs(x))) + 1e-12
    mask = np.abs(x) > thresh_rel * peak
    if not mask.any():
        return 0, len(x)
    i0 = int(np.argmax(mask))
    i1 = int(len(mask) - np.argmax(mask[::-1]))
    return i0, i1


# ---- Base synthesis (say -> aiff -> ffmpeg wav), cached -------------------

def synth_base(char: str, voice: str, cache_dir: Path) -> np.ndarray:
    cache_dir.mkdir(parents=True, exist_ok=True)
    wav_path = cache_dir / f"{char}.wav"
    if wav_path.exists():
        return read_wav_mono(wav_path)
    with tempfile.TemporaryDirectory() as td:
        aiff = Path(td) / "x.aiff"
        raw = Path(td) / "x.wav"
        subprocess.run(["say", "-v", voice, "-o", str(aiff), char], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
                        "-ac", "1", "-ar", str(SR), str(raw)], check=True)
        x = read_wav_mono(raw)
    # Normalise the FULL clip's RMS (keep silence; truncation uses voiced bounds).
    x = x * (REF_RMS / rms(x))
    write_wav_mono(wav_path, x)
    return x


def truncate(x: np.ndarray, i0: int, i1: int, frac: int) -> np.ndarray:
    """Return [i0 .. i0 + frac%·(i1-i0)] with a short fade-out. frac=0 -> empty."""
    span = i1 - i0
    end = i0 + int(round(span * frac / 100.0))
    if end <= i0:
        return np.zeros(1, dtype=np.float32)   # silence anchor
    seg = x[i0:end].copy()
    fade = min(int(SR * FADE_MS / 1000), len(seg))
    if fade > 1:
        seg[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return seg


def wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
                    "-codec:a", "libmp3lame", "-q:a", "5", str(mp3_path)],
                   check=True)


def generate(voice: str, limit: int | None = None) -> int:
    # Audio uses only the acoustically-distinct set (清音46+濁20+半5+ゔ = 72).
    # ゐゑ/ゃゅょ/っ/小書き母音 collapse onto a base sound or are silent in
    # isolation (the C1=∅ slice), so they are excluded here; they are recovered
    # later by the C1≠∅ 2-char task (MFA) or assumed equal to their base char.
    chars = C.AUDIO_ALL if not limit else C.AUDIO_ALL[:limit]
    cache_dir = ROOT / f"audio_base_{voice}"
    out_root = ROOT / f"audio_stimuli_trunc_{voice}"

    print(f"Voice: {voice}  chars: {len(chars)}{' [LIMITED]' if limit else ''}")
    print(f"Output: {out_root.name}")
    print(f"frac-grid: {C.FRAC_GRID} -> {len(C.FRAC_GRID) * len(chars)} mp3s\n")

    t0 = time.time()
    bounds = {}
    for ch in chars:
        x = synth_base(ch, voice, cache_dir)
        bounds[ch] = (x, *voiced_bounds(x))
    print(f"  synthesised/loaded {len(bounds)} base clips in {time.time()-t0:.1f}s")

    t0 = time.time()
    count = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "t.wav"
        for idx, frac in enumerate(C.FRAC_GRID):
            f_dir = out_root / C.frac_label(idx)
            f_dir.mkdir(parents=True, exist_ok=True)
            for ch in chars:
                x, i0, i1 = bounds[ch]
                seg = truncate(x, i0, i1, frac)
                write_wav_mono(tmp, seg)
                wav_to_mp3(tmp, f_dir / f"{ch}.mp3")
                count += 1
    print(f"  generated {count} mp3s in {time.time()-t0:.1f}s")
    print(f"Done. Output at {out_root}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default=DEFAULT_VOICE,
                    help=f"macOS say voice (default: {DEFAULT_VOICE})")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only the first N chars (preview/testing)")
    args = ap.parse_args()
    return generate(args.voice, args.limit)


if __name__ == "__main__":
    sys.exit(main())
