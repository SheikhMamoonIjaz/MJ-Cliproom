# Changelog

User-facing changes to MJ-Cliping are listed here.

## 1.2.0 — 2026-11-19

- **24/7 Autonomous Autopilot & Persistence:**
  - Background autonomous clipping loop runs continuously every 20–30 minutes, discovering live streams and viral gaming moments.
  - State persistence saved in `autonomous.json` ensures Autopilot automatically resumes across server restarts or VPS reboots without requiring manual intervention.
  - **Quota Guard & Multi-Provider AI Failover:** If the primary AI provider (e.g. Gemini) encounters a rate limit (`HTTP 429`) or quota cooldown, Autopilot automatically shifts to secondary providers (e.g. Z.AI GLM / OpenAI) and falls back to signal-based detection (audio loudness dB spikes and facecam motion) so stream capture never halts.
- **Maximized Daily Quota (10,000+ Clips/Day):**
  - Removed artificial daily ceilings for both manual video uploads and automated clipping workflows (`DAILY_VIDEO_QUOTA = 10000`).
- **8 Video Rendering Formats:**
  - Dedicated interactive modal selector offering 8 rendering configurations:
    1. Pure 9:16 Fullscreen Vertical (1080x1920)
    2. 9:16 Stacked Split (Streamer Facecam Top 35% + Gameplay Action Bottom 65%)
    3. 9:16 Ambient Mirror Background (Blurred 16:9 mirror backing)
    4. 9:16 Dynamic Auto-Pan & Action Focus (Crosshair tracking)
    5. 1080x1920 60FPS Ultra HD Render (NVIDIA NVENC GPU acceleration)
    6. 720x1280 Fast Mobile Speed Export (<5 second turnaround)
    7. 1:1 Square Multi-Platform Grid (1080x1080 social feeds)
    8. 4K Vertical UHD Mastering (2160x3840 upscale)
- **Creator & Channel Management:**
  - Integrated 30-streamer catalog across Twitch, YouTube, and Kick (Kai Cenat, xQc, IShowSpeed, Jynxzi, CaseOh, Adin Ross, Buddha, summit1g, DarkViperAU, etc.).
  - 1-Click "Add All to Workspace" syncs all 30 streamer workspaces with pre-configured 9:16 layouts, auto-watch enabled, and custom trigger phrases ("clip that, clip it").
  - Multi-channel support for simultaneously managing YouTube Shorts, TikTok, Instagram Reels, and Kick Clips.
- **Content Creation 6 Feature Add-ons:**
  - **Series Maker:** Automatic episodic series formatting (`Part 1`, `Part 2`, `Part 3`) across clip batches.
  - **Natural AI Voiceover:** Narration persona presets (Hype, Mystery Lore, Esports Breakdown, Comedy).
  - **Animated Captions (ASS Presets):** Word-by-word karaoke typography with bold outlines, neon glows, and custom highlight colors.
  - **Auto-Zoom & Face Focus:** Automatic punch-in on shouting, reactions, and volume spikes.
  - **Map & Location Overlays:** Mini-map coordinate badges and Vice City location stamps burned directly into clips.
  - **Copyright & DMCA Risk Scanner:** Proactive audio and transcript scanning detecting licensed radio music and strike hazards.
- **UI Diagnosis & Health Monitor:**
  - Live system inspection checking hardware GPU video encoders (NVENC/QSV), local Sherpa-ONNX speech latency (<0.3s), available disk storage, and zero-overlap UI layout integrity.
- **Desktop Shortcut Installer:**
  - Automated PowerShell installer now generates a 1-click desktop shortcut (`MJ-Cliping.lnk`) pointing to the local studio launcher.

## 1.1.0 — 2026-11-19

- **Pure 9:16 Vertical Video Enforcement:**
  - Removed wide 16:9 video layouts in favor of pure 9:16 mobile-first short-form video.
  - Enhanced streamer facecam auto-detection using OpenCV to lock onto the streamer's reaction box.
- **Streamlined Minimalist UI/UX:**
  - Redesigned home interface and workspace controls with zero visual overlap, eliminating clipping option boundary glitches.
  - Upgraded live preview player supporting real-time stream embedding for Twitch, YouTube, and Kick.
- **Alarm Dark AI Brain HUD:**
  - High-contrast visual viral alarm banner, real-time loudness dB meter, live dialogue subtitle ticker, and live AI Brain decision feed.
- **Fixed Autopilot & Storage Fetch Errors:**
  - Resolved "failed to fetch" network exceptions on storage and autopilot sync endpoints with resilient error handling.

## 1.0.1 — 2026-11-18

- Removed the permission checkboxes and server checks that blocked recording, clipping, Autopilot and uploads.
  Any saved creator can be recorded and clipped. Signal-only clips still wait in the review queue unless Full auto
  is on for that source. YouTube privacy still defaults to private.

## 1.0.0 — 2026-11-18

- Production release. Version labels no longer say beta. Startup logs to the data folder and names MJ Cliproom.
- Windows `install-mj-cliproom.bat` creates `.venv` and installs the pinned requirements, including OpenCV.
- The clip editor trims on the waveform, splits and merges cuts, reorders them, sets per-cut speed, and previews the hook and caption position. Undo and redo are in the editor.
- Layout choices include full frame, stacked, split and crop. Caption style, caption position, hook text and the MJ title tag are edited before the next render. Thumbnails can be redrawn from the editor.
- Music accepts an owner's mp3, wav, m4a, ogg or flac after they confirm they have the rights. A local folder can be scanned the same way. Each clip sets volume, ducking, fade in, fade out and a start offset.
- Page layout keeps controls reachable at laptop widths and on a phone. Help text in forms stays visible on a narrow screen. Focus outlines are visible from the keyboard.

## 0.12.0 — 2026-11-18

- A YouTube upload stores its resumable session address and continues that same upload after a crash.
- Facecam layout uses a face detector when OpenCV is installed, and the busiest corner when it is not.
- Kick chat is read and counted in the live spike detector, the same way Twitch chat is.
- Each clip card shows the full viral-score breakdown. Thumbnails are drawn from the busiest moment, in
  1280×720 and a vertical Short cover, and can be edited before upload.
- A post package writes five titles, three hooks, a source-credited description, hashtags, a pinned comment,
  and captions for TikTok, Reels, Facebook and X. It does not invent events and does not call GTA 5 GTA 6.
- The review queue accepts A or P to approve and post, and X to dismiss. A daily summary is shown in the app
  and sent through Discord or Telegram when those alerts are already set. Permission notes are still not emailed.
- Authorized rights can expire. A missing language tag no longer skips a Latin title, and English speech is kept
  even when the page names another language.
- Original shorts can be generated and posted from your own words, with no third-party footage. Someone else's
  footage still uploads only from an allowlisted, unexpired Authorized source.
- Post all queues every finished clip of a video. Starting a live session checks that the stream has begun.

## 0.11.0 — 2026-11-18

- Added Autopilot for the MJ Plays GTA creator list. It watches those channels (and any campaign source you add),
  records only confirmed English GTA 6 streams, and uploads only after you set the source to Authorized on the
  allowlist. GTA 5 is skipped and is never called GTA 6.
- The clip queue shows a preview before a scheduled upload. Signal-only moments wait for approval. A viral score
  is stored separately and does not grant permission. Permission notes are drafts you copy. They are not emailed.
- Live clips can use stacked or split gameplay and facecam layouts, a busiest-corner facecam choice, sentence-aware
  cuts, highlighted captions, hook text, MJ Plays GTA intro and outro, loudness normalization, and an optional
  commentary track. A full-frame layout keeps corner watermarks in view.
- Background music accepts only royalty-free or owner-licensed tracks, with genre, mood and attribution. Chart
  songs are refused. Pixabay results are used only when you set a key, and only from Pixabay's own files.
- Uploads keep a YouTube quota budget, a gap between posts, a retry with backoff, and a resume after a restart.
  Several recordings can run at once, up to the number you set and the server's live ceiling.
- A source file outside its job folder is no longer opened. A partial gameplay scan no longer crashes. A live
  render keeps the buffer file it is reading. Channel lookups no longer follow a redirect off YouTube, Twitch or Kick.

## 0.10.3 — 2026-11-16

- Expanded each of the ten AI-ranked clip suggestions into a complete post package: a factual title, a realistic short
  description, and relevant gaming hashtags. Apply or copy the full package, or apply only its title. The prompt uses
  viral-style hooks without inventing events or promising reach; hashtags are topic-specific rather than a live trend feed.

## 0.10.2 — 2026-11-16

- Fixed the missing `brain` import that blocked the new AI title suggestions endpoint.

## 0.10.1 — 2026-11-16

- Added ten ranked, clip-specific AI title suggestions using the active LLM profile. Apply a title without changing
  the description or hashtags; titles aim for strong viewer interest but cannot guarantee virality.
- Added `update-mj-cliproom.bat` for Windows. It starts the supervised launcher when needed, asks the app's updater
  to apply a safe fast-forward, leaves the configured storage folder in place, and opens the app after restart.

## 0.10.0 — 2026-11-16

- Added a first-run What’s New dialog and an [installation and update guide](docs/INSTALL.md).
- Queue a finished gameplay video with a prompt. Review the clips or, with separate authorization, schedule
  eligible clips for selected YouTube and Instagram accounts. Export clips to review and share manually on TikTok.
- Added named AI profiles, active model selection, testing, and optional independent backups. A rate-limited
  provider cools down without cycling its keys. Provider API access is separate from ChatGPT subscriptions.
- New workspaces have no local daily post cap. Existing caps are preserved; set the local cap to 0 for unlimited
  scheduling. Account limits and shared quotas pause affected queues.
- Cancel, resubmit or retry posts from Home, or revoke automatic publishing from a video card.
- The launcher verifies a fast-forward from the configured GitHub branch, with optional trusted signatures.
  It stages dependency changes separately, applies the update after shutdown, and reopens the app in the same tab.
- Kept uploaded videos, thumbnails, generated clips, creator settings, job history, speech data, and resumable
  download files in the selected storage folder. Updating the app does not clear or relocate that folder.
- Added a visible link from the clipping page to the storage setting, where the active upload and media folder can be
  opened or changed. Folder changes still take effect on the next restart so active files are not moved mid-job.
- Preserved retry behavior across restarts: unfinished jobs resume from saved checkpoints, and partial source downloads
  resume when the source platform permits it.
- Added recovery for interrupted multi-part browser uploads. Completed pieces and upload settings stay in the selected
  storage folder for six hours; after a restart, choose the original file to verify it and continue sending.
- Added a version capability check so a newer page blocks clipping, rendering, and posting when the running backend
  has not restarted onto the matching code.
- Kept the posting controls for direct publishing and configurable 15–20 minute scheduling. YouTube posting still
  requires a connected channel and content rights confirmation.
- Fixed Post now so the title, description and hashtags currently in the editor are saved and sent with the upload.
  YouTube receives them as both Shorts description text and video tags, and each queued post keeps its own snapshot.
- Replaced old source-title and timestamp metadata with distinct gameplay-first title and description drafts for each
  clip. AI title ideas now receive the game and clip transcript, not the stream or channel name; local drafts remain
  available when no AI provider is configured. Drafts do not promise views.
- Added a separate LLM API action that returns ten ranked title choices for one clip, with a short angle and transcript
  evidence. Applying a choice updates only the title, keeping the clip description and hashtags intact.
- Prevented generic "Untitled clip" hooks from being burned into new or re-made renders. Older rendered videos keep
  their baked overlay until the owner confirms source permission and re-makes those clips.
- Renamed the clip-card action to Review post, clarified missing rights and account blockers, and made Upload now
  explicitly use the connected account API while keeping status and the resulting link inside MJ Cliproom.
- Added ten curated official NCS track pages with copyable attribution. Track audio stays outside the open-source
  repository; download an instrumental version from NCS and add it to your local library before using it.
- Kept licensed instrumental music at a 30% starting level, with fades, ducking under prominent source audio,
  and peak limiting. Audition the result in the editor before publishing.
