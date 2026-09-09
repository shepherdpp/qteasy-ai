const STORAGE_SESSION = "qteasy-ai.session_id";
const STORAGE_RAIL = "qteasy-ai.session-rail";
const STORAGE_WORKSPACE = "qteasy-ai.workspace";

const SLOT_LABELS = {
  shares: "Symbol",
  start: "Start date",
  end: "End date",
  freq: "Frequency",
  strategy_id: "Strategy",
  slow: "Slow window",
  fast: "Fast window",
  asset_pool: "Asset pool",
  channel: "Data channel",
};

const EXAMPLES = [
  { mode: "ask", text: "What is qteasy?" },
  { mode: "plan", text: "List built-in strategies" },
  { mode: "plan", text: "Help me download daily bars" },
  { mode: "plan", text: "Summarize CSI 300 2023 volatility" },
];

let mode = "plan";
let sessionId = localStorage.getItem(STORAGE_SESSION) || newSessionId();
let state = emptyState();
let transcript = [];
let artifactTab = 0;
let pendingCodeRun = false;
let editingParams = false;
let busy = false;
let shellReady = false;
let codeCache = {};
let filePreview = null;
let sessions = [];
let workspace = { trees: [] };
let railCollapsed = localStorage.getItem(STORAGE_RAIL) === "1";
let workspaceCollapsed = localStorage.getItem(STORAGE_WORKSPACE) === "1";

localStorage.setItem(STORAGE_SESSION, sessionId);

function newSessionId() {
  return `web-${Date.now().toString(36)}`;
}

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
    turns: [],
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function slotLabel(name) {
  return SLOT_LABELS[name] || String(name || "").replace(/_/g, " ");
}

function skillLabel(name) {
  const raw = String(name || "");
  const parts = raw.split(".");
  return parts.slice(-2).join(".") || raw || "step";
}

function riskLines(effects) {
  const e = effects || {};
  if (e.description) return [String(e.description)];
  const lines = [];
  if (e.network) lines.push("Will access the network.");
  if (e.filesystem_write) lines.push("Will write files on disk.");
  if (e.local_state_change) lines.push("Will change local data or config.");
  if (e.heavy_compute) lines.push("May run a heavy compute job.");
  return lines.length ? lines : ["Read-only / low side-effect."];
}

function composerHint() {
  if (mode === "ask") return "Ask: handbook Q&A. Does not execute.";
  if (mode === "agent") return "Agent: same confirm gate; live never auto.";
  return "Plan: review steps, then confirm.";
}

function pendingDecision() {
  const card = state.plan_card;
  const missing = (state.sidebar && state.sidebar.missing) || [];
  const clar = transcript.some((m) => m.kind === "clarification");
  return Boolean((card && card.confirmable) || missing.length || clar);
}

function $(id) {
  return document.getElementById(id);
}

function mountShell() {
  const root = $("root");
  root.innerHTML = `
    <div class="topbar">
      <span class="brand">qteasy-ai Workbench</span>
      <span class="mode-badge" data-testid="mode-badge">Mode: PLAN</span>
      <div class="mode-group">
        <button type="button" data-mode="ask">Ask</button>
        <button type="button" data-mode="plan">Plan</button>
        <button type="button" data-mode="agent">Agent</button>
      </div>
      <span class="spacer"></span>
      <span class="session-title" id="session-title"></span>
      <button type="button" class="ghost" id="btn-toggle-workspace" title="Toggle Workspace">Workspace</button>
    </div>
    <div class="layout" id="layout">
      <aside class="rail" id="session-rail">
        <div class="col-head">
          <h2>Sessions</h2>
          <button type="button" class="icon-btn ghost" id="btn-toggle-rail" title="Collapse session list">«</button>
        </div>
        <div class="rail-new" style="padding:6px;">
          <button type="button" class="primary" id="btn-new-session" style="width:100%;">New</button>
        </div>
        <div class="rail-body" id="session-list"></div>
      </aside>
      <section class="session-col" id="chat-col">
        <div class="col-head"><h2>Session</h2></div>
        <div class="now-chips" id="now-chips"></div>
        <div class="chat-log" id="chat-log"></div>
        <div class="composer">
          <div class="composer-meta">
            <span class="mode-badge" id="composer-mode">Mode: PLAN</span>
            <span id="composer-mode-hint"></span>
          </div>
          <textarea id="query-input" placeholder="Ask in natural language" rows="3"></textarea>
          <div class="composer-row">
            <span class="hint" id="composer-hint">Enter new line · Ctrl/⌘+Enter send</span>
            <span class="busy-dot" id="busy-label" hidden>Working…</span>
            <button type="button" class="primary" id="btn-send">Send</button>
          </div>
        </div>
      </section>
      <section class="artifact-col" id="artifact-col">
        <div class="col-head"><h2>Artifacts</h2></div>
        <div class="artifact-body" id="artifact-panel"></div>
      </section>
      <aside class="workspace-col" id="sidebar-col">
        <div class="col-head">
          <h2>Workspace</h2>
          <button type="button" class="icon-btn ghost" id="btn-collapse-workspace" title="Collapse">»</button>
        </div>
        <div class="workspace-body">
          <div class="now-block" id="workspace-now"></div>
          <div id="workspace-files"></div>
          <div class="g7-slot">Design loop / trial queue reserved for G.7</div>
        </div>
      </aside>
    </div>`;
  bindShell();
  shellReady = true;
  applyLayoutFlags();
  $("composer-mode-hint").textContent = composerHint();
}

function bindShell() {
  document.querySelectorAll("button[data-mode]").forEach((btn) => {
    btn.onclick = () => setMode(btn.getAttribute("data-mode"));
  });
  const input = $("query-input");
  $("btn-send").onclick = () => sendQuery(input.value);
  input.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    if (ev.isComposing || ev.keyCode === 229) return;
    if (ev.ctrlKey || ev.metaKey) {
      ev.preventDefault();
      sendQuery(input.value);
    }
  });
  $("btn-new-session").onclick = () => createSession();
  $("btn-toggle-rail").onclick = () => {
    railCollapsed = !railCollapsed;
    localStorage.setItem(STORAGE_RAIL, railCollapsed ? "1" : "0");
    applyLayoutFlags();
  };
  $("btn-toggle-workspace").onclick = toggleWorkspace;
  $("btn-collapse-workspace").onclick = toggleWorkspace;
  $("chat-log").addEventListener("click", onChatClick);
  $("artifact-panel").addEventListener("click", onArtifactClick);
  $("session-list").addEventListener("click", onSessionListClick);
  $("workspace-files").addEventListener("click", onWorkspaceFileClick);
}

function toggleWorkspace() {
  workspaceCollapsed = !workspaceCollapsed;
  localStorage.setItem(STORAGE_WORKSPACE, workspaceCollapsed ? "1" : "0");
  applyLayoutFlags();
  renderNowChips();
}

function applyLayoutFlags() {
  const layout = $("layout");
  const rail = $("session-rail");
  layout.classList.toggle("rail-collapsed", railCollapsed);
  layout.classList.toggle("workspace-collapsed", workspaceCollapsed);
  rail.classList.toggle("collapsed", railCollapsed);
  $("btn-toggle-rail").textContent = railCollapsed ? "»" : "«";
}

function setMode(next) {
  mode = next === "ask" || next === "agent" ? next : "plan";
  renderMode();
}

function renderMode() {
  const label = `Mode: ${mode.toUpperCase()}`;
  document.querySelectorAll("[data-testid='mode-badge'], #composer-mode").forEach((el) => {
    el.textContent = label;
  });
  document.querySelectorAll("button[data-mode]").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-mode") === mode);
  });
  $("composer-mode-hint").textContent = composerHint();
}

function setBusy(next) {
  busy = next;
  const input = $("query-input");
  const send = $("btn-send");
  if (input) input.disabled = busy;
  if (send) send.disabled = busy;
  const label = $("busy-label");
  if (label) label.hidden = !busy;
}

async function api(path, options) {
  const res = await fetch(path, options);
  let data = {};
  try {
    data = await res.json();
  } catch (exc) {
    data = {};
  }
  if (!res.ok) {
    const err = (data && data.error) || { message: "Request failed." };
    return {
      ...emptyState(),
      error: err,
      messages: [{ kind: "error", text: err.message || "Request failed.", payload: err }],
    };
  }
  return data;
}

function ingestDto(dto, { appendUser } = {}) {
  const prevCard = state.plan_card;
  state = Object.assign(emptyState(), dto || {});
  if (!state.session_id) state.session_id = sessionId;
  const incoming = Array.isArray(state.messages) ? state.messages : [];
  if (appendUser) {
    const last = transcript[transcript.length - 1];
    for (const msg of incoming) {
      if (msg.kind === "user_text" && last && last.kind === "user_text" && last.text === msg.text) continue;
      transcript.push(msg);
    }
  } else if (!transcript.length) {
    transcript = incoming.slice();
  }
  if (prevCard && prevCard.plan_id !== (state.plan_card && state.plan_card.plan_id)) {
    editingParams = false;
  }
}

async function sendQuery(query, { keepDraft } = {}) {
  const text = String(query || "").trim();
  if (!text || busy) return;
  const input = $("query-input");
  if (!keepDraft && input) input.value = "";
  transcript.push({ kind: "user_text", text });
  renderChat();
  setBusy(true);
  try {
    const body = JSON.stringify({ query: text, session_id: sessionId });
    const path = mode === "ask" ? "/v1/ask" : mode === "agent" ? "/v1/run" : "/v1/plan";
    const dto = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body });
    ingestDto(dto, { appendUser: true });
    artifactTab = 0;
    pendingCodeRun = false;
    filePreview = null;
    renderPanes();
    await refreshSessions();
    await refreshWorkspace();
  } catch (exc) {
    transcript.push({
      kind: "error",
      text: "Network error. Check that the workbench server is running.",
    });
    renderChat();
  } finally {
    setBusy(false);
  }
}

async function confirmPlan() {
  const planId = state.plan_card && state.plan_card.plan_id;
  if (!planId || (state.plan_card && state.plan_card.confirmable === false) || busy) return;
  setBusy(true);
  try {
    const dto = await api("/v1/run-plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: planId }),
    });
    ingestDto(dto, { appendUser: true });
    pendingCodeRun = false;
    renderPanes();
    await refreshWorkspace();
  } catch (exc) {
    transcript.push({
      kind: "error",
      text: "Network error. Confirm did not complete. Retry when the server is reachable.",
    });
    renderChat();
  } finally {
    setBusy(false);
  }
}

async function cancelPlan() {
  transcript.push({
    kind: "ask_text",
    text: "Plan cancelled. Type abandon if the session still holds an unfinished job.",
  });
  state = Object.assign({}, state, { plan_card: { ...(state.plan_card || {}), confirmable: false } });
  renderChat();
  await sendQuery("abandon", { keepDraft: true });
}

function followUp(text) {
  return sendQuery(text);
}

function onChatClick(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLElement)) return;
  if (t.id === "btn-confirm") confirmPlan();
  if (t.id === "btn-cancel") cancelPlan();
  if (t.id === "btn-edit") {
    editingParams = true;
    renderChat();
  }
  if (t.id === "btn-edit-cancel") {
    editingParams = false;
    renderChat();
  }
  if (t.id === "btn-edit-submit") submitParamEdits();
  if (t.id === "btn-clarify") submitClarification();
  if (t.dataset.example) {
    const ex = EXAMPLES[Number(t.dataset.example)];
    if (ex) {
      setMode(ex.mode);
      sendQuery(ex.text);
    }
  }
}

function submitClarification() {
  const bits = Array.from(document.querySelectorAll("#chat-log input[data-slot]"))
    .map((el) => {
      const name = el.getAttribute("data-slot");
      const value = String(el.value || "").trim();
      if (!value) return "";
      return `${name} ${value}`;
    })
    .filter(Boolean);
  if (!bits.length) return;
  followUp(bits.join(" "));
}

function submitParamEdits() {
  const bits = Array.from(document.querySelectorAll("#chat-log input[data-edit-slot]"))
    .map((el) => {
      const name = el.getAttribute("data-edit-slot");
      const value = String(el.value || "").trim();
      if (!value) return "";
      if (name === "slow" || name === "fast") return `把${name === "slow" ? "慢线" : "快线"}改成 ${value}`;
      return `${name} ${value}`;
    })
    .filter(Boolean);
  editingParams = false;
  if (!bits.length) {
    renderChat();
    return;
  }
  followUp(bits.join("；"));
}

function onArtifactClick(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLElement)) return;
  if (t.dataset.tab != null) {
    const editor = $("code-editor");
    if (editor) codeCache._draft = editor.value;
    artifactTab = Number(t.dataset.tab || 0);
    pendingCodeRun = false;
    renderArtifacts();
  }
  if (t.id === "btn-code-run") {
    pendingCodeRun = true;
    renderArtifacts();
  }
  if (t.id === "btn-code-confirm") {
    pendingCodeRun = false;
    confirmPlan();
  }
}

function onSessionListClick(ev) {
  const btn = ev.target.closest("[data-session-id]");
  if (!btn) return;
  switchSession(btn.getAttribute("data-session-id"));
}

async function onWorkspaceFileClick(ev) {
  const btn = ev.target.closest("[data-file-path]");
  if (!btn) return;
  const path = btn.getAttribute("data-file-path");
  const dto = await api(`/v1/workspace/file?path=${encodeURIComponent(path)}`);
  if (dto.content != null) {
    filePreview = { path, name: dto.name || path, content: dto.content };
    renderArtifacts();
  } else if (dto.error) {
    transcript.push({ kind: "error", text: dto.error.message || "Cannot preview this file." });
    renderChat();
  }
}

async function createSession() {
  sessionId = newSessionId();
  localStorage.setItem(STORAGE_SESSION, sessionId);
  state = emptyState();
  transcript = [];
  artifactTab = 0;
  pendingCodeRun = false;
  editingParams = false;
  filePreview = null;
  renderPanes();
  await refreshSessions();
}

async function switchSession(id) {
  if (!id || id === sessionId) return;
  sessionId = id;
  localStorage.setItem(STORAGE_SESSION, sessionId);
  const dto = await api(`/v1/session/${encodeURIComponent(id)}`);
  ingestDto(dto);
  transcript = [];
  for (const turn of dto.turns || []) {
    if (turn && turn.query) transcript.push({ kind: "user_text", text: String(turn.query) });
  }
  artifactTab = 0;
  filePreview = null;
  renderPanes();
}

async function refreshSessions() {
  const data = await api("/v1/sessions");
  sessions = data.sessions || [];
  if (sessionId && !sessions.some((row) => row.session_id === sessionId)) {
    sessions = [{ session_id: sessionId, title: sessionId, job: "" }, ...sessions];
  }
  renderSessionList();
}

async function refreshWorkspace() {
  const data = await api("/v1/workspace");
  workspace = data;
  renderWorkspace();
}

function renderSessionList() {
  const host = $("session-list");
  if (!host) return;
  host.innerHTML = sessions
    .map((row) => {
      const active = row.session_id === sessionId ? "active" : "";
      return `<button type="button" class="session-item ${active}" data-session-id="${escapeHtml(row.session_id)}">
        <span class="sid">${escapeHtml(row.title || row.session_id)}</span>
        <span class="meta">${escapeHtml(row.job || row.session_id)}</span>
      </button>`;
    })
    .join("");
  $("session-title").textContent = sessionId;
}

function renderChat() {
  const host = $("chat-log");
  if (!host) return;
  const stick = host.scrollHeight - host.scrollTop - host.clientHeight < 48;
  const parts = [];
  if (!transcript.length) {
    parts.push(`<div class="empty-hint">
      <p>This session is empty. Try a beginner step:</p>
      <div class="examples">${EXAMPLES.map(
        (ex, i) => `<button type="button" class="example" data-example="${i}">${escapeHtml(ex.mode.toUpperCase())}: ${escapeHtml(ex.text)}</button>`
      ).join("")}</div>
    </div>`);
  }
  for (const msg of transcript) {
    if (msg.kind === "plan_card" || msg.kind === "clarification" || msg.kind === "step_status") continue;
    if (msg.kind === "user_text") {
      parts.push(`<div class="msg user"><div class="msg-role">You</div><div class="bubble">${escapeHtml(msg.text)}</div></div>`);
    } else if (msg.kind === "error") {
      parts.push(`<div class="msg"><div class="msg-role">Error</div><div class="bubble err-text">${escapeHtml(msg.text || "Something went wrong.")}</div></div>`);
    } else {
      const src = (msg.payload && msg.payload.sources) || state.sources || [];
      const extra = src.length ? `<div class="warn">Sources: ${escapeHtml(src.join(", "))}</div>` : "";
      parts.push(`<div class="msg"><div class="msg-role">Assistant</div><div class="bubble">${escapeHtml(msg.text || "")}${extra}</div></div>`);
    }
  }
  parts.push(renderClarification());
  parts.push(renderPlanCard());
  parts.push(renderSteps());
  host.innerHTML = parts.join("");
  if (stick) host.scrollTop = host.scrollHeight;
}

function renderClarification() {
  const missing = (state.sidebar && state.sidebar.missing) || [];
  const clar = transcript.concat(state.messages || []).find((m) => m.kind === "clarification");
  if (!clar && !missing.length) return "";
  const pending = ((clar && clar.payload && clar.payload.pending) || []).map((item) => item.name || item).filter(Boolean);
  const fields = missing.length ? missing : pending;
  if (!fields.length && clar) {
    return `<div class="card" data-testid="clarification-form"><h3>Clarification</h3><p>${escapeHtml(clar.text || "")}</p></div>`;
  }
  const inputs = fields
    .map((name) => {
      const current = ((state.sidebar && state.sidebar.slots) || []).find((s) => s.name === name);
      const value = current && current.value != null ? String(current.value) : "";
      return `<div class="slot-row"><label>${escapeHtml(slotLabel(name))}<input data-slot="${escapeHtml(name)}" value="${escapeHtml(value)}" /></label></div>`;
    })
    .join("");
  const prompt = clar ? `<p>${escapeHtml(clar.text || "")}</p>` : "<p>Fill the missing fields, then submit.</p>";
  return `<div class="card" data-testid="clarification-form"><h3>Clarification</h3>${prompt}${inputs}<div class="actions"><button type="button" class="primary" id="btn-clarify">Submit slots</button></div></div>`;
}

function renderPlanCard() {
  const card = state.plan_card;
  if (!card || !card.confirmable || mode === "ask") return "";
  const steps = (card.steps || [])
    .map((s) => {
      const risks = riskLines(s.side_effects)
        .map((line) => `<div class="risk">${escapeHtml(line)}</div>`)
        .join("");
      return `<li><strong>${escapeHtml(skillLabel(s.skill_name))}</strong>${risks}</li>`;
    })
    .join("");
  let editor = "";
  if (editingParams) {
    const slots = (state.sidebar && state.sidebar.slots) || [];
    const rows = slots.length
      ? slots
          .map(
            (s) =>
              `<div class="slot-row"><label>${escapeHtml(slotLabel(s.name))}<input data-edit-slot="${escapeHtml(s.name)}" value="${escapeHtml(s.value == null ? "" : String(s.value))}" /></label></div>`
          )
          .join("")
      : `<div class="slot-row"><label>Follow-up<input data-edit-slot="note" placeholder="Describe the change" /></label></div>`;
    editor = `${rows}<div class="actions"><button type="button" class="primary" id="btn-edit-submit">Apply changes</button><button type="button" id="btn-edit-cancel">Back</button></div>`;
  }
  const busyLock = busy ? "disabled" : "";
  return `<div class="card" data-testid="plan-card"><h3>Review plan</h3>
    <p class="warn">Plan ${escapeHtml(card.plan_id)}</p>
    <ol>${steps}</ol>
    ${editor}
    <div class="actions">
      <button type="button" class="primary" id="btn-confirm" ${busyLock}>Confirm</button>
      <button type="button" id="btn-edit">Change params</button>
      <button type="button" class="danger" id="btn-cancel">Cancel</button>
    </div></div>`;
}

function renderSteps() {
  const steps = (state.execution && state.execution.steps) || [];
  if (!steps.length) return "";
  return `<ol class="step-list" data-testid="step-list">${steps
    .map((s) => {
      const st = s.status || "pending";
      const mark = st === "done" ? "✓" : st === "error" ? "✕" : "•";
      return `<li class="step ${escapeHtml(st)}">${mark} ${escapeHtml(skillLabel(s.skill_name || s.step_id))} <small>${escapeHtml(st)}</small></li>`;
    })
    .join("")}</ol>`;
}

function tableFromRows(rows) {
  if (!rows.length) return "<p class=\"empty-hint\">No preview rows.</p>";
  const first = rows[0];
  if (first && typeof first === "object" && !Array.isArray(first)) {
    const cols = Object.keys(first);
    const head = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
    const body = rows
      .map((row) => `<tr>${cols.map((c) => `<td>${escapeHtml(row[c])}</td>`).join("")}</tr>`)
      .join("");
    return `<table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }
  return `<table class="data-table"><tbody>${rows
    .map((row) => `<tr><td>${escapeHtml(typeof row === "string" ? row : JSON.stringify(row))}</td></tr>`)
    .join("")}</tbody></table>`;
}

function metricsCards(metrics) {
  const entries = Object.entries(metrics || {});
  if (!entries.length) return "<p class=\"empty-hint\">No metrics.</p>";
  return `<div class="metrics">${entries
    .map(([k, v]) => {
      const shown = typeof v === "number" ? String(Number.isInteger(v) ? v : Number(v).toPrecision(4)) : String(v);
      return `<div class="metric"><div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(shown)}</div></div>`;
    })
    .join("")}</div>`;
}

function renderArtifacts() {
  const host = $("artifact-panel");
  if (!host) return;
  const editor = $("code-editor");
  if (editor) codeCache._draft = editor.value;
  const arts = state.artifacts || [];
  if (filePreview) {
    host.innerHTML = `<div class="card"><h3>${escapeHtml(filePreview.name)}</h3><p class="warn">${escapeHtml(filePreview.path)}</p><textarea rows="16" readonly>${escapeHtml(filePreview.content)}</textarea></div>`;
    return;
  }
  if (!arts.length) {
    host.innerHTML = `<p class="empty-hint">No artifacts yet. Confirm a plan to see tables, charts, or code here.</p>`;
    return;
  }
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
    const summary = (current.preview && current.preview.data_summary) || {};
    body = `${metricsCards(summary)}${tableFromRows(rows)}`;
    if (current.export_path) {
      body += `<p><a href="/v1/artifacts/${encodeURIComponent(current.run_id)}?path=${encodeURIComponent(current.export_path)}">Export</a></p>`;
    }
  } else if (current.type === "chart") {
    if (current.warnings && current.warnings.length) body += `<p class="warn">${escapeHtml(current.warnings.join(" "))}</p>`;
    if (current.export_path) {
      const href = `/v1/artifacts/${encodeURIComponent(current.run_id)}?path=${encodeURIComponent(current.export_path)}`;
      body += `<p><a href="${href}">Download PNG</a></p><img class="chart-img" alt="chart" src="${href}" />`;
    } else body += `<p class="warn">Chart file path is missing.</p>`;
  } else if (current.type === "strategy_code") {
    const path = (current.preview && current.preview.path) || current.export_path || "";
    const draft = codeCache._draft != null ? codeCache._draft : codeCache[path] || "";
    body = `<textarea id="code-editor" rows="12">${escapeHtml(draft)}</textarea>
      <div class="actions"><button type="button" id="btn-code-run">Run (requires confirm)</button></div>
      ${pendingCodeRun ? `<div class="card">Confirm running edited strategy?<button type="button" class="primary" id="btn-code-confirm">Confirm run</button></div>` : ""}`;
    if (path && codeCache[path] == null) loadCode(path);
  } else if (current.type === "backtest_report") {
    const metrics = (current.preview && current.preview.metrics) || {};
    body = `${metricsCards(metrics)}
      ${current.export_path ? `<p><a href="/v1/artifacts/${encodeURIComponent(current.run_id)}?path=${encodeURIComponent(current.export_path)}">trade_log</a></p>` : ""}
      <p class="warn">run_id ${escapeHtml(current.run_id)}</p>`;
  }
  host.innerHTML = `<div class="tabs">${tabs}</div><div data-testid="artifact-panel">${body}</div>`;
  const ta = $("code-editor");
  if (ta) {
    ta.addEventListener("input", () => {
      codeCache._draft = ta.value;
    });
  }
}

async function loadCode(path) {
  const dto = await api(`/v1/workspace/file?path=${encodeURIComponent(path)}`);
  if (dto.content != null) {
    codeCache[path] = dto.content;
    const ta = $("code-editor");
    if (ta && !codeCache._draft) ta.value = dto.content;
  }
}

function envLine(summary) {
  const env = summary || {};
  const keys = Object.keys(env);
  if (!keys.length) return "No env_facts yet.";
  const token = env.tushare_token_set || env.has_tushare_token;
  const tables = env.tables || env.local_tables;
  const bits = [];
  if (token != null) bits.push(token ? "Tushare token ready" : "Tushare token missing");
  if (tables) bits.push(typeof tables === "string" ? tables : `tables=${JSON.stringify(tables).slice(0, 80)}`);
  return bits.join(" · ") || `${keys.length} env keys`;
}

function renderNow() {
  const host = $("workspace-now");
  if (!host) return;
  const bar = state.sidebar || {};
  const job = (bar.active_intent && bar.active_intent.job) || "—";
  const missing = (bar.missing || []).map(slotLabel).join(", ") || "—";
  const slots = (bar.slots || [])
    .map((s) => `<li>${escapeHtml(slotLabel(s.name))}: ${escapeHtml(s.value == null ? "—" : String(s.value))}${s.confirmed ? "" : " (unconfirmed)"}</li>`)
    .join("");
  host.innerHTML = `<p><strong>Now</strong></p>
    <p>Job: ${escapeHtml(job)}</p>
    <p>Missing: ${escapeHtml(missing)}</p>
    <p>Plan: ${escapeHtml(bar.current_plan_id || "—")}</p>
    <p>${escapeHtml(envLine(bar.env_summary))}</p>
    <ul>${slots || "<li>No slots yet.</li>"}</ul>`;
  renderNowChips();
}

function renderNowChips() {
  const host = $("now-chips");
  if (!host) return;
  const bar = state.sidebar || {};
  const job = (bar.active_intent && bar.active_intent.job) || "idle";
  const missing = (bar.missing || []).map(slotLabel).join(", ");
  host.innerHTML = `<span class="chip">Job ${escapeHtml(job)}</span>${
    missing ? `<span class="chip warn">Missing ${escapeHtml(missing)}</span>` : ""
  }`;
}

function renderFileTree(nodes) {
  return `<ul class="file-tree">${(nodes || [])
    .map((node) => {
      if (node.kind === "dir") {
        return `<li><div class="dir-name">${escapeHtml(node.name)}</div>${renderFileTree(node.children)}</li>`;
      }
      return `<li><button type="button" class="file" data-file-path="${escapeHtml(node.path)}">${escapeHtml(node.name)}</button></li>`;
    })
    .join("")}</ul>`;
}

function renderWorkspace() {
  renderNow();
  const host = $("workspace-files");
  if (!host) return;
  const trees = workspace.trees || [];
  host.innerHTML = `<p style="padding:0 8px;color:var(--text-muted);font-size:11px;text-transform:uppercase;">Files</p>${renderFileTree(trees)}`;
}

function renderPanes() {
  renderMode();
  renderSessionList();
  renderChat();
  renderArtifacts();
  renderWorkspace();
}

function render() {
  if (!shellReady) mountShell();
  renderPanes();
}

mountShell();
renderMode();
refreshSessions().then(() => refreshWorkspace()).then(() => renderPanes());
