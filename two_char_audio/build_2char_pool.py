#!/usr/bin/env python3
"""
2文字課題の刺激プールを生成する (作業3の続き)
==============================================
対象は「百人一首の上句に実在する、清音46字どうしの隣接かな対」。
対×条件(flat/rise)ごとに全長の音声を1つだけ作る。2文字目の時間ゲートは
再生時にブラウザ側で行う方式(pilot_audio と同じライブ切り出し)なので、
プールは 対数×2 で済む(全 frac を焼き込まない)。

出力:
- pool_2char/<hashid>.mp3        … 全長音声(C1全部 + C2全部)。ファイル名はハッシュ
- pool_2char/manifest.json       … 公開メタ。回答(C2)は含めない。
                                    各エントリに2文字目の開始時刻と長さ(クライアント側ゲート用)
- pool_2char/answer_key_2char.json … 非公開。id→{c1,c2,target,pitch_cond}。GASに貼る用
- hi_karuta_pairs.json           … 対の一覧と頻度

ファイル名のハッシュには SECRET_SALT を使う(.env か環境変数。無ければ dev 値)。
本番はテンプレートの方針どおり固定 salt で作り直す。
"""
import json, os, sys, io, math, hashlib, subprocess, collections, argparse, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
import ifont_common as ic
from make_2char_voicevox import (_post, _get, mora_dur, SEMITONE, RISE_SEMITONES,
                                 PITCH_CONDS)

ENGINE = os.environ.get("VOICEVOX_ENGINE", "http://127.0.0.1:50021")
KAM = "/Users/kurihara/Dropbox/dev/Kikiwake-tmp/mfa_v3/modern_kana_kamigoku.json"


def load_salt():
    env = os.path.join(REPO, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.strip().startswith("SECRET_SALT"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("SECRET_SALT", "dev_2char_salt")


def hi_karuta_pairs():
    """上句に実在する清音46×46の隣接対と頻度。"""
    d = json.load(open(KAM))
    kar = set(ic.AUDIO_KARUTA)
    freq = collections.Counter()
    for v in d.values():
        s = v.replace(" ", "").replace("　", "")
        for i in range(len(s) - 1):
            a, b = s[i], s[i + 1]
            if a in kar and b in kar:
                freq[(a, b)] += 1
    return freq


def cache_moras(kanas, speaker):
    """各かなを1回だけ audio_query して先頭モーラを得る。base_q も1つ取っておく。"""
    moras, base_q = {}, None
    for k in sorted(kanas):
        q = json.loads(_post("/audio_query", params={"text": k, "speaker": speaker}))
        moras[k] = q["accent_phrases"][0]["moras"][0]
        if base_q is None:
            base_q = q
    return moras, base_q


def make_query(c1, c2, moras, base_q, cond, rise_semitones):
    m1 = dict(moras[c1]); m2 = dict(moras[c2])
    base = m1["pitch"] if m1["pitch"] > 0 else (m2["pitch"] if m2["pitch"] > 0 else 4.7)
    delta = rise_semitones * SEMITONE
    m1["pitch"] = base
    m2["pitch"] = base if cond == "flat" else base + delta
    q = dict(base_q)
    q["accent_phrases"] = [{"moras": [m1, m2], "accent": 2,
                            "pause_mora": None, "is_interrogative": False}]
    for k, v in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0,
                     volumeScale=1.0, prePhonemeLength=0.1, postPhonemeLength=0.1).items():
        q[k] = v
    return q, m1, m2


def wav_to_mp3(wav_bytes):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", "pipe:0", "-codec:a", "libmp3lame", "-q:a", "4",
                        "-f", "mp3", "pipe:1"],
                       input=wav_bytes, stdout=subprocess.PIPE, check=True)
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", type=int, default=11)
    ap.add_argument("--rise", type=float, default=RISE_SEMITONES)
    ap.add_argument("--out", default=os.path.join(HERE, "pool_2char"))
    ap.add_argument("--format", choices=["mp3", "wav"], default="mp3")
    ap.add_argument("--limit", type=int, default=None, help="先頭N対だけ(動作確認用)")
    args = ap.parse_args()

    try:
        ver = _get("/version")
    except Exception as e:
        sys.exit(f"VOICEVOX エンジンに接続できない({ENGINE}): {e}")
    print(f"VOICEVOX {ver} / speaker={args.speaker} / rise={args.rise}半音", file=sys.stderr)

    freq = hi_karuta_pairs()
    pairs = [p for p, _ in freq.most_common()]
    if args.limit:
        pairs = pairs[:args.limit]
    json.dump({"".join(p): c for p, c in freq.most_common()},
              open(os.path.join(HERE, "hi_karuta_pairs.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"対 {len(pairs)} 種 × 条件 {len(PITCH_CONDS)} = {len(pairs)*len(PITCH_CONDS)} 音声を生成",
          file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    salt = load_salt()
    kanas = set(a for a, b in pairs) | set(b for a, b in pairs)
    moras, base_q = cache_moras(kanas, args.speaker)

    manifest, answer_key = [], {}
    n = 0
    for (c1, c2) in pairs:
        for cond in PITCH_CONDS:
            q, m1, m2 = make_query(c1, c2, moras, base_q, cond, args.rise)
            wav = _post("/synthesis", params={"speaker": args.speaker}, body=q)
            c2_onset = q["prePhonemeLength"] + mora_dur(m1)
            c2_dur = mora_dur(m2)
            raw = wav_to_mp3(wav) if args.format == "mp3" else wav
            ext = args.format
            sid = hashlib.sha1(f"{salt}|{c1}{c2}|{cond}|{args.speaker}".encode()).hexdigest()[:20]
            fn = f"{sid}.{ext}"
            with open(os.path.join(args.out, fn), "wb") as f:
                f.write(raw)
            # 公開manifest(回答C2は含めない。timingはクライアント側ゲート用)
            manifest.append(dict(
                id=sid, file=fn, pitch_cond=cond,
                rise_semitones=(0.0 if cond == "flat" else args.rise),
                c2_onset_s=round(c2_onset, 4), c2_dur_s=round(c2_dur, 4),
                sr=q.get("outputSamplingRate", 24000),
                freq=freq[(c1, c2)], q_set="karuta", modality="audio2char",
            ))
            # 非公開answer_key
            answer_key["audio2char|" + sid] = dict(c1=c1, c2=c2, target=c2, pitch_cond=cond)
            n += 1
            if n % 200 == 0:
                print(f"  ...{n}", file=sys.stderr)

    json.dump(manifest, open(os.path.join(args.out, "manifest.json"), "w"),
              ensure_ascii=False, indent=1)
    json.dump(answer_key, open(os.path.join(args.out, "answer_key_2char.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"完了: {n} 音声 / manifest {len(manifest)} / answer_key {len(answer_key)} -> {args.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
