"""Every /api path the pages call must exist. Safe reads must not be 404 or 500."""
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-routes-")
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from studio import db, server

db.init()
fails = []


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    if not ok:
        fails.append(name)


def page_calls():
    text = "\n".join(path.read_text(encoding="utf-8") for path in Path("web").rglob("*.*")
                     if path.suffix in {".html", ".js"})
    found = set(re.findall(r"/api/[^\s\"'`\\]+", text))
    clean = []
    for raw in found:
        path = raw.split("?")[0].rstrip(".,);")
        path = re.sub(r"\$\{[^}]+\}", "{id}", path)
        path = re.sub(r"\{[^}]+\}", "{id}", path)
        if path.startswith("/api/") and not path.endswith("/"):
            clean.append(path)
    return sorted(set(clean))


def route_regexes():
    patterns = []
    for route in server.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", path)
        patterns.append((path, re.compile("^" + pattern + "$")))
    return patterns


calls = page_calls()
routes = route_regexes()
missing = [call for call in calls if not any(pattern.match(call) for _path, pattern in routes)]
check("the pages only call routes that exist", missing, [])

client = TestClient(server.app, base_url="http://127.0.0.1:8765")
for path in ("/api/status", "/api/autopilot", "/api/music", "/api/overview", "/api/usage",
             "/api/sync", "/api/notifications", "/api/diagnostics", "/api/logs", "/api/settings",
             "/api/settings/export", "/api/jobs", "/api/creators", "/api/accounts", "/api/storage",
             "/healthz"):
    response = client.get(path)
    check(path + " is not missing or broken", response.status_code not in (404, 500))
    if response.status_code in (404, 500):
        print("   status", response.status_code, response.text[:180])

scan = client.post("/api/autopilot/scan")
check("a scan starts without waiting for every channel", scan.status_code, 200)
check("the scan answer says it is running or already going", scan.json().get("status") in ("running", "done", "idle"))

if fails:
    print(f"\n{len(fails)} FAILED")
    sys.exit(1)
print("\nall route checks passed")
