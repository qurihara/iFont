#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""乙課題(3音連続提示)の干渉判定ルールの検出力シミュレーション (F2)。

判定したい仮説:
  「間隔S=200msでの1音目の正答率は、頭打ち(S=450,700msのプール)と比べて
   δポイント以上は低下していない(=干渉なし)」

判定ルール(事前登録案。docs/prereg_interference.md と対応):
  参加者iごとに d_i = acc1(頭打ち12試行) - acc1(S=200の6試行) を計算し、
  Δ^ = mean(d_i)、SE = sd(d_i)/√N とする。片側α=0.05の2本の検定:
    非劣性: Δ^ + t_{0.95,N-1}·SE < δ           ならば「干渉なし」
    劣化  : Δ^ - t_{0.95,N-1}·SE > 0 (かつ非劣性不成立) ならば「干渉あり」
    どちらでもなければ「判定保留」

生成モデル(シミュレーションの真実):
  logit P(correct1) = α + a_i + b_c - β·1[S=200]
    a_i ~ N(0, σ_subj²)   参加者のばらつき
    b_c ~ N(0, σ_item²)   字(音)のばらつき
  α, β は「周辺正答率(a,bで平均した正答率)」が狙いの値になるよう数値求解で較正する。
  したがって真の差Δは常に確率スケールのポイント差として定義される。

近似の妥当性(重要な3点):
  (1) 本番の出題は「混ぜたデッキから順に配る」ため、同一セッション内で1音目に
      同じ字は2度出ない(42試行 < 字数68/72)。よって参加者内の試行は a_i を与えれば
      独立で、字のばらつき σ_item は参加者内の差得点 d_i の分散をほとんど増やさない
      (1試行の周辺分散は混合によらず p̄(1-p̄) のまま)。主グリッドは字を毎回新規に
      引く「無限プール」で回し、実際の「有限プール(68字を参加者間で共有・
      参加者内非復元)」との一致を検証セルで確認する。
  (2) 参加者ランダム効果 a_i は差得点の中で相殺される(同一参加者の両条件に共通)。
  (3) 対の差得点のt検定は、推定対象(集団平均の正答率差)に対して不偏で、
      階層ロジスティック回帰とほぼ同等以下の効率。したがって本シミュレーションの
      必要Nは保守的(多めに出る)側に倒れる。

実行:
  /Users/kurihara/Desktop/claude_work/ifont_env/bigram_venv/bin/python power_sim_interference.py

出力: 標準出力に表、同ディレクトリに power_sim_interference_results.json
"""

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from numpy.polynomial.hermite_e import hermegauss
from scipy import optimize, special, stats

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

SEED = 20260718
REPS_MAIN = 10000   # 主グリッド
REPS_SUB = 4000     # 感度分析・検証セル
ALPHA_ONE_SIDED = 0.05
DELTAS = [0.05, 0.08, 0.10]                 # 非劣性マージン候補
TRUE_DELTAS = [0.0, 0.03, 0.05, 0.08, 0.10]  # 真の差(確率ポイント)
N_GRID = [10, 20, 30, 40, 50, 60, 80, 100, 130, 150, 200]

# シナリオ(パイロットからの仮値。根拠は下の estimate_from_pilot と prereg 文書)
SCEN = {
    "audio": dict(p_plat=0.70, sig_s=0.6, sig_i=1.2, K=68),
    "visual": dict(p_plat=0.90, sig_s=0.6, sig_i=1.2, K=72),
}

GH_X, GH_W = hermegauss(81)
SQRT2PI = math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------- 較正

def marginal_acc(alpha, s):
    """E[expit(alpha + s·Z)], Z~N(0,1) をガウス=エルミート求積で計算。"""
    if s == 0.0:
        return float(special.expit(alpha))
    return float(np.sum(GH_W * special.expit(alpha + s * GH_X)) / SQRT2PI)


def solve_logit(p_target, s):
    return optimize.brentq(lambda a: marginal_acc(a, s) - p_target, -12.0, 12.0, xtol=1e-12)


def calibrate(p_plat, true_delta, sig_s, sig_i, sig_beta=0.0):
    """周辺正答率が 頭打ち=p_plat, S200=p_plat-true_delta になる α, β を返す。"""
    s_plat = math.hypot(sig_s, sig_i)
    alpha = solve_logit(p_plat, s_plat)
    s_200 = math.sqrt(sig_s ** 2 + sig_i ** 2 + sig_beta ** 2)
    alpha_200 = solve_logit(p_plat - true_delta, s_200)
    beta = alpha - alpha_200
    return alpha, beta


# ---------------------------------------------------------------- 生成

def sim_infinite(N, n200, nplat, alpha, beta, sig_s, sig_i, sig_beta, reps, rng, chunk=1000):
    """無限プール近似: 字効果を試行ごとに新規に引く(参加者内で字が重複しない設計の近似)。
    戻り値: d (reps, N) 参加者ごとの 頭打ち正答率 - S200正答率。"""
    out = []
    left = reps
    while left > 0:
        c = min(chunk, left)
        left -= c
        a = rng.normal(0.0, sig_s, (c, N, 1))
        g200 = alpha - beta + a
        if sig_beta > 0:
            g200 = g200 + rng.normal(0.0, sig_beta, (c, N, 1))
        p200 = special.expit(g200 + rng.normal(0.0, sig_i, (c, N, n200)))
        pplat = special.expit(alpha + a + rng.normal(0.0, sig_i, (c, N, nplat)))
        y200 = (rng.random((c, N, n200)) < p200).mean(-1)
        yplat = (rng.random((c, N, nplat)) < pplat).mean(-1)
        out.append(yplat - y200)
    return np.concatenate(out, 0)


def sim_finite(N, K, n200, nplat, alpha, beta, sig_s, sig_i, reps, rng, chunk=250):
    """有限プール: 1反復=1つの字セット(K字)の実現値を参加者全員で共有し、
    参加者ごとに非復元で n200+nplat 字を無作為に条件へ割り当てる(実際のデッキ配りは
    一様ランダムな並べ替えの先頭42枚を水準へ順に割るので、これと分布同等)。"""
    out = []
    m = n200 + nplat
    left = reps
    while left > 0:
        c = min(chunk, left)
        left -= c
        bpool = rng.normal(0.0, sig_i, (c, 1, K))
        order = np.argsort(rng.random((c, N, K)), axis=-1)[..., :m]
        b = np.take_along_axis(np.broadcast_to(bpool, (c, N, K)), order, axis=-1)
        a = rng.normal(0.0, sig_s, (c, N, 1))
        p200 = special.expit(alpha - beta + a + b[..., :n200])
        pplat = special.expit(alpha + a + b[..., n200:])
        y200 = (rng.random((c, N, n200)) < p200).mean(-1)
        yplat = (rng.random((c, N, nplat)) < pplat).mean(-1)
        out.append(yplat - y200)
    return np.concatenate(out, 0)


# ---------------------------------------------------------------- 判定

def analyze(d, deltas=DELTAS, alpha_one=ALPHA_ONE_SIDED):
    """d: (reps, N)。判定ルールを適用し、判定確率を返す。"""
    reps, N = d.shape
    dbar = d.mean(1)
    sd = d.std(1, ddof=1)
    se = sd / math.sqrt(N)
    tcrit = float(stats.t.ppf(1.0 - alpha_one, N - 1))
    upper = dbar + tcrit * se
    lower = dbar - tcrit * se
    deg = lower > 0.0
    res = {
        "dbar_mean": float(dbar.mean()),
        "dbar_sd": float(dbar.std(ddof=1)),
        "p_deg": float(deg.mean()),  # 「劣化が有意」の率(δに依存しない)
        "rules": {},
    }
    for dl in deltas:
        ni = upper < dl
        v_no = ni                    # 干渉なし(非劣性成立。有意な劣化を伴っても余白内なら「なし」)
        v_yes = (~ni) & deg          # 干渉あり
        v_hold = ~(v_no | v_yes)     # 判定保留
        res["rules"][f"{dl:.2f}"] = {
            "p_no": float(v_no.mean()),
            "p_yes": float(v_yes.mean()),
            "p_hold": float(v_hold.mean()),
            "p_ni_and_deg": float((ni & deg).mean()),
        }
    return res


def analytic_ni_power(p_plat, true_delta, delta, N, n200, nplat):
    """正規近似による非劣性検出力(検算用)。sd(d_i)≈√(p̄(1-p̄)(1/n200+1/nplat))。"""
    pbar = p_plat - true_delta / 2.0
    sd = math.sqrt(pbar * (1 - pbar) * (1.0 / n200 + 1.0 / nplat))
    se = sd / math.sqrt(N)
    z = (delta - true_delta) / se - stats.norm.ppf(1 - ALPHA_ONE_SIDED)
    return float(stats.norm.cdf(z))


# ---------------------------------------------------------------- パイロット推定

def estimate_from_pilot():
    """既存パイロット(PI 1名)から基準正答率の実測値を出す(仮値設定の根拠)。"""
    files = [
        REPO / "temp" / "pilot_soa_audio_1784347651433.json",   # きりたん v3.2
        REPO / "pilot_results" / "audio_v1.9.json",             # めたん時代
        REPO / "pilot_results" / "audio_v2.0.json",
    ]
    tot = {"plat": [0, 0], "s200": [0, 0]}
    per_file = {}
    for f in files:
        if not f.exists():
            per_file[f.name] = "not found"
            continue
        d = json.loads(f.read_text())
        cnt = {"plat": [0, 0], "s200": [0, 0]}
        for t in d["trials"]:
            key = "s200" if t["S"] == 200 else ("plat" if t["S"] in (450, 700) else None)
            if key:
                cnt[key][0] += int(bool(t["correct1"]))
                cnt[key][1] += 1
        per_file[f.name] = {k: f"{v[0]}/{v[1]}" for k, v in cnt.items()}
        for k in tot:
            tot[k][0] += cnt[k][0]
            tot[k][1] += cnt[k][1]

    def wilson(k, n):
        if n == 0:
            return (float("nan"),) * 3
        z = 1.959963984540054
        p = k / n
        den = 1 + z * z / n
        mid = (p + z * z / (2 * n)) / den
        hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
        return p, mid - hw, mid + hw

    summary = {}
    for k, (s, n) in tot.items():
        p, lo, hi = wilson(s, n)
        summary[k] = dict(k=s, n=n, p=round(p, 4), ci95=[round(lo, 4), round(hi, 4)])
    return per_file, summary


# ---------------------------------------------------------------- 実行

def fmt_pct(x):
    return f"{100.0 * x:5.1f}"


def run():
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    results = {
        "config": dict(seed=SEED, reps_main=REPS_MAIN, reps_sub=REPS_SUB,
                       alpha_one_sided=ALPHA_ONE_SIDED, deltas=DELTAS,
                       true_deltas=TRUE_DELTAS, n_grid=N_GRID, scenarios=SCEN),
    }

    print("=" * 78)
    print("F2 乙課題 干渉判定ルールの検出力シミュレーション")
    print(f"seed={SEED}  reps(主グリッド)={REPS_MAIN}  片側α={ALPHA_ONE_SIDED}")
    print("=" * 78)

    # --- パイロット実測 ---
    per_file, summary = estimate_from_pilot()
    results["pilot_estimates"] = dict(per_file=per_file, pooled=summary)
    print("\n[0] パイロット実測(PI1名・聴覚・3セッション合算, correct1)")
    for name, v in per_file.items():
        print(f"  {name}: {v}")
    for k, v in summary.items():
        lab = "頭打ち(450+700)" if k == "plat" else "S=200"
        print(f"  合算 {lab}: {v['k']}/{v['n']} = {v['p']:.3f}  (Wilson95% {v['ci95'][0]:.3f}-{v['ci95'][1]:.3f})")
    dpt = summary["plat"]["p"] - summary["s200"]["p"]
    print(f"  合算の点推定差 Δ^ = 頭打ち - S200 = {dpt:+.3f} (負なら S200 のほうが良い)")

    # --- 主グリッド ---
    print("\n[1] 主グリッド(現行構造: 各水準6問, S200=6試行, 頭打ち=12試行)")
    main = {}
    for scen_name, sc in SCEN.items():
        main[scen_name] = {}
        for N in N_GRID:
            main[scen_name][str(N)] = {}
            for td in TRUE_DELTAS:
                alpha, beta = calibrate(sc["p_plat"], td, sc["sig_s"], sc["sig_i"])
                d = sim_infinite(N, 6, 12, alpha, beta, sc["sig_s"], sc["sig_i"], 0.0,
                                 REPS_MAIN, rng)
                main[scen_name][str(N)][f"{td:.2f}"] = analyze(d)
    results["main"] = main

    for scen_name, sc in SCEN.items():
        print(f"\n  --- シナリオ {scen_name}: 頭打ち正答率={sc['p_plat']:.2f}, "
              f"σ_subj={sc['sig_s']}, σ_item={sc['sig_i']} ---")
        for dl in DELTAS:
            key = f"{dl:.2f}"
            print(f"\n  δ = {dl:.2f} ({int(dl*100)}ポイント)")
            print("    N   | なし|Δ=0  保留|Δ=0  あり|Δ=0 | あり|Δ=.08 あり|Δ=.10 | なし|Δ=δ(誤判定)  解析近似(なし|Δ=0)")
            for N in N_GRID:
                r0 = main[scen_name][str(N)]["0.00"]["rules"][key]
                r8 = main[scen_name][str(N)]["0.08"]["rules"][key]
                r10 = main[scen_name][str(N)]["0.10"]["rules"][key]
                rM = main[scen_name][str(N)][key]["rules"][key]  # 真の差=δ ちょうど
                ana = analytic_ni_power(sc["p_plat"], 0.0, dl, N, 6, 12)
                print(f"    {N:3d} |  {fmt_pct(r0['p_no'])}   {fmt_pct(r0['p_hold'])}   {fmt_pct(r0['p_yes'])}  |"
                      f"   {fmt_pct(r8['p_yes'])}    {fmt_pct(r10['p_yes'])}   |"
                      f"     {fmt_pct(rM['p_no'])}          {fmt_pct(ana)}")

    # --- 有限プール検証 ---
    print("\n[2] 検証: 無限プール近似 vs 有限プール(68字共有・参加者内非復元) [audio基準]")
    sc = SCEN["audio"]
    fp = []
    for N in (40, 130):
        for td in (0.0, 0.08):
            alpha, beta = calibrate(sc["p_plat"], td, sc["sig_s"], sc["sig_i"])
            d_inf = sim_infinite(N, 6, 12, alpha, beta, sc["sig_s"], sc["sig_i"], 0.0, REPS_SUB, rng)
            d_fin = sim_finite(N, sc["K"], 6, 12, alpha, beta, sc["sig_s"], sc["sig_i"], REPS_SUB, rng)
            ai, af = analyze(d_inf), analyze(d_fin)
            row = dict(N=N, true_delta=td,
                       inf=ai["rules"]["0.05"], fin=af["rules"]["0.05"],
                       sd_d_inf=float(np.std(d_inf, ddof=1)), sd_d_fin=float(np.std(d_fin, ddof=1)))
            fp.append(row)
            print(f"  N={N:3d} Δ={td:.2f}: なし率 無限={fmt_pct(ai['rules']['0.05']['p_no'])} "
                  f"有限={fmt_pct(af['rules']['0.05']['p_no'])} / あり率 無限={fmt_pct(ai['rules']['0.05']['p_yes'])} "
                  f"有限={fmt_pct(af['rules']['0.05']['p_yes'])} / sd(d) 無限={np.std(d_inf, ddof=1):.4f} "
                  f"有限={np.std(d_fin, ddof=1):.4f}")
    results["finite_pool_check"] = fp

    # --- 感度分析 ---
    print("\n[3] 感度分析(判定確率, δ=0.05)")
    sens_cfg = [
        ("audio 基準", "audio", dict()),
        ("audio 頭打ち0.60", "audio", dict(p_plat=0.60)),
        ("audio 頭打ち0.80", "audio", dict(p_plat=0.80)),
        ("audio σ_item=0.8", "audio", dict(sig_i=0.8)),
        ("audio σ_item=1.6", "audio", dict(sig_i=1.6)),
        ("audio σ_subj=0.3", "audio", dict(sig_s=0.3)),
        ("audio σ_subj=1.0", "audio", dict(sig_s=1.0)),
        ("audio 干渉の個人差 σ_β=0.2", "audio", dict(sig_beta=0.2)),
        ("visual 基準", "visual", dict()),
        ("visual 頭打ち0.85", "visual", dict(p_plat=0.85)),
        ("visual 頭打ち0.95", "visual", dict(p_plat=0.95)),
    ]
    sens = []
    for label, base, over in sens_cfg:
        sc = dict(SCEN[base])
        sig_beta = over.pop("sig_beta", 0.0)
        sc.update(over)
        Ns = (60, 130) if base == "audio" else (60, 80)
        for N in Ns:
            row = dict(label=label, N=N)
            for td in (0.0, 0.08):
                alpha, beta = calibrate(sc["p_plat"], td, sc["sig_s"], sc["sig_i"], sig_beta)
                d = sim_infinite(N, 6, 12, alpha, beta, sc["sig_s"], sc["sig_i"], sig_beta,
                                 REPS_SUB, rng)
                r = analyze(d)["rules"]["0.05"]
                row[f"no@{td:.2f}"] = r["p_no"]
                row[f"yes@{td:.2f}"] = r["p_yes"]
            sens.append(row)
            print(f"  {label:26s} N={N:3d}: なし|Δ=0 {fmt_pct(row['no@0.00'])}  "
                  f"あり|Δ=0 {fmt_pct(row['yes@0.00'])}  あり|Δ=.08 {fmt_pct(row['yes@0.08'])}")
    results["sensitivity"] = sens

    # --- 水準あたり試行数を変えた場合(参考。セッション時間の制約に注意) ---
    print("\n[4] 参考: 水準あたり試行数を増やした場合 (audio基準, δ=0.05)")
    print("    per_level=6: 42問(現行, 8-12分) / 9: 63問(約13-18分) / 12: 84問(約17-24分)")
    per_level = []
    sc = SCEN["audio"]
    for pl in (6, 9, 12):
        n200, nplat = pl, 2 * pl
        for N in (40, 60, 80, 100, 130):
            row = dict(per_level=pl, N=N)
            for td in (0.0, 0.08):
                alpha, beta = calibrate(sc["p_plat"], td, sc["sig_s"], sc["sig_i"])
                d = sim_infinite(N, n200, nplat, alpha, beta, sc["sig_s"], sc["sig_i"], 0.0,
                                 REPS_SUB, rng)
                r = analyze(d)["rules"]["0.05"]
                row[f"no@{td:.2f}"] = r["p_no"]
                row[f"yes@{td:.2f}"] = r["p_yes"]
            per_level.append(row)
            print(f"  per_level={pl:2d} N={N:3d}: なし|Δ=0 {fmt_pct(row['no@0.00'])}  "
                  f"あり|Δ=.08 {fmt_pct(row['yes@0.08'])}")
    results["per_level"] = per_level

    out = HERE / "power_sim_interference_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(f"\n結果JSON: {out}")
    print(f"所要 {time.time() - t0:.1f} 秒")


if __name__ == "__main__":
    run()
