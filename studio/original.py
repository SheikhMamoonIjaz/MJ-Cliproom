"""Original MJ Plays GTA shorts.

These videos are slides and the owner's own words. They do not use another
creator's footage, so they can post without a third-party rights clearance.
"""
import re
import shutil
import subprocess
from pathlib import Path


def script(topic: str = "") -> str:
    """A short original narration. It does not invent a gameplay event."""
    note = " ".join(str(topic or "").split())[:240]
    lines = [
        "This is an original update from MJ Plays GTA.",
        "No one else's stream or recording is in this video.",
        note or "We are following the GTA 6 launch and only clip footage we are allowed to use.",
        "Tell us what you want explained next.",
    ]
    text = " ".join(lines)
    text = re.sub(r"\bgta\s*(?:5|v)\b", "GTA 6", text, flags=re.I)
    return text


def speak(text: str, wav: Path) -> bool:
    """Write narration with espeak when the machine has it. Otherwise the words stay on screen."""
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        return False
    wav.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([exe, "-w", str(wav), text[:500]], capture_output=True, timeout=30)
    return result.returncode == 0 and wav.is_file() and wav.stat().st_size > 44


def build(dest: Path, text: str, voice: Path = None, music: Path = None) -> Path:
    """A vertical mp4 of the original script. Uses the owner voice file when one is passed."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    from .thumbs import draw_thumbnail
    still = dest.with_suffix(".jpg")
    draw_thumbnail(still, text[:90], wide=False, streamer="MJ Plays GTA")
    spoken = dest.with_suffix(".wav")
    has_voice = voice and Path(voice).is_file()
    if not has_voice and speak(text, spoken):
        voice = spoken
        has_voice = True
    cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(still), "-t", "12"]
    if has_voice:
        cmd += ["-i", str(voice)]
    elif music and Path(music).is_file():
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
    cmd += ["-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(dest)]
    subprocess.run(cmd, check=True, timeout=60)
    return dest
