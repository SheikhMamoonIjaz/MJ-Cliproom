# Changelog

User-facing changes to MJ Cliproom are listed here.

## Unreleased

- Added an in-app updater for clean Git installs. It checks the configured GitHub repository, accepts fast-forward
  updates only, installs changed Python requirements, and reports failures without showing credential-bearing
  command output.
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
