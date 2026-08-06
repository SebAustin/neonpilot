#!/usr/bin/env python3
"""Render a burned-in caption as a transparent 1920x1080 PNG.

The project's ffmpeg build has no drawtext/libass support (Homebrew's default `ffmpeg`
formula ships without freetype/fontconfig), so captions are rendered here with Pillow and
composited onto video with ffmpeg's `overlay` filter instead -- no text rendering happens
inside ffmpeg at all, sidestepping that gap entirely.

Usage: python3 make_caption.py "Caption text" output.png [--top]
"""

from __future__ import annotations

import argparse
import textwrap

from PIL import Image, ImageDraw, ImageFont

CANVAS_W, CANVAS_H = 1920, 1080
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_SIZE = 38
LINE_SPACING = 12
WRAP_CHARS = 66
BOX_PAD_X = 44
BOX_PAD_Y = 26
MARGIN_BOTTOM = 70
MARGIN_TOP = 60
BOX_COLOR = (10, 12, 18, 216)
TEXT_COLOR = (240, 244, 248, 255)
ACCENT_COLOR = (94, 234, 212, 255)  # matches the Dracula-adjacent terminal accent


def render_caption(text: str, out_path: str, *, top: bool = False, accent: bool = False) -> None:
    """Render `text` as a lower-third (or upper-third, if `top`) caption card."""
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    lines = textwrap.wrap(text, width=WRAP_CHARS) or [text]
    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    text_block_h = sum(line_heights) + LINE_SPACING * (len(lines) - 1)
    box_w = max(line_widths) + BOX_PAD_X * 2
    box_h = text_block_h + BOX_PAD_Y * 2
    box_x0 = (CANVAS_W - box_w) // 2
    box_y0 = MARGIN_TOP if top else CANVAS_H - MARGIN_BOTTOM - box_h
    box_y1 = box_y0 + box_h

    draw.rounded_rectangle((box_x0, box_y0, box_x0 + box_w, box_y1), radius=14, fill=BOX_COLOR)

    color = ACCENT_COLOR if accent else TEXT_COLOR
    y = box_y0 + BOX_PAD_Y
    for line, lh in zip(lines, line_heights, strict=True):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (CANVAS_W - lw) // 2
        draw.text((x, y), line, font=font, fill=color)
        y += lh + LINE_SPACING

    img.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text")
    parser.add_argument("out_path")
    parser.add_argument("--top", action="store_true", help="place caption in the upper third")
    parser.add_argument(
        "--accent", action="store_true", help="use the accent color instead of plain white"
    )
    args = parser.parse_args()
    render_caption(args.text, args.out_path, top=args.top, accent=args.accent)


if __name__ == "__main__":
    main()
