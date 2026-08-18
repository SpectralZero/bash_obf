"use strict";

const MAX_BYTES = 1024 * 1024;
const encoder = new TextEncoder();
const state = { presets: {}, layers: [], selectedLayers: null, batch: [] };

const byId = (id) => document.getElementById(id);
const els = {
  apiStatus: byId("api-status"),
  preset: byId("preset-control"),
  layers: byId("layer-list"),
  intensity: byId("intensity"),
  intensityValue: byId("intensity-value"),
  sizeRatio: byId("size-ratio"),
  sizeRatioValue: byId("size-ratio-value"),
  entropyTarget: byId("entropy-target"),
  entropyTargetValue: byId("entropy-target-value"),
  evalMode: byId("eval-mode"),
  seed: byId("seed"),
  source: byId("source-editor"),
  output: byId("output-editor"),
  sourceCount: byId("source-count"),
  outputCount: byId("output-count"),
  message: byId("request-message"),
  obfuscate: byId("obfuscate-action"),
  analyze: byId("analyze-action"),
  batchInput: byId("batch-input"),
  batchList: byId("batch-list"),
  batchSummary: byId("batch-summary"),
  runBatch: byId("run-batch"),
  dropZone: byId("drop-zone"),
};

function bytes(value) { return encoder.encode(value).length; }
function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(value < 10240 ? 1 : 0)} KiB`;
}

function setMessage(text, kind = "") {
  els.message.textContent = text;
  els.message.className = `request-message ${kind}`.trim();
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const message = data?.error?.message || `Request failed with status ${response.status}`;
    throw new Error(message);
  }
  return data;
}

function presetLayers(profile) {
  return profile.force_layers ? profile.force_layers.split(",") : null;
}

function renderPresets() {
  els.preset.replaceChildren(...Object.keys(state.presets).map((name) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "segment";
    button.dataset.preset = name;
    button.textContent = name;
    button.addEventListener("click", () => applyPreset(name));
    return button;
  }));
}

function renderLayers() {
  els.layers.replaceChildren(...state.layers.map((name) => {
    const label = document.createElement("label");
    label.className = "layer-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = name;
    input.checked = state.selectedLayers?.has(name) || false;
    input.addEventListener("change", () => {
      if (state.selectedLayers === null) state.selectedLayers = new Set();
      input.checked ? state.selectedLayers.add(name) : state.selectedLayers.delete(name);
      markCustom();
    });
    const text = document.createElement("span");
    text.textContent = name;
    label.append(input, text);
    return label;
  }));
}

function markCustom() {
  document.querySelectorAll("[data-preset]").forEach((button) => button.classList.remove("active"));
}

function applyPreset(name) {
  const profile = state.presets[name];
  state.selectedLayers = presetLayers(profile);
  if (state.selectedLayers) state.selectedLayers = new Set(state.selectedLayers);
  els.intensity.value = profile.intensity;
  els.evalMode.value = profile.eval_mode;
  updateControls();
  renderLayers();
  document.querySelectorAll("[data-preset]").forEach((button) => {
    button.classList.toggle("active", button.dataset.preset === name);
  });
}

function updateControls() {
  els.intensityValue.value = Number(els.intensity.value).toFixed(2);
  els.sizeRatioValue.value = `${Number(els.sizeRatio.value).toFixed(1)}x`;
  els.entropyTargetValue.value = Number(els.entropyTarget.value).toFixed(1);
}

function configPayload() {
  const config = {
    intensity: Number(els.intensity.value),
    max_size_ratio: Number(els.sizeRatio.value),
    entropy_target: Number(els.entropyTarget.value),
    eval_mode: els.evalMode.value,
  };
  if (els.seed.value) config.seed = els.seed.value;
  if (state.selectedLayers !== null) config.layers = [...state.selectedLayers];
  return config;
}

function updateCounts() {
  els.sourceCount.textContent = formatBytes(bytes(els.source.value));
  els.outputCount.textContent = formatBytes(bytes(els.output.value));
}

function renderMetrics(data) {
  byId("metric-score").textContent = `${data.security_score}/100`;
  const entropy = data.entropy;
  const entropyEl = byId("metric-entropy");
  entropyEl.textContent = `${entropy.overall.toFixed(3)} / ${entropy.target.toFixed(1)}`;
  entropyEl.classList.toggle("in-range", entropy.in_range === true);
  entropyEl.classList.toggle("off-target", entropy.in_range === false);
  entropyEl.title = entropy.in_range ? "Within target range" : "Outside target range";
  const ratio = data.analysis.source_size_ratio;
  byId("metric-ratio").textContent = ratio == null ? "--" : `${ratio.toFixed(2)}x`;
  byId("metric-layers").textContent = data.layers_applied ? String(data.layers_applied.length) : "--";
  byId("metric-elapsed").textContent = data.elapsed_ms == null ? "--" : `${data.elapsed_ms.toFixed(1)} ms`;
}

function renderAnalysis(data) {
  const analysis = data.analysis;
  byId("analysis-hash").textContent = analysis.structure_sha256;
  const entries = [
    ["Standalone eval", analysis.standalone_eval_count],
    ["xxd commands", analysis.xxd_command_count],
    ["Legacy fingerprints", analysis.legacy_fingerprint_count],
    ["Dead assignments", analysis.assigned_never_read_candidates.length],
    ["Uncalled functions", analysis.uncalled_function_candidates.length],
    ["Duplicate literals", analysis.duplicate_literal_group_count],
    ["Split / XOR reconstructions", `${analysis.split_reconstruction_count} / ${analysis.xor_reconstruction_count}`],
    ["Opaque / CFF structures", `${analysis.opaque_constant_count} / ${analysis.cff_dispatcher_count}`],
  ];
  const container = byId("analysis-findings");
  container.className = "findings";
  container.replaceChildren(...entries.map(([label, value]) => {
    const item = document.createElement("div");
    item.className = "finding";
    const name = document.createElement("span");
    name.textContent = label;
    const count = document.createElement("strong");
    count.textContent = value;
    item.append(name, count);
    return item;
  }));
}

async function obfuscate() {
  const sourceBytes = bytes(els.source.value);
  if (!els.source.value.trim()) return setMessage("Source is required", "error");
  if (sourceBytes > MAX_BYTES) return setMessage("Source exceeds the 1 MiB limit", "error");
  setBusy(true, "Obfuscating...");
  try {
    const data = await api("/api/obfuscate", { source: els.source.value, ...configPayload() });
    els.output.value = data.output;
    updateCounts();
    renderMetrics(data);
    renderAnalysis(data);
    setMessage(`Completed with seed ${data.seed}`, "success");
  } catch (error) { setMessage(error.message, "error"); }
  finally { setBusy(false); }
}

async function analyze() {
  const output = els.output.value || els.source.value;
  if (!output.trim()) return setMessage("Source or output is required", "error");
  setBusy(true, "Analyzing...");
  try {
    const body = { output };
    if (els.output.value && els.source.value) body.original_source = els.source.value;
    body.entropy_target = Number(els.entropyTarget.value);
    const data = await api("/api/analyze", body);
    renderMetrics(data);
    renderAnalysis(data);
    setMessage("Static analysis complete", "success");
  } catch (error) { setMessage(error.message, "error"); }
  finally { setBusy(false); }
}

function setBusy(busy, message) {
  els.obfuscate.disabled = busy;
  els.analyze.disabled = busy;
  if (message) setMessage(message);
}

async function addFiles(fileList) {
  for (const file of fileList) {
    if (!file.name.toLowerCase().endsWith(".sh")) {
      setMessage(`${file.name} is not a .sh file`, "error");
      continue;
    }
    if (file.size > MAX_BYTES) {
      setMessage(`${file.name} exceeds the 1 MiB limit`, "error");
      continue;
    }
    if (state.batch.some((item) => item.name === file.name)) {
      setMessage(`${file.name} is already queued`, "error");
      continue;
    }
    const source = await file.text();
    state.batch.push({ name: file.name, source, status: "queued", output: "" });
  }
  renderBatch();
}

function renderBatch() {
  els.runBatch.disabled = state.batch.length === 0;
  els.batchSummary.textContent = state.batch.length
    ? `${state.batch.length} file${state.batch.length === 1 ? "" : "s"} queued`
    : "No files queued";
  if (!state.batch.length) {
    els.batchList.innerHTML = '<tr><td colspan="5" class="empty-cell">Queue is empty</td></tr>';
    return;
  }
  els.batchList.replaceChildren(...state.batch.map((item, index) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = item.name;
    const sourceSize = document.createElement("td");
    sourceSize.textContent = formatBytes(bytes(item.source));
    const status = document.createElement("td");
    const statusLabel = document.createElement("span");
    statusLabel.className = `queue-status ${item.status}`;
    statusLabel.textContent = item.status;
    status.append(statusLabel);
    const outputSize = document.createElement("td");
    outputSize.textContent = item.output ? formatBytes(bytes(item.output)) : "--";
    const action = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-button";
    button.textContent = item.output ? "Save" : "Remove";
    button.addEventListener("click", () => item.output ? download(item.output, `${item.name.slice(0, -3)}.obf.sh`) : removeBatch(index));
    action.append(button);
    row.append(name, sourceSize, status, outputSize, action);
    if (item.error) row.title = item.error;
    return row;
  }));
}

function removeBatch(index) { state.batch.splice(index, 1); renderBatch(); }

async function runBatch() {
  els.runBatch.disabled = true;
  state.batch.forEach((item) => { item.status = "running"; item.error = ""; });
  renderBatch();
  setMessage("Processing batch...");
  try {
    const data = await api("/api/batch", {
      files: state.batch.map(({ name, source }) => ({ name, source })),
      config: configPayload(),
    });
    data.items.forEach((result) => {
      const item = state.batch.find((candidate) => candidate.name === result.name);
      if (item) Object.assign(item, result);
    });
    setMessage(`${data.summary.succeeded} of ${data.summary.total} files completed`, data.summary.failed ? "error" : "success");
  } catch (error) {
    state.batch.forEach((item) => { if (item.status === "running") item.status = "queued"; });
    setMessage(error.message, "error");
  }
  renderBatch();
}

function download(content, filename) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/x-shellscript" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function initialize() {
  updateCounts();
  updateControls();
  try {
    state.presets = await api("/api/presets");
    try {
      state.layers = (await api("/api/layers")).layers || [];
    } catch {
      const allProfile = state.presets.paranoid || state.presets.godmode;
      state.layers = presetLayers(allProfile) || [];
    }
    renderPresets();
    applyPreset("standard");
    els.apiStatus.classList.add("online");
  } catch (error) {
    els.apiStatus.classList.add("error");
    setMessage(error.message, "error");
  }
}

els.source.addEventListener("input", updateCounts);
els.intensity.addEventListener("input", () => { updateControls(); markCustom(); });
els.sizeRatio.addEventListener("input", () => { updateControls(); markCustom(); });
els.entropyTarget.addEventListener("input", () => { updateControls(); markCustom(); });
els.evalMode.addEventListener("change", markCustom);
els.obfuscate.addEventListener("click", obfuscate);
els.analyze.addEventListener("click", analyze);
byId("auto-layers").addEventListener("click", () => { state.selectedLayers = null; renderLayers(); markCustom(); });
byId("reset-config").addEventListener("click", () => { els.sizeRatio.value = 3; els.entropyTarget.value = 4.5; els.seed.value = ""; applyPreset("standard"); });
byId("copy-output").addEventListener("click", async () => {
  if (!els.output.value) return setMessage("There is no output to copy", "error");
  try { await navigator.clipboard.writeText(els.output.value); setMessage("Output copied", "success"); }
  catch { setMessage("Clipboard access was denied", "error"); }
});
byId("download-output").addEventListener("click", () => {
  if (!els.output.value) return setMessage("There is no output to download", "error");
  download(els.output.value, "obfuscated.sh");
});
els.batchInput.addEventListener("change", () => { addFiles(els.batchInput.files); els.batchInput.value = ""; });
byId("clear-batch").addEventListener("click", () => { state.batch = []; renderBatch(); });
els.runBatch.addEventListener("click", runBatch);
["dragenter", "dragover"].forEach((eventName) => els.dropZone.addEventListener(eventName, (event) => {
  event.preventDefault(); els.dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((eventName) => els.dropZone.addEventListener(eventName, (event) => {
  event.preventDefault(); els.dropZone.classList.remove("dragging");
}));
els.dropZone.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));

initialize();
