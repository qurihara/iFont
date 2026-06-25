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
YOON = list("ゃゅょ")          # 3  拗音の小書き
SOKUON = list("っ")            # 1  促音
SMALL_VOWEL = list("ぁぃぅぇぉ")  # 5  小書き母音（外来語専用・通常文では不使用）
WA_SMALL = list("ゎ")          # 1  小書き わ（同上）
KOGO = list("ゐゑ")            # 2  古語
OTHER = list("ゔ")             # 1

# The universe (stroke-mask sources exist for all 84). Order kept as the
# legacy SMALL block ぁぃぅぇぉっゃゅょゎ so nothing downstream shifts.
ALL_CHARS = (SEION + DAKUTEN + HANDAKU
             + SMALL_VOWEL + SOKUON + YOON + WA_SMALL + KOGO + OTHER)  # 84

# ---------------------------------------------------------------------------
# Modality-specific target/response sets (2026-06 design review).
#
# Unifying model: a trial is "preceding context C1 → target C2, gate C2".
# The single-char task is just C1 = ∅ (no context / utterance-initial). In
# THAT C1=∅ slice some kana are degenerate per modality and are excluded:
#
# VISUAL (glyphs are self-contained): keep small ゃゅょ / っ and 古語 ゐゑ as
#   distinct glyphs (measuring small-glyph readability IS the point). Drop
#   only ぁぃぅぇぉゎ (foreign-word only; if they ever appear, substitute the
#   full-size kana at render time). → 84 − 6 = 78.
# AUDIO (single, isolated): drop everything that collapses onto a base sound
#   or is silent in isolation — ゐ→い ゑ→え, ゃ→や ゅ→ゆ ょ→よ, っ=無音,
#   ぁぃぅぇぉ→あいうえお ゎ→わ. Only the acoustically-distinct set remains.
#   These degenerate kana are recovered later via the C1≠∅ 2-char task (needs
#   MFA) or assumed equal to their base char. → 清音46+濁20+半5+ゔ = 72.
# ---------------------------------------------------------------------------
VISUAL_ALL = SEION + DAKUTEN + HANDAKU + YOON + SOKUON + KOGO + OTHER   # 78
VISUAL_KARUTA = SEION + KOGO                                            # 48
AUDIO_ALL = SEION + DAKUTEN + HANDAKU + OTHER                           # 72
AUDIO_KARUTA = SEION                                                    # 46 (ゐゑ→いえ)

VISUAL_CHARSET_FOR = {"all": VISUAL_ALL, "karuta": VISUAL_KARUTA}
AUDIO_CHARSET_FOR = {"all": AUDIO_ALL, "karuta": AUDIO_KARUTA}

# Back-compat default (visual pipeline imports CHARSET_FOR).
KARUTA_CHARS = VISUAL_KARUTA
CHARSET_FOR = VISUAL_CHARSET_FOR

# All q_sets the pipeline knows about.
Q_SETS = ("all", "karuta")

# ---------------------------------------------------------------------------
# k-grid (the frozen 11-level main-experiment grid).
# Stored as floats; the last entry is +inf (only target visible, r = 100%).
# ---------------------------------------------------------------------------
K_GRID = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, math.inf]

# ---------------------------------------------------------------------------
# Audio f_audio_kana: single-kana TEMPORAL GATING (truncation) grid.
# The adopted auditory model. A clean single-kana reading is truncated at
# frac% of its voiced duration (onset→offset); the participant identifies it.
#   frac = 0   -> nothing audible (chance anchor)
#   frac = 100 -> the full clean kana (catch trial)
# Unlike the (deprecated) chorus model this does NOT depend on the candidate
# set, so one pool of clips serves both q_sets; only the response grid (and γ)
# differ by q_set.
# 21 levels (5% steps). Change here to retune granularity.
# ---------------------------------------------------------------------------
FRAC_GRID = list(range(0, 101, 5))   # 0,5,...,100  (21 levels)


def frac_label(frac_index: int) -> str:
    """Stable filesystem/label token for a frac-grid index, e.g. 'f00'..'f20'."""
    return f"f{frac_index:02d}"


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
