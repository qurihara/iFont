#!/usr/bin/env python3
# 特徴点対応モーフィング: 両字のインクを点群とみなし、最適輸送で対応づけて点を動かす。
# 各点が C1 の位置から C2 の対応位置へ移動する = ストロークが動く見た目。
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import ot
from scipy.ndimage import distance_transform_edt

REPO = "/Users/kurihara/Desktop/claude_work/iFont"
OUT = "/Users/kurihara/Library/CloudStorage/GoogleDrive-qurihara@gmail.com/マイドライブ/share/google_desktop_share"
SIZE = 200
N = 700          # 点の数

def ink_points(ch, n, seed):
    im = np.asarray(Image.open(f"{REPO}/experiment/base/{ch}.png").convert("L").resize((SIZE, SIZE))).astype(float)
    ys, xs = np.where(im < 128)
    pts = np.stack([xs, ys], 1).astype(float)
    rng = np.random.default_rng(seed)
    if len(pts) >= n:
        idx = rng.choice(len(pts), n, replace=False)
    else:
        idx = rng.choice(len(pts), n, replace=True)
    return pts[idx]

def ot_map(ch1, ch2):
    X = ink_points(ch1, N, 1); Y = ink_points(ch2, N, 2)
    a = np.full(N, 1.0/N); b = np.full(N, 1.0/N)
    M = ot.dist(X, Y, metric="sqeuclidean"); M /= M.max()
    G = ot.emd(a, b, M)                     # 最適輸送計画
    Yhat = (G @ Y) * N                      # 各源点のバリセントリック対応先
    return X, Yhat

def render_points(P, r=3.2):
    img = Image.new("L", (SIZE, SIZE), 255); dr = ImageDraw.Draw(img)
    for x, y in P:
        dr.ellipse([x-r, y-r, x+r, y+r], fill=0)
    return np.asarray(img)

# --- SDF 方式(比較用) ---
def sdf(ch):
    im = np.asarray(Image.open(f"{REPO}/experiment/base/{ch}.png").convert("L").resize((SIZE, SIZE))).astype(float)
    ink = im < 128
    return distance_transform_edt(~ink) - distance_transform_edt(ink)
def sdf_render(s1, s2, t, soft=1.4):
    s = (1-t)*s1 + t*s2
    cov = np.clip(0.5 - s/soft, 0, 1)
    return (255*(1-cov)).astype("uint8")

FP = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
f_lab = ImageFont.truetype(FP, 22); f_hd = ImageFont.truetype(FP, 20)

def strip(rows, ts, fname, title_rows):
    cell = SIZE; pad = 10; labw = 160; headh = 40
    W = labw + len(ts)*(cell+pad) + pad
    H = headh + len(rows)*(cell+pad) + pad
    cv = Image.new("RGB", (W, H), "white"); dr = ImageDraw.Draw(cv)
    for j, t in enumerate(ts):
        x = labw + pad + j*(cell+pad); dr.text((x+cell/2-22, 10), f"t={t:.1f}", fill="#22283C", font=f_hd)
    for i, frames in enumerate(rows):
        y = headh + pad + i*(cell+pad)
        dr.text((12, y+cell/2-12), title_rows[i], fill="#1E2A5E", font=f_lab)
        for j, im in enumerate(frames):
            x = labw + pad + j*(cell+pad)
            cv.paste(Image.fromarray(im).convert("RGB"), (x, y))
            dr.rectangle([x, y, x+cell-1, y+cell-1], outline="#D8DAE4")
    cv.save(f"{OUT}/{fname}"); print("saved", fname)

ts = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
pairs = [("や","ま"), ("し","の"), ("あ","き"), ("こ","を")]

# 特徴点対応(最適輸送)モーフィング
rows = []; titles = []
for c1, c2 in pairs:
    X, Yhat = ot_map(c1, c2)
    rows.append([render_points((1-t)*X + t*Yhat) for t in ts])
    titles.append(f"{c1} → {c2}")
strip(rows, ts, "文字モーフィング_特徴点対応OT.png", titles)

# SDF 対 OT の比較(や→ま)
X, Yhat = ot_map("や","ま"); s1, s2 = sdf("や"), sdf("ま")
strip([[sdf_render(s1,s2,t) for t in ts], [render_points((1-t)*X+t*Yhat) for t in ts]],
      ts, "文字モーフィング_SDF_対_特徴点対応.png", ["SDF(形が現れる)", "特徴点対応(点が動く)"])
