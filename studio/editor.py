"""Source analysis and caption data shared by the editor and clip exports."""
import json
import math
import os
import re
import subprocess

import numpy as np

from . import config, ctx, media


def _ffmpeg(source, args, start=0):
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", str(source), *args, "pipe:1"],
            capture_output=True, creationflags=media.NO_WINDOW, timeout=600,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Source analysis took too long. Try a shorter range.") from e
    if result.returncode:
        raise RuntimeError("Couldn't analyze this video with FFmpeg.")
    return result.stdout


def pcm(source, start, duration, rate):
    raw = _ffmpeg(source, ["-t", str(duration), "-map", "0:a:0", "-af",
                           f"aresample={rate}:async=1:first_pts=0", "-ac", "1", "-ar", str(rate), "-f", "s16le"], start)
    return np.frombuffer(raw, dtype="<i2")


def waveform(source, duration):
    """Small peak envelope for the timeline, including gaps before the audio track."""
    samples = pcm(source, 0, duration, 400).astype(np.float32)
    if not len(samples):
        return []
    # Draw a fixed number of bins across the whole video, including a silent tail.
    count = max(1, round(duration * 400))
    samples = np.pad(samples[:count], (0, max(0, count - len(samples))))
    return [round(float(np.max(np.abs(part))) / 32768, 3)
            for part in np.array_split(samples, min(800, len(samples)))]


def gameplay(source, start, end, count, minimum, maximum, has_audio=False):
    """Find non-overlapping candidates using low-resolution frame changes and audio peaks."""
    span = end - start
    if span < min(3, minimum):
        return []
    raw = _ffmpeg(source, ["-t", str(span), "-map", "0:v:0", "-an",
                           "-vf", "fps=2,scale=48:28,format=gray", "-threads:v", "1", "-f", "rawvideo"], start)
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 48 * 28)
    if len(frames) < 2:
        return []
    motion = np.concatenate([
        np.mean(np.abs(np.diff(frames[i:i + 1025].astype(np.int16), axis=0)), axis=1)
        for i in range(0, len(frames) - 1, 1024)
    ])
    signal = motion / max(float(np.percentile(motion, 90)), 5)
    samples = pcm(source, start, span, 400) if has_audio else ()
    seconds = len(samples) // 400
    if seconds:
        rms = np.sqrt(np.mean((samples[:seconds * 400].reshape(seconds, 400).astype(np.float32) / 32768) ** 2, axis=1))
        db = 20 * np.log10(rms + 1e-5)
        peaks = np.clip((db - np.median(db)) / 12, 0, 2)
        signal += 0.35 * peaks[np.minimum((np.arange(len(signal)) + 1) // 2, len(db) - 1)]
    length = min(span, maximum, max(minimum, 18))
    picks = []
    for i in np.argsort(-signal):
        if signal[i] < 0.25:
            break
        moment = start + (int(i) + 1) / 2
        a = max(start, min(end - length, moment - length * 0.4))
        b = a + length
        if any(a < c["end"] and b > c["start"] for c in picks):
            continue
        picks.append({"start": round(a, 3), "end": round(b, 3), "title": "Gameplay highlight",
                      "hook": "", "description": "", "hashtags": [], "highlight_words": [],
                      "score": round(100 * (1 - math.exp(-max(0.0, float(signal[i])) / 1.4))),
                      "strength": float(signal[i]),
                      "category": "other", "reason": "Suggested from changes in the picture and audio." if has_audio
                      else "Suggested from changes in the picture.", "score_source": "signals"})
        if len(picks) == count:
            break
    return sorted(picks, key=lambda c: c["start"])


def caption_cues(words, start, end):
    """Group timed words into short editable lines in source time."""
    cues = []
    for word in sorted(words, key=lambda w: w["s"]):
        a, b = max(start, word["s"]), min(end, word["e"])
        if b <= a or not word["w"].strip():
            continue
        text = word["w"].strip()
        if (cues and a - cues[-1]["end"] < 0.45 and b - cues[-1]["start"] <= 3
                and len(cues[-1]["text"]) + len(text) < 60):
            cues[-1]["text"] += " " + text
            cues[-1]["end"] = max(b, cues[-1]["end"])
        elif not cues or b > cues[-1]["end"]:
            cues.append({"start": round(max(a, cues[-1]["end"] if cues else a), 3),
                         "end": round(b, 3), "text": text})
    return [cue for cue in cues if cue["end"] > cue["start"]]


def validate_segments(segments, duration):
    if not isinstance(segments, list) or len(segments) > 12:
        raise ValueError("Use up to 12 cut ranges.")
    result = []
    for span in segments:
        if not isinstance(span, dict):
            raise ValueError("Each range needs a start and an end.")
        a, b = round(float(span.get("start")), 3), round(float(span.get("end")), 3)
        if not 0 <= a < b <= duration or b - a < 0.25:
            raise ValueError("Keep each range inside the video and at least 0.25 seconds long.")
        if any(a < part["end"] and b > part["start"] for part in result):
            raise ValueError("Cut ranges cannot overlap.")
        result.append({"start": a, "end": b})
    if result and not 3 <= cut_length(result) <= 180:
        raise ValueError("The combined clip must be 3 to 180 seconds long.")
    return result


def cut_length(segments):
    return round(sum(span["end"] - span["start"] for span in segments), 3)


def stitch_words(words, segments, offset=0):
    """Translate source timestamps into the ordered cuts."""
    result, elapsed = [], offset
    for span in segments:
        for word in words:
            a, b = max(span["start"], word["s"]), min(span["end"], word["e"])
            if b > a:
                result.append(dict(word, s=elapsed + a - span["start"], e=elapsed + b - span["start"]))
        elapsed += span["end"] - span["start"]
    return result


def validate_keyframes(keyframes, duration):
    if not isinstance(keyframes, list) or len(keyframes) > 16:
        raise ValueError("Use up to 16 crop keyframes.")
    result = []
    for point in keyframes:
        if not isinstance(point, dict):
            raise ValueError("A crop keyframe needs time and crop positions.")
        t = round(float(point.get("time")), 3)
        x, y = float(point.get("x")), float(point.get("y"))
        if not (0 <= t < duration and 0 <= x <= 1 and 0 <= y <= 1) or (result and t <= result[-1]["time"]):
            raise ValueError("Crop keyframes must be in time order, inside the clip, with positions from 0 to 1.")
        result.append({"time": t, "x": x, "y": y})
    return result


def validate_cues(cues, start, end):
    if cues is None:
        return None
    if not isinstance(cues, list) or len(cues) > 300:
        raise ValueError("Use up to 300 caption lines per clip.")
    result, previous = [], start
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError("Each caption needs a start time, end time, and text.")
        a, b = round(float(cue.get("start")), 3), round(float(cue.get("end")), 3)
        if not math.isfinite(a) or not math.isfinite(b) or a < previous or b <= a or b > end:
            raise ValueError("Keep captions in time order, inside the clip, without overlap.")
        message = " ".join(str(cue.get("text", "")).split())
        if not message or len(message) > 160:
            raise ValueError("Use 1 to 160 characters per caption line.")
        result.append({"start": a, "end": b, "text": message})
        previous = b
    return result


def read_glossary():
    path = config.user_dir(ctx.uid()) / "caption-glossary.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_glossary(rules):
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError("Use up to 100 glossary entries.")
    clean = []
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("Each entry needs a phrase to replace and a correction.")
        heard = " ".join(str(rule.get("heard") or "").split())
        correct = " ".join(str(rule.get("correct") or "").split())
        normalized = tuple(_glossary_word(word) for word in heard.split())
        if (not normalized or not all(normalized) or len(normalized) > 8 or len(heard) > 100
                or not correct or len(correct) > 100 or normalized in seen):
            raise ValueError("Use unique phrases of up to 8 words and corrections of 1 to 100 characters.")
        seen.add(normalized)
        clean.append({"heard": heard, "correct": correct})
    path = config.user_dir(ctx.uid()) / "caption-glossary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix("." + os.urandom(6).hex() + ".tmp")
    try:
        temp.write_text(json.dumps(clean, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return clean


def _glossary_word(word):
    return re.sub(r"^\W+|\W+$", "", word.casefold())


def apply_glossary(words, rules):
    """Prefer longer phrases and preserve the timestamp span and trailing punctuation."""
    if not rules:
        return words
    patterns = sorted(
        [(tuple(_glossary_word(w) for w in rule["heard"].split()), rule["correct"]) for rule in rules],
        key=lambda item: -len(item[0]),
    )
    tokens = [_glossary_word(word["w"]) for word in words]
    result = []
    i = 0
    while i < len(words):
        for pattern, correction in patterns:
            j = i + len(pattern)
            if tuple(tokens[i:j]) == pattern:
                suffix = re.search(r"[.!?,;:]+$", words[j - 1]["w"])
                text = correction + (suffix.group() if suffix and correction[-1] not in ".!?,;:" else "")
                result.append({"w": text, "s": words[i]["s"], "e": words[j - 1]["e"]})
                i = j
                break
        else:
            result.append(words[i])
            i += 1
    return result


def srt(cues, start, end):
    def timestamp(seconds):
        ms = round(seconds * 1000)
        hours, remainder = divmod(ms, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        sec, ms = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{sec:02},{ms:03}"

    blocks = []
    for cue in cues:
        a, b = max(cue["start"], start), min(cue["end"], end)
        if b > a:
            blocks.append(f"{len(blocks) + 1}\n{timestamp(a - start)} --> {timestamp(b - start)}\n{cue['text']}\n")
    return "\n".join(blocks)
