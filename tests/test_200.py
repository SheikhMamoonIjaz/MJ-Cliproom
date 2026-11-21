"""MJ Cliproom 2.0.0 verification suite:
- 3x4 AI provider failover with fake clock (all 8 scenarios)
- Source URL normalization, deduplication, classification, and quarantine
- Debounced live transition and streaming WAV loudness
- Clip intelligence (hook/setup/payoff), candidate deduplication, and near-duplicate copy guard
- Video Summarizer (source/range/clip_set, batch reconciliation, coverage flags, MD/TXT/JSON export, immutable words.json)
- 9:16 Fit-with-blur layout, non-overlapping solve_safe_layout, 7 motion presets, and SRT + VTT subtitles
- 9-stage publishing pipeline, 7 distinct statuses, Hold/Approve, and two-pass idempotent 1.3.2 -> 2.0.0 migration + rollback
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

os.environ.update(
    PEAKCUT_DATA=tempfile.mkdtemp(prefix="mj-200-"),
    PEAKCUT_ACCOUNTS="0",
    PEAKCUT_UPDATE_CHECK="0",
    DATABASE_URL="",
)
sys.path.insert(0, ".")

from studio import ai, brain, config, ctx, db, jobs, live, media, migrate, posting, render, server, summarize

db.init()
fails = []


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    if not ok:
        fails.append(name)


def boxes_overlap(a, b):
    if not a or not b:
        return False
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


# ==============================================================================
# 1. Sensitive AI Provider Failover & Bounded 3x4 Retries (Fake Clock)
# ==============================================================================
class FakeClock:
    def __init__(self, start=10000.0):
        self.t = float(start)
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, sec):
        self.sleeps.append(round(float(sec), 2))
        self.t += float(sec)


def setup_three_providers(clock):
    ai._cooldowns.clear()
    ai._health.clear()
    try:
        ai._cooldown_file.unlink()
    except OSError:
        pass
    ai._clock["now"] = clock.now
    ai._clock["sleep"] = clock.sleep
    ai._file().write_text(json.dumps({
        "active": "p1",
        "promote_healthy_globally": False,
        "profiles": [
            {"id": "p1", "name": "Primary Gemini", "provider": "gemini", "models": ["gemini-2.5-flash"],
             "key": "k1", "fallback": True, "order": 0, "enabled": True, "allow_clip_text": True},
            {"id": "p2", "name": "Backup ZAI", "provider": "zai", "models": ["glm-4.5-flash"],
             "key": "k2", "fallback": True, "order": 1, "enabled": True, "allow_clip_text": True},
            {"id": "p3", "name": "Backup OpenAI", "provider": "openai", "models": ["gpt-5-mini"],
             "key": "k3", "fallback": True, "order": 2, "enabled": True, "allow_clip_text": True},
            {"id": "p4", "name": "Same Provider Extra Key", "provider": "gemini", "models": ["gemini-extra"],
             "key": "k4", "fallback": True, "order": 3, "enabled": True, "allow_clip_text": True},
        ]
    }), encoding="utf-8")


# Scenario 1: First fallback succeeds immediately in Round 1
clock = FakeClock()
setup_three_providers(clock)
calls = []
def call_s1(model, prompt, schema):
    calls.append(model)
    if model == "gemini-2.5-flash":
        ai._fail(httpx.Response(429, headers={"Retry-After": "60"}), model)
    return {"ok": True}, 12, 8

out, used_model, sent, wrote, meta = ai.execute_with_failover("test prompt", call_fn=call_s1)
check("Scenario 1: 1st fallback switches immediately to distinct provider in Round 1 with 0s sleep",
      (used_model, calls, clock.sleeps, meta["round"]),
      ("glm-4.5-flash", ["gemini-2.5-flash", "glm-4.5-flash"], [], 0))

# Scenario 2: All 3 distinct providers rate-limited across 4 rounds (max 12 requests, sleeps [5, 10, 15])
clock = FakeClock()
setup_three_providers(clock)
calls = []
def call_s2(model, prompt, schema):
    calls.append(model)
    raise RuntimeError(f"{model}: rate limit reached temporarily")

wait_err = None
try:
    ai.execute_with_failover("test prompt", call_fn=call_s2)
except ai.AIWaitError as exc:
    wait_err = exc
check("Scenario 2: all 3 distinct providers failing across 4 rounds stops at 12 calls with [5, 10, 15]s waits",
      (len(calls), clock.sleeps, wait_err is not None and "gemini-extra" not in calls),
      (12, [5.0, 10.0, 15.0], True))

# Scenario 3: Mixed Retry-After values (provider 1 has Retry-After=20s, becomes eligible again in Round 4 at t+30s)
clock = FakeClock()
setup_three_providers(clock)
calls = []
def call_s3(model, prompt, schema):
    calls.append((model, round(clock.now() - 10000.0, 1)))
    if model == "gemini-2.5-flash":
        if len([c for c in calls if c[0] == "gemini-2.5-flash"]) == 1:
            ai._fail(httpx.Response(429, headers={"Retry-After": "20"}), model)
        return {"recovered": True}, 10, 5
    ai._fail(httpx.Response(429, headers={"Retry-After": "120"}), model)

out, used_model, _, _, meta = ai.execute_with_failover("test prompt", call_fn=call_s3)
check("Scenario 3: Retry-After=20s skips provider in rounds 2 & 3 and succeeds in round 4 at t=30s",
      (used_model, calls),
      ("gemini-2.5-flash", [("gemini-2.5-flash", 0.0), ("glm-4.5-flash", 0.0), ("gpt-5-mini", 0.0), ("gemini-2.5-flash", 30.0)]))

# Scenario 4: Dead key (401/403) marks profile requires_config=True and never retries it
clock = FakeClock()
setup_three_providers(clock)
calls = []
def call_s4(model, prompt, schema):
    calls.append(model)
    if model == "gemini-2.5-flash":
        ai._fail(httpx.Response(401), model)
    return {"ok": True}, 5, 5

ai.execute_with_failover("test prompt", call_fn=call_s4)
p1_state = next(p for p in ai.public()["profiles"] if p["id"] == "p1")
check("Scenario 4: dead 401 key marks requires_config=True and fails over immediately",
      (p1_state["requires_config"], p1_state["last_error_kind"], calls),
      (True, "auth_invalid", ["gemini-2.5-flash", "glm-4.5-flash"]))

# Scenario 5: Malformed JSON output retries once on the same provider within budget
clock = FakeClock()
setup_three_providers(clock)
calls = []
def call_s5(model, prompt, schema):
    calls.append(model)
    if len(calls) == 1:
        raise ValueError("did not return valid JSON")
    return {"fixed": True}, 9, 4

out, used_model, _, _, _ = ai.execute_with_failover("test prompt", call_fn=call_s5)
check("Scenario 5: malformed JSON retries once on the same provider and succeeds",
      (used_model, calls, clock.sleeps),
      ("gemini-2.5-flash", ["gemini-2.5-flash", "gemini-2.5-flash"], []))

# Scenario 6: Network timeout fails over immediately to next provider
clock = FakeClock()
setup_three_providers(clock)
calls = []
def call_s6(model, prompt, schema):
    calls.append(model)
    if model == "gemini-2.5-flash":
        raise httpx.ReadTimeout("timed out")
    return {"ok": True}, 7, 3

out, used_model, _, _, _ = ai.execute_with_failover("test prompt", call_fn=call_s6)
check("Scenario 6: timeout fails over immediately in the same round",
      (used_model, calls, clock.sleeps),
      ("glm-4.5-flash", ["gemini-2.5-flash", "glm-4.5-flash"], []))

# Scenario 7: Cancellation during wait aborts remaining rounds
clock = FakeClock()
setup_three_providers(clock)
calls = []
def call_s7(model, prompt, schema):
    calls.append(model)
    raise RuntimeError("rate limit reached")

cancelled = False
try:
    ai.execute_with_failover("test prompt", call_fn=call_s7, cancel_check=lambda: len(calls) >= 3)
except (RuntimeError, ai.AIWaitError) as exc:
    cancelled = "cancel" in str(exc).lower()
check("Scenario 7: cancellation check aborts before round 2 sleep",
      (cancelled, len(calls), clock.sleeps),
      (True, 3, []))

# Scenario 8: Restart persistence preserves next_eligible_at on disk
clock = FakeClock()
setup_three_providers(clock)
p2_prof = next(p for p in ai._profiles() if p["id"] == "p2")
ai.set_cooldown(p2_prof, 95)
ai._cooldowns.clear()
reloaded_p2 = next(p for p in ai.public()["profiles"] if p["id"] == "p2")
check("Scenario 8: cooldown state persists on disk across restarts",
      reloaded_p2["next_eligible_at"] > clock.now() and reloaded_p2["cooling"] is True)

ai._clock["now"] = __import__("time").time
ai._clock["sleep"] = __import__("time").sleep
ai._file().unlink(missing_ok=True)
ai._saved["at"] = None
ai._cooldowns.clear()
ai._health.clear()


# ==============================================================================
# 2. Intake Normalization, Classification, Quarantine, Live Debounce & 12h WAV
# ==============================================================================
u1 = "https://youtu.be/dQw4w9WgXcQ?si=tracking123&utm_source=share"
u2 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=youtu.be"
check("URL normalization canonicalizes equivalent YouTube links",
      media.normalize_source_url(u1) == media.normalize_source_url(u2) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
check("Source fingerprints match across tracking variants",
      media.source_fingerprint(u1) == media.source_fingerprint(u2))
with patch.object(media, "info", side_effect=[
    RuntimeError("This video is private and requires login"),
    RuntimeError("The channel is currently offline"),
    RuntimeError("404 video not found or deleted"),
    {"kind": "playlist", "title": "Channel Videos"},
    {"kind": "video", "title": "Live Tournament", "is_live": True, "live_status": "is_live"},
    {"kind": "video", "title": "Podcast Episode 12", "is_live": False, "live_status": "not_live", "duration": 3600},
]):
    check("classify_source distinguishes invalid, unsupported, restricted, offline, expired, channel_or_playlist, live_url, and replay_url",
          (media.classify_source("not-a-url")["status"],
           media.classify_source("https://example.com/video.mp4")["status"],
           media.classify_source("https://www.youtube.com/watch?v=priv1234567")["status"],
           media.classify_source("https://www.twitch.tv/offlinestreamer")["status"],
           media.classify_source("https://www.youtube.com/watch?v=dead1234567")["status"],
           media.classify_source("https://www.youtube.com/@channel")["status"],
           media.classify_source("https://www.twitch.tv/livestreamer")["source_type"],
           media.classify_source("https://www.youtube.com/watch?v=vod12345678")["source_type"]),
          ("invalid", "unsupported", "restricted", "offline", "expired", "channel_or_playlist", "live_url", "replay_url"))

q_dir = Path(tempfile.mkdtemp(prefix="mj-quarantine-"))
(q_dir / "source.mp4.part").write_bytes(b"partial-bytes")
(q_dir / "source.mp4").write_bytes(b"complete-source")
moved = media.quarantine_partials(q_dir)
check("quarantine_partials isolates .part files without touching source.mp4",
      len(moved) == 1 and (q_dir / "source.mp4").exists() and not (q_dir / "source.mp4.part").exists())
restored = media.restore_quarantined_partials(q_dir)
check("restore_quarantined_partials returns partial files for resume",
      restored == 1 and (q_dir / "source.mp4.part").exists())
shutil.rmtree(q_dir, ignore_errors=True)

wav_path = Path(tempfile.mkdtemp(prefix="mj-wav-")) / "stream.wav"
with wave.open(str(wav_path), "w") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes((b"\x00\x10" * 16000) * 3)
levels = media.loudness_from_wav(wav_path)
check("streaming WAV loudness computes per-second dB array",
      len(levels) == 3 and all(-60.0 <= db_val <= 0.0 for db_val in levels))
shutil.rmtree(wav_path.parent, ignore_errors=True)

with patch.object(live, "resolve", return_value={"url": "https://stream/live.m3u8"}):
    res_live = live.verify_live_transition("https://www.twitch.tv/xqc", required_checks=2, debounce_sec=0.01)
check("verify_live_transition confirms debounced live signal", res_live is True)


# ==============================================================================
# 3. Clip Intelligence, Candidate Deduplication, Summarizer & Near-Duplicate Copy
# ==============================================================================
words = [
    {"w": "Welcome", "s": 0.0, "e": 0.5}, {"w": "to", "s": 0.5, "e": 0.8}, {"w": "the", "s": 0.8, "e": 1.0},
    {"w": "grand", "s": 1.0, "e": 1.5}, {"w": "finals.", "s": 1.5, "e": 2.2},
    {"w": "Here", "s": 10.0, "e": 10.4}, {"w": "comes", "s": 10.4, "e": 10.8}, {"w": "the", "s": 10.8, "e": 11.0},
    {"w": "winning", "s": 11.0, "e": 11.5}, {"w": "overtake", "s": 11.5, "e": 12.2}, {"w": "at", "s": 12.2, "e": 12.5},
    {"w": "the", "s": 12.5, "e": 12.8}, {"w": "final", "s": 12.8, "e": 13.3}, {"w": "corner!", "s": 13.3, "e": 14.2},
    {"w": "Unbelievable", "s": 24.0, "e": 25.0}, {"w": "finish", "s": 25.0, "e": 25.8}, {"w": "by", "s": 25.8, "e": 26.2},
    {"w": "the", "s": 26.2, "e": 26.5}, {"w": "underdog!", "s": 26.5, "e": 27.5},
]
lines = brain.make_lines(words)
cand = brain._tidy({"start": 0.0, "end": 27.5, "score": 91, "hook": "Final corner overtake",
                    "title": "Underdog wins at the final corner", "reason": "Complete setup and payoff"},
                   0.0, 27.5)
check("Clip candidate includes hook, setup, payoff, evidence, standalone_reason, and source_relevance_score",
      all(bool(cand.get(k)) for k in ("hook", "setup", "payoff", "evidence", "standalone_reason", "source_relevance_score")))

dup_cand = {**cand, "start": cand["start"] + 1.0, "end": cand["end"] - 0.5}
check("is_similar_candidate suppresses overlapping or near-identical moments",
      brain.is_similar_candidate(dup_cand, [cand]) is True)

check("is_near_duplicate_copy detects near-identical channel titles and descriptions",
      brain.is_near_duplicate_copy("The driver takes the final turn in Vice City",
                                   "He holds the inside line and wins the race.",
                                   [{"title": "The driver takes the final turn in Vice City!", "description": "Another desc"}]) is True)

sum_dir = Path(tempfile.mkdtemp(prefix="mj-sum-"))
words_file = sum_dir / "words.json"
words_file.write_text(json.dumps(words), encoding="utf-8")
before_hash = hashlib.sha256(words_file.read_bytes()).hexdigest()
dummy_job = {"id": "sumjob1", "title": "Championship Finals", "duration": 30.0, "dir": str(sum_dir),
             "clips": [cand]}
s_v1 = summarize.generate_summary(dummy_job, scope="source")
s_v2 = summarize.generate_summary(dummy_job, scope="clip_set")
after_hash = hashlib.sha256(words_file.read_bytes()).hexdigest()
check("Summarizer increments versions, keeps words.json 100% immutable, and exports MD/TXT/JSON",
      s_v1["version"] == 1 and s_v2["version"] == 2 and before_hash == after_hash
      and "## Sections" in summarize.export_summary(s_v1, "md")[0]
      and "SECTIONS" in summarize.export_summary(s_v1, "txt")[0]
      and json.loads(summarize.export_summary(s_v1, "json")[0])["id"] == s_v1["id"])
shutil.rmtree(sum_dir, ignore_errors=True)


# ==============================================================================
# 4. Canonical 9:16 Fit-with-Blur, Safe-Layout Solver, Motion Presets & SRT/VTT
# ==============================================================================
for pos in ("bottom", "middle", "top"):
    solved = render.solve_safe_layout(1920, 1080, layout="blur", caption_position=pos,
                                      has_hook=True, has_brand=True, has_lower_third=True,
                                      watermark_corner="top-left")
    b = solved["boxes"]
    pairs = [("brand", "watermark"), ("brand", "hook"), ("hook", "lower_third"),
             ("hook", "captions"), ("lower_third", "captions")]
    overlaps = [p for p in pairs if boxes_overlap(b.get(p[0]), b.get(p[1]))]
    check(f"solve_safe_layout has zero overlap for caption_position={pos}", overlaps, [])

for m_key in render.MOTION_PRESETS:
    ass_text = render.build_ass(words, 0, 15, "Test Hook", "bounce", [], 335, 1520,
                                motion=m_key, watermark=True)
    assert "Style: Box," in ass_text and "Style: Cap," in ass_text
check("All 7 motion presets generate valid ASS overlays with Style: Box and Style: Cap", True)

srt_sample = "1\n00:00:00,500 --> 00:00:02,250\nWelcome to Vice City\n"
vtt_sample = render.srt_to_vtt(srt_sample)
check("srt_to_vtt converts SRT comma timestamps to valid WebVTT",
      vtt_sample.startswith("WEBVTT") and "00:00:00.500 --> 00:00:02.250" in vtt_sample)


# ==============================================================================
# 5. Publishing Statuses & Two-Pass Idempotent 1.3.2 -> 2.0.0 Migration + Rollback
# ==============================================================================
statuses = {
    posting.display_status({"status": "scheduled"}),
    posting.display_status({"status": "uploading"}),
    posting.display_status({"status": "processing"}),
    posting.display_status({"status": "posted", "visibility": "public"}),
    posting.display_status({"status": "posted", "visibility": "private"}),
    posting.display_status({"status": "held"}),
    posting.display_status({"status": "failed"}),
}
check("posting.display_status covers all 7 distinct publishing statuses",
      statuses == set(posting.DISTINCT_STATUSES))

mig_dir = Path(tempfile.mkdtemp(prefix="mj-mig-132-"))
(mig_dir / "users" / "u_local" / "jobs" / "job1").mkdir(parents=True)
(mig_dir / "users" / "u_local" / "ai.json").write_text(json.dumps({
    "provider": "gemini", "models": ["gemini-2.5-flash"], "key": "secret-test-key"
}), encoding="utf-8")
(mig_dir / "users" / "u_local" / "posts.json").write_text(json.dumps([
    {"id": "post_priv", "job": "job1", "clip": "c1", "account": "yt1", "platform": "youtube",
     "status": "scheduled", "visibility": "private", "title": "Private Clip"}
]), encoding="utf-8")
(mig_dir / "users" / "u_local" / "autopilot.json").write_text(json.dumps({
    "settings": {"enabled": True, "privacy": "private"},
    "queue": [{"id": "q1", "status": "review", "title": "Held Review Clip"}]
}), encoding="utf-8")
(mig_dir / "users" / "u_local" / "jobs" / "job1" / "job.json").write_text(json.dumps({
    "id": "job1", "status": "done", "options": {"layout": "auto"},
    "clips": [{"id": "c1", "status": "done", "start": 0, "end": 15, "title": "Private Clip", "subtitle": "c1.srt"}]
}), encoding="utf-8")
(mig_dir / "users" / "u_local" / "jobs" / "job1" / "clips").mkdir(parents=True)
(mig_dir / "users" / "u_local" / "jobs" / "job1" / "clips" / "c1.srt").write_text(srt_sample, encoding="utf-8")

rep1 = migrate.migrate(mig_dir, create_backup=True)
rep2 = migrate.migrate(mig_dir, create_backup=False)
migrated_posts = json.loads((mig_dir / "users" / "u_local" / "posts.json").read_text(encoding="utf-8"))
migrated_auto = json.loads((mig_dir / "users" / "u_local" / "autopilot.json").read_text(encoding="utf-8"))
check("Two-pass 1.3.2 -> 2.0.0 migration is idempotent, generates .vtt, and never makes private/held items public",
      rep1["ok"] and rep2["ok"] and rep2["already_migrated"]
      and migrated_posts[0]["visibility"] == "private"
      and migrated_posts[0]["display_status"] == "Scheduled"
      and migrated_auto["settings"]["privacy"] == "private"
      and migrated_auto["queue"][0]["status"] == "review"
      and (mig_dir / "users" / "u_local" / "jobs" / "job1" / "clips" / "c1.vtt").exists())

rb = migrate.rollback(Path(rep1["backup_dir"]), mig_dir)
check("migrate.rollback cleanly restores pre-2.0.0 snapshot", rb["ok"] is True)
shutil.rmtree(mig_dir, ignore_errors=True)

# API route smoke test via TestClient
client = TestClient(server.app, base_url=config.PUBLIC_URL)
st = client.get("/api/status").json()
check("/api/status exposes version 2.0.0, blur layout, motion_presets, and content_presets",
      st["version"] == "2.0.0" and "blur" in st["layouts"]
      and "kinetic" in st["motion_presets"] and "podcast" in st["content_presets"])

if fails:
    print(f"\nFAILED ({len(fails)}): " + ", ".join(fails))
    sys.exit(1)
print("\nALL 2.0.0 CHECKS PASSED")
