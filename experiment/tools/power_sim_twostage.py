#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""二段階の干渉判定(主案)の正式な判定確率シミュレーション。

事前登録に載せる数値を「正直な二段階モンテカルロ」で計算する。
生成モデルは experiment/tools/power_sim_interference.py の calibrate / sim_infinite を
そのまま import して再利用する(参加者SD=0.6・字SD=1.2 の logit 混合、
1人あたり S200=6試行・頭打ち12試行)。

【二段階手続き(1レプリケーション内で忠実に実装)】
- 第一段: N1(聴覚60/視覚40)のデータで参加者ごとの差得点のt検定。
  片側α=0.025 (⇔両側95%CI)。U=CI上限, L=CI下限。
    U < δ1(=0.08)                → 「干渉なし」確定
    U ≥ δ1 かつ L > 0            → 「干渉あり」確定
    どちらでもない                → 保留 → 第二段へ
- 第二段(保留のみ): 追加参加者を生成して N2(聴覚130/視覚80)まで増員し、
  全データ(第一段+追加)をプールして δ2=0.05 を片側α=0.025 で再判定(同じ3区分)。
  第二段でも決まらなければ最終「保留」。

実装ノート: 参加者は i.i.d. なので、各レプリケーションで N2 人分を先に生成し、
第一段は先頭 N1 人、第二段は全 N2 人(=第一段の N1 人 + 追加 N2-N1 人のプール)を
使うのは、「保留のときだけ追加生成する」手続きと分布として同一である。
第二段の判定は保留レプリケーションにのみ適用する。

セル: 聴覚 頭打ち∈{0.70,0.65,0.60}×真の差∈{0,0.05,0.08,0.10}
      視覚 頭打ち∈{0.90,0.85}×真の差∈{0,0.05,0.08}
各セル10000反復、seed=20260723。
"""

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy import stats

TOOLS = Path("/Users/kurihara/Library/CloudStorage/GoogleDrive-qurihara@gmail.com/"
             "マイドライブ/share/google_desktop_share/iFont/experiment/tools")
sys.path.insert(0, str(TOOLS))
from power_sim_interference import calibrate, sim_infinite  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

SEED = 20260723
REPS = 10000
ALPHA_ONE = 0.025          # 片側α(両側95%CIと同値)
DELTA1 = 0.08              # 第一段の非劣性マージン
DELTA2 = 0.05              # 第二段の非劣性マージン
SIG_S = 0.6                # 参加者SD
SIG_I = 1.2                # 字SD
N200, NPLAT = 6, 12        # 1人あたり試行数

SCEN = {
    "audio":  dict(N1=60, N2=130, p_plats=[0.70, 0.65, 0.60],
                   true_deltas=[0.0, 0.05, 0.08, 0.10]),
    "visual": dict(N1=40, N2=80,  p_plats=[0.90, 0.85],
                   true_deltas=[0.0, 0.05, 0.08]),
}


def judge(d, delta, alpha_one=ALPHA_ONE):
    """d: (reps, N)。3区分判定 (no, yes, hold) のブールベクトルを返す。"""
    reps, N = d.shape
    dbar = d.mean(1)
    se = d.std(1, ddof=1) / math.sqrt(N)
    tcrit = float(stats.t.ppf(1.0 - alpha_one, N - 1))
    U = dbar + tcrit * se
    L = dbar - tcrit * se
    no = U < delta
    yes = (~no) & (L > 0.0)
    hold = ~(no | yes)
    return no, yes, hold


def analytic_stage1_no(p_plat, true_delta, delta, N, alpha_one=ALPHA_ONE,
                       use_t=False):
    """第一段「なし」の解析近似(正規近似)。sd(d̄)=√(p̄(1-p̄)(1/6+1/12))/√N。
    use_t=True なら棄却限界に(実際の検定と同じ) t 分位点を使う変種。"""
    pbar = p_plat - true_delta / 2.0
    se = math.sqrt(pbar * (1 - pbar) * (1.0 / N200 + 1.0 / NPLAT)) / math.sqrt(N)
    crit = float(stats.t.ppf(1 - alpha_one, N - 1)) if use_t \
        else float(stats.norm.ppf(1 - alpha_one))
    z = (delta - true_delta) / se - crit
    return float(stats.norm.cdf(z))


def run():
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    results = {
        "config": dict(seed=SEED, reps=REPS, alpha_one_sided=ALPHA_ONE,
                       delta1=DELTA1, delta2=DELTA2,
                       sig_subj=SIG_S, sig_item=SIG_I,
                       n200=N200, nplat=NPLAT,
                       scenarios={k: dict(N1=v["N1"], N2=v["N2"],
                                          p_plats=v["p_plats"],
                                          true_deltas=v["true_deltas"])
                                  for k, v in SCEN.items()}),
        "cells": [],
    }

    print("=" * 100)
    print("二段階干渉判定(主案)の判定確率  seed=%d  reps=%d  片側α=%.3f" % (SEED, REPS, ALPHA_ONE))
    print("第一段: N1で δ1=%.2f / 第二段(保留のみ): N2にプールして δ2=%.2f" % (DELTA1, DELTA2))
    print("=" * 100)

    for scen_name, sc in SCEN.items():
        N1, N2 = sc["N1"], sc["N2"]
        print(f"\n--- {scen_name}: N1={N1}, N2={N2} ---")
        print("  頭打ち  真Δ  | 1段なし 1段あり 2段へ | 2段なし 2段あり | 最終なし 最終あり 最終保留")
        for p_plat in sc["p_plats"]:
            for td in sc["true_deltas"]:
                alpha, beta = calibrate(p_plat, td, SIG_S, SIG_I)
                # N2人分を一括生成(先頭N1人=第一段、全N2人=第二段プール)
                d = sim_infinite(N2, N200, NPLAT, alpha, beta, SIG_S, SIG_I, 0.0,
                                 REPS, rng)
                no1, yes1, hold1 = judge(d[:, :N1], DELTA1)
                no2_all, yes2_all, hold2_all = judge(d, DELTA2)
                # 第二段の判定は保留レプリケーションにのみ適用
                no2 = hold1 & no2_all
                yes2 = hold1 & yes2_all
                hold2 = hold1 & hold2_all
                fin_no = no1 | no2
                fin_yes = yes1 | yes2
                fin_hold = hold2
                assert np.all(fin_no.astype(int) + fin_yes.astype(int)
                              + fin_hold.astype(int) == 1)
                cell = dict(
                    scenario=scen_name, p_plat=p_plat, true_delta=td,
                    N1=N1, N2=N2,
                    p_stage1_no=float(no1.mean()),
                    p_stage1_yes=float(yes1.mean()),
                    p_stage1_hold=float(hold1.mean()),
                    p_stage2_no=float(no2.mean()),
                    p_stage2_yes=float(yes2.mean()),
                    p_final_no=float(fin_no.mean()),
                    p_final_yes=float(fin_yes.mean()),
                    p_final_hold=float(fin_hold.mean()),
                    analytic_stage1_no=analytic_stage1_no(p_plat, td, DELTA1, N1),
                    analytic_stage1_no_tcrit=analytic_stage1_no(
                        p_plat, td, DELTA1, N1, use_t=True),
                )
                results["cells"].append(cell)
                print(f"  {p_plat:.2f}  {td:.2f}  |"
                      f"  {100*cell['p_stage1_no']:5.1f}  {100*cell['p_stage1_yes']:5.1f}"
                      f"  {100*cell['p_stage1_hold']:5.1f} |"
                      f"  {100*cell['p_stage2_no']:5.1f}  {100*cell['p_stage2_yes']:5.1f} |"
                      f"  {100*cell['p_final_no']:5.1f}  {100*cell['p_final_yes']:5.1f}"
                      f"  {100*cell['p_final_hold']:5.1f}")

    # ---------------- 誤り率の検証 ----------------
    print("\n[誤り率の検証]")
    checks = {"a_stage1_no_at_td008": [], "b_stage2_no_at_td005": []}
    for c in results["cells"]:
        if abs(c["true_delta"] - 0.08) < 1e-9:
            ok = c["p_stage1_no"] <= 0.03  # 約2.5%以下(MC誤差込みで3%を許容)
            checks["a_stage1_no_at_td008"].append(
                dict(scenario=c["scenario"], p_plat=c["p_plat"],
                     p=c["p_stage1_no"], ok=bool(ok)))
            print(f"  (a) {c['scenario']} 頭打ち{c['p_plat']:.2f} 真Δ=0.08: "
                  f"第一段「なし」誤り = {100*c['p_stage1_no']:.2f}%  "
                  f"({'OK' if ok else 'NG'}: 約2.5%以下)")
    for c in results["cells"]:
        if abs(c["true_delta"] - 0.05) < 1e-9:
            ok = c["p_stage2_no"] <= 0.03
            checks["b_stage2_no_at_td005"].append(
                dict(scenario=c["scenario"], p_plat=c["p_plat"],
                     p=c["p_stage2_no"], ok=bool(ok)))
            print(f"  (b) {c['scenario']} 頭打ち{c['p_plat']:.2f} 真Δ=0.05: "
                  f"第二段経由「なし(δ2=0.05)」誤り = {100*c['p_stage2_no']:.2f}%  "
                  f"({'OK' if ok else 'NG'}: 約2.5%以下)")
    results["error_checks"] = checks

    # ---------------- 自己検証: 第一段の周辺確率 vs 解析近似 ----------------
    print("\n[自己検証] 第一段「なし」率 vs 正規近似 (真Δ=0の全セルを表示。"
          "指定の式(z分位点)で2セル以上が2pt以内なら合格)")
    print("  ※参考列: 同じ式で棄却限界のみ実際の検定と同じt分位点にした変種")
    ver = []
    for c in results["cells"]:
        if abs(c["true_delta"]) > 1e-9:
            continue
        diff_z = abs(c["p_stage1_no"] - c["analytic_stage1_no"])
        diff_t = abs(c["p_stage1_no"] - c["analytic_stage1_no_tcrit"])
        ver.append(dict(scenario=c["scenario"], p_plat=c["p_plat"],
                        sim=c["p_stage1_no"],
                        analytic_z=c["analytic_stage1_no"], diff_z=diff_z,
                        analytic_t=c["analytic_stage1_no_tcrit"], diff_t=diff_t,
                        ok_z=bool(diff_z <= 0.02)))
        print(f"  {c['scenario']:6s} 頭打ち{c['p_plat']:.2f} 真Δ=0: "
              f"シミュ={100*c['p_stage1_no']:5.1f}%  "
              f"z近似={100*c['analytic_stage1_no']:5.1f}% (差{100*diff_z:.2f}pt"
              f" {'OK' if diff_z <= 0.02 else 'NG'})  "
              f"t近似={100*c['analytic_stage1_no_tcrit']:5.1f}% (差{100*diff_t:.2f}pt"
              f" {'OK' if diff_t <= 0.02 else 'NG'})")
    n_ok = sum(v["ok_z"] for v in ver)
    print(f"  → 指定式(z)で2pt以内: {n_ok}/{len(ver)}セル "
          f"({'合格' if n_ok >= 2 else '不合格'}: 2セル以上で一致)")
    results["self_verification"] = dict(cells=ver, n_ok_z=n_ok,
                                        passed=bool(n_ok >= 2))

    out = OUT_DIR / "twostage_sim_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(f"\n結果JSON: {out}")
    print(f"所要 {time.time() - t0:.1f} 秒")


if __name__ == "__main__":
    run()
