#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""追加検出力セル計算(丸山パイロット後の低頭打ちシナリオ)。

事前登録済みの power_sim_interference.py を import してそのまま再利用する。
生成モデル: sim_infinite (登録済み主グリッドと同一; 較正は calibrate)。
判定: analyze (差得点の対応 t, 片側α=0.05, 非劣性+劣化の3値判定)。

セル(すべて聴覚: sig_s=0.6, sig_i=1.2, n200=6, nplat=12, reps=10000):
  1) δ=0.08, N=60 : p_plat∈{0.60,0.65,0.70} × true_delta∈{0.0,0.08,0.10}
  2) δ=0.08, N=80 : 同上
  3) δ=0.05, N=130: p_plat=0.65 × true_delta∈{0.0,0.05,0.08}
乱数種 20260722、単一 rng を登録スクリプトと同様にセル間で引き継ぐ。

検証:
  A) δ=0.08/N=60/p_plat=0.70/true=0 が登録済み結果(p_no=86.5%)と種違いの範囲で一致
  B) 複数セルで analytic_ni_power(登録スクリプト内の正規近似)と突き合わせ
"""

import json
import sys
import time
from pathlib import Path

TOOLS = ("/Users/kurihara/Library/CloudStorage/GoogleDrive-qurihara@gmail.com/"
         "マイドライブ/share/google_desktop_share/iFont/experiment/tools")
sys.path.insert(0, TOOLS)

import numpy as np  # noqa: E402
import power_sim_interference as psi  # noqa: E402  登録済みスクリプトを再利用

OUT_DIR = Path(__file__).resolve().parent

SEED = 20260722
REPS = 10000
SIG_S = 0.6
SIG_I = 1.2
N200, NPLAT = 6, 12

# (block_label, delta_rule, N, p_plat list, true_delta list)
BLOCKS = [
    ("main_d08_N60", 0.08, 60, [0.60, 0.65, 0.70], [0.0, 0.08, 0.10]),
    ("main_d08_N80", 0.08, 80, [0.60, 0.65, 0.70], [0.0, 0.08, 0.10]),
    ("altB_d05_N130", 0.05, 130, [0.65], [0.0, 0.05, 0.08]),
]


def main():
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    cells = []
    for label, dl, N, pplats, tds in BLOCKS:
        for pp in pplats:
            for td in tds:
                alpha, beta = psi.calibrate(pp, td, SIG_S, SIG_I)
                d = psi.sim_infinite(N, N200, NPLAT, alpha, beta, SIG_S, SIG_I,
                                     0.0, REPS, rng)
                res = psi.analyze(d)
                r = res["rules"][f"{dl:.2f}"]
                ana = psi.analytic_ni_power(pp, td, dl, N, N200, NPLAT)
                cells.append(dict(
                    block=label, delta_rule=dl, N=N, p_plat=pp, true_delta=td,
                    p_no=r["p_no"], p_hold=r["p_hold"], p_yes=r["p_yes"],
                    p_ni_and_deg=r["p_ni_and_deg"],
                    dbar_mean=res["dbar_mean"], dbar_sd=res["dbar_sd"],
                    p_deg=res["p_deg"],
                    analytic_p_no=ana,
                    all_rules=res["rules"],
                ))
                print(f"{label}  p_plat={pp:.2f} true={td:.2f}: "
                      f"no={100*r['p_no']:5.1f} hold={100*r['p_hold']:5.1f} "
                      f"yes={100*r['p_yes']:5.1f}  (analytic no={100*ana:5.1f})")

    out = dict(
        config=dict(seed=SEED, reps=REPS, sig_s=SIG_S, sig_i=SIG_I,
                    n200=N200, nplat=NPLAT, alpha_one_sided=psi.ALPHA_ONE_SIDED,
                    source_script=str(Path(TOOLS) / "power_sim_interference.py")),
        cells=cells,
        elapsed_sec=time.time() - t0,
    )
    (OUT_DIR / "power_cells_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\nJSON: {OUT_DIR / 'power_cells_results.json'}")
    print(f"elapsed {out['elapsed_sec']:.1f}s")


if __name__ == "__main__":
    main()
