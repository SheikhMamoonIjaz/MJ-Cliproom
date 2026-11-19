# MJ-Cliping · v1.2.1 (24/7 Autonomous AI Stream Clipping & Multi-Platform Production Studio)

[What's new](CHANGELOG.md) · [Install or update](docs/INSTALL.md)

**A high-performance gaming video clipping studio for gameplay recordings, streams, and 24/7 autonomous short-form creation.** Find viral moments, shape them into pure 9:16 vertical clips, add animated captions, and export videos ready for YouTube Shorts, Instagram Reels, or TikTok with zero manual bottlenecks.

MJ-Cliping is maintained by [Sheikh Mamoon Ijaz](https://github.com/SheikhMamoonIjaz). It is an independent, gaming-first fork of [PeakCut](https://github.com/haziqahmedqasmi/PeakCut). This fork keeps the upstream MIT license and credits; see [CREDITS.md](CREDITS.md).

## Version 1.2.1 Feature Architecture

### 1. Automation & Growth (The 4 Core Pillars)
- **Autopilot Posts & Review Queue:** Dedicated review dashboard for all clips created by 24/7 Autopilot with real-time renderer inspection.
- **1-Click 10-Minute YouTube Auto-Scheduler:** Instant 1-click scheduling with a live ticking second-by-second countdown automatically uploading to YouTube Shorts in 10 minutes.
- **AI Viral Metadata & Trending Hashtags:** Generates high-retention titles, meta descriptions, and viral gaming tags (`#GTA6 #Shorts #Gaming #Viral #Trending #GTAGameplay #TwitchClips`).
- **Trend Radar:** Real-time viral topic detection, curiosity hooks, and high-growth hashtags for GTA 6 and top gaming titles.
- **Daily Compilation Video:** 1-click ffmpeg concat demuxer stitching daily top-performing clips into a master highlight recap.
- **Multi-Platform Posting:** Automated tailored caption, hashtag, and aspect ratio formatting for YouTube Shorts, TikTok, and Instagram Reels.
- **24/7 Smart Autopilot:** Continuous background clipping loop scanning live streams every 20–30 minutes with failover guard and auto-persistence across restarts.

### 2. The 8 Video Rendering Formats
1. **Pure 9:16 Fullscreen Vertical (1080x1920):** Direct full-bleed vertical crop optimized for viral mobile retention.
2. **9:16 Stacked Split (Facecam + Gameplay):** Streamer facecam on top 35%, gameplay action on bottom 65%.
3. **9:16 Ambient Mirror Background:** Original 16:9 gameplay center-framed over a real-time blurred ambient mirror.
4. **9:16 Dynamic Auto-Pan & Action Focus:** Intelligent motion and crosshair tracking for fast-paced shooters.
5. **1080x1920 60FPS Ultra HD Render:** High-bitrate 60fps export utilizing NVIDIA NVENC GPU acceleration.
6. **720x1280 Fast Mobile Speed Export:** Lightweight ultra-fast render exported in under 5 seconds for instant turnaround.
7. **1:1 Square Multi-Platform Grid (1080x1080):** Social feed format tailored for Instagram and X feeds.
8. **4K Vertical UHD Mastering (2160x3840):** Ultra-crisp 4K vertical upscale for studio-grade channel archives.

### 3. Creator & Channel Management (The 4 Pillars)
- **Multi-Channel Support:** Manage multiple linked channels across YouTube Shorts, TikTok, Instagram Reels, and Kick.
- **Streamer Catalog & 1-Click Sync:** Integrated directory of 30+ top streamers (Kai Cenat, xQc, IShowSpeed, Jynxzi, CaseOh, Adin Ross, etc.) with 1-click workspace sync.
- **Creator Rights & Permission Allowlist:** Streamer rights status tracking, DMCA safe verification, and automated safe-list filters.
- **Auto-Posting Queue & Publishing Schedule:** Automated release queue with configurable intervals (15–20 minutes) and manual approval locks.

### 4. Content Creation Add-ons (The 6 Add-ons)
- **Series Maker:** Automatic episodic series formatting (`Part 1`, `Part 2`, `Part 3`) across clip batches.
- **Natural AI Voiceover Prompts:** Narration personas (Hype, Mystery Lore, Esports Breakdown, Comedy) for short-form intros.
- **Animated Captions (ASS Presets):** Word-by-word karaoke typography with bold outlines, neon glows, and custom highlight colors.
- **Auto-Zoom & Face Focus Effects:** Automated camera zoom punch-ins on shouting, reactions, and intense moments.
- **Map & Location Overlays:** Mini-map coordinate badges and Vice City location stamps burned directly into clips.
- **Copyright & DMCA Risk Scanner:** Proactive audio and transcript scanning detecting licensed radio music and strike hazards.

### 5. UI Diagnosis & Analytics
- **Analytics Dashboard:** Visual tracking for total clips created, platform breakdown, viral potential scores, and average render speeds.
- **Mobile Approval Dashboard:** Mobile-friendly remote swipe interface for rapid 1-tap Approve, Reject, or Star review.
- **UI Diagnosis & Health Monitor:** Real-time hardware GPU encoder status, Sherpa-ONNX local speech latency check, free disk space, and layout integrity audit.

## Requirements

- Python 3.10 or newer (Python 3.12 or 3.13 recommended)
- Git
- FFmpeg and FFprobe on your PATH (with NVENC support recommended for GPU rendering)
- An AI service key (Google Gemini, Z.AI GLM, Grok, OpenAI, or local Ollama) is optional. Without one, highlight selection uses built-in audio-visual signals.

The first run fetches the speech-recognition model (about 480 MB). The model runs locally on your machine.

## Quick Start / Installation

### Install on Windows (Recommended)

1. Open PowerShell and install FFmpeg:

   ```powershell
   winget install --id Gyan.FFmpeg -e
   ```

   Close and reopen PowerShell after installation so FFmpeg is on your PATH.

2. Clone the repository and enter the directory:

   ```powershell
   git clone https://github.com/SheikhMamoonIjaz/MJ-Cliping.git
   cd MJ-Cliping
   ```

3. Run the automated installer, or execute the steps manually:

   ```powershell
   # Automated installer (installs packages and creates Desktop shortcut automatically):
   .\install-mj-cliproom.bat

   # Or manual PowerShell setup:
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt

   # Create 1-click Desktop Shortcut:
   .\create-desktop-shortcut.bat
   ```

4. Launch MJ-Cliping:

   ```powershell
   .\.venv\Scripts\python.exe -m studio.launcher
   ```

5. Open [http://localhost:8765](http://localhost:8765) in your web browser.

### Install on macOS

```bash
# 1. Install prerequisites via Homebrew
brew install python git ffmpeg

# 2. Clone repository
git clone https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
cd MJ-Cliproom

# 3. Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Start studio server
python -m studio.launcher
```

### Install on Linux (Ubuntu / Debian)

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg

# 2. Clone repository
git clone https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
cd MJ-Cliproom

# 3. Set up environment and install Python packages
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Start studio server
python -m studio.launcher
```
   python -m studio.launcher
   ```

6. Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The first launch downloads the speech model. Keep the
   PowerShell window open while you use the app.

## Install on macOS

1. Install Homebrew if needed, then install Python, Git and FFmpeg:

   ```bash
   brew install python git ffmpeg
   ```

2. Clone the repository and set up the environment:

   ```bash
   git clone https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
   cd MJ-Cliproom
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Start the app and open [http://127.0.0.1:8765](http://127.0.0.1:8765):

   ```bash
   python -m studio.launcher
   ```

## Install on Linux

On Debian or Ubuntu, install the system packages first:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg
```

Then install and start MJ Cliproom:

```bash
git clone https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
cd MJ-Cliproom
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m studio.launcher
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Other Linux distributions need equivalent Python 3, venv,
Git and FFmpeg packages.

## First-time setup

1. Go to **Settings → AI**, choose a provider, enter its API key and press **Save and test**. The key is stored in
   MJ Cliproom's local data folder. You can also use a local Ollama model or leave AI unconfigured.
2. Return to the clip workspace. Paste a finished video or VOD link, or upload a local gameplay recording.
3. Choose **Gameplay** to scan for highlights, **Manual** to start with your own cuts, or **Replay Picker** to choose
   from supported past broadcasts.
4. Set the clip count, length, layout, caption style and optional motion or watermark settings, then choose **Make
   clips**. Confirm that you own the source or have permission to download, edit and publish it. Creator live
   recording has a separate confirmation under **Setup → Their stream**.
5. Follow the download and render progress. If a job fails, the failure card explains the stage and provides a
   **Retry download** or **Retry video** button. Retries reuse the saved partial download whenever possible.
6. Open a finished clip to edit its title, description, hashtags, crop, caption timing and export options. Download
   the MP4 or SRT, or add the clip to a Clip Set for a batch export. Use **Generate title ideas** for Shorts copy or
   full-source video copy. Shorts ideas can be applied to the clip; full-video ideas can be copied for the original.
   Add licensed instrumental audio in the clip editor to mix it under the source audio.

For YouTube posting, open **Settings → Connected apps → YouTube → Continue with Google**. Approve the requested
YouTube access, then select the connected channel in a creator's **Setup**. The existing posting queue can schedule
or automatically publish reviewed clips. Google OAuth credentials and YouTube Data API v3 must be configured by
the server administrator first; see [DEPLOY.md](DEPLOY.md#connecting-youtube-instagram-and-tiktok).
For the full channel connection, top-10 gameplay workflow, direct-post and scheduled queue instructions, retry behavior,
and background-music notes, see [YouTube Shorts automation](docs/YOUTUBE_AUTOMATION.md).

The music picker accepts user-supplied audio only. Use tracks you own or have permission to use. YouTube's Shorts
licensed music catalog has to be added in YouTube's own creation tools; Cliproom does not fetch trending songs.
The app can improve candidate ranking and metadata, but no AI can promise a clip will go viral.

For a live stream, add its channel under **Creators → Setup**, then choose **Record live stream** when it is on air.
Use the live workspace to monitor the stream and clip the recent buffer. Availability depends on the platform,
stream privacy and the stream URL being accessible to the machine running MJ Cliproom.

## Autopilot

**Autopilot** watches the saved creator list for English GTA 6 streams, records a few at a time, and can upload
Shorts to a connected YouTube channel. It is off until you turn it on. There is no permission checkbox.
Signal-only moments stay in the queue for a preview unless you turn on full auto for that one source.
YouTube posts stay private unless you change that on the Autopilot page.

1. Connect YouTube under **Settings → Connected apps**. Google OAuth and YouTube Data API v3 have to be set up
   first. See [DEPLOY.md](DEPLOY.md#connecting-youtube-instagram-and-tiktok). A new Google project usually has
   10,000 quota units a day. One upload costs about 1,600, so the default budget stops at 8,000.
2. Open **Autopilot**. Confirm any handle marked unchecked before that row is watched. The dictated names Nogla,
   TGG, Treyten, SpeirsTheAmazingHD, Putther, TheProfessional and Adin Ross (Kick) are not watched until you tick
   **Handle checked**.
3. Turn on **Full auto** only for a source whose clips should post without waiting in the review queue.
4. Set how many streams may record at once (1–32). The server also has `PEAKCUT_MAX_LIVE`. Raise that in `.env`
   if you want more than the machine's default ceiling. Watching the list does not record all of them at once.
5. Turn Autopilot on. It keeps running while the app process is up. Docker restarts the container. On a computer,
   `python -m studio.supervise` starts it again after a crash.

Clips use a gameplay-and-facecam stack, captions with the spoken word highlighted, an MJ Plays GTA intro and outro,
and a cut that finishes the sentence when the transcript allows it. The description names the source and links it.
GTA 5 categories and titles are skipped and are never relabelled as GTA 6. Add your own commentary track on the
Autopilot page if you want a narration over the stream. Background music has to be royalty-free or supplied by
you. See [YouTube Shorts automation](docs/YOUTUBE_AUTOMATION.md).

A saved YouTube upload session is continued after a restart, so the same video is not posted twice. Facecam
layout looks for a face when OpenCV is installed (`opencv-python-headless`) and otherwise uses the busiest
corner. Kick chat is counted the same way as Twitch chat. Each clip card shows the viral-score breakdown.
Thumbnails are drawn from the busiest moment and can be edited before upload. YouTube receives the wide
thumbnail when the channel is allowed to set one. A post package offers five titles, three hooks, a description
with the source credit, hashtags, a pinned comment, and captions for TikTok, Reels, Facebook and X. Those lines
use only the words already on the clip.

In the review queue, **A** approves and posts, **P** does the same, and **X** dismisses. A daily summary stays
on the Autopilot page and is sent to Discord or Telegram when those alerts are already configured. Permission
notes stay as copy drafts. A rights label is not required before a source is recorded or posted.
A stream with no language tag is kept when the title is Latin, and clear English speech is kept even if the
page says another language. Confirmed Hindi, Urdu and other non-English speech is still skipped.

**Original shorts** is a separate switch. It makes a vertical video from your own script, optional voice track
or espeak, and royalty-free music. It does not use another creator's footage. Other clips wait in
review unless Full auto is on for that source.

## AI providers

Choose a provider in **Settings → AI**. Provider names and model IDs can change; check the provider's current model
list and pricing before use. Hosted providers bill you directly. Speech recognition runs locally; when AI is enabled,
text and metadata required for AI clip selection are sent to the selected provider.

| Provider | Configuration |
|---|---|
| Gemini | Select Gemini in Settings and add a Google AI Studio key |
| OpenAI, Anthropic, Grok, Groq | Select the provider and add its key |
| OpenRouter or OpenRouter Free | Use its key and a currently available model ID; free-tier rate limits apply |
| Z.AI / GLM, DeepSeek, Qwen | Use the provider's key, model ID and compatible endpoint shown in Settings |
| Ollama | Run Ollama locally, pull a model and select it in Settings |
| Custom OpenAI-compatible API | Enter the service's base URL, model ID and key |

The dashboard's **AI usage** page shows recorded provider calls and token use. Keep credentials in the app's settings
or in `.env`; never commit real keys.

## Files, retries and cleanup

By default, MJ Cliproom stores uploaded videos, source thumbnails, clips, settings, job history, and its speech model
under `data/`. **Settings → Storage** shows the active folder, lets you open it, and lets you choose a new default
location. You can also open Storage from the clipping page's **View upload folder** link. A folder move is prepared
while the app is running and takes effect at the next start; when selected, the existing data is carried over first.

Start a Git installation with the launcher to use **Update now**. It verifies a fast-forward from the
configured GitHub branch, stages changed dependencies separately when needed, and applies the update after the
server has stopped. The browser reloads after the updated server is healthy. Your storage path and its contents
stay in place. See the [install guide](docs/INSTALL.md) for Windows setup, stopped-server updates and signatures.

Failed downloads keep a `.part` file when the downloader can resume it. Use **Retry download** on the failed job card
to continue; a platform may still reject a link or discard its old download URL, in which case try again later or
upload the source file. Large browser uploads keep completed pieces for six hours across restarts. Select the same
original file from the saved-upload card to continue; the app checks its name, size and file samples before reusing any
pieces. After a restart, queued video work picks up from saved checkpoints; unfinished live recordings can only
recover from pieces that are still on disk.

Use the source cleanup control on a video card to schedule or cancel removal of the downloaded source after clips
finish. Generated clips and job history are separate. Back up the `data/` folder and, on a deployed server, the
database before moving or removing stored data.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Configuration

Copy `.env.example` to `.env` only when you need to change server settings. The dashboard is easier for local use.
Common settings include:

| Setting | Purpose |
|---|---|
| `PEAKCUT_PORT` | Local server port; defaults to `8765` |
| `PEAKCUT_DATA` | Data folder; defaults to `./data` |
| `PEAKCUT_AI_PROVIDER`, `PEAKCUT_AI_MODELS`, `PEAKCUT_AI_KEY` | Optional AI provider settings |
| `PEAKCUT_ACCOUNTS=1` | Require account sign-in; use for a server shared with other people |
| `PEAKCUT_PUBLIC_URL` | Public HTTPS address for a deployed site |
| `PEAKCUT_UPDATE_CHECK=0` | Disable the in-app update check |

The full settings list and comments are in [.env.example](.env.example). `.env`, `secrets/`, databases and user
data are excluded from Git.

## Self-hosting

For a public server, configure accounts, HTTPS, a database and secrets before exposing the app. Follow
[DEPLOY.md](DEPLOY.md) for Docker, Caddy, PostgreSQL, OAuth posting setup, backups and optional GPU speech
recognition. Do not expose a local, sign-in-free instance to the internet.

## Troubleshooting

- **FFmpeg is missing:** install it (`winget install --id Gyan.FFmpeg -e` on Windows, `brew install ffmpeg` on
  macOS, or `sudo apt install ffmpeg` on Debian/Ubuntu), restart the terminal and restart MJ Cliproom.
- **A download timed out:** select **Retry download** on the failed job. The downloader retries transient network
  errors and resumes a saved partial when the source permits it. Some hosts block automated downloads; upload a
  local file or try again later.
- **AI is unavailable:** check the key, model ID, provider status and network connection in **Settings → AI**. Clip
  selection can still use the built-in signals without an AI key.
- **The browser cannot preview a source:** an H.264 MP4 is the most broadly supported upload format. You can still
  process files that FFmpeg supports even if the browser cannot preview them.
- **Not enough disk space:** check **Settings → Storage**, remove only files you no longer need, or move the data
  folder to a larger drive.

## Development

The backend is Python/FastAPI. The frontend is plain HTML, CSS and JavaScript in `web/`, with no frontend build
step. Contributor notes are in [AGENTS.md](AGENTS.md). Create an isolated data folder when trying risky changes:

```bash
PEAKCUT_DATA=/tmp/mj-cliproom-dev PEAKCUT_PORT=8766 python -m studio.server
```

## Credits and license

MJ Cliproom is maintained by [Sheikh Mamoon Ijaz](https://github.com/SheikhMamoonIjaz). It builds on the MIT-licensed
[PeakCut project](https://github.com/haziqahmedqasmi/PeakCut); the original license and attribution are preserved.
See [CREDITS.md](CREDITS.md) for provenance and font licenses. The project is released under the MIT License; see
[LICENSE](LICENSE). The in-app rights checkbox records your confirmation; it cannot verify permission for you. Clip
only videos you own or have permission to use, and follow the source platform's terms.
