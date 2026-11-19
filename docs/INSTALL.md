# Install MJ-Cliping v1.2.0

MJ-Cliping needs Python 3.10 or newer (3.12–3.13 recommended), FFmpeg on your PATH, and Git if you update from GitHub.

## Windows

From the folder that contains this project:

```bat
install-mj-cliproom.bat
```

That creates `.venv`, upgrades pip, and installs `requirements.txt`. The same steps by hand in PowerShell:

```powershell
# 1. Create virtual environment
py -3 -m venv .venv

# 2. Upgrade pip and install all required dependencies
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Start MJ-Cliping Server
.\.venv\Scripts\python.exe -m studio.launcher
```

Open the address printed in the window: [http://127.0.0.1:8765](http://127.0.0.1:8765).

To update a copy that is already running, double-click `update-mj-cliproom.bat`. It starts the launcher if needed and asks the app to apply a verified fast-forward. Your data folder stays where it is. If sign-in is on, sign in and use **Update now → Install and restart**.

## macOS and Linux

```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Upgrade pip and install all required dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 3. Start MJ-Cliping Server
python -m studio.launcher
```

## Hardware Acceleration (GPU)

MJ-Cliping automatically detects NVIDIA NVENC and Intel QSV for ultra-fast GPU video rendering. Ensure your graphics drivers and FFmpeg with NVENC are installed. Fallback to CPU (`libx264`) is fully automatic.

## 24/7 Autonomous Clipping

Turn on **24/7 Autonomous Mode** from the homepage dashboard. The background worker autonomously polls trending GTA 6 streams and fresh gameplay every 20-30 minutes, producing 9:16 vertical shorts continuously.

## Music folder

Uploads and a folder scan only accept audio you confirm you have the rights to use. Set `PEAKCUT_MUSIC_DIR` in `.env` when that folder is outside your home directory and outside the data folder.

## Notes

OpenCV is installed from `opencv-python-headless` for facecam detection. Optional `espeak-ng` speaks original shorts when you have not uploaded a voice file. Custom YouTube thumbnails need a channel YouTube allows to set them.
