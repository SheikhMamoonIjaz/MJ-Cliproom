# MJ-Cliping · 1.3.2

MJ-Cliping is a local gaming clip editor and YouTube Shorts scheduler. Import a recording or supported replay, pick a highlight, edit its captions and crop, then review and publish from the same workspace.

[Install or update](docs/INSTALL.md) · [YouTube setup and posting](docs/YOUTUBE_AUTOMATION.md) · [Tournament workflow](docs/TOURNAMENT_WORKFLOW.md) · [Changelog](CHANGELOG.md)

## What you can do

- Find highlights in local gameplay recordings and supported replays. Use AI for transcript-based selection or review picks based on activity signals.
- Render 9:16 Shorts. The streamer layout puts gameplay above a detected facecam and places captions near the bottom. Re-render older clips to export them in the new layout.
- Generate ranked YouTube titles, descriptions of at least 1,500 characters, and relevant hashtags using an active LLM profile. Add recent YouTube gaming results as research context and inspect the source links in the editor.
- Generate clip-specific post text that avoids titles and descriptions already saved for the channel. A separate opted-in provider can take over when the active AI service is unavailable or cooling down.
- Post a single rendered clip through the connected YouTube channel. Select up to 200 clips for a batch with a 10-minute interval after each successful upload. See [YouTube limits and scheduling](docs/YOUTUBE_AUTOMATION.md#4-review-the-queue-and-limits).
- The Autopilot Posts batch scheduler probes each video file before queueing and only accepts vertical 9:16 clips up to three minutes. Existing scheduled rows are reused when a batch is rebuilt.
- Choose Light, Dark, or System under **Settings → Appearance**. Preferences are saved in your browser.

## Install

MJ-Cliping requires Git, Python 3.10 or newer, and FFmpeg with FFprobe. On Windows, clone the project and run the installer from the project folder.

```powershell
git clone https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
Set-Location MJ-Cliproom
.\install-mj-cliproom.bat
.\.venv\Scripts\python.exe -m studio.launcher
```

Open [the local dashboard](http://localhost:8765) at the port printed in the terminal. The first run downloads the speech recognition model. See the [installation guide](docs/INSTALL.md) for Windows prerequisites, macOS and Linux commands, and update instructions.

## Make and publish a Short

1. In **All videos**, upload your gameplay or paste a supported replay link. Start in **Gameplay** mode to find highlights, or trim your own selection.
2. Open a finished clip and review the vertical framing, caption timing, sound and post text. Keep the original footage available if you need to re-render it.
3. For AI metadata, set up an active provider in **Settings → AI**. Generate researched post options in the clip editor and review the selected title, long description, and tags. Recent search titles help the LLM choose keywords. The captions and clip supply the facts.
4. In **Settings → Connected apps**, set up Google OAuth and connect the YouTube channel. Choose the destination and visibility. Start with a private upload and check it in YouTube Studio.
5. Post one clip from the editor or select several finished clips and schedule them together. Check the resulting upload status or retry from the queue. Keep MJ-Cliping running and the machine online while posts are due.

YouTube's API and channel limits govern uploads. A 200-clip batch is a queue capacity, and the 10-minute interval allows up to 144 upload slots across 24 hours before platform limits or upload time. See [Google's current quota details](https://developers.google.com/youtube/v3/determine_quota_cost).

## AI and topic research

Configure Gemini, Z.AI, OpenAI, Claude, Grok, Groq, OpenRouter, DeepSeek, Qwen, Ollama, or another compatible service in **Settings → AI**. The active model writes the post text. Independent fallback profiles are used only when enabled. For YouTube search references, connect a YouTube account or set `PEAKCUT_YOUTUBE_RESEARCH_KEY` to a YouTube Data API v3 key. The AI usage page records provider calls and token use.

Hosted providers receive the clip text needed for the selected feature and may charge according to your plan. Keep API credentials in Settings or in the local `.env` file. SEO suggestions use the clip's actual subject and public topic references. Review them for factual accuracy before posting.

## Live streams and tournaments

A creator workspace can monitor supported live channels while the app runs. Availability depends on the source platform, stream access, and your connection. Review what the app captured and confirm the rights to the footage and audio before publishing. The [tournament workflow](docs/TOURNAMENT_WORKFLOW.md) covers authorized sources, agent review, and scheduling.

## Storage and updates

**Settings → Storage** shows where MJ-Cliping saves the source videos, exports, speech model and history. The default is `data/` inside the checkout. A pending storage move takes effect the next time the server starts.

Run the server with `python -m studio.launcher` to use the supervised **Update now** action. On Windows, you can also use `update-mj-cliproom.bat` from the checkout. Finish active work before updating. The [installation guide](docs/INSTALL.md#update-an-existing-installation) covers both update paths and preserving a custom data location.

See [.env.example](.env.example) for settings, [DEPLOY.md](DEPLOY.md) for hosted installs, and [AGENTS.md](AGENTS.md) for contributor notes.

## Credits and license

[Sheikh Mamoon Ijaz](https://github.com/SheikhMamoonIjaz) maintains MJ-Cliping. It builds on the MIT-licensed [PeakCut project](https://github.com/haziqahmedqasmi/PeakCut). See [CREDITS.md](CREDITS.md) for provenance and third-party credits and [LICENSE](LICENSE) for the license.
