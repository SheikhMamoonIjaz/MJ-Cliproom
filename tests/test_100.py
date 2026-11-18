"""1.0.0 editor cuts, music rights, and the dependency list."""
import os
import sys
import tempfile
import wave
from pathlib import Path

os.environ.setdefault("PEAKCUT_DATA", tempfile.mkdtemp(prefix="pc-100-"))
os.environ.setdefault("DATABASE_URL", "")
sys.path.insert(0, ".")

from studio import ctx, editor, music, server

fails = []


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    if not ok:
        fails.append(name)


check("the release version has no beta label", server.VERSION, "1.0.1")
rows = editor.validate_segments([{"start": 0, "end": 10, "speed": 2}], 20)
check("double speed halves the cut length", editor.cut_length(rows), 5.0)
parts = editor.split_segments([{"start": 0, "end": 10}], 4)
check("a cut splits into two pieces", (len(parts), parts[0]["end"], parts[1]["start"]), (2, 4.0, 4.0))
check("the next piece merges back", editor.merge_segments(parts, 0)[0]["end"], 10)
moved = editor.move_segment([{"start": 1, "end": 4}, {"start": 6, "end": 9}], 0, 1)
check("cuts can be reordered", moved[0]["start"], 6)
try:
    editor.split_segments([{"start": 0, "end": 10}], 0.1)
    check("a split on the edge is refused", False)
except ValueError:
    check("a split on the edge is refused", True)

ok = music.clean_meta({"license": "owner"})
check("a track does not need a rights tick", ok["license"], "owner")
ok = music.clean_meta({"license": "owner", "rights": True})
check("a confirmed track is stored as owner-licensed", ok["rights"] is True and ok["license"] == "owner")
try:
    music.allowed_library("/etc")
    check("a system folder is not a music library", False)
except ValueError:
    check("a system folder is not a music library", True)

library = Path(os.environ["PEAKCUT_DATA"]) / "library"
library.mkdir()
tone = library / "tone.wav"
with wave.open(str(tone), "w") as handle:
    handle.setnchannels(1)
    handle.setsampwidth(2)
    handle.setframerate(16000)
    handle.writeframes(b"\x00\x00" * 16000)
with ctx.as_user("u_local"):
    found = music.scan_folder(str(library), True)
check("the folder scan adds the wav", found["added"][0]["rights"] is True and found["added"][0]["name"] == "tone")

root = Path("requirements.txt").read_text(encoding="utf-8").lower()
needed = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "httpx": "httpx", "numpy": "numpy",
    "sqlalchemy": "sqlalchemy", "soundfile": "soundfile", "pil": "pillow",
    "cv2": "opencv-python-headless", "yt_dlp": "yt-dlp", "sherpa_onnx": "sherpa-onnx",
}
missing = [pkg for pkg in needed.values() if pkg not in root]
check("requirements cover the libraries the app imports", missing, [])

if fails:
    print(f"\n{len(fails)} FAILED")
    sys.exit(1)
print("\nall 1.0 checks passed")
