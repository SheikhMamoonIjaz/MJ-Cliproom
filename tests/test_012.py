"""0.12.0: resume, faces, Kick chat, thumbnails, language, rights expiry, original shorts."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PEAKCUT_DATA", tempfile.mkdtemp(prefix="pc-012-"))
os.environ.setdefault("DATABASE_URL", "")
sys.path.insert(0, ".")

from studio import accounts, autopilot, brain, facecam, kickchat, original, posting, thumbs

fails = []


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    if not ok:
        fails.append(name)


words = [{"w": w} for w in ("the", "and", "you", "just", "game", "yeah")]
check("a missing language tag keeps a Latin title", autopilot.accept_language("", "GTA 6 night one", None)[0])
check("Hindi metadata without English speech is skipped", autopilot.accept_language("hi", "GTA 6", None)[0], False)
check("English speech overrides a wrong language tag", autopilot.accept_language("hi", "GTA 6", words)[0])
check("an expiry date does not block posting",
      autopilot.can_publish({"rights": True, "rights_status": "AUTHORIZED", "rights_until": time.time() - 10}))
check("a source with no rights status can still be posted",
      autopilot.can_publish({"rights": False, "rights_status": "UNKNOWN"}))

loc = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc"
check("a matching YouTube session is kept", accounts.session_location({"location": loc, "size": 20}, 20), loc)
check("a different file does not reuse the session", accounts.session_location({"location": loc, "size": 20}, 21), "")
check("a foreign host is not a YouTube session",
      accounts.session_location({"location": "https://evil.example/upload", "size": 20}, 20), "")
held = posting.settle_interrupted({"status": "posting", "upload_session": {"location": loc, "size": 9, "offset": 4}})
check("a saved session is resumed instead of dropped", held["status"], "scheduled")
check("the saved session stays on the post", "location" in held.get("upload_session", {}))

check("Kick chat frames are viewer messages",
      kickchat.is_chat_message({"event": "App\\Events\\ChatMessageEvent", "data": {"content": "hello"}}))
check("a Kick subscribe frame is not chat", kickchat.is_chat_message({"event": "pusher:subscription_succeeded"}), False)
check("a Kick chatroom id is read", kickchat.chatroom_id({"chatroom": {"id": 42}}), "42")

check("the left third is left", facecam.corner_of(10, 160), "left")
check("no face falls back to the busiest corner", facecam.pick_facecam(None, {"left": 1, "right": 9}), "right")

levels = [1, 2, 9, 3]
check("the cover second is the busiest sample", thumbs.peak_time(levels, 1, 4), 2.5)
folder = Path(tempfile.mkdtemp(prefix="pc-thumb-"))
wide = thumbs.draw_thumbnail(folder / "wide.jpg", "He said the line", wide=True, streamer="xQc")
tall = thumbs.draw_thumbnail(folder / "tall.jpg", "He said the line", wide=False)
from PIL import Image
check("the long-form thumbnail is 1280x720", Image.open(wide).size, (1280, 720))
check("the Short cover is vertical", Image.open(tall).size, (1080, 1920))

pack = brain.viral_pack("he said the line and kept driving", "GTA 5 speedrun", "xQc", "https://www.twitch.tv/xqc", "the line")
check("five titles", len(pack["titles"]), 5)
check("three hooks", len(pack["hooks"]), 3)
check("GTA 5 is not renamed", pack["game"], "GTA 5")
check("the description credits the source", "https://www.twitch.tv/xqc" in pack["description"])
check("hashtags stay on the real game", "GTA6" not in pack["hashtags"])
six = brain.viral_pack("the night run", "GTA 6 launch", "MJ Plays GTA", "https://example.com/a", "")
check("GTA 6 stays GTA 6", six["game"], "GTA 6")

text = original.script("someone said gta 5 by mistake")
check("an original script does not keep a GTA 5 label", "gta 5" not in text.lower() and "gta v" not in text.lower())
check("an original script says the video is original", "no one else's" in text.lower())
video = folder / "original.mp4"
original.build(video, text)
check("an original short is a video file", video.is_file() and video.stat().st_size > 1000)

opened = autopilot.clean_settings({"original_mode": True, "enabled": True}, autopilot.default_settings())
check("original shorts can turn autopilot on without someone else's footage", opened["enabled"])
summary = autopilot.daily_summary({"queue": [], "errors": [], "streams": [], "settings": {"channels": [], "original_mode": True}})
check("the daily summary does not ask anyone for permission", "permission" not in summary.lower() and "email" not in summary.lower())

if fails:
    print(f"\n{len(fails)} FAILED")
    sys.exit(1)
print("\nall 0.12 checks passed")
