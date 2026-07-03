"""build_2char_pool.py を、ffmpeg 呼び出しの一時的失敗(ENOENT等)にリトライ耐性を
付けて実行するラッパー。コミット済みスクリプトは変更しない。"""
import sys, os, time, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import build_2char_pool as b2

_orig = b2.wav_to_mp3
def robust_wav_to_mp3(wav_bytes):
    last = None
    for attempt in range(6):
        try:
            return _orig(wav_bytes)
        except (FileNotFoundError, OSError) as ex:
            last = ex
            print(f"  [retry] ffmpeg一時失敗 attempt={attempt} {ex!r}", file=sys.stderr, flush=True)
            time.sleep(0.5 * (attempt + 1))
    raise last
b2.wav_to_mp3 = robust_wav_to_mp3
b2.main()
