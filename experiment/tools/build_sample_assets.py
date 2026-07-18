#!/usr/bin/env python3
"""
出力サンプル(実声版)の素材を作る
================================
GitHub Pagesで公開する ifont_sample.html 用に、東北きりたんの実声で流暢音声を合成し、
各モーラの時刻(視覚の鮮明化を同期させる用)とともに書き出す。
単純連結モードはブラウザ側で既存の1文字プール(68音)を0.2秒間隔で鳴らすので、ここでは作らない。

表示字は原文の表記(ゐ・助詞は・づ)を保ち、音はその代表音(イ・ワ・ズ)を使う。

出力: experiment/sample_assets/<content>_fluent.mp3, experiment/sample_assets/content.json
実行: <venv>/bin/python experiment/tools/build_sample_assets.py  (VOICEVOX起動下)
"""
import json, os, sys, io, wave, math, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)
sys.path.insert(0, os.path.join(REPO, "two_char_audio"))
import build_2char_pool as b2

SPK = 108
OUT = os.path.join(EXP, "sample_assets")

# 各モーラ: (表示字, 音のかな[68音プールの代表音], 文脈で埋もれやすさ ctx, 見どころ badge)
def m(disp, sound, ctx=0.0, badge=None):
    return dict(disp=disp, sound=sound, ctx=ctx, badge=badge)

WAKA = dict(
    key="waka",
    title="（1）百人一首・和歌を1首",
    sub="在原業平「ちはやぶる…」（百人一首17番）。百人一首パックは手検証した読み表を用いる。",
    src="ちはやぶる神代も聞かず竜田川からくれなゐに水くくるとは",
    morae=[
        m("ち","ち"), m("は","は"), m("や","や"), m("ぶ","ぶ"), m("る","る"),
        m("か","か"), m("み","み"), m("よ","よ"), m("も","も"), m("き","き",-0.10), m("か","か"), m("ず","ず",-0.06),
        m("た","た"), m("つ","つ",-0.20,"文脈で埋もれ→視覚が補う"), m("た","た"), m("が","が"), m("は","わ",0,"川のは／音はワ"),
        m("か","か"), m("ら","ら"), m("く","く",-0.10), m("れ","れ"), m("な","な"), m("ゐ","い",0,"古語ゐを保つ／音はイ"), m("に","に"),
        m("み","み"), m("づ","ず",0,"表記づを保つ／音はズ"), m("く","く",-0.18,"文脈で埋もれ→視覚が補う"), m("く","く",-0.08), m("る","る"), m("と","と"), m("は","わ",0,"助詞は／音はワ")],
)

QUIZ = dict(
    key="quiz",
    title="（2）クイズ問題的サンプル",
    sub="「日本で一番高い山は何？」。現代文の直接入力を想定。",
    src="日本で一番高い山は何？",
    morae=[
        m("に","に"), m("ほ","ほ"), m("ん","ん",0.08), m("で","で"),
        m("い","い"), m("ち","ち",-0.10,"文脈で埋もれ→視覚が補う"), m("ば","ば"), m("ん","ん",0.10,"文脈で読める→視覚は控えめ"),
        m("た","た"), m("か","か"), m("い","い"), m("や","や"), m("ま","ま"),
        m("は","わ",-0.06,"助詞は／音はワ"), m("な","な"), m("に","に"),
        m("？","",0,None)],
)


SLOT = 0.20   # 秒/モーラ(運用の提示速度)


def _load_1char_pool():
    """音のかな -> (mp3パス, char_onset_s, char_dur_s, acoustic_onset_ms, gain) を返す。
    本番プール(東北きりたん=cand108)の68音。"""
    man = json.load(open(os.path.join(EXP, "audio1char_manifest.json")))
    merged = json.load(open(os.path.join(EXP, "answer_key_merged.json")))
    onsets = json.load(open(os.path.join(EXP, "audio1char_onsets.json")))
    id2char = {k.split("|")[1]: v["char"] for k, v in merged.items()
               if k.startswith("audio1char|") and v.get("pool") == "cand108"}
    pool = {}
    for s in man["stimuli"]:
        ch = id2char.get(s["id"])
        if ch:
            o = onsets.get(ch, {})
            pool[ch] = (os.path.join(EXP, "audio1char_stimuli", s["file"]),
                        s["char_onset_s"], s["char_dur_s"],
                        o.get("acoustic_onset_ms", 0), o.get("gain", 1.0))
    return pool


def _decode(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-f", "wav", "pipe:1"],
                       stdout=subprocess.PIPE, check=True)
    with wave.open(io.BytesIO(r.stdout), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def render_concat(morae, pool, fr=24000):
    """各モーラの音を、本番と同じ処理(音響的開始からゲート・gain適用)で SLOT 間隔に並べる。
    製品の『単純連結』(測った単音クリップの連結)にあたる。"""
    n = len([x for x in morae])
    total = np.zeros(int((len(morae) * SLOT + 0.05) * fr))
    onsets_ms = []
    for i, x in enumerate(morae):
        onsets_ms.append(int(i * SLOT * 1000) if x["sound"] else None)
        if not x["sound"] or x["sound"] not in pool:
            continue
        path, c_on, c_dur, a_on, gain = pool[x["sound"]]
        sig, sfr = _decode(path)
        a = int((c_on + a_on / 1000) * sfr)
        avail = max(0.01, c_dur - a_on / 1000)
        dur = min(SLOT, avail)
        seg = sig[a:a + int(dur * sfr)] * gain
        nf = int(0.008 * sfr)                       # 端のクリック音を消すフェード
        if len(seg) > 2 * nf:
            seg[:nf] *= np.linspace(0, 1, nf); seg[-nf:] *= np.linspace(1, 0, nf)
        pos = int(i * SLOT * fr)
        total[pos:pos + len(seg)] += seg[:len(total) - pos]
    total = np.clip(total, -1, 1)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes((total * 32767).astype("<i2").tobytes())
    return b2.wav_to_mp3(buf.getvalue()), onsets_ms, int(len(total) / fr * 1000)


def synth_fluent(morae):
    """音のかな列を東北きりたんの連続音声(自然な韻律)で合成し、mp3と各モーラの開始時刻(ms)を返す。"""
    sound_str = "".join(x["sound"] for x in morae if x["sound"])
    q = json.loads(b2.post("/audio_query", {"text": b2.to_kata(sound_str), "speaker": SPK}))
    # 自然さのため音高・長さはVOICEVOXの既定のまま。前後余白だけ短くする。
    q["prePhonemeLength"] = 0.05
    q["postPhonemeLength"] = 0.15
    wav = b2.post("/synthesis", {"speaker": SPK}, q)
    # 各モーラの開始時刻(秒)を query の長さから積み上げる
    onsets_s = []
    t = q["prePhonemeLength"]
    for ap in q["accent_phrases"]:
        for mo in ap["moras"]:
            onsets_s.append(t)
            t += (mo.get("consonant_length") or 0) + (mo.get("vowel_length") or 0)
        if ap.get("pause_mora"):
            t += (ap["pause_mora"].get("vowel_length") or 0)
    with wave.open(io.BytesIO(wav), "rb") as w:
        total_ms = int(w.getnframes() / w.getframerate() * 1000)
    return wav, [int(round(s * 1000)) for s in onsets_s], total_ms


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        b2.get("/version")
    except Exception as e:
        sys.exit(f"VOICEVOX に接続できない: {e}")
    pool = _load_1char_pool()
    contents = {}
    for c in (WAKA, QUIZ):
        sounded = [x for x in c["morae"] if x["sound"]]
        # 単純連結(実声・0.2秒間隔)
        cc_mp3, cc_onsets, cc_total = render_concat(c["morae"], pool)
        with open(os.path.join(OUT, f"{c['key']}_concat.mp3"), "wb") as f:
            f.write(cc_mp3)
        # 流暢合成(実声・自然な韻律)
        wav, onsets_ms, total_ms = synth_fluent(c["morae"])
        if len(onsets_ms) != len(sounded):
            print(f"警告[{c['key']}]: 音モーラ{len(sounded)} と 合成モーラ{len(onsets_ms)} が不一致",
                  file=sys.stderr)
        with open(os.path.join(OUT, f"{c['key']}_fluent.mp3"), "wb") as f:
            f.write(b2.wav_to_mp3(wav))
        # 表示モーラ(？含む)に、流暢音声の各モーラ時刻を順に割り当てる(？は時刻なし)
        fl_onsets, it = [], iter(onsets_ms)
        for x in c["morae"]:
            fl_onsets.append(next(it, total_ms) if x["sound"] else None)
        contents[c["key"]] = dict(
            title=c["title"], sub=c["sub"], src=c["src"], morae=c["morae"],
            concat_file=f"sample_assets/{c['key']}_concat.mp3",
            concat_onsets_ms=cc_onsets, concat_total_ms=cc_total,
            fluent_file=f"sample_assets/{c['key']}_fluent.mp3",
            fluent_onsets_ms=fl_onsets, fluent_total_ms=total_ms,
        )
        print(f"{c['key']}: 連結{cc_total}ms / 流暢{total_ms}ms / 表示{len(c['morae'])}・音{len(sounded)}モーラ",
              file=sys.stderr)
    json.dump(dict(speaker=SPK, speaker_name="東北きりたん/ノーマル", slot_ms=200, contents=contents),
              open(os.path.join(OUT, "content.json"), "w"), ensure_ascii=False, indent=1)
    print(f"完了 -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
