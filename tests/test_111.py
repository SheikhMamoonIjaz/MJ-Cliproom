"""1.1.0: same-computer addresses, diagnostics, and settings export."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-111-")
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


check("localhost and 127.0.0.1 on the same port match",
      server._same_browser("http://localhost:8765", "127.0.0.1:8765"))
check("a different port does not match",
      server._same_browser("http://127.0.0.1:8766", "127.0.0.1:8765"), False)
check("the release is 1.2.0", server.VERSION, "1.2.0")

client = TestClient(server.app, base_url="http://127.0.0.1:8765")
page = client.get("/api/diagnostics")
check("diagnostics answers", page.status_code, 200)
body = page.json()
check("diagnostics names the version", body.get("version"), "1.2.0")
check("diagnostics does not include a key", "key" not in body)
logs = client.get("/api/logs")
check("the log endpoint answers", logs.status_code, 200)
check("the log is a list of lines", isinstance(logs.json().get("lines"), list))

if fails:
    print(f"\n{len(fails)} FAILED")
    sys.exit(1)
print("\nall 1.1 checks passed")
