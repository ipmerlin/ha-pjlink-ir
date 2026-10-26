"""Draw original projector brand assets; requires Pillow for development only."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((72, 288, 952, 744), radius=100, fill="#123345")
    draw.rounded_rectangle((122, 337, 902, 695), radius=62, outline="#2f6575", width=14)
    draw.ellipse((521, 353, 859, 691), fill="#091e2a", outline="#5ddfd5", width=24)
    draw.ellipse((590, 422, 790, 622), fill="#247e91")
    draw.ellipse((620, 452, 760, 592), fill="#80eee2")
    draw.ellipse((638, 461, 682, 505), fill="#e5fffb")
    for y in (438, 493, 548):
        draw.rounded_rectangle((179, y, 415, y + 19), radius=9, fill="#5b8995")
    draw.ellipse((182, 614, 210, 642), fill="#ffbd69")
    draw.rounded_rectangle((201, 730, 294, 791), radius=18, fill="#123345")
    draw.rounded_rectangle((728, 730, 821, 791), radius=18, fill="#123345")
    for offset in (0, 72):
        draw.arc((280 - offset, 84 - offset, 744 + offset, 548 + offset), 225, 315, fill="#e8a956", width=22)
    output = ROOT / "custom_components" / "pjlink_ir" / "brand"
    output.mkdir(exist_ok=True)
    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        image.resize((size, size), Image.Resampling.LANCZOS).save(output / name, optimize=True)
    print("Generated original 256/512 pixel brand assets")


if __name__ == "__main__":
    main()
