"""Post queue: decides when each finished clip goes to which account, posts it, and tracks views."""
import random
import secrets
import threading
import time
from pathlib import Path

import json
import re

from . import accounts, alerts, brain, config, creators, ctx, jobs, live, media

_lock = threading.RLock()
_wake = threading.Event()
YOUTUBE_BATCH_LIMIT = 200
YOUTUBE_GAP = 600
_FILE = config.DATA_DIR / "posts.json"
try:
    _posts: list = json.loads(_FILE.read_text(encoding="utf-8")) if _FILE.exists() else []
except ValueError:
    _posts = []

_LIMIT_FILE = config.DATA_DIR / "post-cooldowns.json"
try:
    _limits = json.loads(_LIMIT_FILE.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _limits = {}


def blocked_until(platform, account=None):
    with _lock:
        return max(0, _limits.get(platform, 0) or 0, _limits.get(f"{platform}:{account}", 0) or 0)


def _record_limit(platform, error, account=None):
    # Shared project/API limits block all accounts; a documented account limit blocks that account
    # across users. Neither case changes an account or credential on any queued post.
    with _lock:
        scope = f"{platform}:{account}" if error.account_only and account else platform
        until = max(_limits.get(scope, 0), time.time() + error.delay)
        _limits[scope] = until
        tmp = _LIMIT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_limits), encoding="utf-8")
        tmp.replace(_LIMIT_FILE)
        for user in {p["user"] for p in _posts if p["platform"] == platform}:
            ctx.bump(user)
        return until


_restart_pending = False


def prepare_restart():
    global _restart_pending
    with _lock:
        if any(p["status"] == "posting" for p in _posts):
            return False
        _restart_pending = True
        return True


def _mine() -> list:
    u = ctx.uid()
    return [p for p in _posts if p.get("user") == u]
OPEN = ("scheduled", "posting")


def _save():
    with _lock:
        tmp = _FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_posts, indent=1), encoding="utf-8")
        tmp.replace(_FILE)


def _day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _text_key(value):
    """Compare post copy without case, punctuation, or whitespace differences."""
    return " ".join(re.findall(r"\w+", str(value or "").casefold()))


def _mirror_rows(job, rows):
    clips = {clip["id"]: clip for clip in job["clips"]}
    changed = False
    for post in rows:
        clip = clips.get(post["clip"])
        if clip is not None:
            clip.setdefault("posts", {})[post["id"]] = {k: post.get(k) for k in
                                                         ("account_name", "platform", "status", "url", "due_at", "error")}
            changed = True
    if changed:
        jobs.save(job)


def _mirror(p):
    """Copy the post's state onto its clip so the clip card can show it."""
    job = jobs.get(p["job"])
    if job:
        _mirror_rows(job, [p])


def _apply_publishing_window(t: float) -> float:
    """Shift a scheduled timestamp into the active peak-hour publishing window when enabled."""
    try:
        from . import render
        pw = render.studio_presets().get("publishing_window") or {}
        if not pw.get("enabled"):
            return t
        start_h = max(0, min(23, int(pw.get("start_hour", 12))))
        end_h = max(start_h + 1, min(24, int(pw.get("end_hour", 23))))
        lt = time.localtime(t)
        if lt.tm_hour < start_h:
            return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, start_h, 0, 0, 0, 0, -1))
        if lt.tm_hour >= end_h:
            nxt = time.localtime(t + 86400)
            return time.mktime((nxt.tm_year, nxt.tm_mon, nxt.tm_mday, start_h, 0, 0, 0, 0, -1))
    except Exception:
        pass
    return t


def _next_slot(account_id, gap_min, gap_max, cap):
    """Pick a randomized gap, then respect earlier posts, the peak-hour window, and the account's daily cap."""
    mine = [p for p in _mine() if p["account"] == account_id and p["status"] in OPEN + ("posted",)]
    gap = random.randint(int(gap_min), max(int(gap_min), int(gap_max)))
    t = _apply_publishing_window(max(time.time(), max((p.get("posted_at") or p["due_at"] for p in mine), default=0) + gap * 60))
    if not cap:
        return t
    for _ in range(30):
        if sum(1 for p in mine if _day(p.get("posted_at") or p["due_at"]) == _day(t)) < cap:
            break
        lt = time.localtime(t + 86400)
        t = _apply_publishing_window(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 9, 0, 0, 0, 0, -1)))
    return t


def _clip_file(job, clip):
    folder = (Path(job["dir"]) / "clips").resolve()
    path = (folder / str(clip.get("file") or "")).resolve()
    if path.parent != folder or not path.is_file():
        raise ValueError("The rendered clip file is missing. Re-make the clip and try again.")
    return path


PIPELINE_STAGES = (
    "intake", "capture", "analysis", "rendering", "metadata",
    "validation", "scheduling", "upload", "remote_verification"
)
DISTINCT_STATUSES = ("Scheduled", "Uploading", "Processing", "Public", "Private", "Held", "Failed")
LEASE_SECONDS = 600


def idempotency_key(job_id: str, clip_id: str, revision: int, platform: str, account_id: str) -> str:
    import hashlib
    raw = f"{job_id}:{clip_id}:v{int(revision or 1)}:{platform}:{account_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def display_status(post: dict) -> str:
    """Map internal queue state to the 7 distinct user-facing publishing statuses."""
    st = str(post.get("status") or "scheduled").lower()
    if st in ("held", "review"):
        return "Held"
    if st == "failed":
        return "Failed"
    if st == "processing":
        return "Processing"
    if st in ("posting", "uploading"):
        return "Processing" if post.get("bytes_uploaded_complete") else "Uploading"
    if st == "posted":
        vis = str(post.get("visibility") or "public").lower()
        return "Private" if vis in ("private", "unlisted") else "Public"
    return "Scheduled"


def _post_row(job, clip, acc, due, metadata, *, automatic=False, autopilot=False):
    rev = int(clip.get("version") or 1)
    return {
        "id": secrets.token_hex(8),
        "idempotency_key": idempotency_key(job["id"], clip["id"], rev, acc["platform"], acc["id"]),
        "clip_revision": rev,
        "user": ctx.uid(),
        "job": job["id"],
        "clip": clip["id"],
        "creator": job.get("creator"),
        "account": acc["id"],
        "account_name": acc["name"],
        "platform": acc["platform"],
        "status": "scheduled",
        "pipeline_stage": "scheduling",
        "due_at": due,
        "created": time.time(),
        "title": metadata["title"],
        "description": metadata["description"],
        "hashtags": metadata["hashtags"],
        "score": clip.get("score", 0),
        "tries": 0,
        "url": "",
        "remote_id": "",
        "error": None,
        "views": None,
        "automatic": automatic,
        "autopilot": bool(autopilot),
        "lease_owner": None,
        "lease_expires_at": 0.0,
    }


def _sync_rows(rows):
    groups = {}
    for post in rows:
        groups.setdefault(post["job"], []).append(post)
    for jid, posts in groups.items():
        try:
            job = jobs.get(jid)
            if job:
                _mirror_rows(job, posts)
        except OSError:
            # The queue has already been written. A panel refresh can still show it.
            pass
    if rows:
        ctx.bump()
        _wake.set()


def youtube_destination(account_id):
    if not account_id:
        choices = [a["id"] for a in accounts.list_accounts() if a["platform"] == "youtube"]
        if len(choices) != 1:
            raise ValueError("Connect a YouTube channel in Settings → Connected Apps." if not choices
                             else "Choose the YouTube channel that should receive these clips.")
        account_id = choices[0]
    account = accounts.get(account_id)
    if not account or account["platform"] != "youtube":
        raise ValueError("Connect or reconnect the selected YouTube channel in Settings → Connected Apps.")
    return account


def youtube_batch(items, account_id="", visibility=None, delay=0):
    """Queue the submitted order, with a real connected destination and durable, unique rows."""
    if not isinstance(items, list) or not 1 <= len(items) <= YOUTUBE_BATCH_LIMIT:
        raise ValueError(f"Select between 1 and {YOUTUBE_BATCH_LIMIT} clips.")
    if visibility is not None and visibility not in ("public", "unlisted", "private"):
        raise ValueError("Choose private, unlisted, or public visibility.")
    acc = youtube_destination(account_id)
    made, skipped = [], []
    now = time.time()
    batch = secrets.token_hex(8) if len(items) > 1 else ""
    with _lock:
        if _restart_pending:
            raise ValueError("MJ Cliproom is restarting. Wait for it to reopen and try again.")
        # Include failed rows: a failed final chunk can still have reached YouTube.
        existing = {(p["job"], p["clip"]) for p in _mine()
                    if p["account"] == acc["id"] and (p["status"] != "cancelled" or p.get("upload_session"))}
        used_titles = {_text_key(p.get("title")) for p in _mine()
                       if p["account"] == acc["id"] and p["status"] not in ("cancelled",)}
        used_descriptions = {_text_key(p.get("description")) for p in _mine()
                             if p["account"] == acc["id"] and p["status"] not in ("cancelled",)}
        due = max(now + delay, blocked_until("youtube", acc["id"]))
        if batch or delay:
            timing = [float(p.get("posted_at") or p.get("due_at") or 0) for p in _mine()
                      if p["account"] == acc["id"] and p["status"] in OPEN + ("posted",)]
            if timing:
                due = max(due, max(timing) + YOUTUBE_GAP)
        for item in items:
            if not isinstance(item, dict):
                skipped.append({"job": "", "clip": "", "reason": "Invalid clip selection."})
                continue
            jid, cid = str(item.get("job") or ""), str(item.get("clip") or "")
            job = jobs.get(jid)
            clip = next((row for row in job["clips"] if row["id"] == cid), None) if job else None
            try:
                if not clip or clip.get("status") != "done":
                    raise ValueError("This clip is unavailable or still rendering.")
                if job.get("rights_cleared") is False:
                    raise ValueError("Confirm source rights for this video before posting.")
                if (jid, cid) in existing:
                    raise ValueError("This clip already has a post for this channel. Check the queue or retry it there.")
                _clip_file(job, clip)
                overrides = item.get("metadata")
                if overrides is not None and not isinstance(overrides, dict):
                    raise ValueError("Enter title, description and hashtags as post text.")
                if isinstance(overrides, dict):
                    overrides = dict(overrides)
                    if "title" in overrides:
                        overrides["title"] = brain.validate_post_title(overrides["title"])
                    if "description" in overrides:
                        overrides["description"] = brain.validate_post_description(overrides["description"])
                    if isinstance(overrides.get("hashtags"), str):
                        overrides["hashtags"] = overrides["hashtags"].replace(",", " ").split()
                meta = jobs.post_metadata(job, clip, overrides)
                brain.validate_post_title(meta["title"])
                brain.validate_post_description(meta["description"])
                title_key, description_key = _text_key(meta["title"]), _text_key(meta["description"])
                if not title_key or not description_key or title_key in used_titles or description_key in used_descriptions:
                    raise ValueError("This channel already has that title or description. Generate fresh post text first.")
            except (OSError, ValueError) as exc:
                skipped.append({"job": jid, "clip": cid, "reason": str(exc)})
                continue
            post = _post_row(job, clip, acc, due, meta)
            post.update(visibility=visibility or "private", shorts=True, batch=batch)
            if batch:
                post.update(batch_index=len(made), gap_seconds=YOUTUBE_GAP)
            made.append(post)
            existing.add((jid, cid))
            used_titles.add(title_key)
            used_descriptions.add(description_key)
            due += YOUTUBE_GAP
        if made:
            _posts.extend(made)
            try:
                _save()
            except OSError:
                del _posts[-len(made):]
                raise
    _sync_rows(made)
    return made, skipped


def schedule_youtube_batch(items, account_id="", visibility="private"):
    """Schedule or reschedule an ordered set as one verified 9:16 batch.

    Existing scheduled rows are reused, so pressing the batch action cannot duplicate them.
    The first slot is ten minutes from now, followed by exact ten-minute increments.
    """
    if not isinstance(items, list) or not 1 <= len(items) <= YOUTUBE_BATCH_LIMIT:
        raise ValueError(f"Select between 1 and {YOUTUBE_BATCH_LIMIT} clips.")
    if visibility not in ("public", "unlisted", "private"):
        raise ValueError("Choose private, unlisted, or public visibility.")
    acc = youtube_destination(account_id)
    now = time.time()
    due = max(now + YOUTUBE_GAP, blocked_until("youtube", acc["id"]))
    batch = secrets.token_hex(8)
    made, skipped = [], []
    pairs = set()
    with _lock:
        mine = _mine()
        target_pairs = {(str(item.get("job") or ""), str(item.get("clip") or ""))
                        for item in items if isinstance(item, dict)}
        used_titles = {_text_key(p.get("title")) for p in mine
                       if p["account"] == acc["id"] and (p["job"], p["clip"]) not in target_pairs
                       and p["status"] != "cancelled"}
        used_descriptions = {_text_key(p.get("description")) for p in mine
                             if p["account"] == acc["id"] and (p["job"], p["clip"]) not in target_pairs
                             and p["status"] != "cancelled"}
        by_pair = {}
        for post in mine:
            if post["account"] == acc["id"]:
                by_pair.setdefault((post["job"], post["clip"]), []).append(post)
        snapshot = [dict(post) for post in _posts]
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                skipped.append({"job": "", "clip": "", "reason": "Choose a finished clip."})
                continue
            jid, cid = str(item.get("job") or ""), str(item.get("clip") or "")
            pair = (jid, cid)
            try:
                if not jid or not cid:
                    raise ValueError("Choose a finished clip.")
                if pair in pairs:
                    raise ValueError("This clip appears more than once in the batch.")
                pairs.add(pair)
                job = jobs.get(jid)
                clip = next((row for row in job["clips"] if row["id"] == cid), None) if job else None
                if not clip or clip.get("status") != "done":
                    raise ValueError("This clip is unavailable or still rendering.")
                if job.get("rights_cleared") is False:
                    raise ValueError("Confirm source rights for this video before posting.")
                path = _clip_file(job, clip)
                spec = media.probe(path, require_audio=False)
                if spec["width"] * 16 != spec["height"] * 9 or spec["duration"] > 180:
                    raise ValueError("Re-make this clip as a 9:16 Short of three minutes or less before scheduling.")
                overrides = item.get("metadata")
                if isinstance(overrides, dict) and ("title" in overrides or "description" in overrides):
                    overrides = dict(overrides)
                    if "title" in overrides:
                        overrides["title"] = brain.validate_post_title(overrides["title"])
                    if "description" in overrides:
                        overrides["description"] = brain.validate_post_description(overrides["description"])
                metadata = jobs.post_metadata(job, clip, overrides)
                brain.validate_post_title(metadata["title"])
                brain.validate_post_description(metadata["description"])
                title_key, description_key = _text_key(metadata["title"]), _text_key(metadata["description"])
                if not title_key or not description_key or title_key in used_titles or description_key in used_descriptions:
                    raise ValueError("This channel already has that title or description. Generate fresh post text first.")
                rows = by_pair.get(pair, [])
                existing = next((row for row in rows if row["status"] == "scheduled"), None)
                if any(row["status"] in ("posting", "posted") or row.get("upload_session") for row in rows):
                    raise ValueError("This clip is already uploading, posted, or has an uncertain upload. Review its queue row.")
                if any(row["status"] == "failed" for row in rows):
                    raise ValueError("This clip already has a failed upload. Review or retry that queue row first.")
                if existing:
                    post = existing
                    post.update(metadata)
                    post.update(due_at=due, visibility=visibility, shorts=True, batch=batch,
                                batch_index=len(made), gap_seconds=YOUTUBE_GAP, error=None)
                else:
                    post = _post_row(job, clip, acc, due, metadata)
                    post.update(visibility=visibility, shorts=True, batch=batch,
                                batch_index=len(made), gap_seconds=YOUTUBE_GAP)
                    _posts.append(post)
                made.append(post)
                used_titles.add(title_key)
                used_descriptions.add(description_key)
                due += YOUTUBE_GAP
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                skipped.append({"job": jid, "clip": cid, "reason": str(exc)})
        if made:
            try:
                _save()
            except OSError:
                _posts[:] = snapshot
                raise
    _sync_rows(made)
    return made, skipped


def settle_interrupted(post):
    """A restart cut an upload off. A saved YouTube session is continued. Autopilot tries again. A hand-made post waits."""
    if post.get("status") != "posting":
        return post
    if post.get("upload_session"):
        post.update(status="scheduled", due_at=time.time() + 20,
                    error="The upload will continue from the saved YouTube session.")
        return post
    if post.get("autopilot"):
        tries = int(post.get("tries") or 0) + 1
        if tries <= 3:
            post.update(status="scheduled", tries=tries,
                        due_at=time.time() + min(900, 60 * (2 ** (tries - 1))),
                        error="The upload was interrupted by a restart and will be tried again.")
        else:
            post.update(status="failed", tries=tries,
                        error="The upload was interrupted too many times. Check the channel, then retry.")
    else:
        post.update(status="failed", error="The studio closed during this upload. Check the account, then retry.")
    return post


def enqueue(job, clip, account_ids, now=False, automatic=False, autopilot=False) -> list:
    c = creators.get(job["creator"]) or creators.DEFAULTS
    metadata = jobs.post_metadata(job, clip)
    made = []
    with _lock:
        for aid in account_ids:
            acc = accounts.get(aid)
            if not acc:
                continue
            if any(p["job"] == job["id"] and p["clip"] == clip["id"] and p["account"] == aid
                   and (p["status"] in OPEN + ("posted", "failed") or p.get("upload_session")
                        or automatic and p["status"] == "cancelled") for p in _mine()):
                continue  # never post the same clip to the same account twice
            due = time.time() if now else _next_slot(
                aid, c["post_gap_min"], c.get("post_gap_max", c["post_gap_min"]), c["daily_cap"])
            due = max(due, blocked_until(acc["platform"], aid))
            p = _post_row(job, clip, acc, due, metadata, automatic=automatic, autopilot=autopilot)
            if autopilot and acc["platform"] == "youtube":
                p["shorts"] = True
            _posts.append(p)
            made.append(p)
        _save()
    _sync_rows(made)
    return made


def on_clip_ready(job, clip):
    """Called once when a clip first finishes rendering."""
    if job.get("automation"):
        return
    c = creators.get(job["creator"])
    if not c or not c["autopost"] or not c["accounts"]:
        return
    if clip.get("auto_gameplay") and clip.get("score_source") != "ai_and_signals":
        return  # picture/audio-only candidates need a human review before automatic posting
    if clip.get("score", 0) < c["post_min_score"]:
        return  # includes hand-made clips (score 0): those wait for you to press Post
    allowed = [aid for aid in c["accounts"] if (accounts.get(aid) or {}).get("platform") in ("youtube", "instagram")]
    made = enqueue(job, clip, allowed)
    if made:
        creators.log(c["id"], f"Queued for {len(made)} account(s): {clip.get('title') or clip.get('hook')}")


def _queue_prompt_posts(job):
    a = job.get("automation") or {}
    if job.get("status") != "done" or not a.get("accounts") or a.get("revoked"):
        return
    creator = creators.get(job["creator"]) or creators.DEFAULTS
    allowed = [aid for aid in a["accounts"] if (accounts.get(aid) or {}).get("platform") in ("youtube", "instagram")]
    for clip in job["clips"]:
        if clip.get("status") == "done" and clip.get("score_source") in ("prompt_ai", "ai_and_signals") \
                and clip.get("score", 0) >= creator["post_min_score"]:
            enqueue(job, clip, allowed, automatic=True)


def _reconcile_prompt_posts():
    for job in jobs.all_jobs():
        if job.get("automation", {}).get("accounts") and job.get("status") == "done" and not job["automation"].get("queued"):
            with ctx.as_user(job["user"]):
                try:
                    with _lock:
                        _queue_prompt_posts(job)
                        job["automation"]["queued"] = True
                        jobs.save(job)
                except (ValueError, OSError):
                    # Retry durable queue writes on the next worker tick.
                    continue


def revoke_prompt_posts(job):
    with _lock:
        if not job.get("automation", {}).get("accounts"):
            raise ValueError("No automatic publishing was authorized for this video.")
        if any(p["job"] == job["id"] and p.get("automatic") and p["status"] == "posting" for p in _mine()):
            raise ValueError("An upload is in progress. Wait for it to finish before revoking authorization.")
        job["automation"]["revoked"] = True
        jobs.save(job)
        rows = [p for p in _mine() if p["job"] == job["id"] and p.get("automatic") and p["status"] == "scheduled"]
        for p in rows:
            p.update(status="cancelled", error="Automatic publishing was revoked for this video.")
        _save()
    for p in rows:
        _mirror(p)


def _caption(clip, creator):
    tags = " ".join("#" + h for h in clip.get("hashtags", []))
    return "\n\n".join(x for x in (clip.get("description", ""), tags, creator.get("post_footer", "")) if x)


def _post(p):
    job = jobs.get(p["job"])
    clip = next((c for c in job["clips"] if c["id"] == p["clip"]), None) if job else None
    acc = accounts.get(p["account"])
    try:
        if not job:
            raise ValueError("That video is no longer available.")
        if p.get("automatic") and job.get("automation", {}).get("revoked"):
            p.update(status="cancelled", error="Automatic publishing was revoked for this video.")
            _save()
            _mirror(p)
            return
        if not clip or clip.get("status") != "done":
            raise ValueError("The clip no longer exists or is not finished.")
        if not acc:
            raise ValueError("That account was disconnected. Reconnect it in Settings → Connected Apps, then retry.")
        if job.get("rights_cleared") is False:
            raise ValueError("Confirm source rights for this video before posting, then retry.")
        path = _clip_file(job, clip)
        creator = creators.get(job["creator"]) or dict(creators.DEFAULTS, name="clips")
        metadata = jobs.post_metadata(job, clip, p)
        p.update(metadata)
        title, cap = metadata["title"], _caption(metadata, creator)
        if acc["platform"] == "youtube":
            if p.get("shorts"):
                try:
                    spec = media.probe(path, require_audio=False)
                except (OSError, RuntimeError, ValueError) as exc:
                    raise ValueError("The clip could not be opened. Re-make it in 9:16 and retry.") from exc
                if spec["width"] * 16 != spec["height"] * 9:
                    raise ValueError("This clip is not 9:16. Re-make it as a vertical clip, then retry.")
                if spec["duration"] > 180:
                    raise ValueError("Trim this clip to three minutes or less, then retry.")
            privacy = p.get("visibility") or (
                job.get("automation", {}).get("visibility", "private") if p.get("automatic") else creator["privacy"])
            thumb = Path(job["dir"]) / "clips" / f"{clip['id']}-thumb.jpg"
            if not thumb.is_file():
                thumb = None

            def remember(session, post=p):
                post["upload_session"] = session
                _save()

            shorts_caption = cap if any(h.casefold() == "shorts" for h in metadata["hashtags"]) else cap + "\n\n#Shorts"
            rid, url = accounts.youtube_upload(acc, path, title, shorts_caption, metadata["hashtags"], privacy,
                                               resume=p.get("upload_session"), on_session=remember, thumbnail=thumb)
            p.pop("upload_session", None)
        elif acc["platform"] == "instagram":
            rid, url = accounts.instagram_upload(acc, path, f"{title}\n\n{cap}", job["id"])
        elif acc["platform"] == "tiktok":
            rid, url = accounts.tiktok_upload(acc, path, f"{title}\n\n{cap}", creator["privacy"])
        else:
            raise RuntimeError("That kind of account is no longer supported.")
        p.update(status="posted", posted_at=time.time(), remote_id=rid, url=url, error=None)
    except accounts.PlatformLimit as e:
        until = _record_limit(p["platform"], e, p["account"])
        p.update(status="scheduled", due_at=until, error=str(e))
    except Exception as e:  # noqa: BLE001
        p["tries"] += 1
        p["error"] = str(e)[-300:]
        if isinstance(e, ValueError):
            p["status"] = "failed"
            creators.log(p["creator"], f"Post stopped on {p['account_name']}: {p['error']}")
        elif p["tries"] < 3 and clip and acc:
            delay = min(3600, 600 * (2 ** max(0, p["tries"] - 1)))
            p.update(status="scheduled", due_at=time.time() + delay)
        else:
            p["status"] = "failed"
            creators.log(p["creator"], f"Post failed on {p['account_name']}: {p['error']}")
            alerts.notify(f"post failed on {p['account_name']} ({p['title']}): {p['error'][:200]}", kind="post")
    with _lock:
        changed = [p, *_space_batch(p)]
        _save()
    _sync_rows(changed)
    if p["status"] == "posted":
        creators.log(p["creator"], f"Posted to {acc['name']}: {title}")


def _space_batch(p):
    """Move later entries when an earlier upload takes longer, is delayed, or is tried again."""
    if not p.get("batch"):
        return []
    gap = p["gap_seconds"]
    anchor = p["due_at"] if p["status"] == "scheduled" else time.time()
    changed = []
    later = sorted((q for q in _posts if q.get("batch") == p["batch"] and q["status"] == "scheduled"
                    and q["batch_index"] > p["batch_index"]), key=lambda q: q["batch_index"])
    for row in later:
        due = max(row["due_at"], anchor + gap)
        if row["due_at"] != due:
            row["due_at"] = due
            changed.append(row)
        anchor = due
    return changed


def _earliest_short_slot(p, job, now):
    """Wait for the previous actual upload, and for the owner-selected local daily cap."""
    same_channel = [q for q in _posts if q["platform"] == "youtube" and q["account"] == p["account"]
                    and q["status"] == "posted"]
    last = max((q.get("posted_at") or 0 for q in same_channel), default=0)
    earliest = max(now, last + (p.get("gap_seconds") or 0))
    creator = creators.get(job.get("creator")) or creators.DEFAULTS
    cap = creator["daily_cap"]
    if cap and sum(_day(q.get("posted_at") or 0) == _day(now) for q in same_channel) >= cap:
        tomorrow = time.localtime(now + 86400)
        earliest = max(earliest, time.mktime((tomorrow.tm_year, tomorrow.tm_mon, tomorrow.tm_mday,
                                           0, 0, 0, 0, 0, -1)))
    return earliest


def _run():
    while True:
        _wake.wait(15)
        _wake.clear()
        _reconcile_prompt_posts()
        now = time.time()
        with _lock:
            due = sorted((p for p in _posts if p["status"] == "scheduled" and (p.get("due_at") or 0) <= now
                          and p.get("user")), key=lambda p: p.get("due_at") or 0)
        for p in due:
            try:
                with ctx.as_user(p["user"]):
                    if accounts.settings()["paused"]:
                        continue
                    job = jobs.get(p["job"])
                    if not job:
                        with _lock:
                            if p["status"] != "scheduled":
                                continue
                            p["status"] = "failed"
                            p["error"] = "That video is no longer available."
                            _save()
                        _mirror(p)
                        continue
                    with _lock:
                        if p["status"] != "scheduled" or p["due_at"] > time.time():
                            continue
                        if _restart_pending or blocked_until(p["platform"], p["account"]) > time.time():
                            continue
                        if p.get("shorts"):
                            now = time.time()
                            slot = _earliest_short_slot(p, job, now)
                            if slot > now:
                                p["due_at"] = slot
                                changed = [p, *_space_batch(p)]
                                _save()
                                _sync_rows(changed)
                                continue
                        if p.get("automatic") and job.get("automation", {}).get("revoked"):
                            p.update(status="cancelled", error="Automatic publishing was revoked for this video.")
                            _save()
                            _mirror(p)
                            continue
                        p["status"] = "posting"
                        _save()  # a restart must not resend an upload with an unknown outcome
                    _mirror(p)
                    _post(p)
            except Exception:  # noqa: BLE001
                if p.get("status") == "posting":
                    p["tries"] = int(p.get("tries") or 0) + 1
                    if p["tries"] < 3:
                        p.update(status="scheduled", due_at=time.time() + min(900, 30 * p["tries"]),
                                 error="The upload stopped unexpectedly and will be tried again.")
                    else:
                        p.update(status="failed", error="The upload stopped unexpectedly.")
                    with _lock:
                        changed = [p, *_space_batch(p)]
                        _save()
                    try:
                        with ctx.as_user(p["user"]):
                            _sync_rows(changed)
                    except Exception:  # noqa: BLE001
                        pass


def _stats_for(recent):
    if blocked_until("youtube") <= time.time():
        _youtube_stats(recent)
    if blocked_until("instagram") <= time.time():
        _instagram_stats(recent)


def _youtube_stats(recent):
    for aid in {p["account"] for p in recent if p["platform"] == "youtube"}:
        acc = accounts.get(aid)
        if acc and blocked_until("youtube", aid) <= time.time():
            try:
                views = accounts.youtube_views(acc, [p["remote_id"] for p in recent if p["account"] == aid])
            except accounts.PlatformLimit as e:
                _record_limit("youtube", e, aid)
                if not e.account_only:
                    return
                continue
            for p in recent:
                if p["account"] == aid and p["remote_id"] in views:
                    p["views"] = views[p["remote_id"]]


def _instagram_stats(recent):
    for p in recent:
        acc = accounts.get(p["account"]) if p["platform"] == "instagram" else None
        if acc and blocked_until("instagram", p["account"]) <= time.time():
            try:
                v = accounts.instagram_views(acc, p["remote_id"])
            except accounts.PlatformLimit as e:
                _record_limit("instagram", e, p["account"])
                if not e.account_only:
                    return
                continue
            if v is not None:
                p["views"] = v


def _stats():
    while True:
        for uid in {p.get("user") for p in _posts if p.get("user")}:
            try:
                with ctx.as_user(uid):
                    _stats_for([p for p in _mine() if p["status"] == "posted" and time.time() - p["posted_at"] < 14 * 86400])
            except Exception:  # noqa: BLE001
                pass
        _save()
        time.sleep(1800)


def check_eligibility(job: dict, clip: dict, account_id: str, overrides: dict = None) -> dict:
    """Verify rights, rendered 9:16 MP4 integrity, unique title/description copy, and connected account before enqueueing."""
    reasons = []
    if not job or not clip:
        return {"eligible": False, "status": "Held", "reasons": ["Clip or project not found."]}
    if job.get("rights_cleared") is False:
        reasons.append("Confirm source rights for this video before publishing.")
    if clip.get("status") != "done":
        reasons.append("Clip has not finished rendering yet.")
    path = None
    try:
        path = _clip_file(job, clip)
        spec = media.probe(path, require_audio=False)
        if spec["width"] * 16 != spec["height"] * 9:
            reasons.append(f"Clip is {spec['width']}x{spec['height']} instead of 9:16 vertical.")
        if spec["duration"] > 180:
            reasons.append("Clip exceeds the 180-second vertical Short limit.")
    except Exception as exc:
        reasons.append(str(exc))

    acc = accounts.get(account_id) if account_id else None
    if not acc:
        reasons.append("Connect a destination account in Settings → Connected Accounts.")
    meta = jobs.post_metadata(job, clip, overrides)
    try:
        brain.validate_post_title(meta["title"])
    except ValueError as exc:
        reasons.append(str(exc))
    try:
        brain.validate_post_description(meta["description"])
    except ValueError as exc:
        reasons.append(str(exc))
    if acc:
        with _lock:
            hist = [
                {"title": p.get("title", ""), "description": p.get("description", "")}
                for p in _mine()
                if p.get("account") == acc["id"]
                and (p.get("job"), p.get("clip")) != (job["id"], clip["id"])
                and p.get("status") != "cancelled"
            ]
        if brain.is_near_duplicate_copy(meta["title"], meta["description"], hist):
            reasons.append("Title or description duplicates or closely resembles an existing post on this channel.")
    return {
        "eligible": len(reasons) == 0,
        "status": "Scheduled" if len(reasons) == 0 else "Held",
        "reasons": reasons,
        "metadata": meta,
        "account": acc["name"] if acc else "",
    }


def hold_post(pid: str, reason: str = "Held for review by user."):
    with _lock:
        p = next((p for p in _mine() if p["id"] == pid), None)
        if not p or p["status"] not in ("scheduled", "failed"):
            raise ValueError("Only scheduled or failed posts can be placed on hold.")
        p.update(status="held", pipeline_stage="validation", error=reason)
        _save()
    _sync_rows([p])
    return p


def approve_held(pid: str, visibility: str = None):
    with _lock:
        p = next((p for p in _mine() if p["id"] == pid), None)
        if not p or p["status"] not in ("held", "scheduled", "failed"):
            raise ValueError("Only held, waiting, or failed posts can be approved.")
        if visibility in ("private", "unlisted", "public"):
            p["visibility"] = visibility
        p.update(status="scheduled", pipeline_stage="scheduling",
                 due_at=max(time.time(), blocked_until(p["platform"], p["account"])), error=None)
        _save()
    _sync_rows([p])
    return p


def cancel(pid):
    with _lock:
        p = next((p for p in _mine() if p["id"] == pid), None)
        if not p or p["status"] not in ("scheduled", "held"):
            raise ValueError("Only posts that are still waiting can be cancelled.")
        p["status"] = "cancelled"
        _save()
    _sync_rows([p])


def expedite(pid, jid, cid):
    with _lock:
        post = next((p for p in _mine() if p["id"] == pid and p["platform"] == "youtube"
                     and p["job"] == jid and p["clip"] == cid), None)
        if not post or post["status"] not in ("scheduled", "held"):
            raise ValueError("Only a waiting YouTube post can be moved forward.")
        if not accounts.get(post["account"]):
            raise ValueError("Reconnect the channel selected for this post.")
        if post.get("batch"):
            raise ValueError("This clip is part of an ordered batch. Its place in the schedule is fixed.")
        post["status"] = "scheduled"
        post["due_at"] = max(time.time(), blocked_until("youtube", post["account"]))
        _save()
    _sync_rows([post])


def retry(pid):
    with _lock:
        p = next((p for p in _mine() if p["id"] == pid), None)
        if not p or p["status"] not in ("failed", "cancelled", "held"):
            raise ValueError("Only failed, held, or cancelled posts can be retried.")
        job = jobs.get(p["job"])
        if not job:
            raise ValueError("That video is no longer available.")
        if p.get("automatic") and job.get("automation", {}).get("revoked"):
            raise ValueError("Automatic publishing was revoked. Review the clip and queue a new post by hand.")
        if any(q is not p and (q["job"], q["clip"], q["account"]) == (p["job"], p["clip"], p["account"])
               and q["status"] in OPEN + ("posted",) for q in _mine()):
            raise ValueError("A post for this clip and account already exists.")
        p.update(status="scheduled", pipeline_stage="scheduling",
                 due_at=max(time.time(), blocked_until(p["platform"], p["account"])), tries=0, error=None)
        changed = [p, *_space_batch(p)]
        _save()
    _sync_rows(changed)


def overview() -> dict:
    today = _day(time.time())
    _posts = _mine()  # everything below is about the signed-in user only
    rows = []
    all_cs, all_js = creators.all_creators(), jobs.list_jobs()
    for c in all_cs:
        js = [j for j in all_js if j["creator"] == c["id"]]
        clips = [k for j in js for k in j["clips"] if k.get("status") == "done"]
        ps = [p for p in _posts if p["creator"] == c["id"]]
        views = sum(p["views"] or 0 for p in ps)
        rows.append({
            "id": c["id"], "name": c["name"],
            "state": "recording" if live.active_for(c["id"]) else "waiting" if c["auto_watch"] and c["channel"] else "idle",
            "autopost": c["autopost"] and bool(c["accounts"]),
            "clips_today": sum(1 for k in clips if _day(k.get("made_at", 0)) == today), "clips_total": len(clips),
            "posted_today": sum(1 for p in ps if p["status"] == "posted" and _day(p["posted_at"]) == today),
            "posted_total": sum(1 for p in ps if p["status"] == "posted"),
            "queued": sum(1 for p in ps if p["status"] in OPEN), "failed": sum(1 for p in ps if p["status"] == "failed"),
            "views": views, "earnings": round(views / 1000 * c["rate_per_1k"], 2)})
    names = {c["id"]: c["name"] for c in all_cs}
    queue = sorted((p for p in _posts if p["status"] in OPEN), key=lambda p: p["due_at"])
    done = sorted((p for p in _posts if p["status"] in ("posted", "failed", "cancelled")), key=lambda p: -(p.get("posted_at") or p["due_at"]))[:15]
    show = [{**{k: v for k, v in p.items() if k not in ("user", "upload_session")},
             "creator_name": names.get(p["creator"], "")} for p in queue + done]
    # last 14 days, oldest first, for the home graph
    days = [_day(time.time() - 86400 * i) for i in range(13, -1, -1)]
    made, posted, views = {d: 0 for d in days}, {d: 0 for d in days}, {d: 0 for d in days}
    for j in all_js:
        for k in j["clips"]:
            d = _day(k.get("made_at") or j["created"])
            if k.get("status") == "done" and d in made:
                made[d] += 1
    for p in _posts:
        if p["status"] == "posted" and _day(p["posted_at"]) in posted:
            posted[_day(p["posted_at"])] += 1
            views[_day(p["posted_at"])] += p["views"] or 0
    daily = [{"day": d, "clips": made[d], "posted": posted[d], "views": views[d]} for d in days]
    return {"paused": accounts.settings()["paused"], "creators": rows, "posts": show, "daily": daily,
            "post_counts": {"waiting": len(queue), "failed": sum(p["status"] == "failed" for p in _posts)},
            "cooldowns": [{"account": a["id"], "name": a["name"], "until": until}
                          for a in accounts.list_accounts()
                          if (until := blocked_until(a["platform"], a["id"])) > time.time()],
            "alerts": alerts.configured(), "recording": len(live.active_mine())}


def digest_text() -> str:
    o = overview()
    lines = ["PeakCut daily summary"]
    for r in o["creators"]:
        lines.append(f"- {r['name']}: {r['state']}, {r['clips_today']} clips today, {r['posted_today']} posted today, "
                     f"{r['queued']} waiting, {r['failed']} failed, {r['views']} views")
    if not o["creators"]:
        lines.append("No creators set up yet.")
    if o["paused"]:
        lines.append("Posting is paused.")
    return "\n".join(lines)


def start():
    with _lock:
        for p in _posts:
            if p.get("account") == "youtube_auto" and p["status"] in OPEN:
                p.update(status="failed", error="This legacy schedule had no connected channel. Choose a channel to queue the clip.")
            if p["status"] == "posting":  # interrupted mid-upload last time
                settle_interrupted(p)
        _save()
    jobs.on_clip_ready.append(on_clip_ready)
    threading.Thread(target=_run, daemon=True).start()
    threading.Thread(target=_stats, daemon=True).start()
    threading.Thread(target=alerts.digest_loop, args=(digest_text,), daemon=True).start()
    threading.Thread(target=alerts.keep_awake_loop,
                     args=(lambda: bool(live.active()) or any(p["status"] in OPEN for p in _posts),), daemon=True).start()
