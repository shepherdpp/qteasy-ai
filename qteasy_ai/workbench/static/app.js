const STORAGE_SESSION = "qteasy-ai.session_id";
const STORAGE_RAIL = "qteasy-ai.session-rail";
const STORAGE_WORKSPACE = "qteasy-ai.workspace";
const STORAGE_TRANSCRIPTS = "qteasy-ai.transcripts";
const STORAGE_COL_SESSION = "qteasy-ai.col-session";
const STORAGE_COL_ARTIFACT = "qteasy-ai.col-artifact";
const MIN_SESSION_COL = 260;
const MIN_ARTIFACT_COL = 280;

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
let openTabs = [];
let activeKey = "";
let pendingCodeRun = false;
let editingParams = false;
let editingNowSlot = "";
let busy = false;
let runAbort = null;
let runStartedAt = 0;
let runElapsedS = 0;
let elapsedTimer = null;
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
let renamingSessionId = "";
let livePoll = null;
let executeSseOpen = false;

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

function composerHint() {
  if (mode === "ask") return "Ask: handbook Q&A. Does not execute.";
  if (mode === "agent") return "Agent: same confirm gate; live never auto.";
  return "Plan: review the artifact. Confirm is optional; you can type freely.";
}

function latestNonUserMessage() {
  const rows = transcript.concat(state.messages || []);
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (rows[i] && rows[i].kind !== "user_text") return rows[i];
  }
  return null;
}

function liveClarifyMessage() {
  const last = latestNonUserMessage();
  if (last && (last.kind === "clarify" || last.kind === "clarification")) return last;
  return null;
}

function shouldShowLiveClarify() {
  const missing = (state.sidebar && state.sidebar.missing) || [];
  if (missing.length) return true;
  const last = liveClarifyMessage();
  if (!last) return false;
  const status = String((last.payload && last.payload.status) || "");
  return status !== "answered" && status !== "skipped";
}

function pendingDecision() {
  const missing = (state.sidebar && state.sidebar.missing) || [];
  return Boolean(missing.length || liveClarifyMessage());
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
      <button type="button" class="icon-btn ghost" id="btn-settings" title="Settings">⚙</button>
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
          <textarea id="query-input" placeholder="Ask in natural language · Ctrl/⌘+Enter to send" rows="3"></textarea>
          <div class="composer-row">
            <div class="mode-dropdown">
              <button type="button" class="mode-badge btn-mode-menu" data-testid="mode-badge" id="composer-mode" aria-haspopup="listbox" aria-expanded="false">Mode: PLAN ▾</button>
              <div class="mode-menu" id="mode-menu" hidden>
                <button type="button" data-mode="ask">Ask</button>
                <button type="button" data-mode="plan">Plan</button>
                <button type="button" data-mode="agent">Agent</button>
              </div>
            </div>
            <div class="provider-dropdown" id="composer-provider">
              <button type="button" class="mode-badge provider-badge" id="composer-provider-btn" aria-haspopup="listbox" aria-expanded="false">Not configured ▾</button>
              <div class="mode-menu provider-menu" id="provider-menu" hidden>
                <button type="button" class="active" id="provider-current" disabled>Not configured</button>
                <button type="button" id="btn-open-settings">Open settings</button>
              </div>
            </div>
            <span class="composer-row-spacer"></span>
            <button type="button" class="primary" id="btn-send">Send</button>
          </div>
        </div>
      </section>
      <div class="col-splitter" id="col-splitter" role="separator" aria-orientation="vertical" title="Resize columns"></div>
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
        </div>
      </aside>
    </div>
    <div class="statusbar" id="statusbar">
      <span id="status-provider">Provider —</span>
      <span class="status-sep">·</span>
      <span id="status-env">Environment —</span>
    </div>`;
  bindShell();
  shellReady = true;
  applyLayoutFlags();
  renderProviderBadge();
  renderStatusbar();
}

function closeModeMenu() {
  ["mode-menu", "edit-mode-menu"].forEach((id) => {
    const menu = $(id);
    if (menu) menu.hidden = true;
  });
  ["composer-mode", "edit-mode"].forEach((id) => {
    const badge = $(id);
    if (badge) badge.setAttribute("aria-expanded", "false");
  });
}

function toggleNamedMenu(menuId, badgeId) {
  if (busy) return;
  const menu = $(menuId);
  const badge = $(badgeId);
  if (!menu) return;
  const nextHidden = !menu.hidden;
  closeModeMenu();
  closeProviderMenu();
  menu.hidden = nextHidden;
  if (badge) badge.setAttribute("aria-expanded", nextHidden ? "false" : "true");
}

function toggleModeMenu() {
  toggleNamedMenu("mode-menu", "composer-mode");
}

function toggleEditModeMenu() {
  toggleNamedMenu("edit-mode-menu", "edit-mode");
}

function closeProviderMenu() {
  const menu = $("provider-menu");
  const badge = $("composer-provider-btn");
  if (menu) menu.hidden = true;
  if (badge) badge.setAttribute("aria-expanded", "false");
}

function toggleProviderMenu() {
  if (busy) return;
  const menu = $("provider-menu");
  const badge = $("composer-provider-btn");
  if (!menu) return;
  const nextHidden = !menu.hidden;
  closeModeMenu();
  menu.hidden = nextHidden;
  if (badge) badge.setAttribute("aria-expanded", nextHidden ? "false" : "true");
}

function providerLabel() {
  const p = providerInfo || {};
  const model = String(p.model || "").trim();
  if (!model) return "Not configured";
  return `${p.mode || "rule"} · ${model}`;
}

function renderProviderBadge() {
  const label = providerLabel();
  const btn = $("composer-provider-btn");
  if (btn) btn.textContent = `${label} ▾`;
  const current = $("provider-current");
  if (current) current.textContent = label;
}

function renderStatusbar() {
  const providerEl = $("status-provider");
  const envEl = $("status-env");
  if (!providerEl || !envEl) return;
  const p = providerInfo || {};
  const modeLabel = p.mode || "—";
  const model = String(p.model || "").trim() || "—";
  providerEl.textContent = `Provider ${modeLabel} · ${model}`;
  const env = envLine((state.sidebar && state.sidebar.env_summary) || {});
  envEl.textContent = env === "No env_facts yet." ? "Environment —" : `Environment ${env}`;
}

function openSettingsTab() {
  closeProviderMenu();
  closeModeMenu();
  openArtifactTab({ type: "settings", run_id: "local" });
}

function bindShell() {
  const modeBadge = $("composer-mode");
  if (modeBadge) {
    modeBadge.onclick = (ev) => {
      ev.stopPropagation();
      toggleModeMenu();
    };
  }
  document.querySelectorAll("#mode-menu button[data-mode]").forEach((btn) => {
    btn.onclick = () => setMode(btn.getAttribute("data-mode"));
  });
  const providerBtn = $("composer-provider-btn");
  if (providerBtn) {
    providerBtn.onclick = (ev) => {
      ev.stopPropagation();
      toggleProviderMenu();
    };
  }
  const openSettings = $("btn-open-settings");
  if (openSettings) openSettings.onclick = () => openSettingsTab();
  const settingsBtn = $("btn-settings");
  if (settingsBtn) settingsBtn.onclick = () => openSettingsTab();
  document.addEventListener("click", (ev) => {
    const dropdown = ev.target && ev.target.closest && ev.target.closest(".mode-dropdown");
    if (!dropdown) closeModeMenu();
    const provider = ev.target && ev.target.closest && ev.target.closest(".provider-dropdown");
    if (!provider) closeProviderMenu();
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
  $("session-list").addEventListener("dblclick", onSessionListDblClick);
  $("workspace-files").addEventListener("click", onWorkspaceArtifactClick);
  $("workspace-now").addEventListener("click", onNowClick);
  bindColumnSplitter();
  window.addEventListener("resize", applyColumnWidths);
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
  applyColumnWidths();
}

function applyColumnWidths() {
  const layout = $("layout");
  if (!layout) return;
  const rail = railCollapsed ? 44 : 200;
  const ws = workspaceCollapsed ? 44 : 280;
  const splitter = 4;
  let sessionW = Number(localStorage.getItem(STORAGE_COL_SESSION) || 0);
  let artW = Number(localStorage.getItem(STORAGE_COL_ARTIFACT) || 0);
  if (sessionW < MIN_SESSION_COL || artW < MIN_ARTIFACT_COL) {
    layout.style.gridTemplateColumns = `${rail}px minmax(${MIN_SESSION_COL}px, 1.1fr) ${splitter}px minmax(${MIN_ARTIFACT_COL}px, 1.4fr) ${ws}px`;
    return;
  }
  const avail = layout.clientWidth - rail - ws - splitter;
  if (avail > 0 && avail < MIN_SESSION_COL + MIN_ARTIFACT_COL) {
    layout.style.gridTemplateColumns = `${rail}px ${MIN_SESSION_COL}px ${splitter}px ${MIN_ARTIFACT_COL}px ${ws}px`;
    return;
  }
  if (avail > 0 && sessionW + artW > avail) {
    let extra = sessionW + artW - avail;
    const takeS = Math.min(Math.max(sessionW - MIN_SESSION_COL, 0), extra);
    sessionW -= takeS;
    extra -= takeS;
    artW = Math.max(MIN_ARTIFACT_COL, artW - extra);
    sessionW = Math.max(MIN_SESSION_COL, sessionW);
  }
  layout.style.gridTemplateColumns = `${rail}px ${sessionW}px ${splitter}px ${artW}px ${ws}px`;
}

function bindColumnSplitter() {
  const split = $("col-splitter");
  if (!split) return;
  let dragging = false;
  let startX = 0;
  let startSession = 0;
  let startArt = 0;
  split.addEventListener("mousedown", (ev) => {
    ev.preventDefault();
    const sessionCol = $("chat-col");
    const artCol = $("artifact-col");
    if (!sessionCol || !artCol) return;
    dragging = true;
    startX = ev.clientX;
    startSession = sessionCol.getBoundingClientRect().width;
    startArt = artCol.getBoundingClientRect().width;
    split.classList.add("dragging");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });
  window.addEventListener("mousemove", (ev) => {
    if (!dragging) return;
    const dx = ev.clientX - startX;
    let nextS = startSession + dx;
    let nextA = startArt - dx;
    if (nextS < MIN_SESSION_COL) {
      nextA -= MIN_SESSION_COL - nextS;
      nextS = MIN_SESSION_COL;
    }
    if (nextA < MIN_ARTIFACT_COL) {
      nextS -= MIN_ARTIFACT_COL - nextA;
      nextA = MIN_ARTIFACT_COL;
    }
    if (nextS < MIN_SESSION_COL || nextA < MIN_ARTIFACT_COL) return;
    localStorage.setItem(STORAGE_COL_SESSION, String(Math.round(nextS)));
    localStorage.setItem(STORAGE_COL_ARTIFACT, String(Math.round(nextA)));
    applyColumnWidths();
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    split.classList.remove("dragging");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  });
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
  closeModeMenu();
  renderMode();
  renderChat();
}

function renderMode() {
  const label = `Mode: ${mode.toUpperCase()} ▾`;
  document.querySelectorAll("[data-testid='mode-badge'], #composer-mode, #edit-mode").forEach((el) => {
    el.textContent = label;
  });
  document.querySelectorAll("#mode-menu button[data-mode], #edit-mode-menu button[data-mode]").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-mode") === mode);
    btn.disabled = busy;
  });
  ["composer-mode", "edit-mode", "composer-provider-btn"].forEach((id) => {
    const badge = $(id);
    if (badge) badge.disabled = busy;
  });
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

function formatElapsed(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

function runningSkillName() {
  const steps = (state.execution && state.execution.steps) || [];
  const live = [...steps].reverse().find((row) => row && (row.status === "running" || row.status === "pending"));
  const name = (live && live.skill_name) || "";
  return SKILL_TITLES[name] || name;
}

function updateBusyElapsedDom() {
  const label = $("busy-elapsed");
  if (label) label.textContent = `Working · ${formatElapsed(runElapsedS)}`;
  const now = $("now-run-status");
  if (now) now.textContent = `Running · ${formatElapsed(runElapsedS)}`;
}

function startElapsedClock() {
  if (elapsedTimer) return;
  elapsedTimer = setInterval(() => {
    if (!runStartedAt) return;
    runElapsedS = Math.floor((Date.now() - runStartedAt) / 1000);
    updateBusyElapsedDom();
  }, 1000);
}

function stopElapsedClock() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

function isAbortError(exc) {
  return Boolean(exc && (exc.name === "AbortError" || /aborted/i.test(String(exc.message || ""))));
}

function dropRunWatch() {
  const controller = runAbort;
  runAbort = null;
  if (controller) controller.abort();
  stopLivePoll();
  if (busy) setBusy(false);
  else {
    stopElapsedClock();
    runStartedAt = 0;
    runElapsedS = 0;
  }
}

function isDtoRunning(dto) {
  return String((dto && dto.execution && dto.execution.status) || "") === "running";
}

function applyRunningWatch(dto) {
  if (!isDtoRunning(dto)) {
    stopLivePoll();
    if (busy && !executeSseOpen) setBusy(false);
    return;
  }
  if (!busy) setBusy(true);
  if (!executeSseOpen) startLivePoll();
}

function startLivePoll() {
  if (livePoll) return;
  livePoll = setInterval(async () => {
    if (executeSseOpen || !sessionId) return;
    const dto = await api(`/v1/session/${encodeURIComponent(sessionId)}`);
    if (isDtoRunning(dto)) {
      if (dto.execution) state.execution = Object.assign({}, state.execution || {}, dto.execution);
      if (dto.plan_card) state.plan_card = Object.assign({}, state.plan_card || {}, dto.plan_card, { confirmable: false });
      renderNow();
      return;
    }
    stopLivePoll();
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    setBusy(false);
    renderPanes();
    await refreshWorkspace();
    await refreshSessions();
  }, 2000);
}

function stopLivePoll() {
  if (livePoll) {
    clearInterval(livePoll);
    livePoll = null;
  }
}

function stopWatchingRun() {
  if (!busy && !runAbort) return;
  dropRunWatch();
  transcript.push({
    kind: "mode_notice",
    text: "Stopped watching this run. The server may still finish; if status looks stuck, refresh the session or start a new topic.",
  });
  persistTranscript();
  renderChat();
}

function setBusy(next) {
  busy = next;
  if (busy) {
    if (!runAbort) runAbort = new AbortController();
    if (!runStartedAt) runStartedAt = Date.now();
    startElapsedClock();
  } else {
    stopElapsedClock();
    runStartedAt = 0;
    runElapsedS = 0;
    runAbort = null;
  }
  const input = $("query-input");
  const send = $("btn-send");
  if (input) input.disabled = busy;
  if (send) send.disabled = busy;
  document.querySelectorAll("#mode-menu button[data-mode]").forEach((btn) => {
    btn.disabled = busy;
  });
  ["composer-mode", "edit-mode", "composer-provider-btn"].forEach((id) => {
    const badge = $(id);
    if (badge) badge.disabled = busy;
  });
  ["btn-confirm", "btn-cancel", "btn-edit", "btn-clarify", "btn-clarify-skip", "btn-retry"].forEach((id) => {
    const el = $(id);
    if (el) el.disabled = busy;
  });
  document.querySelectorAll(".clarify-chip").forEach((el) => {
    el.disabled = busy;
  });
  renderChat();
  renderNow();
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
    return consumeSse(res, options && options.signal);
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

async function consumeSse(res, signal) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let finalDto = null;
  let sseError = null;
  while (true) {
    if (signal && signal.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }
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
      else if (ev === "heartbeat") {
        if (payload.elapsed_s != null) runElapsedS = Number(payload.elapsed_s) || runElapsedS;
        updateBusyElapsedDom();
      }
      else if (ev === "state") finalDto = payload;
      else if (ev === "error") sseError = payload;
    }
  }
  if (signal && signal.aborted) {
    throw new DOMException("Aborted", "AbortError");
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
  if (mode === "agent") executeSseOpen = true;
  try {
    const body = JSON.stringify({ query: text, session_id: sessionId });
    const path = mode === "ask" ? "/v1/ask" : mode === "agent" ? "/v1/run?stream=1" : "/v1/plan";
    const headers = { "Content-Type": "application/json" };
    if (mode === "agent") headers.Accept = "text/event-stream";
    const dto = await api(path, { method: "POST", headers, body, signal: runAbort ? runAbort.signal : undefined });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    pendingCodeRun = false;
    filePreview = null;
    renderPanes();
    await refreshSessions();
    await refreshWorkspace();
  } catch (exc) {
    if (!isAbortError(exc)) {
      transcript.push({
        kind: "error",
        text: "Network error. Check that the workbench server is running.",
        payload: { next_action: "Retry when the server is reachable. You do not need to start over." },
      });
      persistTranscript();
      renderChat();
    }
  } finally {
    executeSseOpen = false;
    setBusy(false);
  }
}

async function sendControlPatches(patches) {
  if (busy) return;
  setBusy(true);
  try {
    const dto = await api("/v1/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, patches }),
    });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    renderPanes();
    return dto;
  } finally {
    setBusy(false);
  }
}

async function sendControlSkip() {
  if (busy) return;
  setBusy(true);
  try {
    const dto = await api("/v1/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, skip: true }),
    });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    renderPanes();
    return dto;
  } finally {
    setBusy(false);
  }
}

async function confirmPlan() {
  const planId = state.plan_card && state.plan_card.plan_id;
  if (!planId || (state.plan_card && state.plan_card.confirmable === false) || busy) return;
  setBusy(true);
  executeSseOpen = true;
  try {
    const dto = await api("/v1/run-plan?stream=1", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ plan_id: planId, session_id: sessionId }),
      signal: runAbort ? runAbort.signal : undefined,
    });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    pendingCodeRun = false;
    closePlanTabsForRun(state.run_id);
    renderPanes();
    await refreshWorkspace();
  } catch (exc) {
    if (!isAbortError(exc)) {
      transcript.push({
        kind: "error",
        text: "Network error. Confirm did not complete. Retry when the server is reachable.",
        payload: { next_action: "Press Retry. You do not need to start over." },
      });
      persistTranscript();
      renderChat();
    }
  } finally {
    executeSseOpen = false;
    setBusy(false);
  }
}

async function cancelPlan() {
  if (busy) return;
  transcript.push({
    kind: "mode_notice",
    text: "Plan card dismissed. Type freely; Confirm remains optional.",
  });
  persistTranscript();
  state = Object.assign({}, state, { plan_card: { ...(state.plan_card || {}), confirmable: false } });
  renderChat();
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
  if (t.id === "btn-stop-watch") stopWatchingRun();
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
  if (t.id === "btn-clarify-skip") {
    sendControlSkip();
    return;
  }
  if (t.dataset.clarifyOption != null) {
    const missing = (state.sidebar && state.sidebar.missing) || [];
    const key = missing[0] || "strategy_id";
    sendControlPatches({ [key]: t.dataset.clarifyOption });
    return;
  }
  if (t.classList.contains("btn-retry") || t.id === "btn-retry") retryLast();
  if (t.id === "edit-mode") {
    ev.stopPropagation();
    toggleEditModeMenu();
    return;
  }
  if (t.closest("#edit-mode-menu") && t.dataset.mode) {
    setMode(t.dataset.mode);
    return;
  }
  const editUser = t.closest("[data-edit-user]");
  if (editUser) {
    editingUserIndex = Number(editUser.getAttribute("data-edit-user"));
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
    if (t.dataset.openPlan != null) {
    openPlanFromRunId(t.dataset.openPlan);
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
  const patches = {};
  Array.from(document.querySelectorAll("#chat-log input[data-slot]")).forEach((el) => {
    const name = el.getAttribute("data-slot");
    const value = String(el.value || "").trim();
    if (!name || !value) return;
    patches[name] = value;
  });
  if (!Object.keys(patches).length) return;
  sendControlPatches(patches);
}

async function submitParamEdits() {
  const patches = {};
  Array.from(document.querySelectorAll("#chat-log input[data-edit-slot], #workspace-now input[data-now-slot]")).forEach((el) => {
    const name = el.getAttribute("data-edit-slot") || el.getAttribute("data-now-slot");
    const value = String(el.value || "").trim();
    if (!name || !value) return;
    patches[name] = value;
  });
  editingParams = false;
  editingNowSlot = "";
  if (!Object.keys(patches).length) {
    renderChat();
    renderNow();
    return;
  }
  if (busy) return;
  dismissModeNotice();
  setBusy(true);
  try {
    const dto = await api("/v1/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, patches }),
    });
    ingestDto(dto, { appendUser: false });
    applyServerTranscript(dto);
    pendingCodeRun = false;
    filePreview = null;
    renderPanes();
    await refreshSessions();
    await refreshWorkspace();
  } catch (exc) {
    transcript.push({
      kind: "error",
      text: "Network error. Parameter update did not complete. Retry when the server is reachable.",
      payload: { next_action: "Press Apply again. You do not need to start over." },
    });
    persistTranscript();
    renderChat();
  } finally {
    setBusy(false);
  }
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
  renderProviderBadge();
  renderStatusbar();
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
  const closer = t.closest("[data-tab-close]");
  if (closer) {
    ev.stopPropagation();
    closeArtifactTab(closer.getAttribute("data-tab-close"));
    return;
  }
  const tabEl = t.closest("[data-tab]");
  if (tabEl) {
    const editor = $("code-editor");
    if (editor) codeCache._draft = editor.value;
    activeKey = String(tabEl.getAttribute("data-tab") || "");
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

function sessionDisplayName(row) {
  return String((row && (row.name || row.title)) || (row && row.session_id) || "").trim();
}

function onSessionListDblClick(ev) {
  const item = ev.target.closest("[data-session-id]");
  if (!item || ev.target.closest("[data-session-delete], [data-session-rename], .session-rename")) return;
  beginRenameSession(item.getAttribute("data-session-id"));
}

function onSessionListClick(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLElement)) return;
  const item = t.closest("[data-session-id]");
  if (!item) return;
  const id = item.getAttribute("data-session-id");
  if (t.closest("[data-session-delete]")) {
    ev.stopPropagation();
    deleteSession(id);
    return;
  }
  if (t.closest("[data-session-rename]")) {
    ev.stopPropagation();
    beginRenameSession(id);
    return;
  }
  if (t.closest(".session-rename")) {
    ev.stopPropagation();
    return;
  }
  switchSession(id);
}

function beginRenameSession(id) {
  if (!id || busy) return;
  renamingSessionId = id;
  renderSessionList();
  const box = document.querySelector(".session-rename");
  if (box) {
    box.focus();
    box.select();
  }
}

async function commitRenameSession(id, raw) {
  const name = String(raw || "").trim();
  renamingSessionId = "";
  const local = sessions.find((row) => row.session_id === id);
  const persisted = Boolean(local && !local.local_only);
  if (!persisted) {
    if (local) {
      local.name = name || "New session";
      local.title = local.name;
    }
    renderSessionList();
    return;
  }
  const dto = await api(`/v1/session/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (dto && dto.error) {
    renderSessionList();
    return;
  }
  await refreshSessions();
}

async function deleteSession(id) {
  if (!id || busy) return;
  const row = sessions.find((item) => item.session_id === id);
  const label = sessionDisplayName(row) || id;
  if (!window.confirm(`Delete session "${label}"? This cannot be undone.`)) return;
  if (row && row.local_only) {
    if (id === sessionId) createSession();
    else {
      sessions = sessions.filter((item) => item.session_id !== id);
      renderSessionList();
    }
    return;
  }
  const dto = await api(`/v1/session/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (dto && dto.error) return;
  if (id === sessionId) {
    await createSession();
    return;
  }
  await refreshSessions();
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

function catalogArtifacts() {
  return workspace.artifacts || state.artifacts || [];
}

function artifactKey(art) {
  if (!art) return "";
  return `${String(art.type || "")}::${String(art.run_id || "")}`;
}

function openArtifactTab(art) {
  if (!art || !art.type || !art.run_id) return;
  const key = artifactKey(art);
  if (!openTabs.some((row) => artifactKey(row) === key)) {
    openTabs = openTabs.concat([{ type: art.type, run_id: art.run_id }]);
  }
  activeKey = key;
  filePreview = null;
  renderArtifacts();
}

function closeArtifactTab(key) {
  const idx = openTabs.findIndex((row) => artifactKey(row) === key);
  if (idx < 0) return;
  openTabs = openTabs.filter((row) => artifactKey(row) !== key);
  if (activeKey === key) {
    const neighbor = openTabs[idx] || openTabs[idx - 1] || null;
    activeKey = neighbor ? artifactKey(neighbor) : "";
  }
  renderArtifacts();
}

function closePlanTabsForRun(runId) {
  const rid = String(runId || "");
  if (!rid) return;
  const next = openTabs.filter((row) => !(row.type === "plan" && String(row.run_id) === rid));
  if (next.length === openTabs.length) return;
  const lost = activeKey === `plan::${rid}`;
  openTabs = next;
  if (lost) {
    const last = openTabs[openTabs.length - 1];
    activeKey = last ? artifactKey(last) : "";
  }
}

function clearOpenTabs() {
  openTabs = [];
  activeKey = "";
}

function pruneMissingTabs() {
  const catalog = catalogArtifacts();
  openTabs = openTabs.filter(
    (tab) => tab.type === "settings" || catalog.some((row) => artifactKey(row) === artifactKey(tab))
  );
  if (activeKey && !openTabs.some((row) => artifactKey(row) === activeKey)) {
    const last = openTabs[openTabs.length - 1];
    activeKey = last ? artifactKey(last) : "";
  }
}

function openPlanFromRunId(runId) {
  const rid = String(runId || "").trim();
  const art = catalogArtifacts().find((row) => row.type === "plan" && String(row.run_id) === rid);
  if (!art) {
    modeNotice = "Plan artifact is not in Workspace yet. Open it from the right-hand index.";
    renderMode();
    return;
  }
  openArtifactTab(art);
}

function currentPlanRunId() {
  const ready = latestMessage("plan_ready");
  const fromCard = ready && ready.payload && ready.payload.run_id;
  if (fromCard) return String(fromCard);
  const art = catalogArtifacts().find((row) => row.type === "plan");
  return art ? String(art.run_id || "") : "";
}

async function onWorkspaceArtifactClick(ev) {
  const btn = ev.target.closest("[data-art-index]");
  if (!btn) return;
  const idx = Number(btn.getAttribute("data-art-index") || 0);
  const listed = workspace.artifacts || state.artifacts || [];
  if (listed.length) state.artifacts = listed;
  const art = listed[idx];
  if (art) openArtifactTab(art);
}

async function createSession() {
  stopLivePoll();
  dropRunWatch();
  persistTranscript();
  sessionId = newSessionId();
  localStorage.setItem(STORAGE_SESSION, sessionId);
  state = emptyState();
  transcript = [];
  persistTranscript();
  clearOpenTabs();
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
  if (!id || id === sessionId) return;
  persistTranscript();
  dropRunWatch();
  sessionId = id;
  localStorage.setItem(STORAGE_SESSION, sessionId);
  transcript = [];
  const dto = await api(`/v1/session/${encodeURIComponent(id)}`);
  ingestDto(dto);
  applySessionMode(dto);
  applyServerTranscript(dto);
  clearOpenTabs();
  filePreview = null;
  editingNowSlot = "";
  editingUserIndex = -1;
  pendingRewind = null;
  await refreshWorkspace();
  await refreshProvider();
  renderPanes();
  applyRunningWatch(dto);
  focusComposer();
}

async function refreshSessions() {
  const data = await api("/v1/sessions");
  sessions = data.sessions || [];
  if (sessionId && !sessions.some((row) => row.session_id === sessionId)) {
    sessions = [
      { session_id: sessionId, name: "New session", title: "New session", last_user: "", job: "", local_only: true },
      ...sessions,
    ];
  }
  renderSessionList();
}

async function refreshWorkspace() {
  const data = await api(`/v1/workspace?session_id=${encodeURIComponent(sessionId)}`);
  workspace = data && Array.isArray(data.artifacts) ? data : { artifacts: [] };
  state.artifacts = workspace.artifacts || [];
  for (const tab of openTabs.filter((row) => row.type === "plan")) {
    if (!catalogArtifacts().some((row) => row.type === "plan" && String(row.run_id) === String(tab.run_id))) {
      closePlanTabsForRun(tab.run_id);
    }
  }
  pruneMissingTabs();
  renderWorkspace();
  renderArtifacts();
}

async function refreshProvider() {
  const data = await api("/v1/provider");
  if (data && !data.error) providerInfo = data;
  renderNow();
  renderProviderBadge();
  renderStatusbar();
}

function renderSessionList() {
  const host = $("session-list");
  if (!host) return;
  host.innerHTML = sessions
    .map((row) => {
      const active = row.session_id === sessionId ? "active" : "";
      const name = sessionDisplayName(row);
      const last = String(row.last_user || "").trim();
      const editing = renamingSessionId === row.session_id;
      const nameBlock = editing
        ? `<input class="session-rename" value="${escapeHtml(name)}" aria-label="Rename session" />`
        : `<span class="sid">${escapeHtml(name)}</span>`;
      const meta = last && last !== name ? `<span class="meta">${escapeHtml(last)}</span>` : "";
      const runTag = row.running ? `<span class="meta running-tag">Running</span>` : "";
      return `<div class="session-item ${active}" data-session-id="${escapeHtml(row.session_id)}">
        <div class="session-main">${nameBlock}${meta}${runTag}</div>
        <div class="session-actions">
          <button type="button" class="icon-btn ghost" data-session-rename title="Rename">✎</button>
          <button type="button" class="icon-btn ghost" data-session-delete title="Delete">🗑</button>
        </div>
      </div>`;
    })
    .join("");
  const current = sessions.find((row) => row.session_id === sessionId);
  $("session-title").textContent = sessionDisplayName(current) || sessionId;
  const box = host.querySelector(".session-rename");
  if (box) {
    box.addEventListener("click", (ev) => ev.stopPropagation());
    box.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        commitRenameSession(renamingSessionId, box.value);
      }
      if (ev.key === "Escape") {
        renamingSessionId = "";
        renderSessionList();
      }
    });
    box.addEventListener("blur", () => {
      if (renamingSessionId) commitRenameSession(renamingSessionId, box.value);
    });
  }
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
    if (msg.kind === "plan_card" || msg.kind === "step_status" || msg.kind === "design_card" || msg.kind === "kb_write") continue;
    if (msg.kind === "clarification" || msg.kind === "clarify") {
      let lastClarifyIdx = -1;
      for (let j = transcript.length - 1; j >= 0; j -= 1) {
        const row = transcript[j];
        if (row && (row.kind === "clarify" || row.kind === "clarification")) {
          lastClarifyIdx = j;
          break;
        }
      }
      if (shouldShowLiveClarify() && i === lastClarifyIdx) continue;
      const answer = msg.payload && msg.payload.answer ? String(msg.payload.answer) : "";
      const answered = answer ? `<div class="answered">Answered: ${escapeHtml(answer)}</div>` : "";
      parts.push(
        `<div class="msg" data-testid="clarify-history"><div class="msg-role">Clarify</div><div class="bubble">${escapeHtml(msg.text || "")}${answered}</div></div>`
      );
      continue;
    }
    if (
      (msg.kind === "ask_text" || msg.kind === "ask") &&
      String(msg.text || "").startsWith("Plan ready:") &&
      state.plan_card &&
      state.plan_card.confirmable &&
      mode !== "ask"
    ) {
      continue;
    }
    if (msg.kind === "mode_notice") {
      parts.push(`<div class="msg"><div class="msg-role">Notice</div><div class="bubble warn">${escapeHtml(msg.text || "")}</div></div>`);
      continue;
    }
    if (msg.kind === "executing") {
      parts.push(`<div class="msg"><div class="msg-role">Running</div><div class="bubble">${escapeHtml(msg.text || "Running steps.")}</div></div>`);
      continue;
    }
    if (msg.kind === "result") {
      parts.push(`<div class="msg"><div class="msg-role">Result</div><div class="bubble">${escapeHtml(msg.text || "")}</div></div>`);
      continue;
    }
    if (msg.kind === "plan_ready") {
      const rid = (msg.payload && msg.payload.run_id) || "";
      const openBtn = rid
        ? `<div class="actions"><button type="button" class="ghost" data-open-plan="${escapeHtml(rid)}">Open plan</button></div>`
        : "";
      parts.push(`<div class="msg"><div class="msg-role">Plan</div><div class="bubble">${escapeHtml(msg.text || "")}${openBtn}</div></div>`);
      continue;
    }
    if (msg.kind === "user_text") {
      if (editingUserIndex === i) {
        const warn = pendingRewind
          ? `<p class="warn">Later executed runs will be discarded: ${(pendingRewind.executed || []).join(", ") || "yes"}. Confirm to continue.</p>`
          : "";
        const sendId = pendingRewind ? "btn-rewind-discard" : "btn-rewind-submit";
        parts.push(`<div class="msg user editing">
          ${warn}
          <div class="composer edit-composer">
            <textarea id="rewind-text" rows="3" placeholder="Ask in natural language · Ctrl/⌘+Enter to send">${escapeHtml((pendingRewind && pendingRewind.query) || msg.text || "")}</textarea>
            <div class="composer-row">
              <div class="mode-dropdown">
                <button type="button" class="mode-badge btn-mode-menu" data-testid="mode-badge" id="edit-mode" aria-haspopup="listbox" aria-expanded="false">Mode: ${mode.toUpperCase()} ▾</button>
                <div class="mode-menu" id="edit-mode-menu" hidden>
                  <button type="button" data-mode="ask">Ask</button>
                  <button type="button" data-mode="plan">Plan</button>
                  <button type="button" data-mode="agent">Agent</button>
                </div>
              </div>
              <span class="composer-row-spacer"></span>
              <button type="button" class="ghost" id="btn-rewind-cancel">Cancel</button>
              <button type="button" class="primary" id="${sendId}">Send</button>
            </div>
          </div>
        </div>`);
      } else {
        parts.push(`<div class="msg user"><div class="msg-role">You <span class="msg-actions"><button type="button" class="icon-btn ghost" data-edit-user="${i}" title="Edit">✎</button></span></div><div class="bubble">${escapeHtml(msg.text)}</div></div>`);
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
    const skill = runningSkillName();
    const skillLine = skill ? `<div class="busy-skill">${escapeHtml(skill)}</div>` : "";
    parts.push(`<div class="msg" id="busy-msg"><div class="msg-role">Assistant</div><div class="bubble busy-bubble"><span class="busy-dot" id="busy-elapsed">Working · ${formatElapsed(runElapsedS)}</span>${skillLine}<div class="progress-indet" aria-hidden="true"><div class="progress-indet-bar"></div></div><div class="actions"><button type="button" class="ghost" id="btn-stop-watch">Stop</button></div></div></div>`);
  }
  parts.push(renderClarification());
  parts.push(renderPlanCard());
  parts.push(renderSteps());
  host.innerHTML = parts.join("");
  const rewind = $("rewind-text");
  if (rewind) {
    rewind.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      if (ev.isComposing || ev.keyCode === 229) return;
      if (ev.ctrlKey || ev.metaKey) {
        ev.preventDefault();
        rewindUserMessage(editingUserIndex, rewind.value, Boolean(pendingRewind));
      }
    });
    rewind.focus();
    rewind.setSelectionRange(rewind.value.length, rewind.value.length);
  }
  renderMode();
  if (stick || busy) host.scrollTop = host.scrollHeight;
}

function latestMessage(kind) {
  const rows = transcript.concat(state.messages || []);
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (rows[i] && rows[i].kind === kind) return rows[i];
  }
  return null;
}

function latestClarify() {
  const rows = transcript.concat(state.messages || []);
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const kind = rows[i] && rows[i].kind;
    if (kind === "clarify" || kind === "clarification") return rows[i];
  }
  return null;
}

function renderClarifyOptions(clar, lock) {
  const raw = (clar && clar.payload && clar.payload.options) || [];
  const chips = raw
    .map((item) => {
      if (!item || typeof item !== "object") return "";
      const id = String(item.id || item.label || "").trim();
      const label = String(item.label || item.id || "").trim();
      if (!id) return "";
      return `<button type="button" class="chip clarify-chip" data-clarify-option="${escapeHtml(id)}" ${lock}>${escapeHtml(label)}</button>`;
    })
    .filter(Boolean)
    .join("");
  if (!chips) return "";
  return `<div class="clarify-options" data-testid="clarify-options">${chips}</div>`;
}

function renderClarification() {
  const missing = (state.sidebar && state.sidebar.missing) || [];
  const live = liveClarifyMessage();
  const clar = live || (missing.length ? latestClarify() : null);
  if (!shouldShowLiveClarify()) return "";
  if (!clar && !missing.length) return "";
  const pending = ((clar && clar.payload && clar.payload.pending) || []).map((item) => item.name || item).filter(Boolean);
  const fields = missing.length ? missing : pending;
  const lock = busy ? "disabled" : "";
  const skipBtn = `<button type="button" class="ghost" id="btn-clarify-skip" ${lock}>Skip</button>`;
  const optionChips = renderClarifyOptions(clar, lock);
  if (!fields.length && clar) {
    return `<div class="card" data-testid="clarification-form"><h3>Clarification</h3><p>${escapeHtml(clar.text || "")}</p>${optionChips}<div class="actions">${skipBtn}</div></div>`;
  }
  const inputs = fields
    .map((name) => {
      const current = ((state.sidebar && state.sidebar.slots) || []).find((s) => s.name === name);
      const value = current && current.value != null ? String(current.value) : "";
      return `<div class="slot-row"><label>${escapeHtml(slotLabel(name))}<input data-slot="${escapeHtml(name)}" value="${escapeHtml(value)}" /></label></div>`;
    })
    .join("");
  const prompt = clar ? `<p>${escapeHtml(clar.text || "")}</p>` : "<p>Fill the missing fields, then submit. Skip ends this request.</p>";
  return `<div class="card" data-testid="clarification-form"><h3>Clarification</h3>${prompt}${optionChips}${inputs}<div class="actions"><button type="button" class="primary" id="btn-clarify" ${lock}>Submit slots</button>${skipBtn}</div></div>`;
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
  const job = (state.sidebar && state.sidebar.active_intent && state.sidebar.active_intent.job) || "";
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
  const jobLine = job ? `<p class="job-line">Job: ${escapeHtml(job)}</p>` : "";
  const rid = currentPlanRunId();
  const openBtn = rid
    ? `<button type="button" class="ghost" data-open-plan="${escapeHtml(rid)}">Open plan</button>`
    : "";
  return `<div class="card compact" data-testid="plan-card"><h3>Plan ready</h3>
    ${jobLine}
    <p class="warn">Plan ${escapeHtml(card.plan_id)}</p>
    <p class="hint">Full steps are in the plan Artifact. Confirm is optional.</p>
    ${editor}
    ${renderDecisionActions(openBtn)}</div>`;
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

function renderPlanMarkdown(md) {
  const raw = String(md || "");
  const markedLib = typeof window !== "undefined" ? window.marked : undefined;
  const purify = typeof window !== "undefined" ? window.DOMPurify : undefined;
  if (!raw) return `<pre class="plan-md">(empty plan.md)</pre>`;
  if (!markedLib || !purify || typeof markedLib.parse !== "function") {
    return `<pre class="plan-md">${escapeHtml(raw)}</pre>`;
  }
  const html = markedLib.parse(raw);
  const wrap = document.createElement("div");
  wrap.innerHTML = purify.sanitize(html);
  wrap.querySelectorAll("pre code.language-mermaid").forEach((code) => {
    const pre = code.parentElement;
    const div = document.createElement("div");
    div.className = "mermaid";
    div.textContent = code.textContent || "";
    if (pre) pre.replaceWith(div);
  });
  return `<div class="plan-md-html">${wrap.innerHTML}</div>`;
}

function runMermaid(root) {
  const mermaidLib = typeof window !== "undefined" ? window.mermaid : undefined;
  if (!mermaidLib || !root) return;
  mermaidLib.initialize({ startOnLoad: false, securityLevel: "strict", theme: "dark" });
  const nodes = root.querySelectorAll(".mermaid");
  if (!nodes.length) return;
  mermaidLib.run({ nodes: Array.from(nodes) });
}

function exportLink(art, label) {
  if (!art || !art.export_path || !art.run_id) return "";
  const href = `/v1/artifacts/${encodeURIComponent(art.run_id)}?path=${encodeURIComponent(art.export_path)}`;
  return `<a class="export-link" href="${href}">${escapeHtml(label || "Export")}</a>`;
}

function renderSettingsBody() {
  const p = providerInfo || {};
  const model = p.model || "—";
  const modeLabel = p.mode || "rule";
  return `<div class="settings-placeholder">
    <h3>Settings</h3>
    <p class="empty-hint">Provider and environment configuration will live here.</p>
    <p>Provider ${escapeHtml(modeLabel)} · ${escapeHtml(model)}</p>
  </div>`;
}

function onTabsWheel(ev) {
  const tabs = ev.currentTarget;
  if (!tabs || tabs.scrollWidth <= tabs.clientWidth) return;
  if (Math.abs(ev.deltaY) < Math.abs(ev.deltaX)) return;
  ev.preventDefault();
  tabs.scrollLeft += ev.deltaY;
}

function bindTabsWheel(host) {
  const tabs = host && host.querySelector(".tabs");
  if (!tabs) return;
  tabs.addEventListener("wheel", onTabsWheel, { passive: false });
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
  const catalog = catalogArtifacts();
  const fileCard = filePreview
    ? `<div class="card"><div class="artifact-toolbar"><span class="art-type">file</span>
        <button type="button" id="btn-file-back">Back to artifacts</button></div>
        <h3>${escapeHtml(filePreview.name)}</h3><p class="warn">${escapeHtml(filePreview.path)}</p>
        <textarea rows="16" readonly>${escapeHtml(filePreview.content)}</textarea></div>`
    : "";
  if (openTabs.length === 0 && !filePreview) {
    host.innerHTML = `<div class="artifact-empty" data-testid="artifact-panel">
      <div class="artifact-empty-mark">◇</div>
      <p class="empty-hint">Open a plan or artifact from Workspace, or click Open plan on a Plan ready card.</p>
    </div>`;
    return;
  }
  const tabs = openTabs
    .map((tab) => {
      const art = catalog.find((row) => artifactKey(row) === artifactKey(tab));
      const key = artifactKey(tab);
      const label =
        tab.type === "settings" ? "Settings" : (art && (art.title || art.type)) || tab.type || "artifact";
      return `<div class="tab ${key === activeKey ? "active" : ""}" data-tab="${escapeHtml(key)}">${escapeHtml(label)}
        <button type="button" class="tab-close" data-tab-close="${escapeHtml(key)}" title="Close">×</button></div>`;
    })
    .join("");
  const currentTab = openTabs.find((tab) => artifactKey(tab) === activeKey) || openTabs[0];
  if (filePreview) {
    host.innerHTML = `<div class="tabs">${tabs}</div><div data-testid="artifact-panel">${fileCard}</div>`;
    bindTabsWheel(host);
    return;
  }
  if (currentTab && currentTab.type === "settings") {
    host.innerHTML = `<div class="tabs">${tabs}</div><div data-testid="artifact-panel">${renderSettingsBody()}</div>`;
    bindTabsWheel(host);
    return;
  }
  const current =
    catalog.find((row) => artifactKey(row) === activeKey) ||
    catalog.find((row) => openTabs.some((tab) => artifactKey(tab) === artifactKey(row)));
  if (!current) {
    host.innerHTML = `<div class="tabs">${tabs}</div><div data-testid="artifact-panel"><p class="empty-hint">This artifact is no longer in the session index.</p></div>`;
    bindTabsWheel(host);
    return;
  }
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
  } else if (current.type === "plan") {
    const markdown = (current.preview && current.preview.markdown) || "";
    const path = (current.preview && current.preview.path) || current.export_path || "";
    body += `<h3>${escapeHtml(current.title || "plan.md")}</h3>
      ${path ? `<p class="warn">${escapeHtml(path)}</p>` : ""}
      ${renderPlanMarkdown(markdown)}
      <p class="hint">JSON in runs/ is the executable source. Editing this markdown does not change what Run executes.</p>`;
  }
  host.innerHTML = `<div class="tabs">${tabs}</div><div data-testid="artifact-panel">${body}</div>`;
  bindTabsWheel(host);
  runMermaid(host);
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
    : "";
  const pipe = job !== "—" ? `<div class="pipeline">${pipelineHtml(job)}</div>` : "";
  const slotBlock = slots.length
    ? `<div class="now-slots"><p class="now-k">Slots</p><ul>${slotRows}</ul></div>`
    : "";
  const env = envLine(bar.env_summary);
  const envBlock = env === "No env_facts yet." ? "" : `<div class="now-env"><p class="now-k">Environment</p><p>${escapeHtml(env)}</p></div>`;
  const execStatus = String((state.execution && state.execution.status) || "");
  const runLine = busy || execStatus === "running"
    ? `<p class="now-run" id="now-run-status">Running · ${formatElapsed(runElapsedS)}</p>`
    : "";
  host.innerHTML = `<div class="now-job"><p class="now-k">Now</p><p class="now-v">Job: ${escapeHtml(job)}</p>
    ${runLine}
    ${pipe}</div>
    ${missingLine}
    ${slotBlock}
    ${envBlock}
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
  const host = $("workspace-files");
  if (!host) return;
  const arts = workspace.artifacts || state.artifacts || [];
  if (!arts.length) {
    host.innerHTML = `<p class="files-k">This session</p><p class="empty-hint">No artifacts in this session yet.</p>`;
    return;
  }
  host.innerHTML = `<p class="files-k">This session</p><ul class="file-tree">${arts
    .map(
      (art, i) =>
        `<li><button type="button" class="file" data-art-index="${i}">${escapeHtml(art.type || "artifact")} · ${escapeHtml(art.title || art.run_id || "")}</button></li>`
    )
    .join("")}</ul>`;
}

function renderPanes() {
  renderMode();
  renderSessionList();
  renderChat();
  renderArtifacts();
  renderWorkspace();
  renderProviderBadge();
  renderStatusbar();
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
