"""Run one server at a time and install a staged update only after a clean supervised exit."""
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPDATE_EXIT = 75


def runtime_python():
    requirements = (ROOT / "requirements.txt").read_bytes().replace(b"\r\n", b"\n")
    version = ROOT / ".mj-runtime" / hashlib.sha256(requirements).hexdigest()
    python = version / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(python) if (version / "ready").is_file() and python.is_file() else sys.executable


def main():
    with tempfile.TemporaryDirectory(prefix="mj-cliproom-launch-") as tmp:
        plan = Path(tmp) / "update.json"
        env = {**os.environ, "PEAKCUT_LAUNCH_PLAN": str(plan), "PEAKCUT_AUTO_RELOAD": "0"}

        def run(python, *args):
            return subprocess.run([python, "-m", *args], cwd=ROOT, env=env).returncode

        try:
            while True:
                python = runtime_python()
                result = run(python, "studio.server")
                if not plan.is_file() and result != UPDATE_EXIT:
                    return result
                # If installation fails, restart the working checkout and display the error to the browser.
                failed = False
                if plan.is_file():
                    failed = run(python, "studio.updates", str(plan)) != 0
                    plan.unlink(missing_ok=True)
                env["PEAKCUT_UPDATE_INSTALL_FAILED"] = "1" if failed else ""
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    sys.exit(main())
