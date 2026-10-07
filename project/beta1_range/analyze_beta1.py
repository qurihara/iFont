#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
analyze_beta1.py — 聴覚の較正実験から、かな1音ごとの認識率曲線の傾き β1 を推定し、
上毛かるたの先頭音44音のあいだで β1 がどれだけばらつくか(R = 最大 ÷ 最小)を見積もる。

入力
  丸山礼華さんの引き継ぎ資料(timeFont_共有_20260911)の
  data/raw/calib2_視覚_2回目/transfer_trials.csv(calib1 を含む累積。phase 列で見分ける)

本命試行の取り出し(引き継ぎ資料 AI引き継ぎ.md の規則)
  is_test が TRUE の行を除く / group == "acal"(聴覚) / modality == "transfer_audio"
  / check_kind が空(確認問題 full・floor を除く)
  さらに、同じ答えを3割以上繰り返した参加者(でたらめ回答の疑い)を除く。

モデル
  p(x) = γ + (λ − γ) / (1 + exp(−β1 (x − x0)))      x: 打ち切り長さ(音の立ち上がりからの ms)
  γ = 1/68 に固定(68 択の当て推量)。λ は自由に推定する版(主解析)と 1 に固定する版の2通り。
  二項分布の最尤推定(多数の初期値から L-BFGS-B)。
  β1 の探索範囲は [0.001, 1.0] /ms。上限 1.0 は 10〜90% の遷移幅が 4.4 ms に相当し、
  この実験の打ち切り間隔(5〜10 ms)では、それより急な曲線は区別できない。上限に張り付いた音は
  「階段状(設計の分解能を超える急さ)」として印を付ける。

「full」(打ち切りなし)試行の扱い
  本命の試行列に埋め込まれた打ち切りなし提示(check_kind は空、stimulus_id の末尾が full)。
  試行データに長さは記録されていないが、刺激 manifest(transfer_audio_manifest.json)に
  字ごとの全長(音の立ち上がりからの ms)があるので、既定ではそれを x として含める。
  これにより λ(上限)が、打ち切り点の少ない音でも試行データで決まる。
  --no-full を付けると、丸山さんの解析と同じように full を当てはめから外す(感度分析)。

不確かさ
  β1 の 95% 区間はプロファイル尤度で出す(log β1 を格子に固定し、x0 と λ を最適化して、
  最尤からの逸脱 2ΔNLL が 3.84 以下の範囲)。β1 が探索の上限に張り付く音では上側が定まらないので、
  上側の区間端を 1.0(上限)として「≧」の印を付ける。
  さらに log β1 に正規分布の事前分布 N(μ, τ²) を置く経験ベイズの階層モデル(Laplace 近似で
  μ・τ² を反復推定)により、少数試行の音の β1 を全体へ縮約した値も出す。

出力(--out で指定したフォルダ)
  beta1_table.csv            音ごとの x0・β1・λ・プロファイル尤度区間・縮約値・試行数(主解析と比較用の列)
  curve_points.csv           音 × 打ち切り長さ ごとの試行数と正答率
  fig1_focus_curves.png      重点8字の認識率曲線
  fig2_beta1_forest.png      上毛かるたの先頭音44音(+ び・ぶ)の β1 を信頼区間つきで並べた図
  summary.json               R の見積もりなど、README に書く数値

使い方
  python3.11 analyze_beta1.py                 # 既定(full を含める)
  python3.11 analyze_beta1.py --no-full       # full を外す感度分析
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IN = os.path.join(
    HERE, "..", "wiss2026", "引き継ぎ_20260911", "展開済み", "data", "raw",
    "calib2_視覚_2回目", "transfer_trials.csv")

N_CHOICES = 68
GAMMA = 1.0 / N_CHOICES
FOCUS = ["あ", "か", "が", "し", "つ", "ぱ", "ま", "ら"]           # 1字あたり 270 試行の重点字
JOMO44 = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわ")
JOMO_REF = {"び": "「ひ」の札の読みは「びゃくえ」", "ぶ": "「ふ」の札の読みは「ぶんぶく」"}
SAME_RESPONSE_CUT = 0.30     # 同じ答えがこの割合以上の参加者を除く
SEED = 20261007
B1_LO, B1_HI = 1e-3, 1.0     # β1 の探索範囲(/ms)
LAM_WEAK = 0.25              # λ がこれ未満の音は曲線がほぼ立ち上がらず、β1 に意味がない
CHI2_95 = 3.841              # プロファイル尤度の 95% 区間のしきい値(自由度1)
X0_LO, X0_HI = -50.0, 300.0  # x0 の探索範囲(ms)。打ち切り点は 10〜150 ms、全長は 250〜451 ms

# 「full」(打ち切りなし)刺激の、音の立ち上がりからの長さ(ms)。
# 出典: g19922ma/iFont (maruyama/font-exploration) experiment/transfer_audio_manifest.json の
# items["<字>|full"].after_onset_ms(= dur_ms − lead_ms)。config_version prov-2026-08-21。
FULL_AFTER_ONSET_MS = {
    "あ": 331, "い": 295, "う": 341, "え": 301, "お": 295, "か": 350, "が": 370, "き": 354,
    "ぎ": 377, "く": 333, "ぐ": 312, "け": 311, "げ": 319, "こ": 283, "ご": 250, "さ": 383,
    "ざ": 356, "し": 419, "じ": 425, "す": 427, "ず": 361, "せ": 418, "ぜ": 406, "そ": 315,
    "ぞ": 332, "た": 336, "だ": 319, "ち": 352, "つ": 345, "て": 309, "で": 314, "と": 270,
    "ど": 276, "な": 333, "に": 344, "ぬ": 342, "ね": 359, "の": 292, "は": 375, "ば": 265,
    "ぱ": 335, "ひ": 451, "び": 353, "ぴ": 320, "ふ": 380, "ぶ": 346, "ぷ": 316, "へ": 324,
    "べ": 312, "ぺ": 285, "ほ": 253, "ぼ": 278, "ぽ": 321, "ま": 303, "み": 345, "む": 360,
    "め": 354, "も": 275, "や": 424, "ゆ": 366, "よ": 315, "ら": 323, "り": 375, "る": 393,
    "れ": 359, "ろ": 280, "わ": 326, "ん": 279,
}


# ---------------------------------------------------------------------------
# 1. データの読み込みと本命試行の取り出し
# ---------------------------------------------------------------------------
def load_main_trials(path, with_full):
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False, dtype=str)
    n0 = len(df)
    df = df[df["is_test"].fillna("").str.upper() != "TRUE"]
    a = df[(df["group"] == "acal") & (df["modality"] == "transfer_audio")].copy()
    n_part_all = a["participant_id"].nunique()
    a["ok"] = a["correct"].str.upper() == "TRUE"

    # 参加者の除外: 同じ答えの割合(全70試行)が SAME_RESPONSE_CUT 以上
    same = a.groupby("participant_id")["response_char"].agg(
        lambda s: s.value_counts().iloc[0] / len(s))
    bad = sorted(same[same >= SAME_RESPONSE_CUT].index.tolist())
    a = a[~a["participant_id"].isin(bad)]

    main = a[a["check_kind"].isna() | (a["check_kind"].str.strip() == "")].copy()
    main["stim_tail"] = main["stimulus_id"].str.split("|").str[-1]
    main["gate_ms"] = pd.to_numeric(main["gate_ms"], errors="coerce")
    is_full = main["gate_ms"].isna() & (main["stim_tail"] == "full")
    n_full = int(is_full.sum())
    main["is_full"] = is_full
    if with_full:
        main.loc[is_full, "gate_ms"] = main.loc[is_full, "target_char"].map(FULL_AFTER_ONSET_MS)
    else:
        main = main[~is_full].copy()
    main = main.dropna(subset=["gate_ms"])
    info = dict(n_rows_file=n0, n_participants_audio=int(n_part_all),
                excluded_participants=bad, n_participants_used=int(main["participant_id"].nunique()),
                n_main_trials=int(len(main)), n_full_trials=n_full, with_full=bool(with_full),
                n_chars=int(main["target_char"].nunique()))
    return main, info


def aggregate(main):
    """音 × 打ち切り長さ ごとの試行数と正答数。"""
    g = main.groupby(["target_char", "gate_ms"])
    t = g.agg(n=("ok", "size"), k=("ok", "sum"), is_full=("is_full", "max")).reset_index()
    t["acc"] = t["k"] / t["n"]
    return t


# ---------------------------------------------------------------------------
# 2. ロジスティック曲線の当てはめ(最尤)
# ---------------------------------------------------------------------------
def model(x, x0, b1, lam, gamma=GAMMA):
    z = np.clip(-b1 * (x - x0), -500, 500)
    return gamma + (lam - gamma) / (1.0 + np.exp(z))


def make_nll(xs, ks, ns, lam_free, lam_fixed=1.0, gamma=GAMMA):
    xs = np.asarray(xs, float); ks = np.asarray(ks, float); ns = np.asarray(ns, float)
    eps = 1e-9

    def nll(th):
        lam = th[2] if lam_free else lam_fixed
        p = np.clip(model(xs, th[0], np.exp(th[1]), lam, gamma), eps, 1 - eps)
        return -float(np.sum(ks * np.log(p) + (ns - ks) * np.log(1 - p)))
    return nll


def fit_one(xs, ks, ns, lam_free, starts=None, warm=None, lam_fixed=1.0):
    """二項最尤。パラメータは (x0, log β1[, λ])。戻り値 dict(x0, b1, lam, nll, converged, note, theta)。"""
    xs = np.asarray(xs, float); ks = np.asarray(ks, float); ns = np.asarray(ns, float)
    nll = make_nll(xs, ks, ns, lam_free, lam_fixed)
    bounds = [(X0_LO, X0_HI), (np.log(B1_LO), np.log(B1_HI))]
    if lam_free:
        bounds.append((GAMMA + 0.01, 1.0))
    if starts is None:
        xg = xs[xs <= 200] if np.any(xs <= 200) else xs
        x0s = np.percentile(xg, [15, 35, 50, 65, 85]).tolist()
        b1s = [0.02, 0.05, 0.1, 0.25, 0.6]
        acc_max = float(np.clip((ks / np.maximum(ns, 1)).max(), GAMMA + 0.05, 0.99))
        starts = [[x0, np.log(b)] + ([acc_max] if lam_free else []) for x0 in x0s for b in b1s]
    if warm is not None:
        starts = [list(warm)] + list(starts)
    best = None
    for s in starts:
        try:
            r = minimize(nll, s, method="L-BFGS-B", bounds=bounds)
        except Exception:
            continue
        if best is None or r.fun < best.fun:
            best = r
    x0, lb = best.x[0], best.x[1]
    lam = best.x[2] if lam_free else lam_fixed
    notes = []
    if not best.success:
        notes.append("収束せず")
    if abs(x0 - X0_LO) < 1e-6 or abs(x0 - X0_HI) < 1e-6:
        notes.append("x0が探索範囲の端")
    if abs(lb - np.log(B1_LO)) < 1e-6:
        notes.append("β1が下限(ほぼ平ら)")
    if abs(lb - np.log(B1_HI)) < 1e-6:
        notes.append("β1が上限1.0(階段状: 打ち切り間隔より急で、設計の分解能を超える)")
    if lam_free and lam < GAMMA + 0.1:
        notes.append(f"λが低い({lam:.2f}): 全長でも当たらない字")
    return dict(x0=float(x0), b1=float(np.exp(lb)), lam=float(lam), nll=float(best.fun),
                converged=bool(best.success), note=";".join(notes), theta=list(best.x))


def profile_ci(xs, ks, ns, lam_free, fit, n_grid=61):
    """log β1 を格子に固定し、残りの係数を最適化してプロファイル尤度を作り、95% 区間を返す。
    戻り値 dict(b1_lo, b1_hi, lo_at_bound, hi_at_bound, profile=(grid, dnll))。"""
    xs = np.asarray(xs, float); ks = np.asarray(ks, float); ns = np.asarray(ns, float)
    grid = np.linspace(np.log(B1_LO), np.log(B1_HI), n_grid)
    x0_ml, lb_ml = fit["theta"][0], fit["theta"][1]
    lam_ml = fit["lam"]
    xg = xs[xs <= 200] if np.any(xs <= 200) else xs
    x0_alts = np.percentile(xg, [25, 75]).tolist()
    prof = np.empty(n_grid)
    for i, lb in enumerate(grid):
        nll_full = make_nll(xs, ks, ns, lam_free)

        def nll_fixed(th, lb=lb):
            return nll_full([th[0], lb] + ([th[1]] if lam_free else []))
        bounds = [(X0_LO, X0_HI)] + ([(GAMMA + 0.01, 1.0)] if lam_free else [])
        starts = [[x0_ml] + ([lam_ml] if lam_free else [])] + \
                 [[x0] + ([0.9] if lam_free else []) for x0 in x0_alts]
        best = min((minimize(nll_fixed, st, method="L-BFGS-B", bounds=bounds).fun for st in starts))
        prof[i] = best
    dnll = 2 * (prof - prof.min())
    inside = dnll <= CHI2_95
    idx = np.where(inside)[0]
    i_lo, i_hi = idx.min(), idx.max()

    def interp(i_in, i_out):
        # 区間の内側の格子点 i_in と外側の格子点 i_out の間で、しきい値を横切る点を線形補間
        g0, g1 = grid[i_in], grid[i_out]; d0, d1 = dnll[i_in], dnll[i_out]
        return g0 + (g1 - g0) * (CHI2_95 - d0) / (d1 - d0) if d1 != d0 else g0
    lo_at_bound = i_lo == 0
    hi_at_bound = i_hi == n_grid - 1
    lo = grid[0] if lo_at_bound else interp(i_lo, i_lo - 1)
    hi = grid[-1] if hi_at_bound else interp(i_hi, i_hi + 1)
    return dict(b1_lo=float(np.exp(lo)), b1_hi=float(np.exp(hi)),
                lo_at_bound=bool(lo_at_bound), hi_at_bound=bool(hi_at_bound),
                profile_grid=grid, profile_dnll=dnll)


def fit_all(main, lam_free):
    tab = aggregate(main)
    rows = {}
    for ch, t in tab.groupby("target_char"):
        xs, ks, ns = t["gate_ms"].values, t["k"].values, t["n"].values
        f = fit_one(xs, ks, ns, lam_free)
        f.update(n_trials=int(t["n"].sum()), n_levels=int(len(t)),
                 n_full=int(main[(main["target_char"] == ch) & main["is_full"]].shape[0]))
        ci = profile_ci(xs, ks, ns, lam_free, f)
        f.update(b1_lo=ci["b1_lo"], b1_hi=ci["b1_hi"], lo_at_bound=ci["lo_at_bound"], hi_at_bound=ci["hi_at_bound"])
        f["at_cap"] = f["b1"] >= B1_HI * 0.999
        f["curve_weak"] = f["lam"] < LAM_WEAK
        rows[ch] = f
    return rows, tab


# ---------------------------------------------------------------------------
# 3. 階層モデル(経験ベイズ、Laplace 近似)による log β1 の縮約
# ---------------------------------------------------------------------------
def _num_hessian(f, th, h=1e-3):
    th = np.asarray(th, float); k = len(th)
    H = np.zeros((k, k))
    for i in range(k):
        for j in range(i, k):
            ei = np.zeros(k); ej = np.zeros(k); ei[i] = h; ej[j] = h
            v = (f(th + ei + ej) - f(th + ei - ej) - f(th - ei + ej) + f(th - ei - ej)) / (4 * h * h)
            H[i, j] = H[j, i] = v
    return H


def eb_hierarchical(tab, rows_ml, iters=40, tol=1e-4):
    """各音について λ を最尤値に固定し、(x0, log β1) を事後最大化する。
    事前分布は log β1 ~ N(μ, τ²)、x0 は一様。μ・τ² は Laplace 近似の事後平均・分散から
    反復で更新する(経験ベイズ)。戻り値: dict(char -> dict(b1_shrunk, x0_shrunk, post_sd)), μ, τ²。"""
    chars = sorted(rows_ml)
    data = {}
    for ch in chars:
        t = tab[tab["target_char"] == ch]
        data[ch] = (t["gate_ms"].values.astype(float), t["k"].values.astype(float),
                    t["n"].values.astype(float), rows_ml[ch]["lam"])
    # 初期値: 最尤推定値の log β1 の平均と分散
    lb_ml = np.array([np.log(rows_ml[ch]["b1"]) for ch in chars])
    mu, tau2 = float(lb_ml.mean()), float(max(lb_ml.var(), 0.05))
    bounds = [(X0_LO, X0_HI), (np.log(B1_LO) - 1, np.log(B1_HI) + 1)]   # 事前分布があるので少し広く
    res = {}
    for it in range(iters):
        ms, vs = [], []
        for ch in chars:
            xs, ks, ns, lam = data[ch]
            nll = make_nll(xs, ks, ns, False, lam_fixed=lam)

            def nlp(th, nll=nll):
                return nll(th) + 0.5 * (th[1] - mu) ** 2 / tau2
            starts = [[x0, mu] for x0 in np.percentile(xs[xs <= 200], [25, 50, 75])] + \
                     [[rows_ml[ch]["x0"], np.log(rows_ml[ch]["b1"])]]
            best = None
            for s in starts:
                r = minimize(nlp, s, method="L-BFGS-B", bounds=bounds)
                if best is None or r.fun < best.fun:
                    best = r
            H = _num_hessian(nlp, best.x)
            try:
                cov = np.linalg.inv(H)
                v = float(cov[1, 1])
                if not np.isfinite(v) or v <= 0:
                    v = tau2
            except np.linalg.LinAlgError:
                v = tau2
            v = min(v, 25.0)
            ms.append(float(best.x[1])); vs.append(v)
            res[ch] = dict(b1_shrunk=float(np.exp(best.x[1])), x0_shrunk=float(best.x[0]),
                           post_sd_logb1=float(np.sqrt(v)))
        ms = np.array(ms); vs = np.array(vs)
        mu_new = float(ms.mean())
        tau2_new = float(max(np.mean(vs + (ms - mu_new) ** 2), 1e-4))
        done = abs(mu_new - mu) < tol and abs(tau2_new - tau2) < tol
        mu, tau2 = mu_new, tau2_new
        if done:
            break
    return res, mu, tau2, it + 1


# ---------------------------------------------------------------------------
# 4. R の見積もり
# ---------------------------------------------------------------------------
def r_estimates(df):
    out = {}
    foc = df[df["is_focus"]]
    out["R_a_focus8"] = float(foc["b1"].max() / foc["b1"].min())
    out["R_a_focus8_chars"] = [foc.loc[foc["b1"].idxmax(), "char"], foc.loc[foc["b1"].idxmin(), "char"]]
    foc44 = foc[foc["in_jomo44"]]
    out["R_a_focus_in44"] = float(foc44["b1"].max() / foc44["b1"].min())
    out["R_a_focus_in44_chars"] = [foc44.loc[foc44["b1"].idxmax(), "char"], foc44.loc[foc44["b1"].idxmin(), "char"]]
    out["R_a_focus_in44_shrunk"] = float(foc44["b1_shrunk"].max() / foc44["b1_shrunk"].min())
    j = df[df["in_jomo44"]]
    out["R_b_point44"] = float(j["b1"].max() / j["b1"].min())
    out["R_b_point44_chars"] = [j.loc[j["b1"].idxmax(), "char"], j.loc[j["b1"].idxmin(), "char"]]
    out["n44_at_cap"] = int(j["at_cap"].sum())
    out["chars44_at_cap"] = j.loc[j["at_cap"], "char"].tolist()
    out["n44_curve_weak"] = int(j["curve_weak"].sum())
    out["chars44_curve_weak"] = j.loc[j["curve_weak"], "char"].tolist()
    js = j[~j["curve_weak"]]
    out["R_b_point44_excl_weak"] = float(js["b1"].max() / js["b1"].min())
    # (c-1) 信頼区間の内側で最も保守的な R: 各音の区間からひとつずつ値を選んで R を最小にする
    out["R_c_ci_conservative"] = float(max(1.0, j["b1_lo"].max() / j["b1_hi"].min()))
    out["R_c_ci_conservative_chars"] = [j.loc[j["b1_lo"].idxmax(), "char"], j.loc[j["b1_hi"].idxmin(), "char"]]
    # 参考: 信頼区間の内側で最も大きな R
    out["R_c_ci_pessimistic"] = float(j["b1_hi"].max() / j["b1_lo"].min())
    # (c-2) 階層モデルで縮約した β1 による R
    out["R_c_shrunk44"] = float(j["b1_shrunk"].max() / j["b1_shrunk"].min())
    out["R_c_shrunk44_chars"] = [j.loc[j["b1_shrunk"].idxmax(), "char"], j.loc[j["b1_shrunk"].idxmin(), "char"]]
    out["R_c_shrunk44_excl_weak"] = float(js["b1_shrunk"].max() / js["b1_shrunk"].min())
    out["R_c_ci_conservative_excl_weak"] = float(max(1.0, js["b1_lo"].max() / js["b1_hi"].min()))
    # 中央値のまわりの散らばり(両端に引きずられない目安): 10〜90 パーセンタイルの比
    out["R_b_p90_p10"] = float(np.percentile(j["b1"], 90) / np.percentile(j["b1"], 10))
    out["R_c_shrunk_p90_p10"] = float(np.percentile(j["b1_shrunk"], 90) / np.percentile(j["b1_shrunk"], 10))
    for k, col in (("b1_44", "b1"), ("b1_shrunk_44", "b1_shrunk")):
        out[f"{k}_min"] = float(j[col].min()); out[f"{k}_max"] = float(j[col].max())
        out[f"{k}_median"] = float(j[col].median())
        out[f"{k}_q25"] = float(j[col].quantile(0.25)); out[f"{k}_q75"] = float(j[col].quantile(0.75))
    return out


def k_design_table(Rs=(2, 3, 4, 6, 10, 15, 23, 30, 60), Ks=(2, 3, 4, 5, 6, 8)):
    """傾きを等比に K 段階用意したとき、最も近い段階との傾きの比は最大で ρ = R^(1/(2(K−1)))。
    x0 が一致し、γ=0・λ=1 のロジスティック曲線 σ(z) で、同じ x での正答率の差の最大
    max_z |σ(z) − σ(ρ z)| を表にする(R=3, K=3 で 0.060、R=4, K=3 で 0.075)。"""
    z = np.linspace(-15, 15, 30001)
    sig = lambda v: 1 / (1 + np.exp(-v))
    out = {}
    for R in Rs:
        out[str(R)] = {}
        for K in Ks:
            rho = R ** (1 / (2 * (K - 1)))
            out[str(R)][str(K)] = dict(rho=float(rho), max_acc_diff=float(np.max(np.abs(sig(z) - sig(rho * z)))))
    return out


# ---------------------------------------------------------------------------
# 5. 図
# ---------------------------------------------------------------------------
PALETTE8 = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


def setup_mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = {x.name for x in matplotlib.font_manager.fontManager.ttflist}
    for f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP", "IPAexGothic"):
        if f in names:
            plt.rcParams["font.family"] = f
            break
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#e6e6e3", "grid.linewidth": 0.6,
                         "axes.edgecolor": "#9a9a95", "axes.labelcolor": "#0b0b0b",
                         "xtick.color": "#52514e", "ytick.color": "#52514e",
                         "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
                         "font.size": 11, "axes.unicode_minus": False})
    return plt


def fig_focus_curves(rows, tab, path, with_full):
    plt = setup_mpl()
    fig, ax = plt.subplots(figsize=(9, 5.4), dpi=160)
    xmax = 160
    xx = np.linspace(0, xmax, 400)
    ends = []
    for i, ch in enumerate(FOCUS):
        f = rows[ch]; c = PALETTE8[i]
        t = tab[(tab["target_char"] == ch) & (~tab["is_full"].astype(bool))]
        ax.plot(xx, model(xx, f["x0"], f["b1"], f["lam"]), color=c, lw=2, zorder=3)
        ax.scatter(t["gate_ms"], t["acc"], s=np.clip(t["n"] * 1.2, 12, 60), color=c,
                   edgecolor="#fcfcfb", linewidth=1.0, zorder=4)
        ends.append((model(xmax, f["x0"], f["b1"], f["lam"]), ch, f, c))
    # 右端のラベルが重ならないように縦位置をずらす
    ends.sort(key=lambda e: e[0])
    ys = [e[0] for e in ends]
    for k in range(1, len(ys)):
        if ys[k] - ys[k - 1] < 0.045:
            ys[k] = ys[k - 1] + 0.045
    for (yend, ch, f, c), y in zip(ends, ys):
        cap = "≧" if f["at_cap"] else "="
        ax.annotate(f"{ch}  β1{cap}{f['b1']:.3f}  λ={f['lam']:.2f}", (xmax, yend), xytext=(8, (y - yend) * 300),
                    textcoords="offset points", va="center", fontsize=9.5, color="#0b0b0b",
                    arrowprops=dict(arrowstyle="-", color=c, lw=0.8, shrinkA=0, shrinkB=2))
    ax.axhline(GAMMA, color="#9a9a95", lw=1, ls=":", zorder=2)
    ax.text(2, GAMMA + 0.015, "当て推量 1/68", color="#52514e", fontsize=9)
    ax.set_xlim(0, xmax); ax.set_ylim(0, 1.0)
    ax.set_xlabel("打ち切り長さ(音の立ち上がりからの ms)")
    ax.set_ylabel("正答率(68 択)")
    sub = "全長提示(250〜450 ms、図の外)の試行も当てはめに使用" if with_full else "全長提示の試行は当てはめに不使用"
    ax.set_title(f"重点8字の認識率曲線(点は観測値、大きさは試行数。1字あたり約 230 試行)\n{sub}", fontsize=10.5)
    fig.subplots_adjust(right=0.78, left=0.08, bottom=0.12, top=0.89)
    fig.savefig(path)
    plt.close(fig)


def fig_forest(df, path):
    plt = setup_mpl()
    from matplotlib.lines import Line2D
    d = df[df["in_jomo44"] | df["is_jomo_ref"]].sort_values("b1").reset_index(drop=True)
    n = len(d)
    fig, ax = plt.subplots(figsize=(8, 0.27 * n + 1.8), dpi=160)
    for i, r in d.iterrows():
        c = "#9a9a95" if r["is_jomo_ref"] else ("#eb6834" if r["is_focus"] else "#2a78d6")
        ax.plot([r["b1_lo"], r["b1_hi"]], [i, i], color=c, lw=1.6, solid_capstyle="round", zorder=2)
        mk = ">" if r["at_cap"] else ("D" if r["is_jomo_ref"] else "o")
        ax.scatter([r["b1"]], [i], s=40 if r["at_cap"] else 36, color=c, edgecolor="#fcfcfb", linewidth=0.8,
                   zorder=4, marker=mk)
        ax.scatter([r["b1_shrunk"]], [i], s=20, facecolor="none", edgecolor="#0b0b0b", linewidth=0.9,
                   zorder=5, marker="s")
    ax.axvline(B1_HI, color="#9a9a95", lw=0.8, ls="--")
    ax.text(B1_HI * 0.93, n - 0.4, "探索の上限 1.0\n(▶ はこれ以上) ", fontsize=8, color="#52514e", va="top", ha="right")
    ax.set_yticks(np.arange(n))
    ax.set_yticklabels([f"{r['char']}{'†' if r['curve_weak'] else ''}  (n={int(r['n_trials'])})" for _, r in d.iterrows()],
                       fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("傾き β1(1/ms、対数軸)。横線は 95% プロファイル尤度区間、□ は階層モデルで縮約した値\n"
                  f"† は λ(全長での正答率)が {LAM_WEAK} 未満で、曲線がほぼ立ち上がらない音", fontsize=9.5)
    ax.set_ylim(-0.8, n - 0.2)
    h = [Line2D([], [], color="#eb6834", marker="o", lw=1.6, label="重点字(約 230 試行)"),
         Line2D([], [], color="#2a78d6", marker="o", lw=1.6, label="少数試行の字"),
         Line2D([], [], color="#9a9a95", marker="D", lw=1.6, label="参考(び・ぶ: 札の読みが濁音)"),
         Line2D([], [], color="#0b0b0b", marker="s", markerfacecolor="none", lw=0, label="縮約した β1")]
    ax.legend(handles=h, loc="lower right", fontsize=9, frameon=False)
    ax.set_title("上毛かるたの先頭音44音の β1(傾きの順)", fontsize=11)
    fig.subplots_adjust(left=0.15, right=0.97, bottom=0.085, top=0.96)
    fig.savefig(path)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 6. main
# ---------------------------------------------------------------------------
def build_table(rows_main, rows_alt, shrink, label_alt):
    recs = []
    for ch in sorted(rows_main):
        f = rows_main[ch]; g = rows_alt.get(ch, {}); s = shrink.get(ch, {})
        recs.append(dict(
            char=ch, is_focus=ch in FOCUS, in_jomo44=ch in JOMO44, is_jomo_ref=ch in JOMO_REF,
            n_trials=f["n_trials"], n_levels=f["n_levels"], n_full=f["n_full"],
            x0=f["x0"],
            b1=f["b1"], b1_lo=f["b1_lo"], b1_hi=f["b1_hi"], lo_at_bound=f["lo_at_bound"], hi_at_bound=f["hi_at_bound"],
            at_cap=f["at_cap"], curve_weak=f["curve_weak"],
            lam=f["lam"],
            b1_shrunk=s.get("b1_shrunk"), x0_shrunk=s.get("x0_shrunk"), post_sd_logb1=s.get("post_sd_logb1"),
            converged=f["converged"], note=f["note"],
            **{f"x0_{label_alt}": g.get("x0"), f"b1_{label_alt}": g.get("b1"),
               f"b1_lo_{label_alt}": g.get("b1_lo"), f"b1_hi_{label_alt}": g.get("b1_hi"),
               f"lam_{label_alt}": g.get("lam"), f"note_{label_alt}": g.get("note")},
        ))
    return pd.DataFrame(recs)


def stability(rows):
    rs = [r for c, r in rows.items() if c in JOMO44]
    ratios = [r["b1_hi"] / r["b1_lo"] for r in rs]
    return dict(n_at_cap=int(sum(r["at_cap"] for r in rs)),
                n_x0_at_bound=int(sum("x0が探索範囲の端" in r["note"] for r in rs)),
                n_not_converged=int(sum(not r["converged"] for r in rs)),
                median_ci_ratio=float(np.median(ratios)),
                n_ci_ratio_over_10=int(sum(x > 10 for x in ratios)),
                total_nll=float(sum(r["nll"] for r in rs)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=DEFAULT_IN)
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--no-full", action="store_true", help="full 試行を当てはめから外す(感度分析)")
    ap.add_argument("--primary", choices=["lam_free", "lam_fixed"], default="lam_free",
                    help="主解析にする上限の扱い")
    args = ap.parse_args()
    with_full = not args.no_full
    os.makedirs(args.out, exist_ok=True)

    main_df, info = load_main_trials(args.inp, with_full)
    print("読み込み:", json.dumps(info, ensure_ascii=False))
    tab = aggregate(main_df)
    tab.to_csv(os.path.join(args.out, "curve_points.csv"), index=False)

    rows_free, _ = fit_all(main_df, True)
    print("λ自由: 当てはめ完了")
    rows_fixed, _ = fit_all(main_df, False)
    print("λ固定: 当てはめ完了")
    rows_main, rows_alt, label_alt = (rows_free, rows_fixed, "lam_fixed") if args.primary == "lam_free" \
        else (rows_fixed, rows_free, "lam_free")

    shrink, mu, tau2, n_it = eb_hierarchical(tab, rows_main)
    print(f"階層モデル: μ={mu:.3f} (β1 の幾何平均 {np.exp(mu):.4f}/ms), τ={np.sqrt(tau2):.3f}, 反復 {n_it} 回")

    df = build_table(rows_main, rows_alt, shrink, label_alt)
    df.to_csv(os.path.join(args.out, "beta1_table.csv"), index=False, float_format="%.5g")
    R = r_estimates(df)
    summ = dict(input=info, primary=args.primary, gamma=GAMMA, b1_bounds=[B1_LO, B1_HI], lam_weak=LAM_WEAK,
                shrink=dict(mu_logb1=mu, tau2_logb1=tau2, tau_logb1=float(np.sqrt(tau2)),
                            b1_geometric_mean=float(np.exp(mu)), n_iter=n_it, n_chars_pooled=len(shrink)),
                R=R, k_design=k_design_table(),
                focus=[dict(char=c, x0=rows_main[c]["x0"], b1=rows_main[c]["b1"], lam=rows_main[c]["lam"],
                            n=rows_main[c]["n_trials"], b1_lo=rows_main[c].get("b1_lo"), b1_hi=rows_main[c].get("b1_hi"),
                            b1_shrunk=shrink[c]["b1_shrunk"], at_cap=rows_main[c]["at_cap"],
                            note=rows_main[c]["note"]) for c in FOCUS],
                stability=dict(lam_free=stability(rows_free), lam_fixed=stability(rows_fixed)))
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summ, fh, ensure_ascii=False, indent=1)
    print(json.dumps(R, ensure_ascii=False, indent=1))
    print("安定さ:", json.dumps(summ["stability"], ensure_ascii=False))

    fig_focus_curves(rows_main, tab, os.path.join(args.out, "fig1_focus_curves.png"), with_full)
    fig_forest(df, os.path.join(args.out, "fig2_beta1_forest.png"))
    print("書き出し先:", args.out)


if __name__ == "__main__":
    main()
