"""Talking to the AI service. You bring your own key, and choose the service and model in the dashboard
(Settings, AI) or in .env. What is saved from the dashboard is kept in ai.json in the data folder and wins.

    PEAKCUT_AI_PROVIDER   gemini | openai | xai | groq | openrouter | anthropic | ollama | custom
    PEAKCUT_AI_MODELS     one or more model ids, comma separated, tried in this order
    PEAKCUT_AI_KEY        your key (or PEAKCUT_AI_KEY_FILE, a file holding it)
    PEAKCUT_AI_BASE_URL   only for "custom" (any service that speaks the OpenAI chat format), or to override

Every service is asked for the same thing: JSON that follows a small schema. Gemini takes the schema directly.
The others are told the schema in the prompt and asked for a JSON object, which works with any chat model."""
from contextlib import contextmanager
from contextvars import ContextVar
from email.utils import parsedate_to_datetime
import json
import os
import re
import secrets
import threading
import time

from urllib.parse import urlsplit

import httpx

from . import config

# name -> (label shown on the pages, address, how it is spoken to, where to get a key, an example model id)
PROVIDERS = {
    "gemini": ("Gemini", "https://generativelanguage.googleapis.com/v1beta/models", "gemini", "https://aistudio.google.com/apikey", "gemini-2.5-flash"),
    "openai": ("OpenAI", "https://api.openai.com/v1", "openai", "https://platform.openai.com/api-keys", "gpt-4o-mini"),
    "xai": ("Grok", "https://api.x.ai/v1", "openai", "https://console.x.ai", "grok-4"),
    "groq": ("Groq", "https://api.groq.com/openai/v1", "openai", "https://console.groq.com/keys", "llama-3.3-70b-versatile"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "openai", "https://openrouter.ai/keys", "google/gemini-2.5-flash"),
    "openrouter-free": ("OpenRouter Free", "https://openrouter.ai/api/v1", "openai", "https://openrouter.ai/keys", "openrouter/free"),
    "zai": ("Z.AI (GLM)", "https://api.z.ai/api/paas/v4", "openai", "https://z.ai/manage-apikey/apikey-list", "glm-4.7-flash"),
    "qwen": ("Alibaba Model Studio (Qwen)", "", "openai", "", ""),
    "deepseek": ("DeepSeek", "https://api.deepseek.com", "openai", "https://platform.deepseek.com/api_keys", ""),
    "anthropic": ("Claude", "https://api.anthropic.com/v1", "anthropic", "https://console.anthropic.com", ""),
    "ollama": ("Ollama (on this machine)", "http://127.0.0.1:11434/v1", "openai", "https://ollama.com", "llama3.1"),
    "custom": ("Custom (OpenAI-compatible)", "", "openai", "", ""),
}
ALIASES = {"google": "gemini", "grok": "xai", "claude": "anthropic", "local": "ollama"}
NO_KEY = {"ollama", "custom"}       # a model running on your own machine needs no key
FIXED_ADDRESS = {"openrouter-free"}
AI_REQUEST_TIMEOUT = 45


def _free_model(model):
    return model == "openrouter/free" or model.endswith(":free")

# ---------------------------------------------------------------- the settings in use
_lock = threading.RLock()
_in_use = ContextVar('ai_profile', default=None)
_cooldown_file = config.DATA_DIR / "ai-cooldowns.json"
try:
    _cooldowns = json.loads(_cooldown_file.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _cooldowns = {}
_saved = {"at": None, "data": {}}
_health: dict = {}          # profile_id -> {"requires_config": bool, "error_kind": str, "reason": str, "at": float}
_semaphores: dict = {}      # service_family -> BoundedSemaphore
_clock = {"now": time.time, "sleep": time.sleep}

MAX_PROVIDERS_PER_ROUND = 3
ROUND_DELAYS = (5, 10, 15)  # 4 rounds total: Round 0 (0s), Round 1 (+5s), Round 2 (+10s), Round 3 (+15s)
MAX_REQUESTS_PER_OP = 12    # 3 providers/round * 4 rounds ceiling
LIVE_OP_DEADLINE = 55.0
OFFLINE_OP_DEADLINE = 180.0


def _now() -> float:
    return float(_clock["now"]())


def _sleep(seconds: float, cancel_event=None) -> bool:
    """Sleep for `seconds` using the active clock; returns False if cancelled during the wait."""
    if seconds <= 0:
        return not (cancel_event and cancel_event.is_set())
    if cancel_event is not None:
        if _clock["sleep"] is time.sleep:
            if cancel_event.wait(timeout=seconds):
                return False
            return not cancel_event.is_set()
        # Fake clock in tests: step in 1s increments or directly check cancel_event
        step = min(1.0, seconds)
        rem = float(seconds)
        while rem > 0:
            if cancel_event.is_set():
                return False
            dt = min(step, rem)
            _clock["sleep"](dt)
            rem -= dt
        return not cancel_event.is_set()
    _clock["sleep"](seconds)
    return True


def _file():
    return config.DATA_DIR / "ai.json"


def _from_dashboard() -> dict:
    """What was saved from the dashboard, read again only when the file changes."""
    f = _file()
    try:
        at = f.stat().st_mtime_ns
    except OSError:
        at = 0
    if _saved["at"] != at:
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if at else {}
        except (OSError, ValueError):
            data = {}
        _saved.update(at=at, data=data if isinstance(data, dict) else {})
    return _saved["data"]


def _normalize_profile(p: dict, idx: int = 0) -> dict:
    prov = ALIASES.get(str(p.get("provider") or "").strip().lower(), str(p.get("provider") or "").strip().lower())
    return {
        "id": str(p.get("id") or f"prof_{idx + 1}"),
        "name": str(p.get("name") or PROVIDERS.get(prov, (prov or "Primary",))[0]),
        "provider": prov,
        "models": list(p.get("models") or []),
        "base_url": str(p.get("base_url") or "").rstrip("/"),
        "key": str(p.get("key") or ""),
        "fallback": bool(p.get("fallback", False)),
        "order": int(p.get("order", idx + 1)),
        "enabled": bool(p.get("enabled", True)),
        "is_local": bool(p.get("is_local", prov in ("ollama", "custom"))),
        "allow_clip_text": bool(p.get("allow_clip_text", True)),
        "max_concurrency": max(1, min(16, int(p.get("max_concurrency", 2)))),
    }


def _profiles() -> list:
    data = _from_dashboard()
    if isinstance(data.get("profiles"), list) and data["profiles"]:
        rows = [_normalize_profile(p, i) for i, p in enumerate(data["profiles"]) if isinstance(p, dict)]
        rows.sort(key=lambda r: r.get("order", 999))
        return rows
    p = str(data.get("provider") or config.AI_PROVIDER or "").strip().lower()
    prov = ALIASES.get(p, p)
    return [_normalize_profile({
        "id": "primary", "name": "Primary", "provider": prov,
        "models": list(data.get("models") or []) if data.get("provider") else list(config.AI_MODELS),
        "base_url": str(data.get("base_url") or "").rstrip("/") if data.get("provider") else config.AI_BASE_URL,
        "key": str(data.get("key", config.ai_key())) if data.get("provider") else config.ai_key(),
        "fallback": False, "order": 1, "enabled": True,
        "is_local": prov in ("ollama", "custom"), "allow_clip_text": True
    }, 0)]


def current() -> dict:
    active = _in_use.get()
    if active is not None:
        return active
    rows = _profiles()
    return next((p for p in rows if p["id"] == _from_dashboard().get("active")), rows[0])


@contextmanager
def use(profile):
    token = _in_use.set(profile)
    try:
        yield
    finally:
        _in_use.reset(token)


def service(profile):
    """Two model or key profiles at the same service share one retry boundary."""
    name = profile["provider"]
    host = (urlsplit(profile["base_url"] or PROVIDERS.get(name, ("", ""))[1]).hostname or "").lower()
    if name not in ("custom", "ollama"):
        return {"openrouter-free": "openrouter"}.get(name, name)
    for provider_id, row in PROVIDERS.items():
        if provider_id not in ("custom", "ollama") and host and urlsplit(row[1]).hostname == host:
            return {"openrouter-free": "openrouter"}.get(provider_id, provider_id)
    return host or name


def _ordered_distinct_profiles(carries_clip_text: bool = False) -> list:
    """Return up to MAX_PROVIDERS_PER_ROUND distinct-service profiles eligible to be considered."""
    primary = current()
    all_profiles = _profiles()
    ordered = [primary] + [p for p in all_profiles if p.get("fallback") and p["id"] != primary["id"]]
    seen = set()
    out = []
    for p in ordered:
        if not p.get("enabled", True) or p["provider"] not in PROVIDERS:
            continue
        if carries_clip_text and not p.get("allow_clip_text", True):
            continue
        if _health.get(p["id"], {}).get("requires_config"):
            continue
        family = service(p)
        if family in seen:
            continue
        with use(p):
            is_ready = ready()
        if not is_ready:
            continue
        seen.add(family)
        out.append(p)
        if len(out) >= MAX_PROVIDERS_PER_ROUND:
            break
    return out


def attempts(carries_clip_text: bool = False):
    for p in _ordered_distinct_profiles(carries_clip_text=carries_clip_text):
        with use(p):
            if not cooling(p):
                yield p


def can_answer() -> bool:
    """Whether the active profile or an opted-in independent backup can answer now."""
    return next(attempts(), None) is not None


def cooldown_until(profile=None) -> float:
    with _lock:
        if not _cooldowns and _cooldown_file.exists():
            try:
                _cooldowns.update(json.loads(_cooldown_file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        target = profile or current()
        return float(_cooldowns.get(service(target), 0) or 0)


def cooling(profile=None) -> bool:
    return cooldown_until(profile) > _now()


def set_cooldown(profile, delay_seconds: float):
    with _lock:
        family = service(profile)
        until = _now() + max(1.0, float(delay_seconds))
        _cooldowns[family] = max(_cooldowns.get(family, 0), until)
        try:
            tmp = _cooldown_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(_cooldowns), encoding="utf-8")
            tmp.replace(_cooldown_file)
        except OSError:
            pass
        return _cooldowns[family]


def retry_delay(headers, default):
    raw = (headers or {}).get("retry-after", (headers or {}).get("Retry-After", ""))
    try:
        return max(1, int(float(raw)))
    except (ValueError, TypeError):
        try:
            return max(1, int(parsedate_to_datetime(raw).timestamp() - _now()))
        except (ValueError, TypeError, OverflowError):
            return default


def provider() -> str:
    return current()["provider"]


def models() -> list:
    return current()["models"]


def key() -> str:
    return current()["key"]


def label() -> str:
    return PROVIDERS.get(provider(), ("",))[0]


def base_url() -> str:
    c = current()
    default = PROVIDERS.get(c["provider"], ("", ""))[1]
    return default if c["provider"] in FIXED_ADDRESS else c["base_url"] or default


def ready() -> bool:
    c = current()
    return bool(c["provider"] in PROVIDERS and c["models"] and base_url() and (c["key"] or c["provider"] in NO_KEY)
                and (c["provider"] != "openrouter-free" or all(_free_model(m) for m in c["models"])))


def redact_text(text: str, raw_secret: str = "") -> str:
    out = str(text or "")
    for p in _profiles():
        if p.get("key") and len(p["key"]) >= 6:
            out = out.replace(p["key"], "<redacted>")
    if raw_secret and len(raw_secret) >= 6:
        out = out.replace(raw_secret, "<redacted>")
    return out


def _summary(c):
    with use(c):
        h = _health.get(c["id"], {})
        cd_until = cooldown_until(c) if ready() else 0.0
        now = _now()
        return {k: c[k] for k in ("id", "name", "provider", "models", "base_url", "fallback")} | {
            "order": c.get("order", 1),
            "enabled": c.get("enabled", True),
            "is_local": c.get("is_local", c["provider"] in ("ollama", "custom")),
            "allow_clip_text": c.get("allow_clip_text", True),
            "has_key": bool(c["key"]),
            "key_hint": c["key"][-4:] if len(c["key"]) >= 12 else "",
            "ready": ready(),
            "cooling": cd_until > now if ready() else False,
            "next_eligible_at": round(cd_until, 2) if cd_until > now else 0,
            "requires_config": bool(h.get("requires_config", False)),
            "last_error_kind": h.get("error_kind", ""),
            "last_reason": redact_text(h.get("reason", ""), c.get("key", "")),
            "label": label(),
        }


def public() -> dict:
    dash = _from_dashboard()
    return {
        **_summary(current()),
        "saved_here": bool(dash),
        "promote_healthy_globally": bool(dash.get("promote_healthy_globally", False)),
        "profiles": [_summary(p) for p in _profiles()],
        "providers": [
            {"id": k, "label": v[0], "address": v[1], "needs_key": k not in NO_KEY, "key_url": v[3], "example": v[4]}
            for k, v in PROVIDERS.items()
        ],
    }


def _write_profiles(rows, active, promote_healthy_globally=None):
    f = _file()
    tmp = f.with_suffix(".tmp")
    for idx, r in enumerate(rows):
        r["order"] = idx + 1
    primary = next((row for row in rows if row["id"] == active), rows[0])
    dash = _from_dashboard()
    promote = dash.get("promote_healthy_globally", False) if promote_healthy_globally is None else bool(promote_healthy_globally)
    data = {k: primary[k] for k in ("provider", "models", "base_url", "key")}
    tmp.write_text(json.dumps({**data, "profiles": rows, "active": active, "promote_healthy_globally": promote}), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(f)
    _saved["at"] = None


def manage(profile_id, action):
    with _lock:
        rows = _profiles()
        idx = next((i for i, p in enumerate(rows) if p["id"] == profile_id), None)
        if idx is None:
            raise ValueError("That AI profile no longer exists.")
        active = current()["id"]
        if action == "activate":
            active = profile_id
            _health.pop(profile_id, None)
        elif action == "move_up" and idx > 0:
            rows[idx - 1], rows[idx] = rows[idx], rows[idx - 1]
        elif action == "move_down" and idx + 1 < len(rows):
            rows[idx + 1], rows[idx] = rows[idx], rows[idx + 1]
        elif action == "toggle_clip_text":
            rows[idx]["allow_clip_text"] = not rows[idx].get("allow_clip_text", True)
        elif action == "clear_error":
            _health.pop(profile_id, None)
            _cooldowns.pop(service(rows[idx]), None)
        elif action == "delete":
            if len(rows) == 1:
                raise ValueError("Save another profile before deleting this one.")
            rows = [p for p in rows if p["id"] != profile_id]
            _health.pop(profile_id, None)
            if active == profile_id:
                active = rows[0]["id"]
        else:
            raise ValueError("Unknown profile action.")
        _write_profiles(rows, active)
    return public()


def save(provider_id: str, model_ids, address: str = "", new_key=None, *, profile_id=None,
         name=None, fallback=None, allow_clip_text=None, is_local=None, order=None,
         promote_healthy_globally=None) -> dict:
    p = ALIASES.get(str(provider_id or "").strip().lower(), str(provider_id or "").strip().lower())
    if p not in PROVIDERS:
        raise ValueError("Choose one of the AI services in the list.")
    if isinstance(model_ids, str):
        model_ids = model_ids.split(",")
    ms = [str(m).strip()[:120] for m in (model_ids or []) if str(m).strip()][:5]
    if not ms:
        raise ValueError("Enter the model to use.")
    if any(not re.fullmatch(r"[\w.\-:/@]+", m) for m in ms):
        raise ValueError("A model id has letters, digits and . - : / only.")
    address = str(address or "").strip().rstrip("/")[:300]
    if address and not re.fullmatch(r"https?://[^\s]+", address):
        raise ValueError("The address has to start with http:// or https://")
    if p == "openrouter-free":
        if not all(_free_model(model) for model in ms):
            raise ValueError("Use openrouter/free or a model whose ID ends in :free.")
        address = ""
    if p in ("custom", "qwen") and not address:
        raise ValueError("Enter your workspace's OpenAI-compatible address." if p == "qwen"
                         else "A custom service needs its address, for example http://127.0.0.1:1234/v1")
    with _lock:
        rows = _profiles()
        active = current()["id"]
        old = next((row for row in rows if row["id"] == (profile_id or active)), None)
        if old is None and profile_id != "new":
            raise ValueError("That AI profile no longer exists.")
        if old is None and len(rows) >= 12:
            raise ValueError("You can save up to 12 AI profiles.")
        k = (old["key"] if new_key is None and old and old["provider"] == p and old["base_url"] == address
             else str(new_key or "").strip()[:400])
        if not k and p not in NO_KEY:
            raise ValueError("Paste a key for this profile and address.")
        row_id = old["id"] if old else secrets.token_hex(8)
        _health.pop(row_id, None)
        row = {
            "id": row_id,
            "provider": p,
            "models": ms,
            "base_url": address,
            "key": k,
            "name": (str(name or "").strip()[:64] or (old["name"] if old else PROVIDERS[p][0])),
            "fallback": (old or {}).get("fallback", False) if fallback is None else bool(fallback),
            "allow_clip_text": (old or {}).get("allow_clip_text", True) if allow_clip_text is None else bool(allow_clip_text),
            "is_local": (p in ("ollama", "custom")) if is_local is None else bool(is_local),
            "order": int(order) if order is not None else (old or {}).get("order", len(rows) + 1),
            "enabled": True,
        }
        rows = [row if old is other else other for other in rows] if old else [*rows, row]
        if order is not None:
            rows.sort(key=lambda r: r.get("order", 999))
        _write_profiles(rows, active if any(r["id"] == active and r["provider"] for r in rows) else row["id"],
                        promote_healthy_globally=promote_healthy_globally)
    return public()


def list_models(provider_id=None, address=None, with_key=None, profile_id=None) -> list:
    """The model ids a service offers, so the settings page can show a list to pick from."""
    c = next((row for row in _profiles() if row["id"] == profile_id), {}) if profile_id else current()
    c = c or {"provider": "", "key": "", "base_url": ""}
    p = ALIASES.get(str(provider_id or c["provider"]).lower(), str(provider_id or c["provider"]).lower())
    if p not in PROVIDERS:
        raise ValueError("Choose one of the AI services in the list.")
    base = str(address if address is not None else c["base_url"] if c["provider"] == p else "").strip().rstrip("/") or PROVIDERS[p][1]
    k = str(with_key or "").strip() or (c["key"] if c["provider"] == p and (c["base_url"] or PROVIDERS[p][1]) == base else "")
    if p in FIXED_ADDRESS:
        base = PROVIDERS[p][1]
    if p == "zai" and base == PROVIDERS[p][1]:
        return ["glm-4.7-flash", "glm-4.5-flash"]
    if not base:
        raise ValueError("Enter the service's address first.")
    how = PROVIDERS[p][2]
    if how == "gemini":
        r = httpx.get(base, params={"pageSize": 200}, headers={"x-goog-api-key": k}, timeout=20)
    elif how == "anthropic":
        r = httpx.get(f"{base}/models", params={"limit": 200}, headers={"x-api-key": k, "anthropic-version": "2023-06-01"}, timeout=20)
    else:
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {k}"} if k else {}, timeout=20)
    if r.status_code != 200:
        raise AIError(f"HTTP {r.status_code} {r.text[:200].replace(k or chr(0), '<key>')}")
    data = r.json()
    if how == "gemini":
        found = [m.get("name", "").split("/")[-1] for m in data.get("models", [])
                 if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    else:
        found = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
    if p == "openrouter-free":
        return ["openrouter/free", *sorted({m for m in found if m.endswith(":free")})[:399]]
    return sorted({m for m in found if m})[:400]


def test(profile_id=None) -> dict:
    row = next((p for p in _profiles() if p["id"] == profile_id), None) if profile_id else current()
    if not row:
        raise ValueError("Save the AI profile first.")
    with use(row):
        try:
            return _test()
        except AIError as e:
            raise AIError(explain(e) or "Check the saved model and provider connection.", status=e.status) from None


def _test() -> dict:
    """One tiny request with the settings in use, to prove the key, the address and the model all work."""
    ms = models()
    if not ready():
        raise ValueError("Save a service, a model and a key first.")
    if cooling():
        raise ValueError("This AI provider is waiting for its rate-limit cooldown.")
    out, sent, wrote = call(ms[0], 'Answer with a JSON array that holds the single string "ok".', {"type": "ARRAY", "items": {"type": "STRING"}})
    return {"ok": True, "model": ms[0], "tokens": sent + wrote, "answer": str(out)[:80]}


class AIError(RuntimeError):
    def __init__(self, message, status=0, error_kind="", retry_after=None, body_text=""):
        super().__init__(message)
        self.status = status
        self.error_kind = error_kind
        self.retry_after = retry_after
        self.body_text = body_text


class AIWaitError(AIError):
    """Raised after bounded retry rounds complete without an eligible or answering provider."""
    def __init__(self, message, *, earliest_retry_at=0.0, attempts_log=None, error_kind="rate_limit"):
        super().__init__(message, status=429, error_kind=error_kind)
        self.earliest_retry_at = float(earliest_retry_at or 0.0)
        self.attempts_log = list(attempts_log or [])


problem = {"text": "", "at": 0.0}       # why the AI last failed, for the dashboard; cleared when it answers again


def classify_error(exc, status: int = 0, body_text: str = "") -> str:
    """Classify an AI error into distinct operational buckets."""
    status = status or getattr(exc, "status", 0) or 0
    existing = getattr(exc, "error_kind", "")
    if existing:
        return existing
    raw = f"{exc} {body_text}".lower()
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)) or "timed out" in raw or "timeout" in raw:
        return "network_timeout"
    if isinstance(exc, httpx.TransportError) or any(k in raw for k in ("connect", "getaddrinfo", "dns", "refused", "reset", "network")):
        return "network_transient"
    if status == 402 or any(k in raw for k in ("insufficient_quota", "credit", "billing", "free-tier", "balance", "payment")):
        return "credits_exhausted"
    if status in (401, 403) or any(k in raw for k in ("api key", "api_key", "unauthorized", "invalid_api_key", "authentication", "permission_denied")):
        return "auth_invalid"
    if status == 404 or any(k in raw for k in ("not found", "does not exist", "unknown model", "not_found", "model_not_found")):
        return "model_invalid"
    if status == 429 or any(k in raw for k in ("rate limit", "rate_limit", "resource_exhausted", "too many requests", "quota")):
        return "rate_limit"
    if "did not answer with json" in raw or isinstance(exc, (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError)):
        return "malformed_output"
    if status >= 500:
        return "server_transient"
    return "permanent_error"


def explain(e) -> str:
    """What went wrong with an AI call, in words the owner can act on."""
    text, low = redact_text(str(e)), redact_text(str(e)).lower()
    name = (models() or ["?"])[0]
    kind = classify_error(e)
    if kind == "model_invalid" or "404" in text or "not found" in low or "does not exist" in low or "unknown model" in low or "not_found" in low:
        return f"{label()} doesn't know the model \"{name}\". Open Settings, AI, press Find models and pick one from the list."
    if kind == "auth_invalid" or "401" in text or "403" in text or "api key" in low or "api_key" in low or "unauthorized" in low or "permission" in low:
        return f"{label()} refused the key. Paste a working key under Settings, AI."
    if kind in ("rate_limit", "credits_exhausted") or "429" in text or "quota" in low or "rate limit" in low or "exhausted" in low:
        return f"{label()} says the key has hit its limit or has no credit left. Check the account with {label()}, or try again later."
    if kind in ("network_timeout", "network_transient") or "connect" in low or "timed out" in low or "timeout" in low or "getaddrinfo" in low or "refused" in low:
        return f"PeakCut couldn't reach {label()}. Check the internet connection" + (" and that Ollama is running." if provider() == "ollama" else ".")
    return ""


def note_problem(e):
    why = explain(e)
    if why:
        problem.update(text=why, at=_now())


def clear_problem():
    problem.update(text="", at=0.0)


def _extract_retry_after(headers: dict) -> float | None:
    if not headers:
        return None
    for k in ("retry-after", "Retry-After", "x-ratelimit-reset-after", "X-RateLimit-Reset-After"):
        if k in headers and str(headers[k]).strip():
            delay = retry_delay({"retry-after": headers[k]}, None)
            if delay is not None:
                return float(delay)
    return None


def _fail(r, model):
    headers = getattr(r, "headers", {}) or {}
    body_text = (getattr(r, "text", "") or "")[:400]
    explicit_ra = _extract_retry_after(headers)
    kind = classify_error(None, status=r.status_code, body_text=body_text)
    if r.status_code == 429 or kind == "credits_exhausted" or (r.status_code >= 500 and explicit_ra is not None):
        delay = explicit_ra if explicit_ra is not None else 900.0
        set_cooldown(current(), delay)
    raise AIError(
        f"HTTP {r.status_code} for model {model}",
        status=r.status_code,
        error_kind=kind,
        retry_after=explicit_ra,
        body_text=redact_text(body_text),
    )


def _service_semaphore(profile) -> threading.BoundedSemaphore:
    family = service(profile)
    with _lock:
        sem = _semaphores.get(family)
        if sem is None:
            sem = _semaphores[family] = threading.BoundedSemaphore(max(1, int(profile.get("max_concurrency", 2))))
        return sem


def execute_with_failover(prompt: str, schema: dict | None = None, *, carries_clip_text: bool = True,
                          is_live: bool = False, cancel_event=None, cancel_check=None, call_fn=None) -> tuple:
    """Execute an AI schema call with sensitive provider switching and bounded retries.

    Contract:
    - Up to 3 eligible, distinct providers per round.
    - Immediate failover (0s) within a round on transient/rate-limit/credit errors.
    - Up to 3 additional rounds with 5s, 10s, and 15s delays between rounds (4 rounds total).
    - Maximum 12 requests per operation, bounded by operation deadline and per-request timeout.
    - Respects explicit Retry-After / reset times per provider; never calls a provider before its due time.
    - Marks invalid credentials (401/403) or unsupported models (404) as requires_config.
    - Retries malformed JSON output once on the same provider within the 12-request budget.
    """
    invoke = call_fn or call
    schema = schema or {}
    start_t = _now()
    deadline = start_t + (LIVE_OP_DEADLINE if is_live else OFFLINE_OP_DEADLINE)
    total_calls = 0
    attempts_log = []
    last_why = ""
    last_kind = "rate_limit"
    primary_id = current()["id"]
    transient_no_header_families = set()
    is_cancelled = lambda: bool((cancel_event is not None and cancel_event.is_set()) or (cancel_check is not None and cancel_check()))

    for round_idx in range(len(ROUND_DELAYS) + 1):
        if is_cancelled():
            raise AIWaitError("Operation cancelled during AI retry wait.", earliest_retry_at=0.0,
                              attempts_log=attempts_log, error_kind="cancelled")
        now = _now()
        if now >= deadline or total_calls >= MAX_REQUESTS_PER_OP:
            break

        # Gather up to 3 distinct providers configured for this operation
        candidates = _ordered_distinct_profiles(carries_clip_text=carries_clip_text)
        if not candidates:
            break

        round_tried_any = False
        for prof in candidates:
            if is_cancelled():
                raise AIWaitError("Operation cancelled.", earliest_retry_at=0.0,
                                  attempts_log=attempts_log, error_kind="cancelled")
            now = _now()
            if now >= deadline or total_calls >= MAX_REQUESTS_PER_OP:
                break
            family = service(prof)
            cd_until = cooldown_until(prof)
            # If the provider is in an explicit Retry-After cooldown (not a transient no-header retry within this op), skip it
            if cd_until > now and family not in transient_no_header_families:
                continue

            round_tried_any = True
            sem = _service_semaphore(prof)
            sem.acquire()
            try:
                with use(prof):
                    prof_models = prof["models"] or [""]
                    all_models_404 = True
                    for model in prof_models:
                        if total_calls >= MAX_REQUESTS_PER_OP or _now() >= deadline:
                            break
                        malformed_retries = 0
                        while total_calls < MAX_REQUESTS_PER_OP and _now() < deadline:
                            total_calls += 1
                            attempt_rec = {
                                "round": round_idx,
                                "profile_id": prof["id"],
                                "provider": prof["provider"],
                                "service": family,
                                "model": model,
                                "at": round(_now() - start_t, 3),
                            }
                            try:
                                out, sent, wrote = invoke(model, prompt, schema)
                                if not isinstance(out, (list, dict)):
                                    raise AIError("The AI did not return a JSON object or array.", error_kind="malformed_output")
                                attempt_rec["status"] = "ok"
                                attempts_log.append(attempt_rec)
                                _health.pop(prof["id"], None)
                                if family in transient_no_header_families:
                                    transient_no_header_families.discard(family)
                                    with _lock:
                                        _cooldowns.pop(family, None)
                                if prof["id"] != primary_id and _from_dashboard().get("promote_healthy_globally"):
                                    manage(prof["id"], "activate")
                                clear_problem()
                                route_note = ""
                                if prof["id"] != primary_id or round_idx > 0 or len(attempts_log) > 1:
                                    route_note = f"Answered by {label()} ({model}) on round {round_idx + 1} after {len(attempts_log) - 1} fallback attempt(s)."
                                return out, model, sent, wrote, {
                                    "profile_id": prof["id"],
                                    "provider": prof["provider"],
                                    "label": label(),
                                    "round": round_idx,
                                    "attempts": attempts_log,
                                    "route_note": route_note,
                                }
                            except (AIError, httpx.TransportError, ValueError, KeyError, IndexError, TypeError, RuntimeError) as exc:
                                status = getattr(exc, "status", 0)
                                kind = classify_error(exc, status=status)
                                last_kind = kind
                                last_why = explain(exc) or redact_text(f"{label()} could not answer with {model}: {exc}")
                                attempt_rec.update(status="error", error_kind=kind, reason=last_why)
                                attempts_log.append(attempt_rec)
                                _health[prof["id"]] = {
                                    "requires_config": kind in ("auth_invalid",),
                                    "error_kind": kind,
                                    "reason": last_why,
                                    "at": _now(),
                                }

                                if kind == "malformed_output":
                                    all_models_404 = False
                                    if malformed_retries < 1 and total_calls < MAX_REQUESTS_PER_OP:
                                        malformed_retries += 1
                                        continue
                                    break  # move to next model or provider

                                if kind == "model_invalid" or status in (400, 404, 422):
                                    break  # try next model on this profile

                                all_models_404 = False
                                if kind == "auth_invalid":
                                    _health[prof["id"]]["requires_config"] = True
                                    break  # skip remaining models on dead key

                                if kind in ("rate_limit", "credits_exhausted", "server_transient", "network_timeout", "network_transient"):
                                    ra = getattr(exc, "retry_after", None)
                                    if ra is not None:
                                        transient_no_header_families.discard(family)
                                        set_cooldown(prof, ra)
                                    else:
                                        # Allow the next round (5s/10s/15s) in this operation to re-test if needed,
                                        # while recording a post-op cooldown if all rounds fail.
                                        transient_no_header_families.add(family)
                                    break  # immediate switch (0s) to next distinct provider in this round

                                break
                        else:
                            continue
                        if _health.get(prof["id"], {}).get("requires_config") or last_kind in (
                            "rate_limit", "credits_exhausted", "server_transient", "network_timeout", "network_transient"
                        ):
                            break
                    if all_models_404 and prof_models:
                        _health[prof["id"]] = {
                            "requires_config": True,
                            "error_kind": "model_invalid",
                            "reason": last_why or f"{label()} rejected configured models.",
                            "at": _now(),
                        }
            finally:
                sem.release()

        # End of round: decide whether another round is permitted
        if round_idx >= len(ROUND_DELAYS) or total_calls >= MAX_REQUESTS_PER_OP:
            break
        wait_sec = ROUND_DELAYS[round_idx]
        now = _now()
        if now + wait_sec >= deadline:
            break
        # Check if any candidate could possibly be eligible in a future round
        remaining_candidates = _ordered_distinct_profiles(carries_clip_text=carries_clip_text)
        if not remaining_candidates:
            break
        future_horizon = start_t + sum(ROUND_DELAYS[round_idx:])
        any_eligible_soon = any(
            (service(p) in transient_no_header_families) or (cooldown_until(p) <= max(now + wait_sec, min(deadline, future_horizon)))
            for p in remaining_candidates
        )
        if not round_tried_any and not any_eligible_soon:
            break
        if is_cancelled() or not _sleep(wait_sec, cancel_event=cancel_event):
            raise AIWaitError("Operation cancelled during AI retry wait.", earliest_retry_at=0.0,
                              attempts_log=attempts_log, error_kind="cancelled")

    # Apply cooldown for any provider that failed transiently without an explicit Retry-After header
    now = _now()
    for p in _profiles():
        fam = service(p)
        if fam in transient_no_header_families and cooldown_until(p) <= now:
            set_cooldown(p, 60.0)

    future_dues = [cooldown_until(p) for p in _ordered_distinct_profiles(carries_clip_text=carries_clip_text) if cooldown_until(p) > now]
    earliest = min(future_dues) if future_dues else (now + 60.0 if attempts_log else 0.0)
    last_why = last_why or "Save a working profile in Settings, AI."
    problem.update(text=last_why, at=now)
    raise AIWaitError(
        f"The AI did not answer: {last_why}",
        earliest_retry_at=earliest,
        attempts_log=attempts_log,
        error_kind=last_kind,
    )


# ---------------------------------------------------------------- the schema, said in words for chat models
def _json_schema(s):
    """Gemini's schema spelling (ARRAY, OBJECT...) as ordinary JSON Schema."""
    if isinstance(s, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _json_schema(v)) for k, v in s.items()}
    if isinstance(s, list):
        return [_json_schema(x) for x in s]
    return s


def _wrapped(prompt, schema):
    return (prompt + "\n\nAnswer with JSON only, no other text and no code fences: one object with a single key "
            "\"items\", whose value follows this JSON Schema:\n" + json.dumps(_json_schema(schema)))


def _parse(text):
    """The JSON in an answer, even if the model wrapped it in a code fence or a sentence."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        out = json.loads(text)
    except ValueError:
        m = re.search(r"[\[{].*[\]}]", text, re.S)
        if not m:
            raise AIError("The AI did not answer with JSON.", error_kind="malformed_output")
        try:
            out = json.loads(m.group(0))
        except ValueError as exc:
            raise AIError("The AI did not answer with JSON.", error_kind="malformed_output") from exc
    if isinstance(out, dict) and "items" in out:
        out = out["items"]
    return out


# ---------------------------------------------------------------- one call
def call(model: str, prompt: str, schema: dict):
    """Ask one model. Returns (the parsed JSON answer, tokens sent, tokens written back)."""
    how = PROVIDERS[provider()][2]
    return {"gemini": _gemini, "openai": _openai, "anthropic": _anthropic}[how](model, prompt, schema)


def _gemini(model, prompt, schema):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json", "responseSchema": schema}}
    r = httpx.post(f"{base_url()}/{model}:generateContent", json=body, headers={"x-goog-api-key": key()}, timeout=AI_REQUEST_TIMEOUT)
    if r.status_code != 200:
        _fail(r, model)
    data = r.json()
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        parsed = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AIError("The AI did not answer with JSON.", error_kind="malformed_output") from exc
    u = data.get("usageMetadata", {})
    sent = int(u.get("promptTokenCount") or 0)
    return parsed, sent, max(0, int(u.get("totalTokenCount") or 0) - sent)   # the answer, and any thinking billed with it


def _openai(model, prompt, schema):
    headers = {"Authorization": f"Bearer {key()}"} if key() else {}
    body = {"model": model, "messages": [{"role": "user", "content": _wrapped(prompt, schema)}]}
    if provider() == "openrouter-free":
        if not _free_model(model):
            raise AIError("This model is outside the OpenRouter Free selection.")
        body["provider"] = {"max_price": {"prompt": 0, "completion": 0, "request": 0}}
    # Most services accept these two extras; a few models refuse one of them, so they are dropped on a refusal.
    extras = [{"temperature": 0.4, "response_format": {"type": "json_object"}}, {"response_format": {"type": "json_object"}}, {}]
    r = None
    for extra in extras:
        r = httpx.post(f"{base_url()}/chat/completions", json={**body, **extra}, headers=headers, timeout=AI_REQUEST_TIMEOUT)
        if r.status_code not in (400, 422):
            break
    if r.status_code != 200:
        _fail(r, model)
    data = r.json()
    u = data.get("usage") or {}
    return _parse(data["choices"][0]["message"].get("content")), int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


def _anthropic(model, prompt, schema):
    body = {"model": model, "max_tokens": 8192, "messages": [{"role": "user", "content": _wrapped(prompt, schema)}]}
    r = httpx.post(f"{base_url()}/messages", json=body, timeout=AI_REQUEST_TIMEOUT,
                   headers={"x-api-key": key(), "anthropic-version": "2023-06-01"})
    if r.status_code != 200:
        _fail(r, model)
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    u = data.get("usage") or {}
    return _parse(text), int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
