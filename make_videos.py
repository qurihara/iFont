"""
Stitch per-font stroke-mask images into one video per font.

For each font: play 84 hiragana in order; each character ramps 0% → 100% over
0.2 seconds (12 frames at 60 fps, sampling p = 0,9,18,27,36,45,55,64,73,82,91,100
from the 101 generated PNGs).

Output: videos/<font_tag>.mp4
"""

import sys
import time
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
VIDEOS_DIR = ROOT / "videos"

FPS = 60
FRAMES_PER_CHAR = 12  # 60 fps × 0.2 s = 12 frames

# Same character order as generate.py
SEION = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん")
DAKUTEN = list("がぎぐげござじずぜぞだぢづでどばびぶべぼ")
HANDAKU = list("ぱぴぷぺぽ")
SMALL = list("ぁぃぅぇぉっゃゅょゎ")
KOGO = list("ゐゑ")
OTHER = list("ゔ")
ALL_CHARS = SEION + DAKUTEN + HANDAKU + SMALL + KOGO + OTHER  # 84

# 12 evenly-spaced indices in 0..100
SAMPLE_INDICES = [round(i * 100 / (FRAMES_PER_CHAR - 1)) for i in range(FRAMES_PER_CHAR)]

FONTS = [
    ("mplus_rounded1c", "stroke_mask_images"),
    ("bizudgothic",     "stroke_mask_images_bizud"),
    ("bizudmincho",     "stroke_mask_images_bizudmincho"),
    ("notosansjp",      "stroke_mask_images_notosansjp"),
    ("notoserifjp",     "stroke_mask_images_notoserifjp"),
    ("mplus1p",         "stroke_mask_images_mplus1p"),
]


def make_video(images_dir: Path, output_path: Path) -> None:
    if not images_dir.exists():
        print(f"  ! missing {images_dir}", file=sys.stderr)
        return
    writer = imageio.get_writer(
        str(output_path),
        fps=FPS,
        codec="libx264",
        quality=8,            # 0=lowest .. 10=highest (lossy)
        pixelformat="yuv420p",
        macro_block_size=1,   # avoid 16-pixel alignment warnings; 256 is divisible by 16 anyway
    )
    try:
        t0 = time.time()
        for ch in ALL_CHARS:
            char_dir = images_dir / "full" / ch
            for p in SAMPLE_INDICES:
                img = Image.open(char_dir / f"p{p:03d}.png").convert("RGB")
                writer.append_data(np.asarray(img))
        elapsed = time.time() - t0
    finally:
        writer.close()
    print(f"  wrote {output_path.name} ({output_path.stat().st_size / 1024:.1f} KB, {elapsed:.1f}s)")


def main() -> int:
    VIDEOS_DIR.mkdir(exist_ok=True)
    print(f"Sample indices ({FRAMES_PER_CHAR} per char): {SAMPLE_INDICES}")
    print(f"Total frames per video: {len(ALL_CHARS) * FRAMES_PER_CHAR} ({len(ALL_CHARS) * FRAMES_PER_CHAR / FPS:.2f}s)\n")
    for tag, image_dir_name in FONTS:
        image_dir = ROOT / image_dir_name
        out_path = VIDEOS_DIR / f"{tag}.mp4"
        print(f"[{tag}] from {image_dir.name}")
        make_video(image_dir, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
