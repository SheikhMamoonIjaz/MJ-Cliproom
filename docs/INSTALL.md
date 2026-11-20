# Install and update MJ-Cliping 1.3.1

## Requirements

Install Git, Python 3.10 or newer, and FFmpeg with FFprobe. Python 3.13 is the preferred Windows installer target. The first launch downloads the local speech recognition model. Leave enough disk space for source recordings, finished clips, and resumable downloads.

## Windows

1. Install Git and Python, then run `winget install --id Gyan.FFmpeg -e` in a terminal. Open a new terminal after the installation so it sees the updated PATH.
2. Clone the Git repository and install the Python dependencies.

   ```powershell
   git clone https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
   Set-Location MJ-Cliproom
   .\install-mj-cliproom.bat
   ```

3. Start the launcher.

   ```powershell
   .\.venv\Scripts\python.exe -m studio.launcher
   ```

4. Open the address printed in the terminal, usually [http://localhost:8765](http://localhost:8765). Keep the launcher open while you clip or post.

For manual dependency setup, run `py -3 -m venv .venv` and then `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` from the checkout.

## macOS and Linux

On macOS, install Git, Python and FFmpeg using `brew install git python ffmpeg`. On Debian or Ubuntu, use `sudo apt install git python3 python3-venv ffmpeg`. Then run the following from a terminal.

```bash
git clone https://github.com/SheikhMamoonIjaz/MJ-Cliproom.git
cd MJ-Cliproom
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m studio.launcher
```

Open the address shown in the terminal. See [DEPLOY.md](../DEPLOY.md) for a shared server with HTTPS, account sign-in and a persistent data directory.

## First launch

1. Open **Settings → Appearance** and choose **Light**, **Dark**, or **System**.
2. Open **Settings → AI**. Save an API provider and model, then test the profile. A local Ollama profile can also write metadata. Gameplay detection can work from signals with AI unconfigured.
3. Import a source in **All videos**. Wait for rendering to finish and open a clip to review its 9:16 frame and captions.
4. Follow the [YouTube setup guide](YOUTUBE_AUTOMATION.md) to connect a posting destination and enable YouTube topic research. For events, use the [tournament workflow](TOURNAMENT_WORKFLOW.md).

## Update an existing installation

Before applying an update, finish active recordings and uploads and resolve any pending Storage move. Check the data path in **Settings → Storage**, especially if it was previously set through `PEAKCUT_DATA` or `PEAKCUT_STORAGE_FILE`.

- **In the app:** With the supervised launcher running, choose **Update now → Install and restart**. The updater checks the configured GitHub branch and a clean checkout before applying a fast-forward. The browser refreshes when the updated server is ready.
- **Windows:** Run `update-mj-cliproom.bat` from the cloned project folder. Keep its PowerShell helper beside it. If sign-in is enabled, finish the update from the signed-in administrator session.
- **Older copies:** Use the [stopped-server bootstrap instructions](BETA_0_10.md#bootstrap-an-older-windows-installation) if the installer or update button is missing. Preserve `.env`, `storage.json`, and the selected data directory when switching checkouts. For a ZIP install, use a Git checkout for future supervised updates.

Keep the same local host and port for an existing YouTube OAuth setup, or register the updated redirect URI in Google Cloud. After restart, confirm the version and storage path before starting new jobs.
