#!/usr/bin/env python3
# 文字モーフィング試作: 符号付き距離場(SDF)の補間で C1→C2 を滑らかに変形する。
# 対応点をとらない陰的モーフィングなので、任意のかな対に使える。
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt

REPO = "/Users/kurihara/Desktop/claude_work/iFont"
OUT = "/Users/kurihara/Library/CloudStorage/GoogleDrive-qurihara@gmail.com/マイドライブ/share/google_desktop_share"
SIZE = 200

def sdf(ch):
    im = np.asarray(Image.open(f"{REPO}/experiment/base/{ch}.png").convert("L").resize((SIZE, SIZE))).astype(float)
    ink = im < 128
    d_out = distance_transform_edt(~ink)   # インクの外側は正
    d_in = distance_transform_edt(ink)     # インクの内側は負
    return d_out - d_in

def render(s, soft=1.4):
    # 符号付き距離を、境界をなめらかにした被覆率(0..1)にする
    cov = np.clip(0.5 - s / soft, 0.0, 1.0)   # s<=0(内側)で1、s>0(外側)で0
    return (255 * (1 - cov)).astype("uint8")

def morph(s1, s2, t):
    return render((1 - t) * s1 + t * s2)

# クロスディゾルブ(単純な重ね合わせ)との比較用
def dissolve(ch1, ch2, t):
    a = np.asarray(Image.open(f"{REPO}/experiment/base/{ch1}.png").convert("L").resize((SIZE, SIZE))).astype(float)
    b = np.asarray(Image.open(f"{REPO}/experiment/base/{ch2}.png").convert("L").resize((SIZE, SIZE))).astype(float)
    return ((1 - t) * a + t * b).astype("uint8")

pairs = [("や", "ま"), ("し", "の"), ("あ", "き"), ("こ", "を")]
ts = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]

# フォント(ラベル用)
FP = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
f_lab = ImageFont.truetype(FP, 24); f_hd = ImageFont.truetype(FP, 20)

cell = SIZE; pad = 10; labw = 150; headh = 40
W = labw + len(ts) * (cell + pad) + pad
H = headh + len(pairs) * (cell + pad) + pad
canvas = Image.new("RGB", (W, H), "white"); dr = ImageDraw.Draw(canvas)
for j, t in enumerate(ts):
    x = labw + pad + j * (cell + pad)
    dr.text((x + cell/2 - 22, 10), f"t={t:.1f}", fill="#22283C", font=f_hd)
for i, (c1, c2) in enumerate(pairs):
    s1, s2 = sdf(c1), sdf(c2)
    y = headh + pad + i * (cell + pad)
    dr.text((14, y + cell/2 - 14), f"{c1} → {c2}", fill="#1E2A5E", font=f_lab)
    for j, t in enumerate(ts):
        im = Image.fromarray(morph(s1, s2, t)).convert("RGB")
        x = labw + pad + j * (cell + pad)
        canvas.paste(im, (x, y))
        dr.rectangle([x, y, x + cell - 1, y + cell - 1], outline="#D8DAE4")
canvas.save(f"{OUT}/文字モーフィング_SDF補間デモ.png")
print("saved morph strip")

# 比較: SDF補間 vs 単純クロスディゾルブ(や→ま)
canvas2 = Image.new("RGB", (W, headh + 2 * (cell + pad) + pad), "white"); dr2 = ImageDraw.Draw(canvas2)
for j, t in enumerate(ts):
    x = labw + pad + j * (cell + pad); dr2.text((x + cell/2 - 22, 10), f"t={t:.1f}", fill="#22283C", font=f_hd)
s1, s2 = sdf("や"), sdf("ま")
for i, (label, fn) in enumerate([("SDF補間", lambda t: morph(s1, s2, t)), ("単純重ね(比較)", lambda t: dissolve("や", "ま", t))]):
    y = headh + pad + i * (cell + pad); dr2.text((14, y + cell/2 - 14), label, fill="#1E2A5E", font=f_lab)
    for j, t in enumerate(ts):
        im = Image.fromarray(fn(t)).convert("RGB"); x = labw + pad + j * (cell + pad)
        canvas2.paste(im, (x, y)); dr2.rectangle([x, y, x + cell - 1, y + cell - 1], outline="#D8DAE4")
canvas2.save(f"{OUT}/文字モーフィング_SDF補間_対_単純重ね.png")
print("saved comparison strip")
