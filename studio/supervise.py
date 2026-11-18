"""Keep MJ Cliproom running after a crash.

Docker already restarts the app container. On a computer, this wrapper starts the normal launcher
and, if the process dies unexpectedly, waits and starts it again. A clean stop (Ctrl+C, or the
launcher finishing an update and choosing to exit) is left alone.

    python -m studio.supervise
"""
import subprocess
import sys
import time

from .launcher import UPDATE_EXIT


def main() -> int:
    delay = 2
    while True:
        try:
            code = subprocess.call([sys.executable, "-m", "studio.launcher"])
        except KeyboardInterrupt:
            return 130
        if code in (0, 130, 143):
            return code
        # The launcher exits with UPDATE_EXIT only after it has already restarted itself.
        if code == UPDATE_EXIT:
            return code
        print(f"MJ Cliproom stopped (code {code}). Starting again in {delay} seconds.", flush=True)
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            return 130
        delay = min(60, delay * 2)


if __name__ == "__main__":
    sys.exit(main())
