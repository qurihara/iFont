"""
Shared constants and helpers for the iFont visual-Kikiwake pipeline.

Single source of truth for:
  - the hiragana character sets (full 84 vs 競技かるた 48),
  - the F1 (subtractive Bayesian) k-grid and the k -> r conversion,
  - the per-font source image directory mapping.

Mirrors the frozen design in experiment/pilot.js so the offline still
generator (make_subtractive_stills.py) and the stimulus-pool builder
(build_stimulus_pool.py) stay in lock-step with the client.

k = alpha_target / alpha_distractor = N * r / (100 - r)   (r in %, N = #distractors)
r = 100 * k / (N + k)
  k = 1   -> target opacity equals each distractor (no visual advantage)
  k = inf -> r = 100 (only the target is visible)
N depends on the active set: 83 for 全字(84), 47 for 競技かるた(48).
"""

import math

# ---------------------------------------------------------------------------
# Character sets (order matches generate.py / make_subtractive_videos.py /
# pilot.js). Do not reorder: stimulus hashes and answer keys depend on it.
# ---------------------------------------------------------------------------
SEION = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん")  # 46
DAKUTEN = list("がぎぐげござじずぜぞだぢづでどばびぶべぼ")  # 20
HANDAKU = list("ぱぴぷぺぽ")  # 5
SMALL = list("ぁぃぅぇぉっゃゅょゎ")  # 10
KOGO = list("ゐゑ")  # 2
OTHER = list("ゔ")  # 1

ALL_CHARS = SEION + DAKUTEN + HANDAKU + SMALL + KOGO + OTHER  # 84

# 競技かるた: 清音 46 + 古語 ゐ ゑ = 48 (濁点/半濁点/小書き/ゔ を除外)
KARUTA_CHARS = SEION + KOGO  # 48

CHARSET_FOR = {
    "all": ALL_CHARS,
    "karuta": KARUTA_CHARS,
}

# All q_sets the pipeline knows about.
Q_SETS = ("all", "karuta")

# ---------------------------------------------------------------------------
# k-grid (the frozen 11-level main-experiment grid).
# Stored as floats; the last entry is +inf (only target visible, r = 100%).
# ---------------------------------------------------------------------------
K_GRID = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, math.inf]


def n_distractors(q_set: str) -> int:
    """Number of non-target characters for the active set (N in the k formula)."""
    return len(CHARSET_FOR[q_set]) - 1


def k_to_r(k: float, n: int) -> float:
    """k -> r(%) for N distractors. k = inf -> 100."""
    if math.isinf(k):
        return 100.0
    return 100.0 * k / (n + k)


def k_label(k_index: int) -> str:
    """Stable filesystem/label token for a k-grid index, e.g. 'k00'..'k10'."""
    return f"k{k_index:02d}"


def k_str(k: float) -> str:
    """Human-readable k value ('inf' for the top level)."""
    return "inf" if math.isinf(k) else (f"{k:g}")


# Per-font source directory holding full/<char>/p100.png ink masks.
IMAGE_DIR_FOR = {
    "mplus_rounded1c": "stroke_mask_images",
    "bizudgothic":     "stroke_mask_images_bizud",
    "bizudmincho":     "stroke_mask_images_bizudmincho",
    "notosansjp":      "stroke_mask_images_notosansjp",
    "notoserifjp":     "stroke_mask_images_notoserifjp",
    "mplus1p":         "stroke_mask_images_mplus1p",
}
