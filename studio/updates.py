"""Is there a newer PeakCut? Compares the version running here with the latest on GitHub, once a minute.

The version here is the git commit this folder was on when PeakCut started (read straight from .git, no git
program needed). Each minute, in the background, PeakCut asks GitHub which commit the project is on now: one small
request to the same address `git` itself uses, which has no hourly allowance to run out of. Only when that commit
changes does it ask GitHub's API what was added, to show the list. Nothing about this computer or its users is
sent. The owner sees a notice in the dashboard within a minute or two, with no restart.

    PEAKCUT_UPDATE_REPO     where to look (default: the project's own repository; a fork points at itself)
    PEAKCUT_UPDATE_BRANCH   which branch (default: main)
    PEAKCUT_UPDATE_CHECK=0  never look"""
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from . import config

REPO = (config.env("PEAKCUT_UPDATE_REPO") or "SheikhMamoonIjaz/MJ-Cliproom").strip().strip("/")
BRANCH = (config.env("PEAKCUT_UPDATE_BRANCH") or "main").strip()
ON = config.env("PEAKCUT_UPDATE_CHECK", "1") != "0" and bool(re.fullmatch(r"[\w.\-]+/[\w.\-]+", REPO)) and bool(re.fullmatch(r"[\w][\w./-]*", BRANCH))
EVERY = 60
UA = {"User-Agent": "MJ-Cliproom-update-check"}
_state = {"checked": 0.0, "result": None, "seen": "", "notes": None}
_lock = threading.Lock()
_started = False
_apply_lock = threading.Lock()
_apply_state = {"state": "idle", "message": "", "latest": "", "target": ""}
RESTART_EXIT = 75
_restart = None
REQUIRE_SIGNATURE = config.env("PEAKCUT_UPDATE_REQUIRE_SIGNATURE") == "1"


class UpdateError(ValueError):
    pass


def apply_status() -> dict:
    return dict(_apply_state)


def _git(*args, timeout=60):
    try:
        return subprocess.run(["git", "-C", str(config.ROOT), *args], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpdateError("Git could not finish the update. Check that Git is installed and try again.") from e


def _origin_matches() -> bool:
    r = _git("remote", "get-url", "origin")
    if r.returncode:
        return False
    raw = r.stdout.strip()
    if raw.startswith("git@github.com:"):
        path = raw.partition(":")[2]
    else:
        from urllib.parse import urlsplit
        parsed = urlsplit(raw)
        if parsed.scheme not in ("https", "ssh") or parsed.hostname != "github.com" or parsed.password or parsed.port:
            return False
        path = parsed.path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path.casefold() == REPO.casefold()


def _preflight() -> None:
    if not ON:
        raise UpdateError("Updates are turned off on this copy of MJ Cliproom.")
    if not (Path(config.ROOT) / ".git").exists():
        raise UpdateError("This copy was installed without Git. Follow the update steps in the README.")
    r = _git("status", "--porcelain", "--untracked-files=all")
    if r.returncode:
        raise UpdateError("Git could not check this installation. Try updating it from the project folder.")
    if r.stdout.strip():
        raise UpdateError("The app folder has local changes. Save or back them up before updating.")
    branch = _git("branch", "--show-current")
    if branch.returncode or branch.stdout.strip() != BRANCH:
        raise UpdateError(f"This copy is not on the {BRANCH} branch, so it cannot use the in-app updater.")
    if not _origin_matches():
        raise UpdateError("The GitHub remote does not match this app's configured update repository.")


def managed_restart(callback):
    global _restart
    _restart = callback


def begin_apply() -> dict:
    """Stage an authenticated fast-forward; the launcher applies it once the server has exited cleanly."""
    _preflight()
    if _restart is None:
        raise UpdateError("This server was not started with the MJ Cliproom launcher. Update it while stopped using the README instructions.")
    if _apply_state["state"] == "restarting":
        return apply_status()
    if not _apply_lock.acquire(blocking=False):
        return apply_status()
    _apply_state.update(state="running", message="Checking the GitHub version…", latest="", target="")
    threading.Thread(target=_apply, name="mj-cliproom-updater", daemon=True).start()
    return apply_status()


def _validate(target):
    if not re.fullmatch(r"[0-9a-f]{40}", target or ""):
        raise UpdateError("GitHub did not return a valid update commit.")
    head = current()
    if head == target:
        raise UpdateError("MJ Cliproom is already up to date.")
    if _git("merge-base", "--is-ancestor", head, target).returncode:
        raise UpdateError("The configured update is not a fast-forward. Your app and data were left in place.")
    if REQUIRE_SIGNATURE and _git("-c", "gpg.minTrustLevel=fully", "verify-commit", target).returncode:
        raise UpdateError("The update commit was not signed by a trusted signer. Review your Git signing settings.")
    changed = _git("diff", "--name-only", "-z", "--no-renames", head, target, "--")
    if changed.returncode:
        raise UpdateError("Git could not inspect the update.")
    protected = {"data", ".env", ".venv", ".mj-runtime", "storage.json"}
    root = Path(config.ROOT).resolve()
    for p in (config.DATA_DIR, config.STORAGE_FILE, config.MODELS_DIR):
        try:
            protected.add(Path(p).resolve().relative_to(root).as_posix().casefold())
        except ValueError:
            pass
    names = {path.casefold() for path in changed.stdout.split("\0") if path}
    if any(name == p or name.startswith(p + "/") or p.startswith(name + "/") for name in names for p in protected):
        raise UpdateError("The update would change a storage or configuration path. Update manually after reviewing the changes.")



def _apply() -> None:
    try:
        target = newest()
        if not target:
            raise UpdateError("GitHub could not be reached. Your current files and data were left alone.")
        if target == current():
            raise UpdateError("MJ Cliproom is already up to date.")
        _apply_state.update(message="Downloading and checking the update…", latest=target[:7])
        fetched = _git("fetch", "--no-tags", "origin", BRANCH, timeout=180)
        if fetched.returncode:
            raise UpdateError("GitHub could not send the update. Check your connection and try again.")
        fetched_sha = _git("rev-parse", "FETCH_HEAD")
        if fetched_sha.returncode or fetched_sha.stdout.strip() != target:
            raise UpdateError("The update changed while downloading. Check for updates again.")
        _validate(target)
        _apply_state.update(state="restarting", target=target, message="Update verified. Restarting MJ Cliproom…")
        _restart(target)
    except UpdateError as e:
        _apply_state.update(state="error", message=str(e), target="")
    except Exception:  # never return command output, which could contain a credential-bearing remote
        _apply_state.update(state="error", target="", message="The update did not finish. Check the connection and try again.")
    finally:
        _apply_lock.release()


def _stage_dependencies(target):
    root = Path(config.ROOT)
    manifest = root / "requirements.txt"
    old = manifest.read_bytes()
    try:
        r = subprocess.run(["git", "-C", str(root), "cat-file", "blob", f"{target}:requirements.txt"],
                           capture_output=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpdateError("Git could not read the updated requirements.") from e
    if r.returncode:
        raise UpdateError("This update is missing its Python requirements. Review it manually.")
    new = r.stdout
    if old.replace(b"\r\n", b"\n") == new.replace(b"\r\n", b"\n"):
        return
    fingerprint = hashlib.sha256(new.replace(b"\r\n", b"\n")).hexdigest()
    runtime = root / ".mj-runtime" / fingerprint
    mark = runtime / "ready"
    exe = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if mark.is_file() and exe.is_file():
        return
    try:
        mark.unlink(missing_ok=True)
        # A new environment keeps the old installation runnable even if pip is interrupted.
        env = subprocess.run([sys.executable, "-m", "venv", str(runtime)],
                             cwd=root, capture_output=True, timeout=180, check=False)
        if env.returncode:
            raise UpdateError("Could not create a separate environment for the update. Your previous version is unchanged.")
        requirements = runtime / "requirements.txt"
        requirements.write_bytes(new)
        deps = subprocess.run([str(exe), "-m", "pip", "install", "-r", str(requirements)],
                              cwd=root, capture_output=True, timeout=720, check=False)
        if deps.returncode:
            raise UpdateError("Dependencies failed to install. The launcher will restart the previous version.")
        mark.write_text("ready", encoding="utf-8")
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpdateError("Dependencies did not finish installing. The launcher will restart the previous version.") from e


def install_staged(target):
    _preflight()
    _validate(target)
    fetched = _git("rev-parse", "FETCH_HEAD")
    if fetched.returncode or fetched.stdout.strip() != target:
        raise UpdateError("The staged commit changed. Your checkout was left in place.")
    _stage_dependencies(target)
    _preflight()
    r = _git("merge", "--ff-only", "--no-overwrite-ignore", target, timeout=180)
    if r.returncode or current() != target:
        raise UpdateError("Git could not apply the fast-forward. Check the app folder before retrying.")


def _launcher_install():
    try:
        target = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["target"]
        install_staged(target)
    except UpdateError as e:
        print(f"MJ Cliproom update: {e}", flush=True)
        return 1
    except (OSError, ValueError, KeyError):
        print("MJ Cliproom update: the staged update could not be read.", flush=True)
        return 1
    return 0


def current() -> str:
    """The commit this folder is on now, or "" when it was not installed with git (a downloaded zip, for example)."""
    g = config.ROOT / ".git"
    try:
        if g.is_file():                      # a worktree or submodule: .git points somewhere else
            g = (config.ROOT / g.read_text(encoding="utf-8").split(":", 1)[1].strip()).resolve()
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if re.fullmatch(r"[0-9a-f]{40}", head) else ""
        ref = head.split(":", 1)[1].strip()
        common = g / "commondir"
        refs = (g / common.read_text(encoding="utf-8").strip()).resolve() if common.is_file() else g
        for f in (g / ref, refs / ref):
            if f.is_file():
                return f.read_text(encoding="utf-8").strip()
        packed = refs / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except (OSError, IndexError):
        pass
    return ""


RUNNING = current()       # the code in memory: what PeakCut is actually running until it is restarted


def newest() -> str:
    """The commit the project is on right now, from the address git itself asks. "" if it cannot be told."""
    r = httpx.get(f"https://github.com/{REPO}.git/info/refs", params={"service": "git-upload-pack"}, headers=UA, timeout=15)
    if r.status_code != 200:
        return ""                            # a private repository, or GitHub is having a moment
    m = re.search(rb"([0-9a-f]{40}) refs/heads/" + re.escape(BRANCH).encode() + rb"[\x00\n]", r.content)
    return m.group(1).decode() if m else ""


def _what_changed(here: str):
    """(how many commits newer, their first lines, newest first), or None if GitHub's API will not say right now."""
    r = httpx.get(f"https://api.github.com/repos/{REPO}/compare/{here}...{BRANCH}", timeout=20,
                  headers={"Accept": "application/vnd.github+json", **UA})
    if r.status_code != 200:
        return None
    d = r.json()
    notes = []
    for c in reversed(d.get("commits") or []):
        msg = str((c.get("commit") or {}).get("message") or "").strip().splitlines()
        notes.append({"sha": str(c.get("sha") or "")[:7], "title": (msg[0] if msg else "")[:140],
                      "date": str(((c.get("commit") or {}).get("committer") or {}).get("date") or "")[:10]})
    return int(d.get("ahead_by") or 0), notes[:20]


def check(force: bool = False):
    """Look once. Returns what the dashboard should say, or None when this copy is up to date (or it cannot be told)."""
    if not ON:
        return None
    with _lock:
        now = time.time()
        if not force and now - _state["checked"] < EVERY:
            return _state["result"]
        _state["checked"] = now
        here, on_disk = RUNNING, current()
        try:
            top = newest() if here else ""
        except Exception:  # noqa: BLE001 - offline: what was known stays, and it is asked again in a minute
            return _state["result"]
        if not top or top == here:
            _state.update(result=None, seen=top)
            return None
        if top != _state["seen"] or _state["notes"] is None:      # a commit not seen before: ask what it brought, once
            _state["seen"] = top
            try:
                _state["notes"] = _what_changed(here)
            except Exception:  # noqa: BLE001
                _state["notes"] = None
        got = _state["notes"]
        if got and got[0] == 0:
            _state["result"] = None          # this copy has its own newer commits: nothing to fetch
            return None
        _state["result"] = {"current": here[:7], "latest": top[:7], "behind": got[0] if got else None,
                            "notes": got[1] if got else [], "url": f"https://github.com/{REPO}/commits/{BRANCH}",
                            # the new files are already in the folder (git pull was run): only a restart is left
                            "restart": on_disk == top}
        return _state["result"]


def latest():
    """For the pages: what the last look found. Never waits on GitHub."""
    return _state["result"] if ON else None


def start():
    """Look every minute, in the background, for as long as PeakCut runs."""
    global _started
    if not ON or _started:
        return
    _started = True

    def loop():
        while True:
            try:
                check()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(EVERY)
    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    sys.exit(_launcher_install())
