"""Cover frames and styled thumbnails.

The cover is the loudest or busiest moment inside the clip, not a fixed second.
A styled card can be drawn for a 1280x720 long-form thumbnail or a vertical Short.
"""
from pathlib import Path


def peak_time(levels, start: float, end: float) -> float:
    """The second inside the clip with the highest motion or loudness."""
    try:
        start_i, end_i = int(start), max(int(start) + 1, int(end))
    except (TypeError, ValueError):
        return 0.0
    window = list(levels or [])[start_i:end_i]
    if not window:
        return float(start or 0)
    hottest = max(range(len(window)), key=lambda index: float(window[index] or 0))
    return round(start_i + hottest + 0.5, 2)


def draw_thumbnail(path: Path, hook: str, *, wide: bool = True, streamer: str = "") -> Path:
    """A branded still. Wide is 1280x720. A Short cover is 1080x1920."""
    from PIL import Image, ImageDraw, ImageFont
    width, height = (1280, 720) if wide else (1080, 1920)
    image = Image.new("RGB", (width, height), (18, 22, 34))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 18), fill=(90, 200, 255))
    font = ImageFont.load_default()
    title = (hook or "GTA 6").strip()[:80]
    draw.text((48, height * 0.38), title, fill=(255, 255, 255), font=font)
    draw.text((48, height - 80), "MJ PLAYS GTA", fill=(215, 241, 255), font=font)
    if streamer:
        draw.text((48, height - 120), str(streamer)[:40], fill=(200, 210, 220), font=font)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=88)
    return path
