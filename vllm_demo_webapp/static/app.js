const state = {
  experiments: {},
  active: "exp02",
  runningJob: null,
};

const controls = {
  exp02: [
    ["num_requests", "Requests", "number"],
    ["concurrency_list", "Concurrency list", "text"],
    ["max_tokens", "Max tokens", "number"],
    ["label", "Label", "text"],
  ],
  exp03: [
    ["topic_limit", "Topic limit", "number"],
    ["questions_per_topic", "Questions/topic", "number"],
    ["concurrency", "Async concurrency", "number"],
    ["label", "Label", "text"],
  ],
  exp07: [
    ["num_requests", "Requests", "number"],
    ["vllm_concurrency", "vLLM concurrency", "number"],
    ["max_tokens", "Max tokens", "number"],
    ["label", "Label", "text"],
    ["include_direct_transformers", "Direct Transformers", "checkbox"],
  ],
};

function byId(id) {
  return document.getElementById(id);
}

function appendLog(line) {
  const log = byId("log-output");
  if (log.textContent === "No job running.") log.textContent = "";
  log.textContent += `${line}\n`;
  log.scrollTop = log.scrollHeight;
}

function activeSpec() {
  return state.experiments[state.active];
}

function renderForm() {
  const spec = activeSpec();
  const form = byId("config-form");
  form.innerHTML = "";
  byId("exp-title").textContent = spec.title;
  byId("exp-description").textContent = spec.description;

  for (const [key, label, type] of controls[state.active]) {
    if (type === "checkbox") {
      const wrap = document.createElement("label");
      wrap.className = "checkbox-field";
      wrap.innerHTML = `<input id="field-${key}" type="checkbox" ${
        spec.defaults[key] ? "checked" : ""
      } /> ${label}`;
      form.appendChild(wrap);
      continue;
    }

    const field = document.createElement("div");
    field.className = "field";
    field.innerHTML = `
      <label for="field-${key}">${label}</label>
      <input id="field-${key}" type="${type}" value="${spec.defaults[key] ?? ""}" />
    `;
    form.appendChild(field);
  }
  updateCommandPreview();
}

function collectPayload() {
  const payload = {};
  for (const [key, , type] of controls[state.active]) {
    const input = byId(`field-${key}`);
    if (!input) continue;
    payload[key] = type === "checkbox" ? input.checked : input.value;
  }
  return payload;
}

function updateCommandPreview() {
  const payload = collectPayload();
  let command = `python vllm/${scriptName(state.active)}`;
  for (const [key, value] of Object.entries(payload)) {
    if (typeof value === "boolean") {
      if (value) command += ` --${key.replaceAll("_", "-")}`;
    } else {
      command += ` --${key.replaceAll("_", "-")} ${value}`;
    }
  }
  byId("command-preview").textContent = command;
}

function scriptName(exp) {
  return {
    exp02: "exp02_llm_concurrency_sweep.py",
    exp03: "exp03_pipeline_sequential_vs_async.py",
    exp07: "exp07_no_vllm_baselines.py",
  }[exp];
}

async function loadExperiments() {
  const response = await fetch("/api/experiments");
  state.experiments = await response.json();
  renderForm();
  await refreshArtifacts();
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    const status = await response.json();
    byId("ready-dot").className = `dot ${status.vllm_ready ? "ready" : "down"}`;
    byId("ready-text").textContent = status.vllm_ready ? "Ready" : "Not ready";
    byId("status-model").textContent = status.model || "unknown";
    byId("status-running").textContent = String(status.metrics?.running ?? 0);
    byId("status-waiting").textContent = String(status.metrics?.waiting ?? 0);
    const cache = Number(status.metrics?.gpu_cache_usage ?? 0) * 100;
    byId("status-cache").textContent = `${cache.toFixed(1)}%`;
  } catch {
    byId("ready-dot").className = "dot down";
    byId("ready-text").textContent = "Unavailable";
  }
}

async function startExperiment() {
  const runBtn = byId("run-btn");
  runBtn.disabled = true;
  byId("log-output").textContent = "";
  appendLog(`[demo] starting ${state.active}`);
  try {
    const response = await fetch(`/api/run/${state.active}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPayload()),
    });
    if (!response.ok) {
      const err = await response.text();
      throw new Error(err);
    }
    const data = await response.json();
    state.runningJob = data.job_id;
    appendLog(`[command] ${data.command}`);
    streamJob(data.job_id);
  } catch (error) {
    appendLog(`[error] ${error.message}`);
    runBtn.disabled = false;
  }
}

function streamJob(jobId) {
  const events = new EventSource(`/api/events/${jobId}`);
  events.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    if (data.line) appendLog(data.line);
    if (data.done) {
      appendLog(`[demo] job finished with status=${data.status}`);
      byId("run-btn").disabled = false;
      events.close();
      await refreshArtifacts();
    }
  };
  events.onerror = () => {
    appendLog("[stream] connection closed");
    byId("run-btn").disabled = false;
    events.close();
  };
}

async function refreshArtifacts() {
  const response = await fetch(`/api/artifacts/${state.active}`);
  const artifacts = await response.json();
  const img = byId("svg-preview");
  const meta = byId("artifact-meta");
  const report = byId("markdown-report");

  if (artifacts.svg) {
    img.src = `/api/file?path=${encodeURIComponent(artifacts.svg)}&t=${Date.now()}`;
    img.style.display = "block";
    meta.textContent = artifacts.svg;
  } else {
    img.removeAttribute("src");
    img.style.display = "none";
    meta.textContent = "No visualization found yet.";
  }

  report.textContent = artifacts.markdown_content || "No markdown report found yet.";
}

function bindNav() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", async () => {
      document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.active = button.dataset.exp;
      renderForm();
      await refreshArtifacts();
    });
  });
}

function bindFormUpdates() {
  byId("config-form").addEventListener("input", updateCommandPreview);
}

async function boot() {
  bindNav();
  bindFormUpdates();
  byId("run-btn").addEventListener("click", startExperiment);
  byId("clear-log").addEventListener("click", () => {
    byId("log-output").textContent = "No job running.";
  });
  byId("refresh-artifacts").addEventListener("click", refreshArtifacts);
  await loadExperiments();
  await refreshStatus();
  setInterval(refreshStatus, 2500);
}

boot();
