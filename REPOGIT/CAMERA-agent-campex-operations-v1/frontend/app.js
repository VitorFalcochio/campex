const form = document.querySelector("#cameraForm");
const loginForm = document.querySelector("#loginForm");
const loginHeader = document.querySelector("#loginHeader");
const loginStatus = document.querySelector("#loginStatus");
const signupForm = document.querySelector("#signupForm");
const signupStatus = document.querySelector("#signupStatus");
const showSignupButton = document.querySelector("#showSignupButton");
const showLoginButton = document.querySelector("#showLoginButton");
const loginPasswordInput = document.querySelector("#loginPasswordInput");
const loginPasswordToggle = document.querySelector("#loginPasswordToggle");
const googleOAuthButton = document.querySelector("#googleOAuthButton");
const connectedAccountPanel = document.querySelector("#connectedAccountPanel");
const connectedAccountName = document.querySelector("#connectedAccountName");
const connectedAccountEmail = document.querySelector("#connectedAccountEmail");
const connectedAccountRole = document.querySelector("#connectedAccountRole");
const loginPanel = document.querySelector("#login");
const logoutButton = document.querySelector("#logoutButton");
const sidebarLogoutButton = document.querySelector("#sidebarLogoutButton");
const accountSettingsLogoutButton = document.querySelector("#accountSettingsLogoutButton");
const accountSettingsName = document.querySelector("#accountSettingsName");
const accountSettingsEmail = document.querySelector("#accountSettingsEmail");
const accountSettingsRole = document.querySelector("#accountSettingsRole");
const accountSettingsPhoto = document.querySelector(".cx-account-photo:not(.cx-org-logo)");
const profileName = document.querySelector(".cx-profile-name");
const profileRole = document.querySelector(".cx-profile-role");
const profileAvatar = document.querySelector(".cx-avatar");
const workspaceName = document.querySelector(".cx-workspace-copy strong");
const workspaceUnit = document.querySelector(".cx-workspace-copy small");
const testButton = document.querySelector("#testButton");
const liveViewButton = document.querySelector("#liveViewButton");
const result = document.querySelector("#result");
const cameraList = document.querySelector("#cameraList");
const apiStatus = document.querySelector("#apiStatus");
const liveImage = document.querySelector("#liveImage");
const viewerTitle = document.querySelector("#viewerTitle");
const viewerStatus = document.querySelector("#viewerStatus");
const viewerStage = document.querySelector("#viewerStage");
const viewerMessage = document.querySelector("#viewerMessage");
const viewerResolution = document.querySelector("#viewerResolution");
const viewerFps = document.querySelector("#viewerFps");
const viewerLastFrame = document.querySelector("#viewerLastFrame");
const viewerClock = document.querySelector("#viewerClock");
const viewerAiStatus = document.querySelector("#viewerAiStatus");
const viewerPeopleCount = document.querySelector("#viewerPeopleCount");
const startAnalysisButton = document.querySelector("#startAnalysisButton");
const stopAnalysisButton = document.querySelector("#stopAnalysisButton");
const createAreaButton = document.querySelector("#createAreaButton");
const undoAreaPointButton = document.querySelector("#undoAreaPointButton");
const saveAreaButton = document.querySelector("#saveAreaButton");
const cancelAreaButton = document.querySelector("#cancelAreaButton");
const areaCanvas = document.querySelector("#areaCanvas");
const areaList = document.querySelector("#areaList");
const viewerAreaName = document.querySelector("#viewerAreaName");
const viewerAreaState = document.querySelector("#viewerAreaState");
const viewerAreaPeople = document.querySelector("#viewerAreaPeople");
const viewerAreaIds = document.querySelector("#viewerAreaIds");
const viewerMachineState = document.querySelector("#viewerMachineState");
const viewerMachineMotion = document.querySelector("#viewerMachineMotion");
const activeIncident = document.querySelector("#activeIncident");
const eventList = document.querySelector("#eventList");
const unackedCount = document.querySelector("#unackedCount");
const soundToggle = document.querySelector("#soundToggle");
const liveAlertList = document.querySelector("#liveAlertList");
const recipientForm = document.querySelector("#recipientForm");
const recipientList = document.querySelector("#recipientList");
const deliveryList = document.querySelector("#deliveryList");
const systemHealth = document.querySelector("#systemHealth");
const pilotChecklist = document.querySelector("#pilotChecklist");
const createMachineButton = document.querySelector("#createMachineButton");
const nextMachineZoneButton = document.querySelector("#nextMachineZoneButton");
const saveMachineButton = document.querySelector("#saveMachineButton");
const machineList = document.querySelector("#machineList");
const operationsList = document.querySelector("#operationsList");
const clientForm = document.querySelector("#clientForm");
const organizationDialog = document.querySelector("#organizationDialog");
const organizationEditorButtons = Array.from(document.querySelectorAll("[data-open-organization-editor]"));
const organizationEditorCloseButtons = Array.from(document.querySelectorAll("[data-close-organization-editor]"));
const unitForm = document.querySelector("#unitForm");
const userForm = document.querySelector("#userForm");
const machineConfigForm = document.querySelector("#machineConfigForm");
const clientList = document.querySelector("#clientList");
const unitList = document.querySelector("#unitList");
const userList = document.querySelector("#userList");
const machineConfigList = document.querySelector("#machineConfigList");
const unitClientSelect = document.querySelector("#unitClientSelect");
const userClientSelect = document.querySelector("#userClientSelect");
const cameraUnitSelect = document.querySelector("#cameraUnitSelect");
const cameraEdgeSelect = document.querySelector("#cameraEdgeSelect");
const machineCameraSelect = document.querySelector("#machineCameraSelect");
const setupSaveStatus = document.querySelector("#setupSaveStatus");
const setupUnitForm = document.querySelector("#setupUnitForm");
const setupAreaForm = document.querySelector("#setupAreaForm");
const setupProcessForm = document.querySelector("#setupProcessForm");
const setupAssetForm = document.querySelector("#setupAssetForm");
const setupCameraContextForm = document.querySelector("#setupCameraContextForm");
const setupMonitorForm = document.querySelector("#setupMonitorForm");
const setupOpenCameraButton = document.querySelector("#setupOpenCameraButton");
const setupUnitClientSelect = document.querySelector("#setupUnitClientSelect");
const setupAreaUnitSelect = document.querySelector("#setupAreaUnitSelect");
const setupProcessAreaSelect = document.querySelector("#setupProcessAreaSelect");
const setupAssetProcessSelect = document.querySelector("#setupAssetProcessSelect");
const setupContextCameraSelect = document.querySelector("#setupContextCameraSelect");
const setupContextAssetSelect = document.querySelector("#setupContextAssetSelect");
const setupMonitorCameraSelect = document.querySelector("#setupMonitorCameraSelect");
const setupHierarchy = document.querySelector("#setupHierarchy");
const setupCameraLinks = document.querySelector("#setupCameraLinks");
const setupCapabilities = document.querySelector("#setupCapabilities");
const setupReadiness = document.querySelector("#setupReadiness");
const setupInstallChecklist = document.querySelector("#setupInstallChecklist");
const alertSetupStatus = document.querySelector("#alertSetupStatus");
const setupCompanySummary = document.querySelector("#setupCompanySummary");
const setupOperationSummary = document.querySelector("#setupOperationSummary");
const setupCameraGate = document.querySelector("#setupCameraGate");
const setupReadinessConclusion = document.querySelector("#setupReadinessConclusion");
const setupHeroStatus = document.querySelector("#setupHeroStatus");
const settingsOrgName = document.querySelector("#settingsOrgName");
const settingsOrgLogos = Array.from(document.querySelectorAll(".cx-org-logo"));
const settingsOrgStatus = document.querySelector("#settingsOrgStatus");
const settingsUnitName = document.querySelector("#settingsUnitName");
const settingsUnitMeta = document.querySelector("#settingsUnitMeta");
const settingsUsersCount = document.querySelector("#settingsUsersCount");
const settingsUsersMeta = document.querySelector("#settingsUsersMeta");
const settingsReportSchedule = document.querySelector("#settingsReportSchedule");
const settingsReportRecipient = document.querySelector("#settingsReportRecipient");
const settingsOperationCount = document.querySelector("#settingsOperationCount");
const settingsOperationMeta = document.querySelector("#settingsOperationMeta");
const settingsReadinessTitle = document.querySelector("#settingsReadinessTitle");
const settingsReadinessText = document.querySelector("#settingsReadinessText");
const settingsReadinessAction = document.querySelector("#settingsReadinessAction");
const settingsSystemBadge = document.querySelector("#settingsSystemBadge");
const settingsPlatformStatus = document.querySelector("#settingsPlatformStatus");
const settingsDataStatus = document.querySelector("#settingsDataStatus");
const settingsProcessingStatus = document.querySelector("#settingsProcessingStatus");
const settingsStorageStatus = document.querySelector("#settingsStorageStatus");
const settingsReportsStatus = document.querySelector("#settingsReportsStatus");
const settingsLastAccess = document.querySelector("#settingsLastAccess");
const settingsActiveSessions = document.querySelector("#settingsActiveSessions");
const settingsSecurityAuth = document.querySelector("#settingsSecurityAuth");
const firstRunPanel = document.querySelector("#firstRunPanel");
const firstRunForm = document.querySelector("#firstRunForm");
const firstRunStatus = document.querySelector("#firstRunStatus");
const firstRunAdminEmail = firstRunForm?.querySelector("input[name='admin_email']");
const setupNavLinks = Array.from(document.querySelectorAll("[data-setup-nav]"));
const setupSections = Array.from(document.querySelectorAll("[data-setup-section]"));

let currentCameraId = null;
let currentCameraName = null;
let statusTimer = null;
let latestFrameTimer = null;
let eventTimer = null;
let deliveryTimer = null;
let eventSource = null;
let drawingArea = false;
let drawingMachine = false;
let machineStep = "machine";
let draftPoints = [];
let draftMachinePoints = [];
let draftOperatorPoints = [];
let currentAreas = [];
let currentMachines = [];
let lastRtspPayload = null;
const seenAlertEvents = new Set();
let liveAlerts = [];
let knownClients = [];
let knownUnits = [];
let knownEdges = [];
let knownCameras = [];
let knownRecipients = [];
let knownUsers = [];
let currentAuthUser = null;
let latestSystemHealth = null;
let activeUnitId = null;
const ACTIVE_UNIT_STORAGE_KEY = "campex_active_unit_id";
let setupOperation = {
  areas: [],
  processes: [],
  assets: [],
  capabilities: [],
  asset_status: [],
  monitored_areas: [],
  machine_monitors: [],
};

stripSensitiveQueryString();

function currentClient() {
  return knownClients[0] || null;
}

function unitBelongsToCurrentClient(unit) {
  const client = currentClient();
  return Boolean(unit && (!client || unit.cliente_id === client.id));
}

function storedActiveUnitId() {
  try {
    return localStorage.getItem(ACTIVE_UNIT_STORAGE_KEY);
  } catch (_error) {
    return null;
  }
}

function persistActiveUnitId(unitId) {
  try {
    if (unitId) localStorage.setItem(ACTIVE_UNIT_STORAGE_KEY, unitId);
    else localStorage.removeItem(ACTIVE_UNIT_STORAGE_KEY);
  } catch (_error) {
    // Browser storage is optional; the active unit still works in memory.
  }
}

function activeUnit() {
  return knownUnits.find((unit) => unit.id === activeUnitId && unitBelongsToCurrentClient(unit)) || null;
}

function resolveActiveUnit() {
  const stored = storedActiveUnitId();
  const validUnits = knownUnits.filter(unitBelongsToCurrentClient);
  const selected = validUnits.find((unit) => unit.id === activeUnitId)
    || validUnits.find((unit) => unit.id === stored)
    || validUnits[0]
    || null;
  activeUnitId = selected?.id || null;
  persistActiveUnitId(activeUnitId);
  return selected;
}

function setActiveUnit(unitId) {
  const unit = knownUnits.find((item) => item.id === unitId && unitBelongsToCurrentClient(item));
  if (!unit) return;
  activeUnitId = unit.id;
  persistActiveUnitId(activeUnitId);
  publishWorkspaceContext();
  renderSettingsOverview();
  renderSetupJourney();
}

function publishWorkspaceContext() {
  const client = currentClient();
  const unit = activeUnit() || resolveActiveUnit();
  window.dispatchEvent(new CustomEvent("campex:workspace-context", {
    detail: {
      organization: client ? { id: client.id, nome: client.nome, status: client.status } : null,
      activeUnitId,
      activeUnit: unit ? { id: unit.id, nome: unit.nome, localizacao: unit.localizacao, timezone: unit.timezone } : null,
      units: knownUnits.filter(unitBelongsToCurrentClient).map((item) => ({
        id: item.id,
        nome: item.nome,
        localizacao: item.localizacao,
        timezone: item.timezone,
      })),
    },
  }));
}

window.addEventListener("campex:set-active-unit", (event) => {
  setActiveUnit(event.detail?.unitId);
});

function stripSensitiveQueryString() {
  const sensitiveKeys = [
    "senha",
    "admin_senha",
    "password",
    "smtp_password",
    "rtsp_url",
    "usuario",
    "token",
    "secret",
  ];
  const url = new URL(window.location.href);
  const hasSensitiveValue = sensitiveKeys.some((key) => url.searchParams.has(key));
  if (!hasSensitiveValue) return;
  sensitiveKeys.forEach((key) => url.searchParams.delete(key));
  const clean = `${url.pathname}${url.search}${url.hash}`;
  window.history.replaceState({}, document.title, clean);
}

function normalizeLocalHost() {
  if (window.location.hostname !== "0.0.0.0") return;
  const next = new URL(window.location.href);
  next.hostname = "127.0.0.1";
  window.location.replace(next.toString());
}

normalizeLocalHost();

function formPayload(targetForm) {
  const data = new FormData(targetForm);
  const payload = {};
  for (const [key, value] of data.entries()) {
    const text = String(value).trim();
    if (text) payload[key] = text;
  }
  targetForm.querySelectorAll("input[type='checkbox'][name]").forEach((input) => {
    payload[input.name] = input.checked;
  });
  return payload;
}

function fillSelect(select, items, emptyLabel) {
  if (!select) return;
  select.innerHTML = [
    `<option value="">${emptyLabel}</option>`,
    ...items.map((item) => `<option value="${item.id}">${item.nome}</option>`),
  ].join("");
}

function fillCameraEdgeSelect() {
  if (!cameraEdgeSelect) return;
  const unitId = cameraUnitSelect?.value || activeUnitId || "";
  const edges = knownEdges.filter((edge) => !unitId || edge.unidade_id === unitId);
  if (!edges.length) {
    cameraEdgeSelect.disabled = true;
    cameraEdgeSelect.innerHTML = '<option value="">Nenhum Edge configurado para esta unidade</option>';
    return;
  }
  const current = cameraEdgeSelect.value;
  cameraEdgeSelect.disabled = false;
  cameraEdgeSelect.innerHTML = [
    '<option value="">Selecione o Campex Edge</option>',
    ...edges.map((edge) => {
      const status = edge.online ? "online" : (edge.connection_status || edge.status || "offline");
      return `<option value="${safeText(edge.id)}">${safeText(edge.nome || edge.id)} · ${safeText(status)}</option>`;
    }),
  ].join("");
  if (Array.from(cameraEdgeSelect.options).some((option) => option.value === current)) {
    cameraEdgeSelect.value = current;
  } else if (edges.length === 1) {
    cameraEdgeSelect.value = edges[0].id;
  }
}

function safeText(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function friendlyError(error) {
  const raw = String(error?.message || error || "erro desconhecido");
  if (/internal server error/i.test(raw)) {
    return "Não foi possível carregar esta visualização agora. Verifique a API local e tente atualizar.";
  }
  if (/failed to fetch|networkerror/i.test(raw)) {
    return "Não foi possível conectar à API local. Confirme se a Campex está iniciada.";
  }
  if (/401|unauthorized|not authenticated/i.test(raw)) {
    return "Entre para acessar esta configuração.";
  }
  return raw.replace(/^Erro:\s*/i, "");
}

function setupErrorState(title, error, action = "Atualizar") {
  return `
    <div class="cx-setup-error">
      <strong>${safeText(title)}</strong>
      <p>${safeText(friendlyError(error))}</p>
      <button type="button" data-setup-refresh>${safeText(action)}</button>
    </div>
  `;
}

function setupStatusPill(status) {
  const value = String(status || "indisponível").toLowerCase();
  const tone = value.includes("online") || value.includes("pass") || value.includes("ativo") || value.includes("sent") ? "online"
    : value.includes("fail") || value.includes("falh") || value.includes("offline") || value.includes("erro") ? "offline"
    : "neutral";
  return `<span class="cx-setup-pill ${tone}">${safeText(status || "Indisponível")}</span>`;
}

function humanSetupType(value) {
  const labels = {
    machine_region: "Região da máquina",
    operator_zone: "Zona do operador",
    work_area: "Área de trabalho",
    workstation: "Posto de trabalho",
    restricted_area: "Área restrita",
    restricted_zone: "Área restrita",
    dwell_area: "Permanência",
    machine_stoppage: "Parada operacional",
    workstation_unattended: "Ausência operacional",
    machine_running_without_operator: "Máquina ativa sem operador",
    machine_stopped_with_operator: "Máquina parada com operador",
    restricted_zone_occupied: "Área restrita ocupada",
  };
  return labels[value] || value || "Não informado";
}

function humanSetupId(value, fallback = "Não informado") {
  const text = String(value || "").trim();
  if (!text) return fallback;
  if (/^(cam|area|mach|evt|evd|rec|del|unit|client|proc|asset|rule)_[a-z0-9_-]+$/i.test(text)) return fallback;
  return text;
}

function currentSetupSection() {
  const key = String(window.location.hash || "#cliente").replace("#", "");
  const known = new Set(setupNavLinks.map((link) => link.dataset.setupNav));
  return known.has(key) ? key : "cliente";
}

function currentReturnPath() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function redirectToLogin() {
  window.location.href = `/login?next=${encodeURIComponent(currentReturnPath())}`;
}

function applySetupSection() {
  const active = currentSetupSection();
  setupNavLinks.forEach((link) => {
    const isActive = link.dataset.setupNav === active;
    link.classList.toggle("active", isActive);
    link.setAttribute("aria-current", isActive ? "page" : "false");
  });
  setupSections.forEach((section) => {
    section.hidden = section.dataset.setupSection !== active;
  });
  if (document.body.classList.contains("cx-authenticated") && loginPanel) {
    loginPanel.hidden = true;
  }
}

function setSetupStatus(message, offline = false) {
  if (!setupSaveStatus) return;
  setupSaveStatus.textContent = message;
  setupSaveStatus.classList.toggle("offline", offline);
  if (setupHeroStatus) setupHeroStatus.textContent = offline ? "Configuração requer atenção" : message;
}

function setText(node, value) {
  if (node) node.textContent = value;
}

function setSetupBadge(node, label, tone = "neutral") {
  if (!node) return;
  node.textContent = label;
  node.className = `cx-setup-pill ${tone}`;
}

function initialsFromText(value) {
  const words = String(value || "Campex")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return (words.length > 1 ? `${words[0][0]}${words[1][0]}` : words[0]?.slice(0, 2) || "C").toUpperCase();
}

function renderSettingsOverview() {
  const client = currentClient();
  const unit = activeUnit() || resolveActiveUnit();
  const activeUsers = knownUsers.filter((user) => user.ativo !== false);
  const activeRecipients = knownRecipients.filter((recipient) => recipient.ativo !== false);
  const activeCameras = knownCameras.filter((camera) => camera.ativa !== false);
  const assetsCount = setupOperation.assets?.length || 0;
  const areasCount = setupOperation.areas?.length || 0;
  const readinessChecks = setupOperation.readiness?.checks || [];
  const missingChecks = readinessChecks.filter((item) => item.status !== "PASS");
  const organizationName = client?.nome || currentAuthUser?.cliente_nome || "Indisponível";
  const unitName = unit?.nome || "Indisponível";

  setText(settingsOrgName, organizationName);
  settingsOrgLogos.forEach((node) => setText(node, initialsFromText(organizationName || "Campex")));
  setSetupBadge(
    settingsOrgStatus,
    client ? safeText(client.status || "Ativa") : currentAuthUser ? "Ativa" : "Sessão necessária",
    client || currentAuthUser ? "online" : "neutral",
  );
  setText(settingsUnitName, unitName);
  setText(settingsUnitMeta, unit ? safeText(unit.localizacao || unit.timezone || "Unidade principal") : "Entre para carregar unidade");
  setText(settingsUsersCount, activeUsers.length ? `${activeUsers.length} membro${activeUsers.length === 1 ? "" : "s"}` : currentAuthUser ? "1 membro" : "Indisponível");
  setText(settingsUsersMeta, activeUsers.length ? "Usuários ativos na organização" : currentAuthUser ? "Sessão atual conectada" : "Membros da organização");
  setText(settingsReportSchedule, activeRecipients.length ? "Configurado" : "Não configurado");
  setText(settingsReportRecipient, activeRecipients[0]?.email || "Nenhum destinatário ativo");
  setText(settingsOperationCount, `${activeCameras.length} câmera${activeCameras.length === 1 ? "" : "s"}`);
  setText(settingsOperationMeta, `${assetsCount} ativo${assetsCount === 1 ? "" : "s"} · ${areasCount} área${areasCount === 1 ? "" : "s"} monitorada${areasCount === 1 ? "" : "s"}`);

  if (!currentAuthUser) {
    setText(settingsReadinessTitle, "Sessão necessária");
    setText(settingsReadinessText, "Entre para carregar organização, operação, alertas e saúde do sistema.");
    if (settingsReadinessAction) {
      settingsReadinessAction.textContent = "Entrar";
      settingsReadinessAction.href = `/login?next=${encodeURIComponent(currentReturnPath())}`;
    }
  } else if (!readinessChecks.length) {
    setText(settingsReadinessTitle, "Configuração em validação");
    setText(settingsReadinessText, "A Campex está aguardando os dados reais de setup e saúde.");
    if (settingsReadinessAction) {
      settingsReadinessAction.textContent = "Ver histórico";
      settingsReadinessAction.href = "#entregas";
    }
  } else if (!missingChecks.length) {
    setText(settingsReadinessTitle, "Pronto para operar");
    setText(settingsReadinessText, "Os itens obrigatórios do checklist carregado estão aprovados.");
    if (settingsReadinessAction) {
      settingsReadinessAction.textContent = "Ver histórico";
      settingsReadinessAction.href = "#entregas";
    }
  } else {
    const firstMissing = missingChecks[0]?.label || "configuração";
    const nextAction = /c[aâ]mera|camera/i.test(firstMissing) ? "Conecte uma câmera para começar a monitorar a operação." : `Revise ${firstMissing.toLowerCase()} para concluir a configuração.`;
    setText(settingsReadinessTitle, /c[aâ]mera|camera/i.test(firstMissing) ? "Próximo passo: conectar sua primeira câmera" : "Próximo passo: concluir a configuração");
    setText(settingsReadinessText, nextAction);
    if (settingsReadinessAction) {
      settingsReadinessAction.textContent = /c[aâ]mera|camera/i.test(firstMissing) ? "Conectar câmera →" : "Abrir configuração →";
      settingsReadinessAction.href = /c[aâ]mera|camera/i.test(firstMissing) ? "#cameras" : "#maquinas";
    }
  }

  const humanHealth = (ok) => (currentAuthUser ? (ok ? "Operacional" : "Requer atenção") : "Indisponível");
  const onlineCameras = Number(latestSystemHealth?.cameras_online ?? 0);
  const aiActive = Number(latestSystemHealth?.ai_active ?? 0);
  const diskValue = latestSystemHealth?.disk_free_gb != null ? `${latestSystemHealth.disk_free_gb} GB livres` : "Indisponível";
  const reportsOk = activeRecipients.length ? "Configurado" : "Não configurado";

  setSetupBadge(settingsSystemBadge, currentAuthUser ? "Dados carregados" : "Sessão necessária", currentAuthUser ? "online" : "neutral");
  setText(settingsPlatformStatus, humanHealth(Boolean(latestSystemHealth?.api || currentAuthUser)));
  setText(settingsDataStatus, currentAuthUser ? (onlineCameras > 0 ? "Operacional" : "Requer atenção") : "Indisponível");
  setText(settingsProcessingStatus, currentAuthUser ? (aiActive > 0 ? "Operacional" : "Requer atenção") : "Indisponível");
  setText(settingsStorageStatus, currentAuthUser ? (latestSystemHealth?.disk_free_gb != null ? "Operacional" : "Indisponível") : diskValue);
  setText(settingsReportsStatus, reportsOk);
  setText(settingsLastAccess, currentAuthUser ? "Sessão atual" : "Sessão necessária");
  setText(settingsActiveSessions, currentAuthUser ? "1 sessão" : "Indisponível");
  setText(settingsSecurityAuth, currentAuthUser ? "Conta autenticada" : "Sessão necessária");

  if (workspaceName) workspaceName.textContent = client?.nome || "Cliente piloto";
  if (workspaceUnit) workspaceUnit.textContent = unit?.nome || "Unidade principal";
  publishWorkspaceContext();
}

function fillSetupSelects() {
  fillSelect(setupUnitClientSelect, knownClients, "Organização padrão ou selecione");
  fillSelect(setupAreaUnitSelect, knownUnits, "Selecione a unidade");
  fillSelect(setupContextCameraSelect, knownCameras, "Selecione a câmera");
  fillSelect(setupMonitorCameraSelect, knownCameras, "Selecione a câmera");
  fillSelect(setupProcessAreaSelect, setupOperation.areas, "Selecione a área");
  fillSelect(setupAssetProcessSelect, setupOperation.processes, "Selecione o processo");
  fillSelect(setupContextAssetSelect, setupOperation.assets, "Selecione o ativo");
  const client = currentClient();
  if (setupUnitClientSelect && client?.id) setupUnitClientSelect.value = client.id;
  if (unitClientSelect && client?.id) unitClientSelect.value = client.id;
  if (userClientSelect && client?.id) userClientSelect.value = client.id;
  if (setupAreaUnitSelect && activeUnitId && Array.from(setupAreaUnitSelect.options).some((option) => option.value === activeUnitId)) {
    setupAreaUnitSelect.value = activeUnitId;
  }
}

function contextForProcess(processId) {
  const process = setupOperation.processes.find((item) => item.id === processId);
  const area = setupOperation.areas.find((item) => item.id === process?.area_id);
  const unit = knownUnits.find((item) => item.id === process?.unidade_id);
  return { process, area, unit };
}

function contextForAsset(assetId) {
  const asset = setupOperation.assets.find((item) => item.id === assetId);
  const process = setupOperation.processes.find((item) => item.id === asset?.process_id);
  const area = setupOperation.areas.find((item) => item.id === (asset?.area_id || process?.area_id));
  const unit = knownUnits.find((item) => item.id === asset?.unidade_id);
  return { asset, process, area, unit };
}

function renderSetupHierarchy() {
  if (!setupHierarchy) return;
  if (!knownUnits.length) {
    setupHierarchy.innerHTML = '<div class="muted">Crie a primeira unidade para começar.</div>';
    return;
  }
  setupHierarchy.innerHTML = knownUnits.map((unit) => {
    const areas = setupOperation.areas.filter((area) => area.unidade_id === unit.id);
    return `
      <article class="compact-card">
        <strong>${safeText(unit.nome)}</strong>
        ${areas.length ? areas.map((area) => {
          const processes = setupOperation.processes.filter((process) => process.area_id === area.id);
          return `
            <div class="setup-tree-row"><span>Área</span>${safeText(area.nome)}</div>
            ${processes.map((process) => {
              const assets = setupOperation.assets.filter((asset) => asset.process_id === process.id);
              return `
                <div class="setup-tree-row nested"><span>Processo</span>${safeText(process.nome)}</div>
                ${assets.map((asset) => `<div class="setup-tree-row nested deep"><span>Ativo</span>${safeText(asset.nome)}</div>`).join("")}
              `;
            }).join("")}
          `;
        }).join("") : '<div class="muted">Nenhuma área criada nesta unidade.</div>'}
      </article>
    `;
  }).join("");
}

function renderSetupCameraLinks() {
  if (!setupCameraLinks) return;
  const linked = knownCameras.filter((camera) => camera.asset_id);
  setupCameraLinks.innerHTML = linked.length ? linked.map((camera) => {
    const { asset, process, area } = contextForAsset(camera.asset_id);
    return `
      <article class="compact-card">
        <strong>${safeText(camera.nome)}</strong>
        <span>${safeText(asset?.nome || "Ativo")} · ${safeText(area?.nome || "Área")} → ${safeText(process?.nome || "Processo")}</span>
      </article>
    `;
  }).join("") : '<div class="muted">Nenhuma câmera associada ao contexto operacional.</div>';
}

function renderSetupCapabilities() {
  if (!setupCapabilities) return;
  setupCapabilities.innerHTML = setupOperation.capabilities.map((capability) => `
    <article class="compact-card">
      <strong>${safeText(capability.label)}</strong>
      <span>${safeText(capability.description)} · ${capability.supported ? "Disponível" : "Em desenvolvimento"}</span>
    </article>
  `).join("");
}

function renderSetupReadiness() {
  if (!setupReadiness) return;
  if (!setupOperation.asset_status.length) {
    setupReadiness.innerHTML = '<div class="muted">Crie um ativo para acompanhar o status de configuração.</div>';
    return;
  }
  setupReadiness.innerHTML = setupOperation.asset_status.map((item) => `
    <article class="compact-card">
      <strong>${safeText(item.asset_name)}</strong>
      <span>${item.ready ? "Pronto para monitorar" : "Configuração incompleta"}</span>
      ${item.missing?.length ? `<div class="muted">Falta: ${item.missing.map(safeText).join(", ")}.</div>` : '<div class="muted">Câmera, zonas e monitor ativos.</div>'}
    </article>
  `).join("");
}

function renderInstallChecklist(readiness) {
  if (!setupInstallChecklist) return;
  const checks = readiness?.checks || [];
  if (!checks.length) {
    setupInstallChecklist.innerHTML = '<div class="muted">Checklist indisponível.</div>';
    return;
  }
  setupInstallChecklist.innerHTML = checks.map((item) => `
    <article class="compact-card">
      <strong>${safeText(item.label)}</strong>
      <span>${safeText(item.status)} · ${safeText(item.detail)}</span>
    </article>
  `).join("");
  if (alertSetupStatus) {
    const alertCheck = checks.find((item) => item.label === "Alertas");
    alertSetupStatus.textContent = alertCheck ? `${alertCheck.status}: ${alertCheck.detail}` : "Alertas ainda não verificados.";
    alertSetupStatus.classList.toggle("offline", alertCheck?.status !== "PASS");
  }
  renderSetupReadinessConclusion(checks);
}

function renderSetupReadinessConclusion(checks) {
  if (!setupReadinessConclusion) return;
  const pending = checks.filter((item) => item.status !== "PASS");
  if (!checks.length) {
    setupReadinessConclusion.textContent = "FALTAM ETAPAS: checklist indisponível.";
    setupReadinessConclusion.classList.add("offline");
    return;
  }
  if (!pending.length) {
    setupReadinessConclusion.textContent = "CAMPEX PRONTA PARA OPERAR";
    setupReadinessConclusion.classList.remove("offline");
    return;
  }
  setupReadinessConclusion.textContent = `FALTAM ${pending.length} ETAPA${pending.length === 1 ? "" : "S"}: ${pending.map((item) => item.label).join(", ")}.`;
  setupReadinessConclusion.classList.add("offline");
}

function renderSetupJourney() {
  if (setupCompanySummary) {
    const client = currentClient();
    const unit = activeUnit() || resolveActiveUnit();
    setupCompanySummary.innerHTML = client && unit
      ? `<article class="setup-summary-row"><strong>${safeText(client.nome)}</strong><span>${safeText(unit.nome)} · ${safeText(unit.timezone || "America/Sao_Paulo")}</span><a href="#cliente">Editar</a></article>`
      : '<div class="muted">Crie empresa e unidade no First Run ou na criação adicional abaixo.</div>';
  }
  if (setupOperationSummary) {
    if (!setupOperation.assets.length) {
      setupOperationSummary.innerHTML = '<div class="muted">Crie a sequência Área → Processo → Ativo para liberar câmera e monitoramento.</div>';
    } else {
      setupOperationSummary.innerHTML = setupOperation.assets.map((asset) => {
        const { process, area, unit } = contextForAsset(asset.id);
        return `
          <article class="setup-summary-row">
            <strong>${safeText(asset.nome)}</strong>
            <span>${safeText(unit?.nome || "Unidade")} → ${safeText(area?.nome || "Área")} → ${safeText(process?.nome || "Processo")}</span>
          </article>
        `;
      }).join("");
    }
  }
  if (setupCameraGate) {
    const hasAsset = setupOperation.assets.length > 0;
    const linked = knownCameras.filter((camera) => camera.asset_id);
    setupCameraGate.innerHTML = hasAsset
      ? linked.length
        ? linked.map((camera) => `<article class="setup-summary-row"><strong>${safeText(camera.nome)}</strong><span>${camera.status || "status técnico indisponível"} · associada ao ativo</span><a href="#cameras">Editar</a></article>`).join("")
        : '<div class="muted">Ativo criado. Cadastre ou associe uma câmera abaixo.</div>'
      : '<div class="muted">Crie um ativo antes de cadastrar câmera na jornada principal.</div>';
  }
  document.body.dataset.setupHasAsset = setupOperation.assets.length ? "true" : "false";
  renderSettingsOverview();
}

async function loadSetupOperation() {
  if (!setupHierarchy) return;
  try {
    setupOperation = await requestJson("/setup/operation");
    knownClients = setupOperation.clientes || knownClients;
    knownUnits = setupOperation.unidades || knownUnits;
    resolveActiveUnit();
    knownCameras = setupOperation.cameras || knownCameras;
    fillSetupSelects();
    renderSetupHierarchy();
    renderSetupCameraLinks();
    renderSetupCapabilities();
    renderSetupReadiness();
    renderInstallChecklist(setupOperation.readiness);
    renderSetupJourney();
    renderSettingsOverview();
    setSetupStatus("Configuração carregada");
  } catch (error) {
    setSetupStatus(`Setup indisponível: ${error.message}`, true);
  }
}

async function checkFirstRun() {
  if (!firstRunPanel) return;
  try {
    const status = await requestJson("/first-run/status");
    const available = Boolean(status.available);
    setFirstRunMode(available);
    if (firstRunStatus) firstRunStatus.textContent = status.message;
    if (available) {
      if (loginStatus) {
        loginStatus.textContent = "Instalação nova: crie o primeiro administrador antes de entrar.";
      }
      firstRunPanel.scrollIntoView({ behavior: "smooth", block: "start" });
      window.setTimeout(() => firstRunAdminEmail?.focus({ preventScroll: true }), 250);
    }
  } catch (error) {
    setFirstRunMode(false);
    if (firstRunStatus) firstRunStatus.textContent = `First Run indisponível: ${error.message}`;
  }
}

function setFirstRunMode(enabled) {
  firstRunPanel.hidden = !enabled;
  if (connectedAccountPanel) connectedAccountPanel.hidden = true;
  if (signupForm) signupForm.hidden = true;
  if (loginHeader) loginHeader.hidden = enabled;
  if (loginForm) {
    loginForm.hidden = enabled;
    loginForm.querySelectorAll("input, button").forEach((control) => {
      control.disabled = enabled;
    });
  }
}

function setupRoleLabel(role) {
  const labels = {
    admin_campex: "Administrador Campex",
    admin_cliente: "Administrador",
    operador: "Operador",
    visualizador: "Visualizador",
  };
  return labels[role] || role || "Usuário";
}

function renderConnectedAccount(user) {
  const authenticated = Boolean(user);
  currentAuthUser = user || null;
  document.body.classList.toggle("cx-authenticated", authenticated);
  if (loginPanel) loginPanel.hidden = authenticated;
  if (loginHeader) loginHeader.hidden = authenticated;
  if (loginForm) loginForm.hidden = authenticated;
  if (signupForm) signupForm.hidden = true;
  if (connectedAccountPanel) connectedAccountPanel.hidden = !authenticated;
  if (!authenticated) {
    setText(profileName, "Entrar");
    setText(profileRole, "Sessão necessária");
    setText(profileAvatar, "C");
    setText(accountSettingsPhoto, "C");
    setText(accountSettingsName, "Sessão necessária");
    setText(accountSettingsEmail, "Entre para acessar sua conta.");
    setText(accountSettingsRole, "Sem autenticação");
    renderSettingsOverview();
    return;
  }
  const name = user.nome || user.email || "Usuário Campex";
  const email = user.email || "-";
  const role = setupRoleLabel(user.role || user.funcao);
  if (connectedAccountName) connectedAccountName.textContent = name;
  if (connectedAccountEmail) connectedAccountEmail.textContent = email;
  if (connectedAccountRole) connectedAccountRole.textContent = role;
  setText(accountSettingsName, name);
  setText(accountSettingsEmail, email);
  setText(accountSettingsRole, role);
  setText(profileName, name);
  setText(profileRole, user.cliente_nome || user.empresa_nome || "Indústria Alpha");
  setText(profileAvatar, initialsFromText(name));
  setText(accountSettingsPhoto, initialsFromText(name));
  if (loginStatus) loginStatus.textContent = "";
  renderSettingsOverview();
}

function showSignupMode() {
  if (loginHeader) loginHeader.hidden = true;
  if (loginForm) loginForm.hidden = true;
  if (signupForm) signupForm.hidden = false;
  if (signupStatus) signupStatus.textContent = "";
  signupForm?.querySelector("input[name='nome']")?.focus();
}

function showLoginMode() {
  if (loginHeader) loginHeader.hidden = false;
  if (loginForm) loginForm.hidden = false;
  if (signupForm) signupForm.hidden = true;
  if (loginStatus) loginStatus.textContent = "Entre para acessar as configurações da operação.";
  loginForm?.querySelector("input[name='email']")?.focus();
}

function configureGoogleOAuthButton() {
  if (!googleOAuthButton) return;
  const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  googleOAuthButton.href = `/auth/oauth/google/start?next=${encodeURIComponent(next)}`;
}

function applyOAuthErrorMessage() {
  if (!loginStatus) return;
  const params = new URLSearchParams(window.location.search);
  const error = params.get("oauth_error");
  if (!error) return;
  const messages = {
    access_not_provisioned: "Este e-mail ainda não possui acesso à Campex. Solicite acesso ao administrador da sua organização.",
    google_failed: "Não foi possível entrar com o Google. Tente novamente.",
    invalid_state: "Não foi possível validar a entrada com Google. Tente novamente.",
  };
  loginStatus.textContent = messages[error] || "Não foi possível entrar com o Google. Tente novamente.";
}

function toggleLoginPassword() {
  if (!loginPasswordInput || !loginPasswordToggle) return;
  const visible = loginPasswordInput.type === "text";
  loginPasswordInput.type = visible ? "password" : "text";
  loginPasswordToggle.setAttribute("aria-pressed", String(!visible));
  loginPasswordToggle.setAttribute("aria-label", visible ? "Mostrar senha" : "Ocultar senha");
}

function openOrganizationEditor() {
  if (!organizationDialog) return;
  const client = currentClient();
  if (clientForm && client) {
    const nome = clientForm.querySelector("input[name='nome']");
    const documento = clientForm.querySelector("input[name='documento']");
    if (nome) nome.value = client.nome || "";
    if (documento) documento.value = client.documento || "";
  }
  if (typeof organizationDialog.showModal === "function") {
    organizationDialog.showModal();
  } else {
    organizationDialog.setAttribute("open", "");
  }
  clientForm?.querySelector("input[name='nome']")?.focus();
}

function closeOrganizationEditor() {
  if (!organizationDialog) return;
  if (typeof organizationDialog.close === "function") {
    organizationDialog.close();
  } else {
    organizationDialog.removeAttribute("open");
  }
}

async function logout() {
  await requestJson("/auth/logout", { method: "POST" }).catch(() => ({ ok: false }));
  window.location.href = "/login";
}

async function signup(event) {
  event.preventDefault();
  if (!signupForm || !signupStatus) return;
  signupStatus.textContent = "Criando conta...";
  try {
    const data = new FormData(signupForm);
    const payload = await requestJson("/auth/signup", {
      method: "POST",
      body: JSON.stringify({
        nome: String(data.get("nome") || ""),
        email: String(data.get("email") || ""),
        senha: String(data.get("senha") || ""),
        empresa_nome: String(data.get("empresa_nome") || ""),
      }),
    });
    renderConnectedAccount(payload.user);
    signupForm.reset();
    window.location.href = payload.next || "/operations-view?view=home";
  } catch (error) {
    signupStatus.textContent = `Não foi possível criar a conta: ${error.message}`;
  }
}

async function completeFirstRun(event) {
  event.preventDefault();
  if (!firstRunForm || !firstRunStatus) return;
  firstRunStatus.textContent = "Criando primeira instalação...";
  try {
    const payload = await requestJson("/first-run/complete", {
      method: "POST",
      body: JSON.stringify(formPayload(firstRunForm)),
    });
    firstRunStatus.textContent = `Instalação criada. Administrador: ${payload.user?.email || "criado"}.`;
    setFirstRunMode(false);
    renderConnectedAccount(payload.user || null);
    window.history.replaceState({}, document.title, window.location.pathname);
    firstRunForm.reset();
    await Promise.all([loadConfigData(), loadCameras(), loadSetupOperation(), loadRecipients(), loadDeliveries()]);
  } catch (error) {
    firstRunStatus.textContent = `Erro no First Run: ${error.message}`;
  }
}

async function saveSetupUnit(event) {
  event.preventDefault();
  await requestJson("/unidades", {
    method: "POST",
    body: JSON.stringify(formPayload(setupUnitForm)),
  });
  setupUnitForm.reset();
  await Promise.all([loadConfigData(), loadSetupOperation()]);
}

async function saveSetupArea(event) {
  event.preventDefault();
  const payload = formPayload(setupAreaForm);
  if (!payload.unidade_id) throw new Error("Selecione a unidade da área.");
  await requestJson("/setup/areas", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  setupAreaForm.reset();
  await loadSetupOperation();
}

async function saveSetupProcess(event) {
  event.preventDefault();
  const payload = formPayload(setupProcessForm);
  const area = setupOperation.areas.find((item) => item.id === payload.area_id);
  if (!area) throw new Error("Selecione a área do processo.");
  payload.unidade_id = area.unidade_id;
  await requestJson("/setup/processes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  setupProcessForm.reset();
  await loadSetupOperation();
}

async function saveSetupAsset(event) {
  event.preventDefault();
  const payload = formPayload(setupAssetForm);
  const { process, area } = contextForProcess(payload.process_id);
  if (!process) throw new Error("Selecione o processo do ativo.");
  payload.unidade_id = process.unidade_id;
  payload.area_id = area?.id || process.area_id;
  await requestJson("/setup/assets", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  setupAssetForm.reset();
  await loadSetupOperation();
}

async function saveSetupCameraContext(event) {
  event.preventDefault();
  const payload = formPayload(setupCameraContextForm);
  const { asset, process, area } = contextForAsset(payload.asset_id);
  if (!payload.camera_id || !asset) throw new Error("Selecione câmera e ativo.");
  await requestJson(`/setup/cameras/${payload.camera_id}/context`, {
    method: "POST",
    body: JSON.stringify({
      asset_id: asset.id,
      process_id: process?.id || asset.process_id,
      area_context_id: area?.id || asset.area_id,
    }),
  });
  setupCameraContextForm.reset();
  await Promise.all([loadCameras(), loadSetupOperation()]);
}

function activeAreaByType(typeNames) {
  return currentAreas.find((area) => area.ativa && typeNames.includes(area.tipo));
}

async function saveSetupMonitor(event) {
  event.preventDefault();
  const payload = formPayload(setupMonitorForm);
  if (!payload.camera_id) throw new Error("Selecione a câmera do monitor.");
  if (currentCameraId !== payload.camera_id) {
    const camera = knownCameras.find((item) => item.id === payload.camera_id);
    await openCamera(payload.camera_id, camera?.nome || "Câmera");
  }
  const machineRegion = activeAreaByType(["machine_region"]);
  const operatorZone = activeAreaByType(["operator_zone", "workstation", "work_area"]);
  if (!machineRegion || !operatorZone) {
    throw new Error("Desenhe e salve uma região da máquina e uma zona do operador antes de ativar o monitor.");
  }
  await requestJson(`/cameras/${payload.camera_id}/machine-monitors`, {
    method: "POST",
    body: JSON.stringify({
      nome: payload.nome,
      ativo: true,
      machine_polygon: machineRegion.pontos,
      operator_polygon: operatorZone.pontos,
      stop_seconds: Number(payload.stop_seconds || 30),
      operator_absence_seconds: Number(payload.operator_absence_seconds || 300),
      stopped_with_operator_seconds: Number(payload.stopped_with_operator_seconds || 120),
    }),
  });
  setupMonitorForm.reset();
  await Promise.all([loadMachines(), loadMachineConfigList(), loadSetupOperation()]);
}

function focusLoginFromHash() {
  if (window.location.hash !== "#login") return;
  const loginSection = document.querySelector("#login");
  const emailInput = loginForm?.querySelector("input[name='email']");
  if (!loginSection || !emailInput) return;
  loginSection.scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => emailInput.focus({ preventScroll: true }), 250);
}

function cleanPayload(includeIdentity) {
  const data = new FormData(form);
  const payload = {};
  for (const [key, value] of data.entries()) {
    const text = String(value).trim();
    if (text) payload[key] = text;
  }
  if (payload.porta_rtsp) payload.porta_rtsp = Number(payload.porta_rtsp);
  if (!includeIdentity) {
    delete payload.nome;
    delete payload.cliente_id;
    delete payload.unidade_id;
    delete payload.edge_id;
  }
  if (includeIdentity) {
    delete payload.cliente_id;
    payload.ativa = Boolean(payload.ativa);
  }
  return payload;
}

function showResult(payload) {
  const online = Boolean(payload.compativel);
  result.className = `result ${online ? "online" : "offline"}`;
  result.textContent = [
    `Status: ${online ? "Online" : "Offline"}`,
    `Conexão realizada: ${payload.conexao_realizada ? "sim" : "não"}`,
    `Vídeo recebido: ${payload.video_recebido ? "sim" : "não"}`,
    `Resolução: ${payload.resolucao || "indisponível"}`,
    `FPS: ${payload.fps ?? "indisponível"}`,
    `Tipo: ${payload.tipo_conexao || "rtsp"}`,
    `Referência segura: ${payload.referencia_segura || payload.url_rtsp || "indisponível"}`,
    payload.motivo_erro ? `Erro: ${payload.motivo_erro}` : "",
  ].filter(Boolean).join("\n");
}

async function requestJson(url, options) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : { detail: await response.text() };
  if (!response.ok) {
    const detail = payload.detail || `Erro HTTP ${response.status}`;
    throw new Error(friendlyError(typeof detail === "string" ? detail : JSON.stringify(detail)));
  }
  if (!isJson) {
    throw new Error("A API respondeu em formato inesperado.");
  }
  return payload;
}

async function testConnection() {
  result.className = "result muted";
  result.textContent = "Testando conexão...";
  try {
    const payload = await requestJson("/cameras/test-connection", {
      method: "POST",
      body: JSON.stringify(cleanPayload(false)),
    });
    showResult(payload);
    if (payload.compativel && payload.video_recebido) {
      lastRtspPayload = cleanPayload(true);
      lastRtspPayload.nome = lastRtspPayload.nome || "Live View";
      sessionStorage.setItem("campex_live_view_source", JSON.stringify(lastRtspPayload));
    }
  } catch (error) {
    result.className = "result offline";
    result.innerHTML = setupErrorState("Câmera offline no teste", error, "Testar novamente");
  }
}

function openLiveView() {
  const payload = lastRtspPayload || cleanPayload(true);
  if (!payload.rtsp_url && !payload.host) {
    result.className = "result offline";
    result.textContent = "Teste a conexão RTSP antes de abrir a Live View.";
    return;
  }
  payload.nome = payload.nome || "Live View";
  sessionStorage.setItem("campex_live_view_source", JSON.stringify(payload));
  window.open("/live-view", "_blank");
}

async function saveCamera(event) {
  event.preventDefault();
  result.className = "result muted";
  result.textContent = "Enviando configuração ao Campex Edge...";
  try {
    const body = cleanPayload(true);
    if (!body.edge_id) throw new Error("Selecione o Campex Edge responsável por esta câmera.");
    const payload = await requestJson("/cameras/rtsp", {
      method: "POST",
      body: JSON.stringify(body),
    });
    result.className = "result online";
    result.textContent = "Configuração enviada ao Campex Edge. Aguardando conexão.";
    if (lastRtspPayload) {
      lastRtspPayload.camera_id = payload.id;
      lastRtspPayload.nome = payload.camera?.nome || lastRtspPayload.nome;
      sessionStorage.setItem("campex_live_view_source", JSON.stringify(lastRtspPayload));
    }
    await loadCameras();
    await loadSetupOperation();
    form.reset();
    form.elements.porta_rtsp.value = 554;
    if (cameraUnitSelect && activeUnitId) cameraUnitSelect.value = activeUnitId;
    fillCameraEdgeSelect();
  } catch (error) {
    result.className = "result offline";
    result.innerHTML = setupErrorState("Não foi possível cadastrar a câmera", error, "Tentar novamente");
  }
}

function renderCameras(cameras) {
  if (!cameras.length) {
    cameraList.innerHTML = '<div class="cx-setup-empty"><strong>Nenhuma câmera cadastrada.</strong><p>Cadastre uma câmera RTSP para associar ao contexto operacional.</p></div>';
    return;
  }
  cameraList.innerHTML = cameras.map((camera) => `
    <article class="camera-card cx-setup-list-row">
      <div class="cx-setup-row-main">
        <strong>${safeText(camera.nome)}</strong>
        <span>${safeText(camera.resolucao || "Resolução indisponível")} · ${camera.fps ?? "FPS indisponível"}</span>
      </div>
      <div>${setupStatusPill(camera.status === "online" ? "Online" : camera.status || "Offline")}</div>
      <div><span>Edge</span><strong>${camera.ativa ? "Ativa no runtime" : "Desativada"}</strong></div>
      <div><span>Último frame</span><strong>${safeText(camera.ultimo_frame || "Nunca")}</strong></div>
      <div class="camera-actions">
        <button type="button" data-action="open" data-camera-id="${camera.id}" data-camera-name="${safeText(camera.nome)}">Abrir</button>
        <button type="button" data-action="live-view" data-camera-id="${camera.id}" data-camera-name="${safeText(camera.nome)}">Live</button>
        <button type="button" data-action="stop" data-camera-id="${camera.id}">Parar</button>
        <button type="button" data-action="toggle-active" data-camera-id="${camera.id}" data-active="${camera.ativa}">
          ${camera.ativa ? "Desativar no Edge" : "Ativar no Edge"}
        </button>
      </div>
    </article>
  `).join("");
}

async function loadCameras() {
  const cameras = await requestJson("/cameras/estado");
  knownCameras = cameras;
  renderCameras(cameras);
  fillSelect(machineCameraSelect, cameras, "Selecione uma câmera");
  fillSetupSelects();
  renderSetupJourney();
  renderSettingsOverview();
  if (cameras.length === 1 && !currentCameraId) {
    openCamera(cameras[0].id, cameras[0].nome).catch(() => {});
  }
}

async function loadConfigData() {
  const [clients, units, users, edges] = await Promise.all([
    requestJson("/clientes").catch(() => []),
    requestJson("/unidades").catch(() => []),
    requestJson("/users").catch(() => []),
    requestJson("/edge-devices").catch(() => []),
  ]);
  knownClients = clients;
  knownUnits = units;
  knownUsers = users;
  knownEdges = edges;
  resolveActiveUnit();
  fillSelect(unitClientSelect, clients, "Organização padrão ou selecione");
  fillSelect(userClientSelect, clients, "Organização padrão ou selecione");
  fillSelect(cameraUnitSelect, units, "Usar unidade padrão");
  if (cameraUnitSelect && activeUnitId && Array.from(cameraUnitSelect.options).some((option) => option.value === activeUnitId)) {
    cameraUnitSelect.value = activeUnitId;
  }
  fillCameraEdgeSelect();
  fillSetupSelects();
  clientList.innerHTML = clients.length ? clients.map((client) => `
    <article class="compact-card cx-setup-list-row">
      <strong>${safeText(client.nome)}</strong>
      <span>${safeText(client.documento || "sem documento")} · ${safeText(client.status || "ativo")}</span>
    </article>
  `).join("") : '<div class="muted">Nenhum cliente cadastrado.</div>';
  unitList.innerHTML = units.length ? units.map((unit) => `
    <article class="compact-card cx-setup-list-row">
      <strong>${safeText(unit.nome)}</strong>
      <span>${safeText(unit.localizacao || "sem endereço")} · ${safeText(unit.timezone || "America/Sao_Paulo")}</span>
    </article>
  `).join("") : '<div class="muted">Nenhuma unidade cadastrada.</div>';
  userList.innerHTML = users.length ? users.map((user) => `
    <article class="compact-card cx-setup-list-row">
      <strong>${safeText(user.nome || user.email)}</strong>
      <span>${safeText(user.email)} · ${safeText(user.role)} · ${user.ativo ? "ativo" : "inativo"}</span>
    </article>
  `).join("") : '<div class="muted">Nenhum usuário cadastrado.</div>';
  renderSetupJourney();
  renderSettingsOverview();
}

function setViewerMessage(text, status = "offline") {
  viewerStage.classList.toggle("online", status === "online");
  viewerMessage.textContent = text;
  viewerStatus.textContent = status;
  viewerStatus.classList.toggle("offline", status !== "online");
}

function updateViewerStatus(payload) {
  const status = payload.status || "offline";
  const reconnecting = status === "reconectando" || status === "conectando";
  viewerStatus.textContent = status;
  viewerStatus.classList.toggle("offline", status !== "online");
  viewerStage.classList.toggle("online", status === "online");
  viewerResolution.textContent = payload.width && payload.height ? `${payload.width}x${payload.height}` : "indisponível";
  viewerFps.textContent = payload.fps ?? "indisponível";
  viewerLastFrame.textContent = payload.last_frame_at || "nunca";
  viewerAiStatus.textContent = payload.ai_status || "inativa";
  viewerPeopleCount.textContent = payload.people_count ?? 0;
  viewerAreaName.textContent = payload.area_nome || "nenhuma";
  viewerAreaState.textContent = payload.area_estado || "livre";
  viewerAreaPeople.textContent = payload.pessoas_na_area ?? 0;
  viewerAreaIds.textContent = payload.ids_na_area && payload.ids_na_area.length ? payload.ids_na_area.join(", ") : "-";
  viewerMachineState.textContent = payload.machine_state || "indisponível";
  viewerMachineMotion.textContent = payload.machine_motion ?? "-";
  if (payload.incident_active) {
    activeIncident.classList.remove("muted");
    activeIncident.textContent = `Ocorrência ativa desde ${payload.incident_started_at} | duração ${payload.incident_duration}s | pessoas na área: ${payload.incident_people}`;
  } else {
    activeIncident.classList.add("muted");
    activeIncident.textContent = "Nenhuma ocorrência ativa.";
  }
  viewerClock.textContent = new Date().toLocaleString();
  if (reconnecting) {
    viewerMessage.textContent = "Tentando reconectar...";
  } else if (status !== "online") {
    viewerMessage.textContent = payload.error || "Câmera offline. Você pode tentar iniciar novamente.";
  }
}

async function pollStatus() {
  if (!currentCameraId) return;
  try {
    const payload = await requestJson(`/cameras/${currentCameraId}/status`);
    updateViewerStatus(payload);
  } catch (error) {
    setViewerMessage(`Erro ao consultar status: ${error.message}`, "offline");
  }
}

function startStatusPolling() {
  if (statusTimer) clearInterval(statusTimer);
  statusTimer = setInterval(pollStatus, 1500);
}

function isCloudFrontend() {
  return window.location.port === "8787" || !["localhost", "127.0.0.1", "0.0.0.0"].includes(window.location.hostname);
}

function refreshCloudLatestFrame() {
  if (!currentCameraId) return;
  liveImage.src = `/cameras/${encodeURIComponent(currentCameraId)}/latest-frame?t=${Date.now()}`;
}

function startLatestFramePolling() {
  if (latestFrameTimer) clearInterval(latestFrameTimer);
  latestFrameTimer = setInterval(refreshCloudLatestFrame, 3000);
}

async function openCamera(cameraId, cameraName) {
  currentCameraId = cameraId;
  currentCameraName = cameraName;
  viewerTitle.textContent = cameraName;
  setViewerMessage(isCloudFrontend() ? "Aguardando primeiro frame do Campex Edge." : "Conectando...", "conectando");
  document.querySelector(".viewer").scrollIntoView({ behavior: "smooth", block: "start" });
  if (isCloudFrontend()) {
    liveImage.onload = () => setViewerMessage("Atualização recente do Campex Edge.", "online");
    liveImage.onerror = () => {
      viewerStage.classList.remove("online");
      viewerMessage.textContent = "Aguardando primeiro frame do Campex Edge.";
    };
    refreshCloudLatestFrame();
    startLatestFramePolling();
  } else {
    await requestJson(`/cameras/${cameraId}/start`, { method: "POST" });
    liveImage.src = `/cameras/${cameraId}/stream?ts=${Date.now()}`;
    liveImage.onerror = () => {
      viewerStage.classList.remove("online");
      viewerMessage.textContent = "Sem imagem no momento. Tentando reconectar...";
    };
  }
  await pollStatus();
  startStatusPolling();
  await loadAreas();
  await loadMachines();
  await loadEvents();
  await loadOperations();
  drawAreaCanvas();
  startEventPolling();
}

async function stopCamera(cameraId) {
  if (latestFrameTimer) {
    clearInterval(latestFrameTimer);
    latestFrameTimer = null;
  }
  if (isCloudFrontend()) {
    if (currentCameraId === cameraId) {
      liveImage.removeAttribute("src");
      setViewerMessage("Visualização de snapshot encerrada.", "offline");
      await pollStatus();
    }
    return;
  }
  await requestJson(`/cameras/${cameraId}/stop`, { method: "POST" });
  if (currentCameraId === cameraId) {
    liveImage.removeAttribute("src");
    setViewerMessage("Transmissão parada.", "offline");
    await pollStatus();
  }
}

function canvasSize() {
  const rect = areaCanvas.getBoundingClientRect();
  areaCanvas.width = Math.max(1, Math.round(rect.width));
  areaCanvas.height = Math.max(1, Math.round(rect.height));
  return rect;
}

function drawPolygon(ctx, points, color, fill) {
  if (!points.length) return;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = point.x * areaCanvas.width;
    const y = point.y * areaCanvas.height;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  if (points.length >= 3) ctx.closePath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.stroke();
  if (fill && points.length >= 3) {
    ctx.fillStyle = fill;
    ctx.fill();
  }
  points.forEach((point) => {
    ctx.beginPath();
    ctx.arc(point.x * areaCanvas.width, point.y * areaCanvas.height, 5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  });
}

function drawAreaCanvas() {
  canvasSize();
  const ctx = areaCanvas.getContext("2d");
  ctx.clearRect(0, 0, areaCanvas.width, areaCanvas.height);
  currentAreas.filter((area) => area.ativa).forEach((area) => {
    drawPolygon(ctx, area.pontos, "#22c55e", "rgba(34, 197, 94, 0.12)");
  });
  currentMachines.filter((machine) => machine.ativo).forEach((machine) => {
    drawPolygon(ctx, machine.machine_polygon, "#38bdf8", "rgba(56, 189, 248, 0.10)");
    drawPolygon(ctx, machine.operator_polygon, "#f97316", "rgba(249, 115, 22, 0.10)");
  });
  if (drawingArea) {
    drawPolygon(ctx, draftPoints, "#f59e0b", "rgba(245, 158, 11, 0.12)");
  }
  if (drawingMachine) {
    drawPolygon(ctx, draftMachinePoints, "#38bdf8", "rgba(56, 189, 248, 0.12)");
    drawPolygon(ctx, draftOperatorPoints, "#f97316", "rgba(249, 115, 22, 0.12)");
  }
}

async function loadAreas() {
  if (!currentCameraId) return;
  currentAreas = await requestJson(`/cameras/${currentCameraId}/areas`);
  renderAreas();
  drawAreaCanvas();
}

function renderAreas() {
  if (!currentAreas.length) {
    areaList.innerHTML = '<div class="muted">Nenhuma área criada para esta câmera.</div>';
    return;
  }
  areaList.innerHTML = currentAreas.map((area) => `
    <div class="area-card">
      <strong>${area.nome}</strong>
      <div>Tipo: ${area.tipo}</div>
      <div>Status: ${area.ativa ? "ativa" : "inativa"}</div>
      <div>Pontos: ${area.pontos.length}</div>
      <div class="actions">
        <button type="button" data-area-action="${area.ativa ? "deactivate" : "activate"}" data-area-id="${area.id}">
          ${area.ativa ? "Desativar" : "Ativar"}
        </button>
        <button type="button" data-area-action="delete" data-area-id="${area.id}">Excluir</button>
      </div>
    </div>
  `).join("");
}

async function loadMachines() {
  if (!currentCameraId) return;
  currentMachines = await requestJson(`/cameras/${currentCameraId}/machine-monitors`);
  renderMachines();
  drawAreaCanvas();
}

function renderMachines() {
  if (!currentMachines.length) {
    machineList.innerHTML = '<div class="muted">Nenhuma máquina cadastrada para esta câmera.</div>';
    return;
  }
  machineList.innerHTML = currentMachines.map((machine) => `
    <div class="area-card">
      <strong>${machine.nome}</strong>
      <div>Estado: ${machine.current_state}</div>
      <div>Movimento: ${machine.current_motion ?? "-"}</div>
      <div>Limite: ${machine.motion_threshold ?? machine.motion_sensitivity}</div>
      <div>Calibração: ${machine.calibration_status}</div>
      <div>Resultado: ${machine.calibration_result || "INVALID"}</div>
      <div>Separação: ${machine.separation_score ?? "-"}</div>
      <div>Status: ${machine.ativo ? "ativa" : "inativa"}</div>
      <div class="actions">
        <button type="button" data-machine-action="calibrate-active" data-machine-id="${machine.id}">Calibrar ativa</button>
        <button type="button" data-machine-action="calibrate-stopped" data-machine-id="${machine.id}">Calibrar parada</button>
        <button type="button" data-machine-action="calibration-status" data-machine-id="${machine.id}">Ver calibração</button>
        <button type="button" data-machine-action="${machine.ativo ? "deactivate" : "activate"}" data-machine-id="${machine.id}">
          ${machine.ativo ? "Desativar" : "Ativar"}
        </button>
        <button type="button" data-machine-action="delete" data-machine-id="${machine.id}">Excluir</button>
      </div>
    </div>
  `).join("");
}

async function loadOperations() {
  const payload = await requestJson("/operations");
  if (!payload.machines.length) {
    operationsList.innerHTML = '<div class="muted">Nenhuma máquina em Operations.</div>';
    return;
  }
  operationsList.innerHTML = payload.machines.map((item) => `
    <article class="event-card">
      <strong>${item.monitor.nome}</strong>
      <div>Estado atual: ${item.monitor.current_state}</div>
      <div>Operador: ${item.monitor.operator_present ? "presente" : "ausente"}</div>
      <div>Paradas: ${item.paradas}</div>
      <div>Tempo parado: ${Math.round(item.tempo_total_parado)}s</div>
      <div>Média: ${Math.round(item.duracao_media)}s</div>
      <div>Maior parada: ${Math.round(item.maior_parada)}s</div>
      <div>Operador ausente: ${item.operador_ausente_percentual}%</div>
    </article>
  `).join("");
}

async function loadMachineConfigList() {
  if (!knownCameras.length) {
    machineConfigList.innerHTML = '<div class="muted">Cadastre uma câmera antes de criar máquinas.</div>';
    return;
  }
  const groups = await Promise.all(knownCameras.map(async (camera) => {
    const monitors = await requestJson(`/cameras/${camera.id}/machine-monitors`).catch(() => []);
    return { camera, monitors };
  }));
  const rows = groups.flatMap((group) => group.monitors.map((monitor) => ({ camera: group.camera, monitor })));
  machineConfigList.innerHTML = rows.length ? rows.map(({ camera, monitor }) => `
    <article class="compact-card">
      <strong>${monitor.nome}</strong>
      <span>${camera.nome} · ${monitor.ativo ? "ativa" : "inativa"} · ${monitor.calibration_status}</span>
    </article>
  `).join("") : '<div class="muted">Nenhuma máquina cadastrada.</div>';
}

async function saveClient(event) {
  event.preventDefault();
  const client = currentClient();
  if (!client?.id) {
    throw new Error("Nenhuma organização atual foi carregada para edição.");
  }
  await requestJson(`/clientes/${encodeURIComponent(client.id)}`, {
    method: "PATCH",
    body: JSON.stringify(formPayload(clientForm)),
  });
  await loadConfigData();
  closeOrganizationEditor();
}

async function saveUnit(event) {
  event.preventDefault();
  await requestJson("/unidades", {
    method: "POST",
    body: JSON.stringify(formPayload(unitForm)),
  });
  unitForm.reset();
  await loadConfigData();
}

async function saveUser(event) {
  event.preventDefault();
  await requestJson("/users", {
    method: "POST",
    body: JSON.stringify(formPayload(userForm)),
  });
  userForm.reset();
  await loadConfigData();
}

async function saveDefaultMachine(event) {
  event.preventDefault();
  machineConfigList.innerHTML = '<div class="muted">Use “Zonas, tolerâncias e monitor” acima: abra a câmera, desenhe a região da máquina e a zona do operador, depois salve o monitor.</div>';
}

async function loadEvents() {
  const params = new URLSearchParams();
  if (currentCameraId) params.set("camera_id", currentCameraId);
  const url = params.toString() ? `/eventos?${params.toString()}` : "/eventos";
  const events = await requestJson(url);
  renderEvents(events);
  updateUnackedCount(events);
}

function updateUnackedCount(events) {
  const count = events.filter((event) => event.status !== "acknowledged").length;
  unackedCount.textContent = `${count} não reconhecidos`;
}

function renderEvents(events) {
  if (!events.length) {
    eventList.innerHTML = '<div class="cx-setup-empty"><strong>Nenhuma ocorrência registrada.</strong><p>Eventos reais aparecerão aqui quando o monitoramento estiver ativo.</p></div>';
    return;
  }
  eventList.innerHTML = events.slice(0, 20).map((event) => `
    <article class="event-card cx-setup-history-card">
      <div class="cx-setup-history-head">
        <strong>${humanSetupType(event.tipo)}</strong>
        ${setupStatusPill(event.status || "Em andamento")}
      </div>
      <div class="cx-setup-history-grid">
        <span>Câmera</span><strong>${humanSetupId(event.camera_nome || event.camera_name || event.camera_id, "Câmera monitorada")}</strong>
        <span>Área</span><strong>${humanSetupId(event.area_nome || event.area_id, "Área não informada")}</strong>
        <span>Início</span><strong>${safeText(event.inicio || "Não informado")}</strong>
        <span>Duração</span><strong>${event.duracao ?? "em andamento"}</strong>
        <span>Causa</span><strong>${safeText(event.cause_category || "pendente")}</strong>
      </div>
      ${event.midia_path ? `<img src="/eventos/${event.id}/evidence" alt="Evidência da ocorrência ${event.id}" />` : ""}
      <div class="actions">
        <button type="button" data-event-action="view" data-event-id="${event.id}">Ver ocorrência</button>
        <button type="button" data-event-action="ack" data-event-id="${event.id}">Reconhecer</button>
        <button type="button" data-event-action="cause" data-event-id="${event.id}">Informar causa</button>
        ${event.replay_path ? `<a href="/eventos/${event.id}/replay" target="_blank"><button type="button">Abrir Replay Causal</button></a>` : ""}
      </div>
    </article>
  `).join("");
}

function beepOnce() {
  if (!soundToggle.checked) return;
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return;
  const ctx = new AudioContext();
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = 880;
  gain.gain.value = 0.08;
  oscillator.connect(gain);
  gain.connect(ctx.destination);
  oscillator.start();
  oscillator.stop(ctx.currentTime + 0.18);
}

function renderLiveAlerts() {
  if (!liveAlerts.length) {
    liveAlertList.innerHTML = '<div class="cx-setup-empty"><strong>Nenhum alerta em tempo real.</strong><p>Alertas aparecem aqui quando eventos críticos forem criados.</p></div>';
    return;
  }
  liveAlertList.innerHTML = liveAlerts.slice(0, 10).map((alert) => `
    <article class="alert-card new cx-setup-history-card" id="evento-${alert.event_id || alert.recipient_id}">
      <div class="cx-setup-history-head">
        <strong>${safeText(alert.titulo || "Alerta Campex")}</strong>
        ${setupStatusPill("Novo")}
      </div>
      <div class="cx-setup-history-grid">
        <span>Câmera</span><strong>${humanSetupId(alert.camera_nome || alert.camera_id, "Câmera monitorada")}</strong>
        <span>Área</span><strong>${humanSetupId(alert.area_nome || alert.area_id, "Área monitorada")}</strong>
        <span>Horário</span><strong>${safeText(alert.horario || "-")}</strong>
        <span>Pessoas</span><strong>${alert.quantidade_pessoas ?? "-"}</strong>
      </div>
      ${alert.evidence_url ? `<img src="${alert.evidence_url}" alt="Miniatura da evidência" />` : ""}
      ${alert.event_id ? `
        <div class="actions">
          <button type="button" data-event-action="view" data-event-id="${alert.event_id}">Ver ocorrência</button>
          <button type="button" data-event-action="ack" data-event-id="${alert.event_id}">Reconhecer</button>
        </div>
      ` : ""}
    </article>
  `).join("");
}

function connectRealtime() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource("/events/stream");
  eventSource.addEventListener("alert", (message) => {
    const payload = JSON.parse(message.data);
    if (payload.type === "delivery_updated") {
      loadDeliveries().catch(() => {});
      return;
    }
    if (payload.event_id && !seenAlertEvents.has(payload.event_id)) {
      seenAlertEvents.add(payload.event_id);
      beepOnce();
    }
    liveAlerts = [payload, ...liveAlerts].slice(0, 10);
    renderLiveAlerts();
    loadEvents().catch(() => {});
    loadDeliveries().catch(() => {});
  });
  eventSource.onerror = () => {
    eventSource.close();
    setTimeout(connectRealtime, 3000);
  };
}

function recipientPayload() {
  const data = new FormData(recipientForm);
  const payload = {};
  for (const [key, value] of data.entries()) {
    const text = String(value).trim();
    if (text) payload[key] = text;
  }
  payload.ativo = payload.ativo !== "false";
  if (payload.event_types) {
    payload.event_types = payload.event_types.split(",").map((item) => item.trim()).filter(Boolean);
  } else {
    payload.event_types = [];
  }
  if (!payload.camera_id) delete payload.camera_id;
  if (!payload.area_id) delete payload.area_id;
  return payload;
}

async function loadRecipients() {
  let recipients = [];
  try {
    recipients = await requestJson("/alert-recipients");
  } catch (error) {
    recipientList.innerHTML = setupErrorState("Não foi possível carregar responsáveis", error);
    return;
  }
  knownRecipients = recipients;
  renderSettingsOverview();
  if (!recipients.length) {
    recipientList.innerHTML = '<div class="cx-setup-empty"><strong>Nenhum responsável cadastrado.</strong><p>Cadastre quem deve receber alertas reais da operação.</p></div>';
    return;
  }
  recipientList.innerHTML = recipients.map((recipient) => `
    <article class="recipient-card cx-setup-list-row">
      <div class="cx-setup-row-main">
        <strong>${safeText(recipient.nome)}</strong>
        <span>${safeText(recipient.email)}</span>
      </div>
      <div>${setupStatusPill(recipient.ativo ? "Ativo" : "Inativo")}</div>
      <div><span>Escopo</span><strong>${recipient.camera_id ? "Câmera específica" : "Todas as câmeras"}</strong></div>
      <div><span>Severidade</span><strong>${safeText(recipient.severidade_minima || "low")}</strong></div>
      <div><span>Eventos</span><strong>${recipient.event_types?.length ? recipient.event_types.map(humanSetupType).join(", ") : "Todos"}</strong></div>
      <div class="actions">
        <button type="button" data-recipient-action="test" data-recipient-id="${recipient.id}">Enviar alerta de teste</button>
        <button type="button" data-recipient-action="edit" data-recipient-id="${recipient.id}">Editar</button>
        <button type="button" data-recipient-action="toggle" data-recipient-id="${recipient.id}" data-active="${recipient.ativo}">
          ${recipient.ativo ? "Desativar" : "Ativar"}
        </button>
        <button type="button" data-recipient-action="delete" data-recipient-id="${recipient.id}">Excluir</button>
      </div>
    </article>
  `).join("");
}

async function loadDeliveries() {
  let deliveries = [];
  try {
    deliveries = await requestJson("/alert-deliveries");
  } catch (error) {
    deliveryList.innerHTML = setupErrorState("Não foi possível carregar entregas", error);
    return;
  }
  if (!deliveries.length) {
    deliveryList.innerHTML = '<div class="cx-setup-empty"><strong>Nenhuma entrega registrada.</strong><p>Histórico de e-mails aparece quando alertas forem enviados.</p></div>';
    return;
  }
  const label = { pending: "Enviando", sent: "Enviado", failed: "Falhou" };
  deliveryList.innerHTML = deliveries.slice(0, 30).map((delivery) => `
    <article class="delivery-card ${delivery.status} cx-setup-history-card">
      <div class="cx-setup-history-head">
        <strong>${delivery.is_test ? "Teste de e-mail" : "Alerta de ocorrência"} · ${safeText(delivery.canal || "e-mail")}</strong>
        ${setupStatusPill(label[delivery.status] || delivery.status)}
      </div>
      <div class="cx-setup-history-grid">
        <span>Origem</span><strong>${delivery.evento_id ? "Evento operacional" : "Teste"}</strong>
        <span>Responsável</span><strong>${humanSetupId(delivery.recipient_name || delivery.destinatario || delivery.recipient_id, "Responsável configurado")}</strong>
        <span>Tentativas</span><strong>${delivery.attempts}</strong>
        <span>Última tentativa</span><strong>${safeText(delivery.last_attempt_at || "-")}</strong>
      </div>
      ${delivery.erro ? `<div class="cx-setup-error compact"><strong>Erro de entrega</strong><p>${safeText(friendlyError(delivery.erro))}</p></div>` : ""}
      ${delivery.status === "failed" ? `
        <div class="actions">
          <button type="button" data-delivery-action="retry" data-delivery-id="${delivery.id}">Tentar novamente</button>
        </div>
      ` : ""}
    </article>
  `).join("");
}

function startDeliveryPolling() {
  if (deliveryTimer) clearInterval(deliveryTimer);
  deliveryTimer = setInterval(() => {
    loadDeliveries().catch(() => {});
  }, 5000);
}

function startEventPolling() {
  if (eventTimer) clearInterval(eventTimer);
  eventTimer = setInterval(() => {
    loadEvents().catch(() => {});
  }, 3000);
}

function startDrawingArea() {
  if (!currentCameraId) {
    setViewerMessage("Abra uma câmera antes de criar uma área.", "offline");
    return;
  }
  drawingArea = true;
  draftPoints = [];
  viewerStage.classList.add("drawing");
  viewerMessage.textContent = "Clique nos pontos da área. Depois salve.";
  drawAreaCanvas();
}

function cancelDrawingArea() {
  drawingArea = false;
  draftPoints = [];
  viewerStage.classList.remove("drawing");
  drawAreaCanvas();
}

async function saveArea() {
  if (!currentCameraId || draftPoints.length < 3) {
    setViewerMessage("A área precisa de pelo menos 3 pontos.", "online");
    return;
  }
  const nome = window.prompt("Nome da zona", "Zona operacional");
  if (!nome) return;
  const tipo = window.prompt(
    "Tipo da zona: machine_region, operator_zone, work_area, restricted_area ou dwell_area",
    "operator_zone",
  );
  if (!tipo) return;
  await requestJson(`/cameras/${currentCameraId}/areas`, {
    method: "POST",
    body: JSON.stringify({
      nome,
      tipo,
      ativa: true,
      pontos: draftPoints,
    }),
  });
  cancelDrawingArea();
  await loadAreas();
  await loadSetupOperation();
}

function startDrawingMachine() {
  if (!currentCameraId) {
    setViewerMessage("Abra uma câmera antes de adicionar máquina.", "offline");
    return;
  }
  drawingMachine = true;
  machineStep = "machine";
  draftMachinePoints = [];
  draftOperatorPoints = [];
  viewerStage.classList.add("drawing");
  viewerMessage.textContent = "Clique nos pontos da região da máquina.";
  drawAreaCanvas();
}

function nextMachineZone() {
  if (!drawingMachine || draftMachinePoints.length < 3) {
    setViewerMessage("Desenhe pelo menos 3 pontos da máquina.", "online");
    return;
  }
  machineStep = "operator";
  viewerMessage.textContent = "Agora clique nos pontos da zona do operador.";
}

async function saveMachine() {
  if (!currentCameraId || draftMachinePoints.length < 3 || draftOperatorPoints.length < 3) {
    setViewerMessage("Desenhe a região da máquina e a zona do operador.", "online");
    return;
  }
  const nome = window.prompt("Nome da máquina", "Máquina principal");
  if (!nome) return;
  await requestJson(`/cameras/${currentCameraId}/machine-monitors`, {
    method: "POST",
    body: JSON.stringify({
      nome,
      machine_polygon: draftMachinePoints,
      operator_polygon: draftOperatorPoints,
      ativo: true,
    }),
  });
  drawingMachine = false;
  draftMachinePoints = [];
  draftOperatorPoints = [];
  viewerStage.classList.remove("drawing");
  await loadMachines();
  await loadOperations();
}

async function setAnalysis(enabled) {
  if (!currentCameraId) {
    setViewerMessage("Abra uma câmera antes de ligar a análise.", "offline");
    return;
  }
  const action = enabled ? "start" : "stop";
  const payload = await requestJson(`/cameras/${currentCameraId}/analysis/${action}`, { method: "POST" });
  updateViewerStatus(payload);
}

async function checkApi() {
  try {
    await requestJson("/health");
    apiStatus.textContent = "API online";
    apiStatus.classList.remove("offline");
  } catch (_error) {
    apiStatus.textContent = "API offline";
    apiStatus.classList.add("offline");
  }
}

function renderSignedOutSetupState() {
  renderCameras([]);
  renderEvents([]);
  renderLiveAlerts();
  recipientList.innerHTML = '<div class="cx-setup-empty"><strong>Entre para configurar responsáveis.</strong><p>Destinatários de alerta ficam disponíveis após autenticação.</p></div>';
  deliveryList.innerHTML = '<div class="cx-setup-empty"><strong>Entre para consultar histórico.</strong><p>Entregas de e-mail e alertas são protegidos pela sessão.</p></div>';
  systemHealth.className = "cx-setup-empty";
  systemHealth.innerHTML = '<strong>Saúde protegida pela sessão.</strong><p>Entre para consultar banco, câmeras, IA e armazenamento.</p>';
  pilotChecklist.className = "cx-setup-empty";
  pilotChecklist.innerHTML = '<strong>Checklist protegido pela sessão.</strong><p>O status do piloto aparece após login.</p>';
  setSetupStatus("Entre para concluir a configuração", true);
  renderSettingsOverview();
}

async function bootstrapProtectedSetup() {
  const auth = await requestJson("/auth/status");
  if (!auth.authenticated) {
    renderConnectedAccount(null);
    renderSignedOutSetupState();
    redirectToLogin();
    return false;
  }
  renderConnectedAccount(auth.user);
  await Promise.allSettled([
    loadConfigData().then(loadSetupOperation),
    loadCameras().then(() => Promise.all([loadMachineConfigList(), loadSetupOperation()])),
    loadEvents(),
    loadRecipients(),
    loadDeliveries(),
    loadSystemHealth(),
    loadOperations(),
  ]);
  connectRealtime();
  startDeliveryPolling();
  return true;
}

async function login(event) {
  event.preventDefault();
  const data = new FormData(loginForm);
  try {
    const payload = await requestJson("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: String(data.get("email") || ""),
        senha: String(data.get("senha") || ""),
      }),
    });
    renderConnectedAccount(payload.user);
    await Promise.all([loadConfigData(), loadCameras(), loadEvents(), loadRecipients(), loadDeliveries(), loadSystemHealth()]);
    await loadMachineConfigList();
    const next = new URLSearchParams(window.location.search).get("next");
    if (next && next.startsWith("/") && !next.startsWith("//")) {
      window.location.href = next;
    }
  } catch (error) {
    loginStatus.textContent = `Login falhou: ${error.message}`;
  }
}

async function loadSystemHealth() {
  try {
    const health = await requestJson("/system/health");
    latestSystemHealth = health;
    systemHealth.className = "cx-setup-health-grid";
    systemHealth.innerHTML = [
      ["API", health.api],
      ["Banco", health.database],
      ["Disco livre", `${health.disk_free_gb} GB`],
      ["Câmeras online", health.cameras_online],
      ["Câmeras offline", health.cameras_offline],
      ["IA ativa", health.ai_active],
      ["IA inativa", health.ai_inactive],
      ["Último frame", health.ultimo_frame || "nenhum"],
      ["Último evento", health.ultimo_evento || "nenhum"],
      ["Último e-mail", health.ultimo_email || "nenhum"],
    ].map(([label, value]) => `
      <article>
        <span>${safeText(label)}</span>
        <strong>${safeText(value)}</strong>
      </article>
    `).join("");
    const checklist = await requestJson("/pilot/checklist");
    pilotChecklist.className = "cx-setup-checklist";
    pilotChecklist.innerHTML = Object.entries(checklist.checks)
      .map(([key, ok]) => `
        <article>
          ${setupStatusPill(ok ? "PASS" : "Pendente")}
          <strong>${safeText(key.replaceAll("_", " "))}</strong>
        </article>
      `)
      .join("");
    renderSettingsOverview();
  } catch (error) {
    latestSystemHealth = null;
    systemHealth.className = "result offline";
    systemHealth.innerHTML = setupErrorState("Não foi possível carregar saúde", error);
    pilotChecklist.className = "result muted";
    pilotChecklist.innerHTML = setupErrorState("Checklist indisponível", error);
    renderSettingsOverview();
  }
}

testButton?.addEventListener("click", testConnection);
liveViewButton?.addEventListener("click", openLiveView);
cameraUnitSelect?.addEventListener("change", fillCameraEdgeSelect);
loginForm.addEventListener("submit", login);
signupForm?.addEventListener("submit", signup);
showSignupButton?.addEventListener("click", showSignupMode);
showLoginButton?.addEventListener("click", showLoginMode);
loginPasswordToggle?.addEventListener("click", toggleLoginPassword);
logoutButton?.addEventListener("click", logout);
sidebarLogoutButton?.addEventListener("click", logout);
accountSettingsLogoutButton?.addEventListener("click", logout);
organizationEditorButtons.forEach((button) => button.addEventListener("click", openOrganizationEditor));
organizationEditorCloseButtons.forEach((button) => button.addEventListener("click", closeOrganizationEditor));
firstRunForm?.addEventListener("submit", completeFirstRun);
clientForm.addEventListener("submit", (event) => {
  saveClient(event).catch((error) => {
    clientList.innerHTML = `<div class="muted">Erro ao salvar cliente: ${error.message}</div>`;
  });
});
unitForm.addEventListener("submit", (event) => {
  saveUnit(event).catch((error) => {
    unitList.innerHTML = `<div class="muted">Erro ao salvar unidade: ${error.message}</div>`;
  });
});
userForm.addEventListener("submit", (event) => {
  saveUser(event).catch((error) => {
    userList.innerHTML = `<div class="muted">Erro ao salvar usuário: ${error.message}</div>`;
  });
});
machineConfigForm.addEventListener("submit", (event) => {
  saveDefaultMachine(event).catch((error) => {
    machineConfigList.innerHTML = `<div class="muted">Erro ao salvar máquina: ${error.message}</div>`;
  });
});
setupUnitForm?.addEventListener("submit", (event) => {
  saveSetupUnit(event).catch((error) => setSetupStatus(`Erro ao salvar unidade: ${error.message}`, true));
});
setupAreaForm?.addEventListener("submit", (event) => {
  saveSetupArea(event).catch((error) => setSetupStatus(`Erro ao salvar área: ${error.message}`, true));
});
setupProcessForm?.addEventListener("submit", (event) => {
  saveSetupProcess(event).catch((error) => setSetupStatus(`Erro ao salvar processo: ${error.message}`, true));
});
setupAssetForm?.addEventListener("submit", (event) => {
  saveSetupAsset(event).catch((error) => setSetupStatus(`Erro ao salvar ativo: ${error.message}`, true));
});
setupCameraContextForm?.addEventListener("submit", (event) => {
  saveSetupCameraContext(event).catch((error) => setSetupStatus(`Erro ao associar câmera: ${error.message}`, true));
});
setupMonitorForm?.addEventListener("submit", (event) => {
  saveSetupMonitor(event).catch((error) => setSetupStatus(`Erro ao salvar monitor: ${error.message}`, true));
});
setupOpenCameraButton?.addEventListener("click", () => {
  const cameraId = setupMonitorCameraSelect?.value || setupContextCameraSelect?.value;
  const camera = knownCameras.find((item) => item.id === cameraId);
  if (!cameraId) {
    setSetupStatus("Selecione uma câmera para abrir o vídeo.", true);
    return;
  }
  openCamera(cameraId, camera?.nome || "Câmera").catch((error) => setSetupStatus(`Erro ao abrir câmera: ${error.message}`, true));
});
form.addEventListener("submit", saveCamera);
cameraList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const cameraId = button.dataset.cameraId;
  const cameraName = button.dataset.cameraName || "Câmera";
  try {
    if (button.dataset.action === "stop") {
      await stopCamera(cameraId);
      return;
    }
    if (button.dataset.action === "toggle-active") {
      await requestJson(`/cameras/${cameraId}`, {
        method: "PATCH",
        body: JSON.stringify({ ativa: button.dataset.active !== "true" }),
      });
      await Promise.all([loadCameras(), loadSetupOperation()]);
      return;
    }
    if (button.dataset.action === "live-view") {
      sessionStorage.setItem("campex_live_view_source", JSON.stringify({ camera_id: cameraId, nome: cameraName }));
      window.open(`/live-view?camera_id=${encodeURIComponent(cameraId)}&nome=${encodeURIComponent(cameraName)}`, "_blank");
      return;
    }
    await openCamera(cameraId, cameraName);
  } catch (error) {
    setViewerMessage(`Erro: ${error.message}`, "offline");
  }
});
startAnalysisButton.addEventListener("click", () => {
  setAnalysis(true).catch((error) => setViewerMessage(`Erro ao ligar análise: ${error.message}`, "offline"));
});
stopAnalysisButton.addEventListener("click", () => {
  setAnalysis(false).catch((error) => setViewerMessage(`Erro ao desligar análise: ${error.message}`, "offline"));
});
createAreaButton.addEventListener("click", startDrawingArea);
undoAreaPointButton.addEventListener("click", () => {
  draftPoints.pop();
  drawAreaCanvas();
});
cancelAreaButton.addEventListener("click", cancelDrawingArea);
saveAreaButton.addEventListener("click", () => {
  saveArea().catch((error) => setViewerMessage(`Erro ao salvar área: ${error.message}`, "offline"));
});
areaCanvas.addEventListener("click", (event) => {
  if (!drawingArea && !drawingMachine) return;
  const rect = canvasSize();
  const point = {
    x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
    y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
  };
  if (drawingMachine) {
    if (machineStep === "machine") draftMachinePoints.push(point);
    else draftOperatorPoints.push(point);
  } else {
    draftPoints.push(point);
  }
  drawAreaCanvas();
});
areaList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-area-action]");
  if (!button) return;
  const areaId = button.dataset.areaId;
  const action = button.dataset.areaAction;
  if (action === "delete") {
    await fetch(`/areas/${areaId}`, { method: "DELETE" });
  } else {
    await requestJson(`/areas/${areaId}/${action}`, { method: "POST" });
  }
  await loadAreas();
});
createMachineButton.addEventListener("click", startDrawingMachine);
nextMachineZoneButton.addEventListener("click", nextMachineZone);
saveMachineButton.addEventListener("click", () => {
  saveMachine().catch((error) => setViewerMessage(`Erro ao salvar máquina: ${error.message}`, "offline"));
});
machineList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-machine-action]");
  if (!button) return;
  const machineId = button.dataset.machineId;
  const action = button.dataset.machineAction;
  if (action === "delete") {
    await fetch(`/machine-monitors/${machineId}`, { method: "DELETE" });
  } else if (action === "calibrate-active" || action === "calibrate-stopped") {
    const phase = action === "calibrate-active" ? "active" : "stopped";
    const message = phase === "active"
      ? "Calibrando máquina funcionando. Mantenha a máquina em operação durante a captura."
      : "Calibrando máquina parada. Mantenha a máquina parada durante a captura.";
    setViewerMessage(message, "online");
    const payload = await requestJson(`/machine-monitors/${machineId}/calibration/${phase}/start`, {
      method: "POST",
      body: JSON.stringify({ duration_seconds: 30 }),
    });
    result.className = "result";
    result.textContent = JSON.stringify(payload, null, 2);
  } else if (action === "calibration-status") {
    const payload = await requestJson(`/machine-monitors/${machineId}/calibration/status`);
    result.className = "result";
    result.textContent = JSON.stringify(payload, null, 2);
  } else {
    await requestJson(`/machine-monitors/${machineId}/${action}`, { method: "POST" });
  }
  await loadMachines();
  await loadOperations();
});
eventList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-event-action]");
  if (!button) return;
  const eventId = button.dataset.eventId;
  if (button.dataset.eventAction === "ack") {
    const observacao = window.prompt("Observação do reconhecimento", "Verificado no MVP");
    await requestJson(`/eventos/${eventId}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: "acknowledged",
        acknowledged_by: "operador local",
        observacao,
      }),
    });
    await loadEvents();
    return;
  }
  if (button.dataset.eventAction === "cause") {
    const cause = window.prompt("Causa da parada", "operador ausente");
    if (!cause) return;
    await requestJson(`/eventos/${eventId}/cause`, {
      method: "PATCH",
      body: JSON.stringify({ cause_category: cause, cause_notes: "" }),
    });
    await loadEvents();
    await loadOperations();
    return;
  }
  const detail = await requestJson(`/eventos/${eventId}`);
  result.className = "result";
  result.textContent = JSON.stringify(detail, null, 2);
});
liveAlertList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-event-action]");
  if (!button) return;
  const eventId = button.dataset.eventId;
  if (button.dataset.eventAction === "ack") {
    await requestJson(`/eventos/${eventId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "acknowledged", acknowledged_by: "operador local" }),
    });
    await loadEvents();
    return;
  }
  const detail = await requestJson(`/eventos/${eventId}`);
  result.className = "result";
  result.textContent = JSON.stringify(detail, null, 2);
});
recipientForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await requestJson("/alert-recipients", {
    method: "POST",
    body: JSON.stringify(recipientPayload()),
  });
  recipientForm.reset();
  await loadRecipients();
});
recipientList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-recipient-action]");
  if (!button) return;
  const recipientId = button.dataset.recipientId;
  if (button.dataset.recipientAction === "test") {
    await requestJson(`/alert-recipients/${recipientId}/test`, { method: "POST" });
    await loadDeliveries();
    return;
  }
  if (button.dataset.recipientAction === "toggle") {
    await requestJson(`/alert-recipients/${recipientId}`, {
      method: "PATCH",
      body: JSON.stringify({ ativo: button.dataset.active !== "true" }),
    });
    await loadRecipients();
    return;
  }
  if (button.dataset.recipientAction === "edit") {
    const current = knownRecipients.find((item) => item.id === recipientId);
    if (!current) return;
    const nome = window.prompt("Nome", current.nome);
    if (!nome) return;
    const email = window.prompt("E-mail", current.email);
    if (!email) return;
    const severidade = window.prompt("Severidade mínima: low, medium, high ou critical", current.severidade_minima || "low");
    const tipos = window.prompt("Tipos de evento separados por vírgula. Vazio = todos", current.event_types?.join(", ") || "");
    await requestJson(`/alert-recipients/${recipientId}`, {
      method: "PATCH",
      body: JSON.stringify({
        nome,
        email,
        severidade_minima: severidade || current.severidade_minima,
        event_types: String(tipos || "").split(",").map((item) => item.trim()).filter(Boolean),
      }),
    });
    await loadRecipients();
    return;
  }
  await fetch(`/alert-recipients/${recipientId}`, { method: "DELETE" });
  await loadRecipients();
});
deliveryList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-delivery-action='retry']");
  if (!button) return;
  await requestJson(`/alert-deliveries/${button.dataset.deliveryId}/retry`, { method: "POST" });
  await loadDeliveries();
});
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-setup-refresh]");
  if (!button) return;
  Promise.allSettled([
    loadConfigData(),
    loadCameras(),
    loadSetupOperation(),
    loadRecipients(),
    loadDeliveries(),
    loadSystemHealth(),
  ]);
});
window.addEventListener("resize", drawAreaCanvas);
window.addEventListener("hashchange", () => {
  applySetupSection();
  focusLoginFromHash();
});
checkApi();
checkFirstRun();
applySetupSection();
configureGoogleOAuthButton();
applyOAuthErrorMessage();
bootstrapProtectedSetup().catch(() => renderSignedOutSetupState());
focusLoginFromHash();
