#!/usr/bin/env python3
# メッシュ(ワープ)モーフィング = 古典的な画像モーフィング。
# 1) 両字の対応点を最適輸送で作る 2) それを制御点に薄板スプライン(TPS)でメッシュを滑らかにワープ
# 3) 両字を中間形へ変形してクロスディゾルブ。メッシュが変形しながら移動する。
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import ot
from scipy.interpolate import RBFInterpolator
from scipy.ndimage import map_coordinates

REPO = "/Users/kurihara/Desktop/claude_work/iFont"
OUT = "/Users/kurihara/Library/CloudStorage/GoogleDrive-qurihara@gmail.com/マイドライブ/share/google_desktop_share"
SIZE = 200

def load(ch):
    return np.asarray(Image.open(f"{REPO}/experiment/base/{ch}.png").convert("L").resize((SIZE, SIZE))).astype(float)

def ink_pts(im, n, seed):
    ys, xs = np.where(im < 128)
    pts = np.stack([xs, ys], 1).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(pts), n, replace=len(pts) < n)
    return pts[idx]

def correspondence(im1, im2, n=500, k=70):
    """最適輸送で対応をつくり、TPS 制御点を k 個に間引く。周囲に固定アンカーを足す。"""
    X = ink_pts(im1, n, 1); Y = ink_pts(im2, n, 2)
    M = ot.dist(X, Y, metric="sqeuclidean"); M /= M.max()
    G = ot.emd(np.full(n, 1/n), np.full(n, 1/n), M)
    Yhat = (G @ Y) * n
    sel = np.random.default_rng(0).choice(n, k, replace=False)
    src = X[sel]; dst = Yhat[sel]
    # 四隅と辺の中点を、動かない制御点として足す(境界を安定させる)
    a = np.array([[0,0],[SIZE-1,0],[0,SIZE-1],[SIZE-1,SIZE-1],
                  [SIZE//2,0],[SIZE//2,SIZE-1],[0,SIZE//2],[SIZE-1,SIZE//2]], float)
    src = np.vstack([src, a]); dst = np.vstack([dst, a])
    return src, dst

# 出力画素の座標(x,y)
gx, gy = np.meshgrid(np.arange(SIZE), np.arange(SIZE))
Q = np.stack([gx.ravel(), gy.ravel()], 1).astype(float)

def warp(img, from_pts, to_pts):
    """出力の各画素が img のどこから来たかを TPS(from→to の逆:to→from)で引いて標本化する。"""
    tps = RBFInterpolator(to_pts, from_pts, kernel="thin_plate_spline", smoothing=1.0)
    srcQ = tps(Q)                       # 中間画素 → img 側の座標(x,y)
    coords = np.stack([srcQ[:,1].reshape(SIZE,SIZE), srcQ[:,0].reshape(SIZE,SIZE)])  # (y,x)
    return map_coordinates(img, coords, order=1, mode="constant", cval=255.0)

def morph_frame(im1, im2, src, dst, t):
    Pt = (1-t)*src + t*dst               # 中間形の制御点
    w1 = warp(im1, src, Pt)              # C1 を中間形へ
    w2 = warp(im2, dst, Pt)              # C2 を中間形へ
    return ((1-t)*w1 + t*w2).clip(0,255).astype("uint8")

def mesh_overlay(im_frame, src, dst, t, step=20):
    """変形するメッシュ(正方格子)を重ねて描く。格子は src→dst のワープを t で補間して動く。"""
    tps = RBFInterpolator(src, dst, kernel="thin_plate_spline", smoothing=1.0)
    xs = np.arange(0, SIZE+1, step)
    P = np.array([[x, y] for y in xs for x in xs], float)
    Pw = (1-t)*P + t*tps(P)              # 各格子点の t 時点の位置
    n = len(xs)
    img = Image.fromarray(im_frame).convert("RGB"); dr = ImageDraw.Draw(img)
    def pt(i, j): return tuple(Pw[i*n+j])
    for i in range(n):
        for j in range(n):
            if j+1 < n: dr.line([pt(i,j), pt(i,j+1)], fill=(46,125,143), width=1)
            if i+1 < n: dr.line([pt(i,j), pt(i+1,j)], fill=(46,125,143), width=1)
    return np.asarray(img)

FP = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
f_lab = ImageFont.truetype(FP, 22); f_hd = ImageFont.truetype(FP, 20)
def strip(rows, ts, fname, titles):
    cell=SIZE; pad=10; labw=170; headh=40
    W=labw+len(ts)*(cell+pad)+pad; H=headh+len(rows)*(cell+pad)+pad
    cv=Image.new("RGB",(W,H),"white"); dr=ImageDraw.Draw(cv)
    for j,t in enumerate(ts): dr.text((labw+pad+j*(cell+pad)+cell/2-22,10),f"t={t:.1f}",fill="#22283C",font=f_hd)
    for i,frames in enumerate(rows):
        y=headh+pad+i*(cell+pad); dr.text((12,y+cell/2-12),titles[i],fill="#1E2A5E",font=f_lab)
        for j,im in enumerate(frames):
            x=labw+pad+j*(cell+pad); cv.paste(Image.fromarray(im).convert("RGB"),(x,y)); dr.rectangle([x,y,x+cell-1,y+cell-1],outline="#D8DAE4")
    cv.save(f"{OUT}/{fname}"); print("saved",fname)

ts=[0.0,0.2,0.4,0.6,0.8,1.0]
pairs=[("や","ま"),("し","の"),("あ","き"),("こ","を")]
rows=[]; titles=[]
for c1,c2 in pairs:
    im1,im2=load(c1),load(c2); src,dst=correspondence(im1,im2)
    rows.append([morph_frame(im1,im2,src,dst,t) for t in ts]); titles.append(f"{c1} → {c2}")
strip(rows,ts,"文字モーフィング_メッシュTPS.png",titles)

# メッシュ可視化(や→ま)
im1,im2=load("や"),load("ま"); src,dst=correspondence(im1,im2)
mrow=[mesh_overlay(morph_frame(im1,im2,src,dst,t),src,dst,t) for t in ts]
strip([mrow],ts,"文字モーフィング_メッシュ可視化.png",["メッシュが変形しながら移動"])
