# Installation & Usage Guide · MJ-Cliping v1.2.0

MJ-Cliping is a high-performance 24/7 autonomous streaming video clipping and multi-platform production studio.

---

## ⚡ Quick Start (Under 1 Minute)

### On Windows
1. Open PowerShell and install FFmpeg:
   ```powershell
   winget install --id Gyan.FFmpeg -e
   ```
2. Clone the repository:
   ```powershell
   git clone https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
   cd MJ-Cliproom
   ```
3. Run the automated installer:
   ```powershell
   .\install-mj-cliproom.bat
   ```
   *This automatically sets up Python `.venv`, installs all required dependencies, verifies hardware encoders, and creates a 1-click **Desktop Shortcut** (`MJ-Cliping.lnk`).*

4. Launch the application:
   - Double-click the **MJ-Cliping** shortcut on your Desktop, or run:
     ```powershell
     .\.venv\Scripts\python.exe -m studio.launcher
     ```
   - Open your browser at **[http://127.0.0.1:8765](http://127.0.0.1:8765)**.

---

## 📦 Dependencies Breakdown

### Required Dependencies (Pinned in `requirements.txt`)
All 13 packages install automatically during setup:
- **`fastapi` & `uvicorn`:** High-throughput async web server and REST API gateways.
- **`python-multipart`:** Resumable chunked file upload handler for massive 4K video files.
- **`httpx`:** Async HTTP client powering AI provider requests and stream metadata probing.
- **`numpy` & `soundfile`:** High-speed audio waveform analysis, loudness dB decibel calculation, and z-score spike detection.
- **`sherpa-onnx`:** Local offline speech-to-text recognition model (runs 100% locally on your CPU with zero external API calls).
- **`pillow` (PIL):** High-resolution thumbnail generation and custom font metrics.
- **`opencv-python-headless`:** Real-time streamer face detection and bounding box tracking.
- **`yt-dlp`:** Stream capture and video downloading for YouTube, Twitch, and Kick.
- **`SQLAlchemy`, `psycopg`, `psycopg-binary`:** Production database core (SQLite by default, PostgreSQL ready).

### Optional Dependencies & Tools
- **FFmpeg with NVENC / QSV:** Recommended for 3.8x faster hardware-accelerated GPU exports. Fallback to CPU `libx264` is automatic.
- **`espeak-ng`:** Optional text-to-speech utility for spoken narration when custom voice files are omitted.
- **AI Service Keys:** Optional (Google Gemini, Z.AI GLM, Grok, OpenAI). If no keys are provided, highlight detection runs continuously using audio loudness and facecam motion signals.

---

## 🖥️ Step-by-Step Manual Installation

### Windows (Manual PowerShell)
```powershell
# 1. Create Python virtual environment
py -3 -m venv .venv

# 2. Upgrade pip and install all required packages
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Create Desktop Shortcut
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\create-desktop-shortcut.ps1

# 4. Start the studio server
.\.venv\Scripts\python.exe -m studio.launcher
```

### macOS & Linux
```bash
# 1. Install FFmpeg
# On macOS (Homebrew):
brew install ffmpeg

# On Ubuntu / Debian:
sudo apt update && sudo apt install -y ffmpeg

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install packages
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. Launch Studio
python -m studio.launcher
```

### Cloud VPS Mode (Headless 24/7 Server)
```bash
# Set environment variables for public headless hosting
export PEAKCUT_HOST=0.0.0.0
export PEAKCUT_PORT=8765
export PEAKCUT_ACCOUNTS=1
export PEAKCUT_DATA=/var/lib/mj-cliping

# Run as background systemd service or via nohup:
nohup python -m studio.server > studio.log 2>&1 &
```

---

## 🚀 How to Use MJ-Cliping (Feature Walkthrough)

### 1. Activating 24/7 Autopilot
- Click **"Start 24/7 Auto"** in the top **MJ-Cliping Studio Hub**.
- The background loop autonomously scans active streamers and pending VODs every 20–30 minutes, cutting pure 9:16 vertical clips.
- **Quota Guard Active:** If an AI key reaches rate limits, the engine automatically switches between configured profiles (Gemini ↔ GLM) or falls back to signal-based detection. Capturing never stops.

### 2. Choosing Video Rendering Formats
- Click **"8 Video Render Formats"** from the Content column.
- Select from:
  - Pure 9:16 Fullscreen Vertical (1080x1920)
  - 9:16 Stacked (Streamer Facecam Top + Gameplay Bottom)
  - 9:16 Ambient Mirror Background Blur
  - 9:16 Dynamic Auto-Pan & Action Focus
  - 1080p60 Ultra HD Render (NVENC GPU)
  - 720p Fast Mobile Speed Export
  - 1:1 Square Multi-Platform Grid
  - 4K Vertical UHD Mastering (2160x3840)

### 3. Streamer Catalog & Workspace Management
- Click **"Streamer Catalog (30 Streamers)"**.
- Browse verified streamers across Twitch, YouTube, and Kick.
- Click **"Add All to Workspace"** to populate all 30 creator workspaces with 9:16 crop rules, rights cleared, and trigger words ("clip that, clip it") automatically.

### 4. Live Stream & AI Brain HUD ("Alarm Dark")
- Click **"Live Stream & Brain HUD"** to preview active streams.
- Observe real-time loudness dB meters, streamer speech dialogue tickers, and transparent AI Brain decision logs.

### 5. UI Diagnosis & Health Monitor
- Click **"UI Diagnosis & Health Monitor"** under Diagnosis & Insights to run an instant health check on your GPU encoder, offline speech latency, free disk storage, and typography layouts.

---

## 🔄 Updating to the Latest Version

Double-click `update-mj-cliproom.bat` or run:
```powershell
git pull origin main
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Your saved clips, creators, database, and AI keys are stored safely in the data folder and persist across updates.

## 24/7 Autonomous Clipping

Turn on **24/7 Autonomous Mode** from the homepage dashboard. The background worker autonomously polls trending GTA 6 streams and fresh gameplay every 20-30 minutes, producing 9:16 vertical shorts continuously.

## Music folder

Uploads and a folder scan only accept audio you confirm you have the rights to use. Set `PEAKCUT_MUSIC_DIR` in `.env` when that folder is outside your home directory and outside the data folder.

## Notes

OpenCV is installed from `opencv-python-headless` for facecam detection. Optional `espeak-ng` speaks original shorts when you have not uploaded a voice file. Custom YouTube thumbnails need a channel YouTube allows to set them.
