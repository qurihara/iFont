"""iFont: テキスト・音階・速度から、字幕と音声再生が同期した動画を出力する CLI。

例:
    ifont-render --text "ちはやふる" --pitch E4 --speed 5 --rise --out out.mp4

字幕は、各文字の音が流れる区間の中で、文字単位の視聴覚対応 g（gmodel）に従って
fade で立ち上がる。音声は既定でトーン合成（音階=pitch）、--engine voicevox で TTS。
"""
import argparse
import os
import tempfile

from . import audio, render, video
from .credits import CREDITS

DEFAULT_FONT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "fonts", "BIZUDGothic-Regular.ttf"))


def build(text, pitch="E4", speed=5.0, out="out.mp4", engine="tones",
          rise=False, fps=30, font=None, keep_frames=False):
    """動画を生成して out のパスを返す。"""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        raise ValueError("text が空です。")
    font = font or DEFAULT_FONT
    if not os.path.exists(font):
        raise FileNotFoundError(f"フォントが見つからない: {font}")
    char_dur = 1.0 / float(speed)          # 1文字あたり秒
    pitch_hz = audio.note_to_hz(pitch)

    work = tempfile.mkdtemp(prefix="ifont_")
    frames_dir = os.path.join(work, "frames")
    wav_path = os.path.join(work, "audio.wav")

    # --- 音声 ---
    used_engine = engine
    if engine == "voicevox":
        try:
            wav_bytes = audio.synth_voicevox(text, speed=1.0)
            with open(wav_path, "wb") as f:
                f.write(wav_bytes)
        except Exception as e:
            print(f"[warn] VOICEVOX を使えませんでした({e})。トーン合成に切り替えます。")
            used_engine = "tones"
    if used_engine == "tones":
        samples, sr = audio.synth_tones(len(chars), pitch_hz, char_dur, rise=rise)
        audio.write_wav(samples, sr, wav_path)

    # --- 字幕フレーム ---
    frames, dur = render.render_frames(chars, char_dur, frames_dir, font, fps=fps)

    # 音声を映像長にそろえる（末尾の静止＝全文字が読める区間を残す）
    audio.pad_wav_to(wav_path, dur)

    # --- 多重化 ---
    out = os.path.abspath(out)
    video.mux(frames_dir, wav_path, out, fps=fps)

    if not keep_frames:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    return out, used_engine, dur


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ifont-render", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", required=True, help="字幕・読み上げるテキスト（かな推奨）")
    ap.add_argument("--pitch", default="E4", help="音階名(例 E4, B3, A#4)または周波数[Hz]")
    ap.add_argument("--speed", type=float, default=5.0, help="1秒あたりの文字数（既定5=0.2秒/文字）")
    ap.add_argument("--out", default="out.mp4", help="出力mp4のパス")
    ap.add_argument("--engine", choices=["tones", "voicevox"], default="tones",
                    help="音声エンジン。tones=自己完結のトーン合成 / voicevox=ローカルTTS(要エンジン)")
    ap.add_argument("--rise", action="store_true",
                    help="競技かるた風に1→2文字目で音高を上げる(完全4度)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--font", default=None, help="TrueTypeフォントのパス(既定 BIZ UDGothic)")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args(argv)

    out, used_engine, dur = build(
        args.text, pitch=args.pitch, speed=args.speed, out=args.out,
        engine=args.engine, rise=args.rise, fps=args.fps, font=args.font,
        keep_frames=args.keep_frames)
    print(f"出力: {out}  ({dur:.1f}s, 音声={used_engine})")
    print(CREDITS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
