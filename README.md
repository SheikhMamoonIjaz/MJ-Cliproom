# MJ Cliproom

**A gaming-focused video clipping studio for gameplay recordings and finished streams.** Find strong moments, shape
them into vertical clips, add captions and motion graphics, then export videos ready for Shorts, Reels or TikTok.

MJ Cliproom is maintained by [Sheikh Mamoon Ijaz](https://github.com/SheikhMamoonIjaz). It is an independent,
gaming-first fork of [PeakCut](https://github.com/haziqahmedqasmi/PeakCut). This fork keeps the upstream MIT
license and credits; see [CREDITS.md](CREDITS.md).

## Features

- Scan gameplay recordings and finished VODs for moments worth clipping, or make cuts by hand.
- Record supported live streams and clip highlights while a stream is running.
- Trim one or more ranges, reorder cuts, and animate the vertical crop between keyframes.
- Export vertical clips with timed captions, hook text, a motion title tag and an optional MJ watermark.
- Review titles, descriptions and hashtags; edit captions and save recurring spelling fixes in a glossary.
- Generate three grounded Shorts or full-video title/description drafts with the selected LLM. When YouTube is
  connected, current popular gaming-video titles can inform phrasing without copying them.
- Rank Gameplay candidates with picture/audio activity and, when speech recognition and an LLM are available,
  transcript context. Signal-only picks are kept out of automatic posting until a person reviews them.
- Add your own licensed instrumental background tracks, set their mix level, and duck them under the video's audio.
- Group selected clips into Clip Sets and export them together with subtitle files.
- Connect supported social accounts for scheduled or automatic posting. Platform app setup and review can be required;
  see [DEPLOY.md](DEPLOY.md#connecting-youtube-instagram-and-tiktok).
- See download and render progress with time estimates. If a download fails, **Retry download** resumes from the
  saved partial file when the source allows it.
- Run it locally without an account, or self-host it with accounts enabled. Bring your own AI key; highlight
  selection still works without AI using audio and visual signals.

## Requirements

- Python 3.10 or newer
- Git
- FFmpeg and FFprobe on your PATH
- An AI service key is optional. Without one, highlight selection uses the built-in non-AI signals.

The first run fetches the speech-recognition model (about 480 MB). The model runs on your machine; if AI is enabled,
the transcript and video metadata used for clip selection may be sent to the provider you choose.

## Install on Windows

1. Install Python 3.10+ and Git. During Python setup, enable the option to add Python to PATH.
2. Open PowerShell and install FFmpeg:

   ```powershell
   winget install --id Gyan.FFmpeg -e
   ```

   Close and reopen PowerShell after installation so FFmpeg is on PATH.

3. Clone the repository and enter its folder:

   ```powershell
   git clone https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
   cd MJ-Cliproom
   ```

4. Create and activate a virtual environment, then install the requirements:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

   If PowerShell blocks activation, use the venv interpreter directly:
   `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and
   `.\.venv\Scripts\python.exe -m studio.server`.

5. Start MJ Cliproom:

   ```powershell
   python -m studio.server
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
   python -m studio.server
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
python -m studio.server
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

The dashboard's **Update now** action downloads a fast-forward update from the configured GitHub repository and
installs changed Python requirements. It stops if the checkout has local edits, is not on the configured branch, or
does not match the configured GitHub repository. Updates change app files only; the selected data folder, cached
transcripts, finished clips, creator settings, and job history are kept. Restart MJ Cliproom after the update.

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
