#!/usr/bin/env python3
"""
メッシュ(ワープ)モーフィング用の、対ごとのメッシュ頂点対応を事前計算する。
======================================================================
古典的な画像モーフィングをブラウザで実時間に動かすため、重い計算(最適輸送と
薄板スプライン)を先に済ませておく。ブラウザ側は、規則格子 G_A(恒等)と、ここで
計算する変形先 G_B を線形補間し、テクスチャを貼った三角形メッシュをワープして
2枚を重ねるだけでよい。

各対 (C1,C2) について:
  1. 両字のインクを点群にし、最適輸送で C1→C2 の対応(バリセントリック)を作る。
  2. その対応を制御点に薄板スプライン(TPS)を当て、周囲に固定アンカーを足す。
  3. M×M の規則格子(C1 側=恒等)を TPS でワープした先を G_B とする。

出力:
  experiment/morph_mesh.bin       G_B を uint8 でパック(順序 = c1_idx*78 + c2_idx)
  experiment/morph_mesh_manifest.json  {chars, grid(M), size, count}
実行: bigram_coverage/.venv/bin/python visual_morph/precompute_morph_mesh.py
"""
import json, os, sys
import numpy as np
from PIL import Image
import ot
from scipy.interpolate import RBFInterpolator

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
import ifont_common as ic

CHARS = list(ic.VISUAL_ALL)          # 78字
SIZE = 256
M = 10                               # メッシュは M×M 頂点
N = 400                              # 最適輸送に使う点の数
K = 60                               # TPS 制御点の数

BASE = os.path.join(REPO, "experiment", "base")
OUT_BIN = os.path.join(REPO, "experiment", "morph_mesh.bin")
OUT_MAN = os.path.join(REPO, "experiment", "morph_mesh_manifest.json")

# 規則格子(C1 側 = 恒等)。[0,SIZE] を M-1 分割
gx = np.linspace(0, SIZE - 1, M)
GRID = np.array([[x, y] for y in gx for x in gx], float)   # (M*M, 2), 順序は行優先

# 周囲の固定アンカー(境界を安定させる)
ANCH = np.array([[0, 0], [SIZE-1, 0], [0, SIZE-1], [SIZE-1, SIZE-1],
                 [SIZE//2, 0], [SIZE//2, SIZE-1], [0, SIZE//2], [SIZE-1, SIZE//2]], float)

def ink_pts(ch, n, seed):
    im = np.asarray(Image.open(os.path.join(BASE, ch + ".png")).convert("L").resize((SIZE, SIZE))).astype(float)
    ys, xs = np.where(im < 128)
    pts = np.stack([xs, ys], 1).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(pts), n, replace=len(pts) < n)
    return pts[idx]

# 各字のインク点をキャッシュ
pts_cache = {c: ink_pts(c, N, 1) for c in CHARS}
sel = np.random.default_rng(0).choice(N, K, replace=False)   # 制御点の間引き(全対で共通)

def warped_grid(c1, c2):
    if c1 == c2:
        return GRID.copy()
    X = pts_cache[c1]; Y = pts_cache[c2]
    Mx = ot.dist(X, Y, metric="sqeuclidean"); Mx /= Mx.max()
    G = ot.emd(np.full(N, 1/N), np.full(N, 1/N), Mx)
    Yhat = (G @ Y) * N                          # C1 の各点 → C2 側の対応先
    src = np.vstack([X[sel], ANCH]); dst = np.vstack([Yhat[sel], ANCH])
    tps = RBFInterpolator(src, dst, kernel="thin_plate_spline", smoothing=1.0)
    return tps(GRID)                            # 規則格子の変形先 G_B

def main():
    n_pairs = len(CHARS) ** 2
    buf = np.zeros((n_pairs, M * M, 2), dtype=np.uint8)
    for i, c1 in enumerate(CHARS):
        for j, c2 in enumerate(CHARS):
            gb = warped_grid(c1, c2)
            q = np.clip(np.round(gb * 255.0 / SIZE), 0, 255).astype(np.uint8)  # [0,SIZE]→uint8
            buf[i * len(CHARS) + j] = q
        print(f"  {i+1}/{len(CHARS)} ({c1}) 完了", file=sys.stderr, flush=True)
    buf.tofile(OUT_BIN)
    json.dump({"chars": CHARS, "grid": M, "size": SIZE, "count": n_pairs,
               "note": "G_B(uint8) per pair, order=c1_idx*78+c2_idx, coord=val*size/255"},
              open(OUT_MAN, "w"), ensure_ascii=False, indent=1)
    print(f"完了: {n_pairs} 対 -> {OUT_BIN} ({os.path.getsize(OUT_BIN)} bytes) / {OUT_MAN}", file=sys.stderr)

if __name__ == "__main__":
    main()
