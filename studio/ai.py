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


def _profiles() -> list:
    data = _from_dashboard()
    if isinstance(data.get("profiles"), list) and data["profiles"]:
        return data["profiles"]
    p = str(data.get("provider") or config.AI_PROVIDER or "").strip().lower()
    return [{"id": "primary", "name": "Primary", "provider": ALIASES.get(p, p),
             "models": list(data.get("models") or []) if data.get("provider") else list(config.AI_MODELS),
             "base_url": str(data.get("base_url") or "").rstrip("/") if data.get("provider") else config.AI_BASE_URL,
             "key": str(data.get("key", config.ai_key())) if data.get("provider") else config.ai_key(),
             "fallback": False}]


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
    return host


def attempts():
    primary = current()
    all_profiles = _profiles()
    seen = set()
    ordered = [primary] + [p for p in all_profiles if p.get("fallback") and p["id"] != primary["id"]]
    for p in ordered:
        if p["provider"] not in PROVIDERS:
            continue
        family = service(p)
        if family in seen:
            continue
        with use(p):
            available = ready() and not cooling()
        if available:
            seen.add(family)
            yield p


def can_answer() -> bool:
    """Whether the active profile or an opted-in independent backup can answer now."""
    return next(attempts(), None) is not None


def cooling(profile=None) -> bool:
    with _lock:
        target = profile or current()
        return _cooldowns.get(service(target), 0) > time.time()


def retry_delay(headers, default):
    raw = headers.get("retry-after", headers.get("Retry-After", ""))
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        try:
            return max(1, int(parsedate_to_datetime(raw).timestamp() - time.time()))
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


def _summary(c):
    with use(c):
        return {k: c[k] for k in ("id", "name", "provider", "models", "base_url", "fallback")} | {
            "has_key": bool(c["key"]), "key_hint": c["key"][-4:] if len(c["key"]) >= 12 else "",
            "ready": ready(), "cooling": cooling() if ready() else False, "label": label()}


def public() -> dict:
    return {**_summary(current()), "saved_here": bool(_from_dashboard()),
            "profiles": [_summary(p) for p in _profiles()],
            "providers": [{"id": k, "label": v[0], "address": v[1], "needs_key": k not in NO_KEY, "key_url": v[3], "example": v[4]}
                          for k, v in PROVIDERS.items()]}


def _write_profiles(rows, active):
    f = _file()
    tmp = f.with_suffix(".tmp")
    # Keep the active settings readable by an older version if the operator rolls back.
    primary = next(row for row in rows if row["id"] == active)
    data = {k: primary[k] for k in ("provider", "models", "base_url", "key")}
    tmp.write_text(json.dumps({**data, "profiles": rows, "active": active}), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(f)
    _saved["at"] = None


def manage(profile_id, action):
    with _lock:
        rows = _profiles()
        if not any(p["id"] == profile_id for p in rows):
            raise ValueError("That AI profile no longer exists.")
        active = current()["id"]
        if action == "activate":
            active = profile_id
        elif action == "delete":
            if len(rows) == 1:
                raise ValueError("Save another profile before deleting this one.")
            rows = [p for p in rows if p["id"] != profile_id]
            if active == profile_id:
                active = rows[0]["id"]
        else:
            raise ValueError("Unknown profile action.")
        _write_profiles(rows, active)
    return public()


def save(provider_id: str, model_ids, address: str = "", new_key=None, *, profile_id=None,
         name=None, fallback=None) -> dict:
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
        row = {"id": old["id"] if old else secrets.token_hex(8), "provider": p, "models": ms,
               "base_url": address, "key": k, "name": (str(name or "").strip()[:64] or (old["name"] if old else PROVIDERS[p][0])),
               "fallback": (old or {}).get("fallback", False) if fallback is None else fallback is True}
        rows = [row if old is other else other for other in rows] if old else [*rows, row]
        _write_profiles(rows, active if any(r["id"] == active and r["provider"] for r in rows) else row["id"])
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
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status



problem = {"text": "", "at": 0.0}       # why the AI last failed, for the dashboard; cleared when it answers again


def explain(e) -> str:
    """What went wrong with an AI call, in words the owner can act on."""
    text, low = str(e), str(e).lower()
    name = (models() or ["?"])[0]
    if "404" in text or "not found" in low or "does not exist" in low or "unknown model" in low or "not_found" in low:
        return f"{label()} doesn't know the model \"{name}\". Open Settings, AI, press Find models and pick one from the list."
    if "401" in text or "403" in text or "api key" in low or "api_key" in low or "unauthorized" in low or "permission" in low:
        return f"{label()} refused the key. Paste a working key under Settings, AI."
    if "429" in text or "quota" in low or "rate limit" in low or "exhausted" in low:
        return f"{label()} says the key has hit its limit or has no credit left. Check the account with {label()}, or try again later."
    if "connect" in low or "timed out" in low or "timeout" in low or "getaddrinfo" in low or "refused" in low:
        return f"PeakCut couldn't reach {label()}. Check the internet connection" + (" and that Ollama is running." if provider() == "ollama" else ".")
    return ""


def note_problem(e):
    import time
    why = explain(e)
    if why:
        problem.update(text=why, at=time.time())


def clear_problem():
    problem.update(text="", at=0.0)


def _fail(r, model):
    headers = getattr(r, "headers", {})
    if r.status_code == 429 or (r.status_code >= 500 and headers.get("retry-after")):
        with _lock:
            family = service(current())
            until = time.time() + retry_delay(headers, 900)
            _cooldowns[family] = max(_cooldowns.get(family, 0), until)
            try:
                tmp = _cooldown_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(_cooldowns), encoding="utf-8")
                tmp.replace(_cooldown_file)
            except OSError:  # keep honoring the cooldown in memory
                pass
    raise AIError(f"HTTP {r.status_code} for model {model}", status=r.status_code)


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
            raise AIError("The AI did not answer with JSON.")
        out = json.loads(m.group(0))
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
    text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    u = data.get("usageMetadata", {})
    sent = int(u.get("promptTokenCount") or 0)
    return json.loads(text), sent, max(0, int(u.get("totalTokenCount") or 0) - sent)   # the answer, and any thinking billed with it


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
