from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import THUMBNAIL_DIR


FONT_PATH = Path(
    r"C:\Windows\Fonts\arialbd.ttf"
)


def create_thumbnail(
    source_image: Path,
    text: str,
    filename: str,
) -> Path:
    image = Image.open(source_image).convert("RGB")
    image = image.resize((1280, 720))

    overlay = Image.new(
        "RGBA",
        image.size,
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(overlay)

    draw.rectangle(
        (0, 420, 1280, 720),
        fill=(0, 0, 0, 170),
    )

    font = ImageFont.truetype(
        str(FONT_PATH),
        90,
    )

    draw.text(
        (640, 550),
        text.upper(),
        font=font,
        anchor="mm",
        align="center",
        fill="white",
        stroke_width=6,
        stroke_fill="black",
    )

    result = Image.alpha_composite(
        image.convert("RGBA"),
        overlay,
    ).convert("RGB")

    output_path = (
        THUMBNAIL_DIR / f"{filename}.jpg"
    )

    result.save(
        output_path,
        quality=95,
    )

    return output_path