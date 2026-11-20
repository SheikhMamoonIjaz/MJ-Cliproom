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
        assert submit(accounts=["tt"]).status_code == 400
        assert submit(options={"mode": "news"}).status_code == 400
        accepted = submit().json()
        duplicate = submit().json()
    jid = accepted["id"]
    assert duplicate["id"] == jid and accepted["options"]["mode"] == "gameplay"
    assert accepted["automation"]["visibility"] == "private"
    print("PASS a prompt is saved once without a permission checkbox, and defaults to private YouTube")

    with ctx.as_user(owner):
        job = jobs.get(jid)
        job["status"] = "done"
        job["clips"] = [{"id": "rated", "status": "done", "score": 95, "file": "ok.mp4", "score_source": "ai_and_signals"},
                        {"id": "signal", "status": "done", "score": 98, "file": "review.mp4", "score_source": "signals"}]
        folder = Path(job["dir"]) / "clips"
        folder.mkdir(exist_ok=True)
        (folder / "ok.mp4").write_bytes(b"mock upload")
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
    assert app.post("/api/posts", headers=origin, json={"job": jid, "clip": "rated", "accounts": ["yt"]}).status_code == 200
    print("PASS only scored clips queue, quota waits persist, retry keeps its destination, and revocation stops queued posts")

    with ctx.as_user(owner):
        job = jobs.get(jid)
        job["clips"].extend({"id": cid, "file": "ok.mp4", "status": "done", "title": f"GTA racing: {cid}"}
                            for cid in ("first", "second", "now"))
        job["clips"].append({"id": "metadata-worker", "file": "ok.mp4", "status": "done",
                             "title": "An old title", "description": "An old description", "hashtags": ["OldTag"]})
        posting._limits.clear()
    worker_description = ("This unique metadata-worker regression description stays tied to its selected gaming clip. " * 25)
    server._UNIQUE_META_TASKS[owner] = {"id": "test-worker", "status": "running", "total": 1,
                                       "completed": 0, "errors": [], "updated_at": time.time()}
    with patch.object(server, "_research_clip_post_ideas", return_value={"ideas": [{
            "title": "Fresh metadata worker regression title", "description": worker_description,
            "hashtags": ["RegressionTag", "Gameplay", "Shorts"]}]}):
        server._run_unique_metadata(owner, "test-worker", [{"job": jid, "clip": "metadata-worker"}], "US")
    with ctx.as_user(owner):
        saved_worker = next(c for c in jobs.get(jid)["clips"] if c["id"] == "metadata-worker")
    assert saved_worker["title"] == "Fresh metadata worker regression title"
    assert len(saved_worker["description"]) >= 1500 and saved_worker["hashtags"] == ["RegressionTag", "Gameplay", "Shorts"]
    assert isinstance(saved_worker["hashtags"], list) and saved_worker["hashtags"]
    assert server._UNIQUE_META_TASKS[owner]["status"] == "complete"
    print("PASS the unique-copy worker normalizes generated hashtag lists before saving clip metadata")

    published_description = ("This published racing highlight has a distinct scene and a clear payoff. " * 25)
    published_job = {"id": "published-meta-job", "status": "done", "title": "Test racing session",
                     "source": {"type": "url", "title": "Test racing session"}, "uploader": "",
                     "clips": [{"id": "published-clip", "status": "done", "title": "Old title",
                                "description": "Old description", "hashtags": ["OldTag"],
                                "start": 0, "end": 20}]}
    published_post = {"id": "published-post", "job": "published-meta-job", "clip": "published-clip",
                      "platform": "youtube", "status": "posted", "account": "yt",
                      "remote_id": "abcdefghijk", "title": "Old title", "description": "Old description"}
    metadata_events = []

    def save_published_metadata(job, cid, changes):
        metadata_events.append("local")
        clip = job["clips"][0]
        clip.update(title=changes["title"], description=changes["description"],
                    hashtags=[tag.lstrip("#") for tag in changes["hashtags"].split()])
        return clip

    metadata_body = {"title": "Fresh published racing title", "description": published_description,
                     "hashtags": "#GTA6 #RacingClips #Shorts"}
    expected_remote = jobs.post_metadata(
        published_job, published_job["clips"][0],
        {**metadata_body, "hashtags": ["#GTA6", "#RacingClips", "#Shorts"]})
    with ctx.as_user(owner), \
            patch.object(server, "_job_or_404", return_value=published_job), \
            patch.object(server, "_metadata_history", return_value=[]), \
            patch.object(posting, "_mine", return_value=[published_post]), \
            patch.object(posting, "_save"), patch.object(posting, "_sync_rows"), \
            patch.object(accounts, "get", return_value={"id": "yt", "platform": "youtube"}), \
            patch.object(accounts, "youtube_update_metadata", side_effect=lambda *args: metadata_events.append("youtube")) as update_youtube, \
            patch.object(jobs, "update_metadata", side_effect=save_published_metadata), \
            patch.object(jobs, "public", return_value={}):
        result = server.save_clip_metadata("published-meta-job", "published-clip", metadata_body)
        assert result["clip"]["title"] == metadata_body["title"]
        assert metadata_events == ["youtube", "local"], metadata_events
        assert update_youtube.call_args.args[1:] == (
            "abcdefghijk", expected_remote["title"], expected_remote["description"],
            expected_remote["hashtags"]), update_youtube.call_args
        metadata_events.clear()
        with patch.object(accounts, "youtube_update_metadata", side_effect=RuntimeError("Reconnect required")), \
                patch.object(jobs, "update_metadata", side_effect=AssertionError("local save must wait for YouTube")):
            try:
                server.save_clip_metadata("published-meta-job", "published-clip", metadata_body)
            except server.HTTPException as error:
                assert error.status_code == 409 and "Reconnect required" in error.detail
            else:
                raise AssertionError("A published clip was reported saved when YouTube rejected its metadata update.")
    print("PASS manual metadata edits sync published YouTube clips and keep local copy unchanged when sync fails")

    def post_text(cid):
        return {"title": f"{cid.title()} GTA race highlight",
                "description": (f"{cid} GTA racing gameplay: a distinct moment with a different decision and outcome. " * 28),
                "hashtags": ["GTA6", "Shorts"]}

    batch = [{"job": jid, "clip": cid, "metadata": post_text(cid)} for cid in ("second", "missing", "first")]
    endpoint = "/api/posts/youtube"
    requested = {"account": "yt", "clips": batch}
    result = app.post(endpoint, headers=origin, json=requested).json()
    assert [p["clip"] for p in result["posts"]] == ["second", "first"]
    first, second = result["posts"]
    assert second["due_at"] - first["due_at"] == 600 and result["skipped"][0]["clip"] == "missing"
    assert app.post(endpoint, headers=origin, json=requested).json()["queued"] == 0
    assert app.post(endpoint, headers=origin, json={**requested, "account": "ig"}).status_code == 400
    oversized = app.post(endpoint, headers=origin, json={**requested,
                           "clips": [{"job": jid, "clip": "missing"}] * 201})
    assert oversized.status_code == 400
    sent = app.post(endpoint, headers=origin, json={
        "account": "yt", "clips": [{"job": jid, "clip": "now", "metadata": {
            "title": "The last corner", "description": "Close racing. " * 120, "hashtags": "#GTA5 #Shorts"}}]
    }).json()
    assert sent["queued"] == 1 and abs(sent["posts"][0]["due_at"] - time.time()) < 2
    with ctx.as_user(owner):
        single = next(p for p in posting._mine() if p["id"] == sent["posts"][0]["id"])
        with patch.object(posting.media, "probe", return_value={"width": 1080, "height": 1920, "duration": 30}), \
                patch.object(accounts, "youtube_upload", return_value=("remote", "https://www.youtube.com/shorts/remote")) as upload:
            posting._post(single)
        assert single["status"] == "posted" and upload.call_args.args[5] == "private"
        assert len(upload.call_args.args[3]) >= 1500 and upload.call_args.args[3].count("#Shorts") == 1
        earlier = next(p for p in posting._mine() if p["id"] == first["id"])
        later = next(p for p in posting._mine() if p["id"] == second["id"])
        earlier["due_at"] = later["due_at"] + 90
        assert posting._space_batch(earlier) == [later]
        assert later["due_at"] == earlier["due_at"] + 600
    print("PASS direct and ordered YouTube batches, missing clips, duplicates, visibility, metadata and delayed slots")
    db.engine.dispose()
