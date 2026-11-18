"""Local storage for provider keys.

The key never goes into a tracked file. On Windows the blob is wrapped with DPAPI
when that call is available. Everywhere else it is sealed with a key that lives
only in this computer's data folder.
"""
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

from . import config, ctx


def _folder() -> Path:
    path = config.user_dir(ctx.uid()) / "vault"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _machine_key() -> bytes:
    path = _folder() / "machine.key"
    if not path.is_file():
        path.write_bytes(os.urandom(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_bytes()


def _mask(key: bytes, nonce: bytes, size: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < size:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:size]


def seal(plain: bytes) -> bytes:
    key = _machine_key()
    nonce = os.urandom(16)
    hidden = bytes(a ^ b for a, b in zip(plain, _mask(key, nonce, len(plain))))
    tag = hmac.new(key, nonce + hidden, hashlib.sha256).digest()
    blob = nonce + tag + hidden
    return _dpapi(blob) if sys.platform == "win32" else blob


def open_sealed(blob: bytes) -> bytes:
    raw = _dpapi_open(blob) if sys.platform == "win32" and blob.startswith(b"\x01DPAPI") else blob
    if len(raw) < 48:
        raise ValueError("That saved key is damaged.")
    nonce, tag, hidden = raw[:16], raw[16:48], raw[48:]
    key = _machine_key()
    if not hmac.compare_digest(tag, hmac.new(key, nonce + hidden, hashlib.sha256).digest()):
        raise ValueError("That saved key could not be opened on this computer.")
    return bytes(a ^ b for a, b in zip(hidden, _mask(key, nonce, len(hidden))))


def _dpapi(blob: bytes) -> bytes:
    try:
        import ctypes
        from ctypes import wintypes
        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        buf = ctypes.create_string_buffer(blob)
        src = Blob(len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = Blob()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
            return blob
        protected = ctypes.string_at(out.pbData, out.cbData)
        ctypes.windll.kernel32.LocalFree(out.pbData)
        return b"\x01DPAPI" + protected
    except Exception:  # noqa: BLE001
        return blob


def _dpapi_open(blob: bytes) -> bytes:
    try:
        import ctypes
        from ctypes import wintypes
        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        data = blob[6:]
        buf = ctypes.create_string_buffer(data)
        src = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
            raise ValueError("Windows could not open the saved key.")
        plain = ctypes.string_at(out.pbData, out.cbData)
        ctypes.windll.kernel32.LocalFree(out.pbData)
        return plain
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Windows could not open the saved key.") from exc


def put_key(provider: str, secret: str):
    name = "".join(ch for ch in provider.lower() if ch.isalnum())[:20]
    if name not in ("gemini", "glm", "openai", "groq", "custom"):
        raise ValueError("Choose Gemini, GLM, OpenAI, Groq or a custom provider.")
    (_folder() / f"{name}.key").write_bytes(seal(secret.encode("utf-8")))


def get_key(provider: str) -> str:
    name = "".join(ch for ch in provider.lower() if ch.isalnum())[:20]
    path = _folder() / f"{name}.key"
    if not path.is_file():
        return ""
    return open_sealed(path.read_bytes()).decode("utf-8")


def list_saved() -> list:
    return sorted(path.stem for path in _folder().glob("*.key") if path.stem != "machine")


def encoder_order(available) -> list:
    """Prefer a hardware encoder, then the normal one."""
    names = [str(item) for item in available]
    preferred = [item for item in ("h264_nvenc", "h264_amf", "h264_qsv", "libx264") if item in names]
    return preferred or ["libx264"]
