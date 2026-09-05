import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

import cardglow


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "cardglow.py"


def test_parse_padding_supports_css_shorthand():
    assert cardglow.parse_padding("10") == (10, 10, 10, 10)
    assert cardglow.parse_padding("10 20") == (10, 20, 10, 20)
    assert cardglow.parse_padding("10 20 30") == (10, 20, 30, 20)
    assert cardglow.parse_padding("10, 20, 30, 40") == (10, 20, 30, 40)


def test_parse_padding_rejects_wrong_value_count():
    with pytest.raises(ValueError, match="expects 1-4 values"):
        cardglow.parse_padding("1 2 3 4 5")


def test_parse_size_parses_dimensions():
    assert cardglow.parse_size("1200x630") == (1200, 630)


@pytest.mark.parametrize("value", ["1200", "1200by630", "0x630"])
def test_parse_size_rejects_invalid_dimensions(value):
    with pytest.raises(ValueError):
        width, height = cardglow.parse_size(value)
        assert width > 0 and height > 0


def test_resolve_config_supports_custom_theme_and_json_keys(tmp_path):
    config = tmp_path / "cardglow.json"
    config.write_text(
        json.dumps({
            "theme": "brand",
            "themes": {
                "brand": {
                    "bg-top": "112233",
                    "no-grid": True,
                }
            },
            "options": {"size": "640x360"},
        }),
        encoding="utf-8",
    )

    options, selected = cardglow.resolve_config(str(config))

    assert selected == "brand"
    assert options["bg_top"] == "112233"
    assert options["no_grid"] is True
    assert options["size"] == "640x360"


def test_cli_config_values_can_be_overridden(tmp_path):
    source = tmp_path / "logo.png"
    config = tmp_path / "cardglow.toml"
    output = tmp_path / "card.png"
    Image.new("RGBA", (24, 16), (30, 120, 220, 255)).save(source)
    config.write_text(
        "size = \"32x16\"\ntransparent = true\nno_grid = true\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(source),
            "--config",
            str(config),
            "--size",
            "48x24",
            "--opaque",
            "--grid",
            "-o",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        assert image.size == (48, 24)
        assert image.mode == "RGB"


def test_autocrop_transparent_margins():
    image = Image.new("RGBA", (10, 8), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (3, 2, 8, 6))

    cropped = cardglow.autocrop_transparent(image)

    assert cropped.size == (5, 4)
    assert cropped.getbbox() == (0, 0, 5, 4)


def test_autocrop_leaves_opaque_and_empty_images_unchanged():
    opaque = Image.new("RGBA", (4, 3), (255, 0, 0, 255))
    empty = Image.new("RGBA", (4, 3), (0, 0, 0, 0))

    assert cardglow.autocrop_transparent(opaque) is opaque
    assert cardglow.autocrop_transparent(empty) is empty


def test_fit_logo_contain_respects_max_size_and_center_alignment():
    logo = Image.new("RGBA", (100, 50), (255, 0, 0, 255))

    resized, x, y = cardglow.fit_logo(
        logo, 200, 100, max_px=80, align="center"
    )

    assert resized.size == (80, 40)
    assert (x, y) == (60, 30)


@pytest.mark.parametrize(
    ("fit", "expected_size", "expected_position"),
    [
        ("height", (160, 80), (20, 10)),
        ("width", (160, 80), (20, 10)),
        ("cover", (160, 80), (20, 10)),
    ],
)
def test_fit_logo_modes_and_padding(fit, expected_size, expected_position):
    logo = Image.new("RGBA", (100, 50), (255, 0, 0, 255))

    resized, x, y = cardglow.fit_logo(
        logo,
        200,
        100,
        padding=(10, 20, 10, 20),
        fit=fit,
        align="top-left",
    )

    assert resized.size == expected_size
    assert (x, y) == expected_position


def test_fit_logo_cover_crops_overflow():
    logo = Image.new("RGBA", (100, 100), (255, 0, 0, 255))

    resized, x, y = cardglow.fit_logo(
        logo, 200, 100, padding=(0, 0, 0, 0), fit="cover", align="center"
    )

    assert resized.size == (200, 100)
    assert (x, y) == (0, 0)


def test_remove_background_preserves_isolated_interior_color():
    image = Image.new("RGBA", (20, 20), (255, 255, 255, 255))
    image.paste((220, 30, 30, 255), (5, 5, 15, 15))
    image.paste((255, 255, 255, 255), (8, 8, 10, 10))

    result = cardglow.remove_background(image, tolerance=1, feather=0)

    assert result.getpixel((0, 0))[3] == 0
    assert result.getpixel((6, 6))[3] == 255
    assert result.getpixel((8, 8))[3] == 255


def test_dominant_color_and_hex_conversion():
    image = Image.new("RGBA", (8, 8), (32, 96, 224, 255))

    assert cardglow.dominant_color(image) == (32, 96, 224)
    assert cardglow.hex_to_rgb("#ff3355") == (255, 51, 85)


def test_make_card_returns_opaque_rgb_image():
    logo = Image.new("RGBA", (20, 10), (30, 120, 220, 255))

    result = cardglow.make_card(
        logo,
        width=120,
        height=80,
        draw_grid=False,
        draw_vignette=False,
    )

    assert result.size == (120, 80)
    assert result.mode == "RGB"


def test_make_transparent_image_places_logo_on_transparent_canvas():
    logo = Image.new("RGBA", (10, 10), (30, 120, 220, 255))

    result = cardglow.make_transparent_image(logo, 40, 30)

    assert result.size == (40, 30)
    assert result.mode == "RGBA"
    assert result.getpixel((0, 0))[3] == 0
    assert result.getbbox() is not None


@pytest.mark.parametrize("tile", [False, True])
def test_draw_watermark_preserves_size_and_changes_pixels(tile):
    image = Image.new("RGB", (120, 80), (20, 20, 20))

    result = cardglow.draw_watermark(
        image, "preview", opacity=1, font_px=12, tile=tile
    )

    assert result.size == image.size
    assert result.mode == image.mode
    assert result.tobytes() != image.tobytes()


@pytest.mark.parametrize("fmt", ["jpeg", "webp"])
def test_metadata_save_kwargs_round_trip_exif(fmt):
    image = Image.new("RGB", (8, 8), (20, 30, 40))
    kwargs = cardglow.metadata_save_kwargs(
        fmt,
        {
            "Software": "cardglow",
            "Author": "Test Author",
            "Copyright": "Test Copyright",
            "Description": "Test Description",
            "License": "MIT",
        },
    )

    output = io.BytesIO()
    image.save(output, format=fmt.upper(), **kwargs)
    output.seek(0)
    exif = Image.open(output).getexif()

    assert exif[cardglow._EXIF_SOFTWARE] == "cardglow"
    assert exif[cardglow._EXIF_ARTIST] == "Test Author"
    assert exif[cardglow._EXIF_COPYRIGHT] == "Test Copyright"
    assert exif[cardglow._EXIF_IMAGE_DESCRIPTION] == "Test Description; License=MIT"


def test_metadata_save_kwargs_writes_png_text_chunks():
    image = Image.new("RGB", (8, 8), (20, 30, 40))
    kwargs = cardglow.metadata_save_kwargs("png", {"Author": "Test Author"})

    output = io.BytesIO()
    image.save(output, format="PNG", **kwargs)
    output.seek(0)

    assert Image.open(output).info["Author"] == "Test Author"
