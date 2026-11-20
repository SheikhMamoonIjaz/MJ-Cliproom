/* Source timeline and timed captions. Uses the app's existing API and session. */
const clipPresets = {
  action: {layout: "crop", style: "clean", captions: "burn"},
  gameplay: {layout: "auto", style: "clean", captions: "burn"},
  clean: {layout: "crop", style: "clean", captions: "clean"},
};

function getEditorStorage(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}

function putEditorStorage(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
}

function openSourceEditor(job, clip) {
  const dialog = $("#sourcedlg");
  const defaultsKey = "peakcut:clip-defaults:" + (S.status.user?.id || "local") + ":" + (job.creator || "all");
  const saved = clip || getEditorStorage(defaultsKey, {});
  const duration = job.duration;
  const length = Math.min(duration, 30);
  const fps = job.fps > 0 ? job.fps : 30;
  const sourceURL = "/api/jobs/" + encodeURIComponent(job.id);
  const markKey = "peakcut:marks:" + job.id;
  let markers = getEditorStorage(markKey, []);
  let peaks = [];
  dialog.innerHTML = `
    <form class="source-editor">
      <header><h2>${clip ? "Trim from source" : "Make a clip"}</h2>
        <button class="btn" type="button" data-action="close">Close</button></header>
      <div class="source-columns">
        <div>
          <div class="source-frame">
            <video controls playsinline preload="metadata" src="${sourceURL}/source" aria-label="Source video"></video>
            <div class="source-crop" aria-hidden="true" hidden></div>
            <div class="live-overlay" data-place="${esc(saved.caption_position || "bottom")}" aria-hidden="true"><b data-live-hook></b><span data-live-cap>Caption</span></div>
          </div>
          <p data-preview-note class="hint" hidden>Preview unavailable. Use the timeline times or upload a browser-compatible MP4.</p>
          <canvas height="66" aria-label="Audio waveform"></canvas>
          <label class="f">Playhead <output data-position>0.000 s</output>
            <input aria-label="Playhead" name="playhead" type="range" min="0" max="${duration}" step="0.001" value="0">
          </label>
          <div class="row">
            <button class="btn sm" type="button" data-action="previous">−1 frame</button>
            <button class="btn sm" type="button" data-action="next">+1 frame</button>
            <button class="btn sm" type="button" data-action="in">Set start</button>
            <button class="btn sm" type="button" data-action="out">Set end</button>
            <button class="btn sm" type="button" data-action="split">Split</button>
            <button class="btn sm" type="button" data-action="merge">Merge next</button>
            <button class="btn sm" type="button" data-action="earlier">Move earlier</button>
            <button class="btn sm" type="button" data-action="later">Move later</button>
            <button class="btn sm" type="button" data-action="undo">Undo</button>
            <button class="btn sm" type="button" data-action="redo">Redo</button>
            <button class="btn sm" type="button" data-action="mark">Add marker</button>
          </div>
          <div data-markers class="row timeline-markers" aria-label="Source markers"></div>
        </div>
        <div class="source-fields">
          <label class="f">Preset<select name="preset"><option value="">Custom</option>
            <option value="action">Full-screen gameplay</option><option value="gameplay">Gameplay with HUD</option>
            <option value="clean">Clean export</option></select></label>
          <div class="two">
            <label class="f">Start (seconds)<input name="start" type="number" min="0" max="${duration}" step="any" required value="${clip?.start ?? 0}"></label>
            <label class="f">End (seconds)<input name="end" type="number" min="0" max="${duration}" step="any" required value="${clip?.end ?? length}"></label>
          </div>
          <label class="f">Drag start <input name="inPoint" type="range" min="0" max="${duration}" step="0.001" value="${clip?.start ?? 0}"></label>
          <label class="f">Drag end <input name="outPoint" type="range" min="0" max="${duration}" step="0.001" value="${clip?.end ?? length}"></label>
          <div class="layout-picks" role="radiogroup" aria-label="Layout">
            ${[["auto", "Auto facecam"], ["stack", "Facecam below"], ["crop", "Full-screen"]].map(([id, label]) =>
              `<button type="button" class="btn sm" data-layout="${id}" aria-pressed="false">${label}</button>`).join("")}
          </div>
          <div class="two">
            <label class="f">Layout<select name="layout">${opts(S.status.layouts, saved.layout || job.options?.layout)}</select></label>
            <label class="f">Caption style<select name="style">${opts(S.status.styles, saved.style || job.options?.style)}</select></label>
          </div>
          <label class="f">Caption position<select name="caption_position">
            <option value="bottom">Bottom</option><option value="middle" ${saved.caption_position === "middle" ? "selected" : ""}>Middle</option>
            <option value="top" ${saved.caption_position === "top" ? "selected" : ""}>Top</option></select></label>
          <label class="f">Speed of the cut under the playhead<input name="speed" type="number" min="0.5" max="2" step="0.05" value="1"></label>
          <div class="two">
            <label class="f">Crop left to right<input name="crop_x" type="range" min="0" max="1" step="0.01" value="${saved.crop_x ?? 0.5}"></label>
            <label class="f">Crop top to bottom<input name="crop_y" type="range" min="0" max="1" step="0.01" value="${saved.crop_y ?? 0.5}"></label>
          </div>
          <details ${clip?.segments?.length || clip?.crop_keyframes?.length ? "open" : ""}>
            <summary>Multiple cuts and moving crop</summary>
            <label class="f">Keep ranges in this order<textarea name="segments" rows="3" placeholder="10.000 --> 15.000 x1">${esc((clip?.segments || []).map(s => s.start + " --> " + s.end + (s.speed && s.speed !== 1 ? " x" + s.speed : "")).join("\n"))}</textarea>
              <span class="hint">Use source seconds. An empty list makes one continuous clip.</span></label>
            <button class="btn sm" type="button" data-action="range">Add selected range</button>
            <label class="f">Crop keyframes<textarea name="crop_keyframes" rows="3" placeholder="0.000 | 20 | 50">${esc((clip?.crop_keyframes || []).map(k => k.time + " | " + (k.x * 100) + " | " + (k.y * 100)).join("\n"))}</textarea>
              <span class="hint">Use seconds in the edited clip, horizontal %, then vertical %.</span></label>
            <button class="btn sm" type="button" data-action="keyframe">Add current crop here</button>
          </details>
          <label class="f">Export<select name="captions"><option value="burn">Burn in captions and hook</option>
            <option value="clean" ${saved.captions === "clean" ? "selected" : ""}>Clean video</option></select></label>
          <label class="f">Title<input name="title" maxlength="100" value="${esc(clip?.title || "Manual clip")}"></label>
          <label class="ck"><input name="watermark" type="checkbox" ${(saved.watermark ?? (!clip && job.options?.watermark)) ? "checked" : ""}> MJ video watermark</label>
          <label class="f">Hook<input name="hook" maxlength="60" value="${esc(clip?.hook || "")}"></label>
          <label class="f">Title tag<select name="motion"><option value="none">No title tag</option><option value="highlight" ${clip?.motion === "highlight" ? "selected" : ""}>MJ title tag</option></select></label>
          <h3>Music</h3>
          <label class="f">Track<select name="music_id"><option value="">Original audio only</option>${(S.status.music || []).map(t => `<option value="${esc(t.id)}" ${t.id === clip?.music_id ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select></label>
          <label class="f">Volume <output data-vol>${Math.round((clip?.music_volume ?? 0.3) * 100)}%</output><input name="music_volume" type="range" min="0" max="1" step="0.01" value="${clip?.music_volume ?? 0.3}"></label>
          <label class="ck"><input name="music_duck" type="checkbox" ${clip?.music_duck === false ? "" : "checked"}> Duck music under speech</label>
          <div class="two">
            <label class="f">Fade in (seconds)<input name="music_fade_in" type="number" min="0" max="5" step="0.1" value="${clip?.music_fade_in ?? 0.4}"></label>
            <label class="f">Fade out (seconds)<input name="music_fade_out" type="number" min="0" max="5" step="0.1" value="${clip?.music_fade_out ?? 0.8}"></label>
          </div>
          <label class="f">Music start offset (seconds)<input name="music_offset" type="number" min="0" max="1800" step="0.1" value="${clip?.music_offset ?? 0}"></label>
          ${clip ? `<label class="f">Thumbnail line<input name="thumb_hook" maxlength="80" value="${esc(clip.thumb_hook || clip.hook || "")}"></label>
          <button class="btn sm" type="button" data-action="thumb">Update thumbnail</button>
          <img data-thumb alt="Thumbnail preview" ${clip.thumb_file ? `src="/media/${job.id}/${esc(clip.thumb_file)}"` : "hidden"}> ` : ""}
          <label class="ck"><input name="remember" type="checkbox"> Remember export settings on this browser</label>
          <div class="row"><button class="btn primary" type="submit">${clip ? "Render changes" : "Create clip"}</button></div>
          <p data-error class="err" role="alert" hidden></p>
        </div>
      </div>
    </form>`;
  const form = dialog.querySelector("form");
  const el = name => form.elements.namedItem(name);
  const video = form.querySelector("video");
  const canvas = form.querySelector("canvas");
  const crop = $(".source-crop", form);
  const error = $("[data-error]", form);
  const report = message => {
    error.textContent = message;
    error.hidden = !message;
  };
  const lines = name => el(name).value.split("\n").filter(line => line.trim());
  function cutRanges() {
    return lines("segments").map(line => {
      const match = line.match(/^\s*(\d+(?:\.\d+)?)\s*-->\s*(\d+(?:\.\d+)?)\s*(?:x\s*(\d+(?:\.\d+)?))?\s*$/);
      if (!match) throw new Error("Use one range per line, for example 10.000 --> 15.000 x1.");
      const row = {start: Number(match[1]), end: Number(match[2])};
      if (match[3]) row.speed = Number(match[3]);
      return row;
    });
  }
  function writeRanges(rows) {
    el("segments").value = rows.map(row => row.start + " --> " + row.end + (row.speed && row.speed !== 1 ? " x" + row.speed : "")).join("\n");
  }
  const history = [], future = [];
  let restoring = false;
  function snapshot() {
    if (restoring) return;
    history.push([...new FormData(form).entries()]);
    if (history.length > 40) history.shift();
    future.length = 0;
  }
  function applyForm(entries) {
    const data = new Map(entries);
    restoring = true;
    for (const input of form.elements) {
      if (!input.name || input.type === "file") continue;
      if (input.type === "checkbox") input.checked = data.has(input.name);
      else if (data.has(input.name)) input.value = data.get(input.name);
    }
    restoring = false;
    syncRange();
    draw();
    drawCrop();
    paintLive();
  }
  function paintLive() {
    const box = $("[data-live-hook]", form);
    if (box) box.textContent = el("hook").value || "Hook";
    const overlay = $(".live-overlay", form);
    if (overlay) overlay.dataset.place = el("caption_position").value || "bottom";
    const vol = $("[data-vol]", form);
    if (vol && el("music_volume")) vol.textContent = Math.round(Number(el("music_volume").value) * 100) + "%";
    $$("[data-layout]", form).forEach(button => button.setAttribute("aria-pressed", button.dataset.layout === el("layout").value ? "true" : "false"));
  }
  function activeIndex(rows, time) {
    return rows.findIndex(row => time >= row.start && time < row.end);
  }
  function cropKeyframes() {
    return lines("crop_keyframes").map(line => {
      const match = line.match(/^\s*(\d+(?:\.\d+)?)\s*\|\s*(\d+(?:\.\d+)?)\s*\|\s*(\d+(?:\.\d+)?)\s*$/);
      if (!match) throw new Error("Use seconds | horizontal % | vertical %, for example 0.000 | 20 | 50.");
      return {time: Number(match[1]), x: Number(match[2]) / 100, y: Number(match[3]) / 100};
    });
  }

  function draw() {
    const width = Math.max(1, canvas.clientWidth);
    const height = 66;
    const scale = window.devicePixelRatio || 1;
    canvas.width = width * scale;
    canvas.height = height * scale;
    const graphics = canvas.getContext("2d");
    graphics.scale(scale, scale);
    graphics.fillStyle = "#122a30";
    graphics.fillRect(0, 0, width, height);
    const a = Number(el("start").value) / duration * width;
    const b = Number(el("end").value) / duration * width;
    graphics.fillStyle = "#2a5358";
    graphics.fillRect(a, 0, Math.max(0, b - a), height);
    graphics.fillStyle = "#b8cfc9";
    peaks.forEach((peak, i) => {
      const wide = width / peaks.length;
      const h = Math.max(1, peak * (height - 6));
      graphics.fillRect(i * wide, (height - h) / 2, Math.max(1, wide - 1), h);
    });
    graphics.fillStyle = "#ffa27c";
    markers.forEach(mark => graphics.fillRect(mark / duration * width, 0, 1, height));
    graphics.fillStyle = "#fff1d7";
    graphics.fillRect(Number(el("playhead").value) / duration * width, 0, 2, height);
  }

  function drawCrop() {
    const sw = video.videoWidth;
    const sh = video.videoHeight;
    const layout = el("layout").value;
    crop.hidden = !sw;
    if (!sw) return;
    const bounds = video.getBoundingClientRect();
    const scale = Math.min(bounds.width / sw, bounds.height / sh);
    const aspect = layout === "stack" ? 1080 / 1040 : 9 / 16;
    const w = Math.min(sw, sh * aspect);
    const h = Math.min(sh, sw / aspect);
    crop.style.left = (bounds.width - sw * scale) / 2 + (sw - w) * scale * Number(el("crop_x").value) + "px";
    crop.style.top = (bounds.height - sh * scale) / 2 + (sh - h) * scale * Number(el("crop_y").value) + "px";
    crop.style.width = w * scale + "px";
    crop.style.height = h * scale + "px";
  }

  function position(seconds, seek = true) {
    const time = Math.max(0, Math.min(duration, seconds));
    if (seek && video.readyState > 0) video.currentTime = time;
    el("playhead").value = time;
    $("[data-position]", form).textContent = time.toFixed(3) + " s";
    draw();
  }

  function syncRange() {
    el("inPoint").value = el("start").value;
    el("outPoint").value = el("end").value;
    draw();
  }

  function drawMarkers() {
    const list = $("[data-markers]", form);
    list.replaceChildren();
    for (const mark of markers) {
      const row = document.createElement("span");
      for (const remove of [false, true]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn sm";
        button.textContent = remove ? "×" : mark.toFixed(2) + " s";
        if (remove) button.setAttribute("aria-label", "Remove marker at " + mark.toFixed(2) + " seconds");
        button.addEventListener("click", () => {
          if (!remove) return position(mark);
          markers = markers.filter(value => value !== mark);
          saveMarkers();
        });
        row.append(button);
      }
      list.append(row);
    }
  }

  function saveMarkers() {
    putEditorStorage(markKey, markers);
    drawMarkers();
    draw();
  }

  form.addEventListener("input", event => {
    const name = event.target.name;
    if (name === "playhead") return position(Number(event.target.value));
    if (name === "inPoint" || name === "outPoint") {
      el(name === "inPoint" ? "start" : "end").value = event.target.value;
      position(Number(event.target.value));
    }
    if (["start", "end", "inPoint", "outPoint"].includes(name)) syncRange();
    if (["crop_x", "crop_y", "layout", "style", "captions"].includes(name)) {
      el("preset").value = "";
      drawCrop();
    }
    if (name === "speed") {
      try {
        const rows = cutRanges();
        const index = activeIndex(rows, Number(el("playhead").value));
        if (index >= 0) {
          rows[index].speed = Number(event.target.value) || 1;
          writeRanges(rows);
        }
      } catch {}
    }
    paintLive();
  });
  el("preset").addEventListener("change", event => {
    const preset = clipPresets[event.target.value];
    if (!preset) return;
    for (const [name, value] of Object.entries(preset)) el(name).value = value;
    el("crop_x").value = el("crop_y").value = 0.5;
    drawCrop();
  });
  canvas.addEventListener("pointerdown", event => {
    const ratio = event.offsetX / canvas.clientWidth;
    const x = ratio * duration;
    const start = Number(el("start").value);
    const end = Number(el("end").value);
    const tol = Math.max(0.15, duration * 0.012);
    const edge = Math.abs(x - start) <= tol ? "start" : Math.abs(x - end) <= tol ? "end" : "";
    if (!edge) return position(x);
    snapshot();
    const move = ev => {
      const rect = canvas.getBoundingClientRect();
      const t = Math.max(0, Math.min(duration, (ev.clientX - rect.left) / rect.width * duration));
      if (edge === "start") el("start").value = Math.min(t, Number(el("end").value) - 0.25).toFixed(3);
      else el("end").value = Math.max(t, Number(el("start").value) + 0.25).toFixed(3);
      syncRange();
      position(Number(el(edge).value), false);
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });
  form.addEventListener("click", event => {
    const pick = event.target.closest("[data-layout]");
    if (!pick) return;
    el("layout").value = pick.dataset.layout;
    el("preset").value = "";
    drawCrop();
    paintLive();
  });
  video.addEventListener("timeupdate", () => position(video.currentTime, false));
  video.addEventListener("loadedmetadata", () => { position(Number(el("start").value)); drawCrop(); });
  video.addEventListener("error", () => { $("[data-preview-note]", form).hidden = false; });
  form.addEventListener("click", event => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    const time = video.readyState > 0 ? video.currentTime : Number(el("playhead").value);
    if (action === "close") dialog.close();
    if (action === "previous" || action === "next") {
      video.pause();
      position(time + (action === "next" ? 1 : -1) / fps);
    }
    if (action === "in" || action === "out") {
      el(action === "in" ? "start" : "end").value = time.toFixed(3);
      syncRange();
    }
    if (action === "range") {
      const start = el("start").value, end = el("end").value;
      if (!start || !end || Number(end) <= Number(start)) return report("Set the end after the start.");
      el("segments").value = [...lines("segments"), start + " --> " + end].join("\n");
      report("");
    }
    if (action === "keyframe") {
      try {
        const spans = cutRanges();
        const current = spans.findIndex(span => time >= span.start && time < span.end);
        if (spans.length && current < 0) throw new Error("Move the playhead into a kept range.");
        const elapsed = spans.length ? spans.slice(0, current).reduce((n, s) => n + s.end - s.start, 0)
          + time - spans[current].start : time - Number(el("start").value);
        if (elapsed < 0 || (!spans.length && time >= Number(el("end").value))) throw new Error("Move the playhead inside the clip.");
        const frame = {time: Number(elapsed.toFixed(3)), x: Number(el("crop_x").value), y: Number(el("crop_y").value)};
        const keys = [...cropKeyframes().filter(k => k.time !== frame.time), frame].sort((a, b) => a.time - b.time);
        el("crop_keyframes").value = keys.map(k => k.time + " | " + (k.x * 100) + " | " + (k.y * 100)).join("\n");
        report("");
      } catch (exc) { report(exc.message); }
    }
    if (action === "split" || action === "merge" || action === "earlier" || action === "later") {
      try {
        snapshot();
        let rows = cutRanges();
        if (!rows.length) rows = [{start: Number(el("start").value), end: Number(el("end").value)}];
        const index = Math.max(0, activeIndex(rows, time));
        if (action === "split") {
          const span = rows[index];
          if (!span || time <= span.start + 0.25 || time >= span.end - 0.25) throw new Error("Move the playhead inside a cut, away from its edges.");
          const speed = Number(el("speed").value) || span.speed || 1;
          rows.splice(index, 1, {start: span.start, end: Number(time.toFixed(3)), speed}, {start: Number(time.toFixed(3)), end: span.end, speed});
        } else if (action === "merge") {
          if (index >= rows.length - 1) throw new Error("Choose a cut that has another cut after it.");
          const left = rows[index], right = rows[index + 1];
          rows.splice(index, 2, {start: Math.min(left.start, right.start), end: Math.max(left.end, right.end), speed: left.speed || 1});
        } else {
          const target = index + (action === "later" ? 1 : -1);
          if (target < 0 || target >= rows.length) throw new Error("That cut cannot move any further.");
          const swap = rows[index]; rows[index] = rows[target]; rows[target] = swap;
        }
        writeRanges(rows);
        report("");
      } catch (exc) { report(exc.message); }
    }
    if (action === "undo" || action === "redo") {
      const from = action === "undo" ? history : future;
      const to = action === "undo" ? future : history;
      if (!from.length) return;
      to.push([...new FormData(form).entries()]);
      applyForm(from.pop());
    }
    if (action === "thumb" && clip) {
      send(sourceURL + "/clips/" + encodeURIComponent(clip.id) + "/thumb", {hook: el("thumb_hook").value}).then(made => {
        const img = $("[data-thumb]", form);
        img.hidden = false;
        img.src = made.wide;
        report("");
      }).catch(exc => report(exc.message));
    }
    if (action === "mark" && markers.length < 100) {
      markers = [...new Set([...markers, Number(time.toFixed(3))])].sort((a, b) => a - b);
      saveMarkers();
    }
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const fields = Object.fromEntries(new FormData(form));
    const {title, hook, style, layout, captions} = fields;
    const watermark = Boolean(fields.watermark);
    const music_duck = Boolean(fields.music_duck);
    const start = Number(fields.start);
    const end = Number(fields.end);
    let segments, crop_keyframes;
    try { segments = cutRanges(); crop_keyframes = cropKeyframes(); }
    catch (exc) { return report(exc.message); }
    const total = segments.length ? segments.reduce((n, s) => n + s.end - s.start, 0) : end - start;
    if (total < 3 - 0.0001 || total > 180 + 0.0001) return report("A clip must be 3 to 180 seconds long.");
    const crop_x = Number(fields.crop_x);
    const crop_y = Number(fields.crop_y);
    const body = {title, hook, style, layout, captions, watermark, start, end, crop_x, crop_y, segments, crop_keyframes,
      caption_position: fields.caption_position, motion: fields.motion, music_id: fields.music_id || "",
      music_volume: Number(fields.music_volume), music_duck, music_fade_in: Number(fields.music_fade_in),
      music_fade_out: Number(fields.music_fade_out), music_offset: Number(fields.music_offset)};
    const submit = event.submitter;
    submit.disabled = true;
    report("");
    try {
      const url = clip ? sourceURL + "/clips/" + encodeURIComponent(clip.id) + "/render" : sourceURL + "/clips";
      await send(url, body);
      if (fields.remember) putEditorStorage(defaultsKey, {style, layout, captions, watermark, crop_x, crop_y});
      dialog.close();
      toast("Clip queued for rendering", "ok");
      await tick();
    } catch (exc) {
      report(exc.message);
      submit.disabled = false;
    }
  });
  const resize = new ResizeObserver(() => { draw(); drawCrop(); });
  dialog.addEventListener("close", () => {
    resize.disconnect();
    video.pause();
    if (dialog.contains(form)) dialog.replaceChildren();
  }, {once: true});
  form.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z") return;
    if (event.target.matches("input, textarea")) return;
    event.preventDefault();
    form.querySelector(`[data-action="${event.shiftKey ? "redo" : "undo"}"]`)?.click();
  });
  dialog.showModal();
  paintLive();
  resize.observe(canvas.parentElement);
  drawMarkers();
  syncRange();
  api(sourceURL + "/waveform").then(value => {
    if (dialog.contains(form)) { peaks = value.peaks; draw(); }
  }).catch(() => {});
}

async function loadCaptionEditor(job, clip, area) {
  try {
    const {cues} = await api(`/api/jobs/${job.id}/clips/${clip.id}/captions`);
    if (!area.isConnected || area.dataset.dirty) return;
    area.value = cues.map(cue => `${(cue.start - clip.start).toFixed(3)} --> ${(cue.end - clip.start).toFixed(3)} | ${cue.text}`).join("\n");
    area.readOnly = false;
  } catch {
    area.placeholder = "Captions could not be loaded. Close and reopen the clip to try again.";
  }
}

function readCaptionEditor(area, start) {
  if (!area || !area.dataset.dirty) return undefined;
  if (area.dataset.dirty === "reset") return null;
  return area.value.split("\n").filter(line => line.trim()).map(line => {
    const match = line.match(/^\s*(\d+(?:\.\d+)?)\s*-->\s*(\d+(?:\.\d+)?)\s*\|\s*(\S.*)\s*$/);
    if (!match) throw new Error("Use one caption per line, for example 0.000 --> 2.500 | Your caption.");
    return {start: start + Number(match[1]), end: start + Number(match[2]), text: match[3]};
  });
}

async function loadCaptionGlossary(area) {
  if (area.dataset.loaded) return;
  try {
    const {rules} = await api("/api/caption-glossary");
    area.value = rules.map(rule => rule.heard + " => " + rule.correct).join("\n");
    area.dataset.loaded = "1";
    area.readOnly = false;
  } catch {
    area.placeholder = "Glossary could not be loaded. Close and reopen this section to retry.";
  }
}

async function saveCaptionGlossary(area) {
  if (!area.dataset.loaded) throw new Error("Wait for the glossary to load.");
  const rules = area.value.split("\n").filter(line => line.trim()).map(line => {
    const split = line.indexOf("=>");
    if (split < 0) throw new Error("Use one correction per line, for example Lost Santos => Los Santos.");
    return {heard: line.slice(0, split).trim(), correct: line.slice(split + 2).trim()};
  });
  await send("/api/caption-glossary", {rules}, "PUT");
  delete area.dataset.dirty;
}
