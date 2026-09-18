const picker = document.querySelector("#gridCameraPicker");
const grid = document.querySelector("#liveGrid");
const message = document.querySelector("#gridMessage");
const resources = document.querySelector("#gridResources");

const cameras = new Map();
const selected = new Map();
let statusTimer = null;

async function requestJson(url, options) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { detail: await response.text() };
  if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
  return payload;
}

function friendlyGridError(error) {
  const raw = String(error?.message || error || "erro desconhecido");
  if (/internal server error/i.test(raw) || raw.startsWith("500")) {
    return "Não foi possível iniciar uma câmera. Verifique a configuração no Setup.";
  }
  if (/401|unauthorized|not authenticated/i.test(raw)) return "Entre para acessar a Live.";
  if (/403|forbidden/i.test(raw)) return "Você não tem permissão para acessar esta câmera.";
  if (/failed to fetch|networkerror/i.test(raw)) return "Não foi possível conectar à API local.";
  return raw;
}

async function authStatus() {
  return requestJson("/auth/status").catch(() => ({ authenticated: false }));
}

function renderAuthGate() {
  picker.innerHTML = "";
  grid.innerHTML = `
    <section class="cx-live-auth-gate">
      <span>Acesso protegido</span>
      <strong>Entre para visualizar câmeras em tempo real.</strong>
      <p>A Campex só carrega streams, status operacional e contexto de câmeras para usuários autenticados.</p>
      <a class="button-link" href="/login?next=%2Flive-grid">Entrar</a>
    </section>
  `;
  message.textContent = "Sessão necessária para carregar a Live.";
  resources.textContent = "Live protegida";
}

function statusLabel(status) {
  if (status === "online") return "Online";
  if (status === "conectando") return "Conectando";
  if (status === "reconectando") return "Reconectando";
  return "Offline";
}

function humanConnectionLabel(status) {
  if (status === "online") return "Conectado";
  if (status === "conectando") return "Conectando";
  if (status === "reconectando") return "Reconectando";
  return "Offline";
}

function secondsLabel(value) {
  const total = Math.max(0, Math.round(Number(value || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function operationalStatusLabel(status, event) {
  if (event) return `${eventLabel(event)} · ${secondsLabel(event.duration_seconds)}`;
  const labels = {
    ativa: "ATIVA",
    parada: "PARADA",
    evento_aberto: "EVENTO ABERTO",
    sem_evento: "Sem evento aberto",
    offline: "Offline",
    sem_frame_recente: "Sem frame recente",
    inferencia_indisponivel: "Inferência indisponível",
    cobertura_parcial: "Cobertura parcial",
  };
  return labels[status] || "Status indisponível";
}

function eventLabel(event) {
  const labels = {
    machine_stoppage: "PARADA",
    machine_running_without_operator: "ATIVA SEM OPERADOR",
    machine_stopped_with_operator: "PARADA COM OPERADOR",
    workstation_unattended: "POSTO SEM OPERADOR",
  };
  return labels[event?.tipo] || "EVENTO ABERTO";
}

function connectionClass(status) {
  if (status === "online") return "online";
  if (status === "conectando" || status === "reconectando") return "warning";
  return "offline";
}

function hasOperationalContext(camera) {
  if (!camera?.ativa) return false;
  return Boolean(
    camera.online ||
    camera.status === "online" ||
    camera.ultimo_frame ||
    camera.last_frame_at
  );
}

function displayCameraName(camera) {
  return camera.context?.primary_label || camera.nome || "Setor em configuração";
}

function displayCameraPath(camera) {
  return camera.context?.path_label || "Área não identificada";
}

function lastFrameLabel(value) {
  return value ? "Recente" : "Sem frame";
}

function inferenceLabel(value) {
  if (value === "ativa") return "Ativa";
  if (value === "iniciando") return "Iniciando";
  return "Inativa";
}

function activeEventDuration(event) {
  if (!event) return "—";
  return secondsLabel(event.duration_seconds);
}

function renderPicker() {
  const rows = Array.from(cameras.values());
  const operationalRows = rows.filter(hasOperationalContext);
  const technicalRows = rows.filter((camera) => camera.ativa && !hasOperationalContext(camera));
  if (!rows.length) {
    picker.innerHTML = "";
    message.textContent = "Nenhuma câmera cadastrada. Cadastre uma câmera em Configurações > Câmeras.";
    return;
  }
  if (!operationalRows.length) {
    picker.innerHTML = `
      <section class="cx-live-config-note">
        <strong>Nenhuma câmera operacional configurada.</strong>
        <span>Associe câmera, área, processo e ativo para acompanhar a operação ao vivo.</span>
        <a class="button-link" href="/settings/cameras">Configurar câmeras →</a>
      </section>
      ${technicalRows.length ? `<details class="cx-live-technical-list"><summary>${technicalRows.length} câmeras aguardam configuração</summary>${technicalRows.map((camera) => `<span>${camera.nome || "Câmera sem nome"}</span>`).join("")}<a href="/settings/cameras">Configurar câmeras →</a></details>` : ""}
    `;
    grid.innerHTML = "";
    message.textContent = "A Live mostra câmeras vinculadas a contexto operacional.";
    return;
  }
  picker.innerHTML = operationalRows.map((camera) => {
    const checked = selected.has(camera.id) ? "checked" : "";
    const status = selected.get(camera.id)?.status?.status;
    return `
      <label class="cx-grid-picker-item">
        <input type="checkbox" data-camera-id="${camera.id}" ${checked} />
        <i class="${connectionClass(status)}" aria-hidden="true"></i>
        <span>
          <strong>${displayCameraName(camera)}</strong>
          <small>${displayCameraPath(camera)}</small>
        </span>
      </label>
    `;
  }).join("") + (technicalRows.length ? `
    <details class="cx-live-technical-list">
      <summary>${technicalRows.length} câmeras aguardam configuração</summary>
      ${technicalRows.map((camera) => `<span>${camera.nome || "Câmera sem nome"}</span>`).join("")}
      <a href="/settings/cameras">Configurar câmeras →</a>
    </details>
  ` : "");
  message.textContent = selected.size
    ? `${selected.size} câmera(s) selecionada(s).`
    : "Selecione uma câmera para acompanhar agora.";
}

function renderGrid() {
  if (!selected.size) {
    grid.innerHTML = `
      <section class="cx-live-empty-stage">
        <strong>Selecione uma câmera.</strong>
        <p>As câmeras configuradas aparecem acima como atalhos compactos.</p>
      </section>
    `;
    return;
  }
  const item = Array.from(selected.values())[0];
  const context = item.status?.context || {};
  const currentEvent = context.current_event;
  const cameraName = context.primary_label || displayCameraName(item.camera);
  const cameraPath = context.path_label || displayCameraPath(item.camera);
  const statusText = operationalStatusLabel(context.operational_status, currentEvent);
  grid.innerHTML = `
    <article class="cx-live-monitor" data-camera-id="${item.camera.id}">
      <section class="cx-live-stage">
        <div class="cx-live-grid-frame">
          <img src="${item.streamUrl}" alt="Transmissão ${cameraName}" />
          <a class="cx-live-grid-hit" href="/live-view?camera_id=${encodeURIComponent(item.camera.id)}&nome=${encodeURIComponent(item.camera.nome)}" aria-label="Abrir ${cameraName}"></a>
          <div class="cx-live-grid-overlay">
            <strong>${cameraName}</strong>
            <span>${item.status?.status === "online" ? "Ao vivo" : humanConnectionLabel(item.status?.status)}</span>
          </div>
        </div>
        ${item.status?.error ? `
          <div class="cx-live-frame-error">
            <strong>Sem imagem disponível</strong>
            <p>A câmera está conectando ou ainda não enviou um frame.</p>
            <button type="button" data-action="restart" data-camera-id="${item.camera.id}">Tentar novamente</button>
            <details><summary>Detalhes técnicos</summary><span>${friendlyGridError(item.status.error)}</span></details>
          </div>
        ` : ""}
      </section>
      <aside class="cx-live-now">
        <span>Agora</span>
        <h2>${cameraName}</h2>
        <p>${cameraPath}</p>
        <dl>
          <div><dt>Estado atual</dt><dd>${statusText}</dd></div>
          <div><dt>Duração</dt><dd>${activeEventDuration(currentEvent)}</dd></div>
          <div><dt>Pessoas</dt><dd>${item.status?.people_count ?? "Indisponível"}</dd></div>
          <div><dt>Conexão</dt><dd>${humanConnectionLabel(item.status?.status)}</dd></div>
          <div><dt>Inferência</dt><dd>${inferenceLabel(item.status?.ai_status)}</dd></div>
          <div><dt>Último frame</dt><dd>${lastFrameLabel(item.status?.last_frame_at)}</dd></div>
        </dl>
        ${currentEvent ? `
          <section class="cx-live-active-event">
            <span>Evento ativo</span>
            <strong>${eventLabel(currentEvent)}</strong>
            <p>${secondsLabel(currentEvent.duration_seconds)}</p>
            <a href="/events?event_uuid=${encodeURIComponent(currentEvent.event_uuid || "")}">Ver evento →</a>
          </section>
        ` : ""}
        <details class="cx-live-grid-technical">
          <summary>Detalhes técnicos</summary>
          <footer>
            <button type="button" data-action="ai-start" data-camera-id="${item.camera.id}" ${item.status?.ai_status === "ativa" ? "hidden" : ""}>Ativar IA</button>
            <button type="button" data-action="ai-stop" data-camera-id="${item.camera.id}" ${item.status?.ai_status !== "ativa" ? "hidden" : ""}>Desativar IA</button>
            <a class="button-link" href="/live-view?camera_id=${encodeURIComponent(item.camera.id)}&nome=${encodeURIComponent(item.camera.nome)}">Abrir câmera</a>
            <button type="button" data-action="stop" data-camera-id="${item.camera.id}">Parar</button>
          </footer>
        </details>
      </aside>
    </article>
  `;
}

async function startCamera(cameraId) {
  const camera = cameras.get(cameraId);
  if (!camera) return;

  const status = await requestJson(`/cameras/${encodeURIComponent(cameraId)}/status`).catch(() => ({
    status: camera.status || "offline",
    last_frame_at: camera.ultimo_frame || null,
  }));

  selected.set(cameraId, {
    camera,
    status,
    streamUrl: `/cameras/${encodeURIComponent(cameraId)}/latest-frame?t=${Date.now()}`,
  });

  renderPicker();
  renderGrid();
}

async function stopCamera(cameraId) {
  selected.delete(cameraId);
  renderPicker();
  renderGrid();
}

async function refreshStatuses() {
  const rows = await requestJson("/cameras/estado").catch(() => []);

  rows.forEach((camera) => cameras.set(camera.id, camera));

  await Promise.all(Array.from(selected.keys()).map(async (cameraId) => {
    const item = selected.get(cameraId);
    if (!item) return;
    try {
      item.camera = cameras.get(cameraId) || item.camera;
      item.status = await requestJson(`/cameras/${encodeURIComponent(cameraId)}/status`);
      item.streamUrl = `/cameras/${encodeURIComponent(cameraId)}/latest-frame?t=${Date.now()}`;
    } catch (error) {
      item.status = { status: "offline", error: error.message };
    }
  }));

  resources.textContent = rowsWithContextLabel();
  renderPicker();
  renderGrid();
}

async function toggleAnalysis(cameraId, enabled) {
  await requestJson(`/cameras/${cameraId}/analysis/${enabled ? "start" : "stop"}`, { method: "POST" });
  await refreshStatuses();
}

picker.addEventListener("change", (event) => {
  const input = event.target.closest("input[data-camera-id]");
  if (!input) return;
  const cameraId = input.dataset.cameraId;
  if (input.checked) startCamera(cameraId).catch((error) => {
    message.textContent = error.message;
    selected.delete(cameraId);
    renderPicker();
  });
  else stopCamera(cameraId);
});

grid.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action][data-camera-id]");
  if (!target) return;
  const cameraId = target.dataset.cameraId;
  const action = target.dataset.action;
  if (action === "stop") stopCamera(cameraId);
  if (action === "restart") {
    stopCamera(cameraId)
      .then(() => startCamera(cameraId))
      .catch((error) => { message.textContent = friendlyGridError(error); });
  }
  if (action === "ai-start") toggleAnalysis(cameraId, true).catch((error) => { message.textContent = error.message; });
  if (action === "ai-stop") toggleAnalysis(cameraId, false).catch((error) => { message.textContent = error.message; });
});

async function boot() {
  const auth = await authStatus();
  if (!auth.authenticated) {
    renderAuthGate();
    return;
  }

  const rows = await requestJson("/cameras/estado");
  rows.forEach((camera) => cameras.set(camera.id, camera));

  renderPicker();

  const auto = rows.filter(hasOperationalContext).slice(0, 2);
  for (const camera of auto) {
    await startCamera(camera.id).catch((error) => {
      message.textContent = friendlyGridError(error);
    });
  }

  await refreshStatuses();
  statusTimer = setInterval(refreshStatuses, 3000);
}

function rowsWithContextLabel() {
  const total = Array.from(cameras.values()).filter(hasOperationalContext).length;
  return `${total} setor(es) configurado(s)`;
}

window.addEventListener("beforeunload", () => {
  if (statusTimer) clearInterval(statusTimer);
});

boot().catch((error) => {
  message.textContent = friendlyGridError(error);
});
