"""Exercise the source timeline API and real FFmpeg output without cloud keys."""
from contextlib import ExitStack, contextmanager
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from zipfile import ZipFile

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, ".")


def wait_for(client, job_id, valid):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if valid(job):
            return job
        time.sleep(0.2)
    raise AssertionError(f"Job didn't reach the expected state: {job}")


def upload(client, media, mode):
    with media.open("rb") as file:
        return client.post("/api/upload", files={"file": (media.name, file, "video/mp4")},
                           data={"rights_cleared": "true", "options": json.dumps({"mode": mode, "min_len": 5,
                                                        "max_len": 10, "max_clips": 1,
                                                        "motion": "highlight" if mode == "gameplay" else "none",
                                                        "watermark": mode == "gameplay"})})


def run_editor(client, root):
    from studio import editor, media

    glossary = [{"heard": "Lost Santos", "correct": "Los Santos"}]
    response = client.put("/api/caption-glossary", json={"rules": glossary})
    response.raise_for_status()
    assert client.get("/api/caption-glossary").json() == {"rules": glossary}
    assert client.put("/api/caption-glossary", json={"rules": glossary * 2}).status_code == 400
    words = [{"w": "Lost", "s": 0, "e": 0.2}, {"w": "Santos.", "s": 0.2, "e": 0.7}]
    assert editor.apply_glossary(words, glossary) == [{"w": "Los Santos.", "s": 0, "e": 0.7}]
    print("PASS saved glossary corrects phrases and preserves their timing")

    source = root / "silent-test.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=red:s=320x180:r=24:d=4", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=4",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-c:v", "libx264", str(source)],
                   check=True, timeout=30)
    response = upload(client, source, "manual")
    response.raise_for_status()
    job_id = response.json()["id"]
    job = wait_for(client, job_id, lambda j: j["status"] in ("done", "error"))
    assert job["status"] == "done" and job["can_edit_source"] and job["clips"] == [], job
    assert client.get(f"/api/jobs/{job_id}/source", headers={"Range": "bytes=0-15"}).status_code == 206
    assert client.get(f"/api/jobs/{job_id}/waveform").json() == {"peaks": []}
    print("PASS silent upload opens a manual source with HTTP seeking")

    stages = []

    @contextmanager
    def downloader(options):
        class Download:
            def download(self, urls):
                destination = Path(options["outtmpl"].replace("%(ext)s", "mp4"))
                url = f"/api/jobs/{destination.parent.name}"
                assert options["continuedl"] and options["retries"] == 10
                assert options["fragment_retries"] == 10 and options["socket_timeout"] == 60
                options["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 25, "total_bytes": 100,
                                               "info_dict": {"vcodec": "avc1"}})
                stages.append(client.get(url).json())
                options["postprocessor_hooks"][0]({"status": "started", "postprocessor": "Merger"})
                stages.append(client.get(url).json())
                shutil.copyfile(source, destination)

        yield Download()

    meta = {"kind": "video", "is_live": False, "duration": 8, "title": "Replay", "uploader": "Player"}
    with patch.object(media, "info", return_value=meta), patch.object(media, "_ydl", downloader):
        unconfirmed = client.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=example", "options": {"mode": "manual"}})
        assert unconfirmed.status_code == 400 and "permission" in unconfirmed.json()["detail"].lower()
        print("PASS source links require an explicit rights confirmation before clipping")
        response = client.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=example", "options": {"mode": "manual"},
                                                   "rights_cleared": True})
        response.raise_for_status()
        linked_job = wait_for(client, response.json()["id"], lambda j: j["status"] in ("done", "error"))
    linked_trace = next(iter(root.glob(f"users/*/jobs/{linked_job['id']}/error.log")), None)
    linked_error = linked_trace.read_text(encoding="utf-8") if linked_trace else ""
    assert linked_job["status"] == "done" and linked_job["transfer"] is None, f"{linked_job}\n{linked_error}"
    assert stages[0]["progress"] > 0.03 and stages[0]["transfer"] == {"track": "video", "bytes": 25, "total": 100}
    assert stages[1]["stage"] == "Combining source video and audio" and stages[1]["transfer"] is None
    print("PASS replay download reports transferred bytes, merge status, and completion")

    voiced = root / "voiced-test.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-f", "lavfi", "-i", "sine=frequency=220",
                    "-c:v", "copy", "-c:a", "aac", "-shortest", str(voiced)], check=True, timeout=30)
    response = upload(client, voiced, "manual")
    response.raise_for_status()
    voiced_id = response.json()["id"]
    wait_for(client, voiced_id, lambda j: j["status"] == "done")
    waveform_url = f"/api/jobs/{voiced_id}/waveform"
    peaks = client.get(waveform_url).json()["peaks"]
    assert len(peaks) == 800 and max(peaks) > 0
    assert client.get(waveform_url).json()["peaks"] == peaks
    print("PASS a source with audio produces a cached waveform")

    multi_url = f"/api/jobs/{voiced_id}/clips"
    response = client.post(multi_url, json={
        "segments": [{"start": 4.5, "end": 6.5}, {"start": 0.5, "end": 2.5}],
        "crop_keyframes": [{"time": 0, "x": 0.2, "y": 0.5}, {"time": 3, "x": 0.8, "y": 0.5}],
        "caption_cues": [{"start": 1.0, "end": 1.7, "text": "Across cuts"}],
        "layout": "crop", "captions": "clean",
    })
    response.raise_for_status()
    multi_job = wait_for(client, voiced_id, lambda j: j["clips"][0]["status"] in ("done", "error"))
    multi_clip = multi_job["clips"][0]
    assert multi_clip["status"] == "done" and multi_clip["duration"] == 4, multi_clip
    multi_srt = client.get(f"/media/{voiced_id}/{multi_clip['subtitle']}").text.splitlines()
    assert multi_srt[1:3] == ["00:00:00,500 --> 00:00:01,200", "Across cuts"]
    assembly = root / "assembly.mp4"
    assembly.write_bytes(client.get(f"/media/{voiced_id}/{multi_clip['file']}").content)

    def pixel(at):
        data = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(assembly), "-frames:v", "1",
                               "-vf", "scale=1:1,format=rgb24", "-f", "rawvideo", "-"], capture_output=True, check=True)
        return data.stdout[:3]

    assert pixel(0.5)[2] > 200 and pixel(3)[0] > 200
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                              "-of", "json", str(assembly)], capture_output=True, check=True)
    assert any(s["codec_type"] == "audio" for s in json.loads(streams.stdout)["streams"])
    print("PASS reordered cuts and moving crop render with audio and clip-relative subtitles")

    clip_url = f"/api/jobs/{job_id}/clips"
    assert client.post(clip_url, json={"start": 7, "end": 99}).status_code == 400
    assert client.post(clip_url, json={"start": 0, "end": 5, "crop_x": 1.5}).status_code == 400
    assert client.post(clip_url, json={"start": 0, "end": 5,
                                      "caption_cues": [{"start": 4, "end": 7, "text": "past clip"}]}).status_code == 400
    print("PASS invalid trim, crop, and caption times are rejected")

    cue = {"start": 1.75, "end": 3.0, "text": "Vice City"}
    response = client.post(clip_url, json={"start": 1.25, "end": 5.25, "layout": "crop", "crop_x": 0.2,
                                           "captions": "clean", "caption_cues": [cue], "title": "Manual test"})
    response.raise_for_status()
    clip_id = response.json()["clip_id"]
    job = wait_for(client, job_id, lambda j: j["clips"][0]["status"] in ("done", "error"))
    clip = job["clips"][0]
    assert clip["status"] == "done" and clip["manual"], clip
    assert client.get(f"{clip_url}/{clip_id}/captions").json() == {"cues": [cue], "edited": True}
    srt = client.get(f"/media/{job_id}/{clip['subtitle']}").text
    assert srt.splitlines()[1:3] == ["00:00:00,500 --> 00:00:01,750", "Vice City"], srt
    output = root / "output.mp4"
    video = client.get(f"/media/{job_id}/{clip['file']}")
    video.raise_for_status()
    output.write_bytes(video.content)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height:format=duration",
                            "-of", "json", str(output)], check=True, capture_output=True, timeout=30)
    info = json.loads(probe.stdout)
    assert info["streams"] == [{"width": 1080, "height": 1920}], info
    assert abs(float(info["format"]["duration"]) - 4) < 0.1, info
    ass = next(root.rglob(f"{clip_id}.ass"))
    assert "Dialogue:" not in ass.read_text(encoding="utf-8")
    print("PASS clean vertical render and correctly shifted SRT")

    response = client.get("/api/clips.zip", params={"subtitles": 1, "ids": f"{job_id}.{clip_id}"})
    response.raise_for_status()
    with ZipFile(BytesIO(response.content)) as batch:
        assert set(batch.namelist()) == {"Manual test.mp4", "Manual test.srt"}
    print("PASS batch export includes video and companion subtitles")

    response = client.post(f"{clip_url}/{clip_id}/render", json={"captions": "burn"})
    response.raise_for_status()
    job = wait_for(client, job_id, lambda j: j["clips"][0]["version"] == 2 or j["clips"][0]["status"] == "error")
    assert job["clips"][0]["status"] == "done", job
    assert "Vice City" in ass.read_text(encoding="utf-8")
    print("PASS timed edits survive rerender and burn into the caption track")

    with patch.object(editor, "gameplay", side_effect=RuntimeError("Temporary scanner error")):
        response = upload(client, source, "gameplay")
        response.raise_for_status()
        gameplay_id = response.json()["id"]
        job = wait_for(client, gameplay_id, lambda j: j["status"] == "error")
        assert job["can_edit_source"] and job["failed_stage"] == "Scanning gameplay for action", job
    client.post(f"/api/jobs/{gameplay_id}/retry").raise_for_status()
    job = wait_for(client, gameplay_id, lambda j: j["status"] in ("done", "error"))
    assert job["status"] == "done" and len(job["clips"]) == 1 and job["clips"][0]["status"] == "done", job
    assert not job["ai"]["used"], job
    highlight = job["clips"][0]
    assert "Gameplay highlight" in highlight["title"] and "Source time" in highlight["description"]
    assert highlight["hashtags"] == ["Gaming", "Gameplay", "Shorts"], highlight
    graphics = next(root.rglob(f"{highlight['id']}.ass")).read_text(encoding="utf-8")
    assert "MJ PLAYS GTA" in graphics and any(line.endswith("}MJ") for line in graphics.splitlines()), graphics
    print("PASS gameplay retries a failed scan and renders a silent visual highlight")
    print("PASS local gameplay drafts title, description and hashtags and renders the motion label")

    from studio import brain, jobs
    draft = brain.gameplay_post("GTA Online races", 60, 90)
    assert draft["hashtags"][0] == "GTAOnline" and "0:01:00–0:01:30" in draft["description"]
    with patch.object(brain, "ask_ai", return_value=([{"title": "The final turn", "description": "MJ takes the final turn.",
                                                       "hashtags": ["GTARacing"]}], "test-model", 10)):
        refined = brain.gameplay_post("GTA Online races", 60, 90, "I am taking the final turn right now", True)
    assert refined["title"] == "The final turn" and refined["hashtags"][:2] == ["GTARacing", "GTAOnline"]
    print("PASS optional AI drafts preserve the source game tag and deterministic fallback")

    scan_job = {"options": {"max_clips": 2, "min_len": 5, "max_len": 20}}
    bounds = []

    def fake_window(path, start, end, *args, **kwargs):
        bounds.append((start, end))
        if len(bounds) == 3:
            raise RuntimeError("Transient decoding error")
        return [{"start": end - 17, "end": end - 1, "strength": end}]

    with patch.object(editor, "gameplay", side_effect=fake_window), \
            patch.object(jobs, "_set", side_effect=lambda job, **fields: job.update(fields)):
        try:
            jobs._scan_gameplay(scan_job, source, 0, 43200, False)
        except RuntimeError:
            assert scan_job["gameplay_scan"]["cursor"] == 1200
        else:
            raise AssertionError("The simulated interruption succeeded unexpectedly.")
        best = jobs._scan_gameplay(scan_job, source, 0, 43200, False)
    assert len(bounds) == 73 and bounds[2] == bounds[3] and bounds[-1][1] == 43200
    hours = [int((clip["start"] + clip["end"]) / 2 // 3600) for clip in best]
    assert len(best) == 12 and hours == list(range(12)), best
    print("PASS a simulated twelve-hour scan resumes at its checkpoint and ranks the entire stream")

    from studio import media
    from unittest.mock import MagicMock
    extractor = MagicMock()
    extractor.__enter__.return_value.extract_info.return_value = {"entries": [
        {"id": "abcdefghijk", "title": "Finished replay", "duration": 800},
        {"id": "abcdefghijl", "title": "Live now", "duration": 100, "live_status": "is_live"},
        {"id": "abcdefghijm", "title": "Upcoming", "duration": 100, "live_status": "is_upcoming"},
    ]}
    with patch.object(media, "_ydl", return_value=extractor):
        replays = client.get("/api/replays", params={"url": "https://www.youtube.com/@testchannel"})
    assert replays.json()["replays"] == [{"title": "Finished replay", "url": "https://www.youtube.com/watch?v=abcdefghijk",
                                         "duration": 800}]
    assert client.get("/api/replays", params={"url": "https://example.com/test"}).status_code == 400
    assert client.get("/assets/collections.js").status_code == 200
    print("PASS Replay Picker separates finished broadcasts from live and upcoming entries")


def run_providers(ai):
    assert "glm-4.7-flash" in ai.list_models("zai")
    assert ai.PROVIDERS["qwen"][0].startswith("Alibaba") and ai.PROVIDERS["deepseek"][1]
    try:
        ai.save("openrouter-free", ["openai/gpt-4o"], "", "test-key")
    except ValueError:
        pass
    else:
        raise AssertionError("OpenRouter Free accepted a paid model.")
    ai.save("openrouter-free", ["openrouter/free"], "https://example.invalid", "test-key")
    with patch.object(ai.httpx, "post", return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": '{"items":["ok"]}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    })) as request:
        assert ai.test()["ok"]
        assert request.call_args.args[0] == "https://openrouter.ai/api/v1/chat/completions"
        body = request.call_args.kwargs["json"]
        assert body["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0}
    print("PASS GLM presets and OpenRouter Free paid-model rejection and price cap")


with ExitStack() as stack:
    directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="peakcut-editor-test-")))
    os.environ.update(PEAKCUT_DATA=str(directory), PEAKCUT_ACCOUNTS="0", PEAKCUT_FETCH_MODEL="0",
                      PEAKCUT_UPDATE_CHECK="0", PEAKCUT_AI_KEY="", PEAKCUT_AI_MODELS="", DATABASE_URL="")
    from studio import ai, db, server
    stack.callback(db.engine.dispose)
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        client = stack.enter_context(TestClient(server.app, base_url="http://127.0.0.1:8799"))
        run_editor(client, directory)
    else:
        print("Editor rendering checks skipped because FFmpeg and FFprobe are unavailable.")
    run_providers(ai)
    print("ALL PASSED")
