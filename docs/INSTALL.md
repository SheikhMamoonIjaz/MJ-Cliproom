# Install MJ Cliproom 1.0.0

MJ Cliproom needs Python 3.10 or newer (3.13 is the Windows target), FFmpeg on your PATH, and Git if you update from GitHub.

## Windows

From the folder that contains this project:

```bat
install-mj-cliproom.bat
```

That creates `.venv`, upgrades pip, and installs `requirements.txt`. The same steps by hand:

```bat
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m studio.launcher
```

Open the address printed in the window. The usual address is http://127.0.0.1:8765.

To update a copy that is already running, double-click `update-mj-cliproom.bat`. It starts the launcher if needed and asks the app to apply a verified fast-forward. Your data folder stays where it is. If sign-in is on, sign in and use **Update now → Install and restart**.

## macOS and Linux

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m studio.launcher
```

## Music folder

Uploads and a folder scan only accept audio you confirm you have the rights to use. Set `PEAKCUT_MUSIC_DIR` in `.env` when that folder is outside your home directory and outside the data folder.

## Notes

OpenCV is installed from `opencv-python-headless` for facecam detection. Optional `espeak-ng` speaks original shorts when you have not uploaded a voice file. Custom YouTube thumbnails need a channel YouTube allows to set them.
