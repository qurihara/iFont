#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
analyze_card.py — 上毛かるたの札当て課題(audio_card / visual_card)の試行データから、
札 × 打ち切り時点の正答率を集計し、札ごと(文字課題は札 × 速さの段階ごと)にロジスティック曲線を
当てはめてレベル x0 と傾き β1 を推定する。

入力(複数可。拡張子で判別)
  .csv / .tsv   GAS の jomo_trials シートを書き出したもの(列: participant_id, task, stimulus_id, cut_ms,
                is_catch, correct, response_char, speed_idx, fade_ms, rt_ms, replays, ua ...)
  .json         ページの点検モードでダウンロードした結果(trials 配列を持つ)

本命試行の取り出し
  task が指定の課題(--task audio|visual。既定は入力の task 列から自動)、is_catch が偽の試行。
  参加者の除外: 同じ答えが SAME_RESPONSE_CUT(30%)以上の参加者、統制試行の正答率が CATCH_MIN(50%)未満の参加者。
  除外した参加者と理由は summary.json に書く。

モデル
  p(x) = γ + (λ − γ) / (1 + exp(−β1 (x − x0)))     x: 打ち切り(第一音の音響的開始からの ms)
  γ = 1/44 に固定(44択の当て推量)。λ は自由(主解析)と 1 に固定(比較用)の2通り。
  二項分布の最尤推定(多数の初期値から L-BFGS-B)。β1 の探索範囲は [0.001, 1.0] /ms
  (上限 1.0 は 10〜90% の遷移幅 4.4 ms。打ち切り間隔 40 ms では、それより急な曲線は区別できない)。
  β1 の 95% 区間はプロファイル尤度(log β1 を格子に固定して x0・λ を最適化し、2ΔNLL ≤ 3.84 の範囲)。

出力(--out)
  curve_points.csv   (task, card, speed_idx) × cut_ms ごとの試行数と正答率
  fit_table.csv      (task, card, speed_idx) ごとの x0・β1・λ・β1 の区間・試行数(λ自由と λ固定)
  summary.json       読み込み・除外・β1 の範囲(R)・速さ段階ごとの β1 の中央値など
  fig_curves.png     札ごとの認識率曲線(文字課題は速さ5段階を重ねる)
  (--simulate N)     既知のパラメータから N 名ぶんの擬似データを作って同じ手順にかけ、推定の回復を確かめる

使い方
  python3.11 experiment/jomo/analyze_card.py jomo_trials.csv --out experiment/jomo/results_audio
  python3.11 experiment/jomo/analyze_card.py --simulate 150 --task audio --out /tmp/sim_audio
  python3.11 experiment/jomo/analyze_card.py --simulate 750 --task visual --out /tmp/sim_visual
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
N_CHOICES = 44
GAMMA = 1.0 / N_CHOICES
CUTS_MS = [40, 80, 120, 160, 200, 260, 340, 450]
CATCH_MS = 1000
FADE_MS_LEVELS = [600, 337, 190, 107, 60]
SAME_RESPONSE_CUT = 0.30
CATCH_MIN = 0.50
B1_LO, B1_HI = 1e-3, 1.0
X0_LO, X0_HI = -100.0, 1500.0
CHI2_95 = 3.841
SEED = 20261008


# ---------------------------------------------------------------------------
# 1. 読み込み
# ---------------------------------------------------------------------------
def load_inputs(paths):
    frames = []
    for p in paths:
        ext = os.path.splitext(p)[1].lower()
        if ext == ".json":
            d = json.load(open(p, encoding="utf-8"))
            rows = d.get("trials", d if isinstance(d, list) else [])
            df = pd.DataFrame(rows)
            if "task" in d:
                df["task"] = d["task"]
            if "participant_id" not in df.columns:
                df["participant_id"] = os.path.basename(p)
            frames.append(df)
        else:
            sep = "\t" if ext == ".tsv" else ","
            frames.append(pd.read_csv(p, sep=sep, encoding="utf-8-sig", dtype=str, low_memory=False))
    df = pd.concat(frames, ignore_index=True)
    for c in ["cut_ms", "speed_idx", "fade_ms", "rt_ms", "replays", "trial_index"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["is_catch", "correct"]:
        if c in df.columns:
            df[c] = df[c].map(lambda v: str(v).strip().upper() == "TRUE" if not isinstance(v, bool) else v)
    if "task" not in df.columns:
        df["task"] = ""
    # ページの点検モードの JSON は task 列が "main" なので、課題名は別に持つ
    df["task"] = df["task"].replace({"main": ""})
    if "correct" not in df.columns:
        df["correct"] = df["response_char"] == df["correct_char"]
    if "speed_idx" not in df.columns:
        df["speed_idx"] = np.nan
    return df


def select_trials(df, task):
    info = dict(n_rows=int(len(df)))
    if task:
        tk = "audio_card" if task == "audio" else "visual_card"
        if (df["task"] != "").any():
            df = df[df["task"] == tk].copy()
    info["n_rows_task"] = int(len(df))
    info["n_participants_all"] = int(df["participant_id"].nunique())
    excluded = {}
    for pid, g in df.groupby("participant_id"):
        reasons = []
        vc = g["response_char"].value_counts()
        if len(g) >= 10 and vc.iloc[0] / len(g) >= SAME_RESPONSE_CUT:
            reasons.append(f"同じ答えが{vc.iloc[0] / len(g):.0%}")
        cg = g[g["is_catch"] == True]      # noqa: E712
        if len(cg) >= 4 and cg["correct"].mean() < CATCH_MIN:
            reasons.append(f"統制試行の正答率{cg['correct'].mean():.0%}")
        if reasons:
            excluded[pid] = "、".join(reasons)
    df = df[~df["participant_id"].isin(excluded)]
    main = df[df["is_catch"] != True].copy()   # noqa: E712
    main = main.dropna(subset=["cut_ms"])
    main["speed_idx"] = main["speed_idx"].fillna(-1).astype(int)
    info.update(n_excluded=len(excluded), excluded=excluded,
                n_participants=int(main["participant_id"].nunique()), n_main=int(len(main)),
                catch_accuracy=float(df[df["is_catch"] == True]["correct"].mean()) if (df["is_catch"] == True).any() else None)  # noqa: E712
    return main, info


def aggregate(main):
    g = main.groupby(["stimulus_id", "speed_idx", "cut_ms"])["correct"]
    tab = g.agg(n="size", k="sum").reset_index()
    tab["p"] = tab["k"] / tab["n"]
    return tab


# ---------------------------------------------------------------------------
# 2. ロジスティックの当てはめ
# ---------------------------------------------------------------------------
def logistic(x, x0, b1, lam):
    z = np.clip(-b1 * (x - x0), -500, 500)
    return GAMMA + (lam - GAMMA) / (1.0 + np.exp(z))


def nll(params, x, n, k, lam_free):
    x0, lb1 = params[0], params[1]
    lam = params[2] if lam_free else 1.0
    p = np.clip(logistic(x, x0, np.exp(lb1), lam), 1e-9, 1 - 1e-9)
    return float(-np.sum(k * np.log(p) + (n - k) * np.log(1 - p)))


def fit_one(x, n, k, lam_free, rng):
    bounds = [(X0_LO, X0_HI), (np.log(B1_LO), np.log(B1_HI))] + ([(GAMMA + 0.01, 1.0)] if lam_free else [])
    best = None
    starts = [(x0, lb, lam) for x0 in (50, 100, 150, 200, 300, 500) for lb in np.log([0.01, 0.03, 0.1, 0.3])
              for lam in ((0.6, 0.9, 1.0) if lam_free else (1.0,))]
    for _ in range(12):
        starts.append((rng.uniform(X0_LO, 600), rng.uniform(np.log(B1_LO), np.log(B1_HI)), rng.uniform(0.3, 1.0)))
    for s in starts:
        p0 = list(s[:3] if lam_free else s[:2])
        try:
            r = minimize(nll, p0, args=(x, n, k, lam_free), method="L-BFGS-B", bounds=bounds)
        except Exception:
            continue
        if best is None or r.fun < best.fun:
            best = r
    x0, lb1 = best.x[0], best.x[1]
    lam = best.x[2] if lam_free else 1.0
    return dict(x0=float(x0), b1=float(np.exp(lb1)), lam=float(lam), nll=float(best.fun), converged=bool(best.success))


def profile_b1(x, n, k, lam_free, fit):
    """log β1 を格子に固定して残りを最適化し、2ΔNLL ≤ 3.84 の範囲を β1 の 95% 区間とする。"""
    grid = np.linspace(np.log(B1_LO), np.log(B1_HI), 61)
    base = fit["nll"]
    ok = []
    for lb in grid:
        def f(q):
            params = [q[0], lb] + ([q[1]] if lam_free else [])
            return nll(params, x, n, k, lam_free)
        p0 = [fit["x0"]] + ([fit["lam"]] if lam_free else [])
        bounds = [(X0_LO, X0_HI)] + ([(GAMMA + 0.01, 1.0)] if lam_free else [])
        r = minimize(f, p0, method="L-BFGS-B", bounds=bounds)
        ok.append(2 * (r.fun - base) <= CHI2_95)
    ok = np.array(ok)
    if not ok.any():
        return fit["b1"], fit["b1"], False, False
    lo, hi = grid[ok].min(), grid[ok].max()
    return float(np.exp(lo)), float(np.exp(hi)), bool(lo <= grid[0] + 1e-9), bool(hi >= grid[-1] - 1e-9)


def fit_all(tab, rng):
    rows = []
    for (card, sp), g in tab.groupby(["stimulus_id", "speed_idx"]):
        x = g["cut_ms"].to_numpy(float); n = g["n"].to_numpy(float); k = g["k"].to_numpy(float)
        rec = dict(stimulus_id=card, speed_idx=int(sp), fade_ms=(FADE_MS_LEVELS[sp] if 0 <= sp < len(FADE_MS_LEVELS) else ""),
                   n_trials=int(n.sum()), n_levels=int(len(x)), p_max=float(g["p"].max()))
        for lam_free, tag in ((True, ""), (False, "_lam1")):
            f = fit_one(x, n, k, lam_free, rng)
            lo, hi, lo_b, hi_b = profile_b1(x, n, k, lam_free, f)
            rec.update({f"x0{tag}": f["x0"], f"b1{tag}": f["b1"], f"lam{tag}": f["lam"], f"nll{tag}": f["nll"],
                        f"b1_lo{tag}": lo, f"b1_hi{tag}": hi, f"b1_hi_at_bound{tag}": hi_b,
                        f"at_cap{tag}": f["b1"] >= B1_HI * 0.999, f"converged{tag}": f["converged"]})
        rec["note"] = "曲線が立ち上がらない(λ<0.25)" if rec["lam"] < 0.25 else ("階段状(β1が上限)" if rec["at_cap"] else "")
        rows.append(rec)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. まとめと図
# ---------------------------------------------------------------------------
def summarize(fit):
    out = {}
    for sp, g in fit.groupby("speed_idx"):
        gg = g[g["lam"] >= 0.25]
        b = gg["b1"].to_numpy()
        if len(b) == 0:
            continue
        out[str(sp)] = dict(n_cards=int(len(g)), n_curve_ok=int(len(gg)),
                            b1_min=float(b.min()), b1_p10=float(np.percentile(b, 10)), b1_median=float(np.median(b)),
                            b1_p90=float(np.percentile(b, 90)), b1_max=float(b.max()),
                            R_p10_p90=float(np.percentile(b, 90) / np.percentile(b, 10)), R_full=float(b.max() / b.min()),
                            x0_median=float(np.median(gg["x0"])), n_at_cap=int(g["at_cap"].sum()),
                            n_weak=int((g["lam"] < 0.25).sum()))
    return out


def fig_curves(tab, fit, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for cand in ["Hiragino Sans", "Hiragino Maru Gothic Pro", "Noto Sans CJK JP", "IPAexGothic", "Yu Gothic"]:
        if any(f.name == cand for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break
    cards = sorted(tab["stimulus_id"].unique())
    speeds = sorted(tab["speed_idx"].unique())
    ncol = 8; nrow = int(np.ceil(len(cards) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(2.3 * ncol, 2.0 * nrow), sharex=True, sharey=True)
    xs = np.linspace(0, 500, 200)
    cmap = plt.get_cmap("viridis")
    for ax, card in zip(axes.flat, cards):
        for sp in speeds:
            col = cmap((speeds.index(sp)) / max(1, len(speeds) - 1)) if len(speeds) > 1 else "C0"
            g = tab[(tab["stimulus_id"] == card) & (tab["speed_idx"] == sp)]
            f = fit[(fit["stimulus_id"] == card) & (fit["speed_idx"] == sp)]
            ax.plot(g["cut_ms"], g["p"], "o", ms=3, color=col)
            if len(f):
                r = f.iloc[0]
                ax.plot(xs, logistic(xs, r["x0"], r["b1"], r["lam"]), "-", lw=1, color=col,
                        label=(f"{r['fade_ms']}ms" if r["fade_ms"] != "" else None))
        ax.axhline(GAMMA, color="#999", lw=0.5, ls=":")
        ax.set_title(card, fontsize=11, pad=2)
        ax.set_ylim(-0.03, 1.03); ax.set_xlim(0, 500)
        ax.tick_params(labelsize=7)
    for ax in axes.flat[len(cards):]:
        ax.axis("off")
    if len(speeds) > 1:
        axes.flat[0].legend(fontsize=6, frameon=False, title="フェード", title_fontsize=6)
    fig.suptitle(title, fontsize=12)
    fig.supxlabel("打ち切り(第一音の音響的開始からの ms)", fontsize=9)
    fig.supylabel("正答率(44択)", fontsize=9)
    fig.tight_layout(rect=(0.02, 0.02, 1, 0.97))
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 4. 擬似データ(推定の回復の確認)
# ---------------------------------------------------------------------------
def simulate(n_participants, task, rng, path):
    cards = json.load(open(os.path.join(HERE, "cards_jomo.json"), encoding="utf-8"))["cards"]
    ids = [c["id"] for c in cards]
    true = {}
    for i, cid in enumerate(ids):
        b1 = float(np.exp(rng.uniform(np.log(0.03), np.log(0.5))))
        x0 = float(rng.uniform(60, 220))
        lam = float(rng.uniform(0.85, 1.0))
        true[cid] = dict(x0=x0, b1=b1, lam=lam)
    rows = []
    speeds = list(range(5)) if task == "visual" else [-1]
    for p in range(n_participants):
        pid = f"sim{p:04d}"
        cells = [(s, c) for s in speeds for c in CUTS_MS]
        plan = []
        while len(plan) < 64:
            plan += [cells[i] for i in rng.permutation(len(cells))]
        plan = plan[:64] + [(speeds[i % len(speeds)], CATCH_MS) for i in range(8)]
        deck = [ids[i] for i in rng.permutation(len(ids))] * 2
        for j, (sp, cut) in enumerate(plan):
            cid = deck[j]
            t = true[cid]
            # 文字課題: 速い段階ほど β1 が大きい(等比)という仮の真値
            b1 = t["b1"] * (10 ** (sp / 4) / 10 ** 0.5) if sp >= 0 else t["b1"]
            pr = logistic(cut, t["x0"], b1, t["lam"])
            ok = rng.random() < pr
            resp = cid if ok else ids[rng.integers(len(ids))]
            rows.append(dict(participant_id=pid, task=("visual_card" if task == "visual" else "audio_card"),
                             stimulus_id=cid, cut_ms=cut, is_catch=(cut == CATCH_MS), response_char=resp,
                             correct_char=cid, correct=(resp == cid), speed_idx=(sp if sp >= 0 else ""),
                             fade_ms=(FADE_MS_LEVELS[sp] if sp >= 0 else ""), rt_ms=int(rng.uniform(800, 3000)), replays=0))
    pd.DataFrame(rows).to_csv(path, index=False)
    return true


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="*")
    ap.add_argument("--task", choices=["audio", "visual"], default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    ap.add_argument("--simulate", type=int, default=0, help="N 名ぶんの擬似データで推定の回復を確かめる")
    ap.add_argument("--no-fig", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rng = np.random.default_rng(SEED)

    truth = None
    if args.simulate:
        task = args.task or "audio"
        simp = os.path.join(args.out, "simulated_trials.csv")
        truth = simulate(args.simulate, task, rng, simp)
        args.inputs = [simp]; args.task = task
    if not args.inputs:
        ap.error("入力ファイルを指定する(か --simulate N)")

    df = load_inputs(args.inputs)
    main_df, info = select_trials(df, args.task)
    print("読み込み:", json.dumps({k: v for k, v in info.items() if k != "excluded"}, ensure_ascii=False))
    if info["n_excluded"]:
        print("除外:", json.dumps(info["excluded"], ensure_ascii=False))
    tab = aggregate(main_df)
    tab.to_csv(os.path.join(args.out, "curve_points.csv"), index=False)
    fit = fit_all(tab, rng)
    fit.to_csv(os.path.join(args.out, "fit_table.csv"), index=False, float_format="%.5g")
    summ = dict(input=info, gamma=GAMMA, cuts_ms=CUTS_MS, b1_bounds=[B1_LO, B1_HI], by_speed=summarize(fit))
    if truth is not None:
        f0 = fit[fit["speed_idx"] == (2 if args.task == "visual" else -1)]
        err = []
        for _, r in f0.iterrows():
            t = truth[r["stimulus_id"]]
            err.append(dict(card=r["stimulus_id"], b1_true=t["b1"], b1_est=r["b1"], x0_true=t["x0"], x0_est=r["x0"],
                            in_ci=(r["b1_lo"] <= t["b1"] <= r["b1_hi"])))
        e = pd.DataFrame(err)
        summ["simulation"] = dict(n_participants=args.simulate,
                                  log10_b1_rmse=float(np.sqrt(np.mean((np.log10(e["b1_est"]) - np.log10(e["b1_true"])) ** 2))),
                                  x0_rmse=float(np.sqrt(np.mean((e["x0_est"] - e["x0_true"]) ** 2))),
                                  ci_coverage=float(e["in_ci"].mean()))
        print("擬似データでの回復:", json.dumps(summ["simulation"], ensure_ascii=False))
    json.dump(summ, open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(summ["by_speed"], ensure_ascii=False, indent=1))
    if not args.no_fig:
        title = "上毛かるた 札ごとの認識率曲線 " + ("(文字・フェード5段階)" if args.task == "visual" else "(音声・通し読み)")
        fig_curves(tab, fit, os.path.join(args.out, "fig_curves.png"), title)
    print("書き出し先:", args.out)


if __name__ == "__main__":
    main()
