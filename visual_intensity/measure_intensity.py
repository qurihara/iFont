#!/usr/bin/env python3
"""
視覚提示アルゴリズムの刺激の強さを定量化する
=============================================
視覚2文字/1文字課題の7つの提示アルゴリズム(fade/stroke/zoom/blur/moya/slideB/slideR)
について、目の疲労と安全性に効く要因を測る。1文字0.2秒・60fps(=13フレーム, u=i/12)で
各アルゴリズムを実際に描画し、次の3軸を計算する。

  1. grain  空間の高周波成分(細かく高コントラストな模様ほど大きい。ピント負担・ちらつき感)
            各フレームの勾配強度の平均。
  2. churn  フレーム間の輝度変化の量(毎フレームどれだけ画が入れ替わるか)。
            連続フレームの平均絶対差。動き系でもちらつき系でも大きくなる総合量。
  3. motion 動きの大きさ(px/フレーム)。位相相関でフレーム間の並進を推定。
            並進の一貫した動き(スライド)は大、乱雑な変化(stroke)は小。

churn は「動き」と「乱雑なちらつき」の両方で上がる。motion で並進成分を切り分けると、
churn が高く motion が低いもの = 位置は動かないのに画が乱れる = 乱雑なちらつき(stroke)、
churn が高く motion も高いもの = 一方向の動き(スライド)、と区別できる。

出力: visual_intensity/intensity_result.json と、標準出力の表。
文字は VISUAL 78字。base/<char>.png(256px, 白地に黒ストローク)から合成する。
実行: .venv/bin/python visual_intensity/measure_intensity.py
"""
import os, sys, json, math
import numpy as np
from PIL import Image, ImageFilter
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BASE = os.path.join(REPO, "experiment", "base")
SIZE = 256
NF = 13                         # 60fps × 0.2s ≈ 13 フレーム (u = i/12)
BLUR_MAX = 12                   # blur アルゴリズムの最大ぼかし半径
HP_SIGMA = 2                    # 高周波抽出のぼかし半径

CHARS = list(
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
    "がぎぐげござじずぜぞだぢづでどばびぶべぼ" "ぱぴぷぺぽ" "っゃゅょ" "ゐゑ" "ゔ"
)


def load_L(ch):
    im = Image.open(os.path.join(BASE, f"{ch}.png")).convert("L").resize((SIZE, SIZE))
    return np.asarray(im, dtype=np.float64)


def over(dst, src, alpha):
    """source-over 合成 (dst に src を不透明度 alpha で重ねる)。"""
    return src * alpha + dst * (1 - alpha)


def render(algo, L, u, overlay, stroke_order):
    white = np.full((SIZE, SIZE), 255.0)
    if algo == "fade":
        return 255 - u * (255 - L)
    if algo == "stroke":
        f = white.copy()
        k = int(len(stroke_order) * u)
        if k > 0:
            idx = stroke_order[:k]
            f.flat[idx] = 0.0
        return f
    if algo == "zoom":
        if u <= 0:
            return white
        s = max(1, int(round(SIZE * u)))
        im = Image.fromarray(L.astype(np.uint8)).resize((s, s))
        canvas = Image.fromarray(white.astype(np.uint8))
        off = (SIZE - s) // 2
        canvas.paste(im, (off, off))
        return np.asarray(canvas, dtype=np.float64)
    if algo == "blur":
        r = (1 - u) * BLUR_MAX
        im = Image.fromarray(L.astype(np.uint8)).filter(ImageFilter.GaussianBlur(r))
        return np.asarray(im, dtype=np.float64)
    if algo == "moya":
        f = over(white, overlay, 1 - u)
        f = over(f, L, u)
        return f
    if algo == "slideB":
        f = white.copy()
        off = int(round((1 - u) * SIZE))
        if off < SIZE:
            h = SIZE - off
            f[off:SIZE, :] = L[0:h, :]
        return f
    if algo == "slideR":
        f = white.copy()
        off = int(round((1 - u) * SIZE))
        if off < SIZE:
            w = SIZE - off
            f[:, off:SIZE] = L[:, 0:w]
        return f
    raise ValueError(algo)


def gradmag(f):
    gy, gx = np.gradient(f)
    return np.hypot(gx, gy)


def highpass(f):
    """0〜255 の float フレームの高周波成分 = 元画像 − ぼかし。0〜255 のまま処理する。"""
    im = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
    lo = np.asarray(im.filter(ImageFilter.GaussianBlur(HP_SIGMA)), dtype=np.float64)
    return f - lo   # 呼び出し側は 0〜255 のフレームを渡すこと


def sr_saliency(f):
    """Spectral Residual 顕著性 (Hou & Zhang, CVPR 2007)。標準どおり出力を [0,1] に
    正規化した顕著性マップを返す。小池研の視線誘導研究が視線計測でなく顕著性の計算で
    効果を測ったのに倣う。64px に縮小、対数振幅スペクトルの残差 R と位相 P から復元。
    ほぼ一様なフレーム(スライドで大半が画面外の時など)では顕著性が定義できないので
    None を返し、集計から除外する。"""
    img = cv2.resize(np.clip(f, 0, 255).astype(np.float32), (64, 64))
    if img.std() < 1.0:                     # ほぼ一様 = 顕著性が定義できない
        return None
    F = np.fft.fft2(img)
    A = np.abs(F); P = np.angle(F)
    L = np.log(A + 1e-9)
    L_avg = cv2.blur(L, (3, 3))
    R = np.clip(L - L_avg, -8, 8)           # exp のオーバーフロー防止(数値安定化)
    S = np.abs(np.fft.ifft2(np.exp(R + 1j * P))) ** 2
    S = cv2.GaussianBlur(S, (0, 0), 3)
    m = S.max()
    return S / m if m > 0 else None         # 標準どおり [0,1] に正規化


_HANN = np.outer(np.hanning(SIZE), np.hanning(SIZE))

def sf_discomfort(f):
    """自然画像の 1/f 振幅スペクトルからの逸脱に基づく視覚的不快感の指標
    (Fernandez & Wilkins 2008 / Penacchio & Wilkins 2015 の考え方の実装)。
    自然画像は振幅スペクトルが 1/f (log-log で傾き約 -1)。中〜高空間周波数に
    1/f より過剰なコントラストエネルギーがあると不快とされる(縞・散点など)。
    ここでは低周波の振幅を基準に 1/f 参照線を引き、その上に出た分の平均をとる。"""
    img = (np.clip(f, 0, 255) - 128.0) * _HANN     # 窓かけで枠エッジの影響を抑える
    A = np.abs(np.fft.fftshift(np.fft.fft2(img)))
    cy, cx = SIZE // 2, SIZE // 2
    yy, xx = np.indices((SIZE, SIZE))
    r = np.hypot(yy - cy, xx - cx).astype(int)
    nb = SIZE // 2
    radial = np.array([A[r == i].mean() if np.any(r == i) else 0.0 for i in range(1, nb)])
    freqs = np.arange(1, nb)
    # 低周波(freq 2〜4)の平均振幅を基準に 1/f 参照線 A_ref = c / f を引く
    lowband = (freqs >= 2) & (freqs <= 4)
    c = np.mean(radial[lowband] * freqs[lowband])
    ref = c / freqs
    # 中〜高周波(全体の10〜80%帯)で、参照線を超えた過剰分の平均(正規化)
    band = (freqs >= 0.10 * nb) & (freqs <= 0.80 * nb)
    excess = np.maximum(radial[band] - ref[band], 0.0)
    return float(excess.mean() / (radial[lowband].mean() + 1e-9))


def shift_mag(a, b):
    """位相相関で a→b の並進(px)を推定し大きさを返す。"""
    A = np.fft.fft2(a); B = np.fft.fft2(b)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-9
    r = np.fft.ifft2(R).real
    dy, dx = np.unravel_index(np.argmax(r), r.shape)
    if dy > SIZE / 2: dy -= SIZE
    if dx > SIZE / 2: dx -= SIZE
    return math.hypot(dx, dy)


ALGOS = ["fade", "stroke", "zoom", "blur", "moya", "slideB", "slideR"]


def main():
    print(f"文字 {len(CHARS)} 字 × {NF} フレーム × {len(ALGOS)} アルゴリズム を測定...", file=sys.stderr)
    Ls = {ch: load_L(ch) for ch in CHARS}
    overlay = np.mean(list(Ls.values()), axis=0)
    # stroke の画素順(文字ごとに決定的乱数でシャッフル。JS の mulberry32 と統計的に等価)
    stroke_orders = {}
    for ch in CHARS:
        ink = np.where(Ls[ch].reshape(-1) <= 128)[0]
        rng = np.random.default_rng(ord(ch))
        rng.shuffle(ink)
        stroke_orders[ch] = ink

    us = [i / (NF - 1) for i in range(NF)]
    result = {}
    for algo in ALGOS:
        grain_acc, churn_acc, hpchurn_acc, motion_acc, sal_acc, sfd_acc = [], [], [], [], [], []
        for ch in CHARS:
            L = Ls[ch]
            frames = [render(algo, L, u, overlay, stroke_orders[ch]) for u in us]  # 0〜255
            fn = [f / 255.0 for f in frames]                    # [0,1] 正規化(grain/churn 用)
            grain_acc.append(np.mean([gradmag(f).mean() for f in fn]))
            diffs = [np.abs(fn[i + 1] - fn[i]).mean() for i in range(NF - 1)]
            churn_acc.append(np.mean(diffs))
            hps = [highpass(f) for f in frames]                 # 高周波は 0〜255 のまま抽出
            hpchurn_acc.append(np.mean([np.abs(hps[i + 1] - hps[i]).mean() / 255.0
                                        for i in range(NF - 1)]))
            motion_acc.append(np.mean([shift_mag(frames[i], frames[i + 1]) for i in range(NF - 1)]))
            # 顕著性はu=0の空フレーム等を除き、定義できたフレームの平均を取る
            sals = [s.mean() for f, u in zip(frames, us) if u > 0
                    for s in [sr_saliency(f)] if s is not None]
            sal_acc.append(np.mean(sals) if sals else float("nan"))
            sfd_acc.append(np.mean([sf_discomfort(f) for f, u in zip(frames, us) if u > 0]))
        result[algo] = dict(
            grain=float(np.mean(grain_acc) * 100),        # 空間高周波(勾配) %
            churn=float(np.mean(churn_acc) * 100),        # フレーム間変化 %
            hp_flicker=float(np.mean(hpchurn_acc) * 100), # 高周波のフレーム間変化 %
            motion_px=float(np.mean(motion_acc)),         # 並進の大きさ px/フレーム
            saliency=float(np.mean(sal_acc) * 1000),      # Spectral Residual 顕著性(生値×1000)
            sf_discomfort=float(np.mean(sfd_acc)),         # 1/f 逸脱の不快感(Fernandez-Wilkins系)
        )
        r = result[algo]
        print(f"  {algo:8s} grain={r['grain']:6.2f}  churn={r['churn']:6.3f}  "
              f"motion={r['motion_px']:6.2f}px  saliency={r['saliency']:6.1f}  "
              f"sf_discomfort={r['sf_discomfort']:6.3f}", file=sys.stderr)

    json.dump(result, open(os.path.join(HERE, "intensity_result.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"\n結果: {os.path.join(HERE, 'intensity_result.json')}", file=sys.stderr)


if __name__ == "__main__":
    main()
