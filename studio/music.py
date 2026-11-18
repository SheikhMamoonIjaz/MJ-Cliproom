"""Per-user instrumental background tracks for rendered clips.

Tracks are supplied by the account owner. The app never downloads or bundles trending songs.
"""
import json
import re
import secrets
import shutil
import threading
from pathlib import Path

from . import config, ctx, media

_lock = threading.RLock()
_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}
MAX_TRACKS = 30
MAX_TRACK_BYTES = 30 * 1024 * 1024
MAX_TRACK_SECONDS = 30 * 60
LICENSES = {
    "owner": "You supplied this track and confirm you can use it.",
    "cc0": "CC0. No attribution required.",
    "cc-by": "CC BY. Keep the attribution with the video.",
    "pixabay": "Pixabay Content License. Royalty-free.",
    "youtube-audio-library": "YouTube Audio Library. Follow that track's attribution rule.",
    "ncs": "NoCopyrightSounds. Keep the NCS credit.",
}
GENRES = ("electronic", "hiphop", "rock", "ambient", "cinematic", "lofi", "pop", "other")
MOODS = ("hype", "chill", "funny", "tense", "epic", "happy")
SOURCES = [
    {"id": "owner", "name": "Your licensed tracks", "url": "", "license": "owner",
     "note": "Upload music you own or have a license for. Chart songs are refused."},
    {"id": "pixabay", "name": "Pixabay Music", "url": "https://pixabay.com/music/", "license": "pixabay",
     "note": "Royalty-free tracks. Set PEAKCUT_PIXABAY_KEY to search them. Audio is not bundled here."},
    {"id": "youtube-audio-library", "name": "YouTube Audio Library", "url": "https://studio.youtube.com/",
     "license": "youtube-audio-library", "note": "Download from YouTube Studio, then upload the file here."},
    {"id": "ncs", "name": "NoCopyrightSounds", "url": "https://ncs.io/music", "license": "ncs",
     "note": "Download the instrumental yourself and keep the NCS credit."},
]


def _root() -> Path:
    path = config.user_dir(ctx.uid()) / "music"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest() -> Path:
    return _root() / "tracks.json"


def _all() -> list:
    try:
        rows = json.loads(_manifest().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        track_id = str(row.get("id", ""))
        filename = str(row.get("file", ""))
        ext = Path(filename).suffix.lower()
        if (re.fullmatch(r"[0-9a-f]{16}", track_id) and ext in _EXTENSIONS
                and filename == track_id + ext):
            clean.append(row)
    return clean


def _save(rows: list):
    path = _manifest()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    temp.replace(path)
    ctx.bump()


def clean_meta(meta) -> dict:
    """Only royalty-free or owner-licensed tracks. Anything else is refused."""
    meta = meta or {}
    license_id = str(meta.get("license") or "owner").lower().replace("_", "-")
    license_id = {"royalty-free": "cc0", "royaltyfree": "cc0", "nocopyright": "cc0"}.get(license_id, license_id)
    if license_id not in LICENSES:
        raise ValueError("Only royalty-free or owner-licensed tracks can be added. Chart songs are not accepted.")
    genre = str(meta.get("genre") or "other").lower()
    mood = str(meta.get("mood") or "hype").lower()
    if genre not in GENRES:
        genre = "other"
    if mood not in MOODS:
        mood = "hype"
    attribution = str(meta.get("attribution") or LICENSES[license_id]).strip()[:400]
    if license_id in ("cc-by", "ncs") and len(attribution) < 12:
        raise ValueError("This license needs an attribution line of at least a few words.")
    rights = meta.get("rights")
    if rights is not True and str(rights).lower() not in ("1", "true", "on", "yes"):
        raise ValueError("Tick the box to confirm you have the rights to use this track.")
    return {"license": license_id, "genre": genre, "mood": mood, "attribution": attribution, "rights": True}


def _public(row) -> dict:
    return {"id": row["id"], "name": row.get("name") or "Track", "duration": row.get("duration"),
            "size": row.get("size"), "genre": row.get("genre") or "other", "mood": row.get("mood") or "hype",
            "license": row.get("license") or "owner", "attribution": row.get("attribution") or LICENSES["owner"],
            "rights": row.get("rights") is True}


def list_tracks() -> list:
    rows = _all()
    return [_public(row) for row in rows if (_root() / row.get("file", "")).is_file()]


def catalog() -> dict:
    return {"sources": SOURCES, "licenses": LICENSES, "genres": list(GENRES), "moods": list(MOODS),
            "note": "Only royalty-free or owner-licensed music is accepted. Chart songs are not searched or stored."}


def parse_pixabay(data) -> list:
    """Turn a Pixabay audio response into tagged, attributed tracks. No other host is accepted."""
    found = []
    for hit in (data or {}).get("hits") or []:
        if not isinstance(hit, dict):
            continue
        audio = str(hit.get("audio") or hit.get("url") or "")
        if not audio_host_ok(audio):
            continue
        tags = [part.strip() for part in str(hit.get("tags") or "").split(",") if part.strip()]
        blob = " ".join(tags).lower()
        genre = "electronic" if any(word in blob for word in ("electro", "edm", "synth")) else "ambient" if "ambient" in blob else "other"
        mood = "chill" if any(word in blob for word in ("chill", "ambient", "soft")) else "hype"
        found.append({"name": (tags[0] if tags else "Pixabay track")[:80], "genre": genre,
                      "mood": mood, "license": "pixabay",
                      "attribution": f"Music from Pixabay by {str(hit.get('user') or 'Pixabay')[:60]}.",
                      "preview": audio, "duration": hit.get("duration")})
    return found


def audio_host_ok(url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host == "cdn.pixabay.com" or host.endswith(".pixabay.com")


def get(track_id: str):
    if not re.fullmatch(r"[0-9a-f]{16}", str(track_id or "")):
        return None
    row = next((row for row in _all() if row["id"] == track_id), None)
    path = _root() / row["file"] if row else None
    return {**row, "path": path} if row and path.is_file() else None


def _inside(folder: Path, root: Path) -> bool:
    try:
        folder.relative_to(root)
        return True
    except ValueError:
        return False


def allowed_library(path) -> Path:
    """A folder the owner may scan: their home, the data folder, or PEAKCUT_MUSIC_DIR."""
    folder = Path(path).expanduser()
    if not folder.is_absolute():
        raise ValueError("Type the full path of the music folder.")
    folder = folder.resolve()
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Choose a real music folder, not a link.")
    roots = [Path.home().resolve(), config.DATA_DIR.resolve()]
    extra = config.env("PEAKCUT_MUSIC_DIR")
    if extra:
        roots.append(Path(extra).expanduser().resolve())
    if not any(_inside(folder, root) for root in roots):
        raise ValueError("The music folder has to be inside your home folder, the data folder, or PEAKCUT_MUSIC_DIR.")
    return folder


def scan_folder(path, rights=False) -> dict:
    """Copy audio files from a local folder into this account's library."""
    if rights is not True and str(rights).lower() not in ("1", "true", "on", "yes"):
        raise ValueError("Tick the box to confirm you have the rights to every track in that folder.")
    folder = allowed_library(path)
    added, skipped = [], []
    seen = 0
    for file in sorted(folder.rglob("*")):
        if seen >= 200:
            break
        if not file.is_file() or file.is_symlink() or file.suffix.lower() not in _EXTENSIONS:
            continue
        if len(file.relative_to(folder).parts) > 3:
            continue
        seen += 1
        try:
            added.append(add(file, file.name, {"license": "owner", "rights": True,
                                               "attribution": "Added from the owner's music folder."}))
        except ValueError as exc:
            skipped.append({"name": file.name[:80], "reason": str(exc)[:160]})
        if len(added) >= MAX_TRACKS:
            break
    return {"added": added, "skipped": skipped[:20]}


def add(source: Path, filename: str, meta=None) -> dict:
    """Validate a short audio-only file and store it in the current user's music folder."""
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
        raise ValueError("Choose an audio-only file, not a video or audio/video file.")
    try:
        duration = float((info.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if not 0 < duration <= MAX_TRACK_SECONDS:
        raise ValueError("Music tracks must be 30 minutes or shorter.")
    clean = re.sub(r"[^\w .()\-]", "", Path(filename).stem).strip(" .")[:80] or "Instrumental track"
    fields = clean_meta(meta)
    with _lock:
        rows = _all()
        if len(rows) >= MAX_TRACKS:
            raise ValueError(f"Keep up to {MAX_TRACKS} background tracks in your library.")
        track_id = secrets.token_hex(8)
        stored_name = track_id + ext
        dest = _root() / stored_name
        shutil.copyfile(source, dest)
        try:
            dest.chmod(0o600)
        except OSError:
            pass
        row = {"id": track_id, "name": clean, "file": stored_name, "duration": round(duration, 2),
               "size": dest.stat().st_size, **fields}
        _save(rows + [row])
    return _public(row)


def delete(track_id: str):
    with _lock:
        track = get(track_id)
        if not track:
            return False
        from . import jobs
        if any(clip.get("music_id") == track_id for job in jobs.list_jobs() for clip in job.get("clips", [])):
            raise ValueError("Remove this track from its clips and save them before deleting it.")
        rows = [row for row in _all() if row["id"] != track_id]
        track["path"].unlink(missing_ok=True)
        _save(rows)
    return True
