"""Beta paths with a disposable data folder and stand-ins for external providers."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory(prefix="mj-beta-") as data:
    os.environ.update(PEAKCUT_DATA=data, PEAKCUT_ACCOUNTS="0", PEAKCUT_UPDATE_CHECK="0", DATABASE_URL="")
    sys.path.insert(0, ".")
    from studio import accounts, ai, brain, config, ctx, db, jobs, posting, server

    db.init()
    base = config.PUBLIC_URL
    app = TestClient(server.app, base_url=base)
    origin = {"Origin": base}
    # Migrate a pre-beta profile and allow fallback only to opted-in independent services.
    ai._file().write_text(json.dumps({"provider": "openai", "models": ["old-model"], "key": "local-test"}))
    ai.save("openai", "another", new_key="another-test", profile_id="new", fallback=True)
    ai.save("gemini", "opted-in", new_key="backup-test", profile_id="new", fallback=True)
    assert [p["provider"] for p in ai.attempts()] == ["openai", "gemini"]
    assert ai.public()["models"] == ["old-model"] and "key" not in json.dumps(ai.public()["profiles"]).replace("has_key", "").replace("key_hint", "")
    attempted = []

    def fake_call(model, prompt, schema):
        attempted.append(model)
        if model == "old-model":
            ai._fail(httpx.Response(429, headers={"Retry-After": "120"}), model)
        return [], 0, 0

    owner = app.get("/api/status").json()["user"]["id"]
    with ctx.as_user(owner), patch.object(ai, "call", fake_call):
        assert brain.ask_ai("test")[1] == "opted-in"
        assert brain.ask_ai("test")[1] == "opted-in"
        assert attempted == ["old-model", "opted-in", "opted-in"]
        accounts._put({"id": "yt", "platform": "youtube", "name": "Test YouTube", "added": 1})
        accounts._put({"id": "ig", "platform": "instagram", "name": "Test Instagram", "added": 1})
        accounts._put({"id": "tt", "platform": "tiktok", "name": "Test TikTok", "added": 1})
    print("PASS AI profiles preserve credentials, honor cooldown and only fail over to an independent service")

    request = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "prompt": "Find the final boss reaction",
               "request_id": "4b3903022670499ca64039260218ee31", "accounts": ["yt", "ig"]}
    def submit(**extra):
        return app.post("/api/automation", headers=origin, json={**request, **extra})

    with patch.object(server.media, "check_youtube"), patch.object(server._tools, "missing", return_value=False):
        assert submit().status_code == 400
        assert submit(rights_cleared=True).status_code == 400
        assert submit(rights_cleared=True, publish_authorized=True, accounts=["tt"]).status_code == 400
        assert submit(rights_cleared=True, publish_authorized=True, options={"mode": "news"}).status_code == 400
        accepted = submit(rights_cleared=True, publish_authorized=True).json()
        duplicate = submit(rights_cleared=True, publish_authorized=True).json()
    jid = accepted["id"]
    assert duplicate["id"] == jid and accepted["options"]["mode"] == "gameplay"
    assert accepted["automation"]["visibility"] == "private"
    print("PASS a prompt is saved once, requires editing and destination consent, and defaults to private YouTube")

    with ctx.as_user(owner):
        job = jobs.get(jid)
        job["status"] = "done"
        job["clips"] = [{"id": "rated", "status": "done", "score": 95, "file": "ok.mp4", "score_source": "ai_and_signals"},
                        {"id": "signal", "status": "done", "score": 98, "file": "review.mp4", "score_source": "signals"}]
        posting._reconcile_prompt_posts()
        posting._reconcile_prompt_posts()
        rows = posting.overview()["posts"]
        assert {(p["clip"], p["account"]) for p in rows} == {("rated", "yt"), ("rated", "ig")}
        yt = next(p for p in posting._mine() if p["platform"] == "youtube")
        try:
            accounts._check(httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}},
                                           headers={"Retry-After": "240"}), "YouTube upload")
        except accounts.PlatformLimit as limit:
            assert not limit.account_only and limit.delay == 240
        else:
            raise AssertionError("A project quota must pause YouTube")
        with patch.object(accounts, "youtube_upload", side_effect=accounts.PlatformLimit(300)):
            posting._post(yt)
        assert yt["status"] == "scheduled" and yt["tries"] == 0
        assert posting.blocked_until("youtube", "another") > time.time()
        assert not posting.blocked_until("instagram", "ig")
        posting.cancel(yt["id"])
        posting.retry(yt["id"])
        assert yt["due_at"] >= posting.blocked_until("youtube")
        assert json.loads(posting._LIMIT_FILE.read_text())["youtube"] > time.time()
        with patch.dict(posting._limits, {}, clear=True):
            posting._record_limit("youtube", accounts.PlatformLimit(120, account_only=True), "yt")
            assert not posting.blocked_until("youtube", "another")
        posting.revoke_prompt_posts(job)
        assert all(p["status"] == "cancelled" for p in posting._mine())
    assert app.post("/api/posts", headers=origin, json={"job": jid, "clip": "rated", "accounts": ["yt"]}).status_code == 400
    print("PASS only scored clips queue, quota waits persist, retry keeps its destination, and revocation stops queued posts")
    db.engine.dispose()
