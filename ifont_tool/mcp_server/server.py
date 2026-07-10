"""iFont の MCP サーバ（LLM からインクルーシブ字幕動画を生成させる）。

前提: `pip install mcp` と、同梱の ifont パッケージ（pip install -e .. など）。
起動:  python mcp_server/server.py     # stdio トランスポート

MCP クライアント(例: Claude Desktop / Claude Code)の設定に、このサーバを
コマンド `python /path/to/ifont_tool/mcp_server/server.py` として登録すると、
`render_inclusive_caption` ツールが使えるようになる。
"""
import os
import sys

# 同梱の ifont を import できるように、親ディレクトリ(ifont_tool)を通す
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP  # noqa: E402  要 `pip install mcp`
from ifont.cli import build  # noqa: E402

mcp = FastMCP("ifont")


@mcp.tool()
def render_inclusive_caption(
    text: str,
    pitch: str = "E4",
    speed: float = 5.0,
    out: str = "out.mp4",
    engine: str = "tones",
    rise: bool = False,
) -> str:
    """テキスト・音階・速度から、字幕と音声が同期した動画(mp4)を生成する。

    Args:
        text: 字幕・読み上げるテキスト（かな推奨）
        pitch: 音階名(例 'E4','B3','A#4')または周波数[Hz]。カンマ区切りで1文字ごとに指定可(例 'B3,E4,G4')。1つだけなら全文字に適用
        speed: 1秒あたりの文字数（既定5=0.2秒/文字）
        out: 出力mp4のパス
        engine: 'tones'(自己完結のトーン合成) か 'voicevox'(ローカルTTS, 要エンジン)
        rise: 競技かるた風に1→2文字目で音高を上げる(完全4度)
    Returns:
        生成した動画のパスと概要
    """
    path, used, dur = build(text, pitch=pitch, speed=speed, out=out,
                            engine=engine, rise=rise)
    return f"生成: {path}（{dur:.1f}秒, 音声={used}）。配布時は BIZ UDGothic(OFL) と、VOICEVOX使用時は話者クレジットを明記。"


if __name__ == "__main__":
    mcp.run()
