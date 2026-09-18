const diagnosticsGrid = document.querySelector("#diagnosticsGrid");
const diagnosticsUpdated = document.querySelector("#diagnosticsUpdated");
const lastDelivery = document.querySelector("#lastDelivery");

async function requestJson(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
  return payload;
}

function render(payload) {
  const cards = [
    ["Banco local", payload.sqlite, "SQLite acessível"],
    ["Câmeras online", payload.cameras_online, "Streams ativos agora"],
    ["IA ativa", payload.ia_ativa, "Análises ligadas"],
    ["Zonas", payload.zonas_ativas, "Zonas ativas salvas"],
    ["Regras", payload.regras_ativas, "Regras operacionais ativas"],
    ["Eventos abertos", payload.eventos_abertos, "Ocorrências em andamento"],
    ["Outbox", payload.outbox_pendente, "Itens aguardando Cloud"],
    ["E-mail", payload.email_mode, "Modo atual"],
    ["Disco livre", `${payload.disco_livre_percentual}%`, "Espaço disponível"],
  ];
  diagnosticsGrid.innerHTML = cards.map(([label, value, hint]) => `
    <article class="cx-resource-card">
      <span>${label}</span>
      <strong>${value ?? "-"}</strong>
      <small>${hint}</small>
    </article>
  `).join("");
  lastDelivery.textContent = payload.ultima_entrega
    ? JSON.stringify(payload.ultima_entrega, null, 2)
    : "Nenhuma entrega registrada.";
  diagnosticsUpdated.textContent = `Atualizado ${new Date().toLocaleTimeString("pt-BR")}`;
}

async function refresh() {
  try {
    render(await requestJson("/local-diagnostics"));
  } catch (error) {
    diagnosticsUpdated.textContent = error.message;
  }
}

refresh();
setInterval(refresh, 10000);
