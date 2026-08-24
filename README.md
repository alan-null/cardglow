# cardglow

Turn any logo — PNG, GIF, or SVG, square or rectangular — into a clean,
[GitHub-OG-card](https://opengraph.githubassets.com)-style social preview
image.

Point it at a logo and get back a ready-to-use `og:image` / Twitter
card PNG, with **zero manual color picking**: cardglow auto-detects the
logo's dominant color and tints the background glow to match.

## See it in action

### Before

<p align="center">
  <img src="docs/input.svg" width="150" alt="Source logo before processing" />
</p>

```bash
./cardglow-docker.sh docs/input.svg --gradient-angle 130 --bg-top ffffff --bg-bottom cccccc --icon-size 300 -o docs/example.png
```

### After

<p align="center">
  <img src="docs/example.png" width="600" alt="Generated social preview card" />
</p>

## Features

- **PNG / GIF / SVG input** — SVGs are rasterized at high resolution; GIFs use the first frame.
- **Auto-crop** — trims transparent margins so off-center or padded source art gets re-centered correctly.
- **Auto color-matched glow** — samples the logo's dominant color, no manual hex-picking needed (or override with `--glow`).
- **Angled gradient background** — CSS `linear-gradient()`-style `--gradient-angle`, dithered to avoid banding on narrow color ranges.
- **Subtle dot grid, vignette, drop shadow** — the same details that make GitHub's own OG cards feel polished.
- **No local installs** — ships as a Docker image; only dependency on your machine is Docker itself.

## Quick start

```bash
docker run --rm -v "$PWD":/data ghcr.io/alan-null/cardglow logo.png
```

That writes `logo-og.png` (1200×630) next to your source file.

Or grab the wrapper script for a shorter command:

```bash
curl -O https://raw.githubusercontent.com/alan-null/cardglow/main/cardglow-docker.sh
chmod +x cardglow-docker.sh
./cardglow-docker.sh logo.png
```

## Usage

```
cardglow <input> [options]

  -o, --output PATH       Output PNG path (default: <input>-og.png)
  --size WxH              Canvas size (default: 1200x630)
  --icon-size PX          Max logo dimension in px (default: 300)
  --bg-top HEX            Top gradient color (default: 0d1117)
  --bg-bottom HEX         Bottom gradient color (default: 090b0f)
  --gradient-angle DEG    Gradient direction, CSS linear-gradient() style:
                          0=to top, 90=to right, 180=to bottom (default),
                          270=to left. Try 135 for a GitHub-style diagonal.
  --glow HEX              Force glow color (default: auto-detected)
  --no-grid               Disable the dot-grid background
  --no-vignette           Disable the corner vignette
  --no-autocrop           Skip auto-cropping transparent margins
  --no-dither             Disable gradient dithering
  --dither-strength FLOAT Dither noise amplitude (default: 1.0)
  --svg-render-px PX      SVG rasterization size (default: 1000)
```

### Examples

```bash
# Basic
./cardglow-docker.sh logo.png

# SVG source, custom output name
./cardglow-docker.sh logo.svg -o card.png

# GitHub-style diagonal gradient
./cardglow-docker.sh logo.png --gradient-angle 135

# Force a specific glow color, drop the dot grid
./cardglow-docker.sh logo.png --glow "#ff3355" --no-grid

# Larger logo, custom canvas size
./cardglow-docker.sh logo.png --icon-size 400 --size 1280x640
```

## Building locally

```bash
git clone https://github.com/alan-null/cardglow.git
cd cardglow
docker build -t cardglow .
docker run --rm -v "$PWD":/data cardglow logo.png
```

## Running without Docker

If you'd rather run it directly:

```bash
pip install pillow cairosvg numpy
python3 cardglow.py logo.png
```