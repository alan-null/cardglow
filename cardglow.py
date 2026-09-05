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
    cardglow logo.svg --size 600x420 --padding 10 --fit height --transparent
    cardglow logo.png --padding "40 80" --fit contain --align bottom-right
    cardglow logo.png -o card.jpg --quality 80  # compressed JPEG output
    cardglow logo.png --format webp             # compressed WebP output
    cardglow photo.png --remove-bg              # auto-remove flat background
    cardglow photo.png --remove-bg --transparent --size 600x600 -o cutout.webp
    cardglow logo.png --watermark "example.com"  # visible corner watermark
    cardglow logo.png --watermark "(c) ACME" --watermark-tile
    cardglow logo.png --copyright "(c) 2026 ACME" --author "ACME Ltd"

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
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, PngImagePlugin


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
        # Pass only one axis so cairosvg derives the other from the viewBox;
        # forcing both would stretch non-square art to a square.
        png_bytes = cairosvg.svg2png(url=path, output_width=svg_render_px)
        im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        if im.height > im.width:
            png_bytes = cairosvg.svg2png(url=path, output_height=svg_render_px)
            im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        return im

    im = Image.open(path)
    if getattr(im, "is_animated", False):  # GIF: use first frame
        im.seek(0)
    return im.convert("RGBA")


def autocrop_transparent(im: Image.Image, pad_ratio: float = 0.0) -> Image.Image:
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

def remove_background(
    im: Image.Image, tolerance: float = 30.0, feather: float = 2.0,
    corner_sample: int = 5,
) -> Image.Image:
    """Auto-remove a flat/near-uniform background. Samples the average
    color of the four corners as the presumed background color, then
    flood-fills outward from the image border across pixels within
    `tolerance` color-distance of it, making only that border-connected
    region transparent (so similarly colored patches inside the subject
    itself are left untouched). `feather` softens the cut edge."""
    rgba = np.array(im.convert("RGBA"))
    full_h, full_w = rgba.shape[:2]
    alpha_full = rgba[..., 3]

    # Scope everything to the bounding box of non-transparent content.
    # A source may already carry a transparent margin of its own (a
    # rounded-corner cutout, prior processing, etc.) without actually
    # having had its real background removed yet; sampling/flooding from
    # the literal image border would either see nothing but that margin
    # (falsely concluding there's no background left) or leak through its
    # anti-aliased edge. Working within the content's own bbox sidesteps
    # both: an already-fully-cut-out subject's bbox hugs its silhouette
    # (nothing flat left to flood-fill), while a subject with a thin
    # transparent margin around a still-flat background exposes that
    # background at the bbox's own edge, where it can be found normally.
    bbox = Image.fromarray(alpha_full, mode="L").getbbox()
    if not bbox:
        return im
    x0, y0, x1, y1 = bbox
    rgb = rgba[y0:y1, x0:x1, :3].astype(np.int16)
    alpha_ch = alpha_full[y0:y1, x0:x1]
    h, w = rgb.shape[:2]

    cs = max(1, min(corner_sample, h, w))
    corner_regions = [
        (rgb[0:cs, 0:cs], alpha_ch[0:cs, 0:cs]),
        (rgb[0:cs, w - cs:w], alpha_ch[0:cs, w - cs:w]),
        (rgb[h - cs:h, 0:cs], alpha_ch[h - cs:h, 0:cs]),
        (rgb[h - cs:h, w - cs:w], alpha_ch[h - cs:h, w - cs:w]),
    ]
    # Only trust opaque pixels for the background color estimate - a
    # transparent pixel's leftover RGB is meaningless (some tools leave
    # white behind, others black) and would otherwise get sampled as if
    # it were a real background color.
    opaque_corners = [
        region.reshape(-1, 3)[a.reshape(-1) >= 250]
        for region, a in corner_regions
    ]
    opaque_corners = [c for c in opaque_corners if len(c) > 0]
    if not opaque_corners:
        # None of the corners have any solid pixels left to sample - the
        # source is already a tight cutout with nothing but soft/
        # transparent edges at its corners, so there's no reliable flat
        # background left to remove.
        return im
    bg_color = np.concatenate(opaque_corners, axis=0).mean(axis=0)

    dist = np.sqrt(((rgb - bg_color) ** 2).sum(axis=-1))
    # Exclude already-partially-transparent pixels from the candidate
    # set too: their RGB is unreliable and they're already a cut edge,
    # not remaining flat background to flood-fill through.
    candidate = (dist <= tolerance) & (alpha_ch >= 250)

    # flood-fill candidate background pixels reachable from the border,
    # done on a mask image so PIL's fast C flood fill does the work.
    # .copy() detaches from the numpy buffer — floodfill silently no-ops
    # on images still backed by shared/array memory.
    mask_im = Image.fromarray(np.where(candidate, 255, 0).astype(np.uint8), mode="L").copy()
    mask_px = mask_im.load()

    border_pts = {(x, 0) for x in range(w)} | {(x, h - 1) for x in range(w)}
    border_pts |= {(0, y) for y in range(h)} | {(w - 1, y) for y in range(h)}
    for pt in border_pts:
        if mask_px[pt] == 255:
            ImageDraw.floodfill(mask_im, pt, 128, thresh=0)

    bg_mask = np.array(mask_im) == 128
    if not bg_mask.any():
        return im

    if feather > 0:
        feather_im = Image.fromarray((bg_mask * 255).astype(np.uint8), mode="L")
        feather_im = feather_im.filter(ImageFilter.GaussianBlur(feather))
        bg_frac = np.asarray(feather_im).astype(np.float32) / 255.0
    else:
        bg_frac = bg_mask.astype(np.float32)

    sub_alpha = alpha_ch.astype(np.float32) * (1.0 - bg_frac)
    out_alpha = alpha_full.astype(np.float32)
    out_alpha[y0:y1, x0:x1] = np.clip(sub_alpha, 0, 255)
    rgba[..., 3] = out_alpha.astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


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

# ----------------------------------------------------------------------
# Layout: content box + fit mode + alignment
# ----------------------------------------------------------------------

ALIGN_FACTORS = {
    "center": (0.5, 0.5),
    "top": (0.5, 0.0),
    "bottom": (0.5, 1.0),
    "left": (0.0, 0.5),
    "right": (1.0, 0.5),
    "top-left": (0.0, 0.0),
    "top-right": (1.0, 0.0),
    "bottom-left": (0.0, 1.0),
    "bottom-right": (1.0, 1.0),
}

FIT_MODES = ("contain", "cover", "width", "height")


def parse_padding(s: str) -> tuple:
    """CSS shorthand -> (top, right, bottom, left).

    "10" | "10 20" | "10 20 30" | "10 20 30 40" (commas also accepted).
    """
    vals = [int(round(float(v))) for v in s.replace(",", " ").split() if v]
    if len(vals) == 1:
        t = r = b = l = vals[0]
    elif len(vals) == 2:
        t = b = vals[0]
        r = l = vals[1]
    elif len(vals) == 3:
        t, r, b = vals
        l = r
    elif len(vals) == 4:
        t, r, b, l = vals
    else:
        raise ValueError(f"--padding expects 1-4 values, got {len(vals)}: {s!r}")
    return t, r, b, l


def fit_logo(
    logo: Image.Image,
    width: int,
    height: int,
    padding: tuple = (0, 0, 0, 0),
    fit: str = "contain",
    align: str = "center",
    max_px: int = None,
    nudge_y: int = 0,
) -> tuple:
    """Scale and place `logo` inside the canvas content box.

    Returns (resized_logo, x, y) so callers can keep shadows/glow in sync.
    """
    if fit not in FIT_MODES:
        raise ValueError(f"unknown fit mode: {fit!r}")
    if align not in ALIGN_FACTORS:
        raise ValueError(f"unknown align: {align!r}")

    pt, pr, pb, pl = padding
    box_w = max(1, width - pl - pr)
    box_h = max(1, height - pt - pb)
    lw, lh = logo.size

    if fit == "contain":
        scale = min(box_w / lw, box_h / lh)
    elif fit == "cover":
        scale = max(box_w / lw, box_h / lh)
    elif fit == "width":
        scale = box_w / lw
    else:  # height
        scale = box_h / lh

    if max_px:
        scale = min(scale, max_px / max(lw, lh))

    new_w = max(1, int(round(lw * scale)))
    new_h = max(1, int(round(lh * scale)))
    out = logo.resize((new_w, new_h), Image.LANCZOS)

    ax, ay = ALIGN_FACTORS[align]
    x = pl + int(round((box_w - new_w) * ax))
    y = pt + int(round((box_h - new_h) * ay)) + nudge_y

    if fit == "cover":
        # Trim the overflow so a covering logo never spills past the content box.
        left = max(0, pl - x)
        top = max(0, pt - y)
        out = out.crop((left, top, min(new_w, left + box_w), min(new_h, top + box_h)))
        x, y = pl, pt + nudge_y

    return out, x, y


def make_card(
    logo: Image.Image,
    width: int = 1200,
    height: int = 630,
    padding: tuple = (0, 0, 0, 0),
    fit: str = "contain",
    align: str = "center",
    max_px: int = None,
    nudge_y: int = 0,
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
    logo_hq, ix, iy = fit_logo(logo, W, H, padding, fit, align, max_px, nudge_y)
    new_w, new_h = logo_hq.size
    cx, cy = ix + new_w // 2, iy + new_h // 2

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

    # drop shadow
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_black = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 180))
    shadow_black.putalpha(logo_hq.split()[-1].point(lambda p: int(p * 0.5)))
    shadow.paste(shadow_black, (ix, iy + int(H * 0.022)), shadow_black)
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(H * 0.032)))
    base = Image.alpha_composite(base, shadow)

    base.paste(logo_hq, (ix, iy), logo_hq)

    return base.convert("RGB")


def make_transparent_image(
    logo: Image.Image,
    width: int,
    height: int,
    padding: tuple = (0, 0, 0, 0),
    fit: str = "contain",
    align: str = "center",
    max_px: int = None,
) -> Image.Image:
    """Place a proportionally scaled logo on a transparent canvas."""
    logo_hq, x, y = fit_logo(logo, width, height, padding, fit, align, max_px)

    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    output.paste(logo_hq, (x, y), logo_hq)
    return output


# ----------------------------------------------------------------------
# Watermarking / provenance metadata
# ----------------------------------------------------------------------

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def load_font(size: int):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)  # scalable default, Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def draw_watermark(
    im: Image.Image,
    text: str,
    position: str = "bottom-right",
    opacity: float = 0.35,
    font_px: int = None,
    color: tuple = (255, 255, 255),
    margin: int = None,
    tile: bool = False,
    angle: float = 30.0,
) -> Image.Image:
    """Composite a semi-transparent text watermark onto the image.

    `tile=True` repeats the text diagonally across the whole canvas, which is
    far harder to crop out than a single corner mark.
    """
    W, H = im.size
    size = font_px or max(11, int(round(H * 0.028)))
    alpha = int(round(max(0.0, min(1.0, opacity)) * 255))
    if alpha == 0 or not text:
        return im

    font = load_font(size)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    if tile:
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        l, t, r, b = probe.textbbox((0, 0), text, font=font)
        tw, th = r - l, b - t
        gap_x, gap_y = int(tw * 0.6) + size, int(th * 2.5) + size
        stamp = Image.new("RGBA", (tw + 2 * size, th + 2 * size), (0, 0, 0, 0))
        ImageDraw.Draw(stamp).text((size - l, size - t), text, font=font, fill=(*color, alpha))
        stamp = stamp.rotate(angle, resample=Image.BICUBIC, expand=True)
        sw, sh = stamp.size
        step_x, step_y = sw + gap_x, sh + gap_y
        for row, y in enumerate(range(-sh, H + step_y, step_y)):
            offset = (row % 2) * step_x // 2
            for x in range(-sw + offset, W + step_x, step_x):
                overlay.alpha_composite(stamp, (x, y))
    else:
        if position not in ALIGN_FACTORS:
            raise ValueError(f"unknown watermark position: {position!r}")
        pad = margin if margin is not None else max(8, int(round(H * 0.025)))
        d = ImageDraw.Draw(overlay)
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        tw, th = r - l, b - t
        ax, ay = ALIGN_FACTORS[position]
        x = pad + int(round((W - 2 * pad - tw) * ax)) - l
        y = pad + int(round((H - 2 * pad - th) * ay)) - t
        # Faint shadow keeps light text legible over light backgrounds.
        d.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, alpha // 2))
        d.text((x, y), text, font=font, fill=(*color, alpha))

    out = Image.alpha_composite(im.convert("RGBA"), overlay)
    return out if im.mode == "RGBA" else out.convert(im.mode)


def parse_metadata_pairs(pairs) -> dict:
    """['Key=Value', ...] -> {'Key': 'Value', ...}"""
    out = {}
    for item in pairs or []:
        if "=" not in item:
            raise ValueError(f"--metadata expects KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        k = k.strip()
        if not k:
            raise ValueError(f"--metadata key must not be empty: {item!r}")
        out[k] = v.strip()
    return out


# EXIF tag ids used for JPEG/WebP provenance.
_EXIF_IMAGE_DESCRIPTION = 0x010E
_EXIF_SOFTWARE = 0x0131
_EXIF_ARTIST = 0x013B
_EXIF_COPYRIGHT = 0x8298


def metadata_save_kwargs(fmt: str, meta: dict) -> dict:
    """Turn a flat key/value map into format-specific Image.save() kwargs.

    PNG gets one tEXt chunk per key; JPEG/WebP get standard EXIF fields, with
    any extra keys folded into ImageDescription as `Key=Value; ...`.
    """
    meta = {k: v for k, v in meta.items() if v}
    if not meta:
        return {}

    if fmt == "png":
        info = PngImagePlugin.PngInfo()
        for k, v in meta.items():
            info.add_text(k, v)
        return {"pnginfo": info}

    exif = Image.Exif()
    rest = dict(meta)
    for key, tag in (("Software", _EXIF_SOFTWARE), ("Author", _EXIF_ARTIST),
                     ("Copyright", _EXIF_COPYRIGHT)):
        if key in rest:
            exif[tag] = rest.pop(key)
    description = rest.pop("Description", None)
    extras = "; ".join(f"{k}={v}" for k, v in rest.items())
    joined = "; ".join(x for x in (description, extras) if x)
    if joined:
        exif[_EXIF_IMAGE_DESCRIPTION] = joined
    return {"exif": exif.tobytes()}


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def parse_size(s: str) -> tuple:
    parts = s.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"--size expects WIDTHxHEIGHT, got {s!r}")
    try:
        w, h = (int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"--size expects integer dimensions, got {s!r}") from exc
    if w <= 0 or h <= 0:
        raise ValueError(f"--size dimensions must be positive, got {s!r}")
    return w, h


def main():
    p = argparse.ArgumentParser(prog="cardglow", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="Path to source logo (.png, .gif, or .svg)")
    p.add_argument("-o", "--output", default=None, help="Output path (default: <input>-og.<format>)")
    p.add_argument(
        "--format", choices=["png", "jpeg", "jpg", "webp"], default=None,
        help="Output image format (default: inferred from -o extension, else png)",
    )
    p.add_argument(
        "--quality", type=int, default=85,
        help="Compression quality for jpeg/webp, 1-100 (default: 85). Ignored for png.",
    )
    p.add_argument("--size", default="1200x630", help="Canvas size, e.g. 1200x630 (default)")
    p.add_argument(
        "--icon-size", type=int, default=None,
        help="Cap the logo's longest side, in px (default: 300 unless --padding/--fit is used)",
    )
    p.add_argument(
        "--padding", default=None,
        help=(
            "Inset from the canvas edges, CSS shorthand: '10', '10 20', "
            "'10 20 30' or '10 20 30 40' (top right bottom left). Defines the content box."
        ),
    )
    p.add_argument(
        "--fit", choices=list(FIT_MODES), default=None,
        help=(
            "How the logo fills the content box: contain (default, never overflows), "
            "height (fill full height), width (fill full width), cover (fill both, cropped)"
        ),
    )
    p.add_argument(
        "--align", choices=sorted(ALIGN_FACTORS), default="center",
        help="Where the logo sits inside the content box (default: center)",
    )
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
    p.add_argument(
        "--transparent", action="store_true",
        help="Output the processed logo on a transparent canvas instead of a card (PNG/WebP only)",
    )
    p.add_argument(
        "--svg-render-px", type=int, default=1000,
        help=("Minimum rasterization size for SVG input, longest side (default: 1000). "
              "Automatically raised to 2x the target draw size when that is larger."),
    )
    p.add_argument(
        "--remove-bg", action="store_true",
        help="Auto-remove a flat/near-uniform background (sampled from the image corners) before compositing",
    )
    p.add_argument(
        "--bg-tolerance", type=float, default=30.0,
        help="Color-distance tolerance for --remove-bg (default: 30). Higher removes more shades/noise.",
    )
    p.add_argument(
        "--bg-feather", type=float, default=2.0,
        help="Edge feather radius in px for --remove-bg (default: 2.0, 0 disables softening)",
    )
    p.add_argument("--watermark", default=None, help="Draw this text as a semi-transparent watermark")
    p.add_argument(
        "--watermark-position", choices=sorted(ALIGN_FACTORS), default="bottom-right",
        help="Where the watermark sits (default: bottom-right). Ignored with --watermark-tile",
    )
    p.add_argument(
        "--watermark-opacity", type=float, default=0.35,
        help="Watermark opacity, 0-1 (default: 0.35; try 0.08 with --watermark-tile)",
    )
    p.add_argument(
        "--watermark-size", type=int, default=None,
        help="Watermark font size in px (default: ~2.8%% of the canvas height)",
    )
    p.add_argument("--watermark-color", default="ffffff", help="Watermark text color, hex (default: ffffff)")
    p.add_argument(
        "--watermark-margin", type=int, default=None,
        help="Watermark inset from the canvas edges in px (default: ~2.5%% of the height)",
    )
    p.add_argument(
        "--watermark-tile", action="store_true",
        help="Repeat the watermark diagonally across the whole image instead of one corner",
    )
    p.add_argument(
        "--watermark-angle", type=float, default=30.0,
        help="Rotation of the tiled watermark in degrees (default: 30)",
    )
    p.add_argument("--author", default=None, help="Embed an author/creator name in the output metadata")
    p.add_argument("--copyright", dest="copyright_", metavar="TEXT", default=None, help="Embed a copyright notice in the output metadata")
    p.add_argument("--description", default=None, help="Embed a description in the output metadata")
    p.add_argument(
        "--metadata", action="append", metavar="KEY=VALUE", default=None,
        help="Embed an extra metadata field (repeatable)",
    )
    p.add_argument(
        "--no-metadata", action="store_true",
        help="Write the image with no metadata at all (not even the default Software tag)",
    )
    args = p.parse_args()

    fmt = args.format or (os.path.splitext(args.output)[1].lstrip(".").lower() if args.output else "png")
    fmt = {"jpg": "jpeg"}.get(fmt, fmt)
    if fmt not in ("png", "jpeg", "webp"):
        fmt = "png"
    if args.transparent and fmt == "jpeg":
        p.error("--transparent requires PNG or WebP output; JPEG does not support transparency")
    out_path = args.output or (os.path.splitext(args.input)[0] + f"-og.{fmt}")
    W, H = parse_size(args.size)

    explicit_layout = args.padding is not None or args.fit is not None
    try:
        padding = parse_padding(args.padding) if args.padding else (0, 0, 0, 0)
    except ValueError as e:
        p.error(str(e))
    fit = args.fit or "contain"
    max_px = args.icon_size if (args.icon_size is not None or explicit_layout) else 300
    # The card's logo sits slightly above centre for optical balance; an explicit
    # padding/fit request means the user wants exact numbers, so drop the nudge.
    nudge_y = 0 if explicit_layout else -int(H * 0.032)

    box_w = max(1, W - padding[3] - padding[1])
    box_h = max(1, H - padding[0] - padding[2])
    svg_px = min(4096, max(args.svg_render_px, 2 * max(box_w, box_h, max_px or 0)))

    logo = load_source_image(args.input, svg_render_px=svg_px)
    if args.remove_bg:
        logo = remove_background(logo, tolerance=args.bg_tolerance, feather=args.bg_feather)
    if not args.no_autocrop:
        logo = autocrop_transparent(logo)

    if args.transparent:
        card = make_transparent_image(logo, W, H, padding, fit, args.align, max_px)
    else:
        glow_rgb = hex_to_rgb(args.glow) if args.glow else None
        card = make_card(
            logo,
            width=W,
            height=H,
            padding=padding,
            fit=fit,
            align=args.align,
            max_px=max_px,
            nudge_y=nudge_y,
            bg_top=hex_to_rgb(args.bg_top),
            bg_bottom=hex_to_rgb(args.bg_bottom),
            gradient_angle=args.gradient_angle,
            dither=not args.no_dither,
            dither_strength=args.dither_strength,
            glow_rgb=glow_rgb,
            draw_grid=not args.no_grid,
            draw_vignette=not args.no_vignette,
        )

    if args.watermark:
        card = draw_watermark(
            card,
            args.watermark,
            position=args.watermark_position,
            opacity=args.watermark_opacity,
            font_px=args.watermark_size,
            color=hex_to_rgb(args.watermark_color),
            margin=args.watermark_margin,
            tile=args.watermark_tile,
            angle=args.watermark_angle,
        )

    save_kwargs = {}
    if fmt == "jpeg":
        save_kwargs = {"quality": args.quality, "optimize": True, "progressive": True}
    elif fmt == "webp":
        save_kwargs = {"quality": args.quality}
    elif fmt == "png":
        save_kwargs = {"optimize": True}

    if not args.no_metadata:
        try:
            extra = parse_metadata_pairs(args.metadata)
        except ValueError as e:
            p.error(str(e))
        meta = {
            "Software": "cardglow",
            "Author": args.author,
            "Copyright": args.copyright_,
            "Description": args.description,
        }
        meta.update(extra)
        save_kwargs.update(metadata_save_kwargs(fmt, meta))

    card.save(out_path, format=fmt.upper(), **save_kwargs)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"Saved {out_path}  ({W}x{H}, {fmt}, {size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
