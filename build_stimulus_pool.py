"""
Build the public stimulus pool and the secret answer key from the F1 k-grid
stills (subtractive_stills_<FONT>_<QSET>/k<idx>/<char>.png).

Grid-mode (no distractors): the client renders a fixed 50音 grid restricted to
the active q_set, so a stimulus carries NO choices list. Each stimulus is

  stimulus_id = sha1("FONT|mode|qset|kidx|char|SECRET_SALT")[:12]

The PNG is copied to experiment/stimuli/<stimulus_id>.png. The answer (char)
lives only in the server-side answer_key.json (.gitignore'd).

manifest.json (shipped to the client) entries:
  {id, q_set, k_index, k, r}              # NO answer, NO choices
answer_key.json (server-side only):
  {id: {answer, char, q_set, k_index, k, r, font, mode}}

Requires env var SECRET_SALT (any string). Pass via --salt or env.

Usage:
    python build_stimulus_pool.py --salt $SECRET_SALT                 # font=bizudgothic, qset=all
    python build_stimulus_pool.py --salt $SECRET_SALT --qset all karuta
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
DEFAULT_FONT = "bizudgothic"
MODE = "f1"


def stimulus_id(font: str, mode: str, q_set: str, k_index: int,
                char: str, salt: str) -> str:
    payload = f"{font}|{mode}|{q_set}|{k_index}|{char}|{salt}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def build_for(font_tag: str, q_set: str, salt: str,
              out_stimuli: Path, manifest_entries: list,
              answer_key: dict, seen_ids: set) -> int:
    src_root = ROOT / f"subtractive_stills_{font_tag}_{q_set}"
    if not src_root.exists():
        print(f"ERROR: source stills not found: {src_root}\n"
              f"  run: python make_subtractive_stills.py --font {font_tag} "
              f"--qset {q_set}", file=sys.stderr)
        return 2

    chars = C.CHARSET_FOR[q_set]
    n = C.n_distractors(q_set)
    added = 0
    for k_index, k in enumerate(C.K_GRID):
        r = C.k_to_r(k, n)
        k_dir = src_root / C.k_label(k_index)
        for char in chars:
            src_png = k_dir / f"{char}.png"
            if not src_png.exists():
                print(f"  missing source: {src_png}", file=sys.stderr)
                continue
            sid = stimulus_id(font_tag, MODE, q_set, k_index, char, salt)
            if sid in seen_ids:
                print(f"  ! hash collision: {sid}", file=sys.stderr)
                continue
            seen_ids.add(sid)

            shutil.copy(src_png, out_stimuli / f"{sid}.png")

            k_json = None if math.isinf(k) else k
            manifest_entries.append({
                "id": sid,
                "q_set": q_set,
                "k_index": k_index,
                "k": k_json,        # null == infinity (target-only / catch)
                "r": round(r, 4),
            })
            answer_key[sid] = {
                "answer": char,
                "char": char,
                "q_set": q_set,
                "k_index": k_index,
                "k": k_json,
                "r": round(r, 4),
                "font": font_tag,
                "mode": MODE,
            }
            added += 1
    print(f"  {font_tag}/{q_set}: {added} stimuli")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salt", default=os.environ.get("SECRET_SALT", ""),
                    help="Secret salt for hashing (env: SECRET_SALT)")
    ap.add_argument("--font", default=DEFAULT_FONT,
                    help=f"Font tag (default: {DEFAULT_FONT})")
    ap.add_argument("--qset", nargs="+", default=["all"],
                    choices=list(C.Q_SETS),
                    help="Question set(s) to include (default: all)")
    args = ap.parse_args()

    if not args.salt:
        print("ERROR: SECRET_SALT not provided (use --salt or env var).",
              file=sys.stderr)
        return 1

    out_stimuli = ROOT / "experiment" / "stimuli"
    out_stimuli.mkdir(parents=True, exist_ok=True)

    manifest_entries: list = []
    answer_key: dict = {}
    seen_ids: set = set()

    rc = 0
    for q in args.qset:
        rc = build_for(args.font, q, args.salt, out_stimuli,
                       manifest_entries, answer_key, seen_ids) or rc
    if not manifest_entries:
        print("ERROR: no stimuli built.", file=sys.stderr)
        return rc or 3

    # Stable canonical sort for clean diffs (client samples randomly anyway).
    manifest_entries.sort(key=lambda e: e["id"])

    manifest = {
        "version": "2.0",
        "font_tag": args.font,
        "mode": MODE,
        "q_sets": sorted(set(e["q_set"] for e in manifest_entries)),
        "k_grid": [C.k_str(k) for k in C.K_GRID],
        "n_distractors": {q: C.n_distractors(q) for q in C.Q_SETS},
        "stimuli": manifest_entries,
    }

    manifest_path = ROOT / "experiment" / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n  wrote {manifest_path} ({len(manifest_entries)} stimuli)")

    answer_key_path = ROOT / "answer_key.json"
    with answer_key_path.open("w", encoding="utf-8") as f:
        json.dump(answer_key, f, ensure_ascii=False, indent=2)
    print(f"  wrote {answer_key_path} (server-side only, .gitignore'd!)")

    print(f"\nDone. {len(seen_ids)} stimuli at {out_stimuli}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
