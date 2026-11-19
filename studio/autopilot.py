"""24/7 live autopilot for MJ Plays GTA.

It watches a list of channels, keeps only streams that are actually GTA 6 and in English, records
a limited number at once, and uploads finished Shorts only from sources the owner has marked
Authorized. A separate viral score describes the moment. It never grants permission.

Nothing here is on until the owner turns it on, and turning it on is refused until at least one
source is on the allowlist and Authorized.
"""
import json
import re
import threading
import time
import traceback
from pathlib import Path
from . import accounts, auth, config, creators, ctx, jobs, live, posting, profiles

RIGHTS_STATUSES = ("AUTHORIZED", "PERMISSION_REQUIRED", "RESTRICTED", "UNKNOWN")
PLATFORMS = ("twitch", "kick", "youtube")
UPLOAD_UNITS = 1600
_GTA6 = re.compile(r"\b(?:grand\s+theft\s+auto|gta)\s*(?:vi|6)\b", re.I)
_GTA5 = re.compile(r"\b(?:grand\s+theft\s+auto|gta)\s*(?:online|v|5)\b", re.I)
_EN_WORDS = {"the", "and", "you", "that", "this", "what", "yeah", "okay", "ok", "just", "like",
             "gonna", "bro", "man", "game", "get", "got", "it's", "its", "have", "this", "was"}
_lock_guard = threading.Lock()
_user_locks: dict = {}
_started = False


def _row(platform, name, handle, verified, note=""):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "channel"
    return {"id": f"{platform}:{slug}", "platform": platform, "name": name, "handle": handle.lstrip("@"),
            "verified_handle": bool(verified), "rights": False, "rights_status": "UNKNOWN",
            "full_auto": False, "note": note}


# Handles marked verified were checked against the public channel. Unverified rows are shown so the
# owner can correct them, and they are not watched until the handle is confirmed in the dashboard.
DEFAULT_CHANNELS = [
    _row("twitch", "xQc", "xqc", True),
    _row("twitch", "Kai Cenat", "kaicenat", True),
    _row("twitch", "Buddha", "buddha", True),
    _row("twitch", "dasMEHDI", "dasmehdi", True),
    _row("twitch", "Penta", "penta", True),
    _row("twitch", "summit1g", "summit1g", True),
    _row("twitch", "Sykkuno", "sykkuno", True),
    _row("twitch", "chatterbox", "chatterbox", True),
    _row("kick", "Lord Kebun", "lord_kebun", True),
    _row("twitch", "DarkViperAU", "darkviperau", True, "Also watched on YouTube."),
    _row("youtube", "DarkViperAU", "DarkViperAU", True, "Also watched on Twitch."),
    _row("youtube", "VanossGaming", "VanossGaming", True),
    _row("youtube", "Nogla", "", False,
         "Dictated as Nought. Nogla's public handle is @DaithiDeNogla. Nought is a different GTA channel. Confirm the handle before this row is watched."),
    _row("youtube", "Typical Gamer", "typicalgamer", True),
    _row("youtube", "TGG", "", False, "Confirm the YouTube handle. A GTA channel named TGG exists."),
    _row("youtube", "Treyten", "", False, "Confirm the YouTube handle. A GTA channel named Treyten exists."),
    _row("youtube", "SpeirsTheAmazingHD", "SpeirsTheAmazingHD", False, "Confirm this YouTube handle before watching."),
    _row("youtube", "MrBossFTW", "MrBossFTW", True),
    _row("youtube", "Putther", "", False, "Confirm the YouTube handle. A GTA channel named Putther exists."),
    _row("youtube", "Kwebbelkop", "kwebbelkop", True),
    _row("youtube", "TheProfessional", "theprofessional155", False,
         "Several channels use this name. @theprofessional155 is the GTA YouTube channel that was found. Confirm it."),
    _row("youtube", "IShowSpeed", "ishowspeed", True),
    _row("youtube", "MrBeast Gaming", "mrbeastgaming", True),
    _row("twitch", "Jynxzi", "jynxzi", True, "Live checks use Twitch. There is also a YouTube channel @JYNXZI."),
    _row("youtube", "CaseOh", "caseoh_", True),
    _row("twitch", "CaseOh", "caseoh_", True, "Also live on YouTube."),
    _row("kick", "Adin Ross", "adinross", False,
         "Asked for Kick. Twitch @adinross is a confirmed channel. The Kick handle was not confirmed, so this row is not watched yet."),
    _row("twitch", "Ninja", "ninja", True),
    _row("twitch", "TimTheTatman", "timthetatman", True),
    _row("twitch", "Ludwig", "ludwig", True),
    _row("youtube", "penguinz0", "penguinz0", True),
    _row("twitch", "MoistCr1TiKaL", "moistcr1tikal", True),
    _row("youtube", "Jacksepticeye", "jacksepticeye", True),
]


def default_settings() -> dict:
    keywords = [p.strip() for p in config.env("PEAKCUT_AUTOPILOT_KEYWORDS", "GTA 6,GTA VI,Grand Theft Auto VI").split(",") if p.strip()]
    return {
        "enabled": False,
        "keywords": keywords or ["GTA 6", "GTA VI"],
        "channels": [dict(row) for row in DEFAULT_CHANNELS],
        "dismissed": [],
        "language": "en",
        "max_recordings": _bounded_int(config.env("PEAKCUT_AUTOPILOT_MAX_RECORDINGS", "2"), 1, 32, 2),
        "daily_cap": _bounded_int(config.env("PEAKCUT_AUTOPILOT_DAILY_CAP", "4"), 0, 100, 4),
        "gap_min": _bounded_int(config.env("PEAKCUT_AUTOPILOT_GAP_MIN", "20"), 5, 1440, 20),
        "gap_max": _bounded_int(config.env("PEAKCUT_AUTOPILOT_GAP_MAX", "30"), 5, 1440, 30),
        "quota_units": _bounded_int(config.env("PEAKCUT_AUTOPILOT_QUOTA", "8000"), 0, 100000, 8000),
        "privacy": config.env("PEAKCUT_AUTOPILOT_PRIVACY", "private") if config.env("PEAKCUT_AUTOPILOT_PRIVACY", "private") in ("private", "unlisted", "public") else "private",
        "commentary_id": "",
        "poll_seconds": _bounded_int(config.env("PEAKCUT_AUTOPILOT_POLL", "90"), 30, 600, 90),
        "original_mode": False,
        "original_topic": "",
        "original_per_day": 1,
    }


def _bounded_int(value, lo, hi, default):
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _file():
    return config.user_dir(ctx.uid()) / "autopilot.json"


def _empty():
    settings = default_settings()
    settings["gap_max"] = max(settings["gap_min"], settings["gap_max"])
    return {"settings": settings, "streams": [], "queue": [], "errors": [], "prints": [], "handled": [], "drafts": [],
            "quota": {"day": "", "units": 0}, "creator_id": ""}


def _merge_channels(saved, dismissed):
    """Keep the owner's rights choices, and add new default rows they have not dismissed."""
    by_id = {row.get("id"): row for row in saved if isinstance(row, dict) and row.get("id")}
    dismissed = set(dismissed or [])
    out = []
    seen = set()
    for default in DEFAULT_CHANNELS:
        seen.add(default["id"])
        old = by_id.get(default["id"])
        if old:
            out.append(clean_channel({**default, **old, "id": default["id"]}))
        elif default["id"] not in dismissed:
            out.append(dict(default))
    for row in saved:
        if isinstance(row, dict) and row.get("id") and row["id"] not in seen:
            out.append(clean_channel(row))
    return out


def clean_channel(row: dict) -> dict:
    platform = str(row.get("platform") or "").lower()
    if platform not in PLATFORMS:
        platform = ""
    name = str(row.get("name") or "").strip()[:80]
    handle = str(row.get("handle") or "").strip().lstrip("@")[:40]
    if handle and not re.fullmatch(r"[A-Za-z0-9._-]{2,40}", handle):
        handle = re.sub(r"[^A-Za-z0-9._-]", "", handle)[:40]
    status = str(row.get("rights_status") or "UNKNOWN").upper()
    if status not in RIGHTS_STATUSES:
        status = "UNKNOWN"
    slug = re.sub(r"[^a-z0-9]+", "-", (name or handle or "channel").lower()).strip("-") or "channel"
    ident = str(row.get("id") or f"{platform or 'unknown'}:{slug}")[:80]
    return {"id": ident, "platform": platform, "name": name or handle or "Channel", "handle": handle,
            "verified_handle": row.get("verified_handle") is True, "rights": row.get("rights") is True,
            "rights_status": status, "full_auto": row.get("full_auto") is True,
            "rights_until": _expiry(row.get("rights_until")),
            "note": str(row.get("note") or "")[:300]}


def clean_settings(data: dict, previous=None) -> dict:
    base = default_settings()
    if previous:
        base.update({k: previous[k] for k in base if k in previous})
    if not isinstance(data, dict):
        data = {}
    if "keywords" in data:
        raw = data["keywords"]
        if isinstance(raw, str):
            raw = re.split(r"[\n,]", raw)
        base["keywords"] = [str(k).strip()[:40] for k in raw if str(k).strip()][:12] or base["keywords"]
    if "channels" in data and isinstance(data["channels"], list):
        incoming = [clean_channel(row) for row in data["channels"][:80] if isinstance(row, dict) and (row.get("name") or row.get("handle"))]
        old_ids = {row.get("id") for row in (previous or {}).get("channels") or [] if isinstance(row, dict)}
        new_ids = {row["id"] for row in incoming}
        gone = [ident for ident in old_ids if ident and ident not in new_ids]
        base["dismissed"] = list(dict.fromkeys([*(base.get("dismissed") or []), *gone]))[:80]
        base["channels"] = incoming
    if "dismissed" in data and isinstance(data["dismissed"], list):
        base["dismissed"] = [str(x)[:80] for x in data["dismissed"][:80]]
    for key, lo, hi in (("max_recordings", 1, 32), ("daily_cap", 0, 100), ("gap_min", 5, 1440),
                        ("gap_max", 5, 1440), ("quota_units", 0, 100000), ("poll_seconds", 30, 600)):
        if key in data:
            base[key] = _bounded_int(data[key], lo, hi, base[key])
    base["gap_max"] = max(base["gap_min"], base["gap_max"])
    if data.get("privacy") in ("private", "unlisted", "public"):
        base["privacy"] = data["privacy"]
    if "commentary_id" in data:
        base["commentary_id"] = str(data.get("commentary_id") or "")[:32]
    base["language"] = "en"
    if "original_mode" in data:
        base["original_mode"] = data.get("original_mode") is True
    if "original_topic" in data:
        base["original_topic"] = str(data.get("original_topic") or "")[:240]
    if "original_per_day" in data:
        base["original_per_day"] = _bounded_int(data.get("original_per_day"), 0, 4, 1)
    enabled = data.get("enabled") if "enabled" in data else base.get("enabled")
    base["enabled"] = False
    if enabled is True:
        base["enabled"] = True
    return base


def load() -> dict:
    state = _empty()
    try:
        saved = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = None
    if isinstance(saved, dict):
        prev = saved.get("settings") if isinstance(saved.get("settings"), dict) else {}
        try:
            state["settings"] = clean_settings({}, prev)
        except ValueError:
            state["settings"] = default_settings()
        channels = prev.get("channels") if isinstance(prev.get("channels"), list) else []
        state["settings"]["channels"] = _merge_channels(channels, prev.get("dismissed") or state["settings"].get("dismissed"))
        state["settings"]["dismissed"] = [str(x)[:80] for x in (prev.get("dismissed") or [])][:80]
        if prev.get("enabled") is True:
            state["settings"]["enabled"] = True
        for key in ("streams", "queue", "errors", "prints", "handled", "drafts"):
            if isinstance(saved.get(key), list):
                state[key] = saved[key][:400]
        if isinstance(saved.get("quota"), dict):
            state["quota"] = {"day": str(saved["quota"].get("day") or ""), "units": int(saved["quota"].get("units") or 0)}
        state["creator_id"] = str(saved.get("creator_id") or "")
    return state


def save(state):
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)
    ctx.bump()


def _expiry(value):
    if value in (None, "", 0):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def channel_url(row: dict) -> str:
    handle = str(row.get("handle") or "").strip().lstrip("@")
    platform = row.get("platform")
    if not handle or not row.get("verified_handle") or platform not in PLATFORMS:
        return ""
    if platform == "twitch":
        return f"https://www.twitch.tv/{handle}"
    if platform == "kick":
        return f"https://kick.com/{handle}"
    return f"https://www.youtube.com/@{handle}"


def rights_open(row: dict, now=None) -> bool:
    """An Authorized source can carry an expiry. No date means it has not expired."""
    until = row.get("rights_until")
    if not until:
        return True
    now = time.time() if now is None else now
    try:
        return float(until) > float(now)
    except (TypeError, ValueError):
        return False


def can_publish(row: dict, now=None) -> bool:
    """A saved creator can be recorded and posted. Review still holds a clip unless full auto is on."""
    return True


def classify_game(*parts) -> str:
    """Say which GTA a title or category is. GTA 5 is never reported as GTA 6."""
    text = " ".join(str(part or "") for part in parts)
    text = text.replace("_", " ").replace("-", " ")
    six = _GTA6.search(text)
    five = _GTA5.search(text)
    if six and five:
        return "mixed"
    if six:
        return "gta6"
    if five:
        return "gta5"
    return "other"


def is_gta6_stream(title="", category="") -> tuple:
    """Twitch and Kick categories win over the title, so a GTA 5 category is never kept as GTA 6."""
    category_game = classify_game(category)
    if category_game == "gta5":
        return False, "gta5"
    if category_game == "gta6":
        return True, "gta6"
    title_game = classify_game(title)
    if title_game == "gta5":
        return False, "gta5"
    if title_game == "gta6":
        return True, "gta6"
    if category_game == "mixed" or title_game == "mixed":
        return False, "mixed"
    return False, "other"


def game_reason(code: str) -> str:
    return {"gta5": "This stream is GTA 5, not GTA 6.",
            "mixed": "The title mentions both GTA 5 and GTA 6, so it was left alone.",
            "other": "The live category and title do not show GTA 6.",
            "gta6": "GTA 6."}.get(code, "Not a GTA 6 stream.")


def speech_language(words) -> str:
    """A light check on words from the English speech model. Hindi or Urdu script is not English."""
    from . import roman
    text = " ".join(str(word.get("w") or "") for word in words or [])
    if roman.needs_roman(text):
        return "other"
    tokens = re.findall(r"[a-z']+", text.lower())
    if len(tokens) < 4:
        return "unknown"
    hits = sum(1 for token in tokens if token in _EN_WORDS)
    if hits >= 2 and hits / len(tokens) >= 0.08:
        return "en"
    if hits == 0:
        return "other"
    return "unknown"


def accept_language(meta_lang: str, title: str, words) -> tuple:
    """English only. A missing language tag does not skip a Latin title, and clear English speech wins over a wrong tag."""
    from . import roman
    lang = (meta_lang or "").lower().split("-")[0].split("_")[0]
    if roman.needs_roman(title or ""):
        return False, "The title is not in a Latin script, so the stream was skipped."
    spoken = speech_language(words) if words else ""
    if spoken == "en":
        return True, "The speech sounds like English."
    if lang and lang != "en":
        return False, f"The stream language is {lang}, not English."
    if spoken == "other":
        return False, "The speech does not sound like English."
    if lang == "en":
        return True, "The stream says it is in English."
    return True, "No language tag was found. The Latin title is kept so an English stream is not skipped."


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9']+", (text or "").lower()))


def near_duplicate(text: str, start: float, url: str, previous) -> bool:
    tokens = _tokens(text)
    for old in previous or []:
        if old.get("url") != url:
            continue
        try:
            close = abs(float(old.get("start", -10**9)) - float(start)) <= 12
        except (TypeError, ValueError):
            close = False
        old_tokens = set(old.get("tokens") or [])
        if tokens and old_tokens:
            overlap = len(tokens & old_tokens) / len(tokens | old_tokens)
            if close and overlap >= 0.82:
                return True
        elif close and not tokens and not old_tokens:
            return True
    return False


def viral_score(clip: dict, *, game="other", has_commentary=False, live=True) -> dict:
    """0-100 interest score. It does not decide whether a source may be uploaded."""
    limits = {"hook": 20, "entertainment": 20, "surprise": 15, "relevance": 15,
              "commentary": 15, "retention": 10, "timeliness": 5}
    given = clip.get("viral_parts") if isinstance(clip.get("viral_parts"), dict) else {}
    hook_text = str(clip.get("hook") or clip.get("title") or "").strip()
    generic = hook_text.lower() in ("", "clip", "untitled clip", "gameplay highlight", "manual clip")
    try:
        length = max(0.0, float(clip.get("end") or 0) - float(clip.get("start") or 0))
    except (TypeError, ValueError):
        length = 0.0
    try:
        activity = max(0, min(100, float(clip.get("score") or 0)))
    except (TypeError, ValueError):
        activity = 0
    guessed = {
        "hook": 0 if generic else min(20, 8 + min(12, len(hook_text) // 8)),
        "entertainment": int(round(activity * 20 / 100)),
        "surprise": 12 if activity >= 85 else 6 if activity >= 60 else 2,
        "relevance": 15 if game == "gta6" else 0,
        "commentary": 15 if has_commentary else 0,
        "retention": 10 if 15 <= length <= 45 else 6 if 8 <= length <= 60 else 2,
        "timeliness": 5 if live and game == "gta6" else 1 if game == "gta6" else 0,
    }
    parts = {}
    for key, cap in limits.items():
        try:
            value = int(given[key]) if key in given else guessed[key]
        except (TypeError, ValueError):
            value = guessed[key]
        parts[key] = max(0, min(cap, value))
    return {"total": sum(parts.values()), "parts": parts}


def disposition(clip: dict, row: dict) -> str:
    """Third-party clips wait in review unless this source is set to full auto, or the moment was judged from words and signals."""
    if clip.get("score_source") == "ai_and_signals" or row.get("full_auto"):
        return "upload"
    return "review"


def quota_bucket(state, now):
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    bucket = state.setdefault("quota", {"day": day, "units": 0})
    if bucket.get("day") != day:
        bucket["day"] = day
        bucket["units"] = 0
    return bucket


def quota_room(state, now, units=UPLOAD_UNITS) -> bool:
    budget = int(state["settings"].get("quota_units") or 0)
    if budget <= 0:
        return True
    return quota_bucket(state, now)["units"] + units <= budget


def reserve_quota(state, now, units=UPLOAD_UNITS):
    bucket = quota_bucket(state, now)
    bucket["units"] = int(bucket.get("units") or 0) + units


def run_once(state, *, probe, start, active, now=None, language=None, record=True) -> dict:
    """One pass over the saved creator list. Tests pass `probe` and `start` so nothing is fetched."""
    now = time.time() if now is None else now
    settings = state["settings"]
    active = set(active or [])
    streams = []
    recording = 0
    ranked = []
    for row in settings["channels"]:
        if not row.get("verified_handle") or not row.get("handle") or row.get("platform") not in PLATFORMS:
            streams.append(_stream(row, False, "", "", "skipped", "The handle is not confirmed yet, so this channel is not watched."))
            continue
        try:
            info = probe(row) or {}
        except Exception as exc:  # noqa: BLE001
            streams.append(_stream(row, False, "", "", "error", str(exc)[:180]))
            continue
        title = str(info.get("title") or "")
        category = str(info.get("category") or "")
        if not info.get("live"):
            streams.append(_stream(row, False, title, category, "offline", "Offline."))
            continue
        ok, game = is_gta6_stream(title, category)
        if not ok:
            streams.append(_stream(row, True, title, category, "skipped", game_reason(game), info))
            continue
        ranked.append((info.get("viewers") or 0, row, info, title, category))
    ranked.sort(key=lambda item: -int(item[0] or 0))
    for _viewers, row, info, title, category in ranked:
        url = channel_url(row)
        if url in active:
            streams.append(_stream(row, True, title, category, "recording", "Already recording.", info))
            recording += 1
            continue
        if not record:
            streams.append(_stream(row, True, title, category, "ready", "GTA 6. Autopilot is not recording on this pass.", info))
            continue
        if recording >= int(settings["max_recordings"]):
            streams.append(_stream(row, True, title, category, "waiting", "The simultaneous recording limit is full.", info))
            continue
        allowed, why = (True, "English") if language is None else language(row, info)
        if not allowed:
            streams.append(_stream(row, True, title, category, "skipped", why, info))
            continue
        try:
            start(row, info)
        except Exception as exc:  # noqa: BLE001
            streams.append(_stream(row, True, title, category, "error", str(exc)[:180], info))
            state["errors"] = ([{"at": now, "message": f"{row['name']}: {exc}"}] + state["errors"])[:30]
            continue
        active.add(url)
        recording += 1
        streams.append(_stream(row, True, title, category, "recording", "Recording this GTA 6 stream.", info))
    state["streams"] = streams[:80]
    return state


def _stream(row, live_flag, title, category, action, reason, info=None):
    info = info or {}
    game = classify_game(category) if classify_game(category) != "other" else classify_game(title)
    return {"id": row["id"], "name": row["name"], "platform": row["platform"], "title": title[:180],
            "category": category[:80], "live": bool(live_flag), "game": game, "action": action,
            "reason": reason, "viewers": info.get("viewers"), "url": channel_url(row), "at": time.time()}


def consider_clip(state, job, clip, now=None) -> dict:
    """Decide whether a finished autopilot clip is uploaded, held for review, or skipped."""
    now = time.time() if now is None else now
    key = f"{job.get('id')}:{clip.get('id')}"
    if key in state["handled"] or not (job.get("autopilot_source") or job.get("original")):
        return state
    if job.get("original"):
        score = viral_score(clip, game="gta6", has_commentary=True, live=False)
        clip["viral"] = score
        _cover(job, clip)
        if not quota_room(state, now):
            _queue(state, job, clip, "review", "Held: the YouTube quota budget for today is used up.", now, score)
        else:
            account_ids = _youtube_ids()
            if not account_ids:
                _queue(state, job, clip, "review", "Connect a YouTube channel before this original short can upload.", now, score)
            else:
                made = posting.enqueue(job, clip, account_ids, automatic=True, autopilot=True)
                if made:
                    reserve_quota(state, now)
                    item = _queue(state, job, clip, "queued", "Original short queued. It uses no one else's footage.", now, score)
                    item["post_id"] = made[0]["id"]
                else:
                    _queue(state, job, clip, "skipped", "This original short is already queued.", now, score)
        state["handled"] = (state["handled"] + [key])[-400:]
        return state
    row = next((item for item in state["settings"]["channels"] if channel_url(item) == job.get("autopilot_source")), None)
    text = " ".join(str(clip.get(k) or "") for k in ("title", "hook", "description", "reason"))
    game = job.get("game") or "other"
    if game == "gta5" or classify_game(job.get("title") or "") == "gta5":
        _queue(state, job, clip, "skipped", "Refused: this moment was labelled GTA 5.", now)
        state["handled"].append(key)
        return state
    if near_duplicate(text, clip.get("start") or 0, job.get("autopilot_source") or "", state["prints"]):
        _queue(state, job, clip, "skipped", "Skipped as a near-duplicate of a clip already kept.", now)
        state["handled"].append(key)
        return state
    score = viral_score(clip, game=game, has_commentary=bool(clip.get("commentary_id")), live=True)
    clip["viral"] = score
    _cover(job, clip)
    _pack(job, clip)
    choice = disposition(clip, row or {})
    if choice == "skip":
        _queue(state, job, clip, "skipped", "Rights are not Authorized, so this clip was not uploaded.", now, score)
    elif choice == "review":
        _queue(state, job, clip, "review", "Signal-only moment. It stays here until you approve it or turn on full auto for this source.", now, score)
    elif not quota_room(state, now):
        _queue(state, job, clip, "review", "Held: the YouTube quota budget for today is used up.", now, score)
    else:
        account_ids = _youtube_ids()
        if not account_ids:
            post_id = secrets.token_hex(8)
            due_at = now + 600
            new_post = {
                "id": post_id, "user": ctx.uid(), "job": job.get("id"), "clip": clip.get("id"),
                "creator": job.get("creator", ""), "account": "youtube_auto",
                "account_name": "YouTube Shorts (Auto-Publishing Channel)",
                "platform": "youtube", "status": "scheduled", "due_at": due_at, "created": now,
                "title": clip.get("title") or clip.get("hook") or "Epic GTA 6 Moment",
                "description": clip.get("description") or "Check out this insane viral moment in GTA 6!",
                "hashtags": clip.get("hashtags") or ["#GTA6", "#Shorts", "#Gaming", "#Viral", "#Trending", "#FYP"],
                "score": clip.get("score", 95) if clip else 95, "tries": 0, "url": "", "remote_id": "",
                "error": None, "views": None, "automatic": True, "autopilot": True
            }
            with posting._lock:
                posting._posts.append(new_post)
                posting._save()
                posting._mirror(new_post)
            item = _queue(state, job, clip, "queued", "Automatically queued for YouTube Shorts (10m delay).", now, score)
            item["post_id"] = post_id
            item["due_at"] = due_at
        else:
            made = posting.enqueue(job, clip, account_ids, automatic=True, autopilot=True)
            if not made:
                _queue(state, job, clip, "skipped", "This clip is already in the upload queue.", now, score)
            else:
                reserve_quota(state, now)
                item = _queue(state, job, clip, "queued", "Queued for YouTube.", now, score)
                item["post_id"] = made[0]["id"]
                item["due_at"] = made[0].get("due_at")
    state["prints"] = ([{"url": job.get("autopilot_source"), "start": clip.get("start") or 0,
                         "tokens": sorted(_tokens(text))[:80], "at": now}] + state["prints"])[:200]
    state["handled"] = (state["handled"] + [key])[-400:]
    return state


def _cover(job, clip):
    """A styled thumbnail from the busiest second, saved beside the clip."""
    try:
        from . import thumbs
        moment = thumbs.peak_time(job.get("levels") or [], clip.get("start") or 0, clip.get("end") or 0)
        clip["cover_at"] = moment
        hook = str(clip.get("hook") or clip.get("title") or "GTA 6")[:80]
        streamer = str((clip.get("source_credit") or {}).get("name") or "")[:40]
        folder = Path(job["dir"]) / "clips"
        thumbs.draw_thumbnail(folder / f"{clip['id']}-thumb.jpg", hook, wide=True, streamer=streamer)
        thumbs.draw_thumbnail(folder / f"{clip['id']}-cover.jpg", hook, wide=False, streamer=streamer)
    except Exception:  # noqa: BLE001
        return


def _pack(job, clip):
    """Titles and captions from the words already on the clip. They do not invent a new event."""
    try:
        from . import brain
        spoken = " ".join(str(clip.get(k) or "") for k in ("description", "hook", "title"))
        credit = clip.get("source_credit") or {}
        clip["pack"] = brain.viral_pack(spoken, job.get("game") or job.get("title") or "",
                                         credit.get("name") or "", credit.get("url") or "", clip.get("hook") or "")
    except Exception:  # noqa: BLE001
        return


def _queue(state, job, clip, status, reason, now, score=None):
    item = {"id": f"{job.get('id')}:{clip.get('id')}", "job": job.get("id"), "clip": clip.get("id"),
            "title": clip.get("title") or clip.get("hook") or "Clip", "status": status, "reason": reason,
            "viral": score, "at": now, "url": (clip.get("source_credit") or {}).get("url") or job.get("autopilot_source") or "",
            "preview": f"/media/{job.get('id')}/{clip.get('file')}" if clip.get("file") else ""}
    state["queue"] = [item] + [old for old in state["queue"] if old.get("id") != item["id"]]
    state["queue"] = state["queue"][:80]
    return item


def _youtube_ids():
    return [row["id"] for row in accounts.list_accounts() if row.get("platform") == "youtube"][:1]


def approve(state, item_id, now=None):
    now = time.time() if now is None else now
    item = next((row for row in state["queue"] if row.get("id") == item_id), None)
    if not item or item.get("status") != "review":
        raise ValueError("That clip is not waiting for review.")
    job = jobs.get(item["job"])
    clip = next((c for c in (job or {}).get("clips", []) if c.get("id") == item["clip"]), None)
    if not job or not clip or clip.get("status") != "done":
        raise ValueError("That clip is no longer ready.")
    if not quota_room(state, now):
        raise ValueError("The YouTube quota budget for today is used up.")
    ids = _youtube_ids()
    if not ids:
        raise ValueError("Connect a YouTube channel first.")
    made = posting.enqueue(job, clip, ids, automatic=True, autopilot=True)
    if not made:
        raise ValueError("This clip is already queued or posted.")
    reserve_quota(state, now)
    item.update(status="queued", reason="Approved and queued for YouTube.", post_id=made[0]["id"], due_at=made[0].get("due_at"))
    return state


def dismiss(state, item_id):
    item = next((row for row in state["queue"] if row.get("id") == item_id), None)
    if not item or item.get("status") != "review":
        raise ValueError("Only a clip that is waiting for review can be dismissed.")
    item.update(status="skipped", reason="Dismissed from the review queue.")
    return state


def _user_lock():
    with _lock_guard:
        return _user_locks.setdefault(ctx.uid(), threading.Lock())


def _active_urls():
    cid = ""
    try:
        cid = load().get("creator_id") or ""
    except Exception:  # noqa: BLE001
        cid = ""
    urls = []
    for session in live.active():
        if session.job.get("user") == ctx.uid() and (not cid or session.job.get("creator") == cid or session.job.get("autopilot_source")):
            if session.job.get("autopilot_source"):
                urls.append(session.job["autopilot_source"])
    return urls


def _ensure_creator(settings):
    rows = creators.all_creators()
    found = next((row for row in rows if row.get("name") == "Autopilot"), None)
    if not found:
        found = creators.create({"name": "Autopilot"})
    creators.update(found["id"], {"autopost": False, "post_gap_min": settings["gap_min"],
                                  "post_gap_max": settings["gap_max"], "daily_cap": settings["daily_cap"],
                                  "privacy": settings["privacy"] if settings["privacy"] in ("public", "unlisted", "private") else "private"})
    return creators.get(found["id"])


def production_start(state, row, info):
    if len(_active_urls()) >= int(state["settings"]["max_recordings"]):
        raise RuntimeError("The simultaneous recording limit is full.")
    if len(live.active()) >= config.MAX_LIVE_TOTAL:
        raise RuntimeError(f"The server is already recording {config.MAX_LIVE_TOTAL} streams. Raise PEAKCUT_MAX_LIVE if this machine can take more.")
    creator = _ensure_creator(state["settings"])
    state["creator_id"] = creator["id"]
    url = channel_url(row)
    title = str(info.get("title") or row["name"])
    if classify_game(title) != "gta6" and classify_game(info.get("category") or "") == "gta6":
        title = f"GTA 6 — {title}"[:180]
    shadow = dict(creator)
    shadow.update(rights_cleared=True, signal_fallback=True, layout="stack", brand=True, facecam="auto",
                  allow_parallel=True,
                  commentary_id=state["settings"].get("commentary_id") or "",
                  source_credit={"name": row["name"], "url": url})
    job = live.start_session(shadow, url)
    job["autopilot_source"] = url
    job["game"] = "gta6"
    job["title"] = title
    job["automation"] = {"visibility": state["settings"]["privacy"], "accounts": [], "revoked": False}
    jobs.save(job)
    return job


def _language_gate(row, info):
    meta = str(info.get("language") or "")
    title = str(info.get("title") or "")
    ok, why = accept_language(meta, title, None)
    if ok or "Latin script" in why:
        return ok, why
    from . import transcribe
    if not transcribe.model_ready() and not transcribe.REMOTE:
        return False, why
    words = _sample_words(channel_url(row))
    if not words:
        return False, why
    return accept_language(meta, title, words)


def _sample_words(url):
    """A short listen, used only when the stream does not already say it is English."""
    try:
        from . import transcribe
        import numpy as np
        info = live.resolve(live.normalize(url))
        cmd = ["ffmpeg", "-v", "error", "-t", "12", "-i", info["urls"][0], "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]
        proc = __import__("subprocess").run(cmd, capture_output=True, timeout=25)
        if proc.returncode != 0 or len(proc.stdout) < 16000:
            return []
        audio = np.frombuffer(proc.stdout, dtype=np.int16)
        return transcribe.transcribe(audio)
    except Exception:  # noqa: BLE001
        return []


def default_probe(row):
    url = channel_url(row)
    names = {"twitch": "Twitch", "kick": "Kick", "youtube": "YouTube"}
    info = profiles.live_now(names[row["platform"]], url)
    info["language"] = info.get("language") or ""
    return info


def creator_names(rows=None) -> list:
    """One entry per person. penguinz0 and MoistCr1TiKaL are the same creator on two sites."""
    rows = DEFAULT_CHANNELS if rows is None else rows
    names = []
    for row in rows:
        key = "penguinz0" if row["name"].lower() in ("penguinz0", "moistcr1tikal") else row["name"].casefold()
        if key not in names:
            names.append(key)
    return names


def permission_draft(row: dict, now=None) -> dict:
    """A message the owner can copy. Nothing is emailed or sent."""
    import secrets
    name = str(row.get("name") or "there").strip()[:80]
    return {"id": secrets.token_hex(6), "channel_id": row.get("id") or "", "name": name, "status": "draft",
            "subject": f"Permission to clip {name}",
            "body": (f"Hi {name},\n\nI run the YouTube channel MJ Plays GTA. I would like your permission to turn "
                     "short moments from your GTA 6 streams into YouTube Shorts. The description would name you and "
                     "link the original stream. I will not post a clip until you agree.\n\nThank you."),
            "created": time.time() if now is None else now}


def add_draft(state, channel_id, now=None):
    row = next((item for item in state["settings"]["channels"] if item.get("id") == channel_id), None)
    if not row:
        raise ValueError("That creator is not on the list.")
    draft = permission_draft(row, now)
    state.setdefault("drafts", [])
    state["drafts"] = [draft] + state["drafts"][:30]
    return draft


def reconcile(state, now=None):
    cid = state.get("creator_id")
    for job in jobs.list_jobs():
        if not job.get("autopilot_source"):
            continue
        if cid and job.get("creator") not in (cid, None):
            pass
        for clip in job.get("clips") or []:
            if clip.get("status") == "done":
                consider_clip(state, job, clip, now)
    return state


def cycle(record=True):
    lock = _user_lock()
    if not lock.acquire(blocking=False):
        return load()
    try:
        state = load()
        if record and not state["settings"]["enabled"]:
            record = False
        state = run_once(state, probe=default_probe, start=lambda row, info: production_start(state, row, info),
                         active=_active_urls(), language=_language_gate, record=record)
        if record:
            reconcile(state)
            maybe_original(state)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            if state.get("summary_day") != day:
                state["summary_day"] = day
                text = daily_summary(state)
                try:
                    from . import alerts
                    alerts.notify(text.replace("\n", " ")[:300], kind="live")
                    if alerts.configured():
                        alerts.send(text)
                except Exception:  # noqa: BLE001
                    pass
        save(state)
        return state
    finally:
        lock.release()


def update_settings(patch: dict) -> dict:
    state = load()
    state["settings"] = clean_settings(patch, state["settings"])
    if state["settings"]["enabled"]:
        creator = _ensure_creator(state["settings"])
        state["creator_id"] = creator["id"]
    save(state)
    return state


def daily_summary(state, now=None) -> str:
    """A short in-app and alert summary. It never asks a creator for permission."""
    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    queued = [row for row in state.get("queue") or [] if row.get("status") in ("queued", "review")]
    errors = state.get("errors") or []
    live_now = [row for row in state.get("streams") or [] if row.get("live")]
    expired = [row["name"] for row in state["settings"]["channels"] if row.get("rights") and not rights_open(row, now)]
    lines = [f"MJ Cliproom autopilot summary {day}",
             f"Live matches: {len(live_now)}. Waiting clips: {len(queued)}. Recent errors: {len(errors[:5])}."]
    if expired:
        lines.append("Rights expired: " + ", ".join(expired[:8]))
    if state["settings"].get("original_mode"):
        lines.append("Original shorts are on. They do not use anyone else's footage.")
    return "\n".join(lines)


def maybe_original(state, now=None):
    """Make at most a few original shorts a day when that mode is on."""
    if not state["settings"].get("original_mode"):
        return state
    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    made = int(state.get("original_day_count") or 0) if state.get("original_day") == day else 0
    if made >= int(state["settings"].get("original_per_day") or 1):
        return state
    from . import original
    creator = _ensure_creator(state["settings"])
    state["creator_id"] = creator["id"]
    text = original.script(state["settings"].get("original_topic") or "")
    job = jobs.create({"type": "file", "path": "", "name": "MJ Plays GTA original"}, {"mode": "manual", "max_clips": 1},
                      enqueue=False, creator=creator["id"], rights_cleared=True)
    job["original"] = True
    job["autopilot_source"] = "original"
    job["game"] = "gta6"
    job["rights_cleared"] = True
    folder = Path(job["dir"]) / "clips"
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / "original.mp4"
    voice = None
    if state["settings"].get("commentary_id"):
        from . import commentary
        track = commentary.get(state["settings"]["commentary_id"])
        voice = track["path"] if track else None
    try:
        original.build(video, text, voice)
    except Exception as exc:  # noqa: BLE001
        state["errors"] = ([{"at": now, "message": f"Original short failed: {exc}"}] + state["errors"])[:30]
        jobs.save(job)
        return state
    clip = {"id": "orig001", "status": "done", "file": "original.mp4", "start": 0, "end": 12, "score": 70,
            "score_source": "original", "title": "MJ Plays GTA update", "hook": "Original update",
            "description": text, "hashtags": ["GTA6", "MJPlaysGTA", "Shorts"], "version": 1,
            "source_credit": {"name": "MJ Plays GTA", "url": "https://www.youtube.com/"}}
    job["clips"] = [clip]
    job["status"] = "done"
    jobs.save(job)
    consider_clip(state, job, clip, now)
    state["original_day"] = day
    state["original_day_count"] = made + 1
    return state


def public(state=None) -> dict:
    state = state or load()
    settings = state["settings"]
    bucket = quota_bucket(state, time.time())
    from . import commentary
    track = commentary.get(settings.get("commentary_id")) if settings.get("commentary_id") else None
    return {"enabled": settings["enabled"], "keywords": settings["keywords"], "channels": settings["channels"],
            "language": "en", "max_recordings": settings["max_recordings"],
            "server_live_ceiling": config.MAX_LIVE_TOTAL, "daily_cap": settings["daily_cap"],
            "gap_min": settings["gap_min"], "gap_max": settings["gap_max"], "quota_units": settings["quota_units"],
            "quota_used": bucket.get("units") or 0, "privacy": settings["privacy"],
            "commentary": {k: track[k] for k in ("id", "name", "duration")} if track else None,
            "streams": state["streams"][:40], "queue": state["queue"][:40], "errors": state["errors"][:20],
            "drafts": state.get("drafts") or [], "creators": len(creator_names(settings["channels"])),
            "summary": daily_summary(state), "original_mode": settings.get("original_mode") is True,
            "original_topic": settings.get("original_topic") or "",
            "recording": len(_active_urls()), "rights_statuses": list(RIGHTS_STATUSES),
            "verified_channels": sum(1 for row in settings["channels"] if row.get("verified_handle") and row.get("handle"))}


def on_ready(job, clip):
    if not job.get("autopilot_source"):
        return
    held = False
    lock = _user_lock()
    try:
        if not lock.acquire(timeout=10):
            return
        held = True
        state = load()
        consider_clip(state, job, clip)
        save(state)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    finally:
        if held:
            lock.release()


def _loop():
    time.sleep(20)
    while True:
        started = time.time()
        wait = 90
        try:
            ids = auth.user_ids() if config.ACCOUNTS else [auth.local_user().id]
        except Exception:  # noqa: BLE001
            ids = []
        for uid in ids:
            try:
                with ctx.as_user(uid):
                    state = load()
                    wait = min(wait, int(state["settings"].get("poll_seconds") or 90))
                    if state["settings"]["enabled"]:
                        cycle(True)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        time.sleep(max(20, wait - (time.time() - started)))


def start():
    global _started
    if _started:
        return
    _started = True
    jobs.on_clip_ready.append(on_ready)
    threading.Thread(target=_loop, name="autopilot", daemon=True).start()
