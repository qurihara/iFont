"""
Build the public stimulus pool and the secret answer key from generated
F1 still PNGs.

For each (FONT_TAG, mode='f1', char, r) tuple:
  stimulus_id = sha1("FONT|mode|char|r|SECRET_SALT")[:12]
  copy the source PNG to experiment/stimuli/<stimulus_id>.png
  add manifest entry: {id, choices: [target + 3 random distractors, shuffled]}
  add answer_key entry: {id: {answer, char, r, font, mode}}

manifest.json is shipped to the client (no answers).
answer_key.json is server-side only (.gitignore must include it).

Requires env var SECRET_SALT (any string). Pass via --salt or env.
"""

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
from pathlib import Path

# Mirror constants from make_subtractive_stills.py
ROOT = Path(__file__).resolve().parent
FONT_TAG = "bizudgothic"
MODE = "f1"
R_LEVELS = list(range(0, 101, 10))

SEION = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん")
DAKUTEN = list("がぎぐげござじずぜぞだぢづでどばびぶべぼ")
HANDAKU = list("ぱぴぷぺぽ")
SMALL = list("ぁぃぅぇぉっゃゅょゎ")
KOGO = list("ゐゑ")
OTHER = list("ゔ")
ALL_CHARS = SEION + DAKUTEN + HANDAKU + SMALL + KOGO + OTHER

N_CHOICES = 4  # target + 3 distractors


def stimulus_id(font: str, mode: str, char: str, r: int, salt: str) -> str:
    payload = f"{font}|{mode}|{char}|{r}|{salt}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def pick_choices(target: str, rng: random.Random) -> list[str]:
    """Pick 3 random distractors from ALL_CHARS minus target, return 4 shuffled."""
    pool = [c for c in ALL_CHARS if c != target]
    distractors = rng.sample(pool, k=N_CHOICES - 1)
    choices = [target, *distractors]
    rng.shuffle(choices)
    return choices


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salt", default=os.environ.get("SECRET_SALT", ""),
                    help="Secret salt for hashing (env: SECRET_SALT)")
    ap.add_argument("--font", default=FONT_TAG,
                    help=f"Font tag (default: {FONT_TAG})")
    args = ap.parse_args()

    if not args.salt:
        print("ERROR: SECRET_SALT not provided (use --salt or env var).", file=sys.stderr)
        return 1

    font_tag = args.font
    src_root = ROOT / f"subtractive_stills_{font_tag}"
    if not src_root.exists():
        print(f"ERROR: source stills not found: {src_root}", file=sys.stderr)
        return 2

    out_stimuli = ROOT / "experiment" / "stimuli"
    out_stimuli.mkdir(parents=True, exist_ok=True)

    manifest_entries = []
    answer_key = {}

    # Seed choice selection deterministically per stimulus
    seen_ids = set()
    for r in R_LEVELS:
        r_dir = src_root / f"r{r:03d}"
        for char in ALL_CHARS:
            src_png = r_dir / f"{char}.png"
            if not src_png.exists():
                print(f"  missing source: {src_png}", file=sys.stderr)
                continue
            sid = stimulus_id(font_tag, MODE, char, r, args.salt)
            if sid in seen_ids:
                print(f"  ! hash collision: {sid}", file=sys.stderr)
                continue
            seen_ids.add(sid)

            # Per-stimulus deterministic choice ordering (seeded by sid for repro)
            rng = random.Random(f"choices:{sid}")
            choices = pick_choices(char, rng)

            # Copy PNG
            dst = out_stimuli / f"{sid}.png"
            shutil.copy(src_png, dst)

            manifest_entries.append({"id": sid, "choices": choices, "r": r})
            answer_key[sid] = {
                "answer": char,
                "char": char,
                "r": r,
                "font": font_tag,
                "mode": MODE,
            }

    # Shuffle manifest order (the client samples from this, so order shouldn't matter,
    # but a stable canonical sort makes diffs cleaner).
    manifest_entries.sort(key=lambda e: e["id"])

    manifest = {
        "version": "1.0",
        "font_tag": font_tag,
        "mode": MODE,
        "r_levels": R_LEVELS,
        "n_choices": N_CHOICES,
        "stimuli": manifest_entries,
    }

    manifest_path = ROOT / "experiment" / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"  wrote {manifest_path} ({len(manifest_entries)} stimuli)")

    answer_key_path = ROOT / "answer_key.json"
    with answer_key_path.open("w", encoding="utf-8") as f:
        json.dump(answer_key, f, ensure_ascii=False, indent=2)
    print(f"  wrote {answer_key_path} (server-side only, .gitignore!)")

    print(f"\nDone. {len(seen_ids)} stimuli at {out_stimuli}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
