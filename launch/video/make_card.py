#!/usr/bin/env python3
"""Render a full-screen 1920x1080 title/close card as a PNG (Pillow, no ffmpeg drawtext --
see make_caption.py's docstring for why). ffmpeg loops the resulting static image to build
the title/close segments.

Usage: python3 make_card.py output.png --line "Big title" --sub "Subtitle line" \
           --sub "Another subtitle line" --accent "accent line"
"""

from __future__ import annotations

import argparse

from PIL import Image, ImageDraw, ImageFont

CANVAS_W, CANVAS_H = 1920, 1080
BG_COLOR = (9, 11, 16)
TITLE_COLOR = (240, 244, 248)
SUB_COLOR = (168, 178, 196)
ACCENT_COLOR = (94, 234, 212)
TITLE_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
SUB_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"
MONO_FONT_PATH = "/System/Library/Fonts/Menlo.ttc"


def _centered_text(
    draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.FreeTypeFont, fill
):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    x = (CANVAS_W - w) // 2
    draw.text((x, y), text, font=font, fill=fill)
    return bbox[3] - bbox[1]


def make_card(
    out_path: str,
    title: str,
    subs: list[str],
    accent: str | None,
) -> None:
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Faint accent rule above the title -- a small deliberate design touch rather than a
    # plain centered block of text on a flat background.
    rule_w, rule_y = 160, CANVAS_H // 2 - 150
    draw.rectangle(
        (CANVAS_W // 2 - rule_w // 2, rule_y, CANVAS_W // 2 + rule_w // 2, rule_y + 4),
        fill=ACCENT_COLOR,
    )

    title_font = ImageFont.truetype(TITLE_FONT_PATH, 108)
    y = rule_y + 40
    y += _centered_text(draw, y, title, title_font, TITLE_COLOR) + 36

    sub_font = ImageFont.truetype(SUB_FONT_PATH, 40)
    for line in subs:
        y += _centered_text(draw, y, line, sub_font, SUB_COLOR) + 18

    if accent:
        y += 20
        mono_font = ImageFont.truetype(MONO_FONT_PATH, 34)
        _centered_text(draw, y, accent, mono_font, ACCENT_COLOR)

    img.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_path")
    parser.add_argument("--line", required=True, help="the big title line")
    parser.add_argument("--sub", action="append", default=[], help="a subtitle line (repeatable)")
    parser.add_argument("--accent", default=None, help="a monospace accent line (e.g. a URL)")
    args = parser.parse_args()
    make_card(args.out_path, args.line, args.sub, args.accent)


if __name__ == "__main__":
    main()
