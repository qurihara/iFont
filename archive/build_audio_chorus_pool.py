"""
Build the public AUDIO stimulus pool and merge the answers into the shared
answer key. The auditory analog of build_stimulus_pool.py.

Source: audio_stimuli_<VOICE>_<QSET>/k<idx>/<char>.mp3
Each stimulus id:
    stimulus_id = sha1("audio|<voice>|f1|<qset>|<kidx>|<char>|SECRET_SALT")[:12]
The "audio|" prefix + voice guarantees audio ids never collide with the
visual ids (which start "FONT|f1|...").

Outputs:
    experiment/audio_stimuli/<stimulus_id>.mp3       (public)
    experiment/audio_manifest.json                   (public: id, q_set, k...)
    answer_key.json                                  (server-side, MERGED)

answer_key.json is SHARED between the visual and audio pools so the GAS
backend needs only one ANSWER_KEY property. This builder MERGES audio
entries into any existing answer_key.json rather than overwriting it, so run
the visual build_stimulus_pool.py first (or in any order) — audio ids are
disjoint. Each entry carries modality="audio" / mode="f1_audio".

Requires env var SECRET_SALT (any string). Pass via --salt or env.

Usage:
    python build_audio_pool.py --salt $SECRET_SALT                 # voice=Kyoko, qset=all
    python build_audio_pool.py --salt $SECRET_SALT --qset all karuta --voice Kyoko
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

import ifont_common as C

ROOT = Path(__file__).resolve().parent
DEFAULT_VOICE = "Kyoko"
MODE = "f1_audio"
MODALITY = "audio"


def stimulus_id(voice: str, q_set: str, k_index: int,
                char: str, salt: str) -> str:
    payload = f"audio|{voice}|f1|{q_set}|{k_index}|{char}|{salt}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def build_for(voice: str, q_set: str, salt: str,
              out_stimuli: Path, manifest_entries: list,
              answer_key: dict, seen_ids: set) -> int:
    src_root = ROOT / f"audio_stimuli_{voice}_{q_set}"
    if not src_root.exists():
        print(f"ERROR: source audio not found: {src_root}\n"
              f"  run: python make_audio_stimuli.py --voice {voice} "
              f"--qset {q_set}", file=sys.stderr)
        return 2

    chars = C.CHARSET_FOR[q_set]
    n = C.n_distractors(q_set)
    added = 0
    for k_index, k in enumerate(C.K_GRID):
        r = C.k_to_r(k, n)
        k_dir = src_root / C.k_label(k_index)
        for char in chars:
            src_mp3 = k_dir / f"{char}.mp3"
            if not src_mp3.exists():
                print(f"  missing source: {src_mp3}", file=sys.stderr)
                continue
            sid = stimulus_id(voice, q_set, k_index, char, salt)
            if sid in seen_ids:
                print(f"  ! hash collision: {sid}", file=sys.stderr)
                continue
            seen_ids.add(sid)

            shutil.copy(src_mp3, out_stimuli / f"{sid}.mp3")

            k_json = None if math.isinf(k) else k
            manifest_entries.append({
                "id": sid,
                "modality": MODALITY,
                "q_set": q_set,
                "k_index": k_index,
                "k": k_json,        # null == infinity (target-only / catch)
                "r": round(r, 4),
            })
            answer_key[sid] = {
                "answer": char,
                "char": char,
                "modality": MODALITY,
                "voice": voice,
                "q_set": q_set,
                "k_index": k_index,
                "k": k_json,
                "r": round(r, 4),
                "mode": MODE,
            }
            added += 1
    print(f"  {voice}/{q_set}: {added} audio stimuli")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salt", default=os.environ.get("SECRET_SALT", ""),
                    help="Secret salt for hashing (env: SECRET_SALT)")
    ap.add_argument("--voice", default=DEFAULT_VOICE,
                    help=f"Voice tag (default: {DEFAULT_VOICE})")
    ap.add_argument("--qset", nargs="+", default=["all"],
                    choices=list(C.Q_SETS),
                    help="Question set(s) to include (default: all)")
    args = ap.parse_args()

    if not args.salt:
        print("ERROR: SECRET_SALT not provided (use --salt or env var).",
              file=sys.stderr)
        return 1

    out_stimuli = ROOT / "experiment" / "audio_stimuli"
    out_stimuli.mkdir(parents=True, exist_ok=True)

    # MERGE into existing answer_key.json (shared with the visual pool).
    answer_key_path = ROOT / "answer_key.json"
    answer_key: dict = {}
    if answer_key_path.exists():
        with answer_key_path.open(encoding="utf-8") as f:
            answer_key = json.load(f)
        print(f"  merging into existing answer_key.json "
              f"({len(answer_key)} entries)")

    manifest_entries: list = []
    seen_ids: set = set(answer_key.keys())

    rc = 0
    for q in args.qset:
        rc = build_for(args.voice, q, args.salt, out_stimuli,
                       manifest_entries, answer_key, seen_ids) or rc
    if not manifest_entries:
        print("ERROR: no audio stimuli built.", file=sys.stderr)
        return rc or 3

    manifest_entries.sort(key=lambda e: e["id"])

    manifest = {
        "version": "2.0",
        "modality": MODALITY,
        "voice": args.voice,
        "mode": MODE,
        "q_sets": sorted(set(e["q_set"] for e in manifest_entries)),
        "k_grid": [C.k_str(k) for k in C.K_GRID],
        "stimuli": manifest_entries,
    }

    manifest_path = ROOT / "experiment" / "audio_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n  wrote {manifest_path} ({len(manifest_entries)} stimuli)")

    with answer_key_path.open("w", encoding="utf-8") as f:
        json.dump(answer_key, f, ensure_ascii=False, indent=2)
    print(f"  wrote {answer_key_path} (server-side only, .gitignore'd! "
          f"now {len(answer_key)} total entries)")

    print(f"\nDone. {len(manifest_entries)} audio stimuli at {out_stimuli}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
