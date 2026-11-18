"""Optional original narration for a clip.

YouTube can treat a reposted moment as reused content unless the upload adds something of your own.
A commentary track is the owner's own voice, mixed on top of the stream audio. It is never fetched
from the internet and it does not replace the picture, so a creator's on-screen watermark stays.
"""
import json
import re
import secrets
import shutil
import threading
from pathlib import Path

from . import config, ctx, media

MAX_TRACK_BYTES = 30 * 1024 * 1024
MAX_TRACK_SECONDS = 30 * 60
_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}
_lock = threading.RLock()


def _root() -> Path:
    d = config.user_dir(ctx.uid()) / "commentary"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest() -> Path:
    return _root() / "manifest.json"


def _all() -> list:
    try:
        rows = json.loads(_manifest().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def _save(rows: list):
    tmp = _manifest().with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    tmp.replace(_manifest())


def list_tracks() -> list:
    return [{k: row[k] for k in ("id", "name", "duration", "size") if k in row}
            for row in _all() if (_root() / row.get("file", "")).is_file()]


def get(track_id: str):
    if not re.fullmatch(r"[0-9a-f]{16}", str(track_id or "")):
        return None
    row = next((row for row in _all() if row["id"] == track_id), None)
    path = _root() / row["file"] if row else None
    return {**row, "path": path} if row and path.is_file() else None


def add(source: Path, filename: str) -> dict:
    """Store one audio-only narration file. The picture of the clip is left alone."""
    source = Path(source)
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_TRACK_BYTES:
        raise ValueError("Choose an audio file no larger than 30 MB.")
    ext = Path(filename or "").suffix.lower()
    if ext not in _EXTENSIONS:
        raise ValueError("Use an MP3, M4A, AAC, WAV, FLAC, OGG or OPUS audio file.")
    try:
        info = json.loads(media.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                                     "-show_streams", str(source)], timeout=30))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("That file could not be read as audio.") from exc
    streams = info.get("streams") or []
    has_audio = any(item.get("codec_type") == "audio" for item in streams)
    has_video = any(item.get("codec_type") == "video" and not (item.get("disposition") or {}).get("attached_pic")
                    for item in streams)
    if not has_audio or has_video:
        raise ValueError("Choose an audio-only file, not a video.")
    try:
        duration = float((info.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if not 0 < duration <= MAX_TRACK_SECONDS:
        raise ValueError("Commentary tracks must be 30 minutes or shorter.")
    clean = re.sub(r"[^\w .()\-]", "", Path(filename).stem).strip(" .")[:80] or "Commentary"
    with _lock:
        rows = _all()
        if len(rows) >= 20:
            raise ValueError("Keep up to 20 commentary tracks.")
        track_id = secrets.token_hex(8)
        stored = track_id + ext
        dest = _root() / stored
        shutil.copyfile(source, dest)
        try:
            dest.chmod(0o600)
        except OSError:
            pass
        row = {"id": track_id, "name": clean, "file": stored, "duration": round(duration, 2),
               "size": dest.stat().st_size}
        _save(rows + [row])
    return {k: row[k] for k in ("id", "name", "duration", "size")}


def delete(track_id: str) -> bool:
    with _lock:
        track = get(track_id)
        if not track:
            return False
        rows = [row for row in _all() if row["id"] != track_id]
        track["path"].unlink(missing_ok=True)
        _save(rows)
        return True
