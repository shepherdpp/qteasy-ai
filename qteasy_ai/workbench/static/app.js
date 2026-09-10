const STORAGE_SESSION = "qteasy-ai.session_id";
const STORAGE_RAIL = "qteasy-ai.session-rail";
const STORAGE_WORKSPACE = "qteasy-ai.workspace";
const STORAGE_TRANSCRIPTS = "qteasy-ai.transcripts";

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

const SKILL_TITLES = {
  "qt.ai.strategy_meta.list": "List built-in strategies",
  "qt.ai.strategy_meta.get": "Show strategy parameters",
  "qt.ai.data.refill_basic_equity_and_index": "Download daily bars (bounded window)",
  "qt.ai.data.read": "Read market data",
  "qt.ai.data.summary_kline": "Summarize k-line statistics",
  "qt.ai.visual.export_kline": "Export a k-line chart",
  "qt.ai.backtest.run_builtin": "Run a built-in backtest",
  "qt.ai.optimize.run_builtin": "Run built-in parameter optimization",
  "qt.ai.strategy.codegen_hybrid": "Generate strategy source",
  "qt.ai.pipeline.live_trade_plan_only": "Live-trade checklist (never auto-executes)",
  "qt.ai.system.fallback": "Need a more specific request",
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
let editingNowSlot = "";
let busy = false;
let shellReady = false;
let codeCache = {};
let filePreview = null;
let sessions = [];
let workspace = { artifacts: [] };
let railCollapsed = localStorage.getItem(STORAGE_RAIL) === "1";
let workspaceCollapsed = localStorage.getItem(STORAGE_WORKSPACE) === "1";
let modeNotice = "";
let editingUserIndex = -1;
let providerInfo = null;
let pendingRewind = null;

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
      design: null,
      trial_queue: [],
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

function stepTitle(step) {
  if (!step) return "step";
  return String(step.summary || SKILL_TITLES[step.skill_name] || skillLabel(step.skill_name));
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

function riskBadges(effects) {
  const e = effects || {};
  const tags = [];
  if (e.network) tags.push(["network", "warn"]);
  if (e.filesystem_write) tags.push(["write", "warn"]);
  if (e.local_state_change) tags.push(["state", "warn"]);
  if (e.heavy_compute) tags.push(["heavy", "warn"]);
  if (!tags.length) tags.push(["read-only", "ok"]);
  return tags.map(([label, kind]) => `<span class="badge ${kind}">${escapeHtml(label)}</span>`).join("");
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

function formatInputs(inputs) {
  const raw = inputs && typeof inputs === "object" ? inputs : {};
  const bits = Object.entries(raw)
    .filter(([key, val]) => val != null && val !== "" && !String(key).startsWith("upstream_"))
    .map(([key, val]) => `${slotLabel(key)}=${typeof val === "string" ? val : JSON.stringify(val)}`);
  return bits.slice(0, 8).join(" · ");
}

const JOB_STAGE = {
  "data.read": "data",
  "data.refill": "data",
  "data.summary": "data",
  "data.export": "data",
  "env.ready": "data",
  "research.screen": "analysis",
  "research.factor_ic": "analysis",
  "strategy.meta": "strategy",
  "strategy.builder": "strategy",
  "backtest.builtin": "backtest",
  "optimize.builtin": "backtest",
  "insight.last_backtest": "backtest",
  "live.plan_only": "backtest",
};

function pipelineHtml(job) {
  const current = JOB_STAGE[job] || "";
  return ["data", "analysis", "strategy", "backtest"]
    .map((name) => `<span class="pipe ${name === current ? "active" : ""}">${name}</span>`)
    .join("<span class=\"pipe-sep\">→</span>");
}

function isCompactPlan(card) {
  const steps = (card && card.steps) || [];
  if (!steps.length || steps.length > 2) return false;
  return steps.every((s) => !s.needs_confirm);
}

function focusComposer() {
  const input = $("query-input");
  if (input && !busy) input.focus();
}

function $(id) {
  return document.getElementById(id);
}

function readTranscriptMap() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_TRANSCRIPTS) || "{}");
    return raw && typeof raw === "object" ? raw : {};
  } catch (exc) {
    return {};
  }
}

function persistTranscript() {
  const all = readTranscriptMap();
  all[sessionId] = transcript;
  localStorage.setItem(STORAGE_TRANSCRIPTS, JSON.stringify(all));
}

function loadTranscriptFor(id) {
  const all = readTranscriptMap();
  return Array.isArray(all[id]) ? all[id] : [];
}

function mountShell() {
  const root = $("root");
  root.innerHTML = `
    <div class="topbar">
      <span class="brand">qteasy-ai Workbench</span>
      <span class="spacer"></span>
      <span class="session-title" id="session-title"></span>
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
        <div class="mode-notice" id="mode-notice" hidden></div>
        <div class="chat-log" id="chat-log"></div>
        <div class="composer">
          <div class="composer-meta">
            <span class="mode-badge" data-testid="mode-badge" id="composer-mode">Mode: PLAN</span>
            <div class="mode-group">
              <button type="button" data-mode="ask">Ask</button>
              <button type="button" data-mode="plan">Plan</button>
              <button type="button" data-mode="agent">Agent</button>
            </div>
            <span id="composer-mode-hint"></span>
          </div>
          <textarea id="query-input" placeholder="Ask in natural language" rows="3"></textarea>
          <div class="composer-row">
            <span class="hint" id="composer-hint">Enter new line · Ctrl/⌘+Enter send</span>
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
          <div class="g7-slot" id="g7-slot"></div>
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
  $("btn-collapse-workspace").onclick = toggleWorkspace;
  $("now-chips").addEventListener("click", () => {
    if (workspaceCollapsed) toggleWorkspace();
  });
  $("chat-log").addEventListener("click", onChatClick);
  $("artifact-panel").addEventListener("click", onArtifactClick);
  $("session-list").addEventListener("click", onSessionListClick);
  $("workspace-files").addEventListener("click", onWorkspaceArtifactClick);
  $("workspace-now").addEventListener("click", onNowClick);
  $("g7-slot").addEventListener("click", onChatClick);
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
  const workspaceCol = $("sidebar-col");
  if (workspaceCol) workspaceCol.classList.toggle("collapsed", workspaceCollapsed);
  $("btn-toggle-rail").textContent = railCollapsed ? "»" : "«";
  const wsBtn = $("btn-collapse-workspace");
  if (wsBtn) wsBtn.textContent = workspaceCollapsed ? "«" : "»";
}

function applySessionMode(dto) {
  const raw = String((dto && dto.mode) || "").toLowerCase();
  if (raw === "ask") mode = "ask";
  else if (raw === "run" || raw === "agent") mode = "agent";
  else if (raw === "plan") mode = "plan";
}

function dismissModeNotice() {
  modeNotice = "";
  renderMode();
}

function setMode(next) {
  if (busy) return;
  const prev = mode;
  mode = next === "ask" || next === "agent" ? next : "plan";
  if (prev !== mode) {
    const gate = pendingDecision()
      ? " Existing Confirm / Cancel still apply; this switch does not execute."
      : "";
    modeNotice = `Switched to ${mode.toUpperCase()}. ${composerHint()}${gate}`;
  }
  renderMode();
  renderChat();
}

function renderMode() {
  const label = `Mode: ${mode.toUpperCase()}`;
  document.querySelectorAll("[data-testid='mode-badge'], #composer-mode").forEach((el) => {
    el.textContent = label;
  });
  document.querySelectorAll("button[data-mode]").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-mode") === mode);
    btn.disabled = busy;
  });
  $("composer-mode-hint").textContent = composerHint();
  const notice = $("mode-notice");
  if (notice) {
    notice.hidden = !modeNotice;
    notice.innerHTML = modeNotice
      ? `${escapeHtml(modeNotice)} <button type="button" class="ghost" id="btn-dismiss-notice">Dismiss</button>`
      : "";
    const dismiss = $("btn-dismiss-notice");
    if (dismiss) dismiss.onclick = dismissModeNotice;
  }
}

function setBusy(next) {
  busy = next;
  const input = $("query-input");
  const send = $("btn-send");
  if (input) input.disabled = busy;
  if (send) send.disabled = busy;
  document.querySelectorAll("button[data-mode]").forEach((btn) => {
    btn.disabled = busy;
  });
  ["btn-confirm", "btn-cancel", "btn-edit", "btn-clarify", "btn-retry"].forEach((id) => {
    const el = $(id);
    if (el) el.disabled = busy;
  });
  document.querySelectorAll(".btn-abandon-trial, .btn-abandon-open, .btn-kb-write").forEach((el) => {
    el.disabled = busy;
  });
  renderChat();
}

function errorFromHttp(data) {
  const err = (data && data.error) || { message: "Request failed." };
  return {
    ...emptyState(),
    error: err,
    messages: [{ kind: "error", text: err.message || "Request failed.", payload: err }],
  };
}

async function api(path, options) {
  const res = await fetch(path, options);
  const ctype = res.headers.get("content-type") || "";
  if (ctype.includes("text/event-stream") && res.body) {
    return consumeSse(res);
  }
  let data = {};
  try {
    data = await res.json();
  } catch (exc) {
    data = {};
  }
  if (!res.ok) {
    if (data && data.needs_confirm) return data;
    return errorFromHttp(data);
  }
  return data;
}

async function consumeSse(res) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let finalDto = null;
  let sseError = null;
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buf += decoder.decode(chunk.value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const block of parts) {
      const eventMatch = block.match(/^event:\s*(.+)$/m);
      const dataMatch = block.match(/^data:\s*(.+)$/m);
      if (!dataMatch) continue;
      let payload = {};
      try {
        payload = JSON.parse(dataMatch[1]);
      } catch (exc) {
        continue;
      }
      const ev = eventMatch ? eventMatch[1].trim() : "";
      if (ev === "step_status") applyLiveStep(payload);
      else if (ev === "state") finalDto = payload;
      else if (ev === "error") sseError = payload;
    }
  }
  if (sseError) return errorFromHttp(sseError);
  return finalDto || errorFromHttp({ error: { message: "Stream ended without a state event." } });
}

function applyLiveStep(event) {
  const steps = Array.isArray(state.execution && state.execution.steps) ? state.execution.steps.slice() : [];
  const row = {
    step_id: event.step_id,
    skill_name: event.skill_name,
    status: event.status || (event.ok ? "done" : "error"),
    ok: event.ok,
  };
  const idx = steps.findIndex((s) => s.step_id && s.step_id === event.step_id);
  if (idx >= 0) steps[idx] = Object.assign({}, steps[idx], row);
  else steps.push(row);
  state.execution = Object.assign({}, state.execution || {}, { status: "running", steps });
  renderChat();
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
  persistTranscript();
}

function mergeRestoredTranscript(dto) {
  const local = loadTranscriptFor(sessionId);
  const fromTurns = (dto.turns || [])
    .filter((t) => t && t.query)
    .map((t) => ({ kind: "user_text", text: String(t.query) }));
  const fromDto = (dto.messages || []).filter(
    (m) => m.kind !== "plan_card" && m.kind !== "step_status"
  );
  const seed = local.length ? local.slice() : fromTurns;
  const seen = new Set(seed.map((m) => `${m.kind}:${m.text}`));
  transcript = seed.slice();
  for (const msg of fromDto) {
    const key = `${msg.kind}:${msg.text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    transcript.push(msg);
  }
  persistTranscript();
}

async function sendQuery(query, { keepDraft } = {}) {
  const text = String(query || "").trim();
  if (!text || busy) return;
  dismissModeNotice();
  const input = $("query-input");
  if (!keepDraft && input) input.value = "";
  transcript.push({ kind: "user_text", text });
  persistTranscript();
  renderChat();
  setBusy(true);
  try {
    const body = JSON.stringify({ query: text, session_id: sessionId });
    const path = mode === "ask" ? "/v1/ask" : mode === "agent" ? "/v1/run?stream=1" : "/v1/plan";
    const headers = { "Content-Type": "application/json" };
    if (mode === "agent") headers.Accept = "text/event-stream";
    const dto = await api(path, { method: "POST", headers, body });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
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
      payload: { next_action: "Retry when the server is reachable. You do not need to start over." },
    });
    persistTranscript();
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
    const dto = await api("/v1/run-plan?stream=1", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ plan_id: planId, session_id: sessionId }),
    });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    pendingCodeRun = false;
    renderPanes();
    await refreshWorkspace();
  } catch (exc) {
    transcript.push({
      kind: "error",
      text: "Network error. Confirm did not complete. Retry when the server is reachable.",
      payload: { next_action: "Press Retry. You do not need to start over." },
    });
    persistTranscript();
    renderChat();
  } finally {
    setBusy(false);
  }
}

async function abandonTrial() {
  if (busy) return;
  setBusy(true);
  try {
    const dto = await api("/v1/open/abandon-trial", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    renderPanes();
  } catch (exc) {
    transcript.push({
      kind: "error",
      text: "Could not abandon the trial. Retry when the server is reachable.",
      payload: { next_action: "Press Abandon trial again." },
    });
    persistTranscript();
    renderChat();
  } finally {
    setBusy(false);
  }
}

async function abandonOpen() {
  if (busy) return;
  setBusy(true);
  try {
    const dto = await api("/v1/open/abandon-job", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    renderPanes();
  } catch (exc) {
    transcript.push({
      kind: "error",
      text: "Could not abandon the open job. Retry when the server is reachable.",
      payload: { next_action: "Press Abandon open job again." },
    });
    persistTranscript();
    renderChat();
  } finally {
    setBusy(false);
  }
}

async function confirmKbWrite() {
  if (busy) return;
  setBusy(true);
  try {
    const dto = await api("/v1/kb/write", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, confirm: true }),
    });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    renderPanes();
    await refreshWorkspace();
  } catch (exc) {
    transcript.push({
      kind: "error",
      text: "Could not write the user-KB note. Retry when the server is reachable.",
      payload: { next_action: "Confirm the write again after reviewing the draft." },
    });
    persistTranscript();
    renderChat();
  } finally {
    setBusy(false);
  }
}

async function cancelPlan() {
  if (busy) return;
  transcript.push({
    kind: "ask_text",
    text: "Plan cancelled. Type abandon if the session still holds an unfinished job.",
  });
  persistTranscript();
  state = Object.assign({}, state, { plan_card: { ...(state.plan_card || {}), confirmable: false } });
  renderChat();
  await sendQuery("abandon", { keepDraft: true });
}

function followUp(text) {
  return sendQuery(text);
}

function retryLast() {
  if (busy) return;
  const planId = state.plan_card && state.plan_card.plan_id;
  const failed = ((state.execution && state.execution.steps) || []).some((s) => s.status === "error");
  if (planId && (failed || state.error)) {
    confirmPlan();
    return;
  }
  if (planId && state.plan_card && state.plan_card.confirmable) {
    confirmPlan();
    return;
  }
  const lastUser = [...transcript].reverse().find((m) => m.kind === "user_text");
  if (lastUser) sendQuery(lastUser.text);
}

function onChatClick(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLElement)) return;
  if (t.id === "btn-confirm" || t.id === "btn-code-confirm") confirmPlan();
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
  if (t.classList.contains("btn-retry") || t.id === "btn-retry") retryLast();
  if (t.dataset.editUser != null) {
    editingUserIndex = Number(t.dataset.editUser);
    pendingRewind = null;
    renderChat();
    return;
  }
  if (t.id === "btn-rewind-cancel") {
    editingUserIndex = -1;
    pendingRewind = null;
    renderChat();
    return;
  }
  if (t.id === "btn-rewind-submit") {
    const box = $("rewind-text");
    rewindUserMessage(editingUserIndex, box ? box.value : "", false);
    return;
  }
  if (t.id === "btn-rewind-discard") {
    const box = $("rewind-text");
    const text = (pendingRewind && pendingRewind.query) || (box ? box.value : "");
    rewindUserMessage(editingUserIndex, text, true);
    return;
  }
  if (t.id === "btn-abandon-trial" || t.classList.contains("btn-abandon-trial")) {
    abandonTrial();
    return;
  }
  if (t.id === "btn-abandon-open" || t.classList.contains("btn-abandon-open")) {
    abandonOpen();
    return;
  }
  if (t.id === "btn-kb-write" || t.classList.contains("btn-kb-write")) {
    confirmKbWrite();
    return;
  }
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
  const bits = Array.from(document.querySelectorAll("#chat-log input[data-edit-slot], #workspace-now input[data-now-slot]"))
    .map((el) => {
      const name = el.getAttribute("data-edit-slot") || el.getAttribute("data-now-slot");
      const value = String(el.value || "").trim();
      if (!value) return "";
      if (name === "slow" || name === "fast") return `把${name === "slow" ? "慢线" : "快线"}改成 ${value}`;
      return `${name} ${value}`;
    })
    .filter(Boolean);
  editingParams = false;
  editingNowSlot = "";
  if (!bits.length) {
    renderChat();
    renderNow();
    return;
  }
  followUp(bits.join("；"));
}

async function submitProviderChange() {
  const model = ($("prov-model") && $("prov-model").value) || "";
  const baseUrl = ($("prov-url") && $("prov-url").value) || "";
  const apiKey = ($("prov-key") && $("prov-key").value) || "";
  const dto = await api("/v1/provider", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, base_url: baseUrl, api_key: apiKey, confirmed: true }),
  });
  if (dto && dto.error) {
    transcript.push({ kind: "error", text: dto.error.message || "Provider update failed.", payload: dto.error });
    renderChat();
    return;
  }
  providerInfo = dto;
  editingNowSlot = "";
  renderNow();
}

function onNowClick(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLElement)) return;
  if (t.dataset.nowEdit) {
    editingNowSlot = t.dataset.nowEdit;
    renderNow();
    return;
  }
  if (t.id === "btn-now-apply") submitParamEdits();
  if (t.id === "btn-now-cancel") {
    editingNowSlot = "";
    renderNow();
  }
  if (t.id === "btn-prov-edit") {
    editingNowSlot = "__provider__";
    renderNow();
    return;
  }
  if (t.id === "btn-prov-cancel") {
    editingNowSlot = "";
    renderNow();
    return;
  }
  if (t.id === "btn-prov-confirm") submitProviderChange();
}

function onArtifactClick(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLElement)) return;
  if (t.dataset.tab != null) {
    const editor = $("code-editor");
    if (editor) codeCache._draft = editor.value;
    artifactTab = Number(t.dataset.tab || 0);
    pendingCodeRun = false;
    filePreview = null;
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
  if (t.id === "btn-file-back") {
    filePreview = null;
    renderArtifacts();
  }
}

function onSessionListClick(ev) {
  const btn = ev.target.closest("[data-session-id]");
  if (!btn) return;
  switchSession(btn.getAttribute("data-session-id"));
}

async function rewindUserMessage(index, text, confirmDiscard) {
  const query = String(text || "").trim();
  if (!query || busy || index < 0) return;
  setBusy(true);
  try {
    const dto = await api(`/v1/session/${encodeURIComponent(sessionId)}/rewind`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message_index: index,
        query,
        mode,
        confirm_discard: Boolean(confirmDiscard),
      }),
    });
    if (dto && dto.needs_confirm) {
      pendingRewind = { query, executed: dto.executed_run_ids || [] };
      renderChat();
      return;
    }
    if (dto && dto.error && !dto.transcript) {
      transcript.push({
        kind: "error",
        text: (dto.error && dto.error.message) || "Rewind failed.",
        payload: dto.error || {},
      });
      renderChat();
      return;
    }
    editingUserIndex = -1;
    pendingRewind = null;
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    artifactTab = 0;
    filePreview = null;
    renderPanes();
    await refreshSessions();
    await refreshWorkspace();
  } finally {
    setBusy(false);
    focusComposer();
  }
}

function applyServerTranscript(dto) {
  const server = Array.isArray(dto && dto.transcript) ? dto.transcript : [];
  transcript = server.filter((m) => m && m.kind !== "plan_card" && m.kind !== "step_status");
  persistTranscript();
}

async function onWorkspaceArtifactClick(ev) {
  const btn = ev.target.closest("[data-art-index]");
  if (!btn) return;
  const idx = Number(btn.getAttribute("data-art-index") || 0);
  artifactTab = idx;
  filePreview = null;
  const listed = workspace.artifacts || [];
  if (listed.length) state.artifacts = listed;
  renderArtifacts();
}

async function createSession() {
  persistTranscript();
  sessionId = newSessionId();
  localStorage.setItem(STORAGE_SESSION, sessionId);
  state = emptyState();
  transcript = [];
  persistTranscript();
  artifactTab = 0;
  pendingCodeRun = false;
  editingParams = false;
  editingNowSlot = "";
  editingUserIndex = -1;
  pendingRewind = null;
  filePreview = null;
  workspace = { artifacts: [] };
  state.artifacts = [];
  modeNotice = "";
  mode = "plan";
  renderPanes();
  await refreshSessions();
  focusComposer();
}

async function switchSession(id) {
  if (!id || id === sessionId || busy) return;
  persistTranscript();
  sessionId = id;
  localStorage.setItem(STORAGE_SESSION, sessionId);
  transcript = [];
  const dto = await api(`/v1/session/${encodeURIComponent(id)}`);
  ingestDto(dto);
  applySessionMode(dto);
  applyServerTranscript(dto);
  artifactTab = 0;
  filePreview = null;
  editingNowSlot = "";
  editingUserIndex = -1;
  pendingRewind = null;
  await refreshWorkspace();
  await refreshProvider();
  renderPanes();
  focusComposer();
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
  const data = await api(`/v1/workspace?session_id=${encodeURIComponent(sessionId)}`);
  workspace = data && Array.isArray(data.artifacts) ? data : { artifacts: [] };
  state.artifacts = workspace.artifacts || [];
  renderWorkspace();
  renderArtifacts();
}

async function refreshProvider() {
  const data = await api("/v1/provider");
  if (data && !data.error) providerInfo = data;
  renderNow();
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
  const current = sessions.find((row) => row.session_id === sessionId);
  $("session-title").textContent = (current && (current.title || current.job)) || sessionId;
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
  for (let i = 0; i < transcript.length; i += 1) {
    const msg = transcript[i];
    if (msg.kind === "plan_card" || msg.kind === "clarification" || msg.kind === "step_status" || msg.kind === "design_card" || msg.kind === "kb_write") continue;
    if (
      msg.kind === "ask_text" &&
      String(msg.text || "").startsWith("Plan ready:") &&
      state.plan_card &&
      state.plan_card.confirmable &&
      mode !== "ask"
    ) {
      continue;
    }
    if (msg.kind === "user_text") {
      if (editingUserIndex === i) {
        const warn = pendingRewind
          ? `<p class="warn">Later executed runs will be discarded: ${(pendingRewind.executed || []).join(", ") || "yes"}. Confirm to continue.</p>`
          : "";
        const discardBtn = pendingRewind
          ? `<button type="button" class="primary" id="btn-rewind-discard">Confirm discard and resend</button>`
          : `<button type="button" class="primary" id="btn-rewind-submit">Resend from here</button>`;
        parts.push(`<div class="msg user"><div class="msg-role">You</div><div class="bubble editing">
          ${warn}<textarea id="rewind-text" rows="3">${escapeHtml((pendingRewind && pendingRewind.query) || msg.text || "")}</textarea>
          <div class="actions">${discardBtn}<button type="button" class="ghost" id="btn-rewind-cancel">Cancel</button></div>
        </div></div>`);
      } else {
        parts.push(`<div class="msg user"><div class="msg-role">You <button type="button" class="ghost" data-edit-user="${i}">Edit</button></div><div class="bubble">${escapeHtml(msg.text)}</div></div>`);
      }
    } else if (msg.kind === "error") {
      const next = (msg.payload && msg.payload.next_action) || "";
      parts.push(`<div class="msg"><div class="msg-role">Error</div><div class="bubble err-text">${escapeHtml(msg.text || "Something went wrong.")}${
        next ? `<div class="next-action">${escapeHtml(next)}</div>` : ""
      }<div class="actions"><button type="button" class="primary btn-retry" id="btn-retry">Retry</button></div></div></div>`);
    } else {
      const src = (msg.payload && msg.payload.sources) || state.sources || [];
      const extra = src.length ? `<div class="warn">Sources: ${escapeHtml(src.join(", "))}</div>` : "";
      parts.push(`<div class="msg"><div class="msg-role">Assistant</div><div class="bubble">${escapeHtml(msg.text || "")}${extra}</div></div>`);
    }
  }
  if (busy) {
    parts.push(`<div class="msg" id="busy-msg"><div class="msg-role">Assistant</div><div class="bubble busy-bubble"><span class="busy-dot">Working…</span></div></div>`);
  }
  parts.push(renderClarification());
  parts.push(renderDesignCard());
  parts.push(renderKbWriteCard());
  parts.push(renderPlanCard());
  parts.push(renderSteps());
  host.innerHTML = parts.join("");
  if (stick || busy) host.scrollTop = host.scrollHeight;
}

function latestMessage(kind) {
  const rows = transcript.concat(state.messages || []);
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (rows[i] && rows[i].kind === kind) return rows[i];
  }
  return null;
}

function renderDesignCard() {
  const msg = latestMessage("design_card");
  const design = (state.sidebar && state.sidebar.design) || (msg && msg.payload) || null;
  if (!design && !msg) return "";
  const spec = (design && design.spec_draft) || (msg && msg.payload && msg.payload.spec_draft) || {};
  const hits = (design && design.kb_hits) || (msg && msg.payload && msg.payload.kb_hits) || [];
  const lock = busy ? "disabled" : "";
  const hitLines = hits.length
    ? `<ul class="kb-hits">${hits
        .map((hit) => `<li>${escapeHtml(hit.path || hit.title || "")}</li>`)
        .join("")}</ul>`
    : `<p class="hint">No user-KB notes matched this draft.</p>`;
  return `<div class="card" data-testid="design-card"><h3>Design loop</h3>
    <p>${escapeHtml((msg && msg.text) || "Refine the FactorSpec before a closed trial.")}</p>
    <p><strong>${escapeHtml(spec.name || "unnamed")}</strong> · ${escapeHtml(spec.universe || "universe TBD")}</p>
    <p>${escapeHtml(spec.hypothesis || "")}</p>
    <p class="hint">Suggested trial: ${escapeHtml(spec.suggested_job || "research.factor_ic")}</p>
    <p class="files-k">User KB sources</p>${hitLines}
    <div class="actions">
      <button type="button" class="ghost btn-abandon-trial" ${lock}>Abandon trial</button>
      <button type="button" class="danger btn-abandon-open" ${lock}>Abandon open job</button>
    </div>
  </div>`;
}

function renderKbWriteCard() {
  const msg = latestMessage("kb_write");
  const pending =
    (msg && msg.payload) ||
    ((state.sidebar && state.sidebar.design && state.sidebar.design.pending_kb_write) || null);
  if (!pending || typeof pending !== "object") return "";
  const lock = busy ? "disabled" : "";
  return `<div class="card" data-testid="kb-write-card"><h3>Write user-KB note</h3>
    <p>${escapeHtml((msg && msg.text) || "Confirm writing this note into user_kb/raw.")}</p>
    <p class="hint">${escapeHtml(pending.relpath || "")}</p>
    <pre class="kb-draft">${escapeHtml(pending.body || "")}</pre>
    <div class="actions"><button type="button" class="primary btn-kb-write" ${lock}>Confirm write</button></div>
  </div>`;
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
  const lock = busy ? "disabled" : "";
  return `<div class="card" data-testid="clarification-form"><h3>Clarification</h3>${prompt}${inputs}<div class="actions"><button type="button" class="primary" id="btn-clarify" ${lock}>Submit slots</button></div></div>`;
}

function renderDecisionActions(extra = "") {
  const lock = busy ? "disabled" : "";
  return `<div class="actions decision-actions">
      <button type="button" class="primary" id="btn-confirm" ${lock}>Confirm</button>
      <button type="button" id="btn-edit" ${lock}>Change params</button>
      <button type="button" class="danger" id="btn-cancel" ${lock}>Cancel</button>
      ${extra}
    </div>`;
}

function renderPlanCard() {
  const card = state.plan_card;
  const missing = (state.sidebar && state.sidebar.missing) || [];
  if (!card || !card.confirmable || mode === "ask" || missing.length) return "";
  const compact = isCompactPlan(card);
  const job = (state.sidebar && state.sidebar.active_intent && state.sidebar.active_intent.job) || "";
  const steps = (card.steps || [])
    .map((s) => {
      const risks = riskLines(s.side_effects)
        .map((line) => `<div class="risk">${escapeHtml(line)}</div>`)
        .join("");
      const badges = riskBadges(s.side_effects);
      const params = formatInputs(s.inputs);
      if (compact) {
        return `<li><strong>${escapeHtml(stepTitle(s))}</strong> ${badges}${params ? `<div class="skill-id">${escapeHtml(params)}</div>` : ""}</li>`;
      }
      return `<li><strong>${escapeHtml(stepTitle(s))}</strong> ${badges}<div class="skill-id">${escapeHtml(skillLabel(s.skill_name))}</div>${params ? `<div class="skill-id">${escapeHtml(params)}</div>` : ""}${risks}</li>`;
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
  const heading = compact ? "Ready to run" : "Review plan";
  const jobLine = job ? `<p class="job-line">Job: ${escapeHtml(job)}</p>` : "";
  return `<div class="card ${compact ? "compact" : ""}" data-testid="plan-card"><h3>${heading}</h3>
    ${jobLine}
    <p class="warn">Plan ${escapeHtml(card.plan_id)}</p>
    <ol>${steps}</ol>
    ${editor}
    ${renderDecisionActions()}</div>`;
}

function renderSteps() {
  const steps = (state.execution && state.execution.steps) || [];
  if (!steps.length) return "";
  const failed = steps.some((s) => s.status === "error");
  const retry = failed
    ? `<div class="actions"><button type="button" class="primary btn-retry" id="btn-retry">Retry failed step</button></div>`
    : "";
  return `<ol class="step-list" data-testid="step-list">${steps
    .map((s) => {
      const st = s.status || "pending";
      const mark = st === "done" ? "✓" : st === "error" ? "✕" : st === "running" ? "…" : "•";
      return `<li class="step ${escapeHtml(st)}">${mark} ${escapeHtml(stepTitle(s) || skillLabel(s.skill_name || s.step_id))} <small>${escapeHtml(st)}</small></li>`;
    })
    .join("")}</ol>${retry}`;
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

function exportLink(art, label) {
  if (!art || !art.export_path || !art.run_id) return "";
  const href = `/v1/artifacts/${encodeURIComponent(art.run_id)}?path=${encodeURIComponent(art.export_path)}`;
  return `<a class="export-link" href="${href}">${escapeHtml(label || "Export")}</a>`;
}

function artifactToolbar(art) {
  const bits = [`<span class="art-type">${escapeHtml(art.type)}</span>`];
  if (art.run_id) bits.push(`<span class="art-id">run ${escapeHtml(art.run_id)}</span>`);
  const exp = exportLink(art, art.type === "chart" ? "Download PNG" : art.type === "backtest_report" ? "trade_log" : "Export");
  if (exp) bits.push(exp);
  return `<div class="artifact-toolbar">${bits.join("")}</div>`;
}

function renderArtifacts() {
  const host = $("artifact-panel");
  if (!host) return;
  const editor = $("code-editor");
  if (editor) codeCache._draft = editor.value;
  const arts = state.artifacts || [];
  const fileCard = filePreview
    ? `<div class="card"><div class="artifact-toolbar"><span class="art-type">file</span>
        <button type="button" id="btn-file-back">Back to artifacts</button></div>
        <h3>${escapeHtml(filePreview.name)}</h3><p class="warn">${escapeHtml(filePreview.path)}</p>
        <textarea rows="16" readonly>${escapeHtml(filePreview.content)}</textarea></div>`
    : "";
  if (!arts.length) {
    host.innerHTML = fileCard || `<p class="empty-hint">No artifacts yet. Confirm a plan to see tables, charts, or code here.</p>`;
    return;
  }
  const tabs = arts
    .map(
      (a, i) =>
        `<div class="tab ${i === artifactTab ? "active" : ""}" data-tab="${i}">${escapeHtml(a.type)} <small>${escapeHtml(a.run_id)}</small></div>`
    )
    .join("");
  if (filePreview) {
    host.innerHTML = `<div class="tabs">${arts
      .map(
        (a, i) =>
          `<div class="tab ${i === artifactTab ? "active" : ""}" data-tab="${i}">${escapeHtml(a.type)} <small>${escapeHtml(a.run_id)}</small></div>`
      )
      .join("")}</div><div data-testid="artifact-panel">${fileCard}</div>`;
    return;
  }
  const current = arts[artifactTab] || arts[0];
  let body = artifactToolbar(current);
  if (current.type === "data_table") {
    const rows = (current.preview && current.preview.preview_rows) || [];
    const summary = (current.preview && current.preview.data_summary) || {};
    body += `${metricsCards(summary)}${tableFromRows(rows)}`;
  } else if (current.type === "chart") {
    if (current.warnings && current.warnings.length) body += `<p class="warn">${escapeHtml(current.warnings.join(" "))}</p>`;
    if (current.export_path) {
      const href = `/v1/artifacts/${encodeURIComponent(current.run_id)}?path=${encodeURIComponent(current.export_path)}`;
      body += `<img class="chart-img" alt="chart" src="${href}" />`;
    } else body += `<p class="warn">Chart file path is missing.</p>`;
  } else if (current.type === "strategy_code") {
    const path = (current.preview && current.preview.path) || current.export_path || "";
    const loaded = (current.preview && current.preview.source) || codeCache[path] || "";
    const draft = codeCache._draft != null ? codeCache._draft : loaded;
    body += `<textarea id="code-editor" rows="12">${escapeHtml(draft)}</textarea>
      <div class="actions"><button type="button" id="btn-code-run">Run (requires confirm)</button></div>
      ${
        pendingCodeRun
          ? `<div class="card" data-testid="plan-card"><h3>Confirm running edited strategy</h3>
              ${renderDecisionActions(`<button type="button" class="primary" id="btn-code-confirm">Confirm run</button>`)}</div>`
          : ""
      }`;
    if (path && !(current.preview && current.preview.source) && codeCache[path] == null) loadCode(path);
  } else if (current.type === "backtest_report") {
    const metrics = (current.preview && current.preview.metrics) || {};
    body += `${metricsCards(metrics)}`;
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

function slotTone(slot) {
  if (slot.confirmed) return "confirmed";
  if (slot.source === "default") return "default";
  return "unconfirmed";
}

function renderNow() {
  const host = $("workspace-now");
  if (!host) return;
  const bar = state.sidebar || {};
  const job = (bar.active_intent && bar.active_intent.job) || "—";
  const missing = bar.missing || [];
  const slots = bar.slots || [];
  const slotRows = slots
    .map((s) => {
      const tone = slotTone(s);
      const tag = tone === "confirmed" ? "confirmed" : tone === "default" ? "default" : "unconfirmed";
      if (editingNowSlot === s.name) {
        return `<li class="slot ${tag}"><label>${escapeHtml(slotLabel(s.name))}<input data-now-slot="${escapeHtml(s.name)}" value="${escapeHtml(s.value == null ? "" : String(s.value))}" /></label>
          <div class="actions"><button type="button" class="primary" id="btn-now-apply">Apply</button><button type="button" id="btn-now-cancel">Back</button></div></li>`;
      }
      const shown = s.value == null || s.value === "" ? "—" : String(s.value);
      return `<li class="slot ${tag}"><button type="button" class="slot-edit" data-now-edit="${escapeHtml(s.name)}">${escapeHtml(slotLabel(s.name))}: ${escapeHtml(shown)} <span class="slot-tag">${tag}</span></button></li>`;
    })
    .join("");
  const missingLine = missing.length
    ? `<p class="missing">Missing: ${escapeHtml(missing.map(slotLabel).join(", "))}</p>`
    : `<p class="ok-line">Slots complete</p>`;
  host.innerHTML = `<div class="now-job"><p class="now-k">Now</p><p class="now-v">Job: ${escapeHtml(job)}</p>
    <div class="pipeline">${pipelineHtml(job === "—" ? "" : job)}</div></div>
    ${missingLine}
    <div class="now-slots"><p class="now-k">Slots</p><ul>${slotRows || "<li>No slots yet. Click a slot name here to edit after a plan fills them.</li>"}</ul></div>
    <div class="now-env"><p class="now-k">Environment</p><p>${escapeHtml(envLine(bar.env_summary))}</p></div>
    <div class="now-provider" id="now-provider">${renderProviderBlock()}</div>
    <div class="now-audit"><p class="now-k">Audit</p>
      <p>Plan: ${escapeHtml(bar.current_plan_id || "—")}</p>
      <p>Run: ${escapeHtml(state.run_id || "—")}</p>
    </div>`;
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
  }<span class="chip ghost">Show Workspace</span>`;
}

function renderFileTree(nodes) {
  const currentRun = String(state.run_id || "");
  return `<ul class="file-tree">${(nodes || [])
    .map((node) => {
      if (node.kind === "dir") {
        return `<li><div class="dir-name">${escapeHtml(node.name)}</div>${renderFileTree(node.children)}</li>`;
      }
      const current = currentRun && String(node.name || "").includes(currentRun) ? "current-run" : "";
      return `<li><button type="button" class="file ${current}" data-file-path="${escapeHtml(node.path)}">${escapeHtml(node.name)}</button></li>`;
    })
    .join("")}</ul>`;
}

function renderProviderBlock() {
  const p = providerInfo || {};
  const model = p.model || "—";
  const modeLabel = p.mode || "rule";
  const key = p.api_key_present ? "key set" : "no key";
  if (editingNowSlot === "__provider__") {
    return `<p class="now-k">Provider</p>
      <label>Model <input id="prov-model" value="${escapeHtml(p.model || "")}" /></label>
      <label>Base URL <input id="prov-url" value="${escapeHtml(p.base_url || "")}" /></label>
      <label>API key <input id="prov-key" type="password" placeholder="${p.api_key_present ? "unchanged" : ""}" /></label>
      <div class="actions"><button type="button" class="primary" id="btn-prov-confirm">Confirm change</button>
      <button type="button" id="btn-prov-cancel">Cancel</button></div>`;
  }
  return `<p class="now-k">Provider</p><p>${escapeHtml(modeLabel)} · ${escapeHtml(model)} · ${escapeHtml(key)}</p>
    <p class="hint">${escapeHtml(p.base_url || "")}</p>
    <button type="button" class="ghost" id="btn-prov-edit">Change provider</button>`;
}

function renderWorkspace() {
  renderNow();
  renderG7Slot();
  const host = $("workspace-files");
  if (!host) return;
  const arts = workspace.artifacts || state.artifacts || [];
  if (!arts.length) {
    host.innerHTML = `<p class="files-k">Artifacts</p><p class="empty-hint">No artifacts in this session yet.</p>`;
    return;
  }
  host.innerHTML = `<p class="files-k">Artifacts</p><ul class="file-tree">${arts
    .map(
      (art, i) =>
        `<li><button type="button" class="file" data-art-index="${i}">${escapeHtml(art.type || "artifact")} · ${escapeHtml(art.title || art.run_id || "")}</button></li>`
    )
    .join("")}</ul>`;
}

function renderG7Slot() {
  const host = $("g7-slot");
  if (!host) return;
  const design = (state.sidebar && state.sidebar.design) || null;
  const queue = (state.sidebar && state.sidebar.trial_queue) || [];
  if (!design && !queue.length) {
    host.innerHTML = "";
    host.hidden = true;
    return;
  }
  host.hidden = false;
  const spec = (design && design.spec_draft) || {};
  const hits = (design && design.kb_hits) || [];
  const lock = busy ? "disabled" : "";
  const queueLines = queue.length
    ? `<ul class="trial-queue">${queue
        .map(
          (item) =>
            `<li data-status="${escapeHtml(item.status || "")}">${escapeHtml(item.job || "")} · ${escapeHtml(item.status || "")}${
              item.reason ? ` · ${escapeHtml(item.reason)}` : ""
            }</li>`
        )
        .join("")}</ul>`
    : `<p class="hint">No closed trial queued.</p>`;
  const pending = design && design.pending_kb_write;
  const writeBtn = pending
    ? `<button type="button" class="primary btn-kb-write" ${lock}>Confirm write</button>`
    : "";
  host.innerHTML = `<p class="files-k">Open loop</p>
    <p><strong>${escapeHtml((spec && spec.name) || "draft")}</strong> · ${escapeHtml((spec && spec.universe) || "")}</p>
    <p>${escapeHtml((spec && spec.hypothesis) || "")}</p>
    <p class="files-k">Trial queue</p>${queueLines}
    <p class="files-k">User KB</p>
    <p class="hint">${hits.length ? hits.map((h) => h.path || h.title).join(", ") : "No matched notes"}</p>
    <div class="actions">
      <button type="button" class="ghost btn-abandon-trial" ${lock}>Abandon trial</button>
      <button type="button" class="danger btn-abandon-open" ${lock}>Abandon open job</button>
      ${writeBtn}
    </div>`;
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

async function restoreCurrentSession() {
  const dto = await api(`/v1/session/${encodeURIComponent(sessionId)}`);
  if (dto && !dto.error) {
    ingestDto(dto);
    applySessionMode(dto);
    applyServerTranscript(dto);
  } else {
    transcript = [];
  }
  await refreshSessions();
  await refreshWorkspace();
  await refreshProvider();
  renderPanes();
}

restoreCurrentSession();
