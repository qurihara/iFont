"""
Subtractive f(t) videos: start with all 84 hiragana superimposed, then fade
out non-target characters one by one until only the target remains.

Two models per (font, target) pair:
  F1 (Bayesian): Sum of opacities = 1 throughout. Target opacity = 1 / |V(t)|.
  F2 (TargetFixed): Target always at alpha=1; non-targets each at alpha=1
       until their exit time, then 0.

Both: non-targets get random exit times (uniformly spaced, randomly permuted).
"""

import sys
import time
from pathlib import Path
import random

import imageio.v2 as imageio
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent

# Phase A: prototype with one font + 5 chars to inspect first
TRIAL_FONT = ("bizudgothic", "stroke_mask_images_bizud")
TRIAL_TARGETS = ["あ", "が", "ぱ", "ゐ", "ぬ"]

# Phase B: full set
FULL_FONTS = [
    ("mplus_rounded1c", "stroke_mask_images"),
    ("bizudgothic",     "stroke_mask_images_bizud"),
    ("bizudmincho",     "stroke_mask_images_bizudmincho"),
    ("notosansjp",      "stroke_mask_images_notosansjp"),
    ("notoserifjp",     "stroke_mask_images_notoserifjp"),
    ("mplus1p",         "stroke_mask_images_mplus1p"),
]
FULL_TARGETS = TRIAL_TARGETS

# Character order (same as generate.py)
SEION = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん")
DAKUTEN = list("がぎぐげござじずぜぞだぢづでどばびぶべぼ")
HANDAKU = list("ぱぴぷぺぽ")
SMALL = list("ぁぃぅぇぉっゃゅょゎ")
KOGO = list("ゐゑ")
OTHER = list("ゔ")
ALL_CHARS = SEION + DAKUTEN + HANDAKU + SMALL + KOGO + OTHER  # 84

T_SEC = 5.0           # video length
FPS = 30
NUM_FRAMES = int(T_SEC * FPS)
DELTA = 0.10          # smoothing half-width in seconds for exit ramps
IMG_SIZE = 256


def load_full_images(image_dir: Path) -> dict[str, np.ndarray]:
    """Load p100.png for each char as ink-density [0..1] array (1=ink)."""
    imgs = {}
    for ch in ALL_CHARS:
        path = image_dir / "full" / ch / "p100.png"
        arr = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
        imgs[ch] = (255.0 - arr) / 255.0  # 1 where ink, 0 where bg
    return imgs


def exit_times_for(target: str, font_tag: str) -> dict[str, float]:
    """Assign each non-target an exit time, uniformly spaced over (0, T), shuffled."""
    non_targets = [c for c in ALL_CHARS if c != target]
    rng = random.Random(f"sub:{font_tag}:{target}")
    rng.shuffle(non_targets)
    # 83 non-targets, evenly spaced exit times (avoid t=0 and t=T edges)
    n = len(non_targets)
    times = [(i + 0.5) / n * T_SEC for i in range(n)]
    return dict(zip(non_targets, times))


def smooth_weight(t: float, tau: float, delta: float = DELTA) -> float:
    """Non-target weight: 1 well before tau, 0 well after. Linear ramp ±delta."""
    return float(np.clip((tau - t) / (2 * delta) + 0.5, 0.0, 1.0))


def alphas_at(t: float, target: str, tau: dict, model: str) -> dict[str, float]:
    """Return dict of alpha values for all chars at time t."""
    weights = {}
    for c in ALL_CHARS:
        if c == target:
            weights[c] = 1.0
        else:
            weights[c] = smooth_weight(t, tau[c])
    if model == "F1":
        total = sum(weights.values())
        return {c: w / total for c, w in weights.items()} if total > 0 else weights
    elif model == "F2":
        return weights
    raise ValueError(model)


def render_frame(ink_imgs: dict, alpha: dict[str, float]) -> np.ndarray:
    """Composite via additive ink with clipping: darkness = sum(alpha * ink), clip [0,1]."""
    darkness = np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.float32)
    for c, a in alpha.items():
        if a > 0:
            darkness += a * ink_imgs[c]
    darkness = np.clip(darkness, 0.0, 1.0)
    out = (255.0 * (1.0 - darkness)).astype(np.uint8)
    return out


def make_video(ink_imgs: dict, target: str, model: str, tau: dict, out_path: Path) -> None:
    writer = imageio.get_writer(
        str(out_path),
        fps=FPS,
        codec="libx264",
        quality=8,
        pixelformat="yuv420p",
        macro_block_size=1,
    )
    try:
        for frame_idx in range(NUM_FRAMES):
            t = frame_idx / FPS
            alpha = alphas_at(t, target, tau, model)
            frame_gray = render_frame(ink_imgs, alpha)
            frame_rgb = np.stack([frame_gray] * 3, axis=-1)
            writer.append_data(frame_rgb)
    finally:
        writer.close()


def run(fonts: list, targets: list, out_root: Path) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "F1_bayesian").mkdir(exist_ok=True)
    (out_root / "F2_target_fixed").mkdir(exist_ok=True)
    for font_tag, image_dir_name in fonts:
        image_dir = ROOT / image_dir_name
        if not image_dir.exists():
            print(f"  ! skip {font_tag} (missing {image_dir.name})", file=sys.stderr)
            continue
        print(f"[{font_tag}] loading 84 char images...")
        ink_imgs = load_full_images(image_dir)
        for target in targets:
            tau = exit_times_for(target, font_tag)
            for model_tag, subdir in [("F1", "F1_bayesian"), ("F2", "F2_target_fixed")]:
                out_path = out_root / subdir / f"{font_tag}_{target}.mp4"
                t0 = time.time()
                make_video(ink_imgs, target, model_tag, tau, out_path)
                size_kb = out_path.stat().st_size / 1024
                print(f"  {model_tag} {target}: {size_kb:.0f}KB in {time.time()-t0:.1f}s")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["A", "B"], default="A",
                    help="A: 1 font × 5 chars (prototype); B: 6 fonts × 5 chars")
    args = ap.parse_args()

    out_root = ROOT / "videos" / "subtractive"
    print(f"T={T_SEC}s, fps={FPS}, {NUM_FRAMES} frames, delta={DELTA}s")
    print(f"chars={len(ALL_CHARS)}, output={out_root}\n")
    if args.phase == "A":
        run([TRIAL_FONT], TRIAL_TARGETS, out_root)
    else:
        run(FULL_FONTS, FULL_TARGETS, out_root)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
