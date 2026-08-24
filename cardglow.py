#!/usr/bin/env python3
"""
cardglow — Turn any logo (PNG / GIF / SVG, square or rectangular)
into a clean, GitHub-OG-card-style social preview image.

Given a logo, this:
  1. Loads it (rasterizing SVG at high resolution if needed).
  2. Auto-crops transparent/empty margins, so rectangular or
     off-center source art is re-centered correctly.
  3. Extracts the logo's dominant color to tint the background glow,
     so every generated card automatically matches its source logo
     with no manual color picking.
  4. Composites it onto a dark card: an angled gradient background
     (dithered to avoid banding), subtle dot grid, soft color-matched
     glow, vignette, and a drop shadow under the logo — matching the
     "opengraph.githubassets.com" aesthetic.
  5. Writes a PNG at the requested size (default 1200x630, the
     standard og:image / Twitter-card size).

Usage:
    cardglow logo.png
    cardglow logo.svg -o card.png
    cardglow logo.gif --icon-size 340 --size 1200x630
    cardglow logo.png --glow "#ff3355"          # force glow color
    cardglow logo.png --gradient-angle 135      # GitHub-style diagonal
    cardglow logo.png --no-grid --no-vignette

Requirements:
    pip install pillow cairosvg numpy
    (cairosvg is only needed if you pass .svg files)
"""

import argparse
import io
import os
import sys
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------

def load_source_image(path: str, svg_render_px: int = 1000) -> Image.Image:
    """Load a PNG, GIF (first frame), or SVG (rasterized) as RGBA."""
    ext = os.path.splitext(path)[1].lower()

    if ext == ".svg":
        try:
            import cairosvg
        except ImportError:
            sys.exit(
                "SVG input requires cairosvg. Install it with:\n"
                "    pip install cairosvg"
            )
        png_bytes = cairosvg.svg2png(
            url=path, output_width=svg_render_px, output_height=svg_render_px
        )
        return Image.open(io.BytesIO(png_bytes)).convert("RGBA")

    im = Image.open(path)
    if getattr(im, "is_animated", False):  # GIF: use first frame
        im.seek(0)
    return im.convert("RGBA")


def autocrop_transparent(im: Image.Image, pad_ratio: float = 0.04) -> Image.Image:
    """Crop fully-transparent margins so the logo's actual content is
    tightly framed before we resize it. If the source has no useful
    transparency (e.g. a flat, fully-opaque rectangular PNG/GIF),
    it's returned unchanged — nothing meaningful to crop."""
    alpha = im.split()[-1]
    bbox = alpha.getbbox()

    if not bbox or bbox == (0, 0, im.width, im.height):
        return im

    w, h = im.size
    pad_x = int((bbox[2] - bbox[0]) * pad_ratio)
    pad_y = int((bbox[3] - bbox[1]) * pad_ratio)
    left = max(0, bbox[0] - pad_x)
    top = max(0, bbox[1] - pad_y)
    right = min(w, bbox[2] + pad_x)
    bottom = min(h, bbox[3] + pad_y)
    return im.crop((left, top, right, bottom))


# ----------------------------------------------------------------------
# Dominant color extraction (no extra dependency)
# ----------------------------------------------------------------------

def dominant_color(im: Image.Image) -> tuple:
    """Cheap dominant-color estimate: downsample, quantize to a small
    palette, skip near-white/near-black/transparent pixels, return the
    most common remaining color. Good enough to auto-tint a glow."""
    small = im.copy()
    small.thumbnail((80, 80))
    small = small.convert("RGBA")

    counts = {}
    px = small.load()
    for yy in range(small.height):
        for xx in range(small.width):
            r, g, b, a = px[xx, yy]
            if a < 60:
                continue
            # skip near-white / near-black / low-saturation grays
            mx, mn = max(r, g, b), min(r, g, b)
            sat = (mx - mn)
            if mx > 235 and sat < 25:
                continue
            if mx < 25:
                continue
            key = (r // 16 * 16, g // 16 * 16, b // 16 * 16)
            counts[key] = counts.get(key, 0) + 1

    if not counts:
        return (90, 140, 220)  # neutral blue fallback

    return max(counts.items(), key=lambda kv: kv[1])[0]


def hex_to_rgb(s: str) -> tuple:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


# ----------------------------------------------------------------------
# Angled linear gradient (CSS linear-gradient()-style angle convention:
# 0deg = to top, 90deg = to right, 180deg = to bottom, 270deg = to left.
# The first color sits at the start of the gradient line, the second
# at the end — e.g. 180deg (the old default) is a plain top→bottom
# split; 135deg gives a GitHub-style bottom-left → top-right diagonal.)
# ----------------------------------------------------------------------

def linear_gradient(
    w: int, h: int, angle_deg: float, color1: tuple, color2: tuple,
    dither: bool = True, dither_strength: float = 1.0, seed: int = 0,
) -> Image.Image:
    angle_rad = math.radians(angle_deg)
    dx = math.sin(angle_rad)
    dy = -math.cos(angle_rad)  # image y grows downward; CSS 0deg points up

    xs = np.arange(w) - (w - 1) / 2.0
    ys = np.arange(h) - (h - 1) / 2.0
    X, Y = np.meshgrid(xs, ys)
    proj = X * dx + Y * dy

    p_min, p_max = proj.min(), proj.max()
    span = p_max - p_min
    t = (proj - p_min) / span if span else np.zeros_like(proj)

    c1 = np.array(color1, dtype=np.float32)
    c2 = np.array(color2, dtype=np.float32)
    rgb = c1[None, None, :] + (c2 - c1)[None, None, :] * t[:, :, None]

    if dither:
        # Narrow-range gradients (e.g. white -> light gray) only span a
        # handful of distinct 8-bit values across the whole image, which
        # rounds into visible banded steps. Small per-pixel random noise
        # before quantizing breaks that up into imperceptible grain
        # instead of visible bands, at no cost to the overall look.
        rng = np.random.default_rng(seed)
        noise = rng.uniform(-0.5, 0.5, size=rgb.shape) * dither_strength
        rgb = rgb + noise

    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    return Image.fromarray(rgb, mode="RGB")


# ----------------------------------------------------------------------
# Card rendering
# ----------------------------------------------------------------------

def make_card(
    logo: Image.Image,
    width: int = 1200,
    height: int = 630,
    icon_max: int = 300,
    bg_top: tuple = (13, 17, 23),
    bg_bottom: tuple = (9, 11, 15),
    gradient_angle: float = 180.0,
    dither: bool = True,
    dither_strength: float = 1.0,
    glow_rgb: tuple = None,
    draw_grid: bool = True,
    draw_vignette: bool = True,
) -> Image.Image:
    W, H = width, height
    cx, cy = W // 2, H // 2 - int(H * 0.032)

    # base gradient — angled per CSS linear-gradient() convention
    base = linear_gradient(
        W, H, gradient_angle, bg_top, bg_bottom,
        dither=dither, dither_strength=dither_strength,
    ).convert("RGBA")

    # dot grid
    if draw_grid:
        dot_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dot_layer)
        spacing = max(20, int(W / 43))
        for gy in range(0, H + spacing, spacing):
            for gx in range(0, W + spacing, spacing):
                dd.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=(255, 255, 255, 14))
        base = Image.alpha_composite(base, dot_layer)

    # glow, tinted to the logo's dominant color
    if glow_rgb is None:
        glow_rgb = dominant_color(logo)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    max_r = int(H * 0.54)
    steps = 120
    for i in range(steps, 0, -1):
        r = int(max_r * i / steps)
        alpha = int(44 * (1 - i / steps) ** 1.6)
        gdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*glow_rgb, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    base = Image.alpha_composite(base, glow)

    # top hairline
    draw = ImageDraw.Draw(base)
    draw.line([(0, 0), (W, 0)], fill=(255, 255, 255, 20), width=2)

    # vignette
    if draw_vignette:
        vignette = Image.new("L", (W, H), 0)
        vd = ImageDraw.Draw(vignette)
        vd.ellipse([-W // 4, -H // 4, W + W // 4, H + H // 4], fill=80)
        vignette = vignette.filter(ImageFilter.GaussianBlur(int(H * 0.24)))
        vignette = ImageOps.invert(vignette)
        black_layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        base = Image.composite(black_layer, base, vignette.point(lambda p: int(p * 0.35)))

    # fit logo (preserving aspect ratio, works for rectangular logos too)
    lw, lh = logo.size
    scale = icon_max / max(lw, lh)
    new_w, new_h = max(1, int(lw * scale)), max(1, int(lh * scale))
    logo_hq = logo.resize((new_w, new_h), Image.LANCZOS)

    # drop shadow
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    alpha_ch = logo_hq.split()[-1]
    shadow_black = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 180))
    shadow_black.putalpha(alpha_ch.point(lambda p: int(p * 0.5)))
    sx = cx - new_w // 2
    sy = cy - new_h // 2 + int(H * 0.022)
    shadow.paste(shadow_black, (sx, sy), shadow_black)
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(H * 0.032)))
    base = Image.alpha_composite(base, shadow)

    ix = cx - new_w // 2
    iy = cy - new_h // 2
    base.paste(logo_hq, (ix, iy), logo_hq)

    return base.convert("RGB")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def parse_size(s: str) -> tuple:
    w, h = s.lower().split("x")
    return int(w), int(h)


def main():
    p = argparse.ArgumentParser(prog="cardglow", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="Path to source logo (.png, .gif, or .svg)")
    p.add_argument("-o", "--output", default=None, help="Output PNG path (default: <input>-og.png)")
    p.add_argument("--size", default="1200x630", help="Canvas size, e.g. 1200x630 (default)")
    p.add_argument("--icon-size", type=int, default=300, help="Max logo dimension in px (default: 300)")
    p.add_argument("--bg-top", default="0d1117", help="Top gradient color, hex (default: 0d1117)")
    p.add_argument("--bg-bottom", default="090b0f", help="Bottom gradient color, hex (default: 090b0f)")
    p.add_argument(
        "--gradient-angle", type=float, default=180.0,
        help=(
            "Gradient direction in degrees, CSS linear-gradient() style: "
            "0=to top, 90=to right, 180=to bottom (default, plain vertical), "
            "270=to left. Try 135 for a GitHub-style bottom-left -> top-right diagonal."
        ),
    )
    p.add_argument(
        "--no-dither", action="store_true",
        help="Disable gradient dithering (may show visible banding on narrow-range gradients)",
    )
    p.add_argument(
        "--dither-strength", type=float, default=1.0,
        help="Dither noise amplitude, roughly in 8-bit levels (default: 1.0). Raise for very narrow-range gradients.",
    )
    p.add_argument("--glow", default=None, help="Force glow color, hex (default: auto-detected from logo)")
    p.add_argument("--no-grid", action="store_true", help="Disable the dot-grid background")
    p.add_argument("--no-vignette", action="store_true", help="Disable the corner vignette")
    p.add_argument("--no-autocrop", action="store_true", help="Skip auto-cropping transparent margins")
    p.add_argument("--svg-render-px", type=int, default=1000, help="Rasterization size for SVG input (default: 1000)")
    args = p.parse_args()

    out_path = args.output or (os.path.splitext(args.input)[0] + "-og.png")
    W, H = parse_size(args.size)

    logo = load_source_image(args.input, svg_render_px=args.svg_render_px)
    if not args.no_autocrop:
        logo = autocrop_transparent(logo)

    glow_rgb = hex_to_rgb(args.glow) if args.glow else None

    card = make_card(
        logo,
        width=W,
        height=H,
        icon_max=args.icon_size,
        bg_top=hex_to_rgb(args.bg_top),
        bg_bottom=hex_to_rgb(args.bg_bottom),
        gradient_angle=args.gradient_angle,
        dither=not args.no_dither,
        dither_strength=args.dither_strength,
        glow_rgb=glow_rgb,
        draw_grid=not args.no_grid,
        draw_vignette=not args.no_vignette,
    )
    card.save(out_path, quality=95)
    print(f"Saved {out_path}  ({W}x{H})")


if __name__ == "__main__":
    main()
