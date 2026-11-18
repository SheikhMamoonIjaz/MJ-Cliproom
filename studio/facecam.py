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


def sample_corner(src, second: float):
    """One grayscale frame, then a face or the busiest side. None when the frame cannot be read."""
    try:
        import numpy as np
        from .media import NO_WINDOW
        import subprocess
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{max(0, float(second)):.2f}", "-i", str(src),
             "-frames:v", "1", "-vf", "scale=160:90", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            capture_output=True, timeout=20, creationflags=NO_WINDOW).stdout
        if len(raw) < 160 * 90:
            return None
        gray = np.frombuffer(raw[:160 * 90], dtype=np.uint8).reshape(90, 160)
    except Exception:  # noqa: BLE001
        return None
    corners = {}
    height, width = gray.shape
    for name, x0, x1 in (("left", 0, width // 3), ("center", width // 3, 2 * width // 3), ("right", 2 * width // 3, width)):
        corners[name] = float(gray[:, x0:x1].std())
    return pick_facecam(gray, corners)


def pick_facecam(gray, corners=None) -> str:
    """Face first, then the busiest corner."""
    boxes = detect_faces(gray) if gray is not None else []
    if boxes and gray is not None:
        width = int(getattr(gray, "shape", [0, 0])[1] or 0)
        best = max(boxes, key=lambda box: box[2] * box[3])
        return corner_of(best[0] + best[2] / 2, width or 1)
    return choose_facecam(corners or {})
