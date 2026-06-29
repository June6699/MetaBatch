from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .runtime import get_resource_dir

ICON_DIRNAME = "assets"
ICON_FILENAME = "metabatch_icon.ico"


def ensure_app_icon() -> Path:
    base_dir = get_resource_dir()
    assets_dir = base_dir / ICON_DIRNAME
    assets_dir.mkdir(parents=True, exist_ok=True)
    icon_path = assets_dir / ICON_FILENAME
    if icon_path.exists():
        return icon_path

    size = 256
    image = Image.new("RGBA", (size, size), (26, 69, 140, 255))
    draw = ImageDraw.Draw(image)

    for index in range(size):
        color = (
            26 + index // 6,
            69 + index // 4,
            min(255, 140 + index // 3),
            255,
        )
        draw.line((0, index, size, index), fill=color)

    draw.rounded_rectangle((24, 24, size - 24, size - 24), radius=52, outline=(255, 255, 255, 190), width=8)
    draw.ellipse((58, 58, 198, 198), fill=(255, 170, 49, 255))
    draw.rounded_rectangle((108, 48, 148, 208), radius=18, fill=(255, 255, 255, 240))
    draw.rounded_rectangle((72, 108, 184, 148), radius=18, fill=(255, 255, 255, 240))

    try:
        font = ImageFont.truetype("seguiemj.ttf", 54)
        draw.text((78, 178), "MB", fill=(255, 255, 255, 255), font=font)
    except Exception:
        pass

    image.save(icon_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    return icon_path
