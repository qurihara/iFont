#!/usr/bin/env python3
"""
1文字 対 2文字の音響比較 — 共調音が弁別に効くかの網羅解析
============================================================
問い: 2文字課題をやる根拠は「前の文字の発音で次の文字の発音が変わり(共調音)、
弁別可能性に影響する」こと。全 72×72 の2文字音声がある今、2文字目(C2)が
単体の1文字にくらべてどれだけ音響的に違うかを網羅的に測り、
「1文字課題だけで足りるか」「2文字課題が必須か」を文字ごとに検証する。

音高の交絡への対処: 実験の1文字は B3、2文字目は E4 と音高が違う。そこで
分析用に E4 の1文字プールも作った。主分析は E4 どうしで比べ、音高差の交絡を消す。
特徴量は MFCC(13次)とその差分(13次)の、区間平均をつないだ26次元。全トークンで
標準化する。

データ:
  2文字の C2 区間  : experiment/audio2char_stimuli/ + audio2char_manifest.json(タイミング)
                     + answer_key_2char.json(c1,c2)
  1文字 E4        : acoustic_analysis/audio1char_E4_stimuli/ + _manifest + answer_key_1char_E4
  1文字 B3(実験用): experiment/audio1char_stimuli/ + audio1char_manifest + answer_key_1char

実行(librosa入りの venv): bigram_coverage/.venv/bin/python acoustic_analysis/analyze_coarticulation.py
"""
import json, os, sys, subprocess, collections, pickle
import numpy as np
import librosa
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EXP = os.path.join(REPO, "experiment")
SR = 22050


def decode(path):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le",
                        "-ac", "1", "-ar", str(SR), "pipe:1"],
                       stdout=subprocess.PIPE, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32).astype(np.float64)


def feature(task):
    """task=(path, onset_s, dur_s, key)。区間の MFCC 平均+差分平均(26次)を返す。"""
    path, onset, dur, key = task
    y = decode(path)
    a = int(onset * SR); b = min(len(y), int((onset + dur) * SR))
    seg = y[a:b]
    if len(seg) < 256:
        return key, None
    m = librosa.feature.mfcc(y=seg, sr=SR, n_mfcc=13, n_fft=512, hop_length=128)
    d = librosa.feature.delta(m)
    return key, np.concatenate([m.mean(axis=1), d.mean(axis=1)])


def load_1char(manifest_path, ak_path, stim_dir):
    man = {s["id"]: s for s in json.load(open(manifest_path))["stimuli"]}
    ak = json.load(open(ak_path))
    tasks = []
    for k, v in ak.items():
        sid = k.split("|")[1]
        s = man[sid]
        tasks.append((os.path.join(stim_dir, s["file"]),
                      s["char_onset_s"], s["char_dur_s"], v["char"]))
    return tasks


def load_2char():
    man = {s["id"]: s for s in json.load(open(os.path.join(EXP, "audio2char_manifest.json")))["stimuli"]}
    ak = json.load(open(os.path.join(EXP, "answer_key_2char.json")))
    tasks = []
    for k, v in ak.items():
        sid = k.split("|")[1]
        s = man[sid]
        tasks.append((os.path.join(EXP, "audio2char_stimuli", s["file"]),
                      s["c2_onset_s"], s["c2_dur_s"], (v["c1"], v["c2"])))
    return tasks


def extract(tasks):
    with Pool() as pool:
        out = pool.map(feature, tasks, chunksize=16)
    return [(k, v) for k, v in out if v is not None]


# ---- 音素カテゴリ(頭子音でざっくり分類。推薦の集計用) ----
CATEGORY = {}
for cs, name in [("あいうえお", "母音"), ("かきくけこ", "無声破裂 k"), ("たてと", "無声破裂 t"),
                 ("ぱぴぷぺぽ", "無声破裂 p"), ("さすせそ", "無声摩擦 s"), ("しちつ", "破擦・拗摩擦"),
                 ("はひふへほ", "無声摩擦 h"), ("がぎぐげご", "有声破裂 g"),
                 ("だでど", "有声破裂 d"), ("ばびぶべぼ", "有声破裂 b"),
                 ("ざじずぜぞづぢ", "有声摩擦・破擦 z"), ("なにぬねの", "鼻音 n"),
                 ("まみむめも", "鼻音 m"), ("らりるれろ", "流音 r"), ("やゆよ", "半母音 y"),
                 ("わ", "半母音 w"), ("ん", "撥音 N"), ("ゔ", "有声摩擦 v")]:
    for c in cs:
        CATEGORY[c] = name


def zscore(mat, mu, sd):
    return (mat - mu) / sd


def main():
    cache = os.path.join(HERE, "features.pkl")
    if os.path.exists(cache):
        print("特徴量をキャッシュから読み込み...", file=sys.stderr)
        two, e4, b3 = pickle.load(open(cache, "rb"))
    else:
        print("特徴量を抽出中(2文字5184 + 1文字E4/B3 各72)...", file=sys.stderr)
        two = extract(load_2char())
        e4 = extract(load_1char(os.path.join(HERE, "audio1char_E4_manifest.json"),
                                os.path.join(HERE, "answer_key_1char_E4.json"),
                                os.path.join(HERE, "audio1char_E4_stimuli")))
        b3 = extract(load_1char(os.path.join(EXP, "audio1char_manifest.json"),
                                os.path.join(EXP, "answer_key_1char.json"),
                                os.path.join(EXP, "audio1char_stimuli")))
        pickle.dump((two, e4, b3), open(cache, "wb"))
    print(f"  2文字 {len(two)} / E4 {len(e4)} / B3 {len(b3)}", file=sys.stderr)

    # 標準化は2文字トークン分布で決める
    X2 = np.array([v for _, v in two])
    mu, sd = X2.mean(0), X2.std(0) + 1e-9
    two_feat = {k: zscore(v, mu, sd) for k, v in two}
    e4_feat = {k: zscore(v, mu, sd) for k, v in e4}
    b3_feat = {k: zscore(v, mu, sd) for k, v in b3}

    chars = sorted(e4_feat.keys(), key="あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽゔ".find)

    # c2 ごとに、72文脈の C2 特徴を集める
    byc2 = collections.defaultdict(list)
    for (c1, c2), v in two_feat.items():
        byc2[c2].append(v)
    cent2 = {c: np.mean(byc2[c], axis=0) for c in byc2}          # 文脈平均(2文字由来の重心)

    def classify(v, centroids, keys):
        dd = [np.linalg.norm(v - centroids[k]) for k in keys]
        return keys[int(np.argmin(dd))]

    # ---- 文字間の距離と、同音異字(距離ほぼ0の別文字)の検出 ----
    cats = list(cent2.keys())
    C = np.array([cent2[c] for c in cats])
    D = np.linalg.norm(C[:, None, :] - C[None, :, :], axis=2)
    np.fill_diagonal(D, np.inf)
    nn_between = {c: float(D[i].min()) for i, c in enumerate(cats)}
    nn_char = {c: cats[int(np.argmin(D[i]))] for i, c in enumerate(cats)}
    mean_between = float(D[np.isfinite(D)].mean())
    HOMO = 0.8   # これ未満なら実質同音(を=お など)
    homophones = sorted({tuple(sorted((c, nn_char[c]))) for c in cats if nn_between[c] < HOMO})

    # ---- A. 共調音の大きさ: 文脈による C2 の広がり ----
    within = {c: float(np.mean([np.linalg.norm(v - cent2[c]) for v in byc2[c]])) for c in byc2}

    # ---- B. 文脈で自分らしさが壊れるか(2文字重心での最近傍分類。同音異字は除く) ----
    non_homo = [c for c in cats if nn_between[c] >= HOMO]
    selfacc_2c, confus = {}, collections.Counter()
    for c2 in byc2:
        hit = 0
        for v in byc2[c2]:
            pred = classify(v, cent2, cats)
            if pred == c2: hit += 1
            else: confus[(c2, pred)] += 1
        selfacc_2c[c2] = hit / len(byc2[c2])

    # ---- C. 単独発話(1文字) 対 語中発話(2文字目) の系統差を分解 ----
    # 各文字で「文脈平均(2文字重心) − 単体E4」を求め、全文字に共通の方向 g(単独→語中の
    # 系統的なずれ)と、文字ごとの残差に分ける。
    diff = {c: cent2[c] - e4_feat[c] for c in cent2 if c in e4_feat}
    g = np.mean(list(diff.values()), axis=0)              # 共通のずれ(単独→語中)
    global_shift = float(np.linalg.norm(g))
    resid = {c: float(np.linalg.norm(diff[c] - g)) for c in diff}  # 文字ごとの残差

    # C1. 単体E4をそのまま基準に、文脈つきC2を分類できるか(補正なし)
    e4acc_raw = collections.Counter(); tot = collections.Counter()
    for c2 in byc2:
        for v in byc2[c2]:
            tot[c2] += 1
            if classify(v, e4_feat, chars) == c2: e4acc_raw[c2] += 1
    e4_acc_raw = {c: e4acc_raw[c] / tot[c] for c in tot}

    # C2. 系統差 g を補正した単体E4を基準に、同じ分類(補正後に自分らしさが戻るか)
    e4g = {c: e4_feat[c] + g for c in e4_feat}
    e4acc_adj = collections.Counter()
    for c2 in byc2:
        for v in byc2[c2]:
            if classify(v, e4g, chars) == c2: e4acc_adj[c2] += 1
    e4_acc_adj = {c: e4acc_adj[c] / tot[c] for c in tot}

    # C3. B3 対 E4(同じ文字の音高差だけの距離。実験の1文字は B3 なので交絡が上乗せ)
    b3_vs_e4 = {c: float(np.linalg.norm(b3_feat[c] - e4_feat[c])) for c in e4_feat if c in b3_feat}

    def cat_agg(d):
        gg = collections.defaultdict(list)
        for c, val in d.items():
            if c in CATEGORY: gg[CATEGORY[c]].append(val)
        return {k: float(np.mean(v)) for k, v in gg.items()}

    result = dict(
        n=dict(two=len(two), e4=len(e4), b3=len(b3)),
        mean_between=mean_between, global_shift=global_shift,
        mean_within=float(np.mean(list(within.values()))),
        mean_resid=float(np.mean(list(resid.values()))),
        homophones=["".join(p) for p in homophones],
        overall_selfacc_2c=float(np.mean([selfacc_2c[c] for c in non_homo])),
        overall_e4_acc_raw=float(np.mean(list(e4_acc_raw.values()))),
        overall_e4_acc_adj=float(np.mean([e4_acc_adj[c] for c in non_homo])),
        per_char={c: dict(
            category=CATEGORY.get(c, "他"),
            within_spread=round(within[c], 2),
            nn_between=round(nn_between[c], 2), nn_char=nn_char[c],
            selfacc_2c=round(selfacc_2c[c], 3),
            e4_acc_raw=round(e4_acc_raw[c], 3),
            e4_acc_adj=round(e4_acc_adj[c], 3),
            resid=round(resid.get(c, float("nan")), 2),
            b3_vs_e4=round(b3_vs_e4.get(c, float("nan")), 2),
        ) for c in chars},
        by_category=dict(
            selfacc_2c=cat_agg(selfacc_2c),
            e4_acc_adj=cat_agg({c: e4_acc_adj[c] for c in tot}),
            within=cat_agg(within), resid=cat_agg(resid), b3_vs_e4=cat_agg(b3_vs_e4),
        ),
        top_confusions=[(f"{a}→{b}", n) for (a, b), n in confus.most_common(20)],
    )
    json.dump(result, open(os.path.join(HERE, "coarticulation_result.json"), "w"),
              ensure_ascii=False, indent=1)

    # ---- 表示 ----
    print(f"\n標準化空間での距離: 文字間の平均 {mean_between:.2f} / 文脈による広がり(共調音)の平均 {result['mean_within']:.2f}")
    print(f"単独発話→語中発話の系統的なずれ(全文字共通) {global_shift:.2f} / それを除いた文字ごとの残差の平均 {result['mean_resid']:.2f}")
    print(f"同音異字(音響的にほぼ同一): {result['homophones']}")
    print(f"\n[共調音] 文脈つきC2が自分の平均で正しく分類される率(同音異字を除く) {result['overall_selfacc_2c']*100:.1f}%")
    print(f"  → {100-result['overall_selfacc_2c']*100:.0f}% は、前の文字の影響で別の文字の側へ寄る")
    print(f"[1文字で足りるか] 単体E4をそのまま基準にした同定率 {result['overall_e4_acc_raw']*100:.1f}%")
    print(f"  系統差を補正した後の同定率 {result['overall_e4_acc_adj']*100:.1f}% (低いほど、単独発話は語中の発音を代表しない)")
    print("\nカテゴリ別(selfacc_2c 高=文脈に強い / e4_acc_adj 高=単独発話で代表できる):")
    bc = result["by_category"]
    order = sorted(bc["e4_acc_adj"], key=lambda k: bc["e4_acc_adj"][k])
    print(f"  {'カテゴリ':<16}{'共調音耐性':>10}{'補正後同定率':>12}{'文脈広がり':>10}{'B3対E4':>8}")
    for k in order:
        print(f"  {k:<16}{bc['selfacc_2c'].get(k,0)*100:>9.0f}%{bc['e4_acc_adj'][k]*100:>11.0f}%{bc['within'].get(k,0):>10.2f}{bc['b3_vs_e4'].get(k,0):>8.2f}")
    worst = sorted([(c, d) for c, d in result["per_char"].items() if d["nn_char"] and result["per_char"]],
                   key=lambda kv: kv[1]["selfacc_2c"])[:12]
    print("\n文脈で最も化けやすい文字(共調音の影響が強い) top12:")
    for c, d in worst:
        print(f"  {c}({d['category']}) 自分の平均で当たる率 {d['selfacc_2c']*100:.0f}% / 文脈広がり {d['within_spread']:.2f} / 最近の別文字 {d['nn_char']}({d['nn_between']:.2f})")
    print(f"\n結果: {os.path.join(HERE,'coarticulation_result.json')}")


if __name__ == "__main__":
    main()
