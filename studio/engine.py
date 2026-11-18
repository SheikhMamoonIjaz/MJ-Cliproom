"""The autonomous engine.

It decides when a scan is due, picks the next original topic without repeating,
learns from view and retention numbers, and answers a few plain questions.
The web app and the Windows task both call this. Nothing here sends email.
"""
import json
import time

from . import config, ctx

SERIES = {
    "GTA 6 Stories": ("A night that went wrong", "The crew splits up", "One last job"),
    "Hidden Locations": ("The tunnel under the pier", "A rooftop you can walk", "The locked garage"),
    "Easter Eggs": ("The radio that should not play", "A poster that moves", "The license plate"),
    "Map Secrets": ("A shortcut through the hills", "The unmarked dock", "The dry river path"),
    "Tips": ("How to lose a chase", "Where the cameras are", "Saving before a mission"),
}
CARDS = (
    ("trends", "Trend radar", "Topics from public GTA 6 talk."),
    ("compilation", "Daily compilation", "One longer video from today's clips."),
    ("multi", "Multi-platform posting", "YouTube, TikTok, Instagram and Facebook when connected."),
    ("series", "Series maker", "Scripts and a voice track for an original series."),
    ("voice", "Natural voiceover", "A generated voice or a file you recorded."),
    ("captions", "Animated captions", "Emoji, keyword pops and karaoke timing."),
    ("motion", "Auto-zoom and SFX", "Zoom, shake and a sound on the loudest moment."),
    ("map", "Map overlays", "A place name on the clip when one is known."),
    ("analytics", "Analytics", "Views and retention from uploads."),
    ("mobile", "Mobile approval", "Review clips from a phone on this network."),
    ("copyright", "Copyright check", "A warning before upload. It does not block the post."),
    ("channels", "More than one channel", "Post to each connected YouTube channel."),
    ("cloud", "Cloud or VPS", "The same app on Linux or in Docker."),
    ("gpu", "GPU rendering", "NVENC, AMF or QSV, then the normal encoder."),
    ("discover", "Streamer discovery", "Names of GTA 6 streams that are busy."),
    ("backup", "Backup and restore", "A copy of settings you can put back."),
)
PROVIDERS = ("gemini", "glm", "openai", "groq", "custom")


def _file():
    folder = config.user_dir(ctx.uid())
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "engine.json"


def default_state() -> dict:
    return {
        "enabled": False,
        "interval_min": 25,
        "last_run": 0,
        "paused": [],
        "used_topics": [],
        "steer": "",
        "posted_today": [],
        "weights": {"creators": {}, "moments": {}, "titles": {}, "hours": {}},
        "providers": list(PROVIDERS),
        "active_provider": "gemini",
        "cards": {key: False for key, _title, _note in CARDS},
        "log": [],
    }


def load() -> dict:
    state = default_state()
    try:
        saved = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(saved, dict):
        state.update({k: saved[k] for k in state if k in saved})
    state["interval_min"] = _interval(state.get("interval_min"))
    return state


def save(state):
    path = _file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)
    ctx.bump()


def _interval(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = 25
    return min(30, max(20, minutes))


def due(state, now=None) -> bool:
    now = time.time() if now is None else now
    if not state.get("enabled"):
        return False
    return now - float(state.get("last_run") or 0) >= _interval(state.get("interval_min")) * 60


def all_topics():
    found = []
    for series, topics in SERIES.items():
        for topic in topics:
            found.append({"series": series, "topic": topic})
    return found


def next_topic(state) -> dict:
    used = set(state.get("used_topics") or [])
    steer = str(state.get("steer") or "").strip()
    if steer:
        return {"series": "Steered", "topic": steer[:120]}
    for item in all_topics():
        key = item["series"] + ": " + item["topic"]
        if key not in used:
            return item
    state["used_topics"] = []
    first = all_topics()[0]
    return first


def take_topic(state) -> dict:
    item = next_topic(state)
    if item["series"] != "Steered":
        state.setdefault("used_topics", []).append(item["series"] + ": " + item["topic"])
    return item


def reweight(state, sample: dict) -> dict:
    """Raise the weight of what held attention. A quiet clip is left alone."""
    try:
        views = max(0, float(sample.get("views") or 0))
        retention = min(1.0, max(0.0, float(sample.get("retention") or 0)))
    except (TypeError, ValueError):
        return state["weights"]
    if views <= 0 and retention <= 0:
        return state["weights"]
    bump = 1 + min(0.5, views / 10000) * (0.5 + retention)
    weights = state.setdefault("weights", {"creators": {}, "moments": {}, "titles": {}, "hours": {}})
    for bucket, key in (("creators", sample.get("creator")), ("moments", sample.get("moment")),
                        ("titles", sample.get("title_style")), ("hours", sample.get("hour"))):
        if not key:
            continue
        table = weights.setdefault(bucket, {})
        table[str(key)[:80]] = round(float(table.get(str(key), 1) or 1) * bump, 3)
    return weights


def failover(state, failed: str) -> str:
    order = [name for name in (state.get("providers") or PROVIDERS) if name in PROVIDERS]
    if failed not in order:
        return order[0] if order else "gemini"
    nxt = order[(order.index(failed) + 1) % len(order)]
    state["active_provider"] = nxt
    return nxt


def answer(state, text: str) -> str:
    asked = " ".join(str(text or "").lower().split())
    if not asked:
        return "Ask for status, what was posted today, or say pause or resume and a creator name."
    if "status" in asked:
        flag = "on" if state.get("enabled") else "off"
        return f"The engine is {flag}. The next scan is every {state.get('interval_min')} minutes. Provider: {state.get('active_provider')}."
    if "post" in asked and "today" in asked:
        rows = state.get("posted_today") or []
        if not rows:
            return "Nothing has been posted today."
        return "Posted today: " + "; ".join(str(row)[:80] for row in rows[:8])
    if asked.startswith("pause "):
        name = asked[6:].strip()
        if name and name not in state["paused"]:
            state["paused"].append(name)
        return f"Paused {name}." if name else "Say pause and the creator name."
    if asked.startswith("resume "):
        name = asked[7:].strip()
        state["paused"] = [item for item in state["paused"] if item != name]
        return f"Resumed {name}." if name else "Say resume and the creator name."
    if asked.startswith("topic "):
        state["steer"] = text.strip()[6:].strip()[:120]
        return "The next original video will use that topic."
    return "I can tell you the status, what was posted today, pause or resume a creator, or take a topic."


def cards(state) -> list:
    flags = state.get("cards") or {}
    return [{"id": key, "title": title, "note": note, "on": flags.get(key) is True}
            for key, title, note in CARDS]


def public(state=None) -> dict:
    state = load() if state is None else state
    return {"enabled": state.get("enabled") is True, "interval_min": state.get("interval_min"),
            "last_run": state.get("last_run") or 0, "paused": state.get("paused") or [],
            "next_topic": next_topic(state), "provider": state.get("active_provider"),
            "providers": list(state.get("providers") or PROVIDERS), "cards": cards(state),
            "disclaimer": ("You are responsible for having the rights to footage and music you record or upload. "
                           "Re-uploading other creators' content can lead to copyright claims.")}


def toggle_card(state, card_id: str) -> dict:
    if card_id not in {key for key, _t, _n in CARDS}:
        raise ValueError("That tool is not on the home page.")
    flags = state.setdefault("cards", {})
    flags[card_id] = not flags.get(card_id)
    return public(state)


def tick(state, now=None, scan=None) -> dict:
    """One engine pass. `scan` is the autopilot cycle, passed in so tests do not touch the network."""
    now = time.time() if now is None else now
    if not due(state, now):
        return state
    topic = take_topic(state)
    note = "Scan skipped."
    if scan:
        try:
            scan()
            note = "Scanned creators."
        except Exception as exc:  # noqa: BLE001
            note = "Scan failed: " + str(exc)[:120]
    state["last_run"] = now
    state.setdefault("log", []).insert(0, {"at": now, "note": note, "topic": topic["topic"]})
    state["log"] = state["log"][:40]
    return state
