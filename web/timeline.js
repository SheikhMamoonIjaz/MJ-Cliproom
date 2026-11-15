/* Source timeline and timed captions. Uses the app's existing API and session. */
const clipPresets = {
  action: {layout: "crop", style: "clean", captions: "burn"},
  gameplay: {layout: "blur", style: "clean", captions: "burn"},
  clean: {layout: "blur", style: "clean", captions: "clean"},
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
          <div class="two">
            <label class="f">Layout<select name="layout">${opts(S.status.layouts, saved.layout || job.options?.layout)}</select></label>
            <label class="f">Caption style<select name="style">${opts(S.status.styles, saved.style || job.options?.style)}</select></label>
          </div>
          <div class="two">
            <label class="f">Crop left to right<input name="crop_x" type="range" min="0" max="1" step="0.01" value="${saved.crop_x ?? 0.5}"></label>
            <label class="f">Crop top to bottom<input name="crop_y" type="range" min="0" max="1" step="0.01" value="${saved.crop_y ?? 0.5}"></label>
          </div>
          <details ${clip?.segments?.length || clip?.crop_keyframes?.length ? "open" : ""}>
            <summary>Multiple cuts and moving crop</summary>
            <label class="f">Keep ranges in this order<textarea name="segments" rows="3" placeholder="10.000 --> 15.000">${esc((clip?.segments || []).map(s => s.start + " --> " + s.end).join("\n"))}</textarea>
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
      const match = line.match(/^\s*(\d+(?:\.\d+)?)\s*-->\s*(\d+(?:\.\d+)?)\s*$/);
      if (!match) throw new Error("Use one range per line, for example 10.000 --> 15.000.");
      return {start: Number(match[1]), end: Number(match[2])};
    });
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
    const layout = sh >= sw ? "crop" : el("layout").value;
    crop.hidden = !sw;
    if (!sw) return;
    const bounds = video.getBoundingClientRect();
    const scale = Math.min(bounds.width / sw, bounds.height / sh);
    const aspect = layout === "crop" ? 9 / 16 : layout === "zoom" ? 1080 / 1000 : sw / sh;
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
  });
  el("preset").addEventListener("change", event => {
    const preset = clipPresets[event.target.value];
    if (!preset) return;
    for (const [name, value] of Object.entries(preset)) el(name).value = value;
    el("crop_x").value = el("crop_y").value = 0.5;
    drawCrop();
  });
  canvas.addEventListener("click", event => position(event.offsetX / canvas.clientWidth * duration));
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
    const start = Number(fields.start);
    const end = Number(fields.end);
    let segments, crop_keyframes;
    try { segments = cutRanges(); crop_keyframes = cropKeyframes(); }
    catch (exc) { return report(exc.message); }
    const total = segments.length ? segments.reduce((n, s) => n + s.end - s.start, 0) : end - start;
    if (total < 3 - 0.0001 || total > 180 + 0.0001) return report("A clip must be 3 to 180 seconds long.");
    const crop_x = Number(fields.crop_x);
    const crop_y = Number(fields.crop_y);
    const body = {title, hook, style, layout, captions, watermark, start, end, crop_x, crop_y, segments, crop_keyframes};
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
  dialog.showModal();
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
