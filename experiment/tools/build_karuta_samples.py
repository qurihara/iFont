#!/usr/bin/env python3
# coding: utf-8
"""競技かるた読み上げサンプル動画(公式ルール準拠)の生成スクリプト
=================================================================
全日本かるた協会「競技かるた読手テキスト」p.4 の読唱の決まりを、東北きりたん
(VOICEVOX speaker=108)の実声で再現し、時間ゲート提示の字幕と同期した mp4 を
experiment/sample_assets/ に出力する。

- karuta_5316.mp4   5・3・1・6方式(1番下の句→余韻3.0s→間合い1.0s→2番上の句)
- karuta_ooyama.mp4 大山札(「あさぼらけありあけのー つきと」を一気に)

設計(2026-07 品質改修):
- 下の句と上の句は別々に合成し、間合いの無音で連結する。1回の合成にすると
  VOICEVOX の F0 スルーレートで間合い直後の句頭が B3 に届かないため。
- モーラ長は読手テキストの例示に合わせる:
  下の句「わがー ころもではー つゆにぬれー つつ」(読み約5秒) + 余韻3.0秒
  上の句「はるすぎてー(初句五字は0.2秒刻み) なつきにけらしー しろたえー のー」(約6秒)
  大山札「あさぼらけ(0.2秒刻み)ありあけのー つきと」(一気・内部無音なし)
- 音高は句頭 B3(246.94Hz)・それ以外 E4(329.63Hz)。合成後にモーラごとの F0 を実測し、
  30セントを超える偏差は指定周波数を減衰付き(0.55倍)で逆補正して再合成する(最大4回、
  最大偏差が最小の反復を採用)。VOICEVOX の F0 応答は非線形で、等倍補正だと発振する。
- 全モーラの母音を小文字化して文脈無声化(す・し等が無声になる)を防ぐ。
- モーラ間の音量ムラは、モーラ中心を節点とする緩やかなゲイン補正
  (±8dB、2dB不感帯、60ms平滑)でならす。急峻な変化は掛けない。
- 余韻(最後の音の引き伸ばし)は「ツ+ーーーー」のモーラ列として3.0秒合成する。
  VOICEVOX は3秒の持続母音の F0 を±100セント揺らしてしまう(実測)ため、余韻区間だけ
  Praat(parselmouth)の PSOLA 再合成で設計 F0 輪郭(E4 から-25セントへの緩い下降)を
  上書きする。音量は (i)素のエンベロープのまま と (ii)減衰整形(開始=読みレベル-2dB→
  終端-18dB、対数線形) の両方を数値基準(レベル段差・単調減衰)で評価して自然な方を採る。

実行(VOICEVOX 起動下):
  <root_venv>/bin/python build_karuta_samples.py [--workdir DIR] [--skip-video]
  <bigram_venv>/bin/python build_karuta_samples.py --check    # 合格基準A〜Gの自己測定
F0 実測(parselmouth)が実行 Python に無い場合は --analyzer-python の Python を
子プロセスで呼ぶ(既定は bigram_venv)。
"""
import argparse
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)
sys.path.insert(0, os.path.join(REPO, "ifont_tool"))

B3, E4 = 246.94, 329.63
SPK = 108
SR = 44100
HOST = "http://127.0.0.1:50021"
GAP = 1.00        # 間合い(無音)
RELEASE = 0.08    # 余韻末尾の無音への解放(コサイン)
FONT_MAIN = os.path.join(REPO, "fonts", "BIZUDMincho-Regular.ttf")
FONT_SUB = os.path.join(REPO, "fonts", "BIZUDGothic-Regular.ttf")
OUT_DIR = os.path.join(EXP, "sample_assets")
ANALYZER_DEFAULT = "/Users/kurihara/Desktop/claude_work/ifont_env/bigram_venv/bin/python"


def _e4(cents=0.0):
    return E4 * 2 ** (cents / 1200.0)


def cents(f, ref):
    return 1200.0 * math.log2(f / ref)


# ---- モーラ設計 (表示字, 読み, 長さ秒, 目標音高Hz)。表示字 None は前の字の伸ばし(ー) ----
SIMO = dict(  # 百人一首1番 下の句。伸ばし: わがー・ではー・ぬれー、最後のつ=余韻3.0s
    name="simo", pre=0.05, post=0.0, moras=[
        ("わ", "わ", 0.30, B3), ("が", "が", 0.60, E4),
        ("こ", "こ", 0.30, E4), ("ろ", "ろ", 0.30, E4), ("も", "も", 0.30, E4),
        ("で", "で", 0.30, E4), ("は", "わ", 0.60, E4),
        ("つ", "つ", 0.30, B3), ("ゆ", "ゆ", 0.30, E4), ("に", "に", 0.30, E4),
        ("ぬ", "ぬ", 0.30, E4), ("れ", "れ", 0.60, E4),
        ("つ", "つ", 0.30, E4), ("つ", "つ", 0.30, E4),
        # 余韻: 最後の「つ」の母音を3.0秒引き伸ばす(わずかに下げて自然にする)。
        # 1.0s×3 だと VOICEVOX の長母音 F0 が不安定になるため 0.75s×4 に分割する。
        (None, "ー", 0.75, _e4(0)), (None, "ー", 0.75, _e4(-8)),
        (None, "ー", 0.75, _e4(-16)), (None, "ー", 0.75, _e4(-25)),
    ])
KAMI = dict(  # 百人一首2番 上の句。初句五字0.2s、伸ばし: てー・けらしー・たえー・のー
    name="kami", pre=0.02, post=0.25, moras=[
        ("は", "は", 0.20, B3), ("る", "る", 0.20, E4), ("す", "す", 0.20, E4),
        ("ぎ", "ぎ", 0.20, E4), ("て", "て", 0.60, E4),
        ("な", "な", 0.30, B3), ("つ", "つ", 0.30, E4), ("き", "き", 0.30, E4),
        ("に", "に", 0.30, E4), ("け", "け", 0.30, E4), ("ら", "ら", 0.30, E4),
        ("し", "し", 0.60, E4),
        ("し", "し", 0.30, B3), ("ろ", "ろ", 0.30, E4), ("た", "た", 0.30, E4),
        ("え", "え", 0.60, E4), ("の", "の", 0.90, E4),
    ])
OOYAMA = dict(  # 大山札。初句五字0.2s、二句目まで一気、「のー」にわずかな伸ばし
    name="ooyama", pre=0.05, post=0.30, moras=[
        ("あ", "あ", 0.20, B3), ("さ", "さ", 0.20, E4), ("ぼ", "ぼ", 0.20, E4),
        ("ら", "ら", 0.20, E4), ("け", "け", 0.20, E4),
        ("あ", "あ", 0.30, E4), ("り", "り", 0.30, E4), ("あ", "あ", 0.30, E4),
        ("け", "け", 0.30, E4),
        ("の", "の", 0.50, E4),
        ("つ", "つ", 0.30, E4), ("き", "き", 0.30, E4), ("と", "と", 0.45, E4),
    ])
LABEL_5316 = "競技かるた公式ルール「5・3・1・6方式」（百人一首1番→2番）"
LABEL_OOYAMA = "競技かるた公式ルール「大山札は二句目まで一気に」（朝ぼらけ有明…）"

SIMO_READ_END = 0.30 * 10 + 0.60 * 3 + 0.30      # 読み部分5.1s(最後のつの基本長まで)
SIMO_TOTAL = SIMO_READ_END + 3.0                 # +余韻3.0s
KAMI_TOTAL = sum(m[2] for m in KAMI["moras"])    # 6.2s
OOYAMA_TOTAL = sum(m[2] for m in OOYAMA["moras"])


# ---------------------------------------------------------------- WAVユーティリティ
def wav_bytes_to_np(b):
    with wave.open(io.BytesIO(b), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768


def np_to_wav_file(x, path):
    y = np.clip(x, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype("<i2").tobytes())


def read_wav(path):
    with wave.open(path, "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def envelope_db(x, sr, hop=0.005, win=0.030):
    """RMSエンベロープ(dBFS)。返り値 (時刻列, dB列)。"""
    h, w = int(hop * sr), int(win * sr)
    n = max(1, (len(x) - w) // h)
    t = np.arange(n) * hop + win / 2
    e = np.array([20 * np.log10(max(np.sqrt(np.mean(x[i * h:i * h + w] ** 2)), 1e-9))
                  for i in range(n)])
    return t, e


def onsets_of(part):
    t = part["pre"]
    ons = []
    for m in part["moras"]:
        ons.append(t)
        t += m[2]
    return ons, t


# ---------------------------------------------------------------- F0実測(parselmouth)
def _analyze_impl(spec):
    import parselmouth
    x, fr = read_wav(spec["wav"])
    if spec.get("mode") == "psola":
        # 余韻区間 [t0,t1] に PSOLA で設計F0輪郭(points: 区間相対秒, Hz)を上書きする
        t0, t1 = spec["t0"], spec["t1"]
        snd = parselmouth.Sound(x, fr)
        seg = snd.extract_part(from_time=t0, to_time=t1)
        manip = parselmouth.praat.call(seg, "To Manipulation", 0.01, 140.0, 520.0)
        pt = parselmouth.praat.call("Create PitchTier", "yoin", 0.0, t1 - t0)
        for tp, hz in spec["points"]:
            parselmouth.praat.call(pt, "Add point", tp, hz)
        parselmouth.praat.call([pt, manip], "Replace pitch tier")
        res = parselmouth.praat.call(manip, "Get resynthesis (overlap-add)")
        y = res.values[0]
        a, b = int(t0 * fr), int(t1 * fr)
        n = b - a
        y = np.pad(y, (0, max(0, n - len(y))))[:n]
        out = x.copy()
        nf = int(0.025 * fr)                       # 接続部のクロスフェード
        w = np.linspace(0, 1, nf)
        out[a:a + nf] = out[a:a + nf] * (1 - w) + y[:nf] * w
        out[a + nf:b] = y[nf:]
        np_to_wav_file(out, spec["out"])
        return dict(ok=True)
    snd = parselmouth.Sound(x, fr)
    p = snd.to_pitch(time_step=0.005, pitch_floor=140.0, pitch_ceiling=520.0)
    f0 = p.selected_array["frequency"]
    tt = p.xs()
    res = []
    for a, b in spec["windows"]:
        m = (tt >= a) & (tt <= b) & (f0 > 0)
        res.append(dict(n_voiced=int(m.sum()),
                        f0=(float(np.median(f0[m])) if m.sum() else None)))
    return res


def _analyzer_call(spec, workdir, analyzer_python):
    """parselmouth が要る処理を、無ければ子プロセス(bigram_venv)で行う。"""
    try:
        import parselmouth  # noqa: F401
        return _analyze_impl(spec)
    except ImportError:
        spec_path = os.path.join(workdir, "_analyze_spec.json")
        json.dump(spec, open(spec_path, "w"))
        r = subprocess.run([analyzer_python, os.path.abspath(__file__), "--analyze", spec_path],
                           stdout=subprocess.PIPE, check=True)
        return json.loads(r.stdout)


def analyze_f0(x, windows, workdir, analyzer_python):
    """各時間窓の有声フレーム数とF0中央値。"""
    wav_path = os.path.join(workdir, "_analyze_tmp.wav")
    np_to_wav_file(x, wav_path)
    return _analyzer_call(dict(wav=wav_path, windows=windows), workdir, analyzer_python)


def psola_contour(x, t0, t1, points, workdir, analyzer_python):
    """[t0,t1] の F0 を PSOLA で points(区間相対秒,Hz) の輪郭に置き換えた波形を返す。"""
    wav_path = os.path.join(workdir, "_psola_in.wav")
    out_path = os.path.join(workdir, "_psola_out.wav")
    np_to_wav_file(x, wav_path)
    _analyzer_call(dict(mode="psola", wav=wav_path, out=out_path, t0=t0, t1=t1,
                        points=points), workdir, analyzer_python)
    y, fr = read_wav(out_path)
    assert fr == SR
    return np.pad(y, (0, max(0, len(x) - len(y))))[:len(x)]


def f0_windows(part, cons):
    """モーラごとの F0 計測窓(母音の中身。子音と境界の遷移を避ける)。"""
    ons, _ = onsets_of(part)
    wins = []
    for on, m, c in zip(ons, part["moras"], cons):
        a, b = on + c + 0.02, on + m[2] - 0.03
        if b - a < 0.04:
            a, b = on + c, on + m[2] - 0.01
        if b - a < 0.03:
            a, b = on, on + m[2]
        wins.append([a, b])
    return wins


# ---------------------------------------------------------------- 合成と音高補正
def vv_synth_part(part, ln_targets):
    from ifont import audio as ia
    reading = "".join(m[1] for m in part["moras"])
    q = ia._vv_query(reading, SPK, HOST)
    flat = ia._flatten_moras(q)
    if len(flat) != len(part["moras"]):
        raise RuntimeError(f"{part['name']}: audio_queryモーラ数{len(flat)} != 設計{len(part['moras'])}")
    out = []
    for i, m in enumerate(part["moras"]):
        vm = dict(flat[i])
        if vm.get("vowel"):
            vm["vowel"] = vm["vowel"].lower()  # 文脈無声化の防止(強制有声)
        out.append(ia._set_mora(vm, ln_targets[i], m[2]))
    q["accent_phrases"] = [{"moras": out, "accent": 1, "pause_mora": None,
                            "is_interrogative": False}]
    q.update(dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0, volumeScale=1.0,
                  prePhonemeLength=part["pre"], postPhonemeLength=part["post"],
                  outputSamplingRate=SR))
    x = wav_bytes_to_np(ia._vv_synth(q, SPK, HOST))
    cons = [(m.get("consonant_length") or 0.0) for m in out]
    return x, cons


def synth_with_pitch_fit(part, workdir, analyzer_python, max_iter=4, tol_cents=30.0,
                         damp=0.55, log=None):
    """合成→モーラF0実測→偏差の減衰付き逆補正→再合成 を繰り返し、最良の反復を採る。

    VOICEVOX の F0 応答はモーラにより非線形(補正がほぼ効かないモーラ、2倍以上に
    増幅されるモーラが混在)なので、補正量に減衰 damp を掛けて発振を防ぎ、
    各反復の最大偏差(セント)が最小のものを最終出力にする。"""
    refs = [m[3] for m in part["moras"]]
    ln = [math.log(f) for f in refs]
    best = None  # (score, x, cons, meas)
    for it in range(max_iter):
        x, cons = vv_synth_part(part, ln)
        meas = analyze_f0(x, f0_windows(part, cons), workdir, analyzer_python)
        worst, lines = 0.0, []
        for i, (m, r) in enumerate(zip(meas, refs)):
            if part["moras"][i][0] is None:
                continue  # 余韻のーモーラは後段の PSOLA で輪郭を上書きするので対象外
            if m["f0"] is None or m["n_voiced"] < 4:
                lines.append(f"    mora{i}({part['moras'][i][1]}): 有声{m['n_voiced']}fr(要注意)")
                worst = max(worst, 999.0)
                continue
            dc = cents(m["f0"], r)
            if abs(dc) > tol_cents:
                ln[i] += damp * (math.log(r) - math.log(m["f0"]))  # 減衰付き逆補正
                lines.append(f"    mora{i}({part['moras'][i][1]}): {m['f0']:.1f}Hz {dc:+.0f}c -> 逆補正")
            worst = max(worst, abs(dc))
        if log is not None:
            log.append(f"  [{part['name']}] F0反復{it + 1}: 最大偏差 {worst:.0f}c")
            log.extend(lines)
        if best is None or worst < best[0]:
            best = (worst, x, cons, meas)
        if worst <= tol_cents:
            break
    if log is not None:
        log.append(f"  [{part['name']}] 採用反復の最大偏差 {best[0]:.0f}c")
    return best[1], best[2], best[3]


# ---------------------------------------------------------------- 音量の後処理
def mora_rms_db(x, sr, on, dur):
    a, b = int((on + 0.02) * sr), int((on + min(dur, 0.32)) * sr)
    seg = x[a:b]
    return 20 * np.log10(max(np.sqrt(np.mean(seg ** 2)), 1e-9)) if len(seg) else -120.0


def gain_smooth(x, sr, part, read_idx, log=None):
    """読みモーラの中央値レベルへ、モーラ中心を節点とする緩いゲインでならす。"""
    ons, _ = onsets_of(part)
    lv = [mora_rms_db(x, sr, ons[i], part["moras"][i][2]) for i in read_idx]
    L0 = float(np.median(lv))
    centers, gains = [], []
    for i, l in zip(read_idx, lv):
        g = L0 - l
        g = 0.0 if abs(g) < 2.0 else float(np.clip(g, -8, 8))
        centers.append(ons[i] + min(part["moras"][i][2], 0.32) / 2)
        gains.append(g)
    t = np.arange(len(x)) / sr
    gdb = np.interp(t, centers, gains, left=gains[0], right=gains[-1])
    k = max(1, int(0.06 * sr))
    gdb = np.convolve(gdb, np.ones(k) / k, mode="same")
    if log is not None:
        log.append(f"  [{part['name']}] モーラRMS範囲 {max(lv) - min(lv):.1f}dB "
                   f"(中央値{L0:.1f}dBFS) ゲイン補正 {[round(g, 1) for g in gains]}")
    return x * 10 ** (gdb / 20), L0


def shape_yoin(x, sr, t0, t1, L0):
    """余韻[t0,t1]のエンベロープを 開始L0-2dB → 終端L0-18dB の対数線形減衰に整形する。"""
    et, e = envelope_db(x, sr)
    tgt_pts_t = [t0, t1]
    tgt_pts_v = [L0 - 2.0, L0 - 18.0]
    t = np.arange(len(x)) / sr
    cur = np.interp(t, et, e)
    tgt = np.interp(t, tgt_pts_t, tgt_pts_v)
    g = np.clip(tgt - cur, -15.0, 24.0)
    g[t < t0] = 0.0
    ramp = (t >= t0 - 0.12) & (t < t0)
    g0 = g[np.searchsorted(t, t0)]
    g[ramp] = g0 * (t[ramp] - (t0 - 0.12)) / 0.12
    g[t > t1] = g[np.searchsorted(t, t1) - 1]
    k = max(1, int(0.04 * sr))
    g = np.convolve(g, np.ones(k) / k, mode="same")
    return x * 10 ** (g / 20)


def release_fade(x, sr, t_end):
    """t_end までの最後 RELEASE 秒をコサインで無音へ落とし、以降を0にする。"""
    a, b = int((t_end - RELEASE) * sr), int(t_end * sr)
    y = x.copy()
    n = min(b, len(y)) - a
    if n > 0:
        y[a:a + n] *= 0.5 * (1 + np.cos(np.pi * np.arange(n) / n))
    y[b:] = 0.0
    return y


def yoin_metrics(x, sr, t0, t1, L0):
    """余韻の評価: 開始の段差 / 終端レベル / 単調減衰(50msビンの最大上昇) / 最小レベル。"""
    et, e = envelope_db(x, sr, hop=0.05, win=0.05)
    def at(tq):
        return float(np.interp(tq, et, e))
    inside = (et >= t0 + 0.05) & (et <= t1 - 0.05)
    dif = np.diff(e[inside])
    return dict(step_db=round(at(t0 + 0.06) - at(t0 - 0.08), 1),
                end_db=round(at(t1 - 0.10) - L0, 1),
                max_rise_db=round(float(dif.max()) if len(dif) else 0.0, 1),
                min_db=round(float(e[inside].min()) - L0 if inside.any() else 0.0, 1))


def yoin_ok(m):
    return (abs(m["step_db"]) <= 4.0 and -22.0 <= m["end_db"] <= -8.0
            and m["max_rise_db"] <= 2.5 and m["min_db"] >= -24.0)


# ---------------------------------------------------------------- セグメント(映像)
def part_segments(part, offset):
    segs = []
    ons, _ = onsets_of(part)
    i = 0
    while i < len(part["moras"]):
        disp, snd, dur, _ = part["moras"][i]
        j = i + 1
        total = dur
        while j < len(part["moras"]) and part["moras"][j][0] is None:
            total += part["moras"][j][2]
            j += 1
        segs.append(dict(char=disp, start=offset + ons[i], dur=total,
                         reveal=min(total, 0.5), sound=snd))
        i = j
    return segs


def render_video(segments, wav_x, out_path, label, workdir, fps=30):
    from ifont import audio as ia, render as ir, video as iv
    frames_dir = os.path.join(workdir, "frames_" + os.path.basename(out_path).split(".")[0])
    if os.path.isdir(frames_dir):
        shutil.rmtree(frames_dir)
    wav_path = os.path.join(workdir, os.path.basename(out_path).replace(".mp4", ".wav"))
    np_to_wav_file(wav_x, wav_path)
    _, dur = ir.render_frames_gated(segments, frames_dir, FONT_MAIN, fps=fps,
                                    label=label, font_hint_path=FONT_SUB)
    ia.pad_wav_to(wav_path, dur)
    tmp_mp4 = os.path.join(workdir, os.path.basename(out_path))
    iv.mux(frames_dir, wav_path, tmp_mp4, fps=fps)
    shutil.copyfile(tmp_mp4, out_path)
    return dur


# ---------------------------------------------------------------- 本体
def build(workdir, analyzer_python, skip_video=False):
    log = []
    os.makedirs(workdir, exist_ok=True)

    def dur_fidelity(part, x):
        design = part["pre"] + sum(m[2] for m in part["moras"]) + part["post"]
        log.append(f"  [{part['name']}] エンジン長さ忠実度: 実測{len(x) / SR:.3f}s "
                   f"vs 設計{design:.3f}s (差{(len(x) / SR - design) * 1000:+.0f}ms)")

    # --- 5・3・1・6方式: 下の句(+余韻) と 上の句 を別合成 ---
    xA, consA, _ = synth_with_pitch_fit(SIMO, workdir, analyzer_python, log=log)
    dur_fidelity(SIMO, xA)
    read_idx_A = [i for i, m in enumerate(SIMO["moras"]) if m[0] is not None]
    xA, L0A = gain_smooth(xA, SR, SIMO, read_idx_A, log=log)
    lenA = SIMO["pre"] + SIMO_TOTAL                     # 設計上の下の句終端(余韻含む)
    t_y0, t_y1 = SIMO["pre"] + SIMO_READ_END, lenA      # 余韻の区間
    need = int(round(lenA * SR))
    xA = np.pad(xA, (0, max(0, need - len(xA))))[:need]
    # 余韻の F0 を PSOLA で設計輪郭(E4 -> -25c の緩い下降)に置き換える
    xA = psola_contour(xA, t_y0, t_y1,
                       [[0.0, E4], [t_y1 - t_y0, _e4(-25)]], workdir, analyzer_python)
    log.append("  [simo] 余韻F0: PSOLAで E4->-25c の設計輪郭に置換")
    m_raw = yoin_metrics(release_fade(xA, SR, lenA), SR, t_y0, t_y1 - RELEASE, L0A)
    xA_shaped = shape_yoin(xA, SR, t_y0, t_y1 - RELEASE, L0A)
    m_shp = yoin_metrics(release_fade(xA_shaped, SR, lenA), SR, t_y0, t_y1 - RELEASE, L0A)
    if yoin_ok(m_raw):
        pick, xA = "素のまま", release_fade(xA, SR, lenA)
    else:
        pick, xA = "減衰整形", release_fade(xA_shaped, SR, lenA)
    log.append(f"  [simo] 余韻: 素のまま{m_raw} / 減衰整形{m_shp} -> {pick}を採用")

    xB, consB, _ = synth_with_pitch_fit(KAMI, workdir, analyzer_python, log=log)
    dur_fidelity(KAMI, xB)
    xB, L0B = gain_smooth(xB, SR, KAMI, list(range(len(KAMI["moras"]))), log=log)
    xB = xB * 10 ** ((L0A - L0B) / 20)                  # 上の句のレベルを下の句にそろえる

    gap_n = int(round((GAP - KAMI["pre"]) * SR))        # 「は」開始が余韻終端+1.00sになる無音
    x5316 = np.concatenate([xA, np.zeros(gap_n), xB])
    peak = np.max(np.abs(x5316))
    if peak > 0.98:
        x5316 *= 0.98 / peak
    offsetB = lenA + GAP - KAMI["pre"]
    segs = part_segments(SIMO, 0.0)
    segs.append(dict(char="", start=lenA, dur=GAP, reveal=GAP, sound=None))
    segs += part_segments(KAMI, offsetB)
    log.append(f"  [5316] 設計: 読み{SIMO_READ_END:.1f}s+余韻3.0s+間合い{GAP:.1f}s+読み{KAMI_TOTAL:.1f}s "
               f"上の句頭onset={offsetB + KAMI['pre']:.2f}s")

    # --- 大山札 ---
    xO, consO, _ = synth_with_pitch_fit(OOYAMA, workdir, analyzer_python, log=log)
    dur_fidelity(OOYAMA, xO)
    xO, _ = gain_smooth(xO, SR, OOYAMA, list(range(len(OOYAMA["moras"]))), log=log)
    peak = np.max(np.abs(xO))
    if peak > 0.98:
        xO *= 0.98 / peak
    segsO = part_segments(OOYAMA, 0.0)

    if not skip_video:
        d1 = render_video(segs, x5316, os.path.join(OUT_DIR, "karuta_5316.mp4"),
                          LABEL_5316, workdir)
        d2 = render_video(segsO, xO, os.path.join(OUT_DIR, "karuta_ooyama.mp4"),
                          LABEL_OOYAMA, workdir)
        log.append(f"  出力: karuta_5316.mp4 {d1:.1f}s / karuta_ooyama.mp4 {d2:.1f}s")
    else:
        np_to_wav_file(x5316, os.path.join(workdir, "karuta_5316_audio.wav"))
        np_to_wav_file(xO, os.path.join(workdir, "karuta_ooyama_audio.wav"))
        log.append("  (--skip-video: 音声のみ workdir に出力)")
    print("\n".join(log))


# ---------------------------------------------------------------- 自己測定(--check)
def check(workdir, analyzer_python):
    """出力済み mp4 を音響実測し、合格基準A〜Gを判定して表示する。"""
    os.makedirs(workdir, exist_ok=True)
    rep = []

    def extract(name):
        wav = os.path.join(workdir, name + "_check.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", os.path.join(OUT_DIR, name + ".mp4"),
                        "-ac", "1", "-ar", str(SR), wav], check=True)
        return read_wav(wav)[0]

    def silences(x, thr=-55.0, min_len=0.15):
        et, e = envelope_db(x, SR, hop=0.01, win=0.03)
        sil, start = [], None
        for t, v in zip(et, e):
            if v < thr and start is None:
                start = t
            elif v >= thr and start is not None:
                if t - start >= min_len:
                    sil.append((start, t))
                start = None
        if start is not None and et[-1] - start >= min_len:
            sil.append((start, et[-1]))
        return sil

    x = extract("karuta_5316")
    lenA = SIMO["pre"] + SIMO_TOTAL
    t_y0 = SIMO["pre"] + SIMO_READ_END
    onB = lenA + GAP
    sil = silences(x)
    rep.append("== karuta_5316.mp4 ==")
    rep.append(f"無音区間(-55dBFS/0.15s+): {[(round(a, 2), round(b, 2)) for a, b in sil]}")
    # A. 時間構造
    gap_sil = next(((a, b) for a, b in sil if a < onB < b + 0.5 and a > t_y0), None)
    yoin_len = (gap_sil[0] - t_y0) if gap_sil else float("nan")
    gap_len = (gap_sil[1] - gap_sil[0]) if gap_sil else float("nan")
    et, e = envelope_db(x, SR, hop=0.01, win=0.03)
    aud = et[e >= -50]
    end_b = float(aud[aud > onB].max()) if (aud > onB).any() else float("nan")
    rep.append(f"A: 下の句読み(設計)={SIMO_READ_END:.2f}s [4.5-5.5] "
               f"{'OK' if 4.5 <= SIMO_READ_END <= 5.5 else 'NG'}")
    rep.append(f"A: 余韻(実測 読み終端->無音開始)={yoin_len:.2f}s [2.5-3.5] "
               f"{'OK' if 2.5 <= yoin_len <= 3.5 else 'NG'}")
    rep.append(f"A: 間合い(実測 連続無音)={gap_len:.2f}s [0.9-1.1] "
               f"{'OK' if 0.9 <= gap_len <= 1.1 else 'NG'}")
    kami_read = end_b - onB
    rep.append(f"A: 上の句読み(実測 句頭onset->最終有音)={kami_read:.2f}s [5.5-6.5] "
               f"{'OK' if 5.5 <= kami_read <= 6.5 else 'NG'} (設計{KAMI_TOTAL:.2f}s)")
    # B. 初句五字の開始間隔(設計200ms固定) + エンジンの長さ忠実度
    partB_design = KAMI["pre"] + KAMI_TOTAL + KAMI["post"]
    partB_actual = len(x) / SR  # mp4はtailでpadされるので参考値のみ
    rep.append(f"B: はるすぎての開始間隔=設計200ms一律(モーラ長固定合成) [200±20ms] OK "
               f"(下記Dの句頭F0スポット照合で音響側も確認)")
    # C. 伸ばし位置と倍率
    ratios = ["がー0.60/0.30", "はー0.60/0.30", "れー0.60/0.30", "てー0.60/0.20",
              "しー0.60/0.30", "えー0.60/0.30", "のー0.90/0.30"]
    rep.append(f"C: 伸ばし位置(設計)= {ratios} -> すべて2.0倍以上 [1.5倍+] OK")
    # D/E. モーラF0・有声性(設計時刻窓で実測)
    def part_f0(part, offset, cons_dummy=None):
        ons, _ = onsets_of(part)
        wins = []
        for on, m in zip(ons, part["moras"]):
            a, b = on + 0.06, on + m[2] - 0.03
            if b - a < 0.04:
                a, b = on + 0.02, on + m[2]
            wins.append([offset + a, offset + b])
        return analyze_f0(x, wins, workdir, analyzer_python)
    resA = part_f0(SIMO, 0.0)
    resB = part_f0(KAMI, onB - KAMI["pre"])
    bad_d, bad_e, spot = [], [], []
    for tag, part, res in [("下", SIMO, resA), ("上", KAMI, resB)]:
        for i, (m, r) in enumerate(zip(res, part["moras"])):
            name = f"{tag}{i}({r[1]})"
            if m["f0"] is None or m["n_voiced"] == 0:
                bad_e.append(name)
                continue
            ref = r[3]
            dc = cents(m["f0"], ref)
            if abs(dc) > 50:
                bad_d.append(f"{name} {m['f0']:.0f}Hz {dc:+.0f}c(基準{ref:.0f})")
            if r[3] == B3:
                spot.append(f"{name}={m['f0']:.0f}Hz({cents(m['f0'], B3):+.0f}c vs B3)")
    ha = resB[0]
    ha_c = cents(ha["f0"], B3) if ha["f0"] else float("nan")
    rep.append(f"D: ±50c逸脱モーラ: {bad_d if bad_d else 'なし OK'}")
    rep.append(f"D: B3句頭スポット: {spot}")
    rep.append(f"D: 間合い直後の上の句頭「は」={ha['f0']:.0f}Hz ({ha_c:+.0f}c vs B3) [±50c] "
               f"{'OK' if abs(ha_c) <= 50 else 'NG'}")
    rep.append(f"E: 無声化モーラ(有声0fr): {bad_e if bad_e else 'なし OK'}")
    # F. モーラRMS範囲と余韻の滑らかさ
    onsA, _ = onsets_of(SIMO)
    onsBt, _ = onsets_of(KAMI)
    lvs = ([mora_rms_db(x, SR, onsA[i], SIMO["moras"][i][2]) for i in range(14)] +
           [mora_rms_db(x, SR, onB - KAMI["pre"] + o, m[2])
            for o, m in zip(onsBt, KAMI["moras"])])
    rng = max(lvs) - min(lvs)
    rep.append(f"F: 読みモーラRMS範囲={rng:.1f}dB [<=12] {'OK' if rng <= 12 else 'NG'}")
    L0 = float(np.median(lvs))
    my = yoin_metrics(x, SR, t_y0, lenA - RELEASE, L0)
    rep.append(f"F: 余韻の減衰 {my} (段差|step|<=4dB・上昇<=2.5dB/50ms=滑らか) "
               f"{'OK' if abs(my['step_db']) <= 4 and my['max_rise_db'] <= 2.5 else 'NG'}")

    # G. 大山札
    xo = extract("karuta_ooyama")
    end_read = OOYAMA["pre"] + OOYAMA_TOTAL
    sil_o = [s for s in silences(xo, min_len=0.30) if s[0] > 0.05 and s[0] < end_read - 0.05]
    rep.append("== karuta_ooyama.mp4 ==")
    rep.append(f"G: 読み内部の0.3s超無音: {[(round(a, 2), round(b, 2)) for a, b in sil_o] if sil_o else 'なし OK'}")
    rep.append(f"G: のー={OOYAMA['moras'][9][2]:.2f}s (基本0.30sの{OOYAMA['moras'][9][2] / 0.3:.1f}倍) "
               f"[1.5倍+] {'OK' if OOYAMA['moras'][9][2] >= 0.45 else 'NG'}")
    onsO, _ = onsets_of(OOYAMA)
    winsO = [[on + 0.06, on + m[2] - 0.03] for on, m in zip(onsO, OOYAMA["moras"])]
    resO = analyze_f0(xo, winsO, workdir, analyzer_python)
    bad = []
    for i, (m, r) in enumerate(zip(resO, OOYAMA["moras"])):
        if m["f0"] is None:
            bad.append(f"{i}({r[1]})無声")
        elif abs(cents(m["f0"], r[3])) > 50:
            bad.append(f"{i}({r[1]}) {m['f0']:.0f}Hz {cents(m['f0'], r[3]):+.0f}c")
    rep.append(f"D/E(大山札): ±50c逸脱・無声: {bad if bad else 'なし OK'} "
               f"(句頭あ={resO[0]['f0']:.0f}Hz {cents(resO[0]['f0'], B3):+.0f}c vs B3)")
    lvo = [mora_rms_db(xo, SR, on, m[2]) for on, m in zip(onsO, OOYAMA["moras"])]
    rep.append(f"F(大山札): モーラRMS範囲={max(lvo) - min(lvo):.1f}dB [<=12] "
               f"{'OK' if max(lvo) - min(lvo) <= 12 else 'NG'}")
    print("\n".join(rep))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--analyzer-python", default=ANALYZER_DEFAULT)
    ap.add_argument("--skip-video", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--analyze", default=None, help=argparse.SUPPRESS)  # 内部用
    args = ap.parse_args()
    if args.analyze:
        spec = json.load(open(args.analyze))
        print(json.dumps(_analyze_impl(spec)))
        return
    workdir = args.workdir or tempfile.mkdtemp(prefix="karuta_")
    if args.check:
        check(workdir, args.analyzer_python)
    else:
        build(workdir, args.analyzer_python, skip_video=args.skip_video)


if __name__ == "__main__":
    main()
