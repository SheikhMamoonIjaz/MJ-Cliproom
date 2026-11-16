# MJ Cliproom 0.10 beta

See the [changelog](../CHANGELOG.md) and the [YouTube setup and test guide](YOUTUBE_AUTOMATION.md).

## Install

Follow the [installation steps](../README.md#requirements) for Git, Python and FFmpeg. Clone the fork,
create its virtual environment, install requirements, then run `python -m studio.launcher` from the
checkout. Open the address printed in the terminal (default http://127.0.0.1:8765). The queues
run with the browser closed as long as the server and computer stay awake and online.

## Update a launcher installation

An owner can choose **Update now → Install and restart**. The fetched commit must match the configured
GitHub branch and be a fast-forward of a clean checkout. After the server shuts down, the launcher
stages changed dependencies in a separate environment, updates the checkout and starts the new version.
The browser refreshes after the new server answers. Finish active live recordings and social uploads
and resolve pending Storage moves first. A rejected update or dependency failure keeps the previous checkout.

On Windows, double-click `update-mj-cliproom.bat` in this checkout. It starts the supervised launcher if needed and
requests the same verified update. If sign-in is enabled, it opens the app so an administrator can sign in and use
**Update now → Install and restart**.

To require signatures, set `PEAKCUT_UPDATE_REQUIRE_SIGNATURE=1` and configure Git to trust the
release maintainer's signing key outside the repository. For SSH see
[Git's allowed signers setting](https://git-scm.com/docs/git-config#Documentation/git-config.txt-gpgsshallowedSignersFile).
Use `git verify-commit` for a stopped-server manual update.

The `v0.10.0-beta` tag is signed with the one-time beta release key. The public
[allowed signers entry](mj-beta-0.10.allowed-signers) has fingerprint
`SHA256:JBWV5dl7SGB/0EugsC4vIMmAMiYQ11Azg+zc+QDxU+k`. Check the fingerprint against a
trusted copy before using the entry. Store it outside the checkout and point Git at it before
running `git verify-tag v0.10.0-beta`. Use the signing key published for each future release.

## Bootstrap an older Windows installation

1. Note the exact live path under **Settings → Storage**. Resolve any pending move, finish active
   work, then use Ctrl+C in the original server window or the service's normal Stop command.
   Back up the existing storage configuration and data before maintenance.
2. Open PowerShell in the installed checkout (normally `%LOCALAPPDATA%\Programs\PeakCut`).
   Continue only if `git status --short` is empty and `git branch --show-current` prints `main`.
   If `git remote -v` still lists the original PeakCut project as origin, set origin to the fork.

~~~powershell
git remote set-url origin https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
git fetch --no-tags origin main
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git merge --ff-only --no-overwrite-ignore FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "Update refused; check the branch and local files" }
~~~

3. Keep the existing `.env`, `storage.json` and storage directory. If the old terminal set
   `PEAKCUT_DATA` or `PEAKCUT_STORAGE_FILE`, restore that same setting before starting. Leave
   `PEAKCUT_DATA` unset if Settings → Storage already saved the correct path. Keep the same port
   and public URL. Run `python -m pip install -r requirements.txt` if dependencies changed,
   then open the desktop shortcut or run `python -m studio.launcher` using the install's virtual
   environment. Verify the version and **Settings → Storage** before queuing new work.

For later manual updates, leave origin unchanged, stop the app, fetch the configured branch and
merge fast-forward. If you installed from a ZIP, use a new Git checkout and configure the same
storage path before opening it. Only one server should use a given storage folder.

## Run the queues

- Under **Settings → AI**, save a profile and select its model. Only enable backup services that
  can receive video context and incur API charges. ChatGPT subscriptions are separate from API access.
- Under **All videos → Queue with a prompt**, enter a finished gameplay video you own or have clearance
  to edit. Review the clips yourself or separately authorize publishing to exact YouTube or Instagram
  destinations. Choose the visibility for YouTube. Signal-only picks stay in review.
- Retry a failed video, cancel a waiting download, resubmit with a different prompt, or revoke automatic
  publishing from its video card. Cancel, resubmit or retry individual posts from Home. If a previous
  upload was interrupted, check the channel before retrying to avoid duplicates.
- New workspaces have no local cap. Set an existing workspace's local daily limit to 0 for the same
  behavior. Platform cooldowns survive restart and retries keep the original destination.
- Download and review clips for manual TikTok sharing. [TikTok's Direct Post guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines)
  require the user to review and consent to the finished post.
