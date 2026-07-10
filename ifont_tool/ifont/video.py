"""フレーム列と音声を ffmpeg で1本の mp4 に多重化する。"""
import os
import shutil
import subprocess


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:  # imageio-ffmpeg が入っていればそれを使う
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def mux(frames_dir, wav_path, out_path, fps=30):
    ff = find_ffmpeg()
    if ff is None:
        raise RuntimeError("ffmpeg が見つからない。brew install ffmpeg するか imageio-ffmpeg を入れてください。")
    cmd = [
        ff, "-y",
        "-framerate", str(fps), "-i", os.path.join(frames_dir, "f%05d.png"),
        "-i", wav_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", out_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path
