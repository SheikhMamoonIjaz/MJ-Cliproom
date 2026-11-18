"""Job pipeline: get video -> audio -> transcript -> AI picks -> rendered clips. One heavy task at a time."""
import collections
import json
import os
import math
import queue
import re
import shutil
import statistics
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import brain, config, creators, ctx, editor, load, media, render, roman, safe, transcribe, usage

class _FairQueue:
    """Whose video is next. Each person has their own line and the lines take turns, so someone who adds ten
    videos does not make everyone else wait behind all ten. Small tasks (re-making one clip) go first."""

    def __init__(self):
        self.cv = threading.Condition()
        self.quick = collections.deque()
        self.lines = {}                       # user -> their waiting videos, oldest first
        self.turn = collections.deque()       # users with something waiting, in the order they will be served
        self.epoch = 0                        # goes up whenever the line moves
        self._pos = (0.0, {})
        self.running = 0                      # videos being worked on right now
        self.last_start = 0.0
        self.held = False                     # videos are waiting only because the machine is near full

    def _room(self) -> bool:
        """May one more video start? One always may. More only while the machine has room, and a few seconds
        after the last one started, so its weight is already showing in the measurements."""
        if self.running == 0:
            return True
        return self.running < config.JOB_WORKERS and time.time() - self.last_start > 6 and not load.busy()

    def done(self):
        with self.cv:
            self.running = max(0, self.running - 1)
            self.cv.notify_all()

    def put(self, item, user=None):
        with self.cv:
            if user is None:
                self.quick.append(item)
            else:
                if user not in self.lines:
                    self.lines[user] = collections.deque()
                    self.turn.append(user)
                self.lines[user].append(item)
            self.epoch += 1
            self.cv.notify()

    def get(self, quick_only=False):
        with self.cv:
            while True:
                if self.quick:
                    self.epoch += 1
                    return self.quick.popleft()
                if not quick_only and self.turn:
                    if self._room():
                        break
                    if not self.held:
                        self.held = True
                        self.epoch += 1
                elif self.held:
                    self.held = False
                    self.epoch += 1
                self.cv.wait(1.0)             # looked at again every second: the line moves the moment there is room
            self.epoch += 1
            self.held = False
            self.running += 1
            self.last_start = time.time()
            user = self.turn.popleft()
            item = self.lines[user].popleft()
            if self.lines[user]:
                self.turn.append(user)
            else:
                del self.lines[user]
            return item

    def ahead(self) -> dict:
        """job id -> how many videos will start before it. Worked out at most once a second."""
        with self.cv:
            if time.time() - self._pos[0] < 1:
                return self._pos[1]
            out, lines, order, n = {}, {u: list(q) for u, q in self.lines.items()}, list(self.turn), 0
            depth = 0
            while order:
                nxt = []
                for u in order:
                    if depth < len(lines[u]):
                        out[lines[u][depth][1]] = n
                        n += 1
                        if depth + 1 < len(lines[u]):
                            nxt.append(u)
                order, depth = nxt, depth + 1
            self._pos = (time.time(), out)
            return out


_q = _FairQueue()
_live_q: "queue.Queue" = queue.Queue()   # live clips never wait behind a long video
_jobs: dict = {}
_by_user: dict = {}                       # user -> {job id: job}: listing one person's videos never scans everyone's
_cancel_events: dict = {}
_lock = threading.RLock()
on_clip_ready: list = []   # callbacks (job, clip), run once when a clip first finishes

DEFAULTS = {"max_clips": 6, "min_len": 15, "max_len": 60, "style": "bounce", "layout": "blur", "quality": 720,
            "range_start": None, "range_end": None, "mode": "news", "motion": "none", "watermark": False,
            "ai_post_text": False}


LIMITS = {"max_clips": (1, 20), "min_len": (5, 120), "max_len": (10, 180), "quality": (360, 1080)}


def clean_options(options) -> dict:
    """Only known settings, each inside its allowed range. Raises ValueError on nonsense."""
    out = {}
    for k, v in (options if isinstance(options, dict) else {}).items():
        if k not in DEFAULTS or v in ("", None):
            continue
        if k in LIMITS:
            lo, hi = LIMITS[k]
            v = max(lo, min(hi, int(float(v))))
        elif k == "style":
            v = v if v in render.STYLES else DEFAULTS["style"]
        elif k == "layout":
            v = v if v in render.LAYOUTS else DEFAULTS["layout"]
        elif k == "mode":
            if v not in ("news", "gameplay", "manual"):
                raise ValueError("Choose News, Gameplay, or Manual.")
        elif k == "motion":
            if v not in ("none", "highlight"):
                raise ValueError("Choose a motion graphics preset.")
        elif k in ("ai_post_text", "watermark"):
            if not isinstance(v, bool):
                raise ValueError("Clip export switches must be on or off.")
        else:                                    # range_start, range_end: seconds into the video
            v = float(v)
            if not math.isfinite(v) or v < 0:
                raise ValueError("That part of the video isn't valid.")
        out[k] = v
    if out.get("range_end") is not None and out["range_end"] <= out.get("range_start", 0):
        raise ValueError("The end of the chosen part must be after its start.")
    return out


def job_dir(jid) -> Path:
    return Path(_jobs[jid]["dir"])


def _render_estimate(job):
    clips = job.get("clips", [])
    pending = [clip for clip in clips if clip.get("status") in ("queued", "rendering")]
    samples = [float(clip["render_seconds"]) for clip in clips
               if clip.get("status") == "done" and clip.get("render_seconds", 0) > 0][-7:]
    if not pending or not samples:
        return None, len(pending), None

    average = statistics.median(samples)
    active = [clip for clip in pending if clip["status"] == "rendering"]
    if not active:
        return None, len(pending), average
    now = time.time()
    active_remaining = max(
        max(0, average - (now - clip.get("render_started_at", now)))
        for clip in active
    )
    queued = len(pending) - len(active)
    eta = active_remaining + math.ceil(queued / len(active)) * average
    return max(0, round(eta)), len(pending), average


HIDDEN = ("dir", "user", "source_path", "recover", "gameplay_scan")


_GENERIC_POST_TITLES = {"", "clip", "untitled clip", "untitled", "manual clip", "gameplay clip"}


def _source_display(job):
    source = str(job.get("title") or job.get("source", {}).get("name") or "Gameplay session").strip()
    if job.get("source", {}).get("type") == "file":
        source = Path(source).stem
    return source.replace("_", " ").strip() or "Gameplay session"


def _is_old_generated_text(text, source=""):
    value = str(text or "").strip()
    if not value:
        return True
    if re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", value):
        return True
    if re.search(r"\bgameplay\s+(?:highlight|moment)\b|captured at", value, re.I):
        return True
    return bool(source and source.casefold() in value.casefold())


def post_metadata(job, clip, overrides=None) -> dict:
    """Return distinct post drafts without exposing source stream names or clip times."""
    values = dict(clip)
    if overrides:
        values.update({key: overrides[key] for key in ("title", "description", "hashtags") if key in overrides})
    source = _source_display(job)
    try:
        start = max(0, float(clip.get("start") or 0))
        end = max(start + 3, float(clip.get("end") or start + 30))
    except (TypeError, ValueError):
        start, end = 0, 30
    try:
        clip_index = next(i for i, row in enumerate(job.get("clips", []), 1) if row.get("id") == clip.get("id"))
    except StopIteration:
        clip_index = 1
    words = clip.get("fixed_words") if isinstance(clip.get("fixed_words"), list) else []
    transcript_bits = []
    for word in words:
        if not isinstance(word, dict):
            continue
        try:
            at = float(word.get("s", -1))
        except (TypeError, ValueError):
            continue
        if start <= at <= end and str(word.get("w", "")).strip():
            transcript_bits.append(str(word["w"]).strip())
    transcript = " ".join(transcript_bits)
    if not transcript:
        cues = clip.get("caption_cues") if isinstance(clip.get("caption_cues"), list) else []
        transcript = " ".join(str(cue.get("text", "")).strip() for cue in cues if isinstance(cue, dict))
    draft = brain.gameplay_post(source, start, end, transcript=transcript, use_ai=False,
                                clip_index=clip_index, hook=clip.get("hook", ""))

    title = str(values.get("title") or "").strip()
    if title.lower() in _GENERIC_POST_TITLES or _is_old_generated_text(title, source):
        title = draft["title"][:100]
    else:
        title = brain._post_text(title, source, job.get("uploader", ""), limit=100)[:100] or draft["title"][:100]

    description = str(values.get("description") or "").strip()
    if _is_old_generated_text(description, source):
        description = draft["description"]
    else:
        description = brain._post_text(description, source, job.get("uploader", ""), limit=2000) or draft["description"]
    raw_tags = values.get("hashtags")
    tags = []
    if isinstance(raw_tags, list):
        for value in raw_tags:
            tag = brain._post_text(str(value).lstrip("#"), source, job.get("uploader", ""), 30)
            tag = "".join(char for char in tag if char.isalnum() or char == "_")[:30]
            if tag and tag not in tags:
                tags.append(tag)
            if len(tags) == 8:
                break
    if not tags:
        tags = draft["hashtags"]
    credit = values.get("source_credit") if isinstance(values.get("source_credit"), dict) else None
    if credit and credit.get("name") and str(credit.get("url") or "").startswith("https://"):
        url = str(credit["url"]).strip()
        if url not in description:
            description = (description + f"\n\nSource: {str(credit['name']).strip()[:80]}\n{url}").strip()[:4000]
    return {"title": title, "description": description, "hashtags": tags}


def public(job) -> dict:
    """What the browser may see: no server paths, no owner id."""
    out = {k: v for k, v in job.items() if k not in HIDDEN}
    out["source"] = {k: v for k, v in job["source"].items() if k != "path"}
    now = time.time()
    out["clips"] = []
    for clip in job["clips"]:
        visible = {k: v for k, v in clip.items()
                   if k not in ("src", "fixed_words", "fixed_for", "caption_cues", "render_started_at")}
        visible.update(post_metadata(job, clip))
        if clip.get("status") == "rendering" and clip.get("render_started_at"):
            visible["render_elapsed_seconds"] = round(now - clip["render_started_at"])
        out["clips"].append(visible)
    render_eta, render_pending, average_render_seconds = _render_estimate(job)
    out["render_eta_seconds"] = render_eta
    out["render_pending_clips"] = render_pending
    if average_render_seconds is not None:
        for clip in out["clips"]:
            if clip.get("status") == "rendering":
                clip["render_eta_seconds"] = max(
                    0, round(average_render_seconds - clip.get("render_elapsed_seconds", 0))
                )
    out["can_edit_source"] = job.get("kind") == "video" and bool(job.get("source_path")) and bool(job.get("duration"))
    out["can_cancel_download"] = (job.get("status") == "queued" or
                                  job.get("status") == "running" and job.get("stage") == "Downloading the source video")
    out["can_schedule_source_deletion"] = (
        job.get("kind") == "video" and job.get("source", {}).get("type") == "url"
        and job.get("status") in ("queued", "running") and not job.get("source_deleted")
    )
    out["can_cancel_source_deletion"] = (
        bool(job.get("delete_source_when_done")) and job.get("status") in ("queued", "running", "error")
    )
    source_path = job.get("source_path")
    source = Path(source_path) if source_path else None
    out["can_delete_source"] = (
        job.get("kind") == "video" and job.get("source", {}).get("type") == "url"
        and job.get("status") == "done" and source is not None and source.is_file()
        and source.resolve().parent == Path(job["dir"]).resolve()
        and not any(c.get("status") in ("queued", "rendering") for c in job["clips"])
    )
    out["source_size_bytes"] = 0
    if out["can_delete_source"]:
        try:
            out["source_size_bytes"] = source.stat().st_size
        except OSError:
            out["can_delete_source"] = False
    ai = job.get("ai") or {}
    out["ai"] = {"tokens": ai.get("tokens", 0), "note": ai.get("note", ""), "used": bool(ai.get("model"))}   # never the model, never raw errors
    if job.get("status") == "queued":
        n = _q.ahead().get(job["id"])
        if n:
            out["stage"] = (f"High demand right now: {n} video{'s' if n != 1 else ''} ahead of yours" if _q.held else
                            f"Waiting in line: {n} video{'s' if n != 1 else ''} ahead of yours")
        elif n == 0 and _q.held:
            out["stage"] = "High demand right now: yours is next"
    return out


def _snapshot(obj, depth=0):
    """A plain copy so a clip list that changes mid-save cannot throw the write away."""
    if depth > 6:
        return str(obj)
    if isinstance(obj, dict):
        return {k: _snapshot(v, depth + 1) for k, v in list(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_snapshot(v, depth + 1) for v in list(obj)]
    return obj


def _known_creator(creator):
    """The creator id to store. Only an id this account already has, never the raw form text."""
    if not creator:
        return None
    match = re.fullmatch(r"[\w\-]{1,60}", str(creator))
    if not match:
        return None
    ident = match.group(0)
    row = creators.get(ident)
    if not row or row.get("id") != ident:
        return None
    return ident


def _job_folder(job) -> Path:
    """The job's own folder, and only when it stays inside that account's data folder."""
    root = config.user_dir(str(job.get("user") or "")).resolve()
    folder = Path(str(job.get("dir") or "")).resolve()
    folder.relative_to(root)
    if folder.is_symlink():
        raise ValueError("The job folder cannot be a link.")
    return folder


def _write_job(folder: Path, text: str):
    """Write job.json without following a link out of the job folder."""
    target = folder / "job.json"
    tmp = folder / "job.json.tmp"
    for path in (target, tmp):
        if path.is_symlink():
            raise ValueError("The job file cannot be a link.")
        path.resolve().relative_to(folder)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, target)


def save(job):
    ctx.bump(job.get("user"))
    with _lock:
        try:
            folder = _job_folder(job)
        except (OSError, ValueError):
            return
        text = None
        for _ in range(5):
            try:
                text = json.dumps(job, indent=1)
                break
            except RuntimeError:  # changed mid-dump by another thread
                time.sleep(0.05)
        if text is None:
            try:
                text = json.dumps(_snapshot(job), indent=1)
            except (TypeError, ValueError):
                return
        try:
            _write_job(folder, text)
        except (OSError, ValueError):
            return


def _set(job, **kw):
    with _lock:
        job.update(kw)
    save(job)


def _remap(path, folder: Path):
    """Paths saved before data moved into per-user folders (or on another machine): find the file by name."""
    if path and not Path(path).exists():
        cand = folder / Path(str(path).replace("\\", "/")).name
        if cand.exists():
            return str(cand)
    return path


def _load_file(f: Path, uid: str):
    try:
        job = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    job.update(dir=str(f.parent), user=uid)
    job.setdefault("kind", "video")
    job.setdefault("creator", None)
    job.setdefault("rights_cleared", False)
    if job.get("source_path"):
        job["source_path"] = _remap(job["source_path"], f.parent)
    if job.get("source", {}).get("path"):
        job["source"]["path"] = _remap(job["source"]["path"], f.parent)
    if job.get("status") in ("queued", "running") and job.get("kind") != "live" and job.get("rights_cleared") is not True:
        job.update(status="error", stage="Source rights confirmation required",
                   error="Confirm that you own or have permission to use this source, then retry the video.",
                   failed_stage="Source rights confirmation required", resume=False)
    elif job.get("status") in ("queued", "running") and job.get("kind") != "live":
        # Picked up again as soon as the server is back (jobs.start), from the last finished part of the transcript.
        job.update(status="queued", stage="Picking up where it stopped", error=None, resume=True)
    if job.get("status") == "live":
        job.update(status="done", stage="Recording paused by a server update", was_live=True)
    buffered = job.get("kind") == "live" and any((f.parent / "buffer").glob("*.ts"))
    for c in job.get("clips", []):
        if c.get("src"):
            c["src"] = _remap(c["src"], f.parent / "clips")
        if c.get("status") in ("rendering", "queued"):
            if job.get("rights_cleared") is not True:
                c.update(status="error", error="Confirm source rights before continuing this clip.")
            elif buffered and not c.get("src"):
                c["status"] = "queued"  # the stream is still on disk: live.recover() finishes these
                job["recover"] = True
            elif job.get("resume"):
                c["status"] = "queued"  # the video is being picked up again: this clip is made then
            elif job.get("kind") != "live" and (job.get("source_path") or (f.parent / "words.json").is_file()):
                c["status"] = "queued"  # a single clip being re-made: jobs.start() makes it again
                job.setdefault("remake", []).append(c["id"])
            else:
                c.update(status="error", error="Interrupted by a restart. Open it and press Save and re-make.")
    _jobs[job["id"]] = job
    _by_user.setdefault(uid, {})[job["id"]] = job
    _cancel_events[job["id"]] = threading.Event()


def load_user(uid: str):
    d = config.USERS_DIR / uid
    for f in list((d / "jobs").glob("*/job.json")) + list((d / "creators").glob("*/*/*/job.json")):
        _load_file(f, uid)


def load_all():
    for d in config.USERS_DIR.iterdir():
        if d.is_dir():
            load_user(d.name)


def all_jobs() -> list:
    """Every user's jobs. Only for background work; never send this to a browser."""
    with _lock:
        return list(_jobs.values())


def list_jobs():
    u = ctx.uid()
    with _lock:
        return sorted((dict(j) for j in _by_user.get(u, {}).values()), key=lambda j: -j["created"])


def get(jid):
    """The job, only if it belongs to whoever this code is running for."""
    job = _jobs.get(jid)
    return job if job and job["user"] == ctx.uid() else None


def busy_count() -> int:
    u = ctx.uid()
    return sum(1 for j in list(_by_user.get(u, {}).values()) if j["kind"] == "video" and j["status"] in ("queued", "running"))


def waiting_total() -> int:
    return sum(1 for j in list(_jobs.values()) if j["kind"] == "video" and j["status"] == "queued")


def queue_epoch() -> int:
    return _q.epoch


def running_now() -> int:
    return _q.running


def create(source: dict, options: dict, enqueue=True, creator=None, kind="video", rights_cleared=False, automation=None) -> dict:
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:10]
    creator_id = _known_creator(creator)
    c = creators.get(creator_id) if creator_id else None
    if c:
        d = creators.root(creator_id) / ("live" if kind == "live" else "videos") / jid
        base = {**DEFAULTS, **{k: c[k] for k in ("max_clips", "min_len", "max_len", "style", "layout")}}
    else:
        d, base, creator_id = config.user_dir(ctx.uid()) / "jobs" / jid, dict(DEFAULTS), None
    d.mkdir(parents=True)
    opts = {**base, **clean_options(options)}
    if opts["min_len"] >= opts["max_len"]:
        opts["min_len"] = max(5, opts["max_len"] - 5)
    job = {"id": jid, "user": ctx.uid(), "kind": kind, "creator": creator_id, "dir": str(d), "created": time.time(), "source": source,
           "options": opts, "status": "queued", "stage": "Waiting", "progress": 0.0,
           "title": source.get("name", ""), "uploader": "", "duration": 0, "clips": [], "error": None, "ai": {},
           "rights_cleared": rights_cleared, "rights_cleared_at": time.time() if rights_cleared else None}
    if automation:
        job["automation"] = automation
    with _lock:
        _jobs[jid] = job
        _by_user.setdefault(job["user"], {})[jid] = job
        _cancel_events[jid] = threading.Event()
    save(job)
    if enqueue:
        _q.put(("job", jid, None), user=job["user"])
    return job


def enqueue(job):
    save(job)
    _q.put(("job", job["id"], None), user=job["user"])


def submit(fn):
    """Run any heavy task (a render, a cleanup) on the single worker, in order."""
    _q.put(("fn", ctx.bind(fn), None))


def submit_live(fn):
    """Live-stream renders and cleanups: their own worker, so a long video can never hold them up."""
    _live_q.put(ctx.bind(fn))


def _live_worker():
    while True:
        fn = _live_q.get()
        try:
            fn()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def delete(jid):
    with _lock:
        job = _jobs.pop(jid, None)
        _cancel_events.pop(jid, None)
        if job:
            _by_user.get(job["user"], {}).pop(jid, None)
    if job:
        ctx.bump(job["user"])
        shutil.rmtree(job["dir"], ignore_errors=True)
    return bool(job)


def clip_changes(job, clip, changes):
    new = dict(clip)
    for k in ("start", "end"):
        if k in changes:
            new[k] = round(float(changes[k]), 3)
    if "src_offset" in clip:  # live clip: can only move inside the saved piece of stream
        new["start"] = max(new["start"], clip["src_offset"])
        new["end"] = min(new["end"], clip["src_end"])
    if not (math.isfinite(new["start"]) and math.isfinite(new["end"])) or new["start"] < 0:
        raise ValueError("Those times aren't valid.")
    if job.get("duration") and job.get("kind") == "video":
        new["end"] = min(new["end"], job["duration"])
    if "segments" in changes:
        if changes["segments"] and (clip.get("src") or not source_file(job)):
            raise ValueError("Multiple cuts need the full source video.")
        new["segments"] = editor.validate_segments(changes["segments"], job.get("duration") or 0)
    segments = new.get("segments") or []
    if segments:
        new["start"] = min(span["start"] for span in segments)
        new["end"] = max(span["end"] for span in segments)
    duration = editor.cut_length(segments) if segments else new["end"] - new["start"]
    if not 3 <= duration <= 180:
        raise ValueError("A clip can be 3 to 180 seconds long.")
    for k in ("hook", "title", "description", "style", "layout"):
        if k in changes:
            new[k] = str(changes[k])[:{"hook": 60, "title": 100, "description": 2000}.get(k, 20)]
    if new.get("style") not in render.STYLES:
        new["style"] = DEFAULTS["style"]
    if new.get("layout") not in render.LAYOUTS:
        new["layout"] = DEFAULTS["layout"]
    for k in ("crop_x", "crop_y"):
        if k in changes:
            value = float(changes[k])
            if not 0 <= value <= 1:
                raise ValueError("Crop position must be between 0 and 1.")
            new[k] = value
    if "captions" in changes:
        if changes["captions"] not in ("burn", "clean"):
            raise ValueError("Choose captions on video or clean video.")
        new["captions"] = changes["captions"]
    if "motion" in changes:
        if changes["motion"] not in ("none", "highlight"):
            raise ValueError("Choose a motion graphics preset.")
        new["motion"] = changes["motion"]
    if "watermark" in changes:
        if not isinstance(changes["watermark"], bool):
            raise ValueError("Choose whether to add the MJ watermark.")
        new["watermark"] = changes["watermark"]
    if "music_id" in changes:
        track_id = str(changes["music_id"] or "").strip()
        if track_id:
            from . import music
            if not music.get(track_id):
                raise ValueError("That background track is no longer in your library.")
        new["music_id"] = track_id
    if "music_volume" in changes:
        volume = float(changes["music_volume"])
        if not math.isfinite(volume) or not 0 <= volume <= 1:
            raise ValueError("Set background music volume between 0 and 100%.")
        new["music_volume"] = round(volume, 2)
    for key in ("music_fade_in", "music_fade_out"):
        if key in changes:
            fade = float(changes[key])
            if not math.isfinite(fade) or not 0 <= fade <= 5:
                raise ValueError("Fades can be from 0 to 5 seconds.")
            new[key] = round(fade, 2)
    if "music_offset" in changes:
        offset = float(changes["music_offset"])
        if not math.isfinite(offset) or not 0 <= offset <= 30 * 60:
            raise ValueError("The music start must be inside the track.")
        new["music_offset"] = round(offset, 2)
    if "caption_position" in changes:
        if changes["caption_position"] not in ("top", "middle", "bottom"):
            raise ValueError("Put captions at the top, middle, or bottom.")
        new["caption_position"] = changes["caption_position"]
    if "music_duck" in changes:
        if not isinstance(changes["music_duck"], bool):
            raise ValueError("Choose whether music should lower under the original audio.")
        new["music_duck"] = changes["music_duck"]
    if "crop_keyframes" in changes:
        new["crop_keyframes"] = editor.validate_keyframes(changes["crop_keyframes"], duration)
    elif new.get("crop_keyframes"):
        new["crop_keyframes"] = [point for point in new["crop_keyframes"] if point["time"] < duration]
    if "hashtags" in changes:
        if not isinstance(changes["hashtags"], str):
            raise ValueError("Enter hashtags as text.")
        tags = ["".join(x for x in tag if x.isalnum() or x == "_")[:30]
                for tag in changes["hashtags"][:500].replace(",", " ").split()]
        new["hashtags"] = list(dict.fromkeys(t for t in tags if t))[:8]
    if "caption_cues" in changes:
        new["caption_cues"] = editor.validate_cues(changes["caption_cues"], new["start"], new["start"] + duration)
    elif new.get("segments") != clip.get("segments") and clip.get("caption_cues") is not None:
        shift = new["start"] - clip["start"]
        new["caption_cues"] = [dict(c, start=c["start"] + shift, end=c["end"] + shift)
                               for c in clip["caption_cues"]]
    return new


def request_render(jid, cid, changes: dict):
    with _lock:
        job = _jobs[jid]
        clip = next(c for c in job["clips"] if c["id"] == cid)
        if job["status"] in ("queued", "running") or clip["status"] in ("queued", "rendering"):
            raise RuntimeError("This clip is still being made.")
        if job.get("source_deleted") and not clip.get("src"):
            raise RuntimeError("The original download was removed. Download the source again to re-make this clip.")
        clip.update(clip_changes(job, clip, changes), status="queued")
        save(job)
    _q.put(("clip", jid, cid))


def update_metadata(job, cid: str, changes: dict):
    """Save post text without forcing an expensive video re-render."""
    allowed = {key: value for key, value in changes.items() if key in ("title", "description", "hashtags")}
    if not allowed:
        raise ValueError("Choose a title, description or hashtags to save.")
    with _lock:
        if job["status"] in ("queued", "running"):
            raise RuntimeError("Wait for this video to finish before saving its post text.")
        clip = next((item for item in job["clips"] if item["id"] == cid), None)
        if not clip:
            raise ValueError("No such clip.")
        if clip.get("status") in ("queued", "rendering"):
            raise RuntimeError("Wait for this clip to finish before saving its post text.")
        if "title" in allowed:
            clip["title"] = str(allowed["title"])[:100]
        if "description" in allowed:
            clip["description"] = str(allowed["description"])[:2000]
        if "hashtags" in allowed:
            if not isinstance(allowed["hashtags"], str):
                raise ValueError("Enter hashtags as text.")
            tags = ["".join(x for x in tag.lstrip("#") if x.isalnum() or x == "_")[:30]
                    for tag in allowed["hashtags"][:500].replace(",", " ").split()]
            clip["hashtags"] = list(dict.fromkeys(tag for tag in tags if tag))[:8]
        clip.update(post_metadata(job, clip))
        sidecar = Path(job["dir"]) / "clips" / f"{cid}.json"
        if sidecar.parent.is_dir():
            sidecar.write_text(json.dumps({key: clip.get(key) for key in
                                           ("title", "description", "hashtags", "hook", "start", "end", "score")},
                                          indent=1), encoding="utf-8")
        save(job)
        return clip


def path_inside(path, root) -> bool:
    """True when a saved path stays inside the folder it belongs to, even if it is a shortcut."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return True


def source_file(job):
    path = job.get("source_path")
    if job.get("kind") == "video" and path and Path(path).is_file() and path_inside(path, job["dir"]):
        return Path(path)
    return None


def delete_source(job):
    with _lock:
        path = source_file(job)
        if (job.get("kind") != "video" or job.get("source", {}).get("type") != "url"
                or job.get("status") != "done" or path is None
                or path.resolve().parent != Path(job["dir"]).resolve()
                or any(c.get("status") in ("queued", "rendering") for c in job["clips"])):
            raise ValueError("The downloaded source can be removed after all clips finish.")
        path.unlink()
        job["source_path"] = None
        job["source_deleted"] = True
        job["delete_source_when_done"] = False
        save(job)


def set_source_deletion(job, enabled):
    if not isinstance(enabled, bool):
        raise ValueError("Choose whether to remove the source after clipping.")
    with _lock:
        if enabled:
            if (job.get("kind") != "video" or job.get("source", {}).get("type") != "url"
                    or job.get("status") not in ("queued", "running") or job.get("source_deleted")):
                raise ValueError("Automatic cleanup can be scheduled while a downloaded video is being processed.")
            job["delete_source_when_done"] = True
        else:
            job["delete_source_when_done"] = False
        save(job)


def cancel_download(job):
    with _lock:
        event = _cancel_events.setdefault(job["id"], threading.Event())
        if job.get("status") == "queued":
            event.set()
            job.update(status="cancelled", stage="Download cancelled", error=None, transfer=None)
            save(job)
            return
        if job.get("status") == "running" and job.get("stage") == "Downloading the source video":
            event.set()
            return
        raise ValueError("This download can no longer be cancelled.")


def finish_video(job, stage, took):
    _set(job, status="done", stage=stage, progress=1.0, took=took)
    if job.get("delete_source_when_done"):
        try:
            delete_source(job)
        except (OSError, ValueError):
            _set(job, delete_source_when_done=False,
                 source_cleanup_error="The clips are ready, but the downloaded source could not be removed.")


def create_manual(job, changes):
    with _lock:
        if job["status"] in ("queued", "running"):
            raise RuntimeError("Wait until the source is ready.")
        if not source_file(job) or not job.get("duration"):
            raise ValueError("The full source video is unavailable. Upload the file to trim it.")
        if len(job["clips"]) >= 100:
            raise ValueError("This video already has 100 clips.")
        clip = {"id": "clip-" + uuid.uuid4().hex[:10], "manual": True, "start": 0,
                "end": min(job["duration"], 30), "title": "Manual clip", "hook": "", "description": "",
                "hashtags": [], "highlight_words": [], "score": 0, "category": "other", "version": 0,
                "style": job["options"]["style"], "layout": job["options"]["layout"],
                "motion": job["options"].get("motion", "none"),
                "watermark": job["options"].get("watermark", False)}
        clip.update(clip_changes(job, clip, changes), status="queued")
        clip.update(post_metadata(job, clip))
        job["clips"].append(clip)
        save(job)
    _q.put(("clip", job["id"], clip["id"]))
    return clip


def retry(job):
    with _lock:
        if job["status"] != "error" or job.get("kind") != "video":
            raise ValueError("Only a stopped video can be retried.")
        if any(c["status"] in ("queued", "rendering") for c in job["clips"]):
            raise ValueError("Wait for the current clip render to finish.")
        job.update(status="queued", stage="Retrying video", error=None, failed_stage=None, resume=True)
        enqueue(job)


def read_words(job):
    path = Path(job["dir"]) / "words.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def editable_captions(job, clip):
    segments = clip.get("segments") or []
    end = clip["start"] + editor.cut_length(segments) if segments else clip["end"]
    if clip.get("caption_cues") is not None:
        return [dict(c, start=max(clip["start"], c["start"]), end=min(end, c["end"]))
                for c in clip["caption_cues"] if min(end, c["end"]) > max(clip["start"], c["start"])]
    words = editor.apply_glossary(clip.get("fixed_words") or read_words(job), editor.read_glossary())
    if segments:
        words = editor.stitch_words(words, segments, offset=clip["start"])
    return editor.caption_cues(words, clip["start"], end)


def render_one(job, clip, words):
    d = Path(job["dir"])
    clip["status"] = "rendering"
    clip["render_started_at"] = time.time()
    save(job)
    try:
        off = clip.get("src_offset", 0.0)
        src = Path(clip["src"]) if clip.get("src") else Path(job.get("source_path") or "")
        if not path_inside(src, job["dir"]):
            raise RuntimeError("That source file is outside this video's folder, so it was not opened.")
        if not clip.get("src"):
            clip["end"] = min(clip["end"], job["duration"])
        local = dict(clip, start=clip["start"] - off, end=clip["end"] - off,
                     hook=roman.to_roman(clip.get("hook") or ""), has_audio=job.get("has_audio"))
        if clip.get("music_id"):
            from . import music
            track = music.get(clip["music_id"])
            if not track:
                raise RuntimeError("The chosen background track is missing. Choose another track and re-make the clip.")
            local["music_path"] = str(track["path"])
        if clip.get("commentary_id"):
            from . import commentary
            voice = commentary.get(clip["commentary_id"])
            if voice:
                local["commentary_path"] = str(voice["path"])
        if clip.get("caption_cues") is not None:
            local["caption_cues"] = [dict(c, start=c["start"] - off, end=c["end"] - off)
                                    for c in clip["caption_cues"]]
        segments = clip.get("segments") or []
        span = [round(clip["start"], 2), round(clip["end"], 2), "en2"]      # "en2": captions made always-English
        if segments:
            span.append(segments)
        if clip.get("caption_cues") is not None:
            raw = []
        elif clip.get("fixed_for") == span and clip.get("fixed_words") and not any(
                roman.needs_roman(w.get("w", "")) for w in clip["fixed_words"]):
            raw = clip["fixed_words"]          # already tidied for this exact span: no second AI call
        else:
            raw = [w for w in words if clip["start"] - 1 <= w["s"] <= clip["end"] + 1
                   and (not segments or any(s["start"] <= w["s"] < s["end"] for s in segments))]
            if (not raw and job.get("options", {}).get("mode") in ("manual", "gameplay") and job.get("has_audio")
                    and (transcribe.model_ready() or transcribe.REMOTE)):
                try:
                    ranges = segments or [{"start": clip["start"], "end": clip["end"]}]
                    for part in sorted(ranges, key=lambda s: s["start"]):
                        a, b = part["start"], part["end"]
                        audio = editor.pcm(src, a - off, b - a, 16000)
                        raw.extend(dict(w, s=w["s"] + a, e=w["e"] + a) for w in transcribe.transcribe(audio))
                except (OSError, RuntimeError, ValueError):
                    pass  # A missing transcript doesn't prevent a visual clip from rendering.
            try:
                if job.get("options", {}).get("mode") not in ("manual", "gameplay"):
                    usage.set_context(job.get("creator"), job.get("title") or "")
                    raw = brain.english_captions(raw, job.get("lang") or "", job.get("title") or "",
                                                 youtube_english=lambda: _english_part(job, clip))
                clip.update(fixed_words=raw, fixed_for=span)
            except Exception:  # noqa: BLE001 - captions still render with the words as heard
                pass
        # the last word on it: whatever was said, nothing is drawn in Hindi or Urdu script
        corrected = editor.apply_glossary(raw, editor.read_glossary()) if raw else raw
        if str(clip.get("hook", "")).strip().lower() in _GENERIC_POST_TITLES:
            # Old clip scans sometimes label an empty hook "Untitled clip". Never burn that placeholder into video.
            clip["hook"] = ""
        if clip.get("auto_gameplay") and not clip.get("post_drafted"):
            if job["options"].get("ai_post_text"):
                if not clip.get("metadata_ai"):
                    transcript = " ".join(w["w"] for w in corrected if clip["start"] <= w["s"] < clip["end"])
                    usage.set_context(job.get("creator"), job.get("title") or "")
                    clip.update(brain.gameplay_post(Path(job["title"]).stem if job["source"]["type"] == "file" else job["title"],
                                                    clip["start"], clip["end"], transcript, config.ai_ready()))
            clip["post_drafted"] = True
        near = [dict(w, s=w["s"] - off, e=w["e"] - off) for w in roman.words(corrected)]
        out = render.render_clip(src, d / "clips", clip["id"], local, near, job["width"], job["height"])
        clip.update(out, status="done", version=clip.get("version", 0) + 1, error=None)
        clip["render_seconds"] = round(time.time() - clip["render_started_at"], 1)
        clip.pop("render_started_at", None)
        clip.update(post_metadata(job, clip))
        post = {k: clip[k] for k in ("title", "description", "hashtags", "hook", "start", "end", "score")}
        (d / "clips" / f"{clip['id']}.json").write_text(json.dumps(post, indent=1), encoding="utf-8")
        if clip["version"] == 1:
            clip.setdefault("made_at", time.time())
            creators.log(job["creator"], f"Clip ready (score {clip['score']}): {clip['title'] or clip['hook']}")
            save(job)
            for fn in (() if clip.get("manual") else on_clip_ready):
                try:
                    fn(job, clip)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
    except Exception as e:  # noqa: BLE001
        clip.update(status="error", error=safe.friendly(e, 400))
        clip.pop("render_started_at", None)
        creators.log(job["creator"], f"Clip failed: {safe.friendly(e, 200)}")
    save(job)


CLIP_MINUTES = float(config.env("PEAKCUT_CLIP_MINUTES", "15"))     # the longest one clip may take to make


def _wait_for_clips(job, futures, began, workers):
    """Wait for a video's clips, but not for ever. A clip that hangs (a download that stalls, an encoder that
    freezes) used to keep the whole video "in progress", and no other clip could be re-made. Now it is marked as
    failed after CLIP_MINUTES and the video finishes with the clips that did work."""
    left, given_up = list(futures), 0
    late = "This clip took too long and was stopped. Open it and press Save and re-make to try again."
    while left:
        still = []
        for f, clip in left:
            if f.done():
                f.result()
                continue
            t = began.get(clip["id"])
            if (t and time.time() - t > CLIP_MINUTES * 60) or (not t and given_up >= workers):
                given_up += 1
                clip.update(status="error", error=late)
                creators.log(job["creator"], f"Clip stopped after {CLIP_MINUTES:g} minutes: {clip.get('title') or clip.get('hook') or clip['id']}")
                save(job)
                continue
            still.append((f, clip))
        left = still
        if left:
            time.sleep(1)


def _english_part(job, clip):
    """YouTube's English captions for just this clip, for a video in another language. Fetched once per video."""
    if (job.get("source") or {}).get("type") != "url":
        return None
    f = Path(job["dir"]) / "words_en.json"
    if f.is_file():
        en = json.loads(f.read_text(encoding="utf-8"))
    else:
        try:
            en = media.youtube_english_words(job["source"]["url"]) or []
        except Exception:  # noqa: BLE001 - YouTube often refuses its translations: the AI translates instead
            en = []
        f.write_text(json.dumps(en), encoding="utf-8")       # asked once per video, refused or not
    return [w for w in en if clip["start"] - 0.5 <= w["s"] <= clip["end"] + 0.5]


LONG_VIDEO = 40 * 60   # above this, fetch only the pieces that become clips
PAD = 8                # seconds kept either side of a fetched piece, so clips can be re-trimmed


def _fetch_piece(job, clip, full_audio):
    """Long videos: download just this clip's stretch and pin down exactly where it starts."""
    d = Path(job["dir"])
    o = job["options"]
    try:
        want = max(0.0, clip["start"] - PAD)
        piece = media.download_section(job["source"]["url"], d / "clips", f"{clip['id']}.src", want,
                                       min(job["duration"], clip["end"] + PAD), int(o["quality"]))
        wav = d / "clips" / f"{clip['id']}.wav"
        media.extract_audio(piece, wav)
        part = media.load_audio(wav)
        wav.unlink(missing_ok=True)
        meta = media.probe(piece)
        off = media.find_offset(full_audio, part, want)
        clip.update(src=str(piece), src_offset=round(off, 2), src_end=round(off + meta["duration"], 2))
        clip["start"], clip["end"] = max(clip["start"], clip["src_offset"]), min(clip["end"], clip["src_end"])
        job.setdefault("width", meta["width"])
        job.setdefault("height", meta["height"])
    except Exception as e:  # noqa: BLE001
        clip.update(status="error", error=f"Could not fetch this part of the video: {safe.friendly(e, 250)}")


BLOCK = 10 * 60         # long videos are transcribed and clipped one block at a time
PROGRESSIVE_FROM = 20 * 60


def _covers(words: list, start: float, end: float) -> bool:
    """Is a borrowed transcript good enough to find clips with? It has to reach the end of the part being clipped
    and have a normal amount of talking in it; otherwise our own model writes the transcript."""
    inside = [w for w in words if start <= w["s"] <= end]
    minutes = max(0.5, (end - start) / 60)
    return len(inside) >= 25 * minutes and inside[-1]["s"] >= start + 0.85 * (end - start)


def _run_job(job):
    import math
    from concurrent.futures import ThreadPoolExecutor
    d = Path(job["dir"])
    o = job["options"]
    src = job["source"]
    t0 = time.time()
    notes = []
    usage.set_context(job["creator"], job["title"] or src.get("name"))
    if o.get("mode") in ("manual", "gameplay"):
        job.pop("resume", None)
        _set(job, status="running", stage="Preparing the source", progress=0.03, error=None, transfer=None)
        _run_source_job(job, t0)
        return
    resuming = bool(job.pop("resume", False)) and (d / "words.json").is_file()
    if resuming:   # after a restart: keep the transcript parts, clips and AI answers already made, and carry on
        _set(job, status="running", stage="Picking up where it stopped", error=None)
    else:
        _set(job, status="running", stage="Getting the audio", progress=0.03, error=None, clips=[], ai={}, done_blocks=0)
    if not transcribe.model_ready() and not transcribe.REMOTE:
        from . import fetch_model
        _set(job, stage="Getting the speech model (one time, about 480 MB)")
        fetch_model.ensure()
        _set(job, stage="Getting the audio")
    fetch = ThreadPoolExecutor(1)
    video = None
    if src["type"] == "url":
        _set(job, stage="Reading video information")
        meta = media.info(src["url"])
        if meta["kind"] != "video":
            raise RuntimeError("That link is a channel or playlist, not a single video. Paste the link of one video.")
        if ((o["range_end"] or meta["duration"]) - (o["range_start"] or 0)) > config.MAX_VIDEO_HOURS * 3600:
            raise RuntimeError(f"That is longer than {config.MAX_VIDEO_HOURS:g} hours. Choose a shorter part of it under Options.")
        if meta["is_live"]:
            raise RuntimeError("This link is a live stream, so it would never finish downloading. Open the creator, "
                               "put this link under Setup, and press Start recording instead.")
        _set(job, title=meta["title"], uploader=meta["uploader"], duration=meta["duration"])
        if not job.get("thumb") and media.save_thumb(d, url=src["url"]):
            _set(job, thumb=True)
        usage.set_context(job["creator"], meta["title"])
        span = (o["range_end"] or meta["duration"]) - (o["range_start"] or 0)
        pieces = span > LONG_VIDEO or meta["duration"] <= 0
        existing = source_file(job)
        if not pieces:  # shorter video: fetch all of it in the background while the audio is worked on
            video = fetch.submit(lambda: existing or media.download(src["url"], d, int(o["quality"])))
        _set(job, stage="Getting the source audio")
        audio_file = existing or media.download_audio(src["url"], d, lambda p: _set(job, progress=0.03 + 0.1 * p))
    else:
        pieces, audio_file = False, Path(src["path"])
        info = media.probe(audio_file)
        if info["duration"] > config.MAX_VIDEO_HOURS * 3600:
            raise RuntimeError(f"That video is longer than {config.MAX_VIDEO_HOURS:g} hours, which is the limit.")
        _set(job, source_path=str(audio_file), width=info["width"], height=info["height"], duration=info["duration"],
             fps=info["fps"], has_audio=info["has_audio"])
        if not job.get("thumb") and media.save_thumb(d, video=audio_file):
            _set(job, thumb=True)
    wav = d / "audio.wav"
    _set(job, stage="Preparing audio for transcription")
    media.extract_audio(audio_file, wav)
    audio = media.load_audio(wav)
    wav.unlink(missing_ok=True)
    if src["type"] == "url" and audio_file != existing:
        audio_file.unlink(missing_ok=True)
    if not job["duration"]:
        job["duration"] = len(audio) / 16000
    lo = int((o["range_start"] or 0) * 16000)
    hi = min(len(audio), int(o["range_end"] * 16000)) if o["range_end"] else len(audio)
    if hi <= lo:
        raise ValueError("The selected range is outside the video. Choose an earlier start time.")
    span = (hi - lo) / 16000
    db = media.loudness_per_second(audio[lo:hi])

    vlock, vstate = threading.Lock(), {}

    def whole_video():
        """Wait for the background download once; retry it, or give up and use pieces."""
        with vlock:
            if "path" not in vstate:
                path = None
                try:
                    path = video.result()
                except Exception as e:  # noqa: BLE001 - sites sometimes refuse a download
                    notes.append(f"Video download refused once ({str(e)[-80:]}), retrying")
                    try:
                        path = media.download(src["url"], d, int(o["quality"]))
                    except Exception as e2:  # noqa: BLE001
                        notes.append(f"Whole-video download failed ({str(e2)[-80:]}), fetching clip parts instead")
                if path:
                    info = media.probe(path)
                    job.update(source_path=str(path), width=info["width"], height=info["height"],
                               fps=info["fps"], has_audio=info["has_audio"])
                vstate["path"] = path
            return vstate["path"]

    exact = {}      # clip id -> (from, to, words): our own model's words for just that clip

    began = {}      # clip id -> when work on it started

    def make(clip, words_now):
        began[clip["id"]] = time.time()
        if src["type"] == "url" and (pieces or not whole_video()):
            _fetch_piece(job, clip, audio)
        if clip["status"] != "error" and yt and yt[1].lower().startswith("en"):
            # The clip was found with YouTube's transcript. What is shown on screen comes from our own model,
            # run on just this clip: full punctuation, nothing blanked out, timings to the word.
            a0, b0 = max(lo, int((clip["start"] - 1.5) * 16000)), min(hi, int((clip["end"] + 1.5) * 16000))
            try:
                tw = [dict(w, s=round(w["s"] + a0 / 16000, 2), e=round(w["e"] + a0 / 16000, 2)) for w in transcribe.transcribe(audio[a0:b0])]
            except Exception:  # noqa: BLE001 - the clip is still made, with YouTube's words
                tw = []
            if len(tw) >= 3:
                exact[clip["id"]] = (a0 / 16000, b0 / 16000, tw)
                words_now = tw
        if clip["status"] != "error":
            render_one(job, clip, words_now)

    cpus = os.cpu_count() or 4
    renders = ThreadPoolExecutor(2 if cpus < 8 else min(6, cpus // 6))  # more clips made at once on a bigger machine
    futures = []
    step = BLOCK * 16000 if span > PROGRESSIVE_FROM else hi - lo
    blocks = [(x, min(hi, x + step)) for x in range(lo, hi, step)] or [(lo, hi)]
    words, tokens, model = [], 0, None
    done_blocks = 0
    yt = None
    if src["type"] == "url" and config.YT_TRANSCRIPT and media.is_youtube(src["url"]):
        try:
            yt = media.youtube_words(src["url"])
        except Exception:  # noqa: BLE001 - no transcript to borrow: ours is written as usual
            yt = None
        if yt and not _covers(yt[0], lo / 16000, hi / 16000):
            yt = None
        job["transcript_from"] = "youtube" if yt else "own"
        job["lang"] = yt[1] if yt else ""          # the language spoken, when YouTube says (decides the captions)
    if resuming:
        try:
            words = json.loads((d / "words.json").read_text(encoding="utf-8"))
        except ValueError:
            words = []
        done_blocks = min(int(job.get("done_blocks", 0)), len(blocks)) if words else 0
        tokens, model = int((job.get("ai") or {}).get("tokens", 0)), (job.get("ai") or {}).get("model")
        if done_blocks < len(blocks):     # words past the last finished part are transcribed again
            cut = blocks[done_blocks][0] / 16000
            words = [w for w in words if w["s"] < cut]
        for c in job["clips"]:            # clips found before the restart that were not finished yet
            if c.get("status") not in ("done", "error"):
                c["status"] = "queued"
                futures.append((renders.submit(ctx.bind(make), c, list(words)), c))
        save(job)
    # The transcript of the next part is written while the AI is still reading this one (the AI is a wait on the
    # network, the transcript is work on this machine), so neither waits for the other.
    ahead = ThreadPoolExecutor(2, thread_name_prefix="ahead")
    heard, now_on = {}, [done_blocks]

    def hear(i):
        if i < len(blocks) and i >= done_blocks and i not in heard:
            a_, b_ = blocks[i]
            last = [0.0]

            def tp(p, i=i, a_=a_, b_=b_):
                if now_on[0] == i and p - last[0] > 0.05:      # only the part being shown moves the bar
                    last[0] = p
                    _set(job, progress=max(job["progress"], 0.14 + 0.78 * ((a_ - lo) + p * (b_ - a_)) / max(1, hi - lo)))
            heard[i] = ahead.submit(ctx.bind(transcribe.transcribe), audio[a_:b_], tp)

    for bi, (a, b) in enumerate(blocks):
        if bi < done_blocks:
            continue                      # transcribed and checked by the AI before the restart
        shift = a / 16000
        where = f" (minute {round((a - lo) / 16000 / 60)} of {round(span / 60)})" if len(blocks) > 1 else ""
        if yt:
            _set(job, stage="Reading the transcript" + where)
            bw = [dict(w, s=round(w["s"] - shift, 2), e=round(w["e"] - shift, 2)) for w in yt[0] if a / 16000 <= w["s"] < b / 16000]
        else:
            _set(job, stage="Writing the transcript" + where)
            now_on[0] = bi
            hear(bi)
            hear(bi + 1)
            bw = heard.pop(bi).result()
        _set(job, progress=max(job["progress"], 0.14 + 0.78 * (b - lo) / max(1, hi - lo)))
        words += [dict(w, s=round(w["s"] + shift, 2), e=round(w["e"] + shift, 2)) for w in bw]
        (d / "words.json").write_text(json.dumps(words), encoding="utf-8")
        _set(job, stage="Finding the best moments" + where, word_count=len(words))
        left = int(o["max_clips"]) - len(job["clips"])
        if left <= 0 or len(bw) < 8:
            job["done_blocks"] = bi + 1
            save(job)
            continue
        quota = max(1, math.ceil(left / (len(blocks) - bi)))
        s0 = int((a - lo) / 16000)
        found, ai = brain.find_clips(bw, db[s0: s0 + int((b - a) / 16000) + 1], (b - a) / 16000, job["title"],
                                     job["uploader"], quota, int(o["min_len"]), int(o["max_len"]), notes.append,
                                     (job.get("automation") or {}).get("prompt", ""))
        tokens += ai.get("tokens", 0)
        model = ai.get("model") or model
        if ai.get("note"):
            notes.append(ai["note"])
        for c in found:
            c.update(id=f"clip{len(job['clips']) + 1:02d}", start=round(c["start"] + shift, 2),
                     end=round(c["end"] + shift, 2), style=o["style"], layout=o["layout"], status="queued", version=0)
            job["clips"].append(c)
            futures.append((renders.submit(ctx.bind(make), c, list(words)), c))
        job["ai"] = {"model": model, "tokens": tokens, "note": "", "log": notes[-5:]}
        job["done_blocks"] = bi + 1       # a restart from here on carries on with the next part
        save(job)
    if futures:
        _set(job, stage="Finishing the clips", progress=max(job["progress"], 0.92))
    _wait_for_clips(job, futures, began, renders._max_workers)
    if exact:           # keep our own words for the clips in the saved transcript, so editing a clip later uses them
        for a_s, b_s, tw in exact.values():
            words = [w for w in words if not a_s <= w["s"] < b_s] + tw
        words.sort(key=lambda w: w["s"])
        (d / "words.json").write_text(json.dumps(words), encoding="utf-8")
    renders.shutdown(wait=False)
    ahead.shutdown(wait=False)
    fetch.shutdown(wait=False)
    del audio
    clips = job["clips"]
    job["ai"] = {"model": model, "tokens": tokens, "log": notes[-5:],
                 "note": (notes[-1] if not clips and notes else
                          "The AI returned no usable result, so clips were picked by loudness only." if clips and not model else "")}
    stage = "Done" if clips else "Done, but nothing clip-worthy was found"
    finish_video(job, stage, round(time.time() - t0))
    _announce_job_result(job)


def _announce_job_result(job):
    ready = sum(clip["status"] == "done" for clip in job["clips"])
    failed = sum(clip["status"] == "error" for clip in job["clips"])
    if ready:
        message = f"{ready} clip{'s' if ready != 1 else ''} ready"
        if failed:
            message += f", {failed} failed to render"
    elif failed:
        message = "All clips failed to render"
    else:
        message = "Nothing clip-worthy found"
    try:
        from . import notices
        name = job.get("title") or job["source"].get("name") or "your video"
        notices.add(job.get("user"), "clips", message,
                    name, f"/app/creators/{job['creator']}" if job.get("creator") else "/app/videos")
    except Exception:  # noqa: BLE001
        pass
    creators.log(job["creator"], f"{message} after {job['took']}s: {job['title']}")


def _scan_gameplay(job, path, start, end, has_audio):
    options = job["options"]
    count = options["max_clips"]
    # Evaluate more than the requested output count and distribute those candidates across the full
    # source duration. A global loudness-only top-N shortlist tends to over-sample one busy section.
    candidate_limit = max(12, min(18, count * 3))
    signature = [path.stat().st_mtime_ns, path.stat().st_size, start, end, count, candidate_limit,
                 options["min_len"], options["max_len"], "time-spread-v2"]
    checkpoint = job.get("gameplay_scan") or {}
    if checkpoint.get("signature") != signature:
        checkpoint = {"signature": signature, "cursor": start, "picks": []}
    cursor = checkpoint["cursor"]
    while cursor < end:
        edge = min(end, cursor + 600)
        a = max(start, cursor - min(45, options["max_len"]))
        picks = editor.gameplay(path, a, edge, min(12, max(4, candidate_limit)),
                                options["min_len"], options["max_len"], has_audio=has_audio)
        checkpoint["picks"].extend(picks)
        checkpoint["cursor"] = cursor = edge
        _set(job, gameplay_scan=checkpoint, stage="Scanning gameplay for action",
             progress=0.25 + 0.35 * (cursor - start) / (end - start))
    candidates = sorted(checkpoint["picks"], key=lambda c: -c.get("strength", 0))
    ranked = []

    def add_non_overlapping(item):
        if any(item["start"] < clip["end"] and item["end"] > clip["start"] for clip in ranked):
            return False
        ranked.append({k: v for k, v in item.items() if k != "strength"})
        return True

    # Reserve a slot for each equal-duration slice, then fill any empty slices by overall activity.
    # The LLM can then compare moments from the beginning, middle and end of long streams.
    bucket_width = max(1.0, (end - start) / candidate_limit)
    for index in range(candidate_limit):
        lo = start + index * bucket_width
        hi = end if index == candidate_limit - 1 else start + (index + 1) * bucket_width
        bucket = [item for item in candidates
                  if lo <= (item["start"] + item["end"]) / 2 < hi]
        for item in bucket:
            if add_non_overlapping(item):
                break
    for item in candidates:
        if len(ranked) >= candidate_limit:
            break
        add_non_overlapping(item)
    return sorted(ranked, key=lambda c: c["start"])


def _run_source_job(job, began):
    """Prepare a complete source for manual editing, or find visual gameplay highlights."""
    directory = Path(job["dir"])
    options = job["options"]
    source = job["source"]
    path = source_file(job)
    if path is None:
        if source["type"] == "file":
            path = Path(source["path"])
        else:
            _set(job, stage="Reading video information")
            meta = media.info(source["url"])
            if meta["kind"] != "video" or meta["is_live"]:
                raise ValueError("Choose a finished video or upload a file.")
            if not 0 < meta["duration"] <= config.MAX_VIDEO_HOURS * 3600:
                raise ValueError("Upload a video file within the source duration limit.")
            _set(job, title=meta["title"], uploader=meta["uploader"], stage="Downloading the source video")

            def transfer(data):
                if data is None:
                    _set(job, transfer=None, stage="Combining source video and audio", progress=0.23)
                    return
                total = data["total"]
                fraction = min(1, data["bytes"] / total) if total else 0
                base, weight = (0.20, 0.03) if data["track"] == "audio" else (0.03, 0.17)
                _set(job, transfer=data, progress=max(job["progress"], base + weight * fraction))

            try:
                path = media.download(source["url"], directory, int(options["quality"]), on_progress=transfer,
                                      cancel_event=_cancel_events.get(job["id"]))
            finally:
                _set(job, transfer=None)
            _set(job, stage="Checking the downloaded video", progress=0.24)
    info = media.probe(path, require_audio=False)
    if not 0 < info["duration"] <= config.MAX_VIDEO_HOURS * 3600:
        raise ValueError("The source video is empty or exceeds the duration limit.")
    _set(job, source_path=str(path), **info)
    if not job.get("thumb") and media.save_thumb(directory, video=path):
        _set(job, thumb=True)
    if options["mode"] == "manual":
        finish_video(job, "Source ready to edit", round(time.time() - began))
        return
    start = options.get("range_start") or 0
    end = min(info["duration"], options.get("range_end") or info["duration"])
    if end <= start:
        raise ValueError("The selected range is outside the video.")
    _set(job, stage="Scanning gameplay for action", progress=0.25)
    if not job.get("gameplay_scanned"):
        found = _scan_gameplay(job, path, start, end, info["has_audio"])
        title = Path(job["title"]).stem if source["type"] == "file" else job["title"]
        if found and info["has_audio"] and (transcribe.model_ready() or transcribe.REMOTE):
            for index, candidate in enumerate(found, 1):
                _set(job, stage=f"Checking candidate {index} of {len(found)}", progress=max(job["progress"], 0.61))
                try:
                    audio = editor.pcm(path, candidate["start"], candidate["end"] - candidate["start"], 16000)
                    spoken = transcribe.transcribe(audio)
                    candidate["transcript"] = " ".join(w.get("w", "") for w in spoken)[:1200]
                except (OSError, RuntimeError, ValueError):
                    candidate["transcript"] = ""
        usage.set_context(job.get("creator"), title)
        direction = (job.get("automation") or {}).get("prompt", "")
        found, model = brain.rank_gameplay_candidates(title, found, options["max_clips"], direction)
        if direction and found and not model:
            job["ai"]["note"] = "No usable dialogue for AI ranking. Signal picks are ready for review and were not queued to post."
        for clip in found:
            clip.pop("strength", None)
            clip.pop("transcript", None)
            clip.update(id="clip-" + uuid.uuid4().hex[:10], style=options["style"], layout=options["layout"],
                        motion=options.get("motion", "none"), watermark=options.get("watermark", False),
                        auto_gameplay=True, status="queued", version=0)
            if not clip.get("metadata_ai"):
                clip.update(brain.gameplay_post(title, clip["start"], clip["end"]))
        job["clips"].extend(found)
        job.pop("gameplay_scan", None)
        _set(job, gameplay_scanned=True)
    found = [clip for clip in job["clips"] if not clip.get("manual")]
    renderable = [clip for clip in found if clip["status"] != "done"]
    total = len(renderable)
    completed = 0
    for index, clip in enumerate(renderable, 1):
        if clip["status"] != "done":
            _set(job, stage=f"Rendering clip {index} of {total}",
                 progress=0.65 + 0.35 * completed / max(1, total))
            render_one(job, clip, [])
            completed += 1
            _set(job, progress=0.65 + 0.35 * completed / max(1, total))
    finish_video(job, "Done" if found else "No gameplay highlights found. You can make a clip by hand.",
                 round(time.time() - began))
    _announce_job_result(job)


def _worker(quick_only=False):
    while True:
        kind, a, cid = _q.get(quick_only)
        if kind == "fn":
            try:
                a()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            continue
        job = _jobs.get(a)
        if not job:
            if kind == "job":
                _q.done()
            continue
        token = ctx._uid.set(job["user"])  # everything this job does runs as its owner
        try:
            if job.get("rights_cleared") is not True:
                raise ValueError("Confirm that you own or have permission to use this source before clipping it.")
            if kind == "job":
                if not _cancel_events.get(job["id"], threading.Event()).is_set():
                    _run_job(job)
            else:
                words = read_words(job)
                clip = next(c for c in job["clips"] if c["id"] == cid)
                render_one(job, clip, words)
        except Exception as e:  # noqa: BLE001
            if kind == "job" and _cancel_events.get(job["id"], threading.Event()).is_set():
                for clip in job["clips"]:
                    if clip.get("status") in ("queued", "rendering"):
                        clip.update(status="error", error="The download was cancelled.")
                _set(job, status="cancelled", stage="Download cancelled", progress=0.03,
                     error=None, transfer=None, failed_stage=None)
                continue
            (Path(job["dir"]) / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
            if kind == "job":
                for c in job["clips"]:
                    if c.get("status") in ("queued", "rendering"):
                        c.update(status="error", error="The video stopped before this clip was made.")
                _set(job, status="error", error=safe.friendly(e), failed_stage=job["stage"], stage="Stopped")
                creators.log(job["creator"], f"Video failed: {safe.friendly(e)[:200]}")
            else:
                clip = next((c for c in job["clips"] if c["id"] == cid), None)
                if clip:
                    clip.update(status="error", error=safe.friendly(e))
                    save(job)
        finally:
            ctx._uid.reset(token)
            if kind == "job":
                _q.done()


def _pick_up_after_restart():
    """Videos and single clips that were being made when the server stopped: queued again, oldest first."""
    waiting = sorted((j for j in all_jobs() if j.get("status") == "queued" and j.get("resume")), key=lambda j: j["created"])
    for j in waiting:
        _q.put(("job", j["id"], None), user=j["user"])
    for j in all_jobs():
        for cid in j.pop("remake", []):
            _q.put(("clip", j["id"], cid))
        if j.get("status") == "done":
            save(j)


def start():
    load.start()
    load_all()
    _pick_up_after_restart()
    for _ in range(max(1, config.JOB_WORKERS)):
        threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_worker, args=(True,), daemon=True).start()   # re-making a single clip never waits behind whole videos
    threading.Thread(target=_live_worker, daemon=True).start()
