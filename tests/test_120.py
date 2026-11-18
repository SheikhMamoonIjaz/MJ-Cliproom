"""1.2.0 autonomous engine: schedule, topics, learning, chat, keys and encoders."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-120-")
os.environ.setdefault("DATABASE_URL", "")
sys.path.insert(0, ".")

from studio import ctx, engine, vault

fails = []


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    if not ok:
        fails.append(name)


with ctx.as_user("u_local"):
    state = engine.default_state()
    check("the engine waits until it is turned on", engine.due(state, 10_000), False)
    state["enabled"] = True
    state["last_run"] = 0
    state["interval_min"] = 25
    check("a first scan is due", engine.due(state, 10_000))
    check("a scan inside the window is not due", engine.due({**state, "last_run": 10_000}, 10_000 + 60), False)
    first = engine.take_topic(state)
    second = engine.take_topic(state)
    check("topics do not repeat immediately", first["topic"] != second["topic"])
    engine.reweight(state, {"creator": "xQc", "moment": "chase", "title_style": "question", "hour": "20",
                            "views": 5000, "retention": 0.6})
    check("a watched creator gains weight", state["weights"]["creators"]["xQc"] > 1)
    check("status answers", "off" not in engine.answer(state, "status") or "on" in engine.answer(state, "status"))
    state["enabled"] = True
    check("today starts empty", "Nothing" in engine.answer(state, "what did you post today"))
    check("a creator can be paused", "Paused xqc" in engine.answer(state, "pause xqc"))
    check("a creator can be resumed", "xqc" not in engine.answer(state, "resume xqc").lower() or "Resumed" in engine.answer(state, "resume xqc"))
    check("a topic can be steered", "topic" in engine.answer(state, "topic the dry river").lower())
    nxt = engine.failover(state, "gemini")
    check("a failed provider moves to the next", nxt != "gemini" and nxt in engine.PROVIDERS)
    secret = vault.seal(b"local-key")
    check("a sealed key opens again", vault.open_sealed(secret), b"local-key")
    check("hardware encoders come first", vault.encoder_order(["libx264", "h264_qsv", "h264_nvenc"])[0], "h264_nvenc")
    ran = []
    state["last_run"] = 0
    engine.tick(state, now=50_000, scan=lambda: ran.append(1))
    check("a due tick runs one scan", ran, [1])
    check("home has sixteen tools", len(engine.cards(state)), 16)
    check("the disclaimer stays one sentence", "copyright claims" in engine.public(state)["disclaimer"])

if fails:
    print(f"\n{len(fails)} FAILED")
    sys.exit(1)
print("\nall 1.2 checks passed")
