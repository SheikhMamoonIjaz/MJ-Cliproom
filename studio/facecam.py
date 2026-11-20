"""Pick the facecam side of a gameplay frame.

A face detector is used when OpenCV is installed. If it finds no face, or it is
not installed, the busiest corner is used instead.
"""
from .render import choose_facecam


def corner_of(x_center: float, width: float) -> str:
    """Map a face's horizontal center to the left, middle, or right third."""
    if width <= 0:
        return "left"
    ratio = x_center / width
    if ratio < 0.34:
        return "left"
    if ratio > 0.66:
        return "right"
    return "center"


def detect_faces(gray):
    """Return (x, y, w, h) boxes. Empty when OpenCV or the cascade is missing."""
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return []
    try:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            return []
        boxes = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24))
    except Exception:  # noqa: BLE001
        return []
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in boxes]


def _frame(src, second: float):
    """Read a small grayscale frame with padding to keep its aspect ratio."""
    try:
        import numpy as np
        from .media import NO_WINDOW
        import subprocess
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{max(0, float(second)):.2f}", "-i", str(src),
             "-frames:v", "1", "-vf", "scale=320:180:force_original_aspect_ratio=decrease,"
             "pad=320:180:(ow-iw)/2:(oh-ih)/2", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            capture_output=True, timeout=20, creationflags=NO_WINDOW).stdout
        if len(raw) < 320 * 180:
            return None
        return np.frombuffer(raw[:320 * 180], dtype=np.uint8).reshape(180, 320)
    except Exception:  # noqa: BLE001
        return None


def sample_corner(src, second: float):
    """Return the face side or busiest side when a frame is available."""
    gray = _frame(src, second)
    if gray is None:
        return None
    corners = {}
    height, width = gray.shape
    for name, x0, x1 in (("left", 0, width // 3), ("center", width // 3, 2 * width // 3), ("right", 2 * width // 3, width)):
        corners[name] = float(gray[:, x0:x1].std())
    return pick_facecam(gray, corners)


def find_center(src, second, width, height):
    """Locate a face in the recording and return its center in source coordinates."""
    if width <= 0 or height <= 0:
        return None
    frame = _frame(src, second)
    boxes = detect_faces(frame) if frame is not None else []
    if not boxes:
        return None
    x, y, w, h = max(boxes, key=lambda box: box[2] * box[3])
    scale = min(320 / width, 180 / height)
    cx = (x + w / 2 - (320 - width * scale) / 2) / (width * scale)
    cy = (y + h / 2 - (180 - height * scale) / 2) / (height * scale)
    return max(0, min(1, cx)), max(0, min(1, cy))


def pick_facecam(gray, corners=None) -> str:
    """Face first, then the busiest corner."""
    boxes = detect_faces(gray) if gray is not None else []
    if boxes and gray is not None:
        width = int(getattr(gray, "shape", [0, 0])[1] or 0)
        best = max(boxes, key=lambda box: box[2] * box[3])
        return corner_of(best[0] + best[2] / 2, width or 1)
    return choose_facecam(corners or {})
