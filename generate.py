"""
Hiragana stroke-pixel random masking image generator.

For each hiragana character and each p in 0..100, generate a 256x256 PNG
where p% of the stroke pixels are visible (cumulatively, in a fixed
random order per character).

Font: M PLUS Rounded 1c Regular (SIL OFL 1.1)
Output: stroke_mask_images/{trial,full}/<char>/p<NNN>.png
"""

import argparse
import csv
import random
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---- Configuration -------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DEFAULT_FONT = ROOT / "fonts" / "MPLUSRounded1c-Regular.ttf"
DEFAULT_OUT = ROOT / "stroke_mask_images"
DEFAULT_CSV = ROOT / "stroke_counts.csv"

IMG_SIZE = 256
FONT_SIZE = 200          # Leaves margin for hiragana descenders/ascenders
STROKE_THRESHOLD = 128   # luminance ≤ this is considered "stroke"

# Hiragana character set: 87 chars
SEION = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん")
DAKUTEN = list("がぎぐげござじずぜぞだぢづでどばびぶべぼ")
HANDAKU = list("ぱぴぷぺぽ")
SMALL = list("ぁぃぅぇぉっゃゅょゎ")
KOGO = list("ゐゑ")
OTHER = list("ゔ")

ALL_CHARS = SEION + DAKUTEN + HANDAKU + SMALL + KOGO + OTHER  # 87 chars

# Phase A (trial) subset
TRIAL_CHARS = list("あいんがぱゐ")
TRIAL_PERCENTS = [0, 10, 25, 50, 75, 90, 100]

# Phase B (full)
FULL_PERCENTS = list(range(0, 101))


# ---- Core ----------------------------------------------------------------


def render_char_bitmap(font: ImageFont.FreeTypeFont, ch: str) -> np.ndarray:
    """Render a single character centered in a white IMG_SIZE square,
    return grayscale (H, W) uint8 ndarray (0=black ink, 255=white bg)."""
    img = Image.new("L", (IMG_SIZE, IMG_SIZE), color=255)
    draw = ImageDraw.Draw(img)
    # Measure glyph bbox and center it
    bbox = draw.textbbox((0, 0), ch, font=font)
    bx0, by0, bx1, by1 = bbox
    w, h = bx1 - bx0, by1 - by0
    x = (IMG_SIZE - w) // 2 - bx0
    y = (IMG_SIZE - h) // 2 - by0
    draw.text((x, y), ch, fill=0, font=font)
    return np.asarray(img, dtype=np.uint8)


def stroke_pixel_coords(bitmap: np.ndarray, threshold: int = STROKE_THRESHOLD) -> np.ndarray:
    """Return (N, 2) array of (row, col) coordinates where luminance ≤ threshold."""
    mask = bitmap <= threshold
    rows, cols = np.nonzero(mask)
    return np.stack([rows, cols], axis=1)  # (N, 2)


def make_image_for_p(stroke_coords_shuffled: np.ndarray, n_show: int) -> Image.Image:
    """Compose a 256x256 white image with `n_show` (already-shuffled) stroke
    pixels painted black."""
    canvas = np.full((IMG_SIZE, IMG_SIZE), 255, dtype=np.uint8)
    if n_show > 0:
        sel = stroke_coords_shuffled[:n_show]
        canvas[sel[:, 0], sel[:, 1]] = 0
    return Image.fromarray(canvas, mode="L")


def generate_for_char(font, ch: str, out_dir: Path, percents: list[int]) -> int:
    """Generate images for one character at all listed percents.
    Returns N (total stroke pixel count)."""
    bitmap = render_char_bitmap(font, ch)
    coords = stroke_pixel_coords(bitmap)
    n_total = len(coords)
    if n_total == 0:
        print(f"  ! WARNING: char {ch!r} has 0 stroke pixels (font missing glyph?)", file=sys.stderr)
        return 0

    rng = random.Random(f"stroke-mask:{ch}")  # deterministic per char
    perm = list(range(n_total))
    rng.shuffle(perm)
    coords_shuffled = coords[perm]

    char_dir = out_dir / ch
    char_dir.mkdir(parents=True, exist_ok=True)

    for p in percents:
        n_show = round(n_total * p / 100)
        img = make_image_for_p(coords_shuffled, n_show)
        img.save(char_dir / f"p{p:03d}.png", optimize=True)

    return n_total


def run_phase(phase_name: str, chars: list[str], percents: list[int], font, out_base: Path) -> dict[str, int]:
    out_dir = out_base / phase_name
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    t0 = time.time()
    for i, ch in enumerate(chars, 1):
        n = generate_for_char(font, ch, out_dir, percents)
        counts[ch] = n
        if i % 10 == 0 or i == len(chars):
            elapsed = time.time() - t0
            print(f"  [{phase_name}] {i}/{len(chars)}  N={n} (elapsed {elapsed:.1f}s)")
    return counts


def write_counts_csv(phase_to_counts: dict[str, dict[str, int]], csv_path: Path) -> None:
    rows = []
    for phase, counts in phase_to_counts.items():
        for ch, n in counts.items():
            rows.append({"phase": phase, "char": ch, "stroke_pixels": n})
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["phase", "char", "stroke_pixels"])
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {csv_path}")


def selftest_phase_a(counts: dict[str, int], out_base: Path) -> bool:
    """For each phase-A char, verify that p100.png has exactly N black pixels."""
    ok = True
    for ch, n_expected in counts.items():
        img = Image.open(out_base / "trial" / ch / "p100.png").convert("L")
        n_black = int(np.sum(np.asarray(img) < STROKE_THRESHOLD + 1))
        # we wrote pure black (0), so this is exact
        n_actual = int(np.sum(np.asarray(img) == 0))
        if n_actual != n_expected:
            print(f"  SELFTEST FAIL  {ch}: expected {n_expected}, got {n_actual}")
            ok = False
        else:
            print(f"  selftest ok    {ch}: N={n_expected}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Hiragana stroke-mask image generator")
    ap.add_argument("--font", type=Path, default=DEFAULT_FONT,
                    help=f"Path to .ttf/.otf (default: {DEFAULT_FONT.name})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"Output base directory (default: {DEFAULT_OUT.name})")
    ap.add_argument("--csv", type=Path, default=None,
                    help="Stroke-count CSV path (default: <out>/stroke_counts.csv)")
    args = ap.parse_args()

    font_path = args.font
    out_base = args.out
    csv_path = args.csv if args.csv else (out_base.parent / f"stroke_counts_{out_base.name}.csv")

    if not font_path.exists():
        print(f"Font not found at {font_path}", file=sys.stderr)
        return 1
    font = ImageFont.truetype(str(font_path), size=FONT_SIZE)
    print(f"Font loaded: {font_path.name}, size {FONT_SIZE}px on {IMG_SIZE}x{IMG_SIZE} canvas")
    print(f"Output base: {out_base}")
    print(f"CSV: {csv_path}")

    # ---- Phase A ---------------------------------------------------------
    print(f"\n=== Phase A: trial ({len(TRIAL_CHARS)} chars × {len(TRIAL_PERCENTS)} levels) ===")
    counts_a = run_phase("trial", TRIAL_CHARS, TRIAL_PERCENTS, font, out_base)

    print("\n--- Phase A selftest ---")
    if not selftest_phase_a(counts_a, out_base):
        print("Self-test failed — aborting before Phase B.", file=sys.stderr)
        return 2

    # ---- Phase B ---------------------------------------------------------
    print(f"\n=== Phase B: full ({len(ALL_CHARS)} chars × {len(FULL_PERCENTS)} levels = {len(ALL_CHARS) * len(FULL_PERCENTS)} images) ===")
    counts_b = run_phase("full", ALL_CHARS, FULL_PERCENTS, font, out_base)

    # ---- CSV -------------------------------------------------------------
    write_counts_csv({"trial": counts_a, "full": counts_b}, csv_path)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
