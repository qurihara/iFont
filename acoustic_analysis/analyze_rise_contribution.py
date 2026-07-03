#!/usr/bin/env python3
"""
上昇輪郭(B3→E4)の寄与を切り分ける — 平坦E4→E4 との比較 (2026-07-04)
====================================================================
MCD 乖離の解析(analyze_mcd_divergence.py)は、単音(平坦E4)と、B3→E4 と上がる2字の
2文字目(C2)を比べていた。この乖離には「共調音・位置(単独か語中か)・上昇輪郭の到達点で
あること」が混ざる。ここでは、輪郭だけを変えた平坦 E4→E4 の C2 を作って、上昇輪郭が
乖離をどれだけ膨らませているかを切り分ける。

方法。各ターゲット C2(72字)につき、決定的に散らした 8 通りの先行文字 C1 を選ぶ(576対)。
その対を、build_query に両モーラとも log(E4) を渡して平坦 E4→E4 で合成し、C2 を切り出す。
比べる相手は、コミット済みの上昇版プール(本番salt, B3→E4)の同じ対の C2 と、単音 E4 版。
- MCD_rising = 乖離(単音E4, 上昇版C2)   ← 既存の乖離と同じ量
- MCD_flat   = 乖離(単音E4, 平坦版C2)   ← 上昇輪郭を取り除いた乖離
差 (MCD_rising - MCD_flat) が、上昇輪郭に由来する分である。

出力: acoustic_analysis/rise_contribution_result.json
要エンジン(VOICEVOX 127.0.0.1:50021)。
"""
import json, os, sys, tempfile, statistics, io, wave, hashlib
import numpy as np, soundfile as sf
from pymcd.mcd import Calculate_MCD

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "two_char_audio"))
import build_2char_pool as b2, ifont_common as ic

E4 = b2.E4
import math
P_E4 = math.log(E4)

E4_MAN = os.path.join(HERE, "audio1char_E4_manifest.json")
E4_AK  = os.path.join(HERE, "audio1char_E4_answerkey.json")
E4_DIR = os.path.join(HERE, "audio1char_E4_stimuli")
TC_MAN = os.path.join(REPO, "experiment", "audio2char_manifest.json")     # 本番salt(上昇版)
TC_DIR = os.path.join(REPO, "experiment", "audio2char_stimuli")
OUT    = os.path.join(HERE, "rise_contribution_result.json")

CLASS = {}
for grp, chars in {
    "母音": "あいうえお", "半母音": "やゆよわ", "撥音": "ん",
    "無声破裂": "かきくけこたてとぱぴぷぺぽ", "無声摩擦": "さしすせそはひふへほ",
    "破擦無声": "ちつ", "有声破裂": "がぎぐげごだぢづでどばびぶべぼ",
    "有声摩擦": "ざじずぜぞ",
    "その他": "らりるれろまみむめもなにぬねのゔ",
}.items():
    for c in chars:
        CLASS[c] = grp

mcd_dtw = Calculate_MCD("dtw")


def wav_bytes_to_arr(wb):
    w = wave.open(io.BytesIO(wb)); sr = w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return a, sr


def write_seg(a, sr, t0, dur, dst):
    i0 = max(0, int(t0 * sr)); i1 = min(len(a), int((t0 + dur) * sr))
    seg = a[i0:i1]
    if len(seg) < int(0.02 * sr):
        return False
    sf.write(dst, seg, sr)
    return True


def main():
    tmp = tempfile.mkdtemp(prefix="rise_")
    # 単音(E4)モーラ本体
    e4 = json.load(open(E4_MAN)); e4ak = json.load(open(E4_AK))
    id2char = {k.split("|")[1]: v["char"] for k, v in e4ak.items()}
    iso = {}
    for s in e4["stimuli"]:
        ch = id2char[s["id"]]
        dst = os.path.join(tmp, f"iso_{ord(ch)}.wav")
        a, sr = sf.read(os.path.join(E4_DIR, s["file"]))
        if a.ndim > 1:
            a = a[:, 0]
        if write_seg(a, sr, s["char_onset_s"], s["char_dur_s"], dst):
            iso[ch] = dst

    # 上昇版プール(本番salt)の id とメタ
    tc = {s["id"]: s for s in json.load(open(TC_MAN))["stimuli"]}
    salt = b2.load_salt()

    chars = list(ic.AUDIO_ALL)
    offsets = [3, 11, 19, 29, 41, 53, 61, 67]      # 決定的に散らした先行文字

    # base_q と各かなの素モーラ
    base_q = None; moras = {}
    for k in chars:
        q = json.loads(b2.post("/audio_query", {"text": b2.to_kata(k), "speaker": b2.SPEAKER}))
        moras[k] = q["accent_phrases"][0]["moras"][0]
        if base_q is None:
            base_q = q

    flat_seg = os.path.join(tmp, "flat.wav")
    recs = []          # (c1, c2, mcd_rising, mcd_flat)
    n = skip = 0
    for ci, c2 in enumerate(chars):
        if c2 not in iso:
            continue
        for off in offsets:
            c1 = chars[(ci + off) % len(chars)]
            # 上昇版 C2 (コミット済みプールから)
            sid = hashlib.sha1(f"{salt}|{c1}{c2}|b3e4|{b2.SPEAKER}".encode()).hexdigest()[:20]
            meta = tc.get(sid)
            if meta is None:
                skip += 1; continue
            ra, rsr = sf.read(os.path.join(TC_DIR, meta["file"]))
            if ra.ndim > 1:
                ra = ra[:, 0]
            rise_seg = os.path.join(tmp, "rise.wav")
            if not write_seg(ra, rsr, meta["c2_onset_s"], meta["c2_dur_s"], rise_seg):
                skip += 1; continue
            # 平坦 E4→E4 を合成して C2 を切り出す
            q, m1, m2 = b2.build_query(moras[c1], moras[c2], base_q, P_E4, P_E4)
            wav = b2.post("/synthesis", {"speaker": b2.SPEAKER}, q)
            a, sr = wav_bytes_to_arr(wav)
            c2_onset = q["prePhonemeLength"] + (m1.get("consonant_length") or 0) + m1["vowel_length"]
            c2_dur = (m2.get("consonant_length") or 0) + m2["vowel_length"]
            if not write_seg(a, sr, c2_onset, c2_dur, flat_seg):
                skip += 1; continue
            try:
                mr = float(mcd_dtw.calculate_mcd(iso[c2], rise_seg))
                mf = float(mcd_dtw.calculate_mcd(iso[c2], flat_seg))
            except Exception:
                skip += 1; continue
            recs.append((c1, c2, mr, mf))
            n += 1
            if n % 100 == 0:
                print(f"  ...{n} (skip {skip})", file=sys.stderr, flush=True)

    def stats(xs):
        xs = sorted(xs)
        if not xs:
            return None
        return dict(n=len(xs), mean=round(statistics.mean(xs), 3),
                    median=round(statistics.median(xs), 3))

    rising = [r[2] for r in recs]; flat = [r[3] for r in recs]
    diff = [r[2] - r[3] for r in recs]
    per_class = {}
    for c1, c2, mr, mf in recs:
        per_class.setdefault(CLASS.get(c2, "その他"), []).append(mr - mf)

    result = dict(
        method="上昇B3→E4 vs 平坦E4→E4 の C2 を、単音E4 と MCD+DTW で比較(サンプル576対)",
        n_pairs=len(recs), n_skip=skip,
        mcd_rising=stats(rising), mcd_flat=stats(flat),
        rise_contribution_diff=stats(diff),
        diff_by_class={k: round(statistics.mean(v), 3)
                       for k, v in sorted(per_class.items(), key=lambda kv: -statistics.mean(kv[1]))},
    )
    json.dump(result, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"完了: {len(recs)}対 (skip {skip}) -> {OUT}", file=sys.stderr)
    print("上昇版乖離:", result["mcd_rising"], "/ 平坦版乖離:", result["mcd_flat"], file=sys.stderr)
    print("上昇輪郭の寄与(差):", result["rise_contribution_diff"], file=sys.stderr)


if __name__ == "__main__":
    main()
