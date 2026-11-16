# Changelog

User-facing changes to MJ Cliproom are listed here.

## 0.10 beta (v0.10.0-beta) — 2026-11-16

- Added a first-run What’s New dialog and a [beta installation and update guide](docs/BETA_0_10.md).
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
