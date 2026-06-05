"""
Generate static F1 (Bayesian, subtractive) stills at 11 levels of r ∈ {0,10,...,100}.

Target opacity = r/100 (smooth real-valued, not stepwise from |V|).
Each non-target opacity = (1 - r/100) / 83.
At r=0: all 84 characters at α = 1/84 (uniform mist).
At r=100: only target visible at α = 1.

Switch the rendering font by editing FONT_TAG below.

Output:
    subtractive_stills_<FONT_TAG>/r<NNN>/<char>.png
    (11 levels × 84 chars = 924 PNGs per font)
"""

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent

# -------------------------------------------------------------------------
# Configure font here. Change FONT_TAG to swap fonts; everything else
# stays the same.
# -------------------------------------------------------------------------
FONT_TAG = "bizudgothic"

IMAGE_DIR_FOR = {
    "mplus_rounded1c": "stroke_mask_images",
    "bizudgothic":     "stroke_mask_images_bizud",
    "bizudmincho":     "stroke_mask_images_bizudmincho",
    "notosansjp":      "stroke_mask_images_notosansjp",
    "notoserifjp":     "stroke_mask_images_notoserifjp",
    "mplus1p":         "stroke_mask_images_mplus1p",
}

R_LEVELS = list(range(0, 101, 10))   # 0,10,20,...,100  (11 levels)

# Character order (same as generate.py / make_subtractive_videos.py)
SEION = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん")
DAKUTEN = list("がぎぐげござじずぜぞだぢづでどばびぶべぼ")
HANDAKU = list("ぱぴぷぺぽ")
SMALL = list("ぁぃぅぇぉっゃゅょゎ")
KOGO = list("ゐゑ")
OTHER = list("ゔ")
ALL_CHARS = SEION + DAKUTEN + HANDAKU + SMALL + KOGO + OTHER  # 84

IMG_SIZE = 256


def load_full_images(image_dir: Path) -> dict[str, np.ndarray]:
    """Load p100.png for each char as ink-density [0..1] array (1=ink, 0=bg)."""
    imgs = {}
    for ch in ALL_CHARS:
        path = image_dir / "full" / ch / "p100.png"
        arr = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
        imgs[ch] = (255.0 - arr) / 255.0
    return imgs


def render_frame(ink_imgs: dict, alpha: dict[str, float]) -> np.ndarray:
    """Additive composite with clipping (same as make_subtractive_videos.py)."""
    darkness = np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.float32)
    for c, a in alpha.items():
        if a > 0:
            darkness += a * ink_imgs[c]
    darkness = np.clip(darkness, 0.0, 1.0)
    return (255.0 * (1.0 - darkness)).astype(np.uint8)


def alphas_for_r(target: str, r: int) -> dict[str, float]:
    """F1 Bayesian smooth: α_target = r/100, α_distractor = (1-r/100)/83."""
    a_target = r / 100.0
    a_other = (1.0 - a_target) / 83.0
    return {c: (a_target if c == target else a_other) for c in ALL_CHARS}


def main() -> int:
    if FONT_TAG not in IMAGE_DIR_FOR:
        print(f"Unknown FONT_TAG: {FONT_TAG}", file=sys.stderr)
        return 1
    image_dir = ROOT / IMAGE_DIR_FOR[FONT_TAG]
    if not image_dir.exists():
        print(f"Source images missing: {image_dir}", file=sys.stderr)
        return 2

    out_root = ROOT / f"subtractive_stills_{FONT_TAG}"
    print(f"Font: {FONT_TAG}")
    print(f"Source: {image_dir.name}")
    print(f"Output: {out_root.name}")
    print(f"R levels: {R_LEVELS}, chars: {len(ALL_CHARS)} → "
          f"total {len(R_LEVELS) * len(ALL_CHARS)} PNGs\n")

    t0 = time.time()
    ink_imgs = load_full_images(image_dir)
    print(f"  loaded {len(ink_imgs)} char images in {time.time() - t0:.1f}s")

    t0 = time.time()
    count = 0
    for r in R_LEVELS:
        r_dir = out_root / f"r{r:03d}"
        r_dir.mkdir(parents=True, exist_ok=True)
        for target in ALL_CHARS:
            alpha = alphas_for_r(target, r)
            frame = render_frame(ink_imgs, alpha)
            Image.fromarray(frame, mode="L").save(r_dir / f"{target}.png", optimize=True)
            count += 1
    print(f"  generated {count} PNGs in {time.time() - t0:.1f}s")
    print(f"\nDone. Output at {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
