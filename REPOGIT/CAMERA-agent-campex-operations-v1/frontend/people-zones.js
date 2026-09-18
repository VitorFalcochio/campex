const updated = document.querySelector("#peopleZonesUpdated");
const kpis = document.querySelector("#peopleZonesKpis");
const workstations = document.querySelector("#workstationList");
const activeEvents = document.querySelector("#activeZoneEvents");
const eventsBody = document.querySelector("#peopleZonesEvents");
const generateTestEvent = document.querySelector("#generateTestEvent");

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : { detail: await response.text() };
  if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
  return payload;
}

function fmtSeconds(value) {
  const seconds = Math.round(Number(value || 0));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes <= 0) return `${rest}s`;
  return `${minutes}m ${String(rest).padStart(2, "0")}s`;
}

function eventLabel(type) {
  const labels = {
    restricted_zone_occupied: "Zona restrita ocupada",
    workstation_unattended: "Posto sem pessoa",
    minimum_staff_not_met: "Equipe abaixo do mínimo",
    shift_start_incomplete: "Início de turno incompleto",
    excessive_zone_dwell: "Permanência excessiva",
    after_hours_presence: "Presença fora de horário",
  };
  return labels[type] || type;
}

function cameraName(cameras, id) {
  return cameras.find((camera) => camera.id === id)?.nome || id;
}

function zoneName(zones, id) {
  return zones.find((zone) => zone.id === id)?.nome || id || "-";
}

function render(payload) {
  const occupiedWorkstations = payload.workstations.filter((zone) => Number(zone.ocupacao_atual || 0) > 0).length;
  kpis.innerHTML = [
    ["Postos configurados", payload.workstations.length, "Zonas do tipo posto de trabalho"],
    ["Postos ocupados", occupiedWorkstations, "Ocupação atual detectada"],
    ["Pessoas identificadas", payload.identified_people, "Tracks temporários, sem reconhecimento facial"],
    ["Eventos ativos", payload.active_events.length, "Ocorrências abertas agora"],
  ].map(([label, value, hint]) => `
    <article class="cx-resource-card">
      <span>${label}</span>
      <strong>${value}</strong>
      <small>${hint}</small>
    </article>
  `).join("");

  workstations.innerHTML = payload.workstations.length ? payload.workstations.map((zone) => `
    <div>
      <span>${zone.nome}${zone.colaborador_turno ? ` · ${zone.colaborador_turno}` : ""}</span>
      <strong>${Number(zone.ocupacao_atual || 0) > 0 ? "Ocupado" : "Vazio"}</strong>
      <small>${zone.ausencias} ausência(s) · ${fmtSeconds(zone.tempo_total_desocupado)} desocupado</small>
    </div>
  `).join("") : '<p class="muted">Nenhum posto configurado ainda.</p>';

  activeEvents.innerHTML = payload.active_events.length ? payload.active_events.map((event) => `
    <div>
      <span>${eventLabel(event.tipo)} · ${zoneName(payload.zones, event.area_id)}</span>
      <strong>${event.severidade || "média"}</strong>
      <small>${event.inicio}</small>
    </div>
  `).join("") : '<p class="muted">Nenhum evento ativo agora.</p>';

  eventsBody.innerHTML = payload.events.length ? payload.events.slice(0, 30).map((event) => `
    <tr>
      <td>${event.inicio || "-"}</td>
      <td>${eventLabel(event.tipo)}</td>
      <td>${cameraName(payload.cameras, event.camera_id)}</td>
      <td>${zoneName(payload.zones, event.area_id)}</td>
      <td>${event.duracao ? fmtSeconds(event.duracao) : "-"}</td>
      <td><span class="cx-badge ${event.status === "open" ? "warning" : "success"}">${event.status || "-"}</span></td>
      <td>${event.midia_path ? `<a href="/eventos/${event.id}/evidence">Abrir</a>` : "Sem evidência"}</td>
    </tr>
  `).join("") : '<tr><td colspan="7">Sem eventos People & Zones registrados ainda.</td></tr>';
  updated.textContent = `Atualizado ${new Date().toLocaleTimeString("pt-BR")}`;
}

async function refresh() {
  try {
    render(await requestJson("/people-zones/summary"));
  } catch (error) {
    updated.textContent = error.message;
  }
}

refresh();
setInterval(refresh, 10000);

generateTestEvent.addEventListener("click", async () => {
  generateTestEvent.disabled = true;
  generateTestEvent.textContent = "Gerando...";
  try {
    await requestJson("/dev/test-event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
    generateTestEvent.textContent = "Ocorrência criada";
    await refresh();
  } catch (error) {
    generateTestEvent.textContent = "Erro ao gerar";
    updated.textContent = error.message;
  } finally {
    setTimeout(() => {
      generateTestEvent.disabled = false;
      generateTestEvent.textContent = "Gerar ocorrência de teste";
    }, 1800);
  }
});
