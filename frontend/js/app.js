import {
  createCamera,
  createInvestigation,
  createMachine,
  createRule,
  createZone,
  cleanupEvidence,
  analyzeVideo,
  cameraSnapshotUrl,
  deleteCamera,
  deleteEvent,
  deleteInvestigation,
  deleteMachine,
  deleteRule,
  deleteZone,
  eventEvidenceUrl,
  cameraStreamUrl,
  cameraVideoUrl,
  getCameraHealth,
  getCameraDiagnostics,
  getCameraProductivity,
  getHealth,
  getMappingPoses,
  getOperationsDiagnostics,
  getOperationsSummary,
  getProductivitySummary,
  getRuntimeSettings,
  getStreamInfo,
  getVisionObjects,
  getVisionStatus,
  getVideoAnalysisStatus,
  listEvents,
  listEvidence,
  listInvestigations,
  listMachines,
  listRules,
  listCameras,
  listZones,
  listVideoAnalyses,
  operationsStreamUrl,
  restartVision,
  setupDemo,
  startMapping,
  startVision,
  stopMapping,
  stopVision,
  simulateRule as simulateRuleRequest,
  testCamera,
  testCameraSource,
  updateCamera,
  updateEvent,
  updateInvestigation,
  updateMachine,
  updateRule,
  updateZone,
  debugVideoUrl,
  uploadedVideoUrl,
} from "./api.js";
import {
  createLocalAccount,
  getCurrentUser,
  signInLocal,
  signOutLocal,
} from "./auth.js";
import { currentRoute, routes } from "./state.js";

const statusElement = document.querySelector("#backend-status");
const statusText = statusElement.querySelector(".status-text");
const pageTitle = document.querySelector("#page-title");
const appView = document.querySelector("#app-view");
const appShell = document.querySelector("#app-shell");
const accountButton = document.querySelector("#account-button");
const accountName = document.querySelector("#account-name");
const navLinks = document.querySelectorAll("[data-route]");
const sidebarToggle = document.querySelector("#sidebar-toggle");
const toastStack = document.querySelector("#toast-stack");
let activeMediaCameraId = null;
let zoneDrawingPoints = [];
let zonePreviewZones = [];
let machineDrawingPoints = [];
let machinePreviewMachines = [];
let machineClickDetectMode = false;
let liveStatusRefreshInFlight = false;
let backendStatusRefreshInFlight = false;
let operationsStream = null;
let operationsStreamLastSummary = "";
let lastBackendState = "checking";
const sidebarStorageKey = "campex.sidebar";
let camerasCache = [];
let rulesCache = [];
let editingCameraId = null;
let editingRuleId = null;
let backendStatusTimer = null;
let liveStatusTimer = null;
let videoAnalysisTimer = null;
let sidebarReady = false;

function refreshIcons() {
  window.lucide?.createIcons({
    attrs: {
      "aria-hidden": "true",
      focusable: "false",
    },
  });
}

function setSidebarState(state) {
  if (!appShell || !sidebarToggle) return;
  const isCollapsed = state === "collapsed";
  appShell.dataset.sidebar = isCollapsed ? "collapsed" : "expanded";
  sidebarToggle.setAttribute("aria-expanded", String(!isCollapsed));
  sidebarToggle.setAttribute("aria-label", isCollapsed ? "Expandir menu" : "Recolher menu");
  sidebarToggle.innerHTML = `<i data-lucide="${isCollapsed ? "panel-left-open" : "panel-left-close"}" aria-hidden="true"></i>`;
  localStorage.setItem(sidebarStorageKey, appShell.dataset.sidebar);
  refreshIcons();
}

function setupSidebar() {
  if (!appShell || !sidebarToggle || sidebarReady) return;
  sidebarReady = true;
  setSidebarState(localStorage.getItem(sidebarStorageKey) || "expanded");
  sidebarToggle.addEventListener("click", () => {
    const nextState = appShell.dataset.sidebar === "collapsed" ? "expanded" : "collapsed";
    setSidebarState(nextState);
  });
}

function notify(title, detail = "", type = "info", timeout = 4200) {
  if (!toastStack) return;
  const toast = document.createElement("article");
  toast.className = "toast";
  toast.dataset.type = type;
  toast.innerHTML = `<strong>${title}</strong>${detail ? `<span>${detail}</span>` : ""}`;
  toastStack.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(6px)";
    setTimeout(() => toast.remove(), 180);
  }, timeout);
}

function notifyError(title, error) {
  notify(title, error?.message || String(error), "error", 6500);
}

function renderAuthScreen(mode = "login") {
  appShell.hidden = true;
  operationsStream?.close();
  operationsStream = null;
  const existing = document.querySelector("#auth-screen");
  existing?.remove();

  const authScreen = document.createElement("section");
  authScreen.className = "auth-screen";
  authScreen.id = "auth-screen";
  authScreen.innerHTML = `
    <div class="auth-left">
      <div class="auth-form-shell">
        <div class="auth-logo-block">
          <img src="./assets/campex-logo-white.png" alt="CAMPEX" />
          <span>INTELIGÊNCIA EM OPERAÇÃO</span>
        </div>

        <div class="auth-copy">
          <h1 id="auth-title">Acesse sua conta</h1>
          <p id="auth-subtitle">Entre para monitorar, analisar e transformar suas câmeras em resultados.</p>
        </div>

        <form class="auth-form" id="login-form">
          <label class="auth-field" aria-label="E-mail">
            <i data-lucide="mail" aria-hidden="true"></i>
            <input name="email" type="email" autocomplete="email" placeholder="E-mail" required />
          </label>
          <label class="auth-field" aria-label="Senha">
            <i data-lucide="lock-keyhole" aria-hidden="true"></i>
            <input name="password" type="password" autocomplete="current-password" placeholder="Senha" required />
            <i data-lucide="eye" aria-hidden="true"></i>
          </label>
          <div class="auth-row-actions">
            <label class="auth-check"><input type="checkbox" name="remember" /><span>Lembrar de mim</span></label>
            <button class="auth-link" type="button">Esqueceu sua senha?</button>
          </div>
          <p class="auth-error" data-auth-error="login"></p>
          <button class="auth-primary" type="submit"><span>Entrar</span><i data-lucide="arrow-right" aria-hidden="true"></i></button>
          <div class="auth-divider"><span>ou</span></div>
          <button class="auth-google" type="button"><span aria-hidden="true">G</span><strong>Entrar com o Google</strong></button>
          <p class="auth-switch"><span>Ainda não tem uma conta?</span><button type="button" data-auth-tab="signup">Criar conta</button></p>
        </form>

        <form class="auth-form" id="signup-form">
          <label class="auth-field" aria-label="Nome">
            <i data-lucide="user" aria-hidden="true"></i>
            <input name="name" autocomplete="name" placeholder="Nome" required minlength="2" />
          </label>
          <label class="auth-field" aria-label="E-mail">
            <i data-lucide="mail" aria-hidden="true"></i>
            <input name="email" type="email" autocomplete="email" placeholder="E-mail" required />
          </label>
          <label class="auth-field" aria-label="Senha">
            <i data-lucide="lock-keyhole" aria-hidden="true"></i>
            <input name="password" type="password" autocomplete="new-password" placeholder="Senha" required minlength="6" />
            <i data-lucide="eye" aria-hidden="true"></i>
          </label>
          <p class="auth-error" data-auth-error="signup"></p>
          <button class="auth-primary" type="submit"><span>Criar e entrar</span><i data-lucide="arrow-right" aria-hidden="true"></i></button>
          <p class="auth-switch"><span>Já tem uma conta?</span><button type="button" data-auth-tab="login">Entrar</button></p>
        </form>
      </div>
      <footer class="auth-footer">
        <strong>CAMPEX</strong>
        <span>Segurança. Operação. Resultados.</span>
      </footer>
    </div>

    <div class="auth-hero-panel">
      <div class="auth-hero-words" aria-label="Monitorar, analisar e evoluir">
        <span>MONITORAR</span>
        <span>ANALISAR</span>
        <span>EVOLUIR</span>
      </div>
      <div class="auth-hero-message">
        <span class="auth-mark-line" aria-hidden="true"></span>
        <h2>Mais que câmeras.<br /><em>Inteligência real<br />para o seu negócio.</em></h2>
        <p>A Campex ajuda empresas a enxergarem mais, agirem mais rápido e operarem com mais eficiência.</p>
      </div>
      <div class="auth-benefits" aria-label="Benefícios CAMPEX">
        <div><i data-lucide="bar-chart-3" aria-hidden="true"></i><span>Mais eficiência</span></div>
        <div><i data-lucide="shield-check" aria-hidden="true"></i><span>Mais segurança</span></div>
        <div><i data-lucide="clock-3" aria-hidden="true"></i><span>Mais resultados</span></div>
      </div>
      <div class="auth-dots" aria-hidden="true"><span></span><span></span><span></span></div>
    </div>
  `;  document.body.prepend(authScreen);

  authScreen.querySelector("#login-form").addEventListener("submit", handleLoginSubmit);
  authScreen.querySelector("#signup-form").addEventListener("submit", handleSignupSubmit);
  authScreen.querySelectorAll("[data-auth-tab]").forEach((button) => {
    button.addEventListener("click", () => setAuthMode(button.dataset.authTab));
  });
  setAuthMode(mode);
  refreshIcons();
}

function setAuthMode(mode) {
  const nextMode = mode === "signup" ? "signup" : "login";
  document.querySelectorAll("[data-auth-tab]").forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.authTab === nextMode));
  });
  const title = document.querySelector("#auth-title");
  const subtitle = document.querySelector("#auth-subtitle");
  if (title) {
    title.textContent = nextMode === "signup" ? "Crie sua conta" : "Acesse sua conta";
  }
  if (subtitle) {
    subtitle.textContent = nextMode === "signup"
      ? "Cadastre seu acesso local para acompanhar câmeras, eventos e evidências."
      : "Entre para monitorar, analisar e transformar suas câmeras em resultados.";
  }
  const loginForm = document.querySelector("#login-form");
  const signupForm = document.querySelector("#signup-form");
  if (loginForm) loginForm.hidden = nextMode !== "login";
  if (signupForm) signupForm.hidden = nextMode !== "signup";
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  await submitAuthForm(form, "login", () => signInLocal({
    email: form.elements.email.value,
    password: form.elements.password.value,
  }));
}

async function handleSignupSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  await submitAuthForm(form, "signup", () => createLocalAccount({
    name: form.elements.name.value,
    email: form.elements.email.value,
    password: form.elements.password.value,
  }));
}

async function submitAuthForm(form, mode, action) {
  const errorHost = document.querySelector(`[data-auth-error="${mode}"]`);
  const submitButton = form.querySelector("button[type='submit']");
  if (errorHost) errorHost.textContent = "";
  submitButton.disabled = true;
  try {
    const user = await action();
    document.querySelector("#auth-screen")?.remove();
    startAuthenticatedApp(user);
  } catch (error) {
    if (errorHost) errorHost.textContent = error.message || String(error);
  } finally {
    submitButton.disabled = false;
  }
}

function startAuthenticatedApp(user = getCurrentUser()) {
  if (!user) {
    renderAuthScreen();
    return;
  }
  appShell.hidden = false;
  if (accountName) accountName.textContent = user.name;
  setupSidebar();
  applyLocalSettings();
  renderRoute();
  refreshIcons();
  refreshBackendStatus();
  if (!backendStatusTimer) {
    backendStatusTimer = setInterval(refreshBackendStatus, 30000);
  }
  if (!liveStatusTimer) {
    liveStatusTimer = setInterval(() => {
      if (currentRoute() === "live") {
        refreshLiveStatus();
      }
    }, 3000);
  }
}

function handleSignOut() {
  signOutLocal();
  operationsStream?.close();
  operationsStream = null;
  clearInterval(backendStatusTimer);
  clearInterval(liveStatusTimer);
  backendStatusTimer = null;
  liveStatusTimer = null;
  renderAuthScreen();
}

function renderRoute() {
  const routeKey = currentRoute();
  const route = routes[routeKey];
  if (routeKey !== "dashboard" && operationsStream) {
    operationsStream.close();
    operationsStream = null;
  }

  pageTitle.textContent = route.title;
  navLinks.forEach((link) => {
    const isCurrent = link.dataset.route === routeKey;
    if (isCurrent) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });

  if (routeKey === "cameras") {
    renderCamerasPage();
    return;
  }

  if (routeKey === "dashboard") {
    renderDashboardPage();
    return;
  }

  if (routeKey === "wall") {
    renderVideoWallPage();
    return;
  }

  if (routeKey === "events") {
    renderEventsPage();
    return;
  }

  if (routeKey === "video-analysis") {
    renderVideoAnalysisPage();
    return;
  }

  if (routeKey === "productivity") {
    renderProductivityPage();
    return;
  }

  if (routeKey === "investigations") {
    renderInvestigationsPage();
    return;
  }

  if (routeKey === "zones") {
    renderZonesPage();
    return;
  }

  if (routeKey === "machines") {
    renderMachinesPage();
    return;
  }

  if (routeKey === "rules") {
    renderRulesPage();
    return;
  }

  if (routeKey === "settings") {
    renderSettingsPage();
    return;
  }

  if (routeKey === "evidence") {
    renderEvidencePage();
    return;
  }

  if (routeKey === "diagnostics") {
    renderDiagnosticsPage();
    return;
  }

  if (routeKey === "live") {
    renderLivePage();
    return;
  }

  appView.innerHTML = `
    <div class="foundation-panel">
      <section class="module-notice">
        <h2>${route.title}</h2>
        <p>${route.message}</p>
      </section>
      <section class="system-strip" aria-label="Estado da fundacao">
        <div class="system-cell">
          <span>Frontend</span>
          <strong>Shell carregado</strong>
        </div>
        <div class="system-cell">
          <span>Backend</span>
          <strong id="backend-summary">Aguardando health check</strong>
        </div>
        <div class="system-cell">
          <span>Banco</span>
          <strong>SQLite inicializado pelo backend</strong>
        </div>
      </section>
    </div>
  `;
}

async function renderDashboardPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-toolbar">
        <button type="button" id="dashboard-refresh">Atualizar</button>
      </section>
      <section id="dashboard-kpis" class="settings-grid"></section>
      <section class="ops-grid">
        <div>
          <div class="section-heading"><h2>Eventos recentes</h2><span id="dashboard-event-count">0</span></div>
          <div id="dashboard-events" class="ops-list"></div>
        </div>
        <aside class="ops-detail">
          <h2>Leitura operacional</h2>
          <div id="dashboard-insights" class="object-list"></div>
        </aside>
      </section>
    </div>
  `;
  document.querySelector("#dashboard-refresh").addEventListener("click", loadDashboard);
  startOperationsStream();
  await loadDashboard();
}

function startOperationsStream() {
  if (operationsStream) return;
  try {
    operationsStream = new EventSource(operationsStreamUrl());
    operationsStream.addEventListener("summary", (event) => {
      if (currentRoute() !== "dashboard") return;
      if (event.data === operationsStreamLastSummary) return;
      operationsStreamLastSummary = event.data;
      const summary = JSON.parse(event.data);
      renderDashboardSummary(summary);
    });
    operationsStream.addEventListener("open", () => {});
    operationsStream.addEventListener("error", () => {
      operationsStream?.close();
      operationsStream = null;
    });
  } catch {
    operationsStream = null;
  }
}

async function loadDashboard() {
  try {
    const [summary, cameras, zones] = await Promise.all([
      getOperationsSummary(),
      listCameras(),
      listZones(),
    ]);
    const cameraById = Object.fromEntries(cameras.map((camera) => [camera.id, camera]));
    const zoneById = Object.fromEntries(zones.map((zone) => [zone.id, zone]));
    renderDashboardSummary(summary);
    document.querySelector("#dashboard-event-count").textContent = `${summary.recent_events.length} itens`;
    document.querySelector("#dashboard-events").innerHTML = summary.recent_events.length
      ? summary.recent_events.map((event) => eventRow(event, cameraById, zoneById)).join("")
      : emptyState("Sem eventos recentes", "Quando a visão detectar ocorrências, elas entram aqui.");
    document.querySelectorAll("[data-event-action]").forEach((button) => {
      button.addEventListener("click", handleEventAction);
    });
    renderDashboardInsights(summary);
  } catch (error) {
    document.querySelector("#dashboard-kpis").innerHTML = emptyState("Falha ao carregar painel", error.message);
  }
}

async function renderProductivityPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-toolbar">
        <button type="button" id="productivity-refresh"><i data-lucide="refresh-cw" aria-hidden="true"></i><span>Atualizar</span></button>
      </section>
      <section id="productivity-kpis" class="settings-grid"></section>
      <section class="ops-grid">
        <div>
          <div class="section-heading"><h2>Sinais por câmera</h2><span id="productivity-signal-count">0 sinais</span></div>
          <div id="productivity-cameras" class="ops-list"></div>
        </div>
        <aside class="ops-detail">
          <h2>Máquinas detectadas</h2>
          <div id="productivity-machines" class="object-list"></div>
          <h2>Limitações</h2>
          <div id="productivity-limitations" class="object-list"></div>
        </aside>
      </section>
    </div>
  `;
  document.querySelector("#productivity-refresh").addEventListener("click", loadProductivity);
  refreshIcons();
  await loadProductivity();
}

async function renderVideoAnalysisPage() {
  clearInterval(videoAnalysisTimer);
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-grid">
        <div>
          <div class="section-heading">
            <h2>CAMPEX Intelligence por MP4</h2>
            <span>Vídeo como fonte real</span>
          </div>
          <form id="video-analysis-form" class="stack-form">
            <label>Arquivo MP4
              <input name="video" type="file" accept="video/mp4,.mp4" required />
            </label>
            <button type="submit" class="primary-action"><i data-lucide="upload" aria-hidden="true"></i><span>Enviar e analisar</span></button>
          </form>
          <div id="video-analysis-player" class="ops-detail"></div>
        </div>
        <aside class="ops-detail">
          <h2>Status</h2>
          <div id="video-analysis-status" class="object-list"></div>
          <h2>CAMPEX Intelligence</h2>
          <div id="video-analysis-insight" class="object-list"></div>
        </aside>
      </section>
      <section class="ops-grid">
        <div>
          <div class="section-heading"><h2>Eventos</h2><span id="video-event-count">0</span></div>
          <div id="video-analysis-events" class="ops-list"></div>
        </div>
        <aside class="ops-detail">
          <h2>Métricas</h2>
          <div id="video-analysis-metrics" class="settings-grid"></div>
          <h2>Tracks</h2>
          <div id="video-analysis-tracks" class="object-list"></div>
        </aside>
      </section>
    </div>
  `;
  document.querySelector("#video-analysis-form").addEventListener("submit", handleVideoAnalysisSubmit);
  refreshIcons();
  await loadLatestVideoAnalysis();
}

async function handleVideoAnalysisSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const file = form.elements.video.files[0];
  if (!file) return;
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const analysis = await analyzeVideo(file);
    notify("Análise criada", "O vídeo entrou na fila de processamento.", "success");
    renderVideoAnalysis(analysis);
    pollVideoAnalysis(analysis.analysis_id);
  } catch (error) {
    notifyError("Falha no upload", error);
  } finally {
    button.disabled = false;
  }
}

async function loadLatestVideoAnalysis() {
  try {
    const analyses = await listVideoAnalyses();
    if (!analyses.length) {
      document.querySelector("#video-analysis-status").innerHTML = emptyState("Nenhuma análise", "Envie um MP4 para iniciar.");
      return;
    }
    renderVideoAnalysis(analyses[0]);
    if (!["COMPLETED", "FAILED"].includes(analyses[0].status)) {
      pollVideoAnalysis(analyses[0].analysis_id);
    }
  } catch (error) {
    document.querySelector("#video-analysis-status").innerHTML = emptyState("Falha ao carregar análises", error.message);
  }
}

function pollVideoAnalysis(analysisId) {
  clearInterval(videoAnalysisTimer);
  videoAnalysisTimer = setInterval(async () => {
    if (currentRoute() !== "video-analysis") {
      clearInterval(videoAnalysisTimer);
      return;
    }
    try {
      const analysis = await getVideoAnalysisStatus(analysisId);
      renderVideoAnalysis(analysis);
      if (["COMPLETED", "FAILED"].includes(analysis.status)) {
        clearInterval(videoAnalysisTimer);
      }
    } catch (error) {
      clearInterval(videoAnalysisTimer);
      notifyError("Falha ao acompanhar análise", error);
    }
  }, 1800);
}

function renderVideoAnalysis(analysis) {
  const source = analysis.source || {};
  const metrics = analysis.metrics || {};
  const summary = metrics.summary || {};
  document.querySelector("#video-analysis-status").innerHTML = [
    objectLine(analysis.status, `${analysis.progress || 0}%`, analysis.error || analysis.original_filename),
    objectLine("Fonte", source.duration_seconds ? `${source.duration_seconds.toFixed(1)}s · ${source.width}x${source.height}` : "Aguardando leitura", source.fps ? `${source.fps.toFixed(2)} FPS` : ""),
  ].join("");
  const runtime = analysis.runtime || {};
  const ai = analysis.ai || {};
  document.querySelector("#video-analysis-player").innerHTML = analysis.analysis_id
    ? `
      <video controls playsinline src="${analysis.debug_video ? debugVideoUrl(analysis.analysis_id) : uploadedVideoUrl(analysis.analysis_id)}"></video>
      ${analysis.debug_video ? objectLine("Vídeo debug", "Overlays CAMPEX ativos", "Arquivo original preservado") : objectLine("Vídeo original", "Ative VIDEO_DEBUG_OVERLAY=true para gerar overlays", "")}
    `
    : emptyState("Sem vídeo", "O player aparece após o upload.");
  document.querySelector("#video-analysis-metrics").innerHTML = [
    metricItem("Pessoas únicas", summary.unique_people ?? metrics.people?.detected ?? "-", "IDs temporários de tracking"),
    metricItem("Visíveis", metrics.people?.people_visible ?? "-", `Pico ${metrics.people?.max_simultaneous ?? "-"}`),
    metricItem("Detecções", summary.total_detections ?? "-", "Amostragem de frames"),
    metricItem("Eventos", summary.total_events ?? "-", "Derivados do histórico"),
    metricItem("Moving", `${metrics.activity?.moving_seconds ?? 0}s`, "Tempo acumulado"),
    metricItem("Stationary", `${metrics.activity?.stationary_seconds ?? 0}s`, `${metrics.activity?.stationary_events ?? 0} eventos`),
  ].join("");
  document.querySelector("#video-analysis-status").innerHTML += [
    objectLine("Detector", runtime.detector || "-", `${runtime.model || "-"} · ${runtime.device || "cpu"}${runtime.fallback ? " · fallback" : ""}`),
    objectLine("Tracker", runtime.tracker || "-", `FPS análise ${runtime.analysis_fps ?? "-"}`),
    objectLine("Entrada", runtime.input_resolution ? `${runtime.input_resolution}px` : "-", "Resolução de inferência"),
    objectLine("IA", ai.status || "pendente", ai.fallback_used ? `Fallback: ${ai.reason || ""}` : (ai.model || "")),
  ].join("");
  const events = analysis.events || [];
  document.querySelector("#video-event-count").textContent = `${events.length} eventos`;
  document.querySelector("#video-analysis-events").innerHTML = events.length
    ? events.slice(0, 80).map((event) => `
      <article class="ops-row">
        <div><strong>${event.event_type}</strong><span>${formatEventTime(event)} · track ${event.track_id ?? "-"}</span></div>
      </article>
    `).join("")
    : emptyState("Sem eventos", "Os eventos aparecem durante ou após o processamento.");
  const tracks = analysis.tracks || [];
  document.querySelector("#video-analysis-tracks").innerHTML = tracks.length
    ? tracks.slice(0, 20).map((track) => objectLine(
        `${track.class} #${track.track_id}`,
        `${track.total_visible_seconds ?? track.duration_seconds ?? 0}s observados · ${(track.confidence * 100).toFixed(0)}%`,
        `${track.movement_state || track.state || "UNKNOWN"} · moving ${track.moving_seconds ?? 0}s · stationary ${track.stationary_seconds ?? 0}s`
      )).join("")
    : emptyState("Sem tracks", "O tracker ainda não confirmou objetos.");
  const insight = analysis.insight || {};
  document.querySelector("#video-analysis-insight").innerHTML = insight.summary
    ? objectLine("Resumo da operação", insight.summary, (insight.limitations || []).join(" "))
    : emptyState("Aguardando inteligência", "O Nemotron é chamado ao final com métricas agregadas.");
  refreshIcons();
}

function formatEventTime(event) {
  if (event.timestamp != null) return formatSeconds(event.timestamp);
  const raw = event.started_at || "";
  if (!raw) return "-";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatSeconds(value) {
  const seconds = Number(value || 0);
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

async function loadProductivity() {
  try {
    const payload = await getProductivitySummary();
    document.querySelector("#productivity-kpis").innerHTML = [
      metricItem("Atividade observada", payload.score == null ? "sem score" : `${payload.score}%`, "Sem calculo de produtividade real"),
      metricItem("Pessoas", payload.counts.people, `${payload.counts.signals} sinais ativos`),
      metricItem("Máquinas", payload.counts.machines, `${payload.mapped_machines_total || 0} mapeadas · ${payload.counts.cameras} câmeras`),
    ].join("");
    document.querySelector("#productivity-signal-count").textContent = `${payload.counts.signals} sinais`;
    document.querySelector("#productivity-cameras").innerHTML = payload.cameras.length
      ? payload.cameras.map(productivityCameraRow).join("")
      : emptyState("Sem câmeras", "Cadastre e ligue Vision nas câmeras para observar atividade.");
    const machines = payload.cameras.flatMap((camera) =>
      (camera.machines || []).map((machine) => ({ ...machine, camera_name: camera.camera_name }))
    );
    const mappedMachines = payload.cameras.flatMap((camera) =>
      (camera.mapped_machines || []).map((machine) => ({ ...machine, camera_name: camera.camera_name }))
    );
    document.querySelector("#productivity-machines").innerHTML = machines.length
      ? machines.map((machine) => objectLine(
          `${machine.class_name} #${machine.track_id}`,
          `${machine.camera_name} · confiança ${(machine.confidence * 100).toFixed(0)}%`,
          "Máquina/veículo reconhecido pelo detector"
        )).join("")
      : mappedMachines.length
        ? mappedMachines.map((machine) => objectLine(
            machine.name,
            `${machine.camera_name} · ${machine.type}`,
            `${machine.state || "UNKNOWN"} · ${machine.requires_operator ? "requer operador" : "operador opcional"} · ativo mapeado`
          )).join("")
        : emptyState("Nenhuma máquina mapeada", "Mapeie máquinas para contextualizar atividade e segurança.");
    document.querySelector("#productivity-limitations").innerHTML = [
      objectLine("Leitura assistiva", "O sistema aponta sinais; a conclusão final deve ser revisada por operador.", "Atividade observada não é produtividade real."),
      objectLine("Máquinas específicas", payload.machine_classes.join(", "), "Classes dependem do detector/fine-tuning."),
      objectLine("Comportamentos", payload.behavior_signals.join(", "), "Sinais disponíveis nesta versão."),
    ].join("");
  } catch (error) {
    document.querySelector("#productivity-kpis").innerHTML = emptyState("Falha ao carregar produtividade", error.message);
  }
}

function productivityCameraRow(camera) {
  const counts = camera.counts || {};
  const signals = camera.signals || [];
  return `
    <article class="ops-row">
      <div>
        <strong>${camera.camera_name}</strong>
        <span>${camera.score == null ? "Sem score" : `Score ${camera.score}%`} · ${counts.people || 0} pessoas · ${counts.machines || 0} máquinas/ativos · ${(camera.mapped_machines || []).length} mapeadas · ${counts.phones || 0} celulares</span>
        <small>${signals.length ? signals.map((signal) => signal.label).join(" · ") : "Sem sinais de atividade no momento"}</small>
      </div>
      <span class="health-badge" data-status="${signals.length ? "DEGRADED" : "ONLINE"}">${signals.length ? "ATENÇÃO" : "OK"}</span>
    </article>
  `;
}

function renderDashboardSummary(summary) {
  const kpis = summary.kpis;
  const intelligence = summary.intelligence || {};
  const triage = intelligence.triage || [];
  const attention = triage.filter((item) => item.decision === "INVESTIGATE");
  const kpiHost = document.querySelector("#dashboard-kpis");
  if (!kpiHost) return;
  kpiHost.innerHTML = [
    metricItem("Câmeras online", `${kpis.cameras_online}/${kpis.cameras_total}`, `${kpis.cameras_active} ativas`),
    metricItem("Eventos abertos", kpis.events_open, `${kpis.events_critical} críticos`),
    metricItem("Recorrências", triage.length, `${attention.length} para investigar`),
    metricItem("Investigações", kpis.investigations_open, "Casos em andamento"),
  ].join("");
  renderDashboardInsights(summary);
}

function renderDashboardInsights(summary) {
  const intelligence = summary.intelligence || {};
  const topGroup = (intelligence.event_groups || [])[0];
  const topTriage = (intelligence.triage || []).find((item) => item.decision === "INVESTIGATE");
  const topFinding = (intelligence.findings || [])[0];
  const topImpact = (intelligence.impacts || [])[0];
  const comparison = intelligence.comparisons?.today_vs_yesterday;
  const normal = intelligence.comparisons?.normal_vs_current;
  const areas = summary.areas.map((area) => `${area.area_id}: ${area.camera_count}`).join(" · ") || "sem áreas";
  const recurrence = topGroup
    ? `${topGroup.location_label}: ${topGroup.frequency}x, ${topGroup.total_duration_label}`
    : "sem recorrência confiável hoje";
  const triage = topTriage
    ? `${topTriage.group.location_label}: ${topTriage.reasons.join(" · ")}`
    : "ruído baixo no momento";
  const finding = topFinding?.statement || "sem finding executivo hoje";
  const comparisonLabel = comparison
    ? `${comparison.direction === "up" ? "+" : comparison.direction === "down" ? "-" : ""}${comparison.duration_delta_label}${comparison.duration_delta_percent !== null ? ` (${comparison.duration_delta_percent}%)` : ""}`
    : "sem base comparativa";
  const normalLabel = normal?.state !== "NO_BASELINE"
    ? `${normal.comparison.direction === "up" ? "+" : normal.comparison.direction === "down" ? "-" : ""}${normal.comparison.duration_delta_label}${normal.comparison.duration_delta_percent !== null ? ` (${normal.comparison.duration_delta_percent}%)` : ""}`
    : "sem baseline recente";
  const impact = topImpact
    ? `${topImpact.lost_time_label} perdidos${topImpact.estimated_cost !== null ? ` · ${formatMoney(topImpact.estimated_cost, topImpact.currency)}` : ""}`
    : "sem impacto acumulado";
  document.querySelector("#dashboard-insights").innerHTML = [
    objectLine("Áreas", areas, "Distribuição das câmeras cadastradas"),
    objectLine("Recorrência", recurrence, "Agrupa eventos confiáveis do dia"),
    objectLine("Triagem", triage, "Sobe frequência, duração ou severidade"),
    objectLine("Finding", finding, "Frase pronta para gerente"),
    objectLine("Hoje vs ontem", comparisonLabel, "Variação de tempo acumulado"),
    objectLine("Atual vs normal", normalLabel, "Média dos dias recentes com amostra"),
    objectLine("Impacto", impact, "Tempo perdido e R$ quando houver taxa configurada"),
  ].join("");
}

async function renderVideoWallPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-toolbar">
        <label>Layout
          <select id="wall-layout">
            <option value="1">1 câmera</option>
            <option value="4" selected>4 câmeras</option>
            <option value="9">9 câmeras</option>
          </select>
        </label>
        <button type="button" id="wall-refresh">Atualizar</button>
      </section>
      <section id="video-wall-grid" class="video-wall-grid" data-layout="4"></section>
    </div>
  `;
  document.querySelector("#wall-layout").addEventListener("change", loadVideoWall);
  document.querySelector("#wall-refresh").addEventListener("click", loadVideoWall);
  await loadVideoWall();
}

async function loadVideoWall() {
  const grid = document.querySelector("#video-wall-grid");
  const layout = Number(document.querySelector("#wall-layout")?.value || 4);
  grid.dataset.layout = String(layout);
  try {
    const cameras = await listCameras();
    const visible = cameras.slice(0, layout);
    grid.innerHTML = visible.length
      ? visible.map(videoWallTile).join("")
      : emptyState("Nenhuma câmera cadastrada", "Cadastre uma câmera para montar o mural operacional.");
  } catch (error) {
    grid.innerHTML = emptyState("Falha ao carregar mural", error.message);
  }
}

function videoWallTile(camera) {
  const media = camera.source_type === "video_file"
    ? `<video class="wall-media" src="${cameraVideoUrl(camera.id)}" autoplay muted playsinline loop></video>`
    : `<img class="wall-media" src="${cameraStreamUrl(camera.id)}" alt="${camera.name}" />`;
  return `
    <article class="wall-tile">
      <header>
        <strong>${camera.name}</strong>
        <span class="health-badge" data-status="${camera.status}">${camera.status}</span>
      </header>
      <div class="wall-media-host">${media}</div>
    </article>
  `;
}

async function renderLivePage() {
  appView.innerHTML = `
    <div class="live-console">
      <section class="live-toolbar" aria-label="Controles ao vivo">
        <label>
          Camera
          <select id="live-camera-select"></select>
        </label>
        <div class="row-actions">
          <button type="button" id="live-toggle-vision" class="mode-toggle" data-active="false">Vision: OFF</button>
          <button type="button" id="live-toggle-mapping" class="mode-toggle" data-active="false">Mapeamento: OFF</button>
          <button type="button" id="live-restart-vision">Reiniciar Vision</button>
          <button type="button" id="live-refresh">Atualizar</button>
        </div>
      </section>
      <section class="live-stage">
        <div class="live-feed">
          <div class="live-feed-header">
            <div>
              <strong id="live-camera-name">Nenhuma camera selecionada</strong>
              <span id="live-detection-summary">Vision parada · 0 objetos</span>
            </div>
            <div class="live-status-badges">
              <span class="health-badge" id="live-camera-status" data-status="OFFLINE">OFFLINE</span>
              <span class="health-badge" id="live-vision-status" data-status="STOPPED">VISION OFF</span>
            </div>
          </div>
          <div id="live-media-host" class="live-media-host" aria-live="polite">
            <div class="media-placeholder">Selecione uma camera</div>
          </div>
          <div class="live-telemetry" id="live-telemetry">
            <span>Camera FPS <strong id="live-camera-fps">0</strong></span>
            <span>Vision FPS <strong id="live-vision-fps">0</strong></span>
            <span>Frames <strong id="live-frame-count">0/0</strong></span>
            <span>Mapeamento <strong id="live-mapping-state">OFF</strong></span>
            <span id="live-error-line">Sem erros</span>
          </div>
        </div>
      </section>
    </div>
  `;

  document.querySelector("#live-camera-select").addEventListener("change", selectLiveCamera);
  document.querySelector("#live-toggle-vision").addEventListener("click", handleToggleVision);
  document.querySelector("#live-toggle-mapping").addEventListener("click", handleToggleMapping);
  document.querySelector("#live-restart-vision").addEventListener("click", handleRestartVision);
  document.querySelector("#live-refresh").addEventListener("click", refreshLiveStatus);
  await loadLiveCameras();
}

async function loadLiveCameras() {
  const select = document.querySelector("#live-camera-select");
  try {
    const cameras = await listCameras();
    select.innerHTML = cameras
      .map((camera) => `<option value="${camera.id}">${camera.name}</option>`)
      .join("");

    if (!cameras.length) {
      select.innerHTML = `<option value="">Cadastre uma camera</option>`;
      renderMediaPlaceholder("Nenhuma câmera cadastrada");
      renderVisionStatus(null, [], null);
      return;
    }

    const savedCameraId = localStorage.getItem("campex.live_camera_id");
    if (savedCameraId && cameras.some((camera) => camera.id === savedCameraId)) {
      select.value = savedCameraId;
    }
    await selectLiveCamera();
  } catch (error) {
    select.innerHTML = `<option value="">Backend indisponivel</option>`;
    renderVisionStatus(null, [], null);
    console.error(error);
  }
}

async function selectLiveCamera() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (cameraId) {
    localStorage.setItem("campex.live_camera_id", cameraId);
  }
  try {
    const camera = await selectedCamera();
    document.querySelector("#live-camera-name").textContent = camera?.name || "Camera";
    const status = statusLabel(camera?.status);
    const statusElement = document.querySelector("#live-camera-status");
    statusElement.textContent = status;
    statusElement.dataset.status = status;
    const visionStatus = await refreshLiveStatus();
    await renderLiveMedia(camera, visionStatus?.status === "RUNNING");
  } catch (error) {
    document.querySelector("#live-camera-name").textContent = "Backend indisponivel";
    document.querySelector("#live-camera-status").textContent = "OFFLINE";
    document.querySelector("#live-camera-status").dataset.status = "OFFLINE";
    renderMediaPlaceholder("Stream indisponivel");
    renderVisionStatus(null, [], null);
    console.error(error);
  }
}

async function selectedCamera() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return null;
  }
  const cameras = await listCameras();
  return cameras.find((item) => item.id === cameraId) || null;
}

async function renderLiveMedia(camera, visionEnabled = false) {
  activeMediaCameraId = camera?.id || null;
  if (!camera?.id) {
    renderMediaPlaceholder("Selecione uma camera");
    return;
  }

  renderMediaPlaceholder("Abrindo stream...");

  if (visionEnabled) {
    renderMjpegElement(camera);
    return;
  }

  if (camera.source_type === "video_file") {
    renderVideoElement(camera);
    return;
  }

  try {
    const info = await getStreamInfo(camera.id);
    if (activeMediaCameraId !== camera.id) {
      return;
    }

    if (info.mode === "file_video") {
      renderVideoElement(camera);
      return;
    }

    renderMjpegElement(camera);
  } catch (error) {
    renderMjpegElement(camera);
  }
}

function renderVideoElement(camera) {
  const mediaHost = document.querySelector("#live-media-host");
  const sources = videoSourcesFor(camera);
  mediaHost.innerHTML = `
    <video
      id="live-video"
      class="live-media"
      src="${sources[0]}"
      controls
      autoplay
      muted
      playsinline
      loop
    ></video>
  `;

  const video = mediaHost.querySelector("video");
  let sourceIndex = 0;
  video.addEventListener("error", () => {
    sourceIndex += 1;
    if (sources[sourceIndex]) {
      video.src = sources[sourceIndex];
      video.load();
      video.play().catch(() => {
        video.controls = true;
      });
      return;
    }
    renderMediaPlaceholder("Nao foi possivel reproduzir o arquivo de video.");
  });
  video.play().catch(() => {
    video.controls = true;
  });
}

function renderMjpegElement(camera) {
  const mediaHost = document.querySelector("#live-media-host");
  const streamUrl = `${cameraStreamUrl(camera.id)}?t=${Date.now()}`;
  mediaHost.innerHTML = `
    <img
      id="live-stream"
      class="live-media"
      alt="Video ao vivo da camera selecionada"
      src="${streamUrl}"
    />
  `;

  mediaHost.querySelector("img").addEventListener("error", () => {
    renderMediaPlaceholder("Aguardando frames da camera ao vivo.");
  });
}

function videoSourcesFor(camera) {
  return [cameraVideoUrl(camera.id)];
}

function renderMediaPlaceholder(message) {
  const mediaHost = document.querySelector("#live-media-host");
  if (!mediaHost) {
    return;
  }
  mediaHost.innerHTML = `<div class="media-placeholder">${message}</div>`;
}

async function handleToggleVision() {
  const button = document.querySelector("#live-toggle-vision");
  if (button?.dataset.active === "true") {
    await handleStopVision();
    return;
  }
  await handleStartVision();
}

async function handleStartVision() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return;
  }
  // Switch to MJPEG immediately so the user sees the live stream while
  // the backend starts the vision session (model loading can take
  // several seconds and the API call may time out on the client side).
  const camera = await selectedCamera();
  if (camera) {
    renderMjpegElement(camera);
  }
  try {
    await startVision(cameraId);
    notify("Vision ligada", "A análise da câmera foi iniciada.", "success");
  } catch (error) {
    console.error("Start vision failed:", error);
    notifyError("Falha ao ligar Vision", error);
  }
  await refreshLiveStatus();
}

async function handleStopVision() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return;
  }
  try {
    await stopVision(cameraId);
    notify("Vision desligada", "A análise da câmera foi pausada.", "warning");
    const camera = await selectedCamera();
    await renderLiveMedia(camera, false);
    await refreshLiveStatus();
  } catch (error) {
    notifyError("Falha ao desligar Vision", error);
  }
}

async function handleToggleMapping() {
  const button = document.querySelector("#live-toggle-mapping");
  if (button?.dataset.active === "true") {
    await handleStopMapping();
    return;
  }
  await handleStartMapping();
}

async function handleStartMapping() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return;
  }
  const button = document.querySelector("#live-toggle-mapping");
  if (button) {
    button.textContent = "Mapeamento: carregando";
    button.dataset.loading = "true";
  }
  const camera = await selectedCamera();
  if (camera) {
    renderMjpegElement(camera);
  }
  try {
    await startMapping(cameraId);
    notify("Mapeamento ligado", "O mapeamento corporal foi solicitado.", "success");
  } catch (error) {
    console.error("Start mapping failed:", error);
    notifyError("Falha ao ligar mapeamento", error);
  } finally {
    if (button) {
      delete button.dataset.loading;
    }
  }
  await refreshLiveStatus();
}

async function handleStopMapping() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return;
  }
  try {
    await stopMapping(cameraId);
    notify("Mapeamento desligado", "O mapeamento corporal foi pausado.", "warning");
    await refreshLiveStatus();
  } catch (error) {
    notifyError("Falha ao desligar mapeamento", error);
  }
}

async function handleRestartVision() {
  const cameraId = document.querySelector("#live-camera-select").value;
  if (!cameraId) {
    return;
  }
  // Switch to MJPEG immediately so the live stream is visible while the
  // backend restarts the vision session (model loading may take several
  // seconds and the API call can time out on the client side).
  const camera = await selectedCamera();
  if (camera) {
    renderMjpegElement(camera);
  }
  try {
    await restartVision(cameraId);
    notify("Vision reiniciada", "A sessão de análise foi reiniciada.", "success");
  } catch (error) {
    console.error("Restart vision failed:", error);
    notifyError("Falha ao reiniciar Vision", error);
  }
  await refreshLiveStatus();
}

async function refreshLiveStatus() {
  const cameraId = document.querySelector("#live-camera-select")?.value;
  if (!cameraId) {
    return;
  }
  if (liveStatusRefreshInFlight) {
    return;
  }
  liveStatusRefreshInFlight = true;

  try {
    const [health, visionStatus, objects, poses] = await Promise.all([
      getCameraHealth(cameraId),
      getVisionStatus(cameraId),
      getVisionObjects(cameraId),
      getMappingPoses(cameraId),
    ]);
    renderVisionStatus(visionStatus, objects, health, poses);
    return visionStatus;
  } catch (error) {
    renderVisionStatus({ status: "ERROR", error: error.message, metrics: null }, [], null, []);
    return null;
  } finally {
    liveStatusRefreshInFlight = false;
  }
}

function renderVisionStatus(visionStatus, objects, health, poses = []) {
  const metrics = visionStatus?.metrics || {};
  const status = visionStatus?.status || "STOPPED";
  const mapping = visionStatus?.components?.mapping || {};
  updateModeButtons(status, mapping);
  const visionBadge = document.querySelector("#live-vision-status");
  const detectionSummary = document.querySelector("#live-detection-summary");
  if (visionBadge) {
    visionBadge.textContent = status === "RUNNING" ? "VISION ON" : status;
    visionBadge.dataset.status = status === "RUNNING" ? "ONLINE" : status === "ERROR" ? "OFFLINE" : "DEGRADED";
  }
  if (detectionSummary) {
    detectionSummary.textContent = `${status} · ${objects.length} objeto(s) · ${poses.length} pose(s)`;
  }
  setText("#live-camera-fps", health?.approximate_fps ?? metrics.camera_fps ?? "0");
  setText("#live-vision-fps", metrics.vision_fps ?? "0");
  setText("#live-frame-count", `${metrics.frames_processed ?? 0}/${metrics.frames_received ?? 0}`);
  setText("#live-mapping-state", mappingLabel(mapping));
  const error = visionStatus?.error || mapping.error;
  const errorLine = document.querySelector("#live-error-line");
  if (errorLine) {
    errorLine.textContent = error || "Sem erros";
    errorLine.dataset.state = error ? "error" : "ok";
  }
}

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) {
    element.textContent = value;
  }
}

function updateModeButtons(status, mapping) {
  const visionButton = document.querySelector("#live-toggle-vision");
  if (visionButton) {
    const visionOn = ["STARTING", "RUNNING", "RECOVER"].includes(status);
    visionButton.dataset.active = String(visionOn);
    visionButton.textContent = `Vision: ${visionOn ? "ON" : "OFF"}`;
  }

  const mappingButton = document.querySelector("#live-toggle-mapping");
  if (mappingButton && mappingButton.dataset.loading !== "true") {
    const mappingOn = mapping.state === "ACTIVE";
    mappingButton.dataset.active = String(mappingOn);
    mappingButton.textContent = `Mapeamento: ${mappingOn ? "ON" : "OFF"}`;
    mappingButton.dataset.status = mapping.state || "STOPPED";
  }
}

function mappingLabel(mapping) {
  if (mapping.error) {
    return `ERRO: ${mapping.error}`;
  }
  if (mapping.state === "ACTIVE" && !mapping.poses) {
    return "ACTIVE, aguardando corpo";
  }
  return mapping.state || "STOPPED";
}

function mappingEmptyMessage(mapping) {
  if (mapping.error) {
    return mapping.error;
  }
  if (mapping.state === "ACTIVE") {
    return "Modelo ativo. Aguarde uma pessoa visivel no stream.";
  }
  return "Ligue Mapeamento para desenhar os pontos do corpo.";
}

function statusLabel(status) {
  return status || "OFFLINE";
}

function sourceTypeLabel(type) {
  return {
    webcam: "Webcam",
    video_file: "Arquivo",
    rtsp: "RTSP",
    ip_camera: "IP/HTTP",
  }[type] || type;
}

function cameraMeta(camera) {
  const health = camera.health || {};
  const resolution = health.resolution ? `${health.resolution.width}x${health.resolution.height}` : "sem resolução";
  const fps = health.approximate_fps ? `${Number(health.approximate_fps).toFixed(1)} FPS` : "FPS indisponível";
  const lastFrame = health.last_successful_frame ? formatDate(health.last_successful_frame) : "sem frame";
  return `${sourceTypeLabel(camera.source_type)} · ${fps} · ${resolution} · último frame ${lastFrame}`;
}

function cameraRows(cameras) {
  if (!cameras.length) {
    return `
      <div class="empty-state">
        <strong>Nenhuma câmera cadastrada</strong>
        <span>Cadastre webcam, MP4, RTSP ou câmera IP para iniciar a operação.</span>
        <button type="button" data-empty-action="add-camera">Adicionar câmera</button>
      </div>
    `;
  }

  return cameras
    .map(
      (camera) => `
        <article class="camera-row" data-camera-id="${camera.id}">
          <div>
            <strong>${camera.name}</strong>
            <span>${cameraMeta(camera)}</span>
            <small>${camera.source_uri}${camera.health?.last_error ? ` · ${camera.health.last_error}` : ""}</small>
          </div>
          <span class="health-badge" data-status="${statusLabel(camera.health?.status || camera.status)}">${statusLabel(camera.health?.status || camera.status)}</span>
          <label class="inline-toggle">
            <input type="checkbox" data-action="toggle-enabled" ${camera.enabled ? "checked" : ""} />
            Ativa
          </label>
          <div class="row-actions">
            <button type="button" data-action="edit">Editar</button>
            <button type="button" data-action="test">Testar</button>
            <button type="button" data-action="diagnostics">Diagnóstico</button>
            <button type="button" data-action="delete">Excluir</button>
          </div>
          <pre class="camera-result" hidden></pre>
        </article>
      `
    )
    .join("");
}

async function renderCamerasPage() {
  appView.innerHTML = `
    <div class="camera-admin">
      <section class="camera-list-panel">
        <div class="section-heading">
          <h2>Câmeras cadastradas</h2>
          <div class="section-actions">
            <button type="button" id="add-camera"><i data-lucide="plus" aria-hidden="true"></i><span>Adicionar câmera</span></button>
            <button type="button" id="refresh-cameras"><i data-lucide="refresh-cw" aria-hidden="true"></i><span>Atualizar</span></button>
          </div>
        </div>
        <div id="camera-list" class="camera-list">Carregando câmeras...</div>
      </section>
      <section class="modal-layer" id="camera-modal" aria-labelledby="camera-modal-title" aria-modal="true" role="dialog" hidden>
        <div class="modal-backdrop" data-close-modal></div>
        <div class="modal-window">
          <header class="modal-header">
            <div>
              <p class="eyebrow">Nova fonte de vídeo</p>
              <h2 id="camera-modal-title">Adicionar câmera</h2>
            </div>
            <button type="button" class="icon-button" id="close-camera-modal" aria-label="Fechar janela">
              <i data-lucide="x" aria-hidden="true"></i>
            </button>
          </header>
          <form id="camera-form" class="modal-form">
            <input type="hidden" name="camera_id" />
            <label>
              Nome
              <input name="name" required maxlength="120" placeholder="Entrada principal" />
            </label>
            <label>
              Tipo da fonte
              <select name="source_type">
                <option value="webcam">Webcam</option>
                <option value="video_file">Arquivo de vídeo</option>
                <option value="rtsp">RTSP</option>
                <option value="ip_camera">Câmera IP / HTTP</option>
              </select>
            </label>
            <label>
              Fonte
              <input name="source_uri" required maxlength="1000" placeholder="0, /caminho/video.mp4, rtsp://... ou http://ip/stream" />
            </label>
            <label>
              Área opcional
              <input name="area_id" maxlength="80" placeholder="entrada" />
            </label>
            <div class="form-options">
              <label class="inline-toggle">
                <input name="enabled" type="checkbox" checked />
                Ativa
              </label>
              <label class="inline-toggle">
                <input name="vision_enabled" type="checkbox" />
                Vision habilitada quando existir
              </label>
            </div>
            <div id="camera-test-result" class="modal-test-result" hidden></div>
            <img id="camera-preview" class="camera-preview" alt="Preview da câmera" hidden />
            <footer class="modal-actions">
              <button type="button" id="test-camera-source"><i data-lucide="radio" aria-hidden="true"></i><span>Testar conexão</span></button>
              <button type="button" id="cancel-camera-modal">Cancelar</button>
              <button type="submit" class="primary-action">Salvar câmera</button>
            </footer>
          </form>
        </div>
      </section>
    </div>
  `;

  document.querySelector("#add-camera").addEventListener("click", openCameraModal);
  document.querySelector("#close-camera-modal").addEventListener("click", closeCameraModal);
  document.querySelector("#cancel-camera-modal").addEventListener("click", closeCameraModal);
  document.querySelector("#camera-modal [data-close-modal]").addEventListener("click", closeCameraModal);
  document.querySelector("#test-camera-source").addEventListener("click", handleTestCameraSource);
  document.querySelector("#camera-form").addEventListener("submit", handleCameraSubmit);
  document.querySelector("#refresh-cameras").addEventListener("click", loadCameras);
  refreshIcons();
  await loadCameras();
}

function openCameraModal() {
  const modal = document.querySelector("#camera-modal");
  const form = document.querySelector("#camera-form");
  if (!modal || !form) return;
  editingCameraId = null;
  form.reset();
  form.elements.enabled.checked = true;
  form.elements.camera_id.value = "";
  document.querySelector("#camera-modal-title").textContent = "Adicionar câmera";
  clearCameraTestResult();
  modal.hidden = false;
  document.body.dataset.modalOpen = "true";
  refreshIcons();
  requestAnimationFrame(() => form.elements.name.focus());
}

function openCameraEditModal(cameraId) {
  const camera = camerasCache.find((item) => item.id === cameraId);
  const modal = document.querySelector("#camera-modal");
  const form = document.querySelector("#camera-form");
  if (!camera || !modal || !form) return;
  editingCameraId = camera.id;
  form.elements.camera_id.value = camera.id;
  form.elements.name.value = camera.name || "";
  form.elements.source_type.value = camera.source_type;
  form.elements.source_uri.value = camera.source_uri || "";
  form.elements.area_id.value = camera.area_id || "";
  form.elements.enabled.checked = Boolean(camera.enabled);
  form.elements.vision_enabled.checked = Boolean(camera.vision_enabled);
  document.querySelector("#camera-modal-title").textContent = "Editar câmera";
  clearCameraTestResult();
  const preview = document.querySelector("#camera-preview");
  if (preview) {
    preview.src = cameraSnapshotUrl(camera.id);
    preview.hidden = false;
  }
  modal.hidden = false;
  document.body.dataset.modalOpen = "true";
  refreshIcons();
  requestAnimationFrame(() => form.elements.name.focus());
}

function closeCameraModal() {
  const modal = document.querySelector("#camera-modal");
  if (!modal) return;
  modal.hidden = true;
  editingCameraId = null;
  delete document.body.dataset.modalOpen;
}

function clearCameraTestResult() {
  const result = document.querySelector("#camera-test-result");
  const preview = document.querySelector("#camera-preview");
  if (result) {
    result.hidden = true;
    result.textContent = "";
    result.dataset.state = "";
  }
  if (preview) {
    preview.hidden = true;
    preview.removeAttribute("src");
  }
}

function cameraPayloadFromForm(form) {
  const data = new FormData(form);
  return {
    name: data.get("name").trim(),
    source_type: data.get("source_type"),
    source_uri: data.get("source_uri").trim(),
    area_id: data.get("area_id").trim() || null,
    enabled: data.get("enabled") === "on",
    vision_enabled: data.get("vision_enabled") === "on",
  };
}

async function loadCameras() {
  const listElement = document.querySelector("#camera-list");
  try {
    const cameras = await listCameras();
    camerasCache = await Promise.all(
      cameras.map(async (camera) => {
        try {
          return { ...camera, health: await getCameraHealth(camera.id) };
        } catch {
          return { ...camera, health: { status: camera.status || "OFFLINE" } };
        }
      })
    );
    listElement.innerHTML = cameraRows(camerasCache);
    listElement.querySelector("[data-empty-action='add-camera']")?.addEventListener("click", openCameraModal);
    listElement.querySelectorAll(".camera-row").forEach((row) => {
      row.addEventListener("click", handleCameraAction);
      row
        .querySelector("[data-action='toggle-enabled']")
        .addEventListener("change", handleEnabledChange);
    });
  } catch (error) {
    listElement.innerHTML = `<div class="empty-state"><strong>Falha ao carregar câmeras</strong><span>${error.message}</span></div>`;
  }
}

async function handleCameraSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = cameraPayloadFromForm(form);

  try {
    const camera = editingCameraId
      ? await updateCamera(editingCameraId, payload)
      : await createCamera(payload);
    notify(
      editingCameraId ? "Câmera atualizada" : "Câmera cadastrada",
      `${camera.name} está pronta para operação.`,
      "success"
    );
    form.reset();
    form.elements.enabled.checked = true;
    closeCameraModal();
    await loadCameras();
  } catch (error) {
    notifyError("Falha ao cadastrar câmera", error);
  }
}

async function handleTestCameraSource() {
  const form = document.querySelector("#camera-form");
  const result = document.querySelector("#camera-test-result");
  const preview = document.querySelector("#camera-preview");
  if (!form || !result) return;
  result.hidden = false;
  result.dataset.state = "loading";
  result.textContent = "Testando conexão e aguardando frame válido...";
  if (preview) {
    preview.hidden = true;
    preview.removeAttribute("src");
  }
  try {
    const payload = cameraPayloadFromForm(form);
    const response = await testCameraSource(payload);
    result.dataset.state = response.success ? "success" : "error";
    const resolution = response.resolution ? `${response.resolution.width}x${response.resolution.height}` : "sem resolução";
    result.textContent = response.success
      ? `Conexão OK · ${resolution}`
      : `Falha no teste: ${response.error || response.status}`;
    if (preview && response.preview_data_url) {
      preview.src = response.preview_data_url;
      preview.hidden = false;
    }
  } catch (error) {
    result.dataset.state = "error";
    result.textContent = error.message;
  }
}

async function handleEnabledChange(event) {
  const row = event.currentTarget.closest(".camera-row");
  const enabled = event.currentTarget.checked;
  try {
    await updateCamera(row.dataset.cameraId, { enabled });
    notify(enabled ? "Câmera ativada" : "Câmera pausada", "Estado atualizado com sucesso.", enabled ? "success" : "warning");
    await loadCameras();
  } catch (error) {
    notifyError("Falha ao atualizar câmera", error);
  }
}

async function handleCameraAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }

  const row = button.closest(".camera-row");
  const result = row.querySelector(".camera-result");
  const cameraId = row.dataset.cameraId;
  const action = button.dataset.action;

  try {
    if (action === "edit") {
      openCameraEditModal(cameraId);
      return;
    }

    if (action === "delete") {
      await deleteCamera(cameraId);
      notify("Câmera removida", "A fonte foi excluída do sistema.", "warning");
      await loadCameras();
      return;
    }

    const response =
      action === "test"
        ? await testCamera(cameraId)
        : action === "diagnostics"
          ? await getCameraDiagnostics(cameraId)
          : await getCameraHealth(cameraId);
    result.hidden = false;
    result.textContent = JSON.stringify(response, null, 2);
    if (action === "test") {
      notify("Teste de câmera concluído", response.status || "Conexão verificada.", "success");
    } else if (action === "diagnostics") {
      notify("Diagnóstico carregado", "Health, frames e Vision foram consultados.", "info");
    } else {
      notify("Saúde da câmera", response.status || "Status atualizado.", response.status === "ONLINE" ? "success" : "warning");
    }
  } catch (error) {
    result.hidden = false;
    result.textContent = error.message;
    notifyError("Falha na ação da câmera", error);
  }
}

async function renderEventsPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-toolbar">
        <label>Status
          <select id="event-status-filter">
            <option value="">Todos</option>
            <option value="OPEN">Abertos</option>
            <option value="REVIEWED">Revisados</option>
            <option value="CLOSED">Fechados</option>
          </select>
        </label>
        <label>Câmera
          <select id="event-camera-filter"><option value="">Todas</option></select>
        </label>
        <label>Tipo
          <input id="event-type-filter" placeholder="PERSON_RESTRICTED_ZONE" />
        </label>
        <button type="button" id="event-refresh">Atualizar</button>
      </section>
      <section class="ops-grid">
        <div>
          <div class="section-heading"><h2>Fila de eventos</h2><span id="event-count">0</span></div>
          <div id="event-list" class="ops-list"></div>
        </div>
        <aside class="ops-detail">
          <h2>Evento selecionado</h2>
          <div id="event-detail">${emptyState("Selecione um evento", "Abra detalhes para revisar contexto e evidência.")}</div>
          <h2>Resumo</h2>
          <dl id="event-summary" class="metric-list"></dl>
        </aside>
      </section>
    </div>
  `;
  document.querySelector("#event-refresh").addEventListener("click", loadEvents);
  ["#event-status-filter", "#event-camera-filter", "#event-type-filter"].forEach((selector) => {
    document.querySelector(selector).addEventListener("change", loadEvents);
    document.querySelector(selector).addEventListener("input", debounce(loadEvents, 250));
  });
  await populateCameraSelect("#event-camera-filter", true);
  await loadEvents();
}

async function loadEvents() {
  const list = document.querySelector("#event-list");
  const params = {
    status: document.querySelector("#event-status-filter")?.value,
    camera_id: document.querySelector("#event-camera-filter")?.value,
    event_type: document.querySelector("#event-type-filter")?.value?.trim(),
    limit: 300,
  };
  try {
    const [events, cameras, zones] = await Promise.all([listEvents(params), listCameras(), listZones()]);
    const cameraById = Object.fromEntries(cameras.map((camera) => [camera.id, camera]));
    const zoneById = Object.fromEntries(zones.map((zone) => [zone.id, zone]));
    document.querySelector("#event-count").textContent = `${events.length} eventos`;
    list.innerHTML = events.length
      ? events.map((event) => eventRow(event, cameraById, zoneById)).join("")
      : emptyState("Nenhum evento encontrado", "Ajuste os filtros ou gere eventos entrando em uma zona.");
    list.querySelectorAll("[data-event-action]").forEach((button) => {
      button.addEventListener("click", handleEventAction);
    });
    renderEventSummary(events);
  } catch (error) {
    list.innerHTML = emptyState("Falha ao carregar eventos", error.message);
  }
}

function eventRow(event, cameraById, zoneById) {
  const camera = cameraById[event.camera_id];
  const zone = event.zone_id ? zoneById[event.zone_id] : null;
  const category = event.metadata?.facts?.activity?.category || "other";
  return `
    <article class="ops-row" data-event-id="${event.id}">
      <div>
        <strong>${event.type}</strong>
        <span>${category} · ${camera?.name || event.camera_id} · ${zone?.name || event.zone_id || "sem zona"} · track ${event.track_id ?? "-"}</span>
        <small>${formatDate(event.started_at)} · ${event.confidence ? Math.round(event.confidence * 100) : "-"}%</small>
      </div>
      <span class="severity-badge" data-severity="${event.severity}">${event.severity}</span>
      <span class="health-badge" data-status="${event.status}">${event.status}</span>
      <div class="row-actions">
        <button type="button" data-event-action="review">Revisar</button>
        <button type="button" data-event-action="close">Fechar</button>
        <button type="button" data-event-action="details">Detalhes</button>
        <button type="button" data-event-action="investigate">Investigar</button>
        <button type="button" data-event-action="delete">Excluir</button>
      </div>
    </article>
  `;
}

async function handleEventAction(event) {
  const button = event.currentTarget;
  const row = button.closest("[data-event-id]");
  const eventId = row.dataset.eventId;
  const action = button.dataset.eventAction;
  if (action === "review") {
    await updateEvent(eventId, { status: "REVIEWED" });
  } else if (action === "close") {
    await updateEvent(eventId, { status: "CLOSED" });
  } else if (action === "investigate") {
    await createInvestigationFromEvent(eventId);
    window.location.hash = "investigations";
    return;
  } else if (action === "details") {
    await showEventDetail(eventId);
    return;
  } else if (action === "delete") {
    await deleteEvent(eventId);
  }
  await loadEvents();
}

async function showEventDetail(eventId) {
  const [events, cameras, zones] = await Promise.all([
    listEvents({ limit: 1000 }),
    listCameras(),
    listZones(),
  ]);
  const event = events.find((item) => item.id === eventId);
  if (!event) return;
  const camera = cameras.find((item) => item.id === event.camera_id);
  const zone = zones.find((item) => item.id === event.zone_id);
  const hasEvidence = Boolean(event.metadata?.overlay_path);
  const category = event.metadata?.facts?.activity?.category || "other";
  document.querySelector("#event-detail").innerHTML = `
    <div class="event-detail-panel">
      ${hasEvidence ? `<img class="event-evidence" src="${eventEvidenceUrl(event.id)}" alt="Evidência do evento ${event.id}" />` : ""}
      <dl class="metric-list">
        <dt>ID</dt><dd>${event.id}</dd>
        <dt>Tipo</dt><dd>${event.type}</dd>
        <dt>Categoria</dt><dd>${category}</dd>
        <dt>Câmera</dt><dd>${camera?.name || event.camera_id}</dd>
        <dt>Zona</dt><dd>${zone?.name || event.zone_id || "-"}</dd>
        <dt>Track</dt><dd>${event.track_id ?? "-"}</dd>
        <dt>Status</dt><dd>${event.status}</dd>
        <dt>Início</dt><dd>${formatDate(event.started_at)}</dd>
        <dt>Evidência</dt><dd>${hasEvidence ? "salva" : "não disponível"}</dd>
      </dl>
      <pre class="code-block">${JSON.stringify(event.metadata || {}, null, 2)}</pre>
    </div>
  `;
}

function renderEventSummary(events) {
  const open = events.filter((event) => event.status === "OPEN").length;
  const critical = events.filter((event) => event.severity === "critical").length;
  const types = new Set(events.map((event) => event.type)).size;
  document.querySelector("#event-summary").innerHTML = `
    <dt>Total</dt><dd>${events.length}</dd>
    <dt>Abertos</dt><dd>${open}</dd>
    <dt>Críticos</dt><dd>${critical}</dd>
    <dt>Tipos</dt><dd>${types}</dd>
  `;
}

async function renderInvestigationsPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-toolbar">
        <button type="button" id="new-investigation">Nova investigação</button>
        <button type="button" id="clear-closed-investigations">Limpar fechadas</button>
      </section>
      <section class="ops-grid">
        <div>
          <div class="section-heading"><h2>Investigações</h2><span id="investigation-count">0</span></div>
          <div id="investigation-list" class="ops-list"></div>
        </div>
        <aside class="ops-detail">
          <h2>Workspace</h2>
          <form id="investigation-form" class="stack-form">
            <label>Título<input name="title" required placeholder="Pessoa em zona restrita" /></label>
            <label>Status
              <select name="status">
                <option value="OPEN">Aberta</option>
                <option value="REVIEWING">Em revisão</option>
                <option value="CLOSED">Fechada</option>
              </select>
            </label>
            <label>Evento relacionado<input name="event_id" placeholder="evt_..." /></label>
            <label>Notas<textarea name="notes" rows="8" placeholder="Hipótese, contexto, próximos passos..."></textarea></label>
            <button type="submit">Salvar investigação</button>
          </form>
        </aside>
      </section>
    </div>
  `;
  document.querySelector("#new-investigation").addEventListener("click", () => fillInvestigationForm());
  document.querySelector("#clear-closed-investigations").addEventListener("click", clearClosedInvestigations);
  document.querySelector("#investigation-form").addEventListener("submit", saveInvestigation);
  await renderInvestigations();
}

async function createInvestigationFromEvent(eventId) {
  const items = await listInvestigations();
  if (items.some((item) => item.event_id === eventId)) {
    return;
  }
  await createInvestigation({
    title: `Investigação ${eventId}`,
    status: "OPEN",
    event_id: eventId,
    notes: "",
  });
}

async function renderInvestigations() {
  const items = await listInvestigations();
  document.querySelector("#investigation-count").textContent = `${items.length} casos`;
  document.querySelector("#investigation-list").innerHTML = items.length
    ? items.map((item) => `
      <article class="ops-row" data-investigation-id="${item.id}">
        <div>
          <strong>${item.title}</strong>
          <span>${item.event_id || "sem evento"} · ${formatDate(item.updated_at)}</span>
          <small>${item.notes ? item.notes.slice(0, 120) : "sem notas"}</small>
        </div>
        <span class="health-badge" data-status="${item.status}">${item.status}</span>
        <div class="row-actions">
          <button type="button" data-investigation-action="edit">Abrir</button>
          <button type="button" data-investigation-action="close">Fechar</button>
          <button type="button" data-investigation-action="delete">Excluir</button>
        </div>
      </article>
    `).join("")
    : emptyState("Nenhuma investigação", "Crie manualmente ou envie um evento para investigação.");
  document.querySelectorAll("[data-investigation-action]").forEach((button) => {
    button.addEventListener("click", handleInvestigationAction);
  });
}

function fillInvestigationForm(item = null) {
  const form = document.querySelector("#investigation-form");
  form.dataset.investigationId = item?.id || "";
  form.elements.title.value = item?.title || "";
  form.elements.status.value = item?.status || "OPEN";
  form.elements.event_id.value = item?.event_id || "";
  form.elements.notes.value = item?.notes || "";
}

async function saveInvestigation(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.dataset.investigationId;
  const payload = {
    title: form.elements.title.value.trim(),
    status: form.elements.status.value,
    event_id: form.elements.event_id.value.trim(),
    notes: form.elements.notes.value.trim(),
  };
  if (id) {
    await updateInvestigation(id, payload);
  } else {
    await createInvestigation(payload);
  }
  fillInvestigationForm();
  await renderInvestigations();
}

async function handleInvestigationAction(event) {
  const row = event.currentTarget.closest("[data-investigation-id]");
  const id = row.dataset.investigationId;
  const action = event.currentTarget.dataset.investigationAction;
  const items = await listInvestigations();
  const item = items.find((entry) => entry.id === id);
  if (!item) return;
  if (action === "edit") {
    fillInvestigationForm(item);
  } else if (action === "close") {
    await updateInvestigation(id, { status: "CLOSED" });
  } else if (action === "delete") {
    await deleteInvestigation(id);
  }
  await renderInvestigations();
}

async function clearClosedInvestigations() {
  const items = await listInvestigations({ status: "CLOSED" });
  await Promise.all(items.map((item) => deleteInvestigation(item.id)));
  await renderInvestigations();
}

async function renderZonesPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-toolbar">
        <label>Câmera<select id="zone-camera-select"></select></label>
        <button type="button" id="zone-refresh">Atualizar</button>
      </section>
      <section class="ops-grid">
        <div>
          <div class="section-heading"><h2>Áreas & zonas</h2><span id="zone-count">0</span></div>
          <div id="area-summary" class="system-strip compact-strip"></div>
          <div class="zone-designer">
            <div class="zone-designer-header">
              <strong id="zone-designer-title">Desenho da câmera</strong>
              <span id="zone-draw-status">Clique na imagem para adicionar pontos</span>
            </div>
            <div id="zone-media-host" class="zone-media-host">
              <div class="media-placeholder">Selecione uma câmera</div>
            </div>
            <div class="zone-draw-tools">
              <button type="button" id="zone-undo-point">Desfazer ponto</button>
              <button type="button" id="zone-clear-points">Limpar desenho</button>
              <button type="button" id="zone-use-full-frame">Quadro inteiro</button>
            </div>
          </div>
          <div id="zone-list" class="ops-list"></div>
        </div>
        <aside class="ops-detail">
          <h2>Nova zona</h2>
          <form id="zone-form" class="stack-form">
            <label>Nome<input name="name" required placeholder="Porta principal" /></label>
            <label>Tipo
              <select name="type">
                <option value="monitored">Monitorada</option>
                <option value="restricted">Restrita</option>
              </select>
            </label>
            <label>Pontos normalizados
              <textarea name="points" rows="6">[]</textarea>
            </label>
            <label class="inline-toggle"><input name="enabled" type="checkbox" checked /> Ativa</label>
            <button type="submit">Salvar zona</button>
          </form>
        </aside>
      </section>
    </div>
  `;
  await populateCameraSelect("#zone-camera-select", false);
  document.querySelector("#zone-camera-select").addEventListener("change", loadZonesPageData);
  document.querySelector("#zone-refresh").addEventListener("click", loadZonesPageData);
  document.querySelector("#zone-form").addEventListener("submit", saveZone);
  document.querySelector("#zone-form").elements.points.addEventListener("input", syncZonePointsFromTextarea);
  document.querySelector("#zone-form").elements.type.addEventListener("change", drawZoneCanvas);
  document.querySelector("#zone-undo-point").addEventListener("click", undoZonePoint);
  document.querySelector("#zone-clear-points").addEventListener("click", clearZoneDrawing);
  document.querySelector("#zone-use-full-frame").addEventListener("click", useFullFrameZone);
  await loadZonesPageData();
}

async function loadZonesPageData() {
  const cameraId = document.querySelector("#zone-camera-select")?.value;
  const [cameras, zones] = await Promise.all([listCameras(), listZones(cameraId)]);
  const selectedCamera = cameras.find((camera) => camera.id === cameraId);
  zonePreviewZones = zones;
  renderAreaSummary(cameras, zones);
  renderZoneMedia(selectedCamera);
  document.querySelector("#zone-count").textContent = `${zones.length} zonas`;
  document.querySelector("#zone-list").innerHTML = zones.length
    ? zones.map((zone) => zoneRow(zone, selectedCamera)).join("")
    : emptyState("Nenhuma zona cadastrada", "Crie uma zona com pontos normalizados entre 0 e 1.");
  document.querySelectorAll("[data-zone-action]").forEach((button) => {
    button.addEventListener("click", handleZoneAction);
  });
  drawZoneCanvas();
}

function renderAreaSummary(cameras, zones) {
  const areaIds = [...new Set(cameras.map((camera) => camera.area_id || "sem_area"))];
  document.querySelector("#area-summary").innerHTML = areaIds.map((areaId) => {
    const areaCameras = cameras.filter((camera) => (camera.area_id || "sem_area") === areaId);
    return `
      <div class="system-cell">
        <span>${areaId === "sem_area" ? "Sem área" : areaId}</span>
        <strong>${areaCameras.length} câmeras · ${zones.length} zonas visíveis</strong>
      </div>
    `;
  }).join("");
}

function zoneRow(zone, camera) {
  return `
    <article class="ops-row" data-zone-id="${zone.id}">
      <div>
        <strong>${zone.name}</strong>
        <span>${camera?.name || zone.camera_id} · ${zone.points.length} pontos</span>
        <small>${zone.points.map((point) => `[${point.join(", ")}]`).join(" ")}</small>
      </div>
      <span class="severity-badge" data-severity="${zone.type === "restricted" ? "critical" : "attention"}">${zone.type}</span>
      <label class="inline-toggle"><input type="checkbox" data-zone-action="toggle" ${zone.enabled ? "checked" : ""} /> Ativa</label>
      <div class="row-actions"><button type="button" data-zone-action="delete">Excluir</button></div>
    </article>
  `;
}

function renderZoneMedia(camera) {
  const host = document.querySelector("#zone-media-host");
  document.querySelector("#zone-designer-title").textContent = camera?.name || "Desenho da câmera";
  if (!camera?.id) {
    host.innerHTML = `<div class="media-placeholder">Cadastre ou selecione uma câmera</div>`;
    return;
  }

  const source = camera.source_type === "video_file" ? cameraVideoUrl(camera.id) : cameraStreamUrl(camera.id);
  const media = camera.source_type === "video_file"
    ? `<video id="zone-media" class="zone-media" src="${source}" autoplay muted playsinline loop controls></video>`
    : `<img id="zone-media" class="zone-media" src="${source}" alt="Preview da câmera" />`;

  host.innerHTML = `
    ${media}
    <canvas id="zone-draw-canvas" class="zone-draw-canvas" aria-label="Desenho de zona"></canvas>
  `;
  const canvas = document.querySelector("#zone-draw-canvas");
  canvas.addEventListener("pointerdown", addZonePoint);
  window.addEventListener("resize", drawZoneCanvas, { once: true });
  setTimeout(drawZoneCanvas, 80);
}

function addZonePoint(event) {
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const x = clamp01((event.clientX - rect.left) / rect.width);
  const y = clamp01((event.clientY - rect.top) / rect.height);
  zoneDrawingPoints.push([roundPoint(x), roundPoint(y)]);
  updateZonePointsField();
  drawZoneCanvas();
}

function syncZonePointsFromTextarea() {
  const form = document.querySelector("#zone-form");
  try {
    const parsed = JSON.parse(form.elements.points.value);
    if (Array.isArray(parsed)) {
      zoneDrawingPoints = parsed
        .filter((point) => Array.isArray(point) && point.length === 2)
        .map((point) => [clamp01(Number(point[0])), clamp01(Number(point[1]))]);
      drawZoneCanvas();
    }
  } catch {
    updateZoneDrawStatus("JSON inválido nos pontos");
  }
}

function updateZonePointsField() {
  const form = document.querySelector("#zone-form");
  form.elements.points.value = JSON.stringify(zoneDrawingPoints);
  updateZoneDrawStatus();
}

function undoZonePoint() {
  zoneDrawingPoints.pop();
  updateZonePointsField();
  drawZoneCanvas();
}

function clearZoneDrawing() {
  zoneDrawingPoints = [];
  updateZonePointsField();
  drawZoneCanvas();
}

function useFullFrameZone() {
  zoneDrawingPoints = [[0.05, 0.05], [0.95, 0.05], [0.95, 0.95], [0.05, 0.95]];
  updateZonePointsField();
  drawZoneCanvas();
}

function updateZoneDrawStatus(message = "") {
  const status = document.querySelector("#zone-draw-status");
  if (!status) return;
  status.textContent = message || (
    zoneDrawingPoints.length < 3
      ? `${zoneDrawingPoints.length} ponto(s). Marque pelo menos 3.`
      : `${zoneDrawingPoints.length} pontos prontos para salvar.`
  );
}

function drawZoneCanvas() {
  const canvas = document.querySelector("#zone-draw-canvas");
  const host = document.querySelector("#zone-media-host");
  if (!canvas || !host) return;
  const rect = host.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${rect.height}px`;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  zonePreviewZones.forEach((zone) => drawZonePolygon(ctx, zone.points, rect, zone.type, false));
  drawZonePolygon(ctx, zoneDrawingPoints, rect, document.querySelector("#zone-form")?.elements.type.value || "restricted", true);
  updateZoneDrawStatus();
}

function drawZonePolygon(ctx, points, rect, type, editing) {
  if (!points?.length) return;
  const color = type === "restricted" ? "#ff4d4d" : "#f0c94a";
  ctx.lineWidth = editing ? 3 : 2;
  ctx.strokeStyle = color;
  ctx.fillStyle = editing ? "rgba(255, 77, 77, 0.22)" : "rgba(240, 201, 74, 0.12)";
  ctx.beginPath();
  points.forEach(([x, y], index) => {
    const px = Number(x) * rect.width;
    const py = Number(y) * rect.height;
    if (index === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  if (points.length >= 3) {
    ctx.closePath();
    ctx.fill();
  }
  ctx.stroke();
  points.forEach(([x, y], index) => {
    const px = Number(x) * rect.width;
    const py = Number(y) * rect.height;
    ctx.beginPath();
    ctx.arc(px, py, editing ? 5 : 3, 0, Math.PI * 2);
    ctx.fillStyle = editing ? "#ffffff" : color;
    ctx.fill();
    if (editing) {
      ctx.fillStyle = "#050505";
      ctx.font = "10px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(index + 1), px, py);
    }
  });
}

function clamp01(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

function roundPoint(value) {
  return Math.round(value * 10000) / 10000;
}

async function saveZone(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const cameraId = document.querySelector("#zone-camera-select")?.value;
  if (!cameraId) return;
  let points;
  try {
    points = JSON.parse(form.elements.points.value);
  } catch {
    notify("Pontos inválidos", "Use JSON como [[0.1,0.1],[0.9,0.1],[0.9,0.9]].", "error");
    return;
  }
  if (!Array.isArray(points) || points.length < 3) {
    notify("Zona incompleta", "Desenhe pelo menos 3 pontos na imagem.", "warning");
    return;
  }
  await createZone({
    camera_id: cameraId,
    name: form.elements.name.value.trim(),
    type: form.elements.type.value,
    enabled: form.elements.enabled.checked,
    points,
  });
  form.reset();
  zoneDrawingPoints = [];
  form.elements.points.value = "[]";
  form.elements.enabled.checked = true;
  await loadZonesPageData();
  notify("Zona salva", "A zona foi cadastrada para essa câmera.", "success");
}

async function handleZoneAction(event) {
  const row = event.currentTarget.closest("[data-zone-id]");
  const zoneId = row.dataset.zoneId;
  const action = event.currentTarget.dataset.zoneAction;
  if (action === "delete") {
    await deleteZone(zoneId);
  } else if (action === "toggle") {
    await updateZone(zoneId, { enabled: event.currentTarget.checked });
  }
  await loadZonesPageData();
}

async function renderMachinesPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-toolbar">
        <label>Câmera<select id="machine-camera-select"></select></label>
        <button type="button" id="machine-refresh">Atualizar</button>
      </section>
      <section class="ops-grid">
        <div>
          <div class="section-heading">
            <h2>Máquinas mapeadas</h2>
            <div class="section-actions">
              <button type="button" id="add-machine"><i data-lucide="plus" aria-hidden="true"></i><span>Adicionar máquina</span></button>
              <span id="machine-count">0</span>
            </div>
          </div>
          <div class="zone-designer">
            <div class="zone-designer-header">
              <strong id="machine-designer-title">Desenho da câmera</strong>
              <span id="machine-draw-status">Clique na imagem para marcar a máquina</span>
            </div>
            <div id="machine-media-host" class="zone-media-host">
              <div class="media-placeholder">Selecione uma câmera</div>
            </div>
            <div class="zone-draw-tools">
              <button type="button" id="machine-detect-click" class="mode-toggle" data-active="false">Detectar pelo clique</button>
              <button type="button" id="machine-undo-point">Desfazer ponto</button>
              <button type="button" id="machine-clear-points">Limpar desenho</button>
              <button type="button" id="machine-use-full-frame">Quadro inteiro</button>
            </div>
          </div>
          <div id="machine-list" class="ops-list"></div>
        </div>
        <aside class="ops-detail">
          <h2>Mapeamento</h2>
          <div class="object-list">
            ${objectLine("Desenho ativo", "Clique no vídeo para marcar pontos", "Depois use Adicionar máquina para salvar como ativo operacional.")}
            ${objectLine("Máquina", "Ativo com identidade", "Diferente de zona: tem tipo, operador esperado e regra de proximidade.")}
          </div>
        </aside>
      </section>
      <section class="modal-layer" id="machine-modal" aria-labelledby="machine-modal-title" aria-modal="true" role="dialog" hidden>
        <div class="modal-backdrop" data-close-modal></div>
        <div class="modal-window">
          <header class="modal-header">
            <div>
              <p class="eyebrow">Ativo operacional</p>
              <h2 id="machine-modal-title">Adicionar máquina</h2>
            </div>
            <button type="button" class="icon-button" id="close-machine-modal" aria-label="Fechar janela">
              <i data-lucide="x" aria-hidden="true"></i>
            </button>
          </header>
          <form id="machine-form" class="modal-form">
            <label>Nome<input name="name" required placeholder="Prensa 01" /></label>
            <label>Tipo
              <select name="type">
                <option value="fixed">Fixa</option>
                <option value="mobile">Móvel</option>
                <option value="vehicle">Veículo</option>
                <option value="conveyor">Esteira</option>
                <option value="robot">Robô</option>
                <option value="other">Outra</option>
              </select>
            </label>
            <label>Pontos normalizados<textarea name="points" rows="6">[]</textarea></label>
            <label>Distância mínima de pessoa<input name="min_person_distance" type="number" min="0" max="1" step="0.01" value="0.08" /></label>
            <label class="inline-toggle"><input name="enabled" type="checkbox" checked /> Ativa</label>
            <label class="inline-toggle"><input name="requires_operator" type="checkbox" checked /> Requer operador</label>
            <label class="inline-toggle"><input name="allow_idle" type="checkbox" /> Pode ficar parada</label>
            <footer class="modal-actions">
              <button type="button" id="cancel-machine-modal">Cancelar</button>
              <button type="submit" class="primary-action">Salvar máquina</button>
            </footer>
          </form>
        </div>
      </section>
    </div>
  `;
  await populateCameraSelect("#machine-camera-select", false);
  document.querySelector("#add-machine").addEventListener("click", openMachineModal);
  document.querySelector("#close-machine-modal").addEventListener("click", closeMachineModal);
  document.querySelector("#cancel-machine-modal").addEventListener("click", closeMachineModal);
  document.querySelector("#machine-modal [data-close-modal]").addEventListener("click", closeMachineModal);
  document.querySelector("#machine-camera-select").addEventListener("change", loadMachinesPageData);
  document.querySelector("#machine-refresh").addEventListener("click", loadMachinesPageData);
  document.querySelector("#machine-form").addEventListener("submit", saveMachine);
  document.querySelector("#machine-form").elements.points.addEventListener("input", syncMachinePointsFromTextarea);
  document.querySelector("#machine-detect-click").addEventListener("click", toggleMachineClickDetect);
  document.querySelector("#machine-undo-point").addEventListener("click", undoMachinePoint);
  document.querySelector("#machine-clear-points").addEventListener("click", clearMachineDrawing);
  document.querySelector("#machine-use-full-frame").addEventListener("click", useFullFrameMachine);
  refreshIcons();
  await loadMachinesPageData();
}

function openMachineModal() {
  const modal = document.querySelector("#machine-modal");
  const form = document.querySelector("#machine-form");
  if (!modal || !form) return;
  form.reset();
  form.elements.points.value = JSON.stringify(machineDrawingPoints);
  form.elements.enabled.checked = true;
  form.elements.requires_operator.checked = true;
  form.elements.allow_idle.checked = false;
  form.elements.min_person_distance.value = 0.08;
  modal.hidden = false;
  document.body.dataset.modalOpen = "true";
  refreshIcons();
  requestAnimationFrame(() => form.elements.name.focus());
}

function closeMachineModal() {
  const modal = document.querySelector("#machine-modal");
  if (!modal) return;
  modal.hidden = true;
  delete document.body.dataset.modalOpen;
}

async function loadMachinesPageData() {
  const cameraId = document.querySelector("#machine-camera-select")?.value;
  const [cameras, machines] = await Promise.all([listCameras(), listMachines(cameraId)]);
  const selectedCamera = cameras.find((camera) => camera.id === cameraId);
  machinePreviewMachines = machines;
  renderMachineMedia(selectedCamera);
  document.querySelector("#machine-count").textContent = `${machines.length} máquinas`;
  document.querySelector("#machine-list").innerHTML = machines.length
    ? machines.map((machine) => machineRow(machine, selectedCamera)).join("")
    : emptyState("Nenhuma máquina mapeada", "Desenhe a área da máquina e salve como ativo operacional.");
  document.querySelectorAll("[data-machine-action]").forEach((button) => {
    button.addEventListener("click", handleMachineAction);
  });
  drawMachineCanvas();
}

function machineRow(machine, camera) {
  return `
    <article class="ops-row" data-machine-id="${machine.id}">
      <div>
        <strong>${machine.name}</strong>
        <span>${camera?.name || machine.camera_id} · ${machine.type} · ${machine.points.length} pontos</span>
        <small>${machine.requires_operator ? "requer operador" : "operador opcional"} · ${machine.allow_idle ? "parada permitida" : "parada monitorada"} · distância ${machine.min_person_distance}</small>
      </div>
      <span class="health-badge" data-status="${machine.enabled ? "ONLINE" : "OFFLINE"}">${machine.enabled ? "ATIVA" : "INATIVA"}</span>
      <label class="inline-toggle"><input type="checkbox" data-machine-action="toggle" ${machine.enabled ? "checked" : ""} /> Ativa</label>
      <div class="row-actions"><button type="button" data-machine-action="delete">Excluir</button></div>
    </article>
  `;
}

function renderMachineMedia(camera) {
  const host = document.querySelector("#machine-media-host");
  document.querySelector("#machine-designer-title").textContent = camera?.name || "Desenho da câmera";
  if (!camera?.id) {
    host.innerHTML = `<div class="media-placeholder">Cadastre ou selecione uma câmera</div>`;
    return;
  }
  const source = camera.source_type === "video_file" ? cameraVideoUrl(camera.id) : cameraStreamUrl(camera.id);
  const media = camera.source_type === "video_file"
    ? `<video id="machine-media" class="zone-media" src="${source}" autoplay muted playsinline loop controls></video>`
    : `<img id="machine-media" class="zone-media" src="${source}" alt="Preview da câmera" />`;
  host.innerHTML = `${media}<canvas id="machine-draw-canvas" class="zone-draw-canvas" aria-label="Desenho de máquina"></canvas>`;
  const canvas = document.querySelector("#machine-draw-canvas");
  canvas.addEventListener("pointerdown", addMachinePoint);
  window.addEventListener("resize", drawMachineCanvas, { once: true });
  setTimeout(drawMachineCanvas, 80);
}

function toggleMachineClickDetect() {
  machineClickDetectMode = !machineClickDetectMode;
  const button = document.querySelector("#machine-detect-click");
  if (button) {
    button.dataset.active = String(machineClickDetectMode);
    button.textContent = machineClickDetectMode ? "Clique para detectar" : "Detectar pelo clique";
  }
  updateMachineDrawStatus(
    machineClickDetectMode
      ? "Clique sobre a máquina para gerar o contorno automaticamente."
      : ""
  );
}

async function addMachinePoint(event) {
  const rect = event.currentTarget.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  if (machineClickDetectMode) {
    await detectMachineFromClick(event, rect);
    return;
  }
  machineDrawingPoints.push([
    roundPoint(clamp01((event.clientX - rect.left) / rect.width)),
    roundPoint(clamp01((event.clientY - rect.top) / rect.height)),
  ]);
  updateMachinePointsField();
  drawMachineCanvas();
}

async function detectMachineFromClick(event, rect) {
  const cameraId = document.querySelector("#machine-camera-select")?.value;
  if (!cameraId) return;
  const click = {
    x: clamp01((event.clientX - rect.left) / rect.width),
    y: clamp01((event.clientY - rect.top) / rect.height),
  };
  updateMachineDrawStatus("Consultando objetos detectados pela Vision...");
  try {
    const objects = await getVisionObjects(cameraId);
    const match = nearestMachineObject(objects, click, rect);
    if (!match) {
      updateMachineDrawStatus("Nenhuma máquina/objeto detectado perto do clique. Ligue Vision e tente novamente.");
      notify("Nenhum objeto encontrado", "A Vision precisa estar ativa e detectar algo próximo do clique.", "warning");
      return;
    }
    machineDrawingPoints = bboxToNormalizedPolygon(match.bounding_box, rect);
    updateMachinePointsField();
    drawMachineCanvas();
    machineClickDetectMode = false;
    const button = document.querySelector("#machine-detect-click");
    if (button) {
      button.dataset.active = "false";
      button.textContent = "Detectar pelo clique";
    }
    notify("Máquina contornada", `${match.class_name} #${match.track_id} foi usado como base.`, "success");
  } catch (error) {
    updateMachineDrawStatus("Falha ao consultar objetos da Vision.");
    notifyError("Falha ao detectar pelo clique", error);
  }
}

function nearestMachineObject(objects, click, rect) {
  const candidates = objects
    .filter((object) => Array.isArray(object.bounding_box) && object.bounding_box.length >= 4)
    .map((object) => {
      const [x1, y1, x2, y2] = object.bounding_box.map(Number);
      const normalized = Math.max(x1, y1, x2, y2) <= 1.5;
      const center = { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
      const normalizedCenter = {
        x: normalized ? center.x : center.x / rect.width,
        y: normalized ? center.y : center.y / rect.height,
      };
      const className = String(object.class_name || "").toLowerCase();
      const priority = machineClassPriority(className);
      return {
        ...object,
        _priority: priority,
        _distance: Math.hypot(normalizedCenter.x - click.x, normalizedCenter.y - click.y),
      };
    })
    .filter((object) => object._distance <= 0.35);
  candidates.sort((a, b) => b._priority - a._priority || a._distance - b._distance);
  return candidates[0] || null;
}

function machineClassPriority(className) {
  if (["forklift", "truck", "car", "bus", "motorcycle", "tractor", "excavator", "crane", "machine", "industrial machine"].includes(className)) {
    return 3;
  }
  if (className !== "person" && className !== "cell phone") {
    return 2;
  }
  return 1;
}

function bboxToNormalizedPolygon(boundingBox, rect) {
  const [rawX1, rawY1, rawX2, rawY2] = boundingBox.map(Number);
  const normalized = Math.max(rawX1, rawY1, rawX2, rawY2) <= 1.5;
  const x1 = normalized ? rawX1 : rawX1 / rect.width;
  const y1 = normalized ? rawY1 : rawY1 / rect.height;
  const x2 = normalized ? rawX2 : rawX2 / rect.width;
  const y2 = normalized ? rawY2 : rawY2 / rect.height;
  const padding = 0.015;
  return [
    [roundPoint(clamp01(Math.min(x1, x2) - padding)), roundPoint(clamp01(Math.min(y1, y2) - padding))],
    [roundPoint(clamp01(Math.max(x1, x2) + padding)), roundPoint(clamp01(Math.min(y1, y2) - padding))],
    [roundPoint(clamp01(Math.max(x1, x2) + padding)), roundPoint(clamp01(Math.max(y1, y2) + padding))],
    [roundPoint(clamp01(Math.min(x1, x2) - padding)), roundPoint(clamp01(Math.max(y1, y2) + padding))],
  ];
}

function syncMachinePointsFromTextarea() {
  const form = document.querySelector("#machine-form");
  try {
    const parsed = JSON.parse(form.elements.points.value);
    if (Array.isArray(parsed)) {
      machineDrawingPoints = parsed
        .filter((point) => Array.isArray(point) && point.length === 2)
        .map((point) => [clamp01(Number(point[0])), clamp01(Number(point[1]))]);
      drawMachineCanvas();
    }
  } catch {
    updateMachineDrawStatus("JSON inválido nos pontos");
  }
}

function updateMachinePointsField() {
  const form = document.querySelector("#machine-form");
  form.elements.points.value = JSON.stringify(machineDrawingPoints);
  updateMachineDrawStatus();
}

function undoMachinePoint() {
  machineDrawingPoints.pop();
  updateMachinePointsField();
  drawMachineCanvas();
}

function clearMachineDrawing() {
  machineDrawingPoints = [];
  updateMachinePointsField();
  drawMachineCanvas();
}

function useFullFrameMachine() {
  machineDrawingPoints = [[0.05, 0.05], [0.95, 0.05], [0.95, 0.95], [0.05, 0.95]];
  updateMachinePointsField();
  drawMachineCanvas();
}

function updateMachineDrawStatus(message = "") {
  const status = document.querySelector("#machine-draw-status");
  if (!status) return;
  status.textContent = message || (
    machineDrawingPoints.length < 3
      ? `${machineDrawingPoints.length} ponto(s). Marque pelo menos 3.`
      : `${machineDrawingPoints.length} pontos prontos para salvar.`
  );
}

function drawMachineCanvas() {
  const canvas = document.querySelector("#machine-draw-canvas");
  const host = document.querySelector("#machine-media-host");
  if (!canvas || !host) return;
  const rect = host.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${rect.height}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  machinePreviewMachines.forEach((machine) => drawMachinePolygon(ctx, machine.points, rect, false));
  drawMachinePolygon(ctx, machineDrawingPoints, rect, true);
  updateMachineDrawStatus();
}

function drawMachinePolygon(ctx, points, rect, editing) {
  if (!points?.length) return;
  const color = "#7db3ff";
  ctx.lineWidth = editing ? 3 : 2;
  ctx.strokeStyle = color;
  ctx.fillStyle = editing ? "rgba(125, 179, 255, 0.2)" : "rgba(125, 179, 255, 0.1)";
  ctx.beginPath();
  points.forEach(([x, y], index) => {
    const px = Number(x) * rect.width;
    const py = Number(y) * rect.height;
    if (index === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  if (points.length >= 3) {
    ctx.closePath();
    ctx.fill();
  }
  ctx.stroke();
  points.forEach(([x, y], index) => {
    const px = Number(x) * rect.width;
    const py = Number(y) * rect.height;
    ctx.beginPath();
    ctx.arc(px, py, editing ? 5 : 3, 0, Math.PI * 2);
    ctx.fillStyle = editing ? "#ffffff" : color;
    ctx.fill();
    if (editing) {
      ctx.fillStyle = "#050505";
      ctx.font = "10px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(index + 1), px, py);
    }
  });
}

async function saveMachine(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const cameraId = document.querySelector("#machine-camera-select")?.value;
  if (!cameraId) return;
  let points;
  try {
    points = JSON.parse(form.elements.points.value);
  } catch {
    notify("Pontos inválidos", "Use JSON como [[0.1,0.1],[0.9,0.1],[0.9,0.9]].", "error");
    return;
  }
  if (!Array.isArray(points) || points.length < 3) {
    notify("Máquina incompleta", "Desenhe pelo menos 3 pontos na imagem.", "warning");
    return;
  }
  await createMachine({
    camera_id: cameraId,
    name: form.elements.name.value.trim(),
    type: form.elements.type.value,
    points,
    enabled: form.elements.enabled.checked,
    requires_operator: form.elements.requires_operator.checked,
    allow_idle: form.elements.allow_idle.checked,
    min_person_distance: Number(form.elements.min_person_distance.value || 0.08),
  });
  form.reset();
  machineDrawingPoints = [];
  form.elements.points.value = "[]";
  form.elements.enabled.checked = true;
  form.elements.requires_operator.checked = true;
  form.elements.min_person_distance.value = 0.08;
  closeMachineModal();
  await loadMachinesPageData();
  notify("Máquina salva", "O ativo operacional foi mapeado para essa câmera.", "success");
}

async function handleMachineAction(event) {
  const row = event.currentTarget.closest("[data-machine-id]");
  const machineId = row.dataset.machineId;
  const action = event.currentTarget.dataset.machineAction;
  if (action === "delete") {
    await deleteMachine(machineId);
  } else if (action === "toggle") {
    await updateMachine(machineId, { enabled: event.currentTarget.checked });
  }
  await loadMachinesPageData();
}

async function renderEvidencePage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-toolbar">
        <button type="button" id="evidence-refresh">Atualizar</button>
      </section>
      <section class="ops-grid">
        <div>
          <div class="section-heading"><h2>Evidências</h2><span id="evidence-count">0</span></div>
          <div id="evidence-list" class="ops-list"></div>
        </div>
        <aside class="ops-detail">
          <h2>Retenção</h2>
          <div class="object-list">
            ${objectLine("Origem", "Eventos com mídia", "Lê media_path, snapshot_path ou evidence_path no metadata do evento")}
            ${objectLine("Status", "Somente leitura", "A criação acontece quando o motor salva evidência no evento")}
          </div>
        </aside>
      </section>
    </div>
  `;
  document.querySelector("#evidence-refresh").addEventListener("click", loadEvidence);
  await loadEvidence();
}

async function loadEvidence() {
  const list = document.querySelector("#evidence-list");
  try {
    const [items, cameras, zones] = await Promise.all([listEvidence(), listCameras(), listZones()]);
    const cameraById = Object.fromEntries(cameras.map((camera) => [camera.id, camera]));
    const zoneById = Object.fromEntries(zones.map((zone) => [zone.id, zone]));
    document.querySelector("#evidence-count").textContent = `${items.length} arquivos`;
    list.innerHTML = items.length
      ? items.map((item) => evidenceRow(item, cameraById, zoneById)).join("")
      : emptyState("Nenhuma evidência salva", "Eventos sem snapshot continuam aparecendo na fila de Eventos.");
  } catch (error) {
    list.innerHTML = emptyState("Falha ao carregar evidências", error.message);
  }
}

function evidenceRow(item, cameraById, zoneById) {
  const camera = cameraById[item.camera_id];
  const zone = item.zone_id ? zoneById[item.zone_id] : null;
  return `
    <article class="ops-row">
      <div>
        <strong>${item.type}</strong>
        <span>${camera?.name || item.camera_id} · ${zone?.name || item.zone_id || "sem zona"}</span>
        <small>${formatDate(item.started_at)} · ${item.media_path}</small>
      </div>
      <span class="severity-badge" data-severity="${item.severity}">${item.severity}</span>
      <span class="health-badge" data-status="${item.status}">${item.status}</span>
    </article>
  `;
}

async function renderDiagnosticsPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-toolbar">
        <button type="button" id="diagnostics-refresh">Atualizar</button>
        <button type="button" id="demo-setup">Preparar demo</button>
        <label>Retenção evidências (dias)<input id="retention-days" type="number" min="0" max="365" value="7" /></label>
        <button type="button" id="cleanup-evidence">Limpar evidências</button>
      </section>
      <section id="diagnostics-grid" class="settings-grid"></section>
      <section class="ops-detail">
        <h2>Último evento</h2>
        <pre id="diagnostics-last" class="code-block">Carregando...</pre>
      </section>
    </div>
  `;
  document.querySelector("#diagnostics-refresh").addEventListener("click", loadDiagnostics);
  document.querySelector("#demo-setup").addEventListener("click", prepareDemo);
  document.querySelector("#cleanup-evidence").addEventListener("click", handleCleanupEvidence);
  await loadDiagnostics();
}

async function prepareDemo() {
  const button = document.querySelector("#demo-setup");
  button.textContent = "Preparando...";
  try {
    await setupDemo();
    button.textContent = "Demo pronta";
    notify("Demo pronta", "Vídeo, zona e Vision foram preparados.", "success");
    await loadDiagnostics();
  } catch (error) {
    button.textContent = "Erro na demo";
    notifyError("Falha ao preparar demo", error);
  } finally {
    setTimeout(() => (button.textContent = "Preparar demo"), 1800);
  }
}

async function handleCleanupEvidence() {
  const days = Number(document.querySelector("#retention-days").value || 7);
  const result = await cleanupEvidence(days);
  notify("Limpeza concluída", `${result.deleted_files} arquivos removidos.`, "success");
  await loadDiagnostics();
}

async function loadDiagnostics() {
  const grid = document.querySelector("#diagnostics-grid");
  try {
    const payload = await getOperationsDiagnostics();
    grid.innerHTML = [
      metricItem("Banco local", payload.sqlite ? "OK" : "Não encontrado", payload.database_path),
      metricItem("Câmeras online", payload.cameras_online, "Streams ativos agora"),
      metricItem("IA ativa", payload.ia_ativa, "Câmeras com vision ligada"),
      metricItem("Zonas ativas", payload.zonas_ativas, "Polígonos monitorados"),
      metricItem("Regras", payload.regras_ativas, "Regras operacionais carregadas"),
      metricItem("Eventos abertos", payload.eventos_abertos, "Ocorrências em andamento"),
      metricItem("Investigações", payload.investigacoes_abertas, "Casos não fechados"),
      metricItem("Disco livre", `${payload.disco_livre_percentual}%`, "Partição do banco local"),
      metricItem("Evidências", `${payload.evidence_mb} MB`, "Armazenamento local"),
    ].join("");
    document.querySelector("#diagnostics-last").textContent = payload.ultima_entrega
      ? JSON.stringify(payload.ultima_entrega, null, 2)
      : "Nenhum evento registrado.";
  } catch (error) {
    grid.innerHTML = emptyState("Falha no diagnóstico", error.message);
  }
}

async function renderRulesPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-grid">
        <div>
          <div class="section-heading">
            <h2>Regras ativas</h2>
            <div class="section-actions">
              <button type="button" id="add-rule"><i data-lucide="plus" aria-hidden="true"></i><span>Adicionar regra</span></button>
              <span>Motor determinístico</span>
            </div>
          </div>
          <div id="rules-list" class="ops-list"></div>
        </div>
        <aside class="ops-detail">
          <h2>Simulador</h2>
          <form id="rule-sim-form" class="stack-form">
            <label>Observação
              <select name="observation">
                <option value="person_entered_zone">Pessoa entrou na zona</option>
                <option value="person_exited_zone">Pessoa saiu da zona</option>
                <option value="person_presence">Pessoa permaneceu na zona</option>
              </select>
            </label>
            <label>Tipo de zona
              <select name="zone_type">
                <option value="restricted">Restrita</option>
                <option value="monitored">Monitorada</option>
              </select>
            </label>
            <button type="submit">Simular</button>
          </form>
          <div id="rule-sim-result" class="object-list"></div>
        </aside>
      </section>
      <section class="modal-layer" id="rule-modal" aria-labelledby="rule-modal-title" aria-modal="true" role="dialog" hidden>
        <div class="modal-backdrop" data-close-modal></div>
        <div class="modal-window">
          <header class="modal-header">
            <div>
              <p class="eyebrow">Motor de eventos</p>
              <h2 id="rule-modal-title">Adicionar regra</h2>
            </div>
            <button type="button" class="icon-button" id="close-rule-modal" aria-label="Fechar janela">
              <i data-lucide="x" aria-hidden="true"></i>
            </button>
          </header>
          <form id="rule-form" class="modal-form">
            <input type="hidden" name="rule_id" />
            <label>Nome<input name="name" required placeholder="Permanência em zona restrita" /></label>
            <label>Observação
              <select name="observation_type">
                <option value="person_entered_zone">Pessoa entrou</option>
                <option value="person_exited_zone">Pessoa saiu</option>
                <option value="person_presence">Pessoa permaneceu</option>
              </select>
            </label>
            <label>Tipo de zona
              <select name="zone_type">
                <option value="restricted">Restrita</option>
                <option value="monitored">Monitorada</option>
              </select>
            </label>
            <label>Tipo de evento<input name="event_type" value="PERSON_RESTRICTED_ZONE" required /></label>
            <label>Severidade
              <select name="severity">
                <option value="critical">Crítica</option>
                <option value="attention">Atenção</option>
                <option value="info">Info</option>
              </select>
            </label>
            <label>Tempo mínimo (s)<input name="duration_threshold_seconds" type="number" min="0" step="1" value="0" /></label>
            <label>Cooldown (s)<input name="cooldown_seconds" type="number" min="0" step="1" value="10" /></label>
            <label class="inline-toggle"><input name="enabled" type="checkbox" checked /> Ativa</label>
            <footer class="modal-actions">
              <button type="button" id="cancel-rule-modal">Cancelar</button>
              <button type="submit" class="primary-action">Salvar regra</button>
            </footer>
          </form>
        </div>
      </section>
    </div>
  `;
  document.querySelector("#add-rule").addEventListener("click", openRuleModal);
  document.querySelector("#close-rule-modal").addEventListener("click", closeRuleModal);
  document.querySelector("#cancel-rule-modal").addEventListener("click", closeRuleModal);
  document.querySelector("#rule-modal [data-close-modal]").addEventListener("click", closeRuleModal);
  document.querySelector("#rule-form").addEventListener("submit", saveRule);
  document.querySelector("#rule-sim-form").addEventListener("submit", simulateRule);
  refreshIcons();
  await loadRules();
}

function resetRuleForm(form) {
  form.reset();
  form.elements.rule_id.value = "";
  form.elements.event_type.value = "PERSON_RESTRICTED_ZONE";
  form.elements.duration_threshold_seconds.value = 0;
  form.elements.cooldown_seconds.value = 10;
  form.elements.enabled.checked = true;
}

function openRuleModal() {
  const modal = document.querySelector("#rule-modal");
  const form = document.querySelector("#rule-form");
  if (!modal || !form) return;
  editingRuleId = null;
  resetRuleForm(form);
  document.querySelector("#rule-modal-title").textContent = "Adicionar regra";
  modal.hidden = false;
  document.body.dataset.modalOpen = "true";
  refreshIcons();
  requestAnimationFrame(() => form.elements.name.focus());
}

function openRuleEditModal(ruleId) {
  const rule = rulesCache.find((item) => item.id === ruleId);
  const modal = document.querySelector("#rule-modal");
  const form = document.querySelector("#rule-form");
  if (!rule || !modal || !form) return;
  editingRuleId = rule.id;
  form.elements.rule_id.value = rule.id;
  form.elements.name.value = rule.name || "";
  form.elements.observation_type.value = rule.observation_type || rule.observation;
  form.elements.zone_type.value = rule.zone_type || rule.zone || "restricted";
  form.elements.event_type.value = rule.event_type || rule.event || "PERSON_RESTRICTED_ZONE";
  form.elements.severity.value = rule.severity || "attention";
  form.elements.duration_threshold_seconds.value = rule.duration_threshold_seconds ?? 0;
  form.elements.cooldown_seconds.value = rule.cooldown_seconds ?? 10;
  form.elements.enabled.checked = Boolean(rule.enabled);
  document.querySelector("#rule-modal-title").textContent = "Editar regra";
  modal.hidden = false;
  document.body.dataset.modalOpen = "true";
  refreshIcons();
  requestAnimationFrame(() => form.elements.name.focus());
}

function closeRuleModal() {
  const modal = document.querySelector("#rule-modal");
  if (!modal) return;
  modal.hidden = true;
  editingRuleId = null;
  delete document.body.dataset.modalOpen;
}

async function saveRule(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    name: form.elements.name.value.trim(),
    observation_type: form.elements.observation_type.value,
    zone_type: form.elements.zone_type.value,
    event_type: form.elements.event_type.value.trim(),
    severity: form.elements.severity.value,
    duration_threshold_seconds: Number(form.elements.duration_threshold_seconds.value || 0),
    cooldown_seconds: Number(form.elements.cooldown_seconds.value || 10),
    enabled: form.elements.enabled.checked,
  };
  const wasEditing = Boolean(editingRuleId);
  await (editingRuleId ? updateRule(editingRuleId, payload) : createRule(payload));
  resetRuleForm(form);
  closeRuleModal();
  notify(wasEditing ? "Regra atualizada" : "Regra cadastrada", "O motor de eventos foi atualizado.", "success");
  await loadRules();
}

async function loadRules() {
  const host = document.querySelector("#rules-list");
  try {
    const rules = await listRules();
    rulesCache = rules;
    host.innerHTML = rules.length
      ? rules.map(ruleCard).join("")
      : `<div class="empty-state"><strong>Nenhuma regra ativa</strong><span>Crie uma regra para transformar observações em eventos.</span><button type="button" data-empty-action="add-rule">Adicionar regra</button></div>`;
    host.querySelector("[data-empty-action='add-rule']")?.addEventListener("click", openRuleModal);
    host.querySelectorAll("[data-rule-action]").forEach((button) => {
      button.addEventListener("click", handleRuleAction);
    });
  } catch (error) {
    host.innerHTML = emptyState("Falha ao carregar regras", error.message);
  }
}

function ruleCard(rule) {
  const observation = rule.observation || rule.observation_type;
  const zone = rule.zone || rule.zone_type;
  const event = rule.event || rule.event_type;
  const delay = rule.delay || (rule.duration_threshold_seconds ? `${rule.duration_threshold_seconds}s` : "imediata");
  return `
    <article class="ops-row" data-rule-id="${rule.id || ""}">
      <div>
        <strong>${rule.name}</strong>
        <span>${observation} · zone=${zone || "qualquer"} · cooldown ${rule.cooldown_seconds ?? 10}s</span>
        <small>${event} · ${delay}</small>
      </div>
      <span class="severity-badge" data-severity="${rule.severity}">${rule.severity}</span>
      <span class="health-badge" data-status="${rule.enabled ? "ONLINE" : "OFFLINE"}">${rule.enabled ? "ATIVA" : "INATIVA"}</span>
      <div class="row-actions">
        <button type="button" data-rule-action="edit">Editar</button>
        <button type="button" data-rule-action="toggle">${rule.enabled ? "Desativar" : "Ativar"}</button>
        <button type="button" data-rule-action="delete">Excluir</button>
      </div>
    </article>
  `;
}

async function handleRuleAction(event) {
  const row = event.currentTarget.closest("[data-rule-id]");
  const ruleId = row.dataset.ruleId;
  if (!ruleId) return;
  const action = event.currentTarget.dataset.ruleAction;
  if (action === "edit") {
    openRuleEditModal(ruleId);
    return;
  }
  if (action === "delete") {
    await deleteRule(ruleId);
  } else if (action === "toggle") {
    const active = row.querySelector(".health-badge")?.textContent === "ATIVA";
    await updateRule(ruleId, { enabled: !active });
  }
  await loadRules();
}

async function simulateRule(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const observation = form.elements.observation.value;
  const zone = form.elements.zone_type.value;
  const result = await simulateRuleRequest({ observation_type: observation, zone_type: zone });
  document.querySelector("#rule-sim-result").innerHTML = result.rules.length
    ? result.rules.map(ruleCard).join("")
    : emptyState("Nenhuma regra disparada", "Essa combinação não gera evento no motor atual.");
}

async function renderSettingsPage() {
  appView.innerHTML = `
    <div class="ops-page">
      <section class="ops-grid">
        <div>
          <div class="section-heading"><h2>Runtime</h2><button type="button" id="settings-refresh">Atualizar</button></div>
          <div id="settings-runtime" class="settings-grid"></div>
        </div>
        <aside class="ops-detail">
          <h2>Preferências locais</h2>
          <form id="local-settings-form" class="stack-form">
            <label>Atualização ao vivo (ms)<input name="refresh_ms" type="number" min="500" step="500" /></label>
            <label>Modo operador
              <select name="operator_mode">
                <option value="standard">Padrão</option>
                <option value="review">Revisão</option>
                <option value="debug">Debug</option>
              </select>
            </label>
            <label>Token API local<input name="api_token" type="password" autocomplete="off" placeholder="Opcional: X-CAMPEX-Token" /></label>
            <label class="inline-toggle"><input name="dense_lists" type="checkbox" /> Listas compactas</label>
            <button type="submit">Salvar local</button>
          </form>
        </aside>
      </section>
    </div>
  `;
  document.querySelector("#settings-refresh").addEventListener("click", loadSettings);
  document.querySelector("#local-settings-form").addEventListener("submit", saveLocalSettings);
  fillLocalSettings();
  await loadSettings();
}

async function loadSettings() {
  const host = document.querySelector("#settings-runtime");
  try {
    const [runtime, cameras, zones, events] = await Promise.all([
      getRuntimeSettings(),
      listCameras(),
      listZones(),
      listEvents({ limit: 50 }),
    ]);
    host.innerHTML = [
      metricItem("Serviço", `${runtime.service_name} ${runtime.version}`, runtime.environment),
      metricItem("Banco", runtime.database_url, `${cameras.length} câmeras`),
      metricItem("Vision", `${runtime.vision.detector} · ${runtime.vision.device}`, `${runtime.vision.fps} FPS · conf ${runtime.vision.confidence}`),
      metricItem("Câmeras", `${runtime.camera.stale_seconds}s stale`, `${runtime.camera.read_failure_limit} falhas até reconectar`),
      metricItem("Zonas", `${zones.length} cadastradas`, `${events.length} eventos recentes`),
      metricItem("CORS", runtime.frontend_origins.join(", "), runtime.log_level),
    ].join("");
  } catch (error) {
    host.innerHTML = emptyState("Falha ao carregar configurações", error.message);
  }
}

function metricItem(title, value, detail) {
  return `<article class="metric-item"><span>${title}</span><strong>${value}</strong><small>${detail || ""}</small></article>`;
}

function objectLine(title, value, detail) {
  return `
    <article class="insight-line">
      <div>
        <strong>${title}</strong>
        <span>${value}</span>
        <small>${detail || ""}</small>
      </div>
    </article>
  `;
}

function formatMoney(value, currency = "BRL") {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value}`;
  }
}

function localSettings() {
  return JSON.parse(localStorage.getItem("campex.settings") || '{"refresh_ms":2000,"operator_mode":"standard","dense_lists":false,"api_token":""}');
}

function applyLocalSettings() {
  const settings = localSettings();
  document.body.dataset.density = settings.dense_lists ? "compact" : "comfortable";
  document.body.dataset.operatorMode = settings.operator_mode || "standard";
  if (settings.api_token) {
    localStorage.setItem("campex.api_token", settings.api_token);
  }
}

function fillLocalSettings() {
  const settings = localSettings();
  const form = document.querySelector("#local-settings-form");
  form.elements.refresh_ms.value = settings.refresh_ms;
  form.elements.operator_mode.value = settings.operator_mode;
  form.elements.dense_lists.checked = Boolean(settings.dense_lists);
  form.elements.api_token.value = settings.api_token || localStorage.getItem("campex.api_token") || "";
}

function saveLocalSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const settings = {
    refresh_ms: Number(form.elements.refresh_ms.value || 2000),
    operator_mode: form.elements.operator_mode.value,
    dense_lists: form.elements.dense_lists.checked,
    api_token: form.elements.api_token.value.trim(),
  };
  localStorage.setItem("campex.settings", JSON.stringify(settings));
  if (settings.api_token) {
    localStorage.setItem("campex.api_token", settings.api_token);
  } else {
    localStorage.removeItem("campex.api_token");
  }
  applyLocalSettings();
  notify("Configurações salvas", "Preferências locais atualizadas.", "success");
}

async function populateCameraSelect(selector, includeAll = false) {
  const select = document.querySelector(selector);
  const cameras = await listCameras();
  select.innerHTML = [
    includeAll ? `<option value="">Todas</option>` : "",
    ...cameras.map((camera) => `<option value="${camera.id}">${camera.name}</option>`),
  ].join("");
}

function emptyState(title, detail) {
  return `<div class="empty-state"><strong>${title}</strong><span>${detail}</span></div>`;
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("pt-BR");
}

function debounce(fn, delay) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), delay);
  };
}

async function refreshBackendStatus() {
  if (backendStatusRefreshInFlight) return;
  backendStatusRefreshInFlight = true;
  const backendSummary = document.querySelector("#backend-summary");

  try {
    if (lastBackendState !== "online") {
      statusElement.dataset.state = "checking";
      statusText.textContent = "Verificando backend";
    }
    const health = await getHealth();
    statusElement.dataset.state = "online";
    statusText.textContent = `${health.service} ${health.version} online`;
    if (lastBackendState !== "online") {
      notify("Backend conectado", `${health.service} ${health.version} respondeu em /health.`, "success");
    }
    lastBackendState = "online";
    if (backendSummary) {
      backendSummary.textContent = "Conectado via /api/v1/health";
    }
  } catch (error) {
    statusElement.dataset.state = "offline";
    statusText.textContent = "Backend indisponível";
    if (lastBackendState !== "offline") {
      notify("Backend indisponível", "Confira se o backend está em http://127.0.0.1:8000 ou se a URL da API está correta.", "error", 8000);
    }
    lastBackendState = "offline";
    if (backendSummary) {
      backendSummary.textContent = "Sem resposta do backend";
    }
    console.error(error);
  } finally {
    backendStatusRefreshInFlight = false;
  }
}

window.addEventListener("hashchange", () => {
  if (!getCurrentUser()) {
    renderAuthScreen();
    return;
  }
  renderRoute();
  refreshIcons();
  refreshBackendStatus();
});

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!document.querySelector("#camera-modal")?.hidden) {
    closeCameraModal();
    return;
  }
  if (!document.querySelector("#rule-modal")?.hidden) {
    closeRuleModal();
    return;
  }
  if (!document.querySelector("#machine-modal")?.hidden) {
    closeMachineModal();
  }
});

accountButton?.addEventListener("click", handleSignOut);
startAuthenticatedApp();
