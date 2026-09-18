from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "cuotago" / "static" / "icons" / "logo-master.png"
OUT = ROOT / "cuotago" / "static" / "splash"
OUT.mkdir(parents=True, exist_ok=True)

SIZES = [
    (1320, 2868),
    (1290, 2796),
    (1206, 2622),
    (1179, 2556),
    (1284, 2778),
    (1242, 2688),
    (1170, 2532),
    (1125, 2436),
    (1080, 2340),
    (828, 1792),
    (750, 1334),
]

# Deliberately light for both media variants. This avoids the black launch flash
# that can happen on iOS when the device is using dark appearance.
BACKGROUND = "#fffaf6"
TEXT = "#101828"
ACCENT = "#ff6429"
FONT_CANDIDATES = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
]
FONT_PATH = next((path for path in FONT_CANDIDATES if path.exists()), None)


def font(size: int):
    return ImageFont.truetype(str(FONT_PATH), size) if FONT_PATH else ImageFont.load_default()


def make_splash(width: int, height: int, theme_name: str):
    canvas = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    icon_src = Image.open(ICON).convert("RGB")

    icon_size = int(min(width, height) * 0.30)
    icon = icon_src.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
    icon_x = (width - icon_size) // 2
    icon_y = int(height * 0.34 - icon_size / 2)
    canvas.paste(icon, (icon_x, icon_y))

    title_font = font(max(30, int(width * 0.075)))
    first, second = "Cuota", "Go"
    first_box = draw.textbbox((0, 0), first, font=title_font)
    second_box = draw.textbbox((0, 0), second, font=title_font)
    first_w = first_box[2] - first_box[0]
    second_w = second_box[2] - second_box[0]
    title_x = (width - first_w - second_w) // 2
    title_y = icon_y + icon_size + int(height * 0.025)
    draw.text((title_x, title_y), first, font=title_font, fill=TEXT)
    draw.text((title_x + first_w, title_y), second, font=title_font, fill=ACCENT)

    out = OUT / f"{width}x{height}-{theme_name}.png"
    canvas.save(out, optimize=True)
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    for w, h in SIZES:
        for theme in ("light", "dark"):
            make_splash(w, h, theme)
