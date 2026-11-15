"""Is there a newer PeakCut? Compares the version running here with the latest on GitHub, once a minute.

The version here is the git commit this folder was on when PeakCut started (read straight from .git, no git
program needed). Each minute, in the background, PeakCut asks GitHub which commit the project is on now: one small
request to the same address `git` itself uses, which has no hourly allowance to run out of. Only when that commit
changes does it ask GitHub's API what was added, to show the list. Nothing about this computer or its users is
sent. The owner sees a notice in the dashboard within a minute or two, with no restart.

    PEAKCUT_UPDATE_REPO     where to look (default: the project's own repository; a fork points at itself)
    PEAKCUT_UPDATE_BRANCH   which branch (default: main)
    PEAKCUT_UPDATE_CHECK=0  never look"""
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
ON = config.env("PEAKCUT_UPDATE_CHECK", "1") != "0" and bool(re.fullmatch(r"[\w.\-]+/[\w.\-]+", REPO))
EVERY = 60
UA = {"User-Agent": "MJ-Cliproom-update-check"}
_state = {"checked": 0.0, "result": None, "seen": "", "notes": None}
_lock = threading.Lock()
_started = False
_apply_lock = threading.Lock()
_apply_state = {"state": "idle", "message": "", "latest": "", "requirements_pending": False}


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
        if parsed.hostname != "github.com":
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


def begin_apply() -> dict:
    """Download a fast-forward update and changed requirements, without touching the data folder."""
    _preflight()
    if not _apply_lock.acquire(blocking=False):
        return apply_status()
    _apply_state.update(state="running", message="Checking the GitHub version…", latest="")
    threading.Thread(target=_apply, name="mj-cliproom-updater", daemon=True).start()
    return apply_status()


def _apply() -> None:
    try:
        before = current()
        target = newest()
        if not target:
            raise UpdateError("GitHub could not be reached. Your current files and data were left alone.")
        retry_requirements = bool(_apply_state.get("requirements_pending")) and before == target
        if before == target and not retry_requirements:
            raise UpdateError("MJ Cliproom is already up to date.")
        requirements = Path(config.ROOT) / "requirements.txt"
        old_requirements = requirements.read_bytes() if requirements.is_file() else b""
        if not retry_requirements:
            _apply_state.update(message="Downloading the update…", latest=target[:7])
            fetched = _git("fetch", "--no-tags", "origin", BRANCH, timeout=180)
            if fetched.returncode:
                raise UpdateError("GitHub could not send the update. Check your connection and try again.")
            fetched_sha = _git("rev-parse", "FETCH_HEAD")
            if fetched_sha.returncode or fetched_sha.stdout.strip() != target:
                raise UpdateError("A newer update appeared while downloading. Check for updates again.")
            merged = _git("merge", "--ff-only", "FETCH_HEAD", timeout=180)
            if merged.returncode:
                raise UpdateError("This update cannot be applied as a fast-forward. Your clips and settings are unchanged.")
        new_requirements = requirements.read_bytes() if requirements.is_file() else b""
        if new_requirements != old_requirements or retry_requirements:
            _apply_state.update(message="Installing the updated requirements…")
            try:
                pip = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(requirements)],
                                     cwd=str(config.ROOT), capture_output=True, text=True, timeout=600, check=False)
            except (OSError, subprocess.TimeoutExpired) as e:
                _apply_state.update(requirements_pending=True)
                raise UpdateError("The code was downloaded, but its Python requirements did not finish installing. Try the update again before restarting.") from e
            if pip.returncode:
                _apply_state.update(requirements_pending=True)
                raise UpdateError("The code was downloaded, but a Python requirement failed to install. Try the update again before restarting.")
        _apply_state.update(state="done", message="Update downloaded. Restart MJ Cliproom to use it; saved data and resumable jobs stay in place.", latest=target[:7], requirements_pending=False)
        check(force=True)
    except UpdateError as e:
        _apply_state.update(state="error", message=str(e))
    except Exception:  # noqa: BLE001 - never return command output, which could contain a credential-bearing remote
        _apply_state.update(state="error", message="The update did not finish. Your saved data was left in place; check the connection and try again.")
    finally:
        _apply_lock.release()


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
        f = g / ref
        if f.is_file():
            return f.read_text(encoding="utf-8").strip()
        packed = g / "packed-refs"
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
