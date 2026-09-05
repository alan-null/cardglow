import subprocess
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "cardglow.py"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_writes_default_png_with_metadata(tmp_path):
    source = tmp_path / "logo.png"
    Image.new("RGBA", (24, 16), (30, 120, 220, 255)).save(source)

    result = run_cli(source, "--size", "64x32", "--author", "Test Author")

    assert result.returncode == 0, result.stderr
    output = tmp_path / "logo-og.png"
    with Image.open(output) as image:
        assert image.size == (64, 32)
        assert image.mode == "RGB"
        assert image.info["Software"] == "cardglow"
        assert image.info["Author"] == "Test Author"


def test_cli_writes_transparent_webp(tmp_path):
    source = tmp_path / "logo.png"
    Image.new("RGBA", (24, 16), (30, 120, 220, 255)).save(source)
    output = tmp_path / "cutout.webp"

    result = run_cli(
        source,
        "--transparent",
        "--size",
        "40x30",
        "--icon-size",
        "20",
        "-o",
        output,
    )

    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        assert image.size == (40, 30)
        assert image.mode == "RGBA"
        assert image.getbbox() is not None
        assert image.getpixel((0, 0))[3] == 0


def test_cli_rasterizes_svg_input(tmp_path):
    source = tmp_path / "logo.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 1">'
        '<rect width="2" height="1" fill="#1e78dc" /></svg>',
        encoding="utf-8",
    )
    output = tmp_path / "card.png"

    result = run_cli(source, "--size", "48x24", "-o", output)

    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        assert image.size == (48, 24)
        assert image.mode == "RGB"
