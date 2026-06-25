"""
Build the public AUDIO stimulus pool (truncation model) and merge the answers
into the shared answer key.

Source: audio_stimuli_trunc_<VOICE>/f<idx>/<char>.mp3   (84 × 21 = 1764)
Each stimulus id:
    stimulus_id = sha1("audiotrunc|<voice>|<fracidx>|<char>|SECRET_SALT")[:12]

Truncation clips do NOT depend on the candidate set, so one pool serves both
q_sets. Each manifest entry is tagged with the q_sets it is valid for
(a karuta char -> ["all","karuta"]; a non-karuta char -> ["all"]); the client
filters by its deployment Q_SET. The answer (char) lives only server-side.

Outputs:
    experiment/audio_stimuli/<stimulus_id>.mp3       (public)
    experiment/audio_manifest.json                   (public: id, frac, q_sets)
    answer_key.json                                  (server-side, MERGED)

answer_key.json is SHARED with the visual pool; audio ids carry the
"audiotrunc|..." hash prefix so they never collide. Entries are tagged
modality="audio" / mode="f1_audio_trunc".

Requires env var SECRET_SALT. Pass via --salt or env.

Usage:
    python build_audio_pool.py --salt $SECRET_SALT            # voice=Kyoko
    python build_audio_pool.py --salt $SECRET_SALT --voice Kyoko
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import ifont_common as C

ROOT = Path(__file__).resolve().parent
DEFAULT_VOICE = "Kyoko"
MODE = "f1_audio_trunc"
MODALITY = "audio"

KARUTA_SET = set(C.KARUTA_CHARS)


def stimulus_id(voice: str, frac_index: int, char: str, salt: str) -> str:
    payload = f"audiotrunc|{voice}|{frac_index}|{char}|{salt}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def q_sets_for(char: str) -> list:
    """Which response sets this char belongs to (the clip itself is shared)."""
    return ["all", "karuta"] if char in KARUTA_SET else ["all"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salt", default=os.environ.get("SECRET_SALT", ""))
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    args = ap.parse_args()
    if not args.salt:
        print("ERROR: SECRET_SALT not provided (use --salt or env var).", file=sys.stderr)
        return 1

    src_root = ROOT / f"audio_stimuli_trunc_{args.voice}"
    if not src_root.exists():
        print(f"ERROR: source not found: {src_root}\n"
              f"  run: python make_audio_stimuli.py --voice {args.voice}", file=sys.stderr)
        return 2

    out_stimuli = ROOT / "experiment" / "audio_stimuli"
    # Replace the (deprecated chorus) audio pool entirely.
    if out_stimuli.exists():
        shutil.rmtree(out_stimuli)
    out_stimuli.mkdir(parents=True, exist_ok=True)

    # MERGE into the shared answer_key.json, but first drop any stale audio
    # entries (the deprecated chorus ids) so the key reflects only the current
    # truncation pool + the visual pool.
    answer_key_path = ROOT / "answer_key.json"
    answer_key = {}
    if answer_key_path.exists():
        with answer_key_path.open(encoding="utf-8") as f:
            answer_key = json.load(f)
        before = len(answer_key)
        answer_key = {k: v for k, v in answer_key.items()
                      if v.get("modality") != "audio"}
        print(f"  merging into answer_key.json: {before} entries, "
              f"dropped {before - len(answer_key)} stale audio entries")

    manifest_entries, seen = [], set(answer_key.keys())
    for frac_index, frac in enumerate(C.FRAC_GRID):
        f_dir = src_root / C.frac_label(frac_index)
        for char in C.ALL_CHARS:
            src = f_dir / f"{char}.mp3"
            if not src.exists():
                print(f"  missing: {src}", file=sys.stderr); continue
            sid = stimulus_id(args.voice, frac_index, char, args.salt)
            if sid in seen:
                print(f"  ! collision {sid}", file=sys.stderr); continue
            seen.add(sid)
            shutil.copy(src, out_stimuli / f"{sid}.mp3")
            qs = q_sets_for(char)
            manifest_entries.append({
                "id": sid, "modality": MODALITY,
                "frac_index": frac_index, "frac": frac, "q_sets": qs,
            })
            answer_key[sid] = {
                "answer": char, "char": char, "modality": MODALITY,
                "voice": args.voice, "frac_index": frac_index, "frac": frac,
                "q_sets": qs, "mode": MODE,
            }

    manifest_entries.sort(key=lambda e: e["id"])
    manifest = {
        "version": "3.0", "modality": MODALITY, "voice": args.voice, "mode": MODE,
        "frac_grid": C.FRAC_GRID,
        "n_choices": {q: len(C.CHARSET_FOR[q]) for q in C.Q_SETS},
        "stimuli": manifest_entries,
    }
    mpath = ROOT / "experiment" / "audio_manifest.json"
    with mpath.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n  wrote {mpath} ({len(manifest_entries)} stimuli)")
    with answer_key_path.open("w", encoding="utf-8") as f:
        json.dump(answer_key, f, ensure_ascii=False, indent=2)
    print(f"  wrote {answer_key_path} (.gitignore'd, now {len(answer_key)} total)")
    print(f"\nDone. {len(manifest_entries)} audio stimuli at {out_stimuli}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
