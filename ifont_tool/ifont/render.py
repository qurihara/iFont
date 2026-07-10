"""字幕フレームの描画。

各文字は、その文字の音が流れる区間の中で、g（gmodel）が定めるスケジュールに従って
0→1 に fade で立ち上がる（時間ゲート提示）。読み終えた文字はそのまま表示され続ける。
音声と同じ時点で同じだけ「見えて」いくことを狙う、インクルーシブ字幕の中核描画である。
"""
import os
from PIL import Image, ImageDraw, ImageFont
from . import gmodel

BG = (16, 19, 26)
FG = (240, 243, 250)


def render_frames(chars, char_dur, out_dir, font_path,
                  fps=30, width=1280, height=360, tail=0.6):
    os.makedirs(out_dir, exist_ok=True)
    n = len(chars)
    total = n * char_dur
    total_frames = int(round((total + tail) * fps))

    # フォントサイズを字数に合わせて決める（横1列で収まるように）
    fontsize = 150
    font = ImageFont.truetype(font_path, fontsize)
    while _line_width(font, chars) > width * 0.9 and fontsize > 40:
        fontsize -= 6
        font = ImageFont.truetype(font_path, fontsize)

    widths = [_char_w(font, c) for c in chars]
    gap = int(fontsize * 0.06)
    line_w = sum(widths) + gap * (n - 1)
    x0 = (width - line_w) // 2
    asc, desc = font.getmetrics()
    y = (height - (asc + desc)) // 2

    paths = []
    for fi in range(total_frames):
        t = fi / fps
        img = Image.new("RGBA", (width, height), BG + (255,))
        draw = ImageDraw.Draw(img)
        x = x0
        for i, c in enumerate(chars):
            local = (t - i * char_dur) / char_dur
            if local <= 0:
                opacity = 0.0
            elif local >= 1:
                opacity = 1.0
            else:
                opacity = gmodel.reveal_opacity(c, local)
            a = int(255 * opacity)
            if a > 0:
                draw.text((x, y), c, font=font, fill=FG + (a,))
            x += widths[i] + gap
        p = os.path.join(out_dir, f"f{fi:05d}.png")
        img.convert("RGB").save(p)
        paths.append(p)
    return paths, total + tail


def _char_w(font, c):
    box = font.getbbox(c)
    return max(box[2] - box[0], int(font.size * 0.4))


def _line_width(font, chars):
    gap = int(font.size * 0.06)
    return sum(_char_w(font, c) for c in chars) + gap * (len(chars) - 1)
