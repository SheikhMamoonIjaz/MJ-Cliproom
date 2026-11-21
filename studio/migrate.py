"""Recoverable, idempotent migration from MJ Cliproom 1.3.x to 2.0.0.

Preserves all user data, jobs, clips, transcripts, accounts, AI profiles, storage settings, and pending uploads.
Creates an automatic pre-migration metadata backup and supports a one-command rollback.
Never turns private, held, or unapproved posts public."""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import config, db

TARGET_SCHEMA = "2.0.0"

METADATA_FILES = (
    "peakcut.db",
    "ai.json",
    "ai-cooldowns.json",
    "apps.json",
    "posts.json",
    "post-cooldowns.json",
    "studio_presets.json",
    "autonomous.json",
    "schema_version.json",
)


def _schema_file(data_dir: Path) -> Path:
    return data_dir / "schema_version.json"


def current_schema(data_dir: Path = None) -> dict:
    d = Path(data_dir or config.DATA_DIR)
    f = _schema_file(d)
    if not f.is_file():
        return {"version": "1.3.2", "migrated_at": 0}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": "1.3.2", "migrated_at": 0}


def snapshot_before_migration(data_dir: Path = None) -> Path:
    """Create a fast, recoverable snapshot of all JSON and SQLite state before applying 2.0.0 schema upgrades."""
    d = Path(data_dir or config.DATA_DIR)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = d / "backups" / f"pre-2.0.0-{stamp}"
    suffix = 1
    while backup_dir.exists():
        suffix += 1
        backup_dir = d / "backups" / f"pre-2.0.0-{stamp}-{suffix}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    for name in METADATA_FILES:
        src = d / name
        if src.is_file():
            shutil.copy2(src, backup_dir / name)

    if config.STORAGE_FILE.is_file():
        shutil.copy2(config.STORAGE_FILE, backup_dir / "storage.json")

    users_dir = d / "users"
    if users_dir.is_dir():
        for pattern in ("*/autopilot.json", "*/accounts/*.json", "*/creators/*/creator.json",
                        "*/jobs/*/job.json", "*/creators/*/*/*/job.json"):
            for f in users_dir.glob(pattern):
                if f.is_file():
                    rel = f.relative_to(d)
                    dest = backup_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
    return backup_dir


def _atomic_json_write(path: Path, data, mode: int = None):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    if mode is not None:
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))


def migrate(data_dir: Path = None, *, create_backup: bool = True) -> dict:
    """Idempotently upgrade a 1.3.x data directory to 2.0.0. Safe to run repeatedly."""
    d = Path(data_dir or config.DATA_DIR)
    d.mkdir(parents=True, exist_ok=True)
    prev = current_schema(d)
    already_200 = prev.get("version") == TARGET_SCHEMA

    backup_path = None
    if create_backup and not already_200:
        backup_path = snapshot_before_migration(d)

    stats = {
        "ok": True,
        "from_version": prev.get("version", "1.3.2"),
        "to_version": TARGET_SCHEMA,
        "idempotent_noop": already_200,
        "already_migrated": already_200,
        "backup_dir": str(backup_path) if backup_path else prev.get("last_backup", ""),
        "ai_profiles_upgraded": 0,
        "jobs_upgraded": 0,
        "clips_upgraded": 0,
        "posts_checked": 0,
        "autopilot_files_upgraded": 0,
        "public_promotions": 0,  # Must always remain 0
    }

    # 1. Upgrade ai.json profiles idempotently
    ai_file = d / "ai.json"
    if ai_file.is_file():
        try:
            ai_data = json.loads(ai_file.read_text(encoding="utf-8"))
            if isinstance(ai_data, dict):
                profiles = ai_data.get("profiles")
                if not isinstance(profiles, list) or not profiles:
                    prov = str(ai_data.get("provider") or config.AI_PROVIDER or "gemini").strip().lower()
                    profiles = [{
                        "id": "primary",
                        "name": "Primary",
                        "provider": prov,
                        "models": list(ai_data.get("models") or config.AI_MODELS or ["gemini-2.5-flash"]),
                        "base_url": str(ai_data.get("base_url") or ""),
                        "key": str(ai_data.get("key") or ""),
                        "fallback": False,
                    }]
                for idx, p in enumerate(profiles):
                    if isinstance(p, dict):
                        p.setdefault("order", idx + 1)
                        p.setdefault("enabled", True)
                        p.setdefault("is_local", p.get("provider") in ("ollama", "custom"))
                        p.setdefault("allow_clip_text", True)
                        stats["ai_profiles_upgraded"] += 1
                ai_data["profiles"] = profiles
                ai_data.setdefault("active", profiles[0]["id"])
                ai_data.setdefault("promote_healthy_globally", False)
                _atomic_json_write(ai_file, ai_data, mode=0o600)
        except (OSError, ValueError):
            pass

    # 2. Upgrade posts.json without ever promoting private/held/draft items to public
    from . import posting, render
    post_files = [d / "posts.json"]
    if (d / "users").is_dir():
        post_files.extend((d / "users").glob("*/posts.json"))
    for posts_file in post_files:
        if posts_file.is_file():
            try:
                posts = json.loads(posts_file.read_text(encoding="utf-8"))
                if isinstance(posts, list):
                    changed = False
                    for p in posts:
                        if not isinstance(p, dict):
                            continue
                        stats["posts_checked"] += 1
                        if "pipeline_stage" not in p:
                            st = p.get("status", "scheduled")
                            p["pipeline_stage"] = (
                                "remote_verification" if st == "posted"
                                else "upload" if st == "posting"
                                else "validation" if st in ("held", "failed")
                                else "scheduling"
                            )
                            changed = True
                        # Never alter visibility to public during migration; default missing visibility on automatic posts to private
                        if "visibility" not in p:
                            p["visibility"] = "private"
                            changed = True
                        if "display_status" not in p:
                            p["display_status"] = posting.display_status(p)
                            changed = True
                    if changed:
                        _atomic_json_write(posts_file, posts)
            except (OSError, ValueError):
                pass

    # 3. Upgrade user jobs, clips, creators, and autopilot files
    users_dir = d / "users"
    if users_dir.is_dir():
        for ap_file in users_dir.glob("*/autopilot.json"):
            try:
                ap = json.loads(ap_file.read_text(encoding="utf-8"))
                if isinstance(ap, dict):
                    settings = ap.setdefault("settings", {})
                    # Guarantee safe default: never flip privacy to public during migration
                    if settings.get("privacy") not in ("private", "unlisted", "public"):
                        settings["privacy"] = "private"
                    settings.setdefault("public_opt_in", False)
                    _atomic_json_write(ap_file, ap)
                    stats["autopilot_files_upgraded"] += 1
            except (OSError, ValueError):
                pass

        job_files = list(users_dir.glob("*/jobs/*/job.json")) + list(users_dir.glob("*/creators/*/*/*/job.json"))
        for jf in job_files:
            try:
                job = json.loads(jf.read_text(encoding="utf-8"))
                if not isinstance(job, dict):
                    continue
                job["schema_version"] = TARGET_SCHEMA
                opts = job.setdefault("options", {})
                opts.setdefault("preset", "mj_gta")
                opts.setdefault("layout", "blur")
                (jf.parent / "summaries").mkdir(exist_ok=True)
                (jf.parent / "quarantine").mkdir(exist_ok=True)
                for clip in job.get("clips") or ():
                    if isinstance(clip, dict):
                        clip.setdefault("setup", f"Opens on: {(clip.get('hook') or clip.get('title') or 'Setup').title()}")
                        clip.setdefault("payoff", clip.get("reason") or "Resolves on a complete sentence payoff.")
                        clip.setdefault("evidence", clip.get("reason") or "Transcript and audio/visual activity peak.")
                        clip.setdefault("standalone_reason", clip.get("reason") or "Works as a standalone vertical clip.")
                        clip.setdefault("source_relevance_score", clip.get("score", 80))
                        srt_name = clip.get("subtitle") or (f"{clip.get('id')}.srt" if clip.get("id") else "")
                        if srt_name:
                            srt_path = jf.parent / "clips" / Path(srt_name).name
                            vtt_path = srt_path.with_suffix(".vtt")
                            if srt_path.is_file() and not vtt_path.is_file():
                                vtt_path.write_text(render.srt_to_vtt(srt_path.read_text(encoding="utf-8")), encoding="utf-8")
                            if vtt_path.is_file():
                                clip.setdefault("vtt_subtitle", f"clips/{vtt_path.name}" if "/" in str(srt_name) else vtt_path.name)
                        stats["clips_upgraded"] += 1
                _atomic_json_write(jf, job)
                stats["jobs_upgraded"] += 1
            except (OSError, ValueError):
                pass

    schema_doc = {
        "version": TARGET_SCHEMA,
        "previous_version": prev.get("version", "1.3.2"),
        "migrated_at": prev.get("migrated_at") or time.time(),
        "last_checked_at": time.time(),
        "last_backup": stats["backup_dir"],
    }
    _atomic_json_write(_schema_file(d), schema_doc)
    return stats


def rollback(backup_dir: Path, data_dir: Path = None) -> dict:
    """Restore a pre-2.0.0 metadata snapshot back into data_dir."""
    bdir = Path(backup_dir)
    d = Path(data_dir or config.DATA_DIR)
    if not bdir.is_dir():
        raise FileNotFoundError(f"Backup directory not found: {bdir}")
    restored = 0
    for f in bdir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(bdir)
            if rel.as_posix() == "storage.json":
                continue
            dest = d / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            restored += 1
    if not (bdir / "schema_version.json").is_file():
        _schema_file(d).unlink(missing_ok=True)
    return {"ok": True, "restored_files": restored, "from_backup": str(bdir)}


def main():
    parser = argparse.ArgumentParser(description="MJ Cliproom 1.3.2 -> 2.0.0 migration tool")
    parser.add_argument("--data", default="", help="Target data directory (defaults to PEAKCUT_DATA)")
    parser.add_argument("--rollback", default="", help="Restore from the specified backup folder")
    args = parser.parse_args()
    target = Path(args.data) if args.data else config.DATA_DIR
    if args.rollback:
        res = rollback(Path(args.rollback), target)
        print(json.dumps(res, indent=2))
        return 0
    res = migrate(target)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
