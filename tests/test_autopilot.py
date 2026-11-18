"""Autopilot, live layouts, royalty-free music and the safety fixes. No network and no real uploads."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("PEAKCUT_DATA", tempfile.mkdtemp(prefix="pc-auto-"))
os.environ.setdefault("DATABASE_URL", "")
sys.path.insert(0, ".")

from studio import autopilot, brain, editor, jobs, live, music, posting, profiles, render

fails = []


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    if not ok:
        fails.append(name)


# --- creator list and rights -------------------------------------------------
names = autopilot.creator_names()
check("the default list is the 30 creators", len(names), 30)
check("every default source starts unauthorized", all(not row["rights"] and row["rights_status"] == "UNKNOWN" for row in autopilot.DEFAULT_CHANNELS))
check("unverified handles are not turned into links", autopilot.channel_url({"platform": "youtube", "handle": "Nogla", "verified_handle": False}), "")
xqc = next(row for row in autopilot.DEFAULT_CHANNELS if row["name"] == "xQc")
check("a confirmed Twitch handle has a channel link", autopilot.channel_url(xqc), "https://www.twitch.tv/xqc")
check("a source without an allowlist can still be posted", autopilot.can_publish({**xqc, "rights": False, "rights_status": "UNKNOWN"}))
check("an expired rights date does not block posting", autopilot.can_publish({**xqc, "rights": True, "rights_status": "AUTHORIZED", "rights_until": 1}))
check("autopilot can be turned on with no Authorized source",
      autopilot.clean_settings({"enabled": True}, autopilot.default_settings())["enabled"])


# --- game and language -------------------------------------------------------
check("GTA VI is GTA 6", autopilot.classify_game("Grand Theft Auto VI launch"), "gta6")
check("GTA V is GTA 5", autopilot.classify_game("GTA V chaos"), "gta5")
check("GTA 5 is not GTA 6", autopilot.classify_game("gta5"), "gta5")
check("a GTA 5 category wins over a GTA 6 title", autopilot.is_gta6_stream("GTA 6 highlights", "Grand Theft Auto V"), (False, "gta5"))
check("an actual GTA 6 category is kept", autopilot.is_gta6_stream("just chatting", "Grand Theft Auto VI"), (True, "gta6"))
check("Hindi metadata is skipped", autopilot.accept_language("hi", "GTA 6", None)[0], False)
check("English metadata is kept", autopilot.accept_language("en", "GTA 6 night", None)[0])
check("Devanagari speech is not English", autopilot.speech_language([{"w": "यह"}, {"w": "खेल"}, {"w": "है"}, {"w": "अच्छा"}]), "other")
check("English function words pass", autopilot.speech_language([{"w": w} for w in "yeah you and the game just got going".split()]), "en")

# --- watch list only, caps, duplicates, viral score, drafts -------------------
state = autopilot._empty()
state["settings"]["max_recordings"] = 2
watched = []
started = []


def probe(row):
    watched.append(row["id"])
    title = "GTA 5 grind" if row["name"] == "Buddha" else "GTA 6 night"
    category = "Grand Theft Auto V" if row["name"] == "Buddha" else "Grand Theft Auto VI"
    return {"live": True, "title": title, "category": category, "viewers": 10, "language": "en"}


def start(row, info):
    started.append(row["id"])


for row in state["settings"]["channels"]:
    if row["name"] in ("xQc", "Kai Cenat", "Buddha"):
        row["verified_handle"] = True
        row["rights"] = True
        row["rights_status"] = "AUTHORIZED"
state = autopilot.run_once(state, probe=probe, start=start, active=set(), language=lambda row, info: (True, "English"))
check("only confirmed rows are probed", "youtube:nogla" not in watched)
check("GTA 5 is not recorded", all("buddha" not in item for item in started))
check("two recordings is the cap", len(started), 2)
check("no open-web search rows", all(not str(row["id"]).startswith("search:") for row in state["streams"]))

extra = autopilot.clean_channel({"name": "Campaign night", "platform": "twitch", "handle": "campaign", "verified_handle": True,
                                 "rights": True, "rights_status": "AUTHORIZED"})
state["settings"]["channels"].append(extra)
state["settings"]["max_recordings"] = 5
started.clear()
state = autopilot.run_once(state, probe=lambda row: {"live": row["id"] == extra["id"], "title": "GTA VI", "category": "GTA 6", "viewers": 3, "language": "en"},
                           start=start, active=set(), language=lambda row, info: (True, "English"))
check("an allowlisted campaign source can be recorded", extra["id"] in started)

score = autopilot.viral_score({"hook": "He barely made the jump", "title": "Last second escape", "score": 80, "start": 0, "end": 28},
                              game="gta6", has_commentary=True, live=True)
check("viral score keeps commentary, relevance and a 0-100 total",
      score["parts"]["commentary"] == 15 and score["parts"]["relevance"] == 15 and score["total"] == sum(score["parts"].values()) <= 100)
check("viral score does not decide posting", autopilot.can_publish(xqc))
check("near duplicates are caught", autopilot.near_duplicate("he barely made the jump", 12, "https://www.twitch.tv/xqc",
      [{"url": "https://www.twitch.tv/xqc", "start": 14, "tokens": ["barely", "he", "jump", "made", "the"]}]))
check("a different moment is kept", autopilot.near_duplicate("totally different chase", 90, "https://www.twitch.tv/xqc",
      [{"url": "https://www.twitch.tv/xqc", "start": 14, "tokens": ["barely", "he", "jump", "made", "the"]}]), False)
draft = autopilot.permission_draft(xqc)
check("permission text is only a draft", draft["status"], "draft")
check("the draft is not an email send", "mailer" not in Path("studio/autopilot.py").read_text(encoding="utf-8"))
_now = __import__("time").time()
_day = __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime(_now))
check("quota blocks another upload once the budget is spent",
      autopilot.quota_room({"settings": {"quota_units": 8000}, "quota": {"day": _day, "units": 7000}}, _now, 1600), False)

# --- clips: sentences, layouts, brand, commentary, music ---------------------
words = [{"w": "He", "s": 1, "e": 1.2}, {"w": "jumps.", "s": 1.2, "e": 1.6},
         {"w": "Then", "s": 4, "e": 4.3}, {"w": "he", "s": 4.3, "e": 4.5}, {"w": "lands.", "s": 4.5, "e": 5.0}]
start, end = brain._snap({"start": 0.2, "end": 2.0}, brain.make_lines(words), words, 1, 30, 20)
check("the cut waits for the end of the sentence", end >= 1.6)
check("facecam follows the busiest corner", render.choose_facecam({"left": 1, "right": 9, "center": 2}), "right")
graph = render.split_filter("stack", "right")
check("stacked layout keeps gameplay and facecam", "vstack" in graph and "iw-ow" in graph and "delogo" not in graph)
check("full-frame mode does not crop", "pad=" in render._filter("blur", 1080, preserve_marks=True) and "delogo" not in render._filter("blur", 1080, preserve_marks=True))
brand = "\n".join(render._brand_events(20))
check("intro and outro both say MJ PLAYS GTA", brand.count("MJ PLAYS GTA"), 2)
fc, _inputs, audio = render.apply_commentary("color", ["-i", "in.mp4"], ["-map", "0:a:0?"], "0:a:0?", False, __file__, 12, 1)
check("commentary is mixed on top", "[voice]" in fc and audio == ["-map", "[narrated]"])
check("chart music is refused", lambda: music.clean_meta({"license": "billboard"}), _raises)
check("Pixabay metadata is kept", music.parse_pixabay({"hits": [{"tags": "electro, chill", "user": "Ada", "audio": "https://cdn.pixabay.com/audio/a.mp3"}]})[0]["license"], "pixabay")
check("a random host is not a Pixabay file", music.audio_host_ok("https://example.com/song.mp3"), False)
check("the safe catalog does not list chart songs", all("chart" not in row["id"] for row in music.catalog()["sources"]))
check("CC BY needs a real credit", lambda: music.clean_meta({"license": "cc-by", "attribution": "x"}), _raises)
from studio import commentary
check("a commentary file name cannot leave its folder",
      commentary._record({"id": "ab" * 8, "file": "../secret.mp3", "name": "Voice", "duration": 1, "size": 4}) is None)

# --- safety fixes ------------------------------------------------------------
folder = Path(tempfile.mkdtemp())
inside = folder / "source.mp4"
inside.write_bytes(b"x")
outside = folder.parent / "secret.txt"
outside.write_text("nope", encoding="utf-8")
check("a source inside the job folder can be opened", jobs.path_inside(inside, folder))
check("a source outside the job folder is refused", jobs.path_inside(outside, folder), False)
check("a creator id cannot be a path", jobs._known_creator("../etc") is None)
check("a blank creator id is empty", jobs._known_creator("") is None)
check("an interrupted autopilot upload is queued again",
      posting.settle_interrupted({"status": "posting", "autopilot": True, "tries": 0})["status"], "scheduled")
check("a hand-made upload still waits for a person",
      posting.settle_interrupted({"status": "posting", "tries": 0})["status"], "failed")
kept, dropped = live.retain_segments([("a", 0, 5), ("b", 5, 10)], 11, {"a"})
check("a render can pin the buffer file it is reading", dropped, ["b"])
try:
    profiles._Stay().redirect_request(type("R", (), {"full_url": "https://www.youtube.com/live"})(), None, 302, "Found", {}, "http://127.0.0.1/")
    check("redirects off YouTube, Twitch and Kick are refused", False)
except Exception as exc:
    check("redirects off YouTube, Twitch and Kick are refused", type(exc).__name__ in ("HTTPError", "error"))


def fake_ffmpeg(source, args, start=0):
    return b"\x00" * (48 * 28 + 10)


editor._ffmpeg = fake_ffmpeg
check("a short gameplay frame does not crash the scan", editor.gameplay(inside, 0, 8, 2, 5, 10, has_audio=False), [])

calls = []


def fake_enqueue(job, clip, ids, now=False, automatic=False, autopilot=False):
    calls.append(clip["id"])
    return [{"id": "post1", "due_at": 10}]


autopilot.posting.enqueue = fake_enqueue
autopilot._youtube_ids = lambda: ["yt"]
ready = autopilot.clean_channel({**xqc, "rights": True, "rights_status": "AUTHORIZED"})
held = autopilot._empty()
held["settings"]["channels"] = [ready]
source = autopilot.channel_url(ready)
job = {"id": "job1", "autopilot_source": source, "game": "gta6", "title": "GTA 6 night", "clips": []}
signal = {"id": "sig", "status": "done", "start": 1, "end": 20, "score": 55, "score_source": "signals",
          "title": "A loud crash", "hook": "Listen to this", "file": "sig.mp4", "description": "A loud moment."}
agreed = {**signal, "id": "ai", "start": 40, "end": 70, "title": "He makes the ramp", "hook": "Watch this line",
           "description": "A clean ramp.", "score_source": "ai_and_signals", "file": "ai.mp4", "score": 90}
autopilot.consider_clip(held, job, signal)
check("a signal-only clip waits for preview", held["queue"][0]["status"], "review")
check("a signal-only clip is not uploaded", calls, [])
autopilot.consider_clip(held, job, agreed)
check("an agreed clip is queued after it can be previewed", held["queue"][0]["status"], "queued")
check("the queue has a preview link", held["queue"][0]["preview"], "/media/job1/ai.mp4")
blocked = autopilot._empty()
autopilot.consider_clip(blocked, {**job, "game": "gta5", "title": "GTA 5"}, {**agreed, "id": "old"})
check("a GTA 5 moment is not uploaded", blocked["queue"][0]["status"], "skipped")

check("post text keeps the source credit", "https://www.twitch.tv/xqc" in jobs.post_metadata(
    {"title": "GTA 6 night", "uploader": "xQc", "clips": [{"id": "c"}], "source": {"name": "GTA 6 night"}},
    {"id": "c", "start": 1, "end": 20, "title": "Last second escape", "description": "He makes the jump.",
     "hashtags": ["GTA6"], "source_credit": {"name": "xQc", "url": "https://www.twitch.tv/xqc"}})["description"])

print("\nFAILED: " + ", ".join(fails) if fails else "\nAll autopilot checks passed.")
sys.exit(1 if fails else 0)
