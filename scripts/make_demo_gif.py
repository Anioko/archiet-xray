"""Render the README demo GIF deterministically — no screen capture.

Draws a dark terminal window and animates the real X-Ray session (typed
commands, output revealed line by line). Same input, same GIF — in the same
spirit as the tool itself. Dev-only; requires Pillow.

    py scripts/make_demo_gif.py   # writes demo.gif at repo root
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 880, 560
PAD_X, PAD_TOP = 28, 64
LINE_H = 26
BG = (13, 17, 23)        # GitHub dark
CHROME = (33, 38, 45)
FG = (201, 209, 217)
DIM = (139, 148, 158)
GREEN = (63, 185, 80)
CYAN = (121, 192, 255)
AMBER = (210, 153, 34)
WHITE = (240, 246, 252)

FONT_PATH = "C:/Windows/Fonts/CascadiaMono.ttf"
FONT = ImageFont.truetype(FONT_PATH, 17)
FONT_BOLD = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 17)

# (text, color, bold) — the real session, output text verbatim from a run.
SCRIPT: list[tuple[str, str]] = [
    ("$ pip install archiet-xray", "cmd"),
    ("$ archiet-xray .", "cmd"),
    ("Archiet X-Ray v0.1.1 — microblog", "title"),
    ("  visibility score : 78/100", "score"),
    ("  code files       : 34 (34 read, 5 with elements)", "out"),
    ("  routes           : 27   (21 auth-guarded, 6 public)", "out"),
    ("  entities         : 5    (User, Post, Message, …)", "out"),
    ("  findings         : 0", "out"),
    ("  wrote            : .archiet/ARCHITECTURE.md", "out"),
    ("                     .archiet/AGENT_CONTEXT.md", "out"),
    ("                     .archiet/architecture.json", "out"),
    ("", "out"),
    ("$ claude mcp add archiet-xray -- python mcp_server.py .", "cmd"),
    ("Added stdio MCP server archiet-xray", "out"),
    ("", "out"),
    ("# your agent now asks blast_radius before it edits", "final"),
]

COLORS = {"cmd": WHITE, "out": DIM, "title": CYAN, "score": AMBER, "final": GREEN}


def base_frame() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, 40], radius=0, fill=CHROME)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([16 + i * 26, 14, 28 + i * 26, 26], fill=c)
    d.text((W // 2 - 60, 11), "archiet-xray", font=FONT, fill=DIM)
    return img


def draw_lines(lines: list[tuple[str, str]], cursor: bool = False) -> Image.Image:
    img = base_frame()
    d = ImageDraw.Draw(img)
    y = PAD_TOP
    for text, kind in lines:
        font = FONT_BOLD if kind in {"title", "score", "final"} else FONT
        if kind == "cmd" and text.startswith("$ "):
            d.text((PAD_X, y), "$ ", font=FONT_BOLD, fill=GREEN)
            d.text((PAD_X + 22, y), text[2:], font=font, fill=COLORS[kind])
        else:
            d.text((PAD_X, y), text, font=font, fill=COLORS.get(kind, FG))
        y += LINE_H
    if cursor:
        d.rectangle([PAD_X, y + 4, PAD_X + 10, y + 22], fill=FG)
    return img


def main() -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []
    shown: list[tuple[str, str]] = []

    frames.append(draw_lines([], cursor=True))
    durations.append(700)

    for text, kind in SCRIPT:
        if kind == "cmd":
            # type the command 4 chars at a time
            for i in range(2, len(text) + 1, 4):
                frames.append(draw_lines(shown + [(text[:i], "cmd")]))
                durations.append(55)
            shown.append((text, kind))
            frames.append(draw_lines(shown, cursor=True))
            durations.append(550)
        else:
            shown.append((text, kind))
            frames.append(draw_lines(shown))
            durations.append(360 if kind != "out" else 180)

    frames.append(draw_lines(shown))
    durations.append(4200)  # hold the final card

    out = Path(__file__).resolve().parents[1] / "demo.gif"
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
