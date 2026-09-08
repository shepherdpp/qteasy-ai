const sessionId = "web-session";
let mode = "plan";
let state = emptyState();
let artifactTab = 0;
let pendingCodeRun = false;

function emptyState() {
  return {
    mode: "plan",
    session_id: sessionId,
    messages: [],
    plan_card: null,
    sidebar: {
      active_intent: null,
      slots: [],
      missing: [],
      env_summary: {},
      current_plan_id: "",
      clarify_round: 0,
    },
    artifacts: [],
    execution: { status: "", steps: [] },
    error: null,
    run_id: "",
    sources: [],
  };
}

async function api(path, options) {
  const res = await fetch(path, options);
  return res;
}

function setMode(next) {
  mode = next;
  render();
}

async function sendQuery(query) {
  const body = JSON.stringify({ query, session_id: sessionId });
  const path = mode === "ask" ? "/v1/ask" : mode === "agent" ? "/v1/run" : "/v1/plan";
  const res = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body });
  state = await res.json();
  artifactTab = 0;
  pendingCodeRun = false;
  render();
}

async function confirmPlan() {
  const planId = state.plan_card && state.plan_card.plan_id;
  if (!planId || (state.plan_card && state.plan_card.confirmable === false)) return;
  const res = await api("/v1/run-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_id: planId }),
  });
  state = await res.json();
  render();
}

function cancelPlan() {
  state = Object.assign({}, state, { plan_card: null });
  render();
}

async function followUp(text) {
  await sendQuery(text);
}

function renderMessages() {
  return (state.messages || [])
    .map((msg) => `<div class="msg ${msg.kind === "user_text" ? "user" : ""}"><strong>${msg.kind}</strong><div>${escapeHtml(msg.text || "")}</div></div>`)
    .join("");
}

function renderClarification() {
  const missing = (state.sidebar && state.sidebar.missing) || [];
  const clar = (state.messages || []).find((m) => m.kind === "clarification");
  if (!clar && !missing.length) return "";
  const pending = ((clar && clar.payload && clar.payload.pending) || []).map((item) => item.name || item).filter(Boolean);
  const fields = missing.length ? missing : pending;
  const inputs = fields
    .map((name) => `<label>${escapeHtml(name)}<input data-slot="${escapeHtml(name)}" /></label>`)
    .join("");
  return `<div class="card" data-testid="clarification-form"><h3>Clarification</h3>${inputs}<button id="btn-clarify">Submit slots</button></div>`;
}

function renderPlanCard() {
  const card = state.plan_card;
  if (!card || !card.confirmable) return "";
  const steps = (card.steps || [])
    .map(
      (s) =>
        `<li>${escapeHtml(s.skill_name)} — network=${s.side_effects && s.side_effects.network} write=${s.side_effects && s.side_effects.filesystem_write}</li>`
    )
    .join("");
  return `<div class="card" data-testid="plan-card"><h3>Plan ${escapeHtml(card.plan_id)}</h3><ul>${steps}</ul>
    <button id="btn-confirm">Confirm</button>
    <button id="btn-edit">Change params</button>
    <button id="btn-cancel">Cancel</button></div>`;
}

function renderSteps() {
  const steps = (state.execution && state.execution.steps) || [];
  if (!steps.length) return "";
  return `<ol data-testid="step-list">${steps
    .map((s) => `<li class="step ${s.status || ""}">${s.status === "done" ? "✓" : "•"} ${escapeHtml(s.skill_name || s.step_id)}</li>`)
    .join("")}</ol>`;
}

function renderArtifacts() {
  const arts = state.artifacts || [];
  if (!arts.length) return `<p>No artifacts yet.</p>`;
  const tabs = arts
    .map(
      (a, i) =>
        `<div class="tab ${i === artifactTab ? "active" : ""}" data-tab="${i}">${escapeHtml(a.type)} <small>${escapeHtml(a.run_id)}</small></div>`
    )
    .join("");
  const current = arts[artifactTab] || arts[0];
  let body = "";
  if (current.type === "data_table") {
    const rows = (current.preview && current.preview.preview_rows) || [];
    body = `<pre>${escapeHtml(JSON.stringify(current.preview && current.preview.data_summary, null, 2))}</pre>
      <table>${rows.map((row) => `<tr><td>${escapeHtml(JSON.stringify(row))}</td></tr>`).join("")}</table>`;
    if (current.export_path) body += `<p><a href="/v1/artifacts/${encodeURIComponent(current.run_id)}?path=${encodeURIComponent(current.export_path)}">Export</a></p>`;
  } else if (current.type === "chart") {
    if (current.warnings && current.warnings.length) body += `<p class="warn">${escapeHtml(current.warnings.join(" "))}</p>`;
    if (current.export_path) body += `<p><a href="/v1/artifacts/${encodeURIComponent(current.run_id)}?path=${encodeURIComponent(current.export_path)}">Download PNG</a></p><img alt="chart" src="/v1/artifacts/${encodeURIComponent(current.run_id)}?path=${encodeURIComponent(current.export_path)}" />`;
    else body += `<p class="warn">Chart file path is missing.</p>`;
  } else if (current.type === "strategy_code") {
    body = `<textarea id="code-editor" rows="12"></textarea>
      <button id="btn-code-run">Run (requires confirm)</button>
      ${pendingCodeRun ? `<div class="card">Confirm running edited strategy?<button id="btn-code-confirm">Confirm run</button></div>` : ""}`;
  } else if (current.type === "backtest_report") {
    body = `<pre>${escapeHtml(JSON.stringify(current.preview && current.preview.metrics, null, 2))}</pre>
      ${current.export_path ? `<a href="/v1/artifacts/${encodeURIComponent(current.run_id)}?path=${encodeURIComponent(current.export_path)}">trade_log</a>` : ""}`;
  }
  return `<div class="tabs">${tabs}</div><div data-testid="artifact-panel">${body}</div>`;
}

function renderSidebar() {
  const bar = state.sidebar || {};
  const slots = (bar.slots || [])
    .map((s) => `<li>${escapeHtml(s.name)}=${escapeHtml(String(s.value))} (${s.source}, confirmed=${s.confirmed})</li>`)
    .join("");
  return `<p>Job: ${escapeHtml((bar.active_intent && bar.active_intent.job) || "-")}</p>
    <p>Missing: ${escapeHtml((bar.missing || []).join(", ") || "-")}</p>
    <ul>${slots}</ul>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function render() {
  const root = document.getElementById("root");
  root.innerHTML = `
    <div class="topbar">
      <strong>qteasy-ai Workbench</strong>
      <span class="mode-badge" data-testid="mode-badge">Mode: ${mode.toUpperCase()}</span>
      <button data-mode="ask">Ask</button>
      <button data-mode="plan">Plan</button>
      <button data-mode="agent">Agent</button>
    </div>
    <div class="layout">
      <div class="col" id="chat-col">
        <h2>Chat</h2>
        ${renderMessages()}
        ${renderClarification()}
        ${renderPlanCard()}
        ${renderSteps()}
      </div>
      <div class="col" id="artifact-col">
        <h2>Artifacts</h2>
        ${renderArtifacts()}
      </div>
      <div class="col" id="sidebar-col">
        <h2>State</h2>
        ${renderSidebar()}
      </div>
    </div>
    <div class="inputbar">
      <input id="query-input" placeholder="Ask in natural language" />
      <button id="btn-send">Send</button>
    </div>`;
  root.querySelectorAll("button[data-mode]").forEach((btn) => {
    btn.onclick = () => setMode(btn.getAttribute("data-mode"));
  });
  const send = root.querySelector("#btn-send");
  const input = root.querySelector("#query-input");
  if (send && input) {
    send.onclick = () => sendQuery(input.value);
    input.onkeydown = (ev) => {
      if (ev.key === "Enter") sendQuery(input.value);
    };
  }
  const confirm = root.querySelector("#btn-confirm");
  if (confirm) confirm.onclick = confirmPlan;
  const cancel = root.querySelector("#btn-cancel");
  if (cancel) cancel.onclick = cancelPlan;
  const edit = root.querySelector("#btn-edit");
  if (edit) edit.onclick = () => {
    const text = window.prompt("Follow-up (fills or changes slots)", "");
    if (text) followUp(text);
  };
  const clar = root.querySelector("#btn-clarify");
  if (clar) {
    clar.onclick = () => {
      const bits = Array.from(root.querySelectorAll("input[data-slot]")).map((el) => `${el.getAttribute("data-slot")} ${el.value}`);
      followUp(bits.join(" "));
    };
  }
  root.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      artifactTab = Number(tab.getAttribute("data-tab") || 0);
      render();
    };
  });
  const runBtn = root.querySelector("#btn-code-run");
  if (runBtn) {
    runBtn.onclick = () => {
      pendingCodeRun = true;
      render();
    };
  }
  const codeConfirm = root.querySelector("#btn-code-confirm");
  if (codeConfirm) {
    codeConfirm.onclick = () => {
      pendingCodeRun = false;
      confirmPlan();
    };
  }
}

render();
