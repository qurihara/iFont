"""
Generate static F1 (Bayesian, subtractive) stills on the frozen 11-level
k-grid, for one or both question sets (全字 84 / 競技かるた 48).

For a target T, parameter r (derived from k via the active set's N):
    target opacity      = r/100
    each non-target     = (1 - r/100) / N
    darkness(x,y)       = clip( r/100 * ink_T + (1-r/100)/N * Σ ink_other , 0..1)

The non-target sum runs over the ACTIVE set only, so the same (char, k)
renders differently for q_set='all' (N=83) vs 'karuta' (N=47). That is the
intended behaviour and is why stills are generated per q_set.

Output:
    subtractive_stills_<FONT_TAG>_<QSET>/k<idx>/<char>.png
    (11 k-levels × |set| chars  =  924 PNGs for 'all', 528 for 'karuta')

Usage:
    python make_subtractive_stills.py                  # FONT_TAG below, q_set=all
    python make_subtractive_stills.py --font bizudgothic --qset all karuta
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

import ifont_common as C

ROOT = Path(__file__).resolve().parent

# Default font when --font is not passed.
FONT_TAG = "bizudgothic"

IMG_SIZE = 256


def load_full_images(image_dir: Path, chars: list) -> dict:
    """Load p100.png for each char as ink-density [0..1] array (1=ink, 0=bg)."""
    imgs = {}
    for ch in chars:
        path = image_dir / "full" / ch / "p100.png"
        arr = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
        imgs[ch] = (255.0 - arr) / 255.0
    return imgs


def render_frame(ink_imgs: dict, target: str, r: float, n: int,
                 chars: list, ink_sum: np.ndarray) -> np.ndarray:
    """Additive F1 composite with clipping, over the active char set."""
    a_target = r / 100.0
    a_other = (1.0 - a_target) / n
    tgt = ink_imgs[target]
    # Σ ink over distractors = (Σ ink over all active) - ink_target
    distr_sum = ink_sum - tgt
    darkness = a_target * tgt + a_other * distr_sum
    np.clip(darkness, 0.0, 1.0, out=darkness)
    return (255.0 * (1.0 - darkness)).astype(np.uint8)


def generate_for(font_tag: str, q_set: str) -> int:
    if font_tag not in C.IMAGE_DIR_FOR:
        print(f"Unknown font: {font_tag}", file=sys.stderr)
        return 1
    if q_set not in C.CHARSET_FOR:
        print(f"Unknown q_set: {q_set}", file=sys.stderr)
        return 1

    image_dir = ROOT / C.IMAGE_DIR_FOR[font_tag]
    if not image_dir.exists():
        print(f"Source images missing: {image_dir}", file=sys.stderr)
        return 2

    chars = C.CHARSET_FOR[q_set]
    n = C.n_distractors(q_set)
    out_root = ROOT / f"subtractive_stills_{font_tag}_{q_set}"

    print(f"Font: {font_tag}  q_set: {q_set}  (N={n}, chars={len(chars)})")
    print(f"Source: {image_dir.name}")
    print(f"Output: {out_root.name}")
    print(f"k-grid: {[C.k_str(k) for k in C.K_GRID]} -> "
          f"{len(C.K_GRID) * len(chars)} PNGs\n")

    t0 = time.time()
    ink_imgs = load_full_images(image_dir, chars)
    ink_sum = np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.float32)
    for ch in chars:
        ink_sum += ink_imgs[ch]
    print(f"  loaded {len(ink_imgs)} char images in {time.time() - t0:.1f}s")

    t0 = time.time()
    count = 0
    for idx, k in enumerate(C.K_GRID):
        r = C.k_to_r(k, n)
        k_dir = out_root / C.k_label(idx)
        k_dir.mkdir(parents=True, exist_ok=True)
        for target in chars:
            frame = render_frame(ink_imgs, target, r, n, chars, ink_sum)
            Image.fromarray(frame, mode="L").save(
                k_dir / f"{target}.png", optimize=True)
            count += 1
    print(f"  generated {count} PNGs in {time.time() - t0:.1f}s")
    print(f"Done. Output at {out_root}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", default=FONT_TAG,
                    help=f"Font tag (default: {FONT_TAG})")
    ap.add_argument("--qset", nargs="+", default=["all"],
                    choices=list(C.Q_SETS),
                    help="Question set(s) to generate (default: all)")
    args = ap.parse_args()

    rc = 0
    for q in args.qset:
        rc = generate_for(args.font, q) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
