#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
analyze_confusion.py — 聴覚の較正実験から、かな「ほ」と「こ」の混同が実際に大きいかを確かめる。

背景
  上毛かるたの競技県大会規則の「読み手に関する注意事項」に、
  「紛らわしく聞き取りにくい読み札(ほ、こ等の札)については特に注意すること」とある。
  競技の現場で知られているこの混同が、我々の測定データ(かな1音を途中まで聞かせて68音から当てる課題)
  にも現れているかを調べる。

入力
  丸山礼華さんの引き継ぎ資料(timeFont_共有_20260911)の
  data/raw/calib2_視覚_2回目/transfer_trials.csv(calib1 を含む累積。phase 列で見分ける)

本命試行の取り出し(引き継ぎ資料 AI引き継ぎ.md の規則。beta1_range/analyze_beta1.py と同じ)
  is_test が TRUE の行を除く / group == "acal"(聴覚) / modality == "transfer_audio"
  / check_kind が空(確認問題 full・floor を除く)
  さらに、同じ答えを3割以上繰り返した参加者(でたらめ回答の疑い)を除く(--keep-all で除かない)。

打ち切りの長さの区分
  全体          本命試行のすべて(打ち切りなしを含む)
  短い打ち切り  gate_ms が 10〜40 ms
  長い打ち切り  gate_ms が 45〜150 ms
  打ち切りなし  音の全長(250〜451 ms)を聞かせた試行(stimulus_id の末尾が full、gate_ms は空)
  重点8字以外の音は、1音あたり 7 つの打ち切り点(10〜150 ms)を持ち、その中央値は 40 ms なので、
  40 ms を境にして短い側と長い側に分けた。

出力(--out で指定したフォルダ)
  confusion_44.csv           上毛かるたの先頭音44音の混同行列(全体。行=目標、列=回答44音+「他」、試行数つき)
  confusion_44_<区分>.csv    同じものを区分ごとに(short / long / full)
  confusion_68_<区分>.csv    67 目標音 × 68 回答音の混同行列(all / short / long / full)
  top_confusions.csv         目標音ごとの「最も多い誤答先」とその割合(区分 × 範囲(68音/44音))
  hoko_rates.csv             ほ→こ・こ→ほ の割合(区分ごと、試行数と Wilson の 95% 区間、順位。
                             rank_all_pairs_* は目標≠回答の全組(観測された組)の中での順位、
                             n_targets_above_in_top_list_* は「最も多い誤答先」の一覧でこの割合を上回る目標音の数)
  pair_rates_<区分>.csv      目標≠回答のすべての組の割合(順位の根拠)
  fig_confusion_44.png       44音の混同行列の図(平方根の色階調。ほ・こ に印)
  summary.json               README に書く数値

使い方
  python3.11 analyze_confusion.py             # 既定(でたらめ回答の疑いのある参加者を除く)
  python3.11 analyze_confusion.py --keep-all  # 参加者を除かない(感度分析)
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IN = os.path.join(
    os.path.dirname(HERE), "wiss2026", "引き継ぎ_20260911", "展開済み", "data", "raw",
    "calib2_視覚_2回目", "transfer_trials.csv")

JOMO44 = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわ")
KANA68 = list("あいうえおかがきぎくぐけげこごさざしじすずせぜそぞただちつてでとどなにぬねのはばぱひびぴ"
              "ふぶぷへべぺほぼぽまみむめもやゆよらりるれろわん")
assert len(KANA68) == 68 and len(JOMO44) == 44
SAME_RESPONSE_CUT = 0.30     # 同じ答えがこの割合以上の参加者を除く
SHORT_MAX_MS = 40            # 短い打ち切り: gate_ms <= 40

BINS = [("all", "全体"), ("short", "短い打ち切り(10〜40 ms)"),
        ("long", "長い打ち切り(45〜150 ms)"), ("full", "打ち切りなし(全長)")]


# ---------------------------------------------------------------------------
# 1. データの読み込みと本命試行の取り出し
# ---------------------------------------------------------------------------
def load_main_trials(path, keep_all=False):
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False, dtype=str)
    n0 = len(df)
    df = df[df["is_test"].fillna("").str.upper() != "TRUE"]
    a = df[(df["group"] == "acal") & (df["modality"] == "transfer_audio")].copy()
    n_part_all = a["participant_id"].nunique()

    same = a.groupby("participant_id")["response_char"].agg(
        lambda s: s.value_counts().iloc[0] / len(s))
    bad = sorted(same[same >= SAME_RESPONSE_CUT].index.tolist())
    if not keep_all:
        a = a[~a["participant_id"].isin(bad)]

    main = a[a["check_kind"].isna() | (a["check_kind"].str.strip() == "")].copy()
    main["stim_tail"] = main["stimulus_id"].str.split("|").str[-1]
    main["gate_ms"] = pd.to_numeric(main["gate_ms"], errors="coerce")
    main["is_full"] = main["gate_ms"].isna() & (main["stim_tail"] == "full")
    main = main[main["is_full"] | main["gate_ms"].notna()].copy()
    main["bin"] = np.where(main["is_full"], "full",
                           np.where(main["gate_ms"] <= SHORT_MAX_MS, "short", "long"))
    main["ok"] = main["target_char"] == main["response_char"]
    assert set(main["target_char"]) <= set(KANA68) and set(main["response_char"]) <= set(KANA68)
    info = dict(n_rows_file=n0, n_participants_audio=int(n_part_all),
                excluded_participants=([] if keep_all else bad),
                n_participants_used=int(main["participant_id"].nunique()),
                n_main_trials=int(len(main)),
                n_by_bin={b: int((main["bin"] == b).sum()) for b, _ in BINS[1:]},
                n_targets=int(main["target_char"].nunique()),
                targets_missing=sorted(set(KANA68) - set(main["target_char"])),
                short_max_ms=SHORT_MAX_MS)
    return main, info


def subset(main, b):
    return main if b == "all" else main[main["bin"] == b]


# ---------------------------------------------------------------------------
# 2. 混同行列
# ---------------------------------------------------------------------------
def confusion(sub, rows, cols, other_col):
    """行=目標、列=回答の件数表。cols に含まれない回答は other_col 列にまとめる。"""
    ct = pd.crosstab(sub["target_char"], sub["response_char"])
    ct = ct.reindex(index=rows, columns=sorted(set(ct.columns) | set(cols)), fill_value=0)
    out = ct[cols].copy()
    extra = [c for c in ct.columns if c not in cols]
    if other_col is not None:
        out[other_col] = ct[extra].sum(axis=1) if extra else 0
    out["n"] = ct.sum(axis=1)
    out.index.name = "target"
    return out


# ---------------------------------------------------------------------------
# 3. 割合と区間
# ---------------------------------------------------------------------------
def wilson(k, n, z=1.959964):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def pair_rates(sub):
    """目標 ≠ 回答のすべての組の割合(目標ごとの試行数で割る)。"""
    ct = pd.crosstab(sub["target_char"], sub["response_char"])
    n = ct.sum(axis=1)
    rows = []
    for t in ct.index:
        for r in ct.columns:
            if t == r or ct.loc[t, r] == 0:
                continue
            k = int(ct.loc[t, r])
            lo, hi = wilson(k, int(n[t]))
            rows.append(dict(target=t, response=r, k=k, n=int(n[t]), rate=k / n[t],
                             ci_lo=lo, ci_hi=hi))
    df = pd.DataFrame(rows).sort_values(["rate", "k"], ascending=False).reset_index(drop=True)
    df["rank"] = df["rate"].rank(method="min", ascending=False).astype(int)
    return df


def top_confusions(sub, scope_chars):
    """目標音ごとに、最も多い誤答先とその割合。"""
    ct = pd.crosstab(sub["target_char"], sub["response_char"])
    rows = []
    for t in ct.index:
        if t not in scope_chars:
            continue
        row = ct.loc[t]
        n = int(row.sum())
        k_ok = int(row.get(t, 0))
        wrong = row.drop(labels=[t], errors="ignore")
        wrong = wrong[wrong > 0]
        if len(wrong) == 0:
            rows.append(dict(target=t, n=n, n_correct=k_ok, acc=k_ok / n, top_wrong="",
                             k_top=0, rate_top=0.0, rate_top_of_errors=np.nan,
                             ci_lo=0.0, ci_hi=wilson(0, n)[1], n_wrong=0))
            continue
        kmax = int(wrong.max())
        ties = sorted(wrong[wrong == kmax].index.tolist())
        lo, hi = wilson(kmax, n)
        rows.append(dict(target=t, n=n, n_correct=k_ok, acc=k_ok / n, top_wrong="/".join(ties),
                         k_top=kmax, rate_top=kmax / n,
                         rate_top_of_errors=kmax / (n - k_ok) if n > k_ok else np.nan,
                         ci_lo=lo, ci_hi=hi, n_wrong=int(n - k_ok)))
    df = pd.DataFrame(rows).sort_values(["rate_top", "k_top"], ascending=False).reset_index(drop=True)
    df["rank"] = df["rate_top"].rank(method="min", ascending=False).astype(int)
    df["n_in_scope"] = len(df)
    return df


def hoko_row(sub, t, r):
    ct = pd.crosstab(sub["target_char"], sub["response_char"])
    n = int(ct.loc[t].sum()) if t in ct.index else 0
    k = int(ct.loc[t, r]) if (t in ct.index and r in ct.columns) else 0
    lo, hi = wilson(k, n)
    return dict(k=k, n=n, rate=(k / n if n else np.nan), ci_lo=lo, ci_hi=hi)


# ---------------------------------------------------------------------------
# 4. 図
# ---------------------------------------------------------------------------
def draw_matrix(ct44, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Rectangle
    for cand in ["Hiragino Sans", "Hiragino Kaku Gothic Pro", "Hiragino Maru Gothic ProN",
                 "Noto Sans CJK JP", "IPAexGothic"]:
        if any(f.name == cand for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams["axes.unicode_minus"] = False

    cols = JOMO44 + ["他"]
    counts = ct44[cols].to_numpy(dtype=float)
    n = ct44["n"].to_numpy(dtype=float)
    prop = counts / n[:, None]
    fig, ax = plt.subplots(figsize=(11.5, 10.5))
    im = ax.imshow(np.sqrt(prop), cmap="Blues", vmin=0, vmax=1, aspect="equal")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols, fontsize=10)
    ax.set_yticks(range(len(JOMO44)))
    ax.set_yticklabels([f"{c} ({int(k)})" for c, k in zip(JOMO44, n)], fontsize=9)
    ax.set_xlabel("回答した音(「他」は44音以外の回答の合計)", fontsize=11)
    ax.set_ylabel("目標の音(括弧内は試行数)", fontsize=11)
    ax.xaxis.set_ticks_position("top")
    ax.xaxis.set_label_position("top")
    ax.tick_params(length=0)
    for i in range(len(JOMO44)):
        for j in range(len(cols)):
            k = int(counts[i, j])
            if k > 0 and i != j:
                ax.text(j, i, str(k), ha="center", va="center", fontsize=6.2,
                        color="white" if prop[i, j] > 0.3 else "#222222")
    # ほ・こ の印
    ih, ik = JOMO44.index("ほ"), JOMO44.index("こ")
    for (i, j) in [(ih, ik), (ik, ih)]:
        ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, edgecolor="#d62728", lw=2.2))
    for (i, j) in [(ih, ih), (ik, ik)]:
        ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, edgecolor="#d62728",
                               lw=1.2, ls="--"))
    for lab in ax.get_yticklabels():
        if lab.get_text().startswith(("ほ ", "こ ")):
            lab.set_color("#d62728"); lab.set_fontweight("bold")
    for lab in ax.get_xticklabels():
        if lab.get_text() in ("ほ", "こ"):
            lab.set_color("#d62728"); lab.set_fontweight("bold")
    ax.text(ik + 0.6, ih, f"ほ→こ {int(counts[ih, ik])}/{int(n[ih])}", color="#d62728",
            fontsize=8.5, va="center", ha="left", fontweight="bold")
    ax.text(ih + 0.6, ik, f"こ→ほ {int(counts[ik, ih])}/{int(n[ik])}", color="#d62728",
            fontsize=8.5, va="center", ha="left", fontweight="bold")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, ticks=np.sqrt([0, 0.01, 0.05, 0.1, 0.25, 0.5, 1]))
    cb.ax.set_yticklabels(["0", "1%", "5%", "10%", "25%", "50%", "100%"])
    cb.set_label("目標の音の試行のうち、その音と答えた割合(色は平方根の階調)", fontsize=10)
    ax.set_title(title, fontsize=12, pad=14)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 5. 主処理
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=DEFAULT_IN)
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--keep-all", action="store_true", help="でたらめ回答の疑いのある参加者を除かない(感度分析)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    main_df, info = load_main_trials(args.inp, keep_all=args.keep_all)
    print("入力:", json.dumps(info, ensure_ascii=False))

    targets68 = [c for c in KANA68 if c in set(main_df["target_char"])]
    summary = dict(input=info, bins={})
    tops = []
    for b, label in BINS:
        sub = subset(main_df, b)
        # 混同行列
        c44 = confusion(sub, JOMO44, JOMO44, "他")
        c44.to_csv(os.path.join(args.out, "confusion_44.csv" if b == "all" else f"confusion_44_{b}.csv"),
                   encoding="utf-8-sig")
        c68 = confusion(sub, targets68, KANA68, None)
        c68.to_csv(os.path.join(args.out, f"confusion_68_{b}.csv"), encoding="utf-8-sig")
        # 組ごとの割合
        pr = pair_rates(sub)
        pr.to_csv(os.path.join(args.out, f"pair_rates_{b}.csv"), index=False, encoding="utf-8-sig")
        pr44 = pr[pr["target"].isin(JOMO44) & pr["response"].isin(JOMO44)].copy()
        pr44["rank"] = pr44["rate"].rank(method="min", ascending=False).astype(int)
        # 最も多い誤答先
        t68 = top_confusions(sub, set(targets68)); t68.insert(0, "scope", "68音"); t68.insert(0, "bin", b)
        t44 = top_confusions(sub, set(JOMO44)); t44.insert(0, "scope", "44音"); t44.insert(0, "bin", b)
        tops += [t68, t44]
        # ほ→こ・こ→ほ
        hk = hoko_row(sub, "ほ", "こ"); kh = hoko_row(sub, "こ", "ほ")
        tbl = np.array([[hk["k"], hk["n"] - hk["k"]], [kh["k"], kh["n"] - kh["k"]]])
        p_sym = float(fisher_exact(tbl)[1]) if hk["n"] and kh["n"] else np.nan

        def rank_of(df, t, r):
            m = df[(df["target"] == t) & (df["response"] == r)]
            return (int(m["rank"].iloc[0]) if len(m) else None, int(len(df)))

        def rank_in_tops(df, rate):
            # 「最も多い誤答先」の一覧の中で、この割合を上回る目標音が何音あるか(= 何位相当か − 1)
            return int((df["rate_top"] > rate).sum()), int(len(df))

        entry = dict(label=label, n_trials=int(len(sub)),
                     ho_to_ko=hk, ko_to_ho=kh, fisher_p_symmetry=p_sym,
                     ho_top=t68[t68["target"] == "ほ"].iloc[0][["top_wrong", "k_top", "n", "rate_top", "n_correct"]].to_dict(),
                     ko_top=t68[t68["target"] == "こ"].iloc[0][["top_wrong", "k_top", "n", "rate_top", "n_correct"]].to_dict(),
                     rank_pair68=dict(ho_to_ko=rank_of(pr, "ほ", "こ"), ko_to_ho=rank_of(pr, "こ", "ほ")),
                     rank_pair44=dict(ho_to_ko=rank_of(pr44, "ほ", "こ"), ko_to_ho=rank_of(pr44, "こ", "ほ")),
                     rank_in_tops68=dict(ho_to_ko=rank_in_tops(t68, hk["rate"]), ko_to_ho=rank_in_tops(t68, kh["rate"])),
                     rank_in_tops44=dict(ho_to_ko=rank_in_tops(t44, hk["rate"]), ko_to_ho=rank_in_tops(t44, kh["rate"])),
                     median_top_rate68=float(t68["rate_top"].median()),
                     median_top_rate44=float(t44["rate_top"].median()),
                     # 「ほ」の回答の内訳、「こ」の回答の内訳(上位)
                     ho_responses=c68.loc["ほ"].drop("n").sort_values(ascending=False).head(8).to_dict() if "ほ" in c68.index else {},
                     ko_responses=c68.loc["こ"].drop("n").sort_values(ascending=False).head(8).to_dict() if "こ" in c68.index else {})
        summary["bins"][b] = entry
        print(f"[{label}] ほ→こ {hk['k']}/{hk['n']} = {hk['rate']:.3f} [{hk['ci_lo']:.3f}, {hk['ci_hi']:.3f}]"
              f"  こ→ほ {kh['k']}/{kh['n']} = {kh['rate']:.3f} [{kh['ci_lo']:.3f}, {kh['ci_hi']:.3f}]"
              f"  Fisher p={p_sym:.3f}")
        print(f"   順位(68音の全組) ほ→こ {entry['rank_pair68']['ho_to_ko']}, こ→ほ {entry['rank_pair68']['ko_to_ho']};"
              f" 一覧内 ほ→こ {entry['rank_in_tops68']['ho_to_ko']}, こ→ほ {entry['rank_in_tops68']['ko_to_ho']}")
        print(f"   ほ の最多誤答 {entry['ho_top']}  こ の最多誤答 {entry['ko_top']}")

    pd.concat(tops, ignore_index=True).to_csv(os.path.join(args.out, "top_confusions.csv"),
                                              index=False, encoding="utf-8-sig")

    # ほ→こ・こ→ほ の表
    rows = []
    for b, label in BINS:
        e = summary["bins"][b]
        for d, key in [("ほ→こ", "ho_to_ko"), ("こ→ほ", "ko_to_ho")]:
            r = e[key]
            rows.append(dict(bin=b, label=label, direction=d, k=r["k"], n=r["n"], rate=r["rate"],
                             ci_lo=r["ci_lo"], ci_hi=r["ci_hi"],
                             rank_all_pairs_68=e["rank_pair68"][key][0], n_pairs_68=e["rank_pair68"][key][1],
                             rank_all_pairs_44=e["rank_pair44"][key][0], n_pairs_44=e["rank_pair44"][key][1],
                             n_targets_above_in_top_list_68=e["rank_in_tops68"][key][0], n_targets_68=e["rank_in_tops68"][key][1],
                             n_targets_above_in_top_list_44=e["rank_in_tops44"][key][0], n_targets_44=e["rank_in_tops44"][key][1],
                             fisher_p_symmetry=e["fisher_p_symmetry"]))
    pd.DataFrame(rows).to_csv(os.path.join(args.out, "hoko_rates.csv"), index=False, encoding="utf-8-sig")

    # 図(全体)
    c44_all = confusion(subset(main_df, "all"), JOMO44, JOMO44, "他")
    draw_matrix(c44_all, os.path.join(args.out, "fig_confusion_44.png"),
                f"上毛かるた先頭音44音の混同行列(聴覚、本命試行 全体、{info['n_participants_used']}名)")

    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("出力先:", args.out)


if __name__ == "__main__":
    main()
