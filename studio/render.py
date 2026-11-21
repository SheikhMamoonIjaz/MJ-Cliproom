"""Turns a time range into a vertical clip: 9:16 layout, bouncy word captions, hook title, cover."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config, editor, roman
from .media import NO_WINDOW, probe, run

W, H = config.OUT_W, config.OUT_H

# ASS colours are &HBBGGRR. `size` is the ASS font size (line height); _Font turns it into real pixels.
STYLES = {
    "bounce": {"label": "Bounce", "font": "Poppins ExtraBold", "size": 132, "base": "FFFFFF", "active": "00F0FF",
               "strong": "FFFFFF", "outline": 7, "pop": 112, "upper": True, "per": 3},
    "hype": {"label": "Hype", "font": "Anton", "size": 152, "base": "FFFFFF", "active": "3C3CFF",
             "strong": "00D7FF", "outline": 7, "pop": 114, "upper": True, "per": 2},
    "clean": {"label": "Clean", "font": "Poppins ExtraBold", "size": 100, "base": "FFFFFF", "active": "6BD7FF",
              "strong": "FFFFFF", "outline": 5, "pop": 106, "upper": False, "per": 4},
}
HOOK = {"font": "Poppins ExtraBold", "size": 96, "ink": "14100E", "box": "FFFFFF", "pad_x": 36, "pad_y": 22, "radius": 26,
        "max_w": 900}
FONT_FILES = {"Poppins ExtraBold": "Poppins-ExtraBold.ttf", "Anton": "Anton-Regular.ttf", "Archivo Black": "ArchivoBlack-Regular.ttf"}
CAP_MAX_W = 960   # captions never run wider than this, whatever is said


class _Font:
    """Measures text exactly as the renderer will draw it, so every word can be placed by hand: the highlighted
    word can grow without pushing its neighbours, and the heading box fits its text."""
    _cache: dict = {}

    def __init__(self, name):
        import struct
        path = Path(__file__).resolve().parent / "fonts" / FONT_FILES.get(name, FONT_FILES["Poppins ExtraBold"])
        d = path.read_bytes()
        tables = {}
        for i in range(struct.unpack(">H", d[4:6])[0]):
            tag, _, off, _ = struct.unpack(">4sIII", d[12 + 16 * i: 28 + 16 * i])
            tables[tag] = off
        self.upm = struct.unpack(">H", d[tables[b"head"] + 18: tables[b"head"] + 20])[0]
        o = tables[b"OS/2"]
        self.asc, self.desc = struct.unpack(">HH", d[o + 74: o + 78])      # what the renderer sizes the font by
        self.cap = struct.unpack(">h", d[o + 88: o + 90])[0] or int(self.upm * 0.7)
        self.path = str(path)
        self._pil = {}

    @classmethod
    def get(cls, name):
        if name not in cls._cache:
            cls._cache[name] = cls(name)
        return cls._cache[name]

    def em(self, size):
        return size * self.upm / (self.asc + self.desc)

    def width(self, text, size):
        """Pixels wide at this ASS size."""
        try:
            from PIL import ImageFont
            if "f" not in self._pil:
                self._pil["f"] = ImageFont.truetype(self.path, 200)
            return self._pil["f"].getlength(text) * self.em(size) / 200
        except Exception:  # noqa: BLE001 - no measuring library: a fair estimate keeps clips rendering
            return len(text) * self.em(size) * 0.62

    def cap_shift(self, size):
        """How far below the anchor the middle of a capital letter sits when text is centred on a point."""
        return ((self.asc - self.desc) / 2 - self.cap / 2) * size / (self.asc + self.desc)


CAPTION_LEAD = 0.0  # measured: word stamps are within 0.15 s of the voice, so no shift is needed
def install_fonts():
    """Copy the bundled caption fonts next to the data, so captions look the same on every machine and server."""
    src = Path(__file__).resolve().parent / "fonts"
    for f in src.glob("*.ttf"):
        if not (config.FONTS_DIR / f.name).exists():
            shutil.copyfile(f, config.FONTS_DIR / f.name)


LAYOUTS = {
    "blur": "Fit with blur (9:16)",
    "auto": "9:16 with facecam below when detected",
    "crop": "Full-screen gameplay (9:16)",
    "stack": "9:16 gameplay above facecam",
}

MOTION_PRESETS = {
    "none": "No motion overlay",
    "highlight": "MJ Brand Title Pill",
    "kinetic": "Kinetic Pop & Hook Emphasis",
    "lower_third": "Editorial Lower-Third Card",
    "punch_zoom": "Dynamic Punch-In Zoom",
    "swipe_reveal": "Swipe Reveal Entrance",
    "parallax": "Ambient Parallax Blur",
}


def _ts(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def _clean(text):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", re.sub(r"[{}\\]", "", str(text))).strip()


def _key(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _groups(words, per):
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= per or sum(len(x["w"]) for x in cur) + len(w["w"]) > 16
                    or w["s"] - cur[-1]["e"] > 0.45 or cur[-1]["w"][-1:] in ".?!"):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def choose_facecam(corners) -> str:
    """Pick the corner with the most activity. That is usually the facecam."""
    if not isinstance(corners, dict) or not corners:
        return "left"
    return max(("left", "right", "center"), key=lambda name: float(corners.get(name) or 0))


def face_x(corner: str) -> str:
    return {"left": "0", "right": "iw-ow", "center": "(iw-ow)/2"}.get(corner or "left", "0")


def split_filter(layout: str, facecam: str = "left") -> str:
    """Stack gameplay and facecam in a vertical frame. The facecam pane is not cropped away."""
    face_h, game_h = 440, 1040
    if isinstance(facecam, tuple):
        cx, cy = facecam
        x = f"'max(0,min(iw-ow,iw*{cx:.5f}-ow/2))'"
        y = f"'max(0,min(ih-oh,ih*{cy:.5f}-oh/2))'"
    else:
        x, y = face_x(facecam), "ih-oh"
    face = (f"crop='min(iw*0.36,ih*0.44*{W}/{face_h})':'ow*{face_h}/{W}':{x}:{y},"
            f"scale={W}:{face_h}")
    game = f"scale={W}:{game_h}:force_original_aspect_ratio=increase,crop={W}:{game_h}:(iw-ow)/2:(ih-oh)/2"
    if layout == "split":
        top, bottom = face, game
    else:
        top, bottom = game, face
    return (f"[0:v]fps={config.OUT_FPS},split=2[panetop][panebot];"
            f"[panetop]{top},setsar=1[a];[panebot]{bottom},setsar=1[b];"
            f"[a][b]vstack=inputs=2,pad={W}:{H}:0:0:color=0x101419,setsar=1[v0];")


def geometry(src_w, src_h, layout):
    """Where the video sits in the 1080x1920 frame, and where hook and captions go."""
    if layout == "zoom":
        layout = "crop"
    if layout in ("stack", "split"):
        return layout, H, 280, 1540
    if src_h >= src_w and layout not in ("crop", "blur"):
        layout = "crop"
    if layout == "blur":
        fg_h = min(H, max(480, int(round(W * max(1, src_h) / max(1, src_w) / 2)) * 2))
    else:
        fg_h = H
    top = (H - fg_h) // 2
    if layout == "crop":
        return layout, fg_h, 310, 1520
    # Fit with blur: place hook in upper safe zone above foreground and captions in lower safe zone below foreground
    hook_y = max(290, min(420, top - 130)) if top > 360 else 310
    cap_y = min(1580, max(1420, top + fg_h + 150)) if (top + fg_h) < 1500 else 1520
    return layout, fg_h, hook_y, cap_y


def solve_safe_layout(src_w: int, src_h: int, layout: str = "blur", caption_position: str = "bottom",
                      has_hook: bool = True, has_brand: bool = False, has_lower_third: bool = False,
                      watermark_corner: str = "top-left") -> dict:
    """Compute guaranteed non-overlapping vertical title-safe bounding boxes on the 1080x1920 canvas."""
    eff_layout, fg_h, hook_y, cap_y = geometry(src_w or 1920, src_h or 1080, layout or "blur")
    place = (caption_position or "bottom").lower()

    # Reserve top status/brand zone (Y: 140..235)
    brand_box = (56, 156, 520, 224) if has_brand else None
    wm_corners = {
        "top-left": (60, 152, 220, 220),
        "top-right": (W - 220, 152, W - 60, 220),
        "bottom-left": (60, H - 230, 220, H - 162),
        "bottom-right": (W - 220, H - 230, W - 60, H - 162),
    }
    wm_box = wm_corners.get(watermark_corner or "top-left", wm_corners["top-left"])
    if has_brand and (watermark_corner or "top-left") == "top-left":
        # Shift top-left watermark to top-right when top-left brand pill is active so they never collide
        wm_box = wm_corners["top-right"]
        effective_wm_corner = "top-right"
    else:
        effective_wm_corner = watermark_corner or "top-left"

    if place == "top":
        cap_y = 360
        hook_y = 600 if has_hook else 335
        lt_y = 1480
    elif place == "middle":
        hook_y = 335
        cap_y = 960
        lt_y = 1480
    else:
        hook_y = max(335, hook_y)
        cap_y = max(1440, min(1580, cap_y))
        lt_y = min(1260, cap_y - 180)

    hook_box = (90, int(hook_y - 95), W - 90, int(hook_y + 95)) if has_hook else None
    cap_box = (60, int(cap_y - 105), W - 60, int(cap_y + 105))
    lower_third_box = (64, int(lt_y - 54), 760, int(lt_y + 54)) if has_lower_third else None

    return {
        "canvas": {"width": W, "height": H, "aspect": "9:16"},
        "layout": eff_layout,
        "foreground_height": fg_h,
        "hook_y": int(hook_y),
        "cap_y": int(cap_y),
        "lower_third_y": int(lt_y),
        "watermark_corner": effective_wm_corner,
        "boxes": {
            k: v for k, v in (
                ("brand", brand_box),
                ("watermark", wm_box),
                ("hook", hook_box),
                ("lower_third", lower_third_box),
                ("captions", cap_box),
            ) if v is not None
        },
    }


def _rounded_rect_ass(x0: float, y0: float, x1: float, y1: float, r: float = 24.0) -> str:
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    n = lambda v: f"{v:.0f}"  # noqa: E731
    return (f"m {n(x0 + r)} {n(y0)} l {n(x1 - r)} {n(y0)} b {n(x1)} {n(y0)} {n(x1)} {n(y0)} {n(x1)} {n(y0 + r)} "
            f"l {n(x1)} {n(y1 - r)} b {n(x1)} {n(y1)} {n(x1)} {n(y1)} {n(x1 - r)} {n(y1)} "
            f"l {n(x0 + r)} {n(y1)} b {n(x0)} {n(y1)} {n(x0)} {n(y1)} {n(x0)} {n(y1 - r)} "
            f"l {n(x0)} {n(y0 + r)} b {n(x0)} {n(y0)} {n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}")


def _hook_events(hook, dur, y):
    """The heading: dark text in a white rounded box that fits it, on one line or two balanced ones."""
    f, size = _Font.get(HOOK["font"]), HOOK["size"]
    words = hook.split()
    if not words:
        return []
    lines = [" ".join(words)]
    if f.width(lines[0], size) > HOOK["max_w"] and len(words) > 1:      # two lines, split where they come out most even
        cut = min(range(1, len(words)), key=lambda i: max(f.width(" ".join(words[:i]), size), f.width(" ".join(words[i:]), size)))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    widest = max(f.width(l, size) for l in lines)
    if widest > HOOK["max_w"]:
        size = max(40, int(size * HOOK["max_w"] / widest))
        widest = max(f.width(l, size) for l in lines)
    line_h = f.em(size) * 1.16
    bw, bh = widest + 2 * HOOK["pad_x"], line_h * len(lines) + 2 * HOOK["pad_y"]
    x0, y0, r = (W - bw) / 2, y - bh / 2, min(HOOK["radius"], bh / 2)
    x1, y1 = x0 + bw, y0 + bh
    box = _rounded_rect_ass(x0, y0, x1, y1, r)
    span = f"{_ts(0)},{_ts(dur)}"
    ev = [f"Dialogue: 3,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(160,0)\\c&H{HOOK['box']}&\\p1}}{box}{{\\p0}}"]
    for i, line in enumerate(lines):
        cy = y - line_h * (len(lines) - 1) / 2 + i * line_h - f.cap_shift(size)
        ev.append(f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an5\\pos({W // 2},{cy:.0f})\\fad(160,0)\\fs{size}}}{line}")
    return ev


def _lower_third_events(dur: float, title: str = "", subtitle: str = "", y: int = 1260) -> list:
    """Animated editorial lower-third card shown near the start of the clip without overlapping captions."""
    if dur < 1.5:
        return []
    end_t = min(dur, 4.0)
    span = f"{_ts(0.15)},{_ts(end_t)}"
    main_text = (_clean(title) or "FEATURED HIGHLIGHT")[:44]
    sub_text = (_clean(subtitle) or "MJ CLIPROOM")[:48]
    box = _rounded_rect_ass(64, y - 52, 740, y + 52, 18)
    Accent = _rounded_rect_ass(64, y - 52, 78, y + 52, 6)
    return [
        f"Dialogue: 2,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(180,220)\\c&H181614&\\alpha&H38&\\p1}}{box}{{\\p0}}",
        f"Dialogue: 3,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(180,220)\\c&H1F4ED9&\\p1}}{Accent}{{\\p0}}",
        f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an7\\pos(98,{y - 38})\\fad(180,220)\\fs40\\b1\\c&HFFFFFF&}}{main_text}",
        f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an7\\pos(98,{y + 6})\\fad(180,220)\\fs28\\b1\\c&H7AD7FF&}}{sub_text}",
    ]


def _brand_events(dur: float, title: str = "") -> list:
    """A short brand title at the start and again at the end. It does not cover the facecam."""
    intro = min(1.8, max(0.5, dur * 0.12))
    label = _clean(title) if title and _clean(title) else "MJ PLAYS GTA"
    look = rf"{{\an7\pos(56,192)\fad(140,200)\fs48\b1\bord3\c&HD7F1FF&\3c&H3A3312&}}{label}"
    events = [f"Dialogue: 3,0:00:00.00,{_ts(intro)},Cap,,0,0,0,,{look}"]
    if dur > 4:
        begin = max(intro + 0.3, dur - 1.8)
        events.append(f"Dialogue: 3,{_ts(begin)},{_ts(dur)},Cap,,0,0,0,,{look}")
    return events


_PRESET_CACHE = {"mtime": None, "data": {}}
_PRESET_DEFAULTS = {
    "voiceover": {"tone": "Energetic Gamer / Hype", "prefix": "Wait until you see what happened in this GTA 6 mission..."},
    "map_overlay": {"enabled": False, "loc": "Vice City East · Port Gellhorn", "style": "Dark Glass Pill with Coordinates"},
    "autozoom": {"enabled": False, "intensity": "Dynamic Smooth (1.25x Punch-in)", "corner": "Top-Left (Default Esports)"},
    "captions": {"preset": "Bounce (Bold Yellow Highlight + Deep Shadow)", "limit": 3, "backing": True},
    "branding": {"brand_title": "MJ PLAYS GTA", "watermark_text": "MJ", "watermark_corner": "top-left", "watermark_opacity": 88},
    "quality_guard": {"trim_silence": False, "min_lead_pad": 0.35, "skip_dark_frames": True},
    "publishing_window": {"enabled": False, "start_hour": 12, "end_hour": 23},
    "retention": {"enabled": False, "hours": 48},
    "cross_post": {"platforms": ["youtube"]},
}


def studio_presets() -> dict:
    """Read saved studio render and automation presets from the data folder, cached by file mtime."""
    import json
    path = config.DATA_DIR / "studio_presets.json"
    try:
        mtime = path.stat().st_mtime_ns if path.is_file() else 0
    except OSError:
        mtime = 0
    if _PRESET_CACHE["mtime"] != mtime:
        loaded = {}
        if mtime:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    loaded = raw
            except (OSError, ValueError):
                loaded = {}
        merged = {}
        for key, default in _PRESET_DEFAULTS.items():
            val = loaded.get(key)
            merged[key] = {**default, **val} if isinstance(val, dict) else dict(default)
        _PRESET_CACHE["mtime"] = mtime
        _PRESET_CACHE["data"] = merged
    return _PRESET_CACHE["data"]


def trim_dead_air(words: list, start: float, end: float, pad: float = 0.35) -> tuple:
    """Trim leading and trailing dead air (> 1.2s) around spoken words without making the clip too short."""
    span = end - start
    if span <= 4.0 or not words:
        return start, end
    inside = [w for w in words if isinstance(w, dict) and w.get("w") and w.get("e", 0) > start and w.get("s", 0) < end]
    if not inside:
        return start, end
    first_s = max(start, min(float(w["s"]) for w in inside))
    last_e = min(end, max(float(w["e"]) for w in inside))
    new_start = max(start, first_s - pad) if (first_s - start) > 1.2 else start
    new_end = min(end, last_e + pad) if (end - last_e) > 1.2 else end
    min_len = max(3.0, span * 0.55)
    if new_end - new_start < min_len:
        return start, end
    return round(new_start, 3), round(new_end, 3)


def build_ass(words, start, end, hook, style_name, highlight, hook_y, cap_y, cues=None, motion="none",
              watermark=False, brand=False, map_overlay=None, words_per_group=None,
              brand_title="", watermark_text="MJ", watermark_corner="top-left", watermark_opacity=88,
              caption_backing=True, lower_third_y=1260) -> str:
    st = STYLES.get(style_name, STYLES["bounce"])
    words = [dict(w, s=w["s"] - CAPTION_LEAD, e=w["e"] - CAPTION_LEAD) for w in words]
    strong = {_key(h) for h in highlight if _key(h)}
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{st['size']},&H00{st['base']},&H00{st['base']},&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{st['outline']},2,5,0,0,0,1
Style: Hook,{HOOK['font']},{HOOK['size']},&H00{HOOK['ink']},&H00{HOOK['ink']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
Style: Box,{HOOK['font']},40,&H00121212,&H00121212,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dur = end - start
    has_brand = bool(motion == "highlight" or brand)
    if has_brand and watermark and watermark_corner == "top-left":
        watermark_corner = "top-right"
    ev = _hook_events(_clean(hook), dur, hook_y)
    if has_brand:
        ev.extend(_brand_events(dur, brand_title))
    if motion == "lower_third":
        ev.extend(_lower_third_events(dur, hook or brand_title or "HIGHLIGHT", brand_title or "MJ CLIPROOM", y=lower_third_y))
    if watermark:
        wm_label = _clean(watermark_text) or "MJ"
        corners = {
            "top-left": (7, 76, 174),
            "top-right": (9, W - 76, 174),
            "bottom-left": (1, 76, H - 174),
            "bottom-right": (3, W - 76, H - 174),
        }
        an, wx, wy = corners.get(watermark_corner, (7, 76, 174))
        opacity = max(10, min(100, int(watermark_opacity or 88)))
        alpha = max(0, min(255, int(round((100 - opacity) * 255 / 100))))
        ev.append(f"Dialogue: 5,0:00:00.00,{_ts(dur)},Cap,,0,0,0,,"
                  rf"{{\an{an}\pos({wx},{wy})\fs62\b1\bord4\c&HD7F1FF&\3c&H3A3312&\alpha&H{alpha:02X}&}}{wm_label}")
    if map_overlay:
        loc = _clean(map_overlay) if isinstance(map_overlay, str) and map_overlay.strip() else "Vice City"
        map_y = 248 if has_brand else 180
        ev.append(f"Dialogue: 4,0:00:00.00,{_ts(dur)},Cap,,0,0,0,,"
                  f"{{\\an7\\pos(64,{map_y})\\fs42\\b1\\bord3\\c&H00FFFFFF&\\3c&H00000000&\\shad2}}📍 {loc}")
    f = _Font.get(st["font"])
    if cues is not None:
        for cue in cues:
            a, b = max(start, cue["start"]) - start, min(end, cue["end"]) - start
            if b - a >= 0.02:
                label = _clean(cue["text"])
                size = min(st["size"], 100 if len(label) <= 65 else 72)
                if caption_backing and label:
                    est_w = min(CAP_MAX_W + 48, max(240, len(label) * size * 0.36 + 56))
                    bx0, bx1 = (W - est_w) / 2, (W + est_w) / 2
                    by0, by1 = cap_y - size * 0.62, cap_y + size * 0.62
                    pill = _rounded_rect_ass(bx0, by0, bx1, by1, 20)
                    ev.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},Box,,0,0,0,,{{\\an7\\pos(0,0)\\c&H141210&\\alpha&H58&\\p1}}{pill}{{\\p0}}")
                ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cap,,60,60,0,,"
                          f"{{\\an5\\pos({W // 2},{cap_y:.0f})\\q0\\fs{size}}}{label}")
        return head + "\n".join(ev) + "\n"
    inside = [dict(w, w=_clean(w["w"])) for w in words if w["s"] >= start - 0.05 and w["s"] < end]
    inside = sorted((w for w in inside if w["w"]), key=lambda w: w["s"])
    for i, w in enumerate(inside[:-1]):
        w["e"] = max(w["s"], min(w["e"], inside[i + 1]["s"]))
    per = max(1, min(6, int(words_per_group))) if words_per_group else st["per"]
    groups = _groups(inside, per)
    pop_boost = 6 if motion == "kinetic" else 0
    for gi, g in enumerate(groups):
        g_start = max(0.0, g[0]["s"] - start)
        g_end = min(g[-1]["e"] + 0.25, groups[gi + 1][0]["s"] if gi + 1 < len(groups) else end) - start
        if g_end - g_start < 0.02:
            continue
        texts = []
        for x in g:
            t = re.sub(r"[.,;:]+$", "", x["w"])
            texts.append(t.upper() if st["upper"] else t)
        if not all(roman.drawable(t) for t in texts):
            line = " ".join(texts)
            fs = max(44, min(int(st["size"] * 0.7), int(1500 / max(1, len(line)) * 1.6)))
            ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(g_end)},Cap,,60,60,0,,{{\\an5\\pos({W // 2},{cap_y:.0f})\\q0\\fs{fs}}}{line}")
            continue
        size = st["size"]
        gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * st["outline"] + 6) * size / st["size"]
        total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        if total > CAP_MAX_W:
            size = max(36, int(size * CAP_MAX_W / total))
            gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * st["outline"] + 6) * size / st["size"]
            total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        if caption_backing and texts:
            pad_x, pad_y = 28, max(18, int(f.em(size) * 0.24))
            lh = f.em(size)
            bx0, bx1 = max(36, (W - total) / 2 - pad_x), min(W - 36, (W + total) / 2 + pad_x)
            by0, by1 = cap_y - lh * 0.56 - pad_y, cap_y + lh * 0.56 + pad_y
            pill = _rounded_rect_ass(bx0, by0, bx1, by1, 22)
            ev.append(f"Dialogue: 0,{_ts(g_start)},{_ts(g_end)},Box,,0,0,0,,{{\\an7\\pos(0,0)\\c&H141210&\\alpha&H5C&\\p1}}{pill}{{\\p0}}")
        cy = cap_y - f.cap_shift(size)
        x = (W - total) / 2
        for i, (w, t) in enumerate(zip(g, texts)):
            wd = f.width(t, size)
            p = max(104, min(st["pop"] + pop_boost, 100 + int(2200 / max(wd, 1))))
            pos = f"\\an5\\pos({x + wd / 2:.0f},{cy:.0f})\\fs{size}"
            x += wd + gap
            a = max(g_start, w["s"] - start)
            b = (g[i + 1]["s"] - start) if i + 1 < len(g) else g_end
            base = st["strong"] if _key(w["w"]) in strong else st["base"]
            if a - g_start >= 0.02:
                ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(a)},Cap,,0,0,0,,{{{pos}\\c&H{base}&}}{t}")
            if b - a >= 0.02:
                ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{st['active']}&\\fscx94\\fscy94"
                          f"\\t(0,90,\\fscx{p}\\fscy{p})\\t(90,200,\\fscx{p - 5}\\fscy{p - 5})}}{t}")
            if g_end - b >= 0.02:
                ev.append(f"Dialogue: 1,{_ts(b)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}\\c&H{base}&\\fscx{p - 5}\\fscy{p - 5}"
                          f"\\t(0,90,\\fscx100\\fscy100)}}{t}")
    return head + "\n".join(ev) + "\n"


def _crop_expression(keyframes, axis, initial):
    samples = [(point["time"], point[axis]) for point in keyframes]
    if not samples:
        return f"{initial:.4f}"
    if samples[0][0] > 0:
        samples.insert(0, (0, initial))
    value = f"{samples[-1][1]:.4f}"
    for (a, x), (b, y) in reversed(list(zip(samples, samples[1:]))):
        value = f"if(lt(t,{b:.3f}),{x:.4f}+({y-x:.4f})*max(0,t-{a:.3f})/{b-a:.3f},{value})"
    return value


def _filter(layout, fg_h, crop_x=0.5, crop_y=0.5, keyframes=(), preserve_marks=False, facecam="left", motion="none"):
    if layout in ("stack", "split"):
        return split_filter(layout, facecam)
    if preserve_marks:
        # Fit the whole picture, including a corner watermark. Nothing is cropped off and nothing is blurred away.
        return (f"[0:v]fps={config.OUT_FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[v0];")
    x = f"x='(iw-ow)*({_crop_expression(keyframes, 'x', crop_x)})'"
    y = f"y='(ih-oh)*({_crop_expression(keyframes, 'y', crop_y)})'"
    if layout in ("crop", "zoom"):
        if motion == "punch_zoom":
            zw, zh = int(W * 1.10), int(H * 1.10)
            return (f"[0:v]fps={config.OUT_FPS},scale={zw}:{zh}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{H}:{x}:{y},setsar=1[v0];")
        return f"[0:v]fps={config.OUT_FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:{x}:{y},setsar=1[v0];"
    # Default 9:16 Fit with blur composition: darkened Gaussian-blurred backdrop + sharp uncropped foreground
    fg_scale_h = fg_h if fg_h < H else int(round(W * 9 / 16 / 2)) * 2
    overlay_y = "(H-h)/2"
    if motion == "parallax":
        overlay_y = "(H-h)/2+14*sin(t*0.9)"
    return (f"[0:v]fps={config.OUT_FPS},split=2[a][b];"
            f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,"
            f"scale={W}:{H},eq=brightness=-0.14:saturation=1.15[bg];"
            f"[b]scale={W}:{fg_scale_h}:force_original_aspect_ratio=increase,crop={W}:{fg_scale_h}:{x}:{y}[fg];"
            f"[bg][fg]overlay=0:{overlay_y},setsar=1[v0];")


_qsv_ok = None
RENDER_SECONDS = 600      # one clip's video encode; far beyond normal, so a frozen encoder is stopped, not waited on


def apply_commentary(fc, inputs, audio, audio_map, cut, commentary_path, duration, volume=1.0):
    """Mix the owner's own narration on top of the stream. The picture is not changed."""
    if not commentary_path:
        return fc, inputs, audio
    path = Path(commentary_path)
    if not path.is_file():
        raise RuntimeError("The commentary track is missing.")
    index = list(inputs).count("-i")
    inputs = list(inputs) + ["-i", str(path)]
    vol = max(0.0, min(1.0, float(volume)))
    dur = max(0.1, float(duration))
    fc += f";[{index}:a:0]volume={vol:.3f},atrim=duration={dur:.3f},asetpts=PTS-STARTPTS[voice]"
    mix = "amix=inputs=2:duration=first:dropout_transition=2:normalize=0,alimiter=limit=0.95[narrated]"
    if list(audio)[:2] == ["-map", "[mixout]"]:
        fc += f";[mixout][voice]{mix}"
    elif audio_map and cut:
        fc += f";[edited_audio][voice]{mix}"
    elif audio_map:
        fc += f";[0:a:0]loudnorm=I=-14:TP=-1.5:LRA=11[sourceaudio];[sourceaudio][voice]{mix}"
    else:
        fc += ";[voice]anull[narrated]"
    return fc, inputs, ["-map", "[narrated]"]


def _facecam_choice(src, start, layout, choice, width, height):
    if layout not in ("auto", "stack", "split") or choice in ("left", "right", "center"):
        return choice or "left"
    from .facecam import find_center
    center = find_center(src, start, width, height)
    return center or (None if layout == "auto" else "left")


def srt_to_vtt(srt_text: str) -> str:
    """Convert an SRT caption track into a valid WebVTT (.vtt) track."""
    if not srt_text or not srt_text.strip():
        return ""
    blocks = []
    for block in re.split(r"\n\s*\n", srt_text.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        if lines[0].isdigit():
            lines = lines[1:]
        if not lines:
            continue
        lines[0] = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", lines[0])
        blocks.append("\n".join(lines))
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def render_clip(src: Path, out_dir: Path, name: str, clip: dict, words: list, src_w: int, src_h: int) -> dict:
    """Render a vertical MP4 and write its cover, ASS track, and optional SRT/VTT."""
    out_dir.mkdir(parents=True, exist_ok=True)
    presets = studio_presets()
    start, end = clip["start"], clip["end"]
    segments = clip.get("segments") or []
    if not segments and (clip.get("trim_silence") or (clip.get("trim_silence") is not False and presets.get("quality_guard", {}).get("trim_silence"))):
        start, end = trim_dead_air(words, start, end, float(presets.get("quality_guard", {}).get("min_lead_pad") or 0.35))
    layout = clip.get("layout", "blur")
    facecam = _facecam_choice(src, segments[0]["start"] if segments else start,
                              layout, clip.get("facecam"), src_w, src_h)
    if layout == "auto":
        layout = "stack" if facecam else ("blur" if src_w > src_h else "crop")
    if layout == "split":
        layout = "stack"  # Convert old top-face layouts when re-rendered.
    clean = clip.get("captions") == "clean"
    motion = "none" if clean else (clip.get("motion") or "none")
    has_brand = not clean and bool(clip.get("brand") or motion == "highlight")
    branding = presets.get("branding") or {}
    wm_corner = clip.get("watermark_corner") or branding.get("watermark_corner", "top-left")
    safe_box = solve_safe_layout(
        src_w, src_h, layout,
        caption_position=clip.get("caption_position") or "bottom",
        has_hook=bool(not clean and (clip.get("hook") or "").strip()),
        has_brand=has_brand,
        has_lower_third=bool(not clean and motion == "lower_third"),
        watermark_corner=wm_corner,
    )
    layout = safe_box["layout"]
    fg_h = safe_box["foreground_height"]
    hook_y = safe_box["hook_y"]
    cap_y = safe_box["cap_y"]
    cues = clip.get("caption_cues")
    has_audio = clip.get("has_audio")
    if clip.get("music_path") and has_audio is None:
        has_audio = probe(src, require_audio=False)["has_audio"]
    if segments:
        words = editor.stitch_words(words, segments)
        if cues is not None:
            cues = [dict(c, start=c["start"] - start, end=c["end"] - start) for c in cues]
        start, end = 0, editor.cut_length(segments)
    sidecar = editor.srt(cues if cues is not None else editor.caption_cues(words, start, end), start, end)
    map_ov = clip.get("map_overlay")
    if map_ov is None and presets.get("map_overlay", {}).get("enabled"):
        map_ov = presets["map_overlay"].get("loc")
    cap_limit = clip.get("words_per_group") or (presets.get("captions") or {}).get("limit")
    cap_backing = clip.get("caption_backing", (presets.get("captions") or {}).get("backing", True))
    ass = build_ass([] if clean else words, start, end, "" if clean else clip.get("hook", ""),
                    clip.get("style", "bounce"), clip.get("highlight_words", []), hook_y, cap_y,
                    [] if clean else cues, motion,
                    watermark=not clean and clip.get("watermark", False),
                    brand=has_brand,
                    map_overlay=map_ov,
                    words_per_group=cap_limit,
                    brand_title=clip.get("brand_title") or branding.get("brand_title", "MJ PLAYS GTA"),
                    watermark_text=clip.get("watermark_text") or branding.get("watermark_text", "MJ"),
                    watermark_corner=safe_box["watermark_corner"],
                    watermark_opacity=clip.get("watermark_opacity") or branding.get("watermark_opacity", 88),
                    caption_backing=bool(cap_backing),
                    lower_third_y=safe_box["lower_third_y"])
    # The clip is made in a short work folder and moved into place afterwards. The caption step of ffmpeg cannot
    # open files whose full path is longer than 260 characters on Windows, which a data folder deep inside other
    # folders easily reaches. Inside the work folder every name is short and relative (a drive colon would also
    # break the filter syntax).
    work = Path(tempfile.mkdtemp(prefix="pk"))
    try:
        return _render_in(work, src, out_dir, name, start, end, layout, fg_h, ass, sidecar,
                          clip.get("crop_x", 0.5), clip.get("crop_y", 0.5), clean,
                          segments, has_audio, clip.get("crop_keyframes") or [], clip.get("music_path"),
                          clip.get("music_volume", 0.30), clip.get("music_duck", True),
                          clip.get("music_fade_in", 0.4), clip.get("music_fade_out", 0.8),
                          clip.get("music_offset", 0),
                          clip.get("commentary_path"), clip.get("commentary_volume", 1.0),
                          bool(clip.get("preserve_source_marks")), facecam, motion)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _cut_inputs(src, start, end, segments, has_audio):
    if not segments:
        return ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src)], "", "0:a:0?"
    if has_audio is None:
        has_audio = probe(src, require_audio=False)["has_audio"]
    inputs, filters, parts = [], [], []
    for i, part in enumerate(segments):
        inputs.extend(["-ss", f"{part['start']:.3f}", "-t", f"{part['end'] - part['start']:.3f}",
                       "-i", str(src)])
        speed = float(part.get("speed") or 1) or 1
        filters.append(f"[{i}:v]setpts=(PTS-STARTPTS)/{speed:.3f}[partv{i}]")
        parts.append(f"[partv{i}]")
        if has_audio:
            filters.append(f"[{i}:a:0]asetpts=PTS-STARTPTS,atempo={speed:.3f}[parta{i}]")
            parts.append(f"[parta{i}]")
    filters.append("".join(parts) + f"concat=n={len(segments)}:v=1:a={int(has_audio)}[edited]"
                   + ("[joined_audio]" if has_audio else ""))
    if has_audio:
        filters.append("[joined_audio]loudnorm=I=-14:TP=-1.5:LRA=11[edited_audio]")
    return inputs, ";".join(filters) + ";", "[edited_audio]" if has_audio else None


def _render_in(work: Path, src: Path, out_dir: Path, name: str, start, end, layout, fg_h, ass: str,
               sidecar, crop_x, crop_y, clean, segments, has_audio, keyframes,
               music_path=None, music_volume=0.30, music_duck=True, music_fade_in=0.4,
               music_fade_out=0.8, music_offset=0, commentary_path=None,
               commentary_volume=1.0, preserve_marks=False, facecam="left", motion="none") -> dict:
    global _qsv_ok
    (work / f"{name}.ass").write_text(ass, encoding="utf-8")
    (work / "f").mkdir()
    for f in config.FONTS_DIR.glob("*.ttf"):
        shutil.copyfile(f, work / "f" / f.name)
    inputs, cut, audio_map = _cut_inputs(src, start, end, segments, has_audio)
    fc = _filter(layout, fg_h, crop_x, crop_y, keyframes, preserve_marks, facecam, motion=motion).rstrip(";")
    if cut:
        fc = cut + fc.replace("[0:v]", "[edited]")
    if not clean:
        fc += f";[v0]ass={name}.ass:fontsdir=f[v]"
    audio = ["-map", audio_map] if audio_map else []
    if audio and not cut:
        audio.extend(["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"])
    if music_path:
        music_file = Path(music_path)
        if not music_file.is_file():
            raise RuntimeError("The selected background music file is missing.")
        audio_duration = max(0.1, end - start)
        music_index = inputs.count("-i")
        inputs.extend(["-stream_loop", "-1", "-i", str(music_file)])
        fade_in = max(0.0, min(5.0, float(music_fade_in or 0)))
        fade_out = max(0.0, min(5.0, float(music_fade_out or 0)))
        offset = max(0.0, float(music_offset or 0))
        chain = (f"volume={max(0.0, min(1.0, float(music_volume))):.3f},"
                 f"atrim=start={offset:.3f}:duration={audio_duration:.3f},asetpts=PTS-STARTPTS")
        if fade_in >= 0.05:
            chain += f",afade=t=in:st=0:d={min(fade_in, audio_duration / 2):.3f}"
        if fade_out >= 0.05:
            chain += f",afade=t=out:st={max(0.0, audio_duration - fade_out):.3f}:d={min(fade_out, audio_duration / 2):.3f}"
        fc += f";[{music_index}:a:0]{chain}[musicbed]"
        if audio_map:
            if not cut:
                fc += ";[0:a:0]loudnorm=I=-14:TP=-1.5:LRA=11[sourceaudio]"
            source_label = "edited_audio" if cut else "sourceaudio"
            if music_duck:
                fc += (f";[{source_label}]asplit=2[mainaudio][sidemeter]"
                       ";[musicbed][sidemeter]sidechaincompress=threshold=0.08:ratio=4:attack=25:release=450[duckedbed]"
                       ";[mainaudio][duckedbed]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
                       "alimiter=limit=0.95[mixout]")
            else:
                fc += (f";[{source_label}][musicbed]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
                       "alimiter=limit=0.95[mixout]")
        else:
            fc += ";[musicbed]anull[mixout]"
        audio = ["-map", "[mixout]"]
    fc, inputs, audio = apply_commentary(fc, inputs, audio, audio_map, bool(segments), commentary_path,
                                         max(0.1, end - start), commentary_volume)
    base = ["ffmpeg", "-y", "-v", "error", *inputs,
            "-filter_complex", fc, "-map", "[v0]" if clean else "[v]", *audio,
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", "-pix_fmt"]
    encoders = []
    # GPU Rendering: NVENC (NVIDIA), QSV (Intel), CPU (libx264 fallback)
    if config.GPU_RENDER in ("auto", "nvenc", "cuda"):
        encoders.append(("nvenc", ["yuv420p", "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]))
    if config.GPU_RENDER in ("auto", "qsv") and _qsv_ok is not False:
        encoders.append(("qsv", ["nv12", "-c:v", "h264_qsv", "-global_quality", "23", "-preset", "fast"]))
    encoders.append(("x264", ["yuv420p", "-c:v", "libx264", "-crf", "21", "-preset", "veryfast"]))
    err = None
    for label, enc in encoders:
        p = subprocess.run(base + enc + [f"{name}.mp4"], cwd=work, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=RENDER_SECONDS)
        if p.returncode == 0:
            if label == "qsv":
                _qsv_ok = True
            break
        err = p.stderr[-1200:]
        if label == "qsv":
            _qsv_ok = False
    else:
        raise RuntimeError(f"Render failed: {err}")
    # Verify rendered output dimensions and codec via media probing
    spec = probe(work / f"{name}.mp4", require_audio=False)
    if spec["width"] != W or spec["height"] != H:
        raise RuntimeError(f"Rendered clip dimensions ({spec['width']}x{spec['height']}) did not match {W}x{H}.")
    cover_t = min(1.2, (end - start) / 2)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{cover_t:.2f}", "-i", f"{name}.mp4", "-frames:v", "1",
         "-q:v", "3", f"{name}.jpg"], cwd=work)
    for ext in ("mp4", "jpg", "ass"):
        shutil.move(str(work / f"{name}.{ext}"), str(out_dir / f"{name}.{ext}"))
    srt_path = out_dir / f"{name}.srt"
    vtt_path = out_dir / f"{name}.vtt"
    if sidecar:
        srt_path.write_text(sidecar, encoding="utf-8")
        vtt_path.write_text(srt_to_vtt(sidecar), encoding="utf-8")
    else:
        srt_path.unlink(missing_ok=True)
        vtt_path.unlink(missing_ok=True)
    return {"file": f"{name}.mp4", "cover": f"{name}.jpg", "layout": layout, "duration": round(end - start, 3),
            "output_width": W, "output_height": H, "output_aspect": "9:16", "output_fps": config.OUT_FPS,
            "subtitle": srt_path.name if sidecar else None,
            "subtitle_vtt": vtt_path.name if sidecar else None}


def stitch_compilation(clip_paths: list[Path], out_path: Path) -> dict:
    """Stitches multiple vertical 9:16 clips into a single compilation video."""
    valid = [p for p in clip_paths if p.exists() and p.stat().st_size > 0]
    if not valid:
        raise ValueError("No valid clips provided for compilation")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_path.parent / f"_concat_{out_path.stem}.txt"
    try:
        content = "\n".join(f"file '{p.resolve().as_posix()}'" for p in valid)
        list_file.write_text(content, encoding="utf-8")
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
               "-i", str(list_file), "-c", "copy", str(out_path)]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW, timeout=300)
        if p.returncode != 0:
            # Re-encode fallback if stream copy fails
            reenc = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                     "-i", str(list_file), "-c:v", "libx264", "-crf", "22", "-preset", "veryfast",
                     "-c:a", "aac", "-b:a", "160k", str(out_path)]
            subprocess.run(reenc, check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        cover_path = out_path.with_suffix(".jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", str(out_path),
                        "-frames:v", "1", "-q:v", "3", str(cover_path)],
                       capture_output=True, creationflags=NO_WINDOW)
        return {"file": out_path.name, "cover": cover_path.name if cover_path.exists() else None,
                "count": len(valid), "size": out_path.stat().st_size}
    finally:
        list_file.unlink(missing_ok=True)

