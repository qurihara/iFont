#!/usr/bin/env python3
"""原稿の図を作る。

- 模式図（fig_dir4_schematic.png、fig_timeline_schematic.png）は設計の説明であり、データではない。
- 末尾が _synthetic の図は仮想データで作った想定の結果である。図の中に「仮想データ」と描き込む。
  実測に置き換えるときは、入力を実測値に差し替え、描き込みを消し、ファイル名から _synthetic を外し、
  _synthetic のファイルをその場で消す。
数値は future_diary_plan.md と一致させる。乱数の種は固定する。
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from pathlib import Path

import os
PLAIN = os.environ.get('FD_PLAIN') == '1'   # 1 なら「仮想データ」の描き込みを省き figs_plain/ に出す
OUT = Path(__file__).resolve().parent / ('figs_plain' if PLAIN else 'figs')
OUT.mkdir(exist_ok=True)
rng = np.random.default_rng(20261008)

for cand in ['/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc', '/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc',
             '/Library/Fonts/Arial Unicode.ttf']:
    if Path(cand).exists():
        font_manager.fontManager.addfont(cand)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=cand).get_name()
        break
plt.rcParams['font.size'] = 10
plt.rcParams['axes.unicode_minus'] = False
C_AUDIO = '#B5412E'
C_VIS = '#2A4A7B'
C_GRAY = '#7A8493'


def synthetic_mark(ax):
    if PLAIN:
        return
    ax.text(0.99, 0.02, '仮想データ', transform=ax.transAxes, ha='right', va='bottom',
            fontsize=9, color='#c00000', alpha=0.85)


def logistic(t, x0, b1, lam=1.0, gam=1 / 44):
    return gam + (lam - gam) / (1 + np.exp(-b1 * (t - x0)))


JOMO44 = list('あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわ')
# 手元の推定（beta1_range/README.md の縮約値）を出発点にした想定値
BASE_B1 = dict(あ=0.618, お=0.514, え=0.441, ほ=0.431, も=0.424, み=0.345, わ=0.337, ま=0.323, ふ=0.321,
               さ=0.300, に=0.299, ひ=0.295, ね=0.294, ゆ=0.291, れ=0.273, た=0.254, の=0.250, め=0.248,
               る=0.246, せ=0.238, ろ=0.234, へ=0.222, う=0.217, そ=0.216, い=0.214, と=0.212, す=0.197,
               け=0.192, ら=0.187, ぬ=0.185, な=0.182, て=0.180, し=0.149, く=0.140, や=0.140, よ=0.135,
               む=0.107, き=0.104, は=0.079, ち=0.069, か=0.065, り=0.061, こ=0.031, つ=0.027)


def synth_curves44():
    """通し読みの想定値（x0, β1）。"""
    b1 = {}
    x0 = {}
    for k in JOMO44:
        b1[k] = BASE_B1[k] * np.exp(rng.normal(0, 0.22))
        x0[k] = float(np.clip(rng.normal(47, 18), 12, 118))
    b1['あ'] = 0.66
    b1['つ'] = 0.031
    b1['こ'] = 0.040
    x0['あ'] = 12
    x0['こ'] = 118
    x0['つ'] = 20
    return x0, b1


X0, B1 = synth_curves44()


def fig6_1():
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    for k in JOMO44:
        ax.scatter(X0[k], B1[k], s=14, color=C_AUDIO)
        ax.annotate(k, (X0[k], B1[k]), textcoords='offset points', xytext=(3, 2), fontsize=8)
    ax.set_yscale('log')
    ax.set_xlabel('レベル x0（第一音の立ち上がりからの ms）')
    ax.set_ylabel('傾き β1（1/ms、対数）')
    ax.set_title('上毛かるた 44 札の通し読みの曲線（x0 と β1）', fontsize=10)
    for d, lab in zip([25, 50, 100, 200, 400], ['D=25', '50', '100', '200', '400 ms']):
        b = 4.39 / (0.3 * d) * 0.95
        ax.axhline(b, color=C_VIS, lw=0.6, ls=':')
        ax.text(121, b, lab, fontsize=7, color=C_VIS, va='center')
    ax.set_xlim(0, 135)
    synthetic_mark(ax)
    fig.tight_layout()
    fig.savefig(OUT / 'fig6_1_curves44_synthetic.png', dpi=200)
    plt.close(fig)


def fig6_2():
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharey=True)
    t = np.linspace(0, 200, 400)
    Ds = [25, 50, 100, 200, 400]
    b1s = [0.55, 0.28, 0.14, 0.069, 0.035]
    x0s = [9, 16, 30, 57, 112]
    for ax, k, scale in zip(axes, ['あ', 'つ'], [1.0, 1.0]):
        for D, b, x in zip(Ds, b1s, x0s):
            ax.plot(t, logistic(t, x, b, lam=0.98), color=C_VIS, lw=1.2, alpha=0.5 + 0.1 * Ds.index(D) / 4)
            ax.text(x + 4.39 / b * 0.6 + 2, 0.5 - 0.07 * Ds.index(D), f'{D}', fontsize=7, color=C_VIS)
        ax.plot(t, logistic(t, X0[k], B1[k], lam=0.95), color=C_AUDIO, lw=2.2, label='音声（通し読み）')
        ax.set_title(f'「{k}」', fontsize=10)
        ax.set_xlabel('現れ始め／第一音からの時間 (ms)')
        synthetic_mark(ax)
    axes[0].set_ylabel('認識率')
    axes[0].legend(loc='lower right', fontsize=8, frameon=False, bbox_to_anchor=(1.0, 0.1))
    fig.suptitle('フェードの 5 段階（D = 25〜400 ms、青）と音声の曲線（赤）', fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / 'fig6_2_fade5_synthetic.png', dpi=200)
    plt.close(fig)


def fig6_3():
    n = 44
    cand = np.sort(np.clip(rng.gamma(4, 0.0055, n), 0.004, 0.046))
    cand[-1] = 0.046
    it1 = np.sort(np.clip(rng.gamma(3.2, 0.013, n), 0.006, 0.091))
    it1[-1] = 0.091
    it1 = np.sort(np.where(np.arange(n) >= n - 12, np.maximum(it1, 0.051), np.minimum(it1, 0.049)))
    it2 = np.sort(np.clip(rng.gamma(4, 0.0046, n), 0.004, 0.034))
    it2[-1] = 0.034
    # 中央値を計画の値に寄せる
    for arr, med in ((cand, 0.022), (it1, 0.038), (it2, 0.018)):
        arr *= med / np.median(arr)
    it1[-1] = 0.091
    cand[-1] = 0.046
    it2[-1] = 0.034
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    x = np.arange(1, n + 1)
    ax.plot(x, cand, 'o-', ms=3, lw=1, color=C_GRAY, label='候補版（方向4、測った曲線からの予測）')
    ax.plot(x, it1, 's-', ms=3, lw=1, color=C_VIS, alpha=0.6, label='精密版 1 回目（実測）')
    ax.plot(x, it2, '^-', ms=3, lw=1, color=C_AUDIO, label='精密版 2 回目（g を更新して実測）')
    ax.axhline(0.05, color='k', lw=0.6, ls='--')
    ax.text(1, 0.052, '収束の基準 0.05', fontsize=8)
    ax.set_xlabel('札（残差の小さい順）')
    ax.set_ylabel('音声との認識率の差の最大')
    ax.legend(fontsize=7.5, frameon=False, loc='upper left')
    ax.set_ylim(0, 0.1)
    synthetic_mark(ax)
    fig.tight_layout()
    fig.savefig(OUT / 'fig6_3_iteration_synthetic.png', dpi=200)
    plt.close(fig)
    return cand, it1, it2


def fig6_4():
    fig, ax = plt.subplots(figsize=(4.2, 3.6))
    xs, ys = [], []
    for k in JOMO44:
        pred = BASE_B1[k]
        meas = B1[k]
        if k in 'へろひふ':
            meas = pred * np.exp(rng.normal(0.9, 0.3))
        xs.append(pred)
        ys.append(meas)
        col = C_AUDIO if k in 'へろひふ' else C_VIS
        ax.scatter(pred, meas, s=14, color=col)
        ax.annotate(k, (pred, meas), textcoords='offset points', xytext=(3, 2), fontsize=7)
    lim = [0.02, 1.2]
    ax.plot(lim, lim, color=C_GRAY, lw=0.7, ls='--')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel('1 音の単独提示から予測した β1 (1/ms)')
    ax.set_ylabel('通し読みで実測した β1 (1/ms)')
    ax.set_title('赤: 単独提示で λ が 0.25 未満だった 4 札', fontsize=9)
    synthetic_mark(ax)
    fig.tight_layout()
    fig.savefig(OUT / 'fig6_4_prediction_synthetic.png', dpi=200)
    plt.close(fig)


def fig7_1():
    conds = ['補正なし', '紙の形', 'アプリ']
    means = [18.4, 1.2, -0.8]
    sds = [7.5, 5.7, 5.9]
    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    for i, (c, m, s) in enumerate(zip(conds, means, sds)):
        d = rng.normal(0, s, 20)
        d = d - d.mean() + m
        d = np.round(d)
        jit = rng.uniform(-0.18, 0.18, 20)
        ax.scatter(i + jit, d, s=14, color=C_GRAY, alpha=0.7)
        ci = 1.96 * s / np.sqrt(20)
        ax.errorbar(i, m, yerr=ci, fmt='o', color=C_AUDIO, capsize=4, ms=6, zorder=3)
        ax.text(i + 0.25, m, f'{m:+.1f}', fontsize=8, color=C_AUDIO, va='center')
    ax.axhline(0, color='k', lw=0.6)
    ax.axhspan(-4, 4, color=C_VIS, alpha=0.08)
    ax.text(2.45, 4.3, '同等とみなす範囲 ±4 枚', fontsize=7, color=C_VIS, ha='right')
    ax.set_xticks(range(3))
    ax.set_xticklabels(conds)
    ax.set_ylabel('取り札数の差（聞く役 − 見る役、枚）')
    ax.set_title('1 試合 44 枚、20 試合 × 3 条件。赤は平均と 95% 信頼区間', fontsize=9)
    synthetic_mark(ax)
    fig.tight_layout()
    fig.savefig(OUT / 'fig7_1_match_synthetic.png', dpi=200)
    plt.close(fig)


def fig7_2():
    fig, ax = plt.subplots(figsize=(5.0, 3.0))
    a = np.clip(rng.normal(0.46, 0.21, 420), 0, 1)
    v = np.clip(rng.normal(0.44, 0.23, 420), 0, 1)
    bins = np.linspace(0, 1, 21)
    ax.hist(a, bins=bins, alpha=0.6, color=C_AUDIO, label='聞く役（f_audio で計算）')
    ax.hist(v, bins=bins, alpha=0.5, color=C_VIS, label='見る役（f_visual で計算）')
    ax.set_xlabel('早押し度 1 − f(押した時刻)')
    ax.set_ylabel('取りの回数')
    ax.legend(fontsize=8, frameon=False)
    ax.set_title('アプリ条件（20 試合）で正解札を取った押しの早押し度', fontsize=9)
    synthetic_mark(ax)
    fig.tight_layout()
    fig.savefig(OUT / 'fig7_2_hayaoshi_synthetic.png', dpi=200)
    plt.close(fig)


def fig_dir4_schematic():
    fig, axes = plt.subplots(1, 3, figsize=(8.4, 2.7))
    t = np.linspace(0, 200, 400)
    fa = logistic(t, 60, 0.08, lam=0.97)
    ax = axes[0]
    ax.plot(t, fa, color=C_AUDIO, lw=2)
    ax.set_title('(1) 札ごとの音声の曲線を測る', fontsize=9)
    ax.text(100, 0.3, '通し読みを途中で\n打ち切って 44 択', fontsize=8, color=C_AUDIO)
    ax = axes[1]
    for D, b, x, lab, tx, ty in zip([25, 100, 400], [0.55, 0.14, 0.035], [9, 30, 112], ['速い', '中', '遅い'],
                                    [3, 48, 130], [0.9, 0.62, 0.3]):
        ax.plot(t, logistic(t, x, b, lam=0.98), color=C_VIS, lw=1.4)
        ax.text(tx, ty, lab, fontsize=8, color=C_VIS)
    ax.set_title('(2) 字ごとに K 段階の速さで測る', fontsize=9)
    ax = axes[2]
    ax.plot(t, fa, color=C_AUDIO, lw=2.4, label='音声')
    ax.plot(t, logistic(t, 30, 0.14, lam=0.98), color=C_VIS, lw=1.2, ls=':', label='選んだ段階（中）')
    ax.plot(t, logistic(t, 30 + 30, 0.14, lam=0.98), color=C_VIS, lw=1.6, label='開始を Δ だけずらす')
    ax.annotate('', xy=(60, 0.5), xytext=(30, 0.5), arrowprops=dict(arrowstyle='->', lw=1.2))
    ax.text(32, 0.56, 'Δ', fontsize=9)
    ax.legend(fontsize=7, frameon=False, loc='lower right')
    ax.set_title('(3) β1 が最も近い段階を選び x0 を合わせる', fontsize=9)
    for ax in axes:
        ax.set_xlabel('時間 (ms)', fontsize=8)
        ax.set_ylim(0, 1.05)
        ax.tick_params(labelsize=8)
    axes[0].set_ylabel('認識率', fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / 'fig_dir4_schematic.png', dpi=200)
    plt.close(fig)


def fig_timeline_schematic():
    fig, ax = plt.subplots(figsize=(8.4, 2.6))
    ax.set_xlim(0, 8)
    ax.set_ylim(0, 4)
    rows = ['読み手（合成音声）', '聞く役が受け取る', '見る役が受け取る（画面）', '札と判定']
    for i, r in enumerate(rows):
        y = 3.3 - i * 0.9
        ax.text(-0.05, y, r, ha='right', va='center', fontsize=8)
        ax.axhline(y, color=C_GRAY, lw=0.3)
    y = 3.3
    ax.add_patch(plt.Rectangle((0, y - 0.25), 2.0, 0.5, color='#333'))
    ax.text(1.0, y, '空読み（前の札）', color='w', ha='center', va='center', fontsize=8)
    ax.text(2.75, y, '約 1.5 秒', ha='center', va='center', fontsize=8)
    ax.add_patch(plt.Rectangle((3.5, y - 0.25), 4.0, 0.5, color=C_AUDIO))
    ax.text(5.5, y, '本読み（この札）', color='w', ha='center', va='center', fontsize=8)
    ax.axvline(3.5, color=C_AUDIO, lw=1, ls='--')
    ax.text(3.55, 3.85, '第一音（時計の原点）', color=C_AUDIO, fontsize=8)
    y = 2.4
    ax.add_patch(plt.Rectangle((3.5, y - 0.25), 0.6, 0.5, color=C_AUDIO))
    ax.text(3.8, y, '1 音目', color='w', ha='center', va='center', fontsize=7)
    ax.add_patch(plt.Rectangle((4.1, y - 0.25), 3.4, 0.5, color=C_AUDIO, alpha=0.7))
    ax.text(5.8, y, '続き（測った条件のまま）', color='w', ha='center', va='center', fontsize=8)
    y = 1.5
    ax.add_patch(plt.Rectangle((3.35, y - 0.25), 0.85, 0.5, color=C_VIS))
    ax.text(3.78, y, '1 文字目', color='w', ha='center', va='center', fontsize=7)
    ax.add_patch(plt.Rectangle((4.2, y - 0.25), 3.3, 0.5, color=C_VIS, alpha=0.7))
    ax.text(5.85, y, '2 文字目以降（読まれた時刻に現れる）', color='w', ha='center', va='center', fontsize=8)
    ax.annotate('', xy=(3.35, y + 0.38), xytext=(3.5, y + 0.38), arrowprops=dict(arrowstyle='->', lw=1))
    ax.text(3.3, y + 0.5, 'Δ（札ごと）', fontsize=7, ha='right')
    y = 0.6
    ax.text(3.6, y, '札に手が伸びる。先に触れた側の取り。聞く役は第一音、見る役は 1 文字目の現れ始めより前が早取り。', fontsize=8, va='center')
    ax.set_xticks(range(0, 9))
    ax.set_xticklabels([f'{i} s' for i in range(0, 9)], fontsize=7)
    ax.set_yticks([])
    for s in ['top', 'right', 'left']:
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / 'fig_timeline_schematic.png', dpi=200)
    plt.close(fig)


if __name__ == '__main__':
    fig6_1()
    fig6_2()
    fig6_3()
    fig6_4()
    fig7_1()
    fig7_2()
    fig_dir4_schematic()
    fig_timeline_schematic()
    print('done', sorted(p.name for p in OUT.glob('*.png')))
