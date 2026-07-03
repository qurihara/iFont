#!/usr/bin/env python3
"""
1文字課題の刺激プール生成 (2文字課題の C1=∅ 特殊ケース)
========================================================
統一モデルの「単音課題 = 先行文脈なし(発話先頭)」にあたる。全72字(音声で区別可能な
かな)を、発話先頭の音高 B3 (246.94Hz)・1文字0.2秒で合成する。時間ゲート(truncation)は
再生時にブラウザ側で行うので、プールは 72 ファイルで済む。

build_2char_pool.py の関数を再利用する。実行は parselmouth の入った venv で:
  bigram_coverage/.venv/bin/python two_char_audio/build_1char_pool.py

出力:
- experiment/audio1char_stimuli/<hash>.mp3   1文字の合成音声(前後余白つき)
- experiment/audio1char_manifest.json        公開メタ(回答なし。文字の開始時刻と長さ=ゲート用)
- experiment/answer_key_1char.json           非公開(char/target/実測F0)。GASに貼る用
"""
import json, os, sys, math, hashlib, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_2char_pool as b2
sys.path.insert(0, b2.REPO)
import ifont_common as ic

B3 = b2.B3
MORA_DUR = b2.MORA_DUR
REPO = b2.REPO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", type=int, default=b2.SPEAKER)
    ap.add_argument("--out", default=os.path.join(REPO, "experiment", "audio1char_stimuli"))
    ap.add_argument("--manifest", default=os.path.join(REPO, "experiment", "audio1char_manifest.json"))
    ap.add_argument("--answerkey", default=os.path.join(REPO, "experiment", "answer_key_1char.json"))
    args = ap.parse_args()

    ver = b2.get("/version")
    chars = list(ic.AUDIO_ALL)
    print(f"VOICEVOX {ver} / speaker={args.speaker} / {len(chars)}字 / "
          f"B3={B3}Hz / 1モーラ{MORA_DUR}s", file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    salt = b2.load_salt()
    p_base = math.log(B3)

    # 各かなの素のモーラと base_q を取得
    moras, base_q = {}, None
    for k in chars:
        q = json.loads(b2.post("/audio_query", {"text": k, "speaker": args.speaker}))
        moras[k] = q["accent_phrases"][0]["moras"][0]
        if base_q is None:
            base_q = q

    manifest, answer_key = [], {}
    n_corrected = 0
    for ch in chars:
        # 1モーラだけのクエリ (C2 側に同じモーラを置き、accent_phrases を1モーラに)
        m = b2.set_mora(moras[ch], p_base, MORA_DUR)
        q = dict(base_q)
        q["accent_phrases"] = [{"moras": [m], "accent": 1,
                                "pause_mora": None, "is_interrogative": False}]
        for kk, vv in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0,
                           volumeScale=1.0, prePhonemeLength=0.1, postPhonemeLength=0.1).items():
            q[kk] = vv
        wav = b2.post("/synthesis", {"speaker": args.speaker}, q)
        # 1モーラ版の実測: 母音の定常部で測る
        onset = q["prePhonemeLength"] + (m.get("consonant_length") or 0)
        f0 = b2.med_f0(wav, onset + 0.03, onset + m["vowel_length"] - 0.02)
        e = b2.cents(f0, B3) if f0 and not math.isnan(f0) else float("nan")
        corrected = False
        if not math.isnan(e) and abs(e) > b2.CORRECT_CENTS:
            adj = p_base + (math.log(B3) - math.log(f0))
            m = b2.set_mora(moras[ch], adj, MORA_DUR)
            q["accent_phrases"][0]["moras"] = [m]
            wav = b2.post("/synthesis", {"speaker": args.speaker}, q)
            onset = q["prePhonemeLength"] + (m.get("consonant_length") or 0)
            f0 = b2.med_f0(wav, onset + 0.03, onset + m["vowel_length"] - 0.02)
            corrected = True
            n_corrected += 1
        char_onset = q["prePhonemeLength"]                       # 前余白の直後 = 文字の開始
        char_dur = (m.get("consonant_length") or 0) + m["vowel_length"]
        sid = hashlib.sha1(f"{salt}|{ch}|b3-1char|{args.speaker}".encode()).hexdigest()[:20]
        with open(os.path.join(args.out, sid + ".mp3"), "wb") as f:
            f.write(b2.wav_to_mp3(wav))
        manifest.append(dict(
            id=sid, file=sid + ".mp3",
            char_onset_s=round(char_onset, 4), char_dur_s=round(char_dur, 4),
            sr=q.get("outputSamplingRate", 24000),
            q_set="all", modality="audio1char",
        ))
        answer_key["audio1char|" + sid] = dict(
            char=ch, target=ch,
            f0_hz=(round(f0, 1) if f0 and not math.isnan(f0) else None),
            corrected=corrected,
        )

    pub = dict(modality="audio1char", q_set="all", speaker=args.speaker,
               pitch_scheme="B3", mora_dur_s=MORA_DUR,
               count=len(manifest), stimuli=manifest)
    json.dump(pub, open(args.manifest, "w"), ensure_ascii=False, indent=1)
    json.dump(answer_key, open(args.answerkey, "w"), ensure_ascii=False, indent=1)
    print(f"完了: {len(manifest)} 音声 (補正 {n_corrected}) -> {args.out}", file=sys.stderr)
    print(f"  manifest {args.manifest} / answer_key {args.answerkey}", file=sys.stderr)


if __name__ == "__main__":
    main()
