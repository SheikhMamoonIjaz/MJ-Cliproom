function openReplayPicker(channel = "") {
  const dialog = $("#collectiondlg");
  dialog.innerHTML = `<div class="dlg">
    <h2>Replay Picker</h2>
    <form class="fields"><label class="f">YouTube or Twitch channel
      <input name="channel" type="url" required value="${esc(channel)}" placeholder="https://www.youtube.com/@channel">
    </label><div class="row"><button class="btn primary">Find replays</button>
      <button class="btn" type="button" data-close>Close</button></div></form>
    <div class="fields" data-replays aria-live="polite"></div>
  </div>`;
  const form = $("form", dialog);
  const list = $("[data-replays]", dialog);
  $("[data-close]", dialog).onclick = () => dialog.close();
  form.onsubmit = async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    list.textContent = "Checking finished broadcasts…";
    try {
      const result = await api("/api/replays?url=" + encodeURIComponent(form.elements.channel.value.trim()));
      list.replaceChildren();
      if (!result.replays.length) list.textContent = "No finished replays found. You can paste a direct replay link or upload the video.";
      result.replays.forEach(replay => {
        const choice = document.createElement("button");
        choice.className = "btn";
        choice.type = "button";
        choice.textContent = replay.title + (replay.duration ? " · " + fmtLen(replay.duration) : "");
        choice.onclick = () => {
          dialog.close();
          takeLink(att(), replay.url, $("#url"));
        };
        list.append(choice);
      });
    } catch (error) {
      list.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
  dialog.showModal();
}

function openClipSets(selection = []) {
  const dialog = $("#collectiondlg");
  const key = "peakcut:clipsets:" + (S.status.user?.id || "local");
  let sets = getEditorStorage(key, []);
  let current = sets[0]?.id;
  dialog.innerHTML = `<div class="dlg"><h2>Clip Sets</h2>
    <p class="help">Review and export clips together. Sets are saved in this browser.</p>
    <form class="row"><label class="f">New set name<input name="name" maxlength="60" required></label>
      <button class="btn">Create set</button></form>
    <div data-sets class="fields"></div><button class="btn" type="button" data-close>Close</button></div>`;
  const form = $("form", dialog);
  const panel = $("[data-sets]", dialog);
  $("[data-close]", dialog).onclick = () => dialog.close();
  function setClip(id) {
    const [jobId, clipId] = id.split(".");
    return jobOf(jobId)?.clips.find(clip => clip.id === clipId);
  }
  function save() {
    try { localStorage.setItem(key, JSON.stringify(sets)); }
    catch { toast("This browser could not save the clip set.", "bad"); }
    renderSet();
  }
  function renderSet() {
    const set = sets.find(item => item.id === current);
    panel.replaceChildren();
    if (!set) return;
    const selector = document.createElement("select");
    selector.setAttribute("aria-label", "Open clip set");
    sets.forEach(item => selector.add(new Option(item.name, item.id)));
    selector.value = current;
    selector.onchange = () => { current = selector.value; renderSet(); };
    panel.append(selector);
    if (selection.length) {
      const add = document.createElement("button");
      add.type = "button";
      add.className = "btn";
      add.textContent = "Add " + selection.length + " selected";
      add.onclick = () => {
        const ids = new Set(set.clips.map(item => item.id));
        const additions = selection.filter(id => !ids.has(id));
        if (set.clips.length + additions.length > 150) return toast("A set holds up to 150 clips.", "bad");
        additions.forEach(id => set.clips.push({id, status: "keep"}));
        save();
      };
      panel.append(add);
    }
    set.clips.forEach(item => {
      const clip = setClip(item.id);
      const row = document.createElement("div");
      row.className = "row";
      const label = document.createElement("span");
      label.textContent = clip?.title || "Unavailable clip";
      const status = document.createElement("select");
      status.setAttribute("aria-label", "Review status for " + label.textContent);
      [["keep", "Keep"], ["revise", "Revise"], ["approved", "Approved"]].forEach(([value, name]) =>
        status.add(new Option(name, value)));
      status.value = item.status;
      status.onchange = () => { item.status = status.value; save(); };
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn sm";
      remove.textContent = "Remove";
      remove.onclick = () => { set.clips = set.clips.filter(c => c.id !== item.id); save(); };
      row.append(label, status, remove);
      panel.append(row);
    });
    const approved = set.clips.filter(item => item.status === "approved" && setClip(item.id)?.status === "done");
    const download = document.createElement("button");
    download.type = "button";
    download.className = "btn primary";
    download.textContent = "Export approved (" + approved.length + ")";
    download.disabled = !approved.length;
    download.onclick = () => zipDownload(approved.map(item => item.id));
    panel.append(download);
  }
  form.onsubmit = event => {
    event.preventDefault();
    const name = form.elements.name.value.trim();
    if (!name) return;
    if (sets.length >= 30) return toast("This browser holds up to 30 clip sets.", "bad");
    current = newId();
    sets = [{id: current, name, clips: []}, ...sets];
    form.reset();
    save();
  };
  dialog.showModal();
  renderSet();
}
