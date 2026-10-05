"""Dev-only script using Pillow to generate banner art from the Amadeus logo."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def load_and_preprocess(image_path: Path, dark_threshold: int = 140) -> Image.Image:
    """Load image, composite transparency on white, invert dark pixels to foreground, auto-crop."""
    orig = Image.open(image_path).convert("RGBA")
    # Composite transparent pixels on pure white
    bg = Image.new("RGBA", orig.size, (255, 255, 255, 255))
    comp = Image.alpha_composite(bg, orig).convert("L")

    # Dark logo pixels -> foreground (255), light background -> 0
    inv = comp.point(lambda p: 255 if p < dark_threshold else 0)

    # Auto-crop margins
    bbox = inv.getbbox()
    if bbox:
        return inv.crop(bbox)
    return inv


def render_braille(cropped: Image.Image, cols: int, bin_threshold: int = 70) -> str:
    """Convert binary PIL image to Unicode Braille art.

    Each braille cell is 2 dots wide x 4 dots tall.
    Width in dots: cols * 2. Height proportional to preserve aspect ratio.
    """
    target_w = cols * 2
    target_h = max(4, int(cropped.height * (target_w / cropped.width)))
    resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)
    binary = resized.point(lambda p: 255 if p >= bin_threshold else 0)

    pw = (target_w + 1) // 2 * 2
    ph = (target_h + 3) // 4 * 4
    canvas = Image.new("L", (pw, ph), 0)
    canvas.paste(binary, (0, 0))
    pixels = canvas.load()

    lines: list[str] = []
    for y in range(0, ph, 4):
        row_chars: list[str] = []
        for x in range(0, pw, 2):
            val = 0
            if pixels[x, y] > 0:
                val |= 0x01
            if pixels[x, y + 1] > 0:
                val |= 0x02
            if pixels[x, y + 2] > 0:
                val |= 0x04
            if pixels[x + 1, y] > 0:
                val |= 0x08
            if pixels[x + 1, y + 1] > 0:
                val |= 0x10
            if pixels[x + 1, y + 2] > 0:
                val |= 0x20
            if pixels[x, y + 3] > 0:
                val |= 0x40
            if pixels[x + 1, y + 3] > 0:
                val |= 0x80
            row_chars.append(chr(0x2800 + val) if val else " ")
        lines.append("".join(row_chars).rstrip())

    # Strip empty lines from top and bottom
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    # Trim isolated single dots at top/bottom boundary if any
    while lines and len(lines[0].strip()) == 1 and lines[0].strip() in ("⠈", "⠐", "⠁", "⠄"):
        lines.pop(0)
    while lines and len(lines[-1].strip()) == 1 and lines[-1].strip() in ("⠈", "⠐", "⠁", "⠄"):
        lines.pop()

    return "\n".join(lines)


def render_halfblocks(cropped: Image.Image, cols: int, bin_threshold: int = 110) -> str:
    """Convert binary PIL image to half-block art (▀, ▄, █)."""
    target_w = cols
    target_h = max(2, int(cropped.height * (target_w / cropped.width) * 2))
    resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)
    binary = resized.point(lambda p: 255 if p >= bin_threshold else 0)

    ph = (target_h + 1) // 2 * 2
    canvas = Image.new("L", (target_w, ph), 0)
    canvas.paste(binary, (0, 0))
    pixels = canvas.load()

    lines: list[str] = []
    for y in range(0, ph, 2):
        row_chars: list[str] = []
        for x in range(target_w):
            top = pixels[x, y] > 0
            bot = pixels[x, y + 1] > 0
            if top and bot:
                row_chars.append("█")
            elif top:
                row_chars.append("▀")
            elif bot:
                row_chars.append("▄")
            else:
                row_chars.append(" ")
        lines.append("".join(row_chars).rstrip())

    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Amadeus banner art.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("assets/amadeus_logo.png"),
        help="Path to logo image.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=60,
        help="Column width for main banner (default: 60).",
    )
    parser.add_argument(
        "--small-width",
        type=int,
        default=34,
        help="Column width for small banner (default: 34).",
    )
    parser.add_argument(
        "--mode",
        choices=["braille", "halfblock"],
        default="braille",
        help="Rendering mode (default: braille).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=70,
        help="Binarization threshold for main banner (default: 70).",
    )
    parser.add_argument(
        "--small-threshold",
        type=int,
        default=80,
        help="Binarization threshold for small banner (default: 80).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    input_path = args.input if args.input.is_absolute() else repo_root / args.input
    assets_dir = repo_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    cropped = load_and_preprocess(input_path)

    if args.mode == "braille":
        banner_main = render_braille(cropped, args.width, args.threshold)
        banner_small = render_braille(cropped, args.small_width, args.small_threshold)
    else:
        banner_main = render_halfblocks(cropped, args.width, args.threshold)
        banner_small = render_halfblocks(cropped, args.small_width, args.small_threshold)

    banner_file = assets_dir / "banner.txt"
    banner_small_file = assets_dir / "banner_small.txt"

    banner_file.write_text(banner_main, encoding="utf-8")
    banner_small_file.write_text(banner_small, encoding="utf-8")
    print(f"Generated {banner_file} ({args.width} cols)")
    print(f"Generated {banner_small_file} ({args.small_width} cols)")


if __name__ == "__main__":
    main()
