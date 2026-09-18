const title = document.querySelector("#workspaceTitle");
const heading = document.querySelector("#workspaceHeading");
const subtitle = document.querySelector("#workspaceSubtitle");
const cards = document.querySelector("#workspaceCards");
const tableTitle = document.querySelector("#workspaceTableTitle");
const tableHint = document.querySelector("#workspaceTableHint");
const head = document.querySelector("#workspaceHead");
const body = document.querySelector("#workspaceBody");
const search = document.querySelector("#workspaceSearch");
const tabs = document.querySelector("#workspaceTabs");
const filters = document.querySelector("#workspaceFilters");
const grid = document.querySelector("#workspaceGrid");
const primaryAction = document.querySelector("#workspacePrimaryAction");
const drawer = document.querySelector("#workspaceDrawer");
const drawerContent = document.querySelector("#workspaceDrawerContent");
const drawerClose = document.querySelector("#workspaceDrawerClose");

let rowsCache = [];
let currentTab = "all";
let viewMode = "grid";
let operationsSelectedPeriod = "day";
let operationsSelectedState = "all";
let operationsSelectedAsset = "";
let eventsSelectedPeriod = "all";
let eventsSelectedStatus = "all";
let eventsSelectedSeverity = "all";
let eventsSelectedFamily = "official";
let eventsContextQuery = "";

const routes = {
  "/home-view": {
    title: "Início",
    section: "home",
    breadcrumb: "Início",
    permissions: [],
    heading: "Início",
    subtitle: "Visão atual da sua operação.",
    action: "Atualizar",
    tabs: [],
    filters: [],
    columns: ["Origem", "Status"],
    customRender: renderHomePage,
  },
  "/dashboard": {
    title: "Operação",
    section: "operation",
    breadcrumb: "Operação",
    external: true,
  },
  "/overview": {
    title: "Operação",
    section: "operation",
    breadcrumb: "Operação",
    external: true,
  },
  "/operations-view": {
    title: "Operação",
    section: "operation",
    breadcrumb: "Operação",
    permissions: [],
    heading: "Operação",
    subtitle: "O que merece atenção na operação.",
    action: "Atualizar",
    tabs: ["Hoje", "Turno", "Semana", "Mês", "Personalizado"],
    filters: ["Período", "Família", "Ativo"],
    columns: ["Item", "Família", "Duração", "Eventos", "Rastreabilidade"],
    customRender: renderOperationsReadModelPage,
  },
  "/cameras": {
    title: "Câmeras",
    section: "operation",
    breadcrumb: "Operação / Câmeras",
    permissions: [],
    heading: "Câmeras",
    subtitle: "Pontos conectados, status e últimas atualizações.",
    endpoint: "/cameras/estado",
    action: "Adicionar câmera",
    actionHref: "/settings/cameras",
    emptyTitle: "Nenhuma câmera cadastrada.",
    emptyDescription: "Cadastre uma câmera RTSP para acompanhar a operação pela Campex.",
    tabs: ["Todas", "Ativa", "Sem sinal", "Em configuração", "Pausada"],
    filters: ["Status", "Unidade"],
    columns: ["Câmera", "Localização", "Status", "Último evento", "Última atualização", "Ações"],
    row: (camera) => [
      camera.nome || "Câmera",
      camera.unidade_id || "—",
      badge(cameraStatusLabel(camera.status)),
      camera.ultimo_erro || "Sem evento",
      camera.ultimo_frame || camera.criado_em || "—",
      rowMenu(),
    ],
    card: cameraCard,
  },
  "/events": {
    title: "Eventos",
    section: "operation",
    breadcrumb: "Operação / Eventos",
    permissions: [],
    heading: "Eventos",
    subtitle: "Ocorrências e incidentes registrados pela operação.",
    endpoint: "/eventos",
    action: "Atualizar",
    emptyTitle: "Nenhum evento operacional registrado neste período.",
    emptyDescription: "Os acontecimentos monitorados pela Campex aparecerão aqui.",
    tabs: ["Todos", "Abertos", "Encerrados", "Novo", "Reconhecido", "Resolvido", "Não classificados", "Com evidência"],
    filters: ["Período", "Unidade", "Área", "Processo", "Ativo", "Família", "Estado físico", "Workflow"],
    columns: ["Evento", "Contexto", "Horário", "Duração", "Workflow", "Evidência", "Ação"],
    row: eventRow,
    card: eventCard,
    detail: eventDetail,
    customRender: renderEventsPage,
  },
  "/alerts": {
    title: "Alertas",
    section: "monitoring",
    breadcrumb: "Monitoramento / Alertas",
    permissions: [],
    heading: "Alertas",
    subtitle: "Configuração e histórico de entregas de alertas, sem misturar falha de envio com evento aguardando análise.",
    endpoint: "/alert-deliveries",
    action: "Criar regra de alerta",
    actionHref: "/settings/cameras#destinatarios",
    emptyTitle: "Nenhum alerta registrado.",
    emptyDescription: "Configure destinatários para registrar entregas de alertas operacionais.",
    tabs: ["Regras de alerta", "Destinatários", "Entregas", "Falhas"],
    filters: ["Evento", "Severidade", "Destinatário", "Canal", "Status", "Falha"],
    columns: ["Evento", "Destinatário", "Canal", "Horário", "Resultado", "Tentativas", "Erro", "Status", "Ações"],
    load: loadAlertsWorkspace,
    row: alertRow,
    detail: alertDeliveryDetail,
  },
  "/evidence": {
    title: "Evidências",
    section: "monitoring",
    breadcrumb: "Monitoramento / Evidências",
    permissions: [],
    heading: "Evidências",
    subtitle: "Biblioteca operacional de snapshots associados a eventos reais.",
    endpoint: "/eventos",
    action: "Abrir eventos",
    actionHref: "/events",
    emptyTitle: "Nenhuma evidência salva.",
    emptyDescription: "As evidências serão exibidas quando um evento configurado registrar uma ocorrência visual.",
    tabs: ["Grade", "Lista"],
    filters: ["Período", "Evento", "Categoria", "Área", "Câmera", "Severidade", "Retenção"],
    columns: ["Snapshot", "Evento", "Horário", "Unidade", "Área", "Câmera", "Tipo", "Severidade", "Duração", "Retenção", "Status", "Abrir"],
    filterRows: (rows) => rows.filter((event) => event.midia_path || event.snapshot_path),
    row: evidenceRow,
    card: evidenceCard,
    detail: evidenceDetail,
  },
  "/rules": {
    title: "Regras",
    section: "monitoring",
    breadcrumb: "Monitoramento / Regras",
    permissions: [],
    heading: "Regras",
    subtitle: "Construtor operacional de regras visuais em linguagem de operação.",
    endpoint: "/visual-rules",
    action: "Configurar regra",
    actionType: "visual-rule",
    emptyTitle: "Nenhuma regra configurada.",
    emptyDescription: "Crie uma regra visual para transformar estados do vídeo em eventos e alertas.",
    tabs: ["Todas", "Ativas", "Inativas", "Em desenvolvimento"],
    filters: ["Unidade", "Câmera", "Área", "Condição", "Severidade", "Status"],
    columns: ["Nome", "Unidade", "Câmera", "Área/zona", "Condição", "Tempo mínimo", "Severidade", "Cooldown", "Alerta", "Status", "Última ativação", "Ações"],
    row: (rule) => [
      `<strong>${rule.nome || rule.tipo_evento}</strong>`,
      rule.unidade_id || "—",
      rule.camera_id || "—",
      rule.regiao_id || rule.area_id || "—",
      humanCondition(rule),
      `${rule.tempo_minimo || 0}s`,
      badge(rule.severidade || "medium"),
      `${rule.cooldown_seconds || 0}s`,
      rule.alerta_inicio || rule.alerta_normalizacao ? "Configurado" : "Sem alerta",
      badge(rule.ativo ? "Ativa" : "Inativa"),
      rule.last_triggered_at || rule.ultima_ativacao || "—",
      rowMenu(),
    ],
    detail: ruleDetail,
  },
  "/reports": {
    title: "Relatórios",
    section: "intelligence",
    breadcrumb: "Inteligência / Relatórios",
    permissions: [],
    heading: "Relatórios",
    subtitle: "Receba automaticamente a leitura diária da sua operação.",
    columns: [],
    customRender: renderReportsPage,
  },
  "/insights": {
    title: "Intelligence",
    section: "intelligence",
    breadcrumb: "Intelligence",
    permissions: [],
    heading: "Intelligence",
    subtitle: "O que a Campex entendeu sobre a operação que merece ser percebido.",
    endpoint: "/operations/read-model/insights",
    action: "Atualizar",
    emptyTitle: "Ainda não existem dados suficientes para gerar padrões confiáveis.",
    emptyDescription: "A Campex só apresenta insights quando os eventos classificados sustentam a constatação.",
    tabs: ["Briefing", "Atenção", "Padrões", "KPIs", "Causas"],
    filters: [],
    columns: ["Insight", "Número", "Por que", "Eventos", "Investigar"],
    customRender: renderIntelligencePage,
    row: (item) => [item.statement, item.number || "—", item.why || "—", traceButton("Eventos", item.event_uuids), `<a class="cx-link" href="/events">Investigar</a>`],
  },
  "/history": {
    title: "Histórico",
    section: "intelligence",
    breadcrumb: "Inteligência / Histórico",
    permissions: [],
    heading: "Histórico",
    subtitle: "Linha histórica de eventos e mudanças de estado.",
    endpoint: "/operations/events?limit=100&offset=0",
    emptyTitle: "Nenhum histórico encontrado.",
    emptyDescription: "As mudanças de estado aparecerão aqui conforme a Campex monitora a operação.",
    transform: (payload) => payload.events || [],
    tabs: ["Todos", "Máquina", "Operador", "Câmera"],
    filters: ["Período", "Tipo"],
    columns: ["Início", "Tipo", "Estado anterior", "Novo estado", "Duração"],
    row: (event) => [event.started_at || "—", event.event_type || "—", event.previous_state || "—", event.new_state || "—", event.duration_seconds ?? "—"],
  },
  "/integrations": {
    title: "Integrações",
    section: "platform",
    breadcrumb: "Plataforma / Integrações",
    permissions: [],
    heading: "Integrações",
    subtitle: "Conexões futuras com sistemas da operação.",
    endpoint: "/health",
    action: "Adicionar integração",
    tabs: ["Todas", "Ativas", "Futuras"],
    filters: ["Status"],
    columns: ["Integração", "Status", "Observação"],
    emptyTitle: "Nenhuma integração configurada.",
    emptyDescription: "Conecte a Campex aos sistemas utilizados pela operação.",
    transform: () => [],
    row: (item) => [item.name, badge(item.status), item.note],
  },
  "/users": {
    title: "Usuários",
    section: "platform",
    breadcrumb: "Plataforma / Usuários",
    permissions: [],
    heading: "Usuários",
    subtitle: "Equipe, convites e permissões vinculadas ao cliente.",
    endpoint: "/users",
    action: "Convidar usuário",
    actionHref: "/settings/cameras#usuarios",
    emptyTitle: "Nenhum usuário cadastrado.",
    emptyDescription: "O administrador convida usuários; a identidade é vinculada ao cliente e as permissões são aplicadas.",
    tabs: ["Todos", "Admins", "Operadores", "Visualizadores"],
    filters: ["Função", "Cliente", "Unidade", "Status"],
    columns: ["Nome", "E-mail", "Função", "Cliente", "Unidades", "Status", "Último acesso"],
    row: (user) => [
      user.nome || "—",
      user.email || "—",
      user.role || "—",
      user.cliente_id || "Cliente vinculado",
      user.unidades?.join?.(", ") || "Conforme permissão",
      badge(user.ativo ? "Ativo" : "Inativo"),
      user.ultimo_acesso || "—",
    ],
  },
  "/settings": {
    title: "Configurações",
    section: "platform",
    breadcrumb: "Plataforma / Configurações",
    permissions: [],
    heading: "Configurações",
    subtitle: "Empresa, unidades, usuários, câmeras, máquinas, alertas, segurança e retenção.",
    endpoint: "/health",
    action: "Configurar câmeras",
    actionHref: "/settings/cameras",
    emptyTitle: "Nenhuma configuração encontrada.",
    emptyDescription: "Abra uma área de configuração para ajustar o piloto local.",
    tabs: ["Empresa", "Unidades", "Usuários", "Câmeras", "Máquinas e áreas", "Edges", "Alertas", "Integrações", "Segurança", "Retenção"],
    filters: ["Área"],
    columns: ["Configuração", "Destino"],
    transform: () => [
      { name: "Empresa", href: "/settings/cameras#clientes", note: "Cliente, documento e status." },
      { name: "Unidades", href: "/settings/cameras#unidades", note: "Unidades operacionais vinculadas ao cliente." },
      { name: "Usuários", href: "/users", note: "Convites, permissões e vínculo ao cliente." },
      { name: "Câmeras", href: "/settings/cameras" },
      { name: "Máquinas e áreas", href: "/settings/cameras#maquinas", note: "Zonas e parâmetros de calibração." },
      { name: "Edges", href: "/edges", note: "Computadores Campex conectados às unidades." },
      { name: "Alertas", href: "/settings/notifications", note: "Destinatários e entregas." },
      { name: "Integrações", href: "/integrations", note: "Conexões futuras com sistemas da operação." },
      { name: "Segurança", href: "/settings/account", note: "Sessão, credenciais protegidas e acesso local." },
      { name: "Retenção de evidências", href: "/evidence", note: "Política local de snapshots." },
    ],
    row: (item) => [item.name, `<span>${item.note || "Configuração do piloto local."}</span> <a class="cx-link" href="${item.href}">Abrir</a>`],
  },
  "/edges": {
    title: "Campex Edge",
    section: "platform",
    breadcrumb: "Plataforma / Configurações / Edges",
    permissions: [],
    heading: "Campex Edge",
    subtitle: "Computadores responsáveis por conectar a operação física à Campex.",
    endpoint: "/edge-devices",
    action: "Instalar Campex Edge",
    actionType: "install-edge",
    emptyTitle: "Nenhum Edge instalado.",
    emptyDescription: "Instale o Campex Edge em um computador da unidade para conectar câmeras e iniciar o monitoramento.",
    tabs: ["Todos", "Online", "Offline"],
    filters: ["Unidade", "Status"],
    columns: ["Edge", "Unidade", "Status", "Último contato"],
    transform: (payload) => Array.isArray(payload) ? payload : [],
    row: (edge) => [
      edge.nome || edge.id || "Campex Edge",
      edge.unidade_id || "—",
      badge(edge.online ? "Online" : "Offline"),
      edge.last_seen_at || "Nunca",
    ],
  },

  "/settings/cameras": {
    title: "Configurações de câmeras",
    section: "platform",
    breadcrumb: "Plataforma / Configurações / Câmeras",
    external: true,
  },
  "/settings/notifications": {
    title: "Notificações",
    section: "platform",
    breadcrumb: "Plataforma / Configurações / Notificações",
    permissions: [],
    heading: "Notificações",
    subtitle: "Configurações de destinatários e entregas de alertas.",
    endpoint: "/alert-recipients",
    action: "Adicionar destinatário",
    actionHref: "/settings/cameras#destinatarios",
    emptyTitle: "Nenhum destinatário cadastrado.",
    emptyDescription: "Cadastre responsáveis para receber alertas por e-mail.",
    tabs: ["Todos", "Ativos", "Inativos"],
    filters: ["E-mail", "Tipo de evento"],
    columns: ["Nome", "E-mail", "Status", "Teste"],
    transform: (payload) => Array.isArray(payload) ? payload : payload.recipients || [],
    row: (recipient) => [
      recipient.nome || "—",
      recipient.email || "—",
      badge(recipient.ativo ? "Ativo" : "Inativo"),
      `<button type="button" data-test-recipient="${recipient.id}">Enviar teste</button>`,
    ],
  },
  "/settings/account": {
    title: "Conta",
    section: "platform",
    breadcrumb: "Plataforma / Configurações / Conta",
    permissions: [],
    heading: "Conta",
    subtitle: "Preferências gerais da conta local.",
    endpoint: "/health",
    action: "Abrir configurações",
    actionHref: "/settings/cameras",
    emptyTitle: "Nenhum dado de conta disponível.",
    emptyDescription: "As preferências da conta local aparecerão aqui quando configuradas.",
    tabs: ["Geral", "Segurança", "Sistema"],
    filters: ["Status"],
    columns: ["Item", "Status"],
    transform: (payload) => [
      { name: "API local", status: payload.status || "ok" },
      { name: "Sessão", status: "Local" },
      { name: "Banco", status: "SQLite" },
    ],
    row: (item) => [item.name, badge(item.status)],
  },
  "/help": {
    title: "Ajuda",
    section: "support",
    breadcrumb: "Suporte / Ajuda",
    permissions: [],
    heading: "Ajuda",
    subtitle: "Orientações para operar o piloto local da Campex.",
    endpoint: "/health",
    action: "Abrir configurações",
    actionHref: "/settings/cameras",
    emptyTitle: "Central de ajuda local",
    emptyDescription: "Use esta área para revisar os próximos passos: cadastrar câmera, validar eventos, revisar evidências e configurar alertas.",
    tabs: ["Primeiros passos", "Conectar câmera", "Configurar zona", "Criar regra", "Configurar alerta", "Revisar evento", "Evidências", "Problemas", "Diagnóstico", "Contato"],
    filters: ["Tema", "Status"],
    columns: ["Tema", "Orientação", "Status", "Ação"],
    load: loadHelpWorkspace,
    row: (item) => [item.name, item.note, badge(item.status || "Disponível"), item.href ? `<a class="cx-link" href="${item.href}">Abrir</a>` : "—"],
  },
};

function isHomeView() {
  return window.location.pathname === "/operations-view" && new URLSearchParams(window.location.search).get("view") === "home";
}

function currentRouteKey() {
  return isHomeView() ? "/home-view" : window.location.pathname;
}

function navigationKeyFromUrl(url) {
  if (url.pathname === "/operations-view" && url.searchParams.get("view") === "home") return "/home-view";
  if (url.pathname === "/settings" || url.pathname.startsWith("/settings/")) return "/settings/cameras";
  if (url.pathname === "/" || url.pathname === "/dashboard") return "/operations-view";
  return url.pathname;
}

async function requestJson(url, options) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : { detail: await response.text() };
  if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
  return payload;
}

async function authStatus() {
  return requestJson("/auth/status").catch(() => ({ authenticated: false, bootstrap: false }));
}

function badge(value) {
  const text = String(value || "—");
  const key = text.toLowerCase();
  const klass = key.includes("ativa") || key.includes("ativo") || key.includes("online") || key.includes("enviado") || key.includes("sent") || key.includes("disponível") || key.includes("sem falhas")
    ? "success"
      : key.includes("pend") || key.includes("config") || key.includes("atenção")
      ? "warning"
      : key.includes("sinal") || key.includes("offline") || key.includes("erro") || key.includes("fal")
        ? "danger"
        : "offline";
  return `<span class="cx-badge ${klass}">${text}</span>`;
}

function cameraStatusLabel(status) {
  if (status === "online") return "Ativa";
  if (status === "offline") return "Sem sinal";
  if (status === "nao_conectada" || status === "nao_testada") return "Em configuração";
  if (status === "inativa") return "Pausada";
  return status || "Em configuração";
}

function alertStatusLabel(status) {
  if (status === "sent") return "Enviado";
  if (status === "pending") return "Em processamento";
  if (status === "failed") return "Falha de entrega";
  return status || "Resolvido";
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

function familyLabel(family) {
  const labels = {
    interruption: "Interrupções",
    wait: "Esperas",
    absence: "Ausências",
    flow: "Fluxo/movimentação",
    visual: "Inteligência visual",
    unknown: "Sem classificação",
  };
  return labels[family] || family || "Sem classificação";
}

function isOfficialFamily(family) {
  return ["interruption", "wait", "absence", "flow", "visual"].includes(String(family || ""));
}

function officialFamilyRows(summary) {
  return (summary.events_by_family || []).filter((item) => isOfficialFamily(item.key));
}

function officialEventCount(summary) {
  return officialFamilyRows(summary).reduce((sum, item) => sum + Number(item.total_events || 0), 0);
}

function officialDuration(summary) {
  return officialFamilyRows(summary).reduce((sum, item) => sum + Number(item.total_duration_seconds || 0), 0);
}

function unknownEventCount(summary, currentPayload) {
  const summaryUnknown = (summary.events_by_family || [])
    .filter((item) => !isOfficialFamily(item.key))
    .reduce((sum, item) => sum + Number(item.total_events || 0), 0);
  const openUnknown = (currentPayload.open_events || []).filter((event) => !isOfficialFamily(event.event_family)).length;
  return Math.max(summaryUnknown, openUnknown);
}

function classifiedOpenEvents(currentPayload) {
  return (currentPayload.open_events || []).filter((event) => isOfficialFamily(event.event_family));
}

function formatDateParts(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const day = date.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "");
  const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return { day, time };
}

function formatOperationsPeriod(period) {
  const start = formatDateParts(period?.start);
  const end = formatDateParts(period?.end);
  if (!start || !end) return "Período não informado";
  if (start.day === end.day) return `Hoje · ${start.day}<br><span>${start.time} → ${end.time}</span>`;
  return `${start.day} → ${end.day}<br><span>${start.time} → ${end.time}</span>`;
}

function operationPeriod() {
  const selected = document.querySelector("#operationsPeriod")?.value;
  const tabPeriod = { hoje: "day", turno: "turno", semana: "week", mês: "month", personalizado: "custom" }[currentTab];
  return selected || operationsSelectedPeriod || tabPeriod || "day";
}

function readModelQuery(extra = {}) {
  const params = new URLSearchParams();
  params.set("period", operationPeriod());
  Object.entries(extra).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, value);
  });
  return params.toString();
}

function groupByKey(items = []) {
  return new Map((items || []).map((item) => [item.key, item]));
}

function getFamily(summary, family) {
  return groupByKey(summary.events_by_family || []).get(family) || {
    key: family,
    total_events: 0,
    total_duration_seconds: 0,
    event_uuids: [],
  };
}

function comparisonFor(comparison, key) {
  return comparison?.metrics?.[key] || { current: 0, previous: 0, absolute_difference: 0, percent_change: null };
}

function comparisonText(metric) {
  if (metric.percent_change === null || metric.percent_change === undefined) return "sem base anterior";
  const sign = metric.percent_change > 0 ? "+" : "";
  return `${sign}${metric.percent_change}% vs período anterior`;
}

function coverageWarning(coverage) {
  if (!coverage || coverage.status === "observed") return "";
  const label = coverage.status === "partial" ? "Cobertura parcial" : "Cobertura desconhecida";
  const detail = coverage.reason || "Alguns períodos não possuem dados suficientes.";
  return `<div class="cx-ops-warning"><strong>${label}</strong><span>${detail}</span></div>`;
}

function traceButton(label, uuids = []) {
  const list = (uuids || []).filter(Boolean).join(",");
  if (!list) return `<button type="button" class="cx-linklike" disabled>${label}</button>`;
  return `<button type="button" class="cx-linklike" data-event-uuids="${list}">${label}</button>`;
}

function operationsBriefing(summary, lossesPayload) {
  const coverage = summary.coverage || {};
  const classifiedCount = officialEventCount(summary);
  if (!classifiedCount) {
    if (Number(summary.total_events || 0) > 0) {
      return "Sem eventos operacionais classificados suficientes neste período.";
    }
    return coverage.status && coverage.status !== "observed"
      ? "Ainda não há eventos no período, e a cobertura dos dados não permite afirmar que a operação esteve sem ocorrências."
      : "Nenhum evento operacional foi registrado no período selecionado.";
  }
  const topArea = (summary.events_by_area || []).find((item) => item.key !== "não informado");
  const topAsset = (lossesPayload.by_asset || []).find((item) => item.key !== "não informado");
  const topFamily = officialFamilyRows(summary)[0];
  if (topArea && topAsset && topFamily) {
    return `${topArea.key} concentrou ${secondsLabel(topArea.total_duration_seconds)} em ${familyLabel(topFamily.key).toLowerCase()}. O ativo ${topAsset.key} é o principal ponto de atenção no período.`;
  }
  if (topFamily) {
    return `${familyLabel(topFamily.key)} concentraram ${secondsLabel(topFamily.total_duration_seconds)} no período selecionado.`;
  }
  return "A Campex consolidou os eventos do período, mas ainda não há concentração operacional suficiente para destacar uma área.";
}

function operationsAttention(summary, lossesPayload, comparisonPayload, currentPayload) {
  const callouts = [];
  const topAsset = (lossesPayload.by_asset || [])[0];
  const totalLossDuration = (lossesPayload.by_family || []).reduce((sum, item) => sum + Number(item.total_duration_seconds || 0), 0);
  if (topAsset && totalLossDuration > 0) {
    const share = Math.round((Number(topAsset.total_duration_seconds || 0) / totalLossDuration) * 100);
    callouts.push({
      title: `${topAsset.key} concentrou ${share}% das perdas monitoradas.`,
      why: `${secondsLabel(topAsset.total_duration_seconds)} em ${topAsset.total_events} evento(s) classificados como perda operacional.`,
      event_uuids: topAsset.event_uuids,
    });
  }
  const durationComparison = comparisonFor(comparisonPayload, "total_duration_seconds");
  if (durationComparison.percent_change !== null && Math.abs(durationComparison.percent_change) >= 10) {
    callouts.push({
      title: `A duração total mudou ${comparisonText(durationComparison)}.`,
      why: `${secondsLabel(durationComparison.current)} no período atual contra ${secondsLabel(durationComparison.previous)} no período anterior.`,
      event_uuids: comparisonPayload.current_event_uuids || [],
    });
  }
  const repeatedAsset = (summary.events_by_asset || []).find((item) => item.total_events >= 3 && item.key !== "não informado");
  if (repeatedAsset) {
    callouts.push({
      title: `${repeatedAsset.total_events} ocorrências foram registradas no mesmo ativo.`,
      why: `O ativo ${repeatedAsset.key} repetiu eventos no período selecionado.`,
      event_uuids: repeatedAsset.event_uuids,
    });
  }
  const openClassified = classifiedOpenEvents(currentPayload);
  if (openClassified.length) {
    callouts.push({
      title: `${openClassified.length} evento(s) operacionais continuam abertos.`,
      why: "Há ocorrências físicas em andamento que ainda não foram normalizadas.",
      event_uuids: openClassified.map((event) => event.event_uuid),
    });
  }
  return callouts.slice(0, 4);
}

function renderOperationsCards(summary, currentPayload, comparisonPayload) {
  const families = ["interruption", "wait", "absence", "flow"];
  return families.map((family) => {
    const item = getFamily(summary, family);
    const hasData = item.total_events > 0;
    return `
      <article class="cx-ops-card">
        <span>${familyLabel(family)}</span>
        <strong>${hasData ? secondsLabel(item.total_duration_seconds) : "Sem dados"}</strong>
        <small>${hasData ? `${item.total_events} evento(s)` : "Aguardando eventos reais"}</small>
        ${traceButton("Ver eventos", item.event_uuids)}
      </article>
    `;
  }).join("") + `
    <article class="cx-ops-card cx-ops-card-open">
      <span>Eventos abertos</span>
      <strong>${classifiedOpenEvents(currentPayload).length || 0}</strong>
      <small>Ocorrências operacionais classificadas ainda OPEN</small>
      ${traceButton("Ver ativos", classifiedOpenEvents(currentPayload).map((event) => event.event_uuid))}
    </article>
  `;
}

function eventContextLabel(event) {
  const asset = event.asset_name || event.asset_id || event.machine_name || event.machine_monitor_id;
  const process = event.process_name || event.process_id;
  const area = event.area_name || event.area_context_id || event.area_id;
  const camera = event.camera_name || event.camera_id;
  const primary = asset || process || area || camera || "Contexto operacional não informado";
  const path = [area, process].filter(Boolean).join(" → ");
  return { primary, path: path || camera || "Contexto não informado" };
}

function renderOperationsCurrent(currentPayload) {
  const events = classifiedOpenEvents(currentPayload);
  if (!events.length) return `<div class="cx-empty-state"><strong>Nenhum evento operacional classificado aberto.</strong><p>A operação não possui ocorrências OPEN classificadas no momento.</p></div>`;
  return events.map((event) => `
    <article class="cx-ops-current">
      <strong>${eventContextLabel(event).primary}</strong>
      <span>${familyLabel(event.event_family)} há ${secondsLabel(event.current_duration_seconds)}</span>
      <small>${eventContextLabel(event).path} · workflow: ${event.workflow_status || "new"}</small>
      ${traceButton("Ver evento", [event.event_uuid])}
    </article>
  `).join("");
}

function renderOperationsRanking(title, items = [], total = 0) {
  const rows = (items || []).slice(0, 5);
  if (!rows.length) return `<section class="cx-ops-block"><h3>${title}</h3><p class="muted">Sem dados para ranking.</p></section>`;
  return `
    <section class="cx-ops-block">
      <h3>${title}</h3>
      ${rows.map((item) => {
        const share = total ? Math.round((Number(item.total_duration_seconds || 0) / total) * 100) : 0;
        return `<div class="cx-ops-rank"><strong>${item.key}</strong><span>${secondsLabel(item.total_duration_seconds)} · ${item.total_events} evento(s) · ${share}%</span>${traceButton("Eventos", item.event_uuids)}</div>`;
      }).join("")}
    </section>
  `;
}

function renderUnknownQualityNote(summary, currentPayload) {
  const count = unknownEventCount(summary, currentPayload);
  if (!count) return "";
  return `<div class="cx-ops-quality"><strong>${count} evento(s) ainda não possuem classificação operacional.</strong><span>Eles continuam preservados para auditoria, mas não entram nos indicadores oficiais da Operations.</span></div>`;
}

function renderTraceDrawer(uuids) {
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawerContent.innerHTML = `
    <h2>Eventos relacionados</h2>
    <p>Veja os registros operacionais relacionados a esta informação.</p>
    <ul class="cx-trace-list">${uuids.map((uuid, index) => `<li><a class="cx-link" href="/events?event_uuid=${encodeURIComponent(uuid)}">Abrir evento ${index + 1}</a></li>`).join("")}</ul>
    <p class="muted">Cada item leva ao evento original registrado pela Campex.</p>
  `;
  drawer.querySelector("h2")?.setAttribute("id", "workspaceDrawerTitle");
  drawer.focus({ preventScroll: true });
}

function humanStatus(value) {
  const key = String(value || "").trim().toUpperCase();
  const labels = {
    NORMAL: "Operação normal",
    ATTENTION: "Atenção",
    CRITICAL: "Crítico",
    UNKNOWN: "Sem dados suficientes",
    ACTIVE: "Em operação",
    STOPPED: "Parada",
    PRESENT: "Presença confirmada",
    ABSENT: "Ausência confirmada",
    LOW_ACTIVITY: "Baixa atividade",
    NORMAL_ACTIVITY: "Operação normal",
    NO_ACTIVITY: "Sem atividade",
    ONLINE: "Online",
    OFFLINE: "Offline",
    ALERT: "Alerta",
    OPEN: "Em andamento",
    CLOSED: "Encerrado",
  };
  return labels[key] || value || "Indisponível";
}

function homeContextName(value, fallback = "Ativo sem nome") {
  const text = String(value || "").trim();
  if (!text) return fallback;
  if (/^(evt|cam|opasset|oparea|opproc|area|proc|mach|compat|live|cli|uni)_/i.test(text) || /^[a-f0-9-]{16,}$/i.test(text)) return fallback;
  return text;
}

function homeDataValue(value, formatter = (item) => item) {
  if (value === null || value === undefined) return "Indisponível";
  return formatter(value);
}

function homeBusinessLabel(value, fallback = "Não informado") {
  const text = String(value ?? "").trim();
  if (!text) return fallback;
  const key = text.toLowerCase();
  const labels = {
    machine: "Máquina",
    workstation: "Posto operacional",
    asset: "Ativo",
    open: "Aberto",
    closed: "Encerrado",
    new: "Novo",
    acknowledged: "Reconhecido",
    resolved: "Resolvido",
    unknown: "Dados insuficientes",
    not_available: "Não disponível",
    available: "Disponível",
    partial: "Parcial",
    observed: "Observada",
  };
  if (labels[key]) return labels[key];
  if (/^(evt|cam|opasset|area|proc|mach|compat|live)_/i.test(text) || /^[a-f0-9-]{16,}$/i.test(text)) return fallback;
  return text;
}

function homeDefaultPeriod() {
  const now = new Date();
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  return { start: start.toISOString(), end: now.toISOString() };
}

function homeDefaultSummary() {
  return {
    period: homeDefaultPeriod(),
    coverage: { status: "unknown", reason: "Cobertura ainda não informada pelo backend.", gaps: [] },
    events_by_family: [],
    events_by_area: [],
    events_by_asset: [],
    total_events: 0,
  };
}

function homeDefaultCurrent() {
  return { open_events: [] };
}

function homeDefaultTimeline() {
  return { items: [] };
}

function homeDefaultSetup() {
  return { assets: [], areas: [], processes: [] };
}

function homeDefaultEvents() {
  return { events: [] };
}

function homeDefaultInsights() {
  return { briefing: [], insights: [], patterns: [], kpis: [], coverage: { status: "unknown" } };
}

function homeDefaultOperationalData() {
  return {
    machine_metrics: [],
    human_operation: {},
    safety_zones: {},
    reports: {},
    coverage: { status: "unknown" },
  };
}

async function homeResource(url, fallback) {
  try {
    return { ok: true, data: await requestJson(url), error: null, url };
  } catch (error) {
    return { ok: false, data: fallback, error: error.message || "Falha ao carregar seção.", url };
  }
}

function homeSectionStatus(result, availableLabel = "Dados reais") {
  if (result?.ok) return `<small>${availableLabel}</small>`;
  return `<small>Indisponível: ${sanitize(result?.error || "falha de carregamento")}</small>`;
}

function homeMetric(label, value, detail, icon = "info", tone = "") {
  const toneClass = tone ? ` cx-home-kpi-${sanitize(tone)}` : "";
  return `
    <article class="cx-home-kpi${toneClass}">
      <span class="cx-home-kpi-icon" data-icon="${sanitize(icon)}"></span>
      <span class="cx-home-kpi-label">${label}</span>
      <strong>${value}</strong>
      <small>${detail}</small>
    </article>
  `;
}

function homeTopbarStatus(summary) {
  const coverage = homeCoverageState(summary.coverage);
  if (coverage.tone === "good") return "Sistemas normais";
  if (coverage.tone === "attention") return "Cobertura parcial";
  return "Dados insuficientes";
}

function homeCoverageState(coverage) {
  if (!coverage || !coverage.status) return { label: "Cobertura desconhecida", tone: "unknown" };
  if (coverage.status === "observed") return { label: "Cobertura observada", tone: "good" };
  if (coverage.status === "partial") return { label: "Cobertura parcial", tone: "attention" };
  return { label: "Cobertura insuficiente", tone: "unknown" };
}

function homeAttention(alertPayload, summary) {
  const alerts = (alertPayload.decisions || []).filter((decision) => decision.decision === "ALERT");
  const sorted = alerts.sort((a, b) => ({"critical": 4, "high": 3, "medium": 2, "low": 1}[b.severity] || 0) - ({"critical": 4, "high": 3, "medium": 2, "low": 1}[a.severity] || 0));
  if (sorted.length) {
    const item = sorted[0];
    return {
      hasAlert: true,
      html: `
        <article class="cx-home-attention-card critical">
          <span>${homeBusinessLabel(item.severity || "high", "Prioridade")}</span>
          <strong>${item.title || "Incidente operacional requer atenção"}</strong>
          <p>${item.summary || "A Campex encontrou uma condição operacional sustentada por dados reais."}</p>
          <div class="cx-home-meta">
            <span>${homeContextName(item.asset_label || item.asset_id || item.camera_name || item.camera_id, "Contexto operacional")}</span>
            <span>${(item.reason_codes || []).slice(0, 2).join(" · ") || "Motivo factual registrado"}</span>
          </div>
          ${traceButton("Ver incidente", item.event_refs || [])}
        </article>
      `,
    };
  }
  const coverage = homeCoverageState(summary.coverage);
  if (coverage.tone !== "good") {
    return {
      hasAlert: false,
      html: `
        <article class="cx-home-attention-card unknown">
          <span>${coverage.label}</span>
          <strong>Cobertura insuficiente para afirmar normalidade.</strong>
          <p>A Campex ainda não possui observação confiável o bastante neste período.</p>
        </article>
      `,
    };
  }
  return {
    hasAlert: false,
    html: `
      <article class="cx-home-attention-card normal">
        <span>Sem criticidade ativa</span>
        <strong>Nenhuma situação crítica exige atenção agora.</strong>
        <p>Não há decisões críticas de alerta no período consultado.</p>
      </article>
    `,
  };
}

function renderHomeMetrics(currentPayload, summary, briefing, impact) {
  const coverage = homeCoverageState(summary.coverage);
  const openEvents = classifiedOpenEvents(currentPayload).length;
  const downtime = impact.operational_impact?.downtime_seconds ?? impact.machine_metrics?.downtime_seconds;
  const incidents = impact.operational_impact?.incident_count ?? summary.total_events;
  const monitoredAssets = impact.machine_metrics?.length ?? 0;
  const metrics = [
    homeMetric("Incidentes ativos", openEvents, "Eventos físicos abertos", "alert"),
    homeMetric("Downtime observado", homeDataValue(downtime, secondsLabel), incidents ? `${incidents} incidente(s) no período` : "Sem incidentes de downtime", "clock"),
    homeMetric("Ativos", monitoredAssets || "Indisponível", monitoredAssets ? "Com dados operacionais" : "Aguardando dados de ativos", "asset"),
    homeMetric("Cobertura", coverage.label, summary.coverage?.sample_count ? `${summary.coverage.sample_count} amostras` : "Amostras insuficientes ou indisponíveis", "signal"),
  ];
  return `
    <section class="cx-home-kpi-grid" aria-label="Indicadores principais">
      ${metrics.join("")}
    </section>
  `;
}

function renderHomeProtectedMetrics() {
  return `
    <section class="cx-home-kpi-grid" aria-label="Indicadores principais">
      ${[
        homeMetric("Ativos monitorados", "Não disponível", "Entre para carregar ativos reais", "asset"),
        homeMetric("Downtime observado", "Não disponível", "Entre para carregar o período", "clock"),
        homeMetric("Incidentes ativos", "Não disponível", "Entre para carregar eventos", "alert"),
        homeMetric("Cobertura dos dados", "Não disponível", "Entre para carregar amostras", "signal"),
      ].join("")}
    </section>
  `;
}

function renderHomeActivity(timelinePayload) {
  const items = (timelinePayload.items || []).filter((item) => ["machine_activity", "person_presence", "zone_occupancy", "operational_activity", "event_started", "event_closed"].includes(item.type)).slice(-8).reverse();
  if (!items.length) {
    return `<div class="cx-home-empty"><strong>Aguardando dados da operação.</strong><p>A atividade recente aparecerá quando houver amostras ou eventos reais.</p></div>`;
  }
  return `
    <div class="cx-home-timeline-list">
      ${items.map((item) => {
        const state = String(item.new_state || item.state || "unknown").toLowerCase();
        const context = homeContextName(item.asset_name || item.asset_id || item.area_name || item.camera_name || item.camera_id, "Contexto operacional");
        return `
          <article class="cx-home-timeline-item ${sanitize(state)}">
            <time>${item.timestamp ? new Date(item.timestamp).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "—"}</time>
            <i aria-hidden="true"></i>
            <div>
              <strong>${humanStatus(item.new_state || item.state || item.type)}</strong>
              <small>${context}</small>
            </div>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderHomeActivityLegend() {
  return `
    <div class="cx-home-activity-legend">
      <span><i class="running"></i>Operação</span>
      <span><i class="stopped"></i>Parada</span>
      <span><i class="low"></i>Baixa atividade</span>
      <span><i class="unknown"></i>Sem dados</span>
    </div>
  `;
}

function renderHomeAssets(setupPayload, currentPayload) {
  const assets = setupPayload.assets || [];
  if (!assets.length) return `<div class="cx-home-empty"><strong>Nenhum ativo configurado.</strong><p>Configure a hierarquia operacional em Configurações para a Campex contextualizar a operação.</p><a class="cx-secondary-action" href="/settings/cameras">Abrir Configurações</a></div>`;
  const openEvents = classifiedOpenEvents(currentPayload);
  return assets.slice(0, 6).map((asset) => {
    const activeEvent = openEvents.find((event) => event.asset_id === asset.id);
    return `
      <article class="cx-home-asset">
        <div>
          <strong>${homeContextName(asset.nome)}</strong>
          <span>${homeBusinessLabel(asset.tipo, "Ativo operacional")}</span>
        </div>
        <div>
          ${activeEvent ? badge("Evento aberto") : badge(asset.ativo ? "Monitorável" : "Inativo")}
          <small>${activeEvent ? `${familyLabel(activeEvent.event_family)} · ${secondsLabel(activeEvent.current_duration_seconds)}` : "Sem evento aberto informado"}</small>
        </div>
      </article>
    `;
  }).join("");
}

function renderHomeIncidents(eventsPayload, alertPayload) {
  const alertRefs = new Set((alertPayload.decisions || []).flatMap((item) => item.event_refs || []));
  const sourceEvents = Array.isArray(eventsPayload) ? eventsPayload : (eventsPayload.events || []);
  const events = sourceEvents.filter((event) => isOfficialFamily(event.event_family)).slice(0, 5);
  if (!events.length) return `<div class="cx-home-empty"><strong>Nenhum incidente relevante no período.</strong><p>Eventos reais aparecerão aqui quando a Campex registrar ocorrências operacionais.</p></div>`;
  return events.map((event) => {
    const context = eventContextLabel(event);
    const uuid = event.event_uuid;
    return `
    <article class="cx-home-incident">
      <strong>${familyLabel(event.event_family)}</strong>
      <span>${event.fim ? secondsLabel(event.duracao || event.read_duration_seconds) : "Em andamento"}</span>
      <small>${alertRefs.has(uuid) ? "Alerta · " : "Registrado · "}${homeContextName(context.primary, "Contexto operacional")}</small>
      ${traceButton("Ver incidente", [uuid])}
    </article>
  `;
  }).join("");
}

function renderHomeImpact(impact) {
  const financial = impact.financial_impact || {};
  const operational = impact.operational_impact || {};
  const machineMetrics = impact.machine_metrics || [];
  const downtime = operational.downtime_seconds ?? machineMetrics.reduce((sum, item) => sum + Number(item.stopped_seconds || item.downtime_seconds || 0), 0);
  const financialLine = financial.status === "AVAILABLE" || financial.status === "PARTIAL"
    ? `${financial.currency || ""} ${Number(financial.estimated_amount || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "Impacto financeiro não configurado";
  return `
    <section class="cx-home-impact-list">
      <article>
        <span>Impacto operacional</span>
        <strong>${homeDataValue(downtime, secondsLabel)}</strong>
        <small>Downtime observado pelo backend</small>
      </article>
      <article>
        <span>Impacto financeiro</span>
        <strong>${financialLine}</strong>
        <small>${homeBusinessLabel(financial.status || "not_available")}</small>
      </article>
    </section>
  `;
}

function renderHomeOperationalSummary(currentPayload, summary, operationalData, setupPayload, failedSections) {
  const coverage = homeCoverageState(summary.coverage);
  const openEvents = classifiedOpenEvents(currentPayload).length;
  const downtime = operationalData.operational_impact?.downtime_seconds ?? operationalData.machine_metrics?.downtime_seconds;
  const assetsCount = (setupPayload.assets || []).length;
  return `
    <div class="cx-home-summary-list">
      <div><span>Downtime</span><strong>${homeDataValue(downtime, secondsLabel)}</strong></div>
      <div><span>Incidentes</span><strong>${summary.total_events ?? openEvents ?? "Indisponível"}</strong></div>
      <div><span>Cobertura</span><strong>${coverage.label}</strong></div>
      <div><span>Ativos</span><strong>${assetsCount || "Indisponível"}</strong></div>
    </div>
    <div class="cx-home-summary-note">
      <strong>${coverage.tone === "good" ? "Leitura operacional disponível." : "Leitura operacional limitada."}</strong>
      <p>${summary.coverage?.reason || "A Campex apresenta somente dados sustentados por eventos e amostras reais."}</p>
    </div>
    <details class="cx-home-data-details">
      <summary>Detalhes dos dados</summary>
      <p>Gaps: ${(summary.coverage?.gaps || []).length}</p>
      <p>Dados insuficientes: ${operationalData.quality?.reasons?.includes("unknown_period_present") ? "presente" : "não informado"}</p>
      ${failedSections.length ? `<p>Seções indisponíveis: ${failedSections.map((item) => sanitize(item.url.split("?")[0])).join(", ")}</p>` : "<p>Sem falhas de carregamento informadas pelo frontend.</p>"}
    </details>
  `;
}

function operationsStateLabel(value) {
  const key = String(value || "").toUpperCase();
  const labels = {
    RUNNING: "Em operação",
    ACTIVE: "Em operação",
    NORMAL_ACTIVITY: "Em operação",
    STOPPED: "Parado",
    LOW_ACTIVITY: "Baixa atividade",
    NO_ACTIVITY: "Sem atividade",
    UNKNOWN: "Dados insuficientes",
    OFFLINE: "Offline",
    EVENT_OPEN: "Incidente ativo",
  };
  return labels[key] || homeBusinessLabel(value, "Dados insuficientes");
}

function operationsStateTone(value) {
  const key = String(value || "").toUpperCase();
  if (["RUNNING", "ACTIVE", "NORMAL_ACTIVITY", "PRESENT", "ONLINE"].includes(key)) return "running";
  if (["STOPPED", "NO_ACTIVITY", "OFFLINE"].includes(key)) return "stopped";
  if (["LOW_ACTIVITY", "EVENT_OPEN"].includes(key)) return "attention";
  return "unknown";
}

function operationsStateDot(value) {
  const label = operationsStateLabel(value);
  return `<span class="cx-ops-state ${operationsStateTone(value)}"><i></i>${label}</span>`;
}

function operationsLatestByAsset(timelinePayload) {
  const latest = new Map();
  (timelinePayload.items || []).forEach((item) => {
    const assetId = item.asset_id || item.context?.asset_id;
    if (!assetId) return;
    const previous = latest.get(assetId);
    if (!previous || new Date(item.timestamp).getTime() > new Date(previous.timestamp).getTime()) latest.set(assetId, item);
  });
  return latest;
}

function operationsEventAssetId(event) {
  return event.asset_id || event.machine_id || event.machine_monitor_id || event.context?.asset_id;
}

function operationsAreaLabel(value) {
  const text = String(value || "").trim();
  if (!text) return "Área não identificada";
  const technicalId = /^(oparea|area|opproc|process|asset|camera|cam)[_-][a-z0-9_-]{6,}$/i.test(text);
  if (technicalId) return "Área não identificada";
  return homeContextName(text, "Área não identificada");
}

function operationsAssetRows(setupPayload, currentPayload, timelinePayload, eventsPayload) {
  const latest = operationsLatestByAsset(timelinePayload);
  const sourceEvents = Array.isArray(eventsPayload) ? eventsPayload : (eventsPayload.events || []);
  const openEvents = classifiedOpenEvents(currentPayload);
  const assets = setupPayload.assets || [];
  const rows = assets.map((asset) => {
    const activeEvent = openEvents.find((event) => operationsEventAssetId(event) === asset.id);
    const latestItem = latest.get(asset.id);
    const relatedEvent = sourceEvents.find((event) => operationsEventAssetId(event) === asset.id);
    const state = activeEvent
      ? (activeEvent.event_family === "interruption" ? "STOPPED" : "EVENT_OPEN")
      : (latestItem?.new_state || latestItem?.state || "UNKNOWN");
    return {
      id: asset.id,
      name: homeContextName(asset.nome || asset.name, "Ativo operacional"),
      area: operationsAreaLabel(asset.area_name || asset.area || asset.area_id || asset.area_context_id),
      state,
      stateLabel: operationsStateLabel(state),
      tone: operationsStateTone(state),
      durationSeconds: activeEvent?.current_duration_seconds ?? latestItem?.duration_seconds ?? null,
      activity: latestItem ? humanStatus(latestItem.new_state || latestItem.state) : "Dados insuficientes",
      incident: activeEvent ? familyLabel(activeEvent.event_family) : "Sem incidente ativo",
      eventUuid: activeEvent?.event_uuid || relatedEvent?.event_uuid,
      updatedAt: latestItem?.timestamp || activeEvent?.inicio || relatedEvent?.inicio || null,
    };
  });
  if (rows.length) return rows;
  return (openEvents || []).map((event) => {
    const context = eventContextLabel(event);
    const state = event.event_family === "interruption" ? "STOPPED" : "EVENT_OPEN";
    return {
      id: operationsEventAssetId(event) || event.event_uuid,
      name: homeContextName(context.primary, "Ativo operacional"),
      area: operationsAreaLabel(context.path),
      state,
      stateLabel: operationsStateLabel(state),
      tone: operationsStateTone(state),
      durationSeconds: event.current_duration_seconds ?? event.read_duration_seconds ?? null,
      activity: familyLabel(event.event_family),
      incident: familyLabel(event.event_family),
      eventUuid: event.event_uuid,
      updatedAt: event.inicio || null,
    };
  });
}

function operationsFilterRows(rows) {
  const state = operationsSelectedState || "all";
  const asset = operationsSelectedAsset || "";
  return rows.filter((row) => {
    const matchesState = state === "all" || row.tone === state || String(row.state).toLowerCase() === state;
    const matchesAsset = !asset || String(row.id || row.name) === asset;
    return matchesState && matchesAsset;
  });
}

function operationsMetricValue(value) {
  return value === null || value === undefined ? "Indisponível" : value;
}

function renderOperationsMetrics(rows, summary) {
  const knownRows = rows.filter((row) => row.tone !== "unknown");
  const running = knownRows.filter((row) => row.tone === "running").length;
  const stopped = knownRows.filter((row) => row.tone === "stopped").length;
  const coverage = homeCoverageState(summary.coverage);
  const metrics = [
    homeMetric("Ativos monitorados", operationsMetricValue(rows.length || null), rows.length ? "Ativos/áreas com contexto operacional" : "Aguardando Configurações", "asset", "assets"),
    homeMetric("Em operação", operationsMetricValue(knownRows.length ? running : null), "Estados confirmados pelos dados atuais", "signal", "running"),
    homeMetric("Parados", operationsMetricValue(knownRows.length ? stopped : null), "Paradas ou ausência de atividade", "pause", "stopped"),
    homeMetric("Cobertura dos dados", coverage.label, summary.coverage?.sample_count ? `${summary.coverage.sample_count} amostras` : "Amostras insuficientes ou indisponíveis", "coverage", "coverage"),
  ];
  return `<section class="cx-home-kpi-grid cx-ops-v1-metrics" aria-label="Resumo operacional">${metrics.join("")}</section>`;
}

function renderOperationsFilters(rows) {
  const assetOptions = rows.map((row) => `<option value="${sanitize(row.id || row.name)}" ${operationsSelectedAsset === String(row.id || row.name) ? "selected" : ""}>${sanitize(row.name)}</option>`).join("");
  return `
    <div class="cx-ops-v1-filters">
      <label>Período
        <select id="operationsPeriod">
          <option value="day" ${operationPeriod() === "day" ? "selected" : ""}>Hoje</option>
          <option value="turno" ${operationPeriod() === "turno" ? "selected" : ""}>Turno</option>
          <option value="week" ${operationPeriod() === "week" ? "selected" : ""}>Semana</option>
          <option value="month" ${operationPeriod() === "month" ? "selected" : ""}>Mês</option>
        </select>
      </label>
      <label>Estado
        <select id="operationsStateFilter">
          <option value="all" ${operationsSelectedState === "all" ? "selected" : ""}>Todos</option>
          <option value="running" ${operationsSelectedState === "running" ? "selected" : ""}>Em operação</option>
          <option value="stopped" ${operationsSelectedState === "stopped" ? "selected" : ""}>Parados</option>
          <option value="attention" ${operationsSelectedState === "attention" ? "selected" : ""}>Atenção</option>
          <option value="unknown" ${operationsSelectedState === "unknown" ? "selected" : ""}>Dados insuficientes</option>
        </select>
      </label>
      ${assetOptions ? `<label>Ativo<select id="operationsAssetFilter"><option value="">Todos</option>${assetOptions}</select></label>` : ""}
    </div>
  `;
}

function renderOperationsAssetList(rows) {
  const filtered = operationsFilterRows(rows);
  if (!filtered.length) {
    return `<div class="cx-home-empty"><strong>Nenhum ativo encontrado para esta seleção.</strong><p>Ajuste o filtro ou configure ativos e áreas em Configurações.</p></div>`;
  }
  return `
    <div class="cx-ops-asset-list" aria-label="Ativos monitorados">
      <div class="cx-ops-asset-head" aria-hidden="true">
        <span>Ativo</span>
        <span>Status</span>
        <span>Leitura operacional</span>
        <span>Atualização</span>
      </div>
      ${filtered.map((row) => `
        <button class="cx-ops-asset-row" type="button" data-event-uuids="${row.eventUuid || ""}" ${row.eventUuid ? "" : "disabled"}>
          <span class="cx-ops-asset-primary">
            <i class="cx-ops-asset-icon" aria-hidden="true"><span class="cx-nav-icon" data-icon="operations"></span></i>
            <span>
              <strong>${row.name}</strong>
              <small>${row.area}</small>
            </span>
          </span>
          <span class="cx-ops-asset-status">
            ${operationsStateDot(row.state)}
            <small>${row.durationSeconds === null || row.durationSeconds === undefined ? "Tempo indisponível" : `${secondsLabel(row.durationSeconds)} no estado`}</small>
          </span>
          <span class="cx-ops-asset-reading">
            <small>Atividade: ${row.activity}</small>
            <small>Incidente: <b class="cx-ops-incident ${row.incident === "Sem incidente ativo" ? "clear" : "active"}">${row.incident}</b></small>
          </span>
          <span class="cx-ops-updated">${row.updatedAt ? new Date(row.updatedAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "Indisponível"}${row.eventUuid ? "<i>›</i>" : ""}</span>
        </button>
      `).join("")}
    </div>
  `;
}

function renderOperationsRecentActivity(timelinePayload) {
  const items = (timelinePayload.items || []).filter((item) => ["machine_activity", "person_presence", "zone_occupancy", "operational_activity", "event_started", "event_closed"].includes(item.type)).slice(-6).reverse();
  if (!items.length) {
    return `<div class="cx-home-empty"><strong>Nenhuma mudança recente disponível.</strong><p>A Campex mostrará mudanças relevantes quando houver timeline real no período.</p></div>`;
  }
  return `<div class="cx-ops-recent-activity">${items.map((item) => {
    const context = homeContextName(item.asset_name || item.asset_id || item.camera_name || item.camera_id, "Contexto operacional");
    const time = item.timestamp ? new Date(item.timestamp).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "Horário indisponível";
    const state = String(item.new_state || item.state || "unknown").toLowerCase();
    return `<article class="cx-ops-activity-row ${sanitize(state)}"><time>${time}</time><i aria-hidden="true"></i><div><strong>${humanStatus(item.new_state || item.state)}</strong><span>${context}</span></div></article>`;
  }).join("")}</div>`;
}

async function renderHomePage(config) {
  const params = readModelQuery();
  const [currentResult, summaryResult, timelineResult, insightsResult, operationalDataResult, setupResult, eventsResult] = await Promise.all([
    homeResource(`/operations/read-model/current?${params}`, homeDefaultCurrent()),
    homeResource(`/operations/read-model/summary?${params}`, homeDefaultSummary()),
    homeResource(`/operations/timeline?${params}`, homeDefaultTimeline()),
    homeResource(`/operations/read-model/insights?${params}`, homeDefaultInsights()),
    homeResource(`/operations/read-model/operational-data?${params}`, homeDefaultOperationalData()),
    homeResource("/setup/operation", homeDefaultSetup()),
    homeResource("/eventos", homeDefaultEvents()),
  ]);
  const currentPayload = currentResult.data;
  const summary = currentResult.ok || summaryResult.ok ? summaryResult.data : homeDefaultSummary();
  const timelinePayload = timelineResult.data;
  const insightsPayload = insightsResult.data;
  const operationalData = operationalDataResult.data;
  const setupPayload = setupResult.data;
  const eventsPayload = eventsResult.data;
  const sourceEvents = Array.isArray(eventsPayload) ? eventsPayload : (eventsPayload.events || []);
  const alertPayload = { decisions: [] };
  const attention = homeAttention(alertPayload, summary);
  const classifiedCount = officialEventCount(summary);
  const briefingLine = insightsPayload.briefing?.[0] || insightsPayload.headline || "A Campex está aguardando dados suficientes para montar uma leitura operacional.";
  const failedSections = [currentResult, summaryResult, timelineResult, insightsResult, operationalDataResult, setupResult, eventsResult].filter((item) => !item.ok);
  const coverage = homeCoverageState(summary.coverage);

  title.textContent = "Início";
  heading.textContent = "Visão atual da sua operação.";
  subtitle.textContent = "Dados reais da instalação Campex, sem preenchimento demonstrativo.";
  tableTitle.textContent = "";
  tableHint.textContent = "";
  primaryAction.textContent = "Atualizar";
  primaryAction.onclick = () => loadPage();
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  rowsCache = [];
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  body.closest("table")?.setAttribute("aria-hidden", "true");
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");

  cards.innerHTML = `
    <section class="cx-home-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar ativos, incidentes, câmeras...</div>
        <div class="cx-home-topbar-actions">
          <span>${homeContextName(summary.filters?.site_id || "Unidade principal", "Unidade principal")}</span>
          <span>${homeTopbarStatus(summary)}</span>
        </div>
      </div>
      <header class="cx-home-hero">
        <div>
          <span>Início</span>
          <h2>Visão atual da sua operação.</h2>
          <p>${briefingLine}</p>
        </div>
        <div class="cx-home-hero-meta" aria-label="Contexto do período">
          <div>
            <small>Período</small>
            <strong>${formatOperationsPeriod(summary.period)}</strong>
          </div>
          <div>
            <small>Cobertura</small>
            <strong>${coverage.label}</strong>
          </div>
        </div>
      </header>

      ${renderHomeMetrics(currentPayload, summary, insightsPayload, operationalData)}

      <section class="cx-home-main-grid">
        <div class="cx-home-main-column">
          <section class="cx-home-attention">
            <div class="cx-home-section-head">
              <span>O que merece atenção</span>
              <small>${attention.hasAlert ? "Decisão crítica real" : coverage.tone !== "good" ? coverage.label : "Sem alerta crítico ativo"}</small>
            </div>
            ${attention.html}
          </section>

          <section class="cx-home-activity">
            <div class="cx-home-section-head">
              <span>Atividade recente</span>
              ${homeSectionStatus(timelineResult, `${(timelinePayload.items || []).length} mudança(s) no período`)}
            </div>
            ${renderHomeActivity(timelinePayload)}
          </section>
        </div>

        <aside class="cx-home-side-column">
          <section class="cx-home-summary">
            <div class="cx-home-section-head">
              <span>Resumo operacional</span>
              ${homeSectionStatus(currentResult, coverage.label)}
            </div>
            ${renderHomeOperationalSummary(currentPayload, summary, operationalData, setupPayload, failedSections)}
          </section>
        </aside>
      </section>

      <section class="cx-home-list-grid">
        <section class="cx-home-section">
          <div class="cx-home-section-head">
            <span>Ativos / áreas</span>
            <small>${(setupPayload.assets || []).length || "Nenhum ativo"}</small>
          </div>
          <div class="cx-home-list">${renderHomeAssets(setupPayload, currentPayload)}</div>
        </section>

        <section class="cx-home-section">
          <div class="cx-home-section-head">
            <span>Incidentes recentes</span>
            <small>${summary.total_events || 0} evento(s)</small>
          </div>
          <div class="cx-home-list">${renderHomeIncidents(eventsPayload, alertPayload)}</div>
        </section>
      </section>

      <section class="cx-home-secondary-row">
        <section class="cx-home-secondary-panel">
          <div class="cx-home-section-head">
            <span>Impacto operacional</span>
            ${homeSectionStatus(operationalDataResult, "Dados do período")}
          </div>
          ${renderHomeImpact(operationalData)}
        </section>

        <section class="cx-home-secondary-panel">
          <div class="cx-home-section-head">
            <span>Resumo do período</span>
            ${homeSectionStatus(insightsResult, humanStatus(insightsPayload.overall_status || "UNKNOWN"))}
          </div>
          <article class="cx-home-period-briefing">
            <strong>${classifiedCount ? briefingLine : "Sem dados operacionais suficientes neste período."}</strong>
            <p>${(insightsPayload.insights || []).slice(0, 2).map((item) => item.statement || item.text).join(" ") || "Aguardando eventos e amostras reais para formar destaques."}</p>
          </article>
        </section>
      </section>
    </section>
  `;
  openEventFromQuery(config, sourceEvents);
}

async function renderOperationsReadModelPage(config) {
  const params = readModelQuery();
  const [currentResult, summaryResult, timelineResult, setupResult, eventsResult] = await Promise.all([
    homeResource(`/operations/read-model/current?${params}`, homeDefaultCurrent()),
    homeResource(`/operations/read-model/summary?${params}`, homeDefaultSummary()),
    homeResource(`/operations/timeline?${params}`, homeDefaultTimeline()),
    homeResource("/setup/operation", homeDefaultSetup()),
    homeResource("/eventos", homeDefaultEvents()),
  ]);
  const currentPayload = currentResult.data;
  const summary = summaryResult.data;
  const timelinePayload = timelineResult.data;
  const setupPayload = setupResult.data;
  const eventsPayload = eventsResult.data;
  const assetRows = operationsAssetRows(setupPayload, currentPayload, timelinePayload, eventsPayload);
  const coverage = homeCoverageState(summary.coverage);
  const failedSections = [currentResult, summaryResult, timelineResult, setupResult, eventsResult].filter((item) => !item.ok);
  rowsCache = operationsFilterRows(assetRows);
  title.textContent = "Operação";
  heading.textContent = "Estado operacional da sua planta.";
  subtitle.textContent = "Estados, incidentes e qualidade de dados vindos do runtime e dos eventos reais da Campex.";
  tableTitle.textContent = "";
  tableHint.textContent = "";
  primaryAction.textContent = "Atualizar";
  primaryAction.onclick = () => loadPage(window.location.pathname);
  renderTabs(config);
  renderFilters({ filters: [] });
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  body.closest("table")?.setAttribute("aria-hidden", "true");
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");
  cards.innerHTML = `
    <section class="cx-ops-v1-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar ativos, incidentes, câmeras...</div>
        <div class="cx-home-topbar-actions">
          <span>${homeContextName(summary.filters?.site_id || "Unidade principal", "Unidade principal")}</span>
          <span>${coverage.label}</span>
        </div>
      </div>
      <header class="cx-ops-hero">
        <span class="cx-ops-hero-icon" aria-hidden="true"><span class="cx-nav-icon" data-icon="operations"></span></span>
        <div>
          <span>Operação</span>
          <h2>Estado operacional da sua planta.</h2>
          <p>Veja o que está em operação, parado ou exigindo atenção agora.</p>
        </div>
        <div class="cx-ops-context">
          <div><small>Período</small><strong>${formatOperationsPeriod(summary.period)}</strong></div>
          <div><small>Unidade</small><strong>${homeContextName(summary.filters?.site_id || "Unidade principal", "Unidade principal")}</strong></div>
          <div><small>Cobertura</small><strong>${coverage.label}</strong></div>
        </div>
      </header>

      ${renderOperationsMetrics(assetRows, summary)}

      ${coverage.status === "partial" || coverage.status === "unknown" ? `<div class="cx-home-quality-note"><strong>${coverage.label}</strong><span>${summary.coverage?.reason || "A Campex ainda não recebeu amostras suficientes para afirmar normalidade operacional."}</span></div>` : ""}

      <section class="cx-home-section cx-ops-v1-assets">
        <div class="cx-home-section-head">
          <span>Ativos monitorados</span>
          <small>${assetRows.length ? `${assetRows.length} ativo(s)` : "Aguardando configuração"}</small>
        </div>
        ${renderOperationsFilters(assetRows)}
        ${renderOperationsAssetList(assetRows)}
      </section>

      <section class="cx-ops-bottom-grid">
        <section class="cx-home-section">
          <div class="cx-home-section-head">
            <span>Atividade recente</span>
            <small>${(timelinePayload.items || []).length} mudança(s)</small>
          </div>
          ${renderOperationsRecentActivity(timelinePayload)}
        </section>
        <section class="cx-home-section">
          <div class="cx-home-section-head">
            <span>Qualidade dos dados</span>
            <small>${coverage.label}</small>
          </div>
          <div class="cx-home-quality">
            <div class="cx-ops-quality-radial" data-tone="${sanitize(coverage.tone)}">
              <strong>${coverage.label}</strong>
            </div>
            <strong>${coverage.label}</strong>
            <p>${summary.coverage?.sample_count ? `${summary.coverage.sample_count} amostras. ` : ""}${summary.coverage?.reason || "Qualidade informada pelos dados operacionais da Campex."}</p>
            <details class="cx-home-data-details">
              <summary>Detalhes dos dados</summary>
              <p>Eventos abertos: ${classifiedOpenEvents(currentPayload).length}</p>
              <p>Confiança: ${coverage.status === "unknown" ? "dados insuficientes" : coverage.label}</p>
              <p>Amostras: ${summary.coverage?.sample_count ?? "não informado"}</p>
              <p>Dados insuficientes: ${coverage.status === "unknown" ? "sim" : "não informado"}</p>
              ${failedSections.length ? `<p>Seções indisponíveis: ${failedSections.map((item) => sanitize(item.url.split("?")[0])).join(", ")}</p>` : "<p>Sem falhas de carregamento informadas pelo frontend.</p>"}
            </details>
          </div>
        </section>
      </section>
    </section>
  `;
}

function intelligenceBriefingText(payload) {
  const lines = payload.briefing || [];
  if (!lines.length) return "Ainda não existem eventos operacionais classificados suficientes neste período.";
  return humanInsightText(lines.join(" "));
}

function intelligenceKpiValue(kpi) {
  if (kpi.value_seconds !== undefined && kpi.value_seconds !== null) return secondsLabel(kpi.value_seconds);
  if (kpi.value !== undefined && kpi.value !== null) return String(kpi.value);
  return "Sem dados";
}

function humanTechnicalLabel(value, fallback = "Não informado") {
  const text = String(value || "").trim();
  if (!text || text === "null" || text === "undefined") return fallback;
  if (text === "não informado") return "Não informado";
  const technical = /^(mach|machine|asset|area|proc|process|cam|camera|evt|event|rule|unit|site|mon)_[a-z0-9_-]+$/i;
  const uuid = /^[0-9a-f]{8}-[0-9a-f-]{13,}$/i;
  if (technical.test(text) || uuid.test(text)) return fallback;
  return text;
}

function humanInsightText(value) {
  return sanitize(value || "")
    .replace(/\bmach_[a-z0-9_-]+\b/gi, "ativo monitorado")
    .replace(/\bmachine_[a-z0-9_-]+\b/gi, "ativo monitorado")
    .replace(/\basset_[a-z0-9_-]+\b/gi, "ativo monitorado")
    .replace(/\barea_[a-z0-9_-]+\b/gi, "área monitorada")
    .replace(/\bproc_[a-z0-9_-]+\b/gi, "processo monitorado")
    .replace(/\bcam_[a-z0-9_-]+\b/gi, "câmera monitorada")
    .replace(/\bevt_[a-z0-9_-]+\b/gi, "evento rastreável")
    .replace(/\b[0-9a-f]{8}-[0-9a-f-]{13,}\b/gi, "registro rastreável")
    .replace(/\bmachine_stoppage\b/g, "parada operacional")
    .replace(/\bworkstation_unattended\b/g, "ausência operacional")
    .replace(/\bmachine_running_without_operator\b/g, "máquina ativa sem operador")
    .replace(/\bmachine_stopped_with_operator\b/g, "máquina parada com operador");
}

function humanKpiLabel(label) {
  const labels = {
    "Duração de interrupções": "Interrupções",
    "Frequência de interrupções": "Frequência",
    "Duração média": "Duração média",
    "Espera": "Espera",
    "Ausência": "Ausência operacional",
    "Recorrência": "Recorrência",
  };
  return labels[label] || humanInsightText(label || "Indicador");
}

function insightTraceAction(item, label = "Investigar") {
  const count = (item?.event_uuids || []).filter(Boolean).length;
  const text = count ? `${label} ${count} evento${count === 1 ? "" : "s"}` : label;
  return traceButton(text, item?.event_uuids);
}

function renderInsightCard(item) {
  return `
    <article class="cx-intel-card">
      <i aria-hidden="true"></i>
      <div>
        <strong>${humanInsightText(item.statement)}</strong>
        <p><b>Por que a Campex está destacando isso?</b> ${humanInsightText(item.why || "Insight gerado por regra determinística a partir dos eventos do período.")}</p>
        <div class="cx-intel-trace">${insightTraceAction(item, "Ver eventos relacionados")}</div>
      </div>
      <span>${humanInsightText(item.number || "Verificável")}</span>
    </article>
  `;
}

function renderInsightList(items, emptyText) {
  if (!items?.length) return `<div class="cx-empty-state"><strong>${emptyText}</strong><p>A Campex não inventa padrões quando os dados não sustentam a afirmação.</p></div>`;
  return `<div class="cx-intel-list">${items.map(renderInsightCard).join("")}</div>`;
}

function renderCauseRows(causes = []) {
  if (!causes.length) return `<p class="muted">Nenhuma causa confirmada foi registrada por humanos neste período.</p>`;
  return causes.map((cause) => `
    <div class="cx-intel-cause">
      <strong>${humanTechnicalLabel(cause.key, "Causa não informada")}</strong>
      <span>${secondsLabel(cause.total_duration_seconds)} · ${cause.total_events} evento(s)</span>
      ${traceButton("Ver eventos", cause.event_uuids)}
    </div>
  `).join("");
}

function renderIntelligenceSummary(payload, allInsights) {
  const affectedAssets = new Set();
  allInsights.forEach((item) => {
    const asset = item?.metrics?.asset_id || item?.metrics?.asset_name || item?.metrics?.asset_label;
    if (asset) affectedAssets.add(String(asset));
  });
  const comparison = payload.comparison?.metrics?.total_duration_seconds;
  return `
    <section class="cx-intel-summary">
      <article>
        <span>Insights relevantes</span>
        <strong>${allInsights.length || "Sem dados"}</strong>
      </article>
      <article>
        <span>Ativos afetados</span>
        <strong>${affectedAssets.size || "Indisponível"}</strong>
      </article>
      <article>
        <span>Eventos analisados</span>
        <strong>${payload.data_quality?.classified_events ?? "Indisponível"}</strong>
      </article>
      <article>
        <span>Comparação</span>
        <strong>${comparison ? comparisonText(comparison) : "Sem base anterior"}</strong>
      </article>
    </section>
  `;
}

function renderIntelligenceNotices(payload, unknownCount) {
  const coverage = payload.coverage || {};
  if ((!coverage || coverage.status === "observed") && !unknownCount) return "";
  const label = coverage.status === "partial" ? "Cobertura parcial dos dados" : "Cobertura dos dados em avaliação";
  const detail = coverage.reason || "Algumas leituras podem mudar conforme novos dados forem classificados.";
  const unknownDetail = unknownCount ? ` ${unknownCount} evento(s) ainda aguardam classificação operacional.` : "";
  return `
    <section class="cx-intel-notices" aria-label="Avisos de qualidade">
      <article>
        <i aria-hidden="true"></i>
        <div>
          <strong>${sanitize(label)}</strong>
          <span>${sanitize(detail + unknownDetail)}</span>
        </div>
        <label for="intelTabQuality">Ver qualidade dos dados</label>
      </article>
    </section>
  `;
}

function renderIntelligenceKpiDetails(kpis = []) {
  if (!kpis.length) {
    return `<div class="cx-empty-state"><strong>Sem indicadores analíticos suficientes.</strong><p>A Campex aguarda eventos classificados para calcular estes detalhes.</p></div>`;
  }
  return `
    <div class="cx-intel-kpi-details">
      ${kpis.map((kpi) => `
        <div>
          <span>${humanKpiLabel(kpi.label)}</span>
          <strong>${intelligenceKpiValue(kpi)}</strong>
          ${traceButton("Ver eventos relacionados", kpi.event_uuids)}
        </div>
      `).join("")}
    </div>
  `;
}

function intelligenceAssetLabel(item) {
  const metrics = item?.metrics || {};
  return humanTechnicalLabel(
    metrics.asset_name || metrics.asset_label || metrics.asset || metrics.asset_id,
    "Ativo sem nome disponível"
  );
}

function renderImpactedAssets(payload, allInsights) {
  const rows = allInsights
    .filter((item) => item?.metrics?.asset_id || item?.metrics?.asset_name || item?.metrics?.asset_label || item?.metrics?.asset)
    .slice(0, 4);
  if (!rows.length) return `<div class="cx-empty-state"><strong>Nenhum ativo se destacou no período.</strong><p>A Campex precisa de eventos classificados para montar concentração por ativo.</p></div>`;
  return `<div class="cx-intel-impact-list">${rows.map((item) => `
    <div>
      <strong>${intelligenceAssetLabel(item)}</strong>
      <span>${humanInsightText(item.number || item.statement)}</span>
      ${insightTraceAction(item, "Ver")}
    </div>
  `).join("")}</div>`;
}

function renderIntelligenceComparison(payload) {
  const metrics = payload.comparison?.metrics || {};
  const rows = [
    ["Eventos", metrics.total_events],
    ["Duração", metrics.total_duration_seconds],
    ["Duração média", metrics.average_duration_seconds],
  ];
  return rows.map(([label, metric]) => {
    const current = label === "Eventos" ? metric?.current : secondsLabel(metric?.current);
    const previous = label === "Eventos" ? metric?.previous : secondsLabel(metric?.previous);
    return `
      <div class="cx-intel-comparison-row">
        <span>${label}</span>
        <strong>${metric ? current : "Indisponível"}</strong>
        <small>${metric ? `anterior: ${previous} · ${comparisonText(metric)}` : "Sem base comparável"}</small>
      </div>
    `;
  }).join("");
}

function renderIntelligencePrimaryInsight(payload, allInsights) {
  const primary = (payload.attention || [])[0] || (payload.patterns || [])[0] || allInsights[0];
  if (!primary) {
    return `
      <section class="cx-intel-primary">
        <span>Leitura principal</span>
        <strong>Ainda não há leitura principal sustentada pelos dados.</strong>
        <p>A Campex aguarda eventos classificados e cobertura suficiente para destacar uma mudança operacional.</p>
      </section>
    `;
  }
  const eventCount = (primary.event_uuids || []).filter(Boolean).length;
  const context = intelligenceAssetLabel(primary);
  return `
    <section class="cx-intel-primary">
      <span>Leitura principal</span>
      <strong>${humanInsightText(primary.statement)}</strong>
      <p>${humanInsightText(primary.why || "Leitura gerada por regra determinística a partir dos dados observados.")}</p>
      <div class="cx-intel-primary-meta">
        <span>${humanInsightText(primary.number || "Impacto verificável")}</span>
        <span>${eventCount ? `${eventCount} evento(s) relacionado(s)` : "Sem eventos relacionados informados"}</span>
        <span>${context}</span>
      </div>
      ${insightTraceAction(primary, "Ver eventos relacionados")}
    </section>
  `;
}

function renderIntelligenceQuality(payload, unknownCount) {
  const coverage = homeCoverageState(payload.coverage);
  return `
    <section class="cx-intel-module">
      <h3>Qualidade dos dados</h3>
      <div class="cx-intel-quality-panel">
        <strong>${coverage.label}</strong>
        <p>${sanitize(payload.coverage?.reason || "Qualidade calculada a partir das amostras e eventos disponíveis no período.")}</p>
        <div>
          <span>Eventos classificados</span>
          <b>${payload.data_quality?.classified_events ?? "Sem dados suficientes"}</b>
        </div>
        <div>
          <span>Eventos aguardando classificação</span>
          <b>${unknownCount || "Nenhum informado"}</b>
        </div>
        <div>
          <span>Período</span>
          <b>${formatOperationsPeriod(payload.period)}</b>
        </div>
      </div>
    </section>
  `;
}

async function renderReportsPage(config) {
  const tenantsPayload = await requestJson("/reports/tenants");
  const tenants = tenantsPayload.tenants || [];

  title.textContent = "Relatórios";
  heading.textContent = "Relatórios";
  subtitle.textContent = "Configure uma vez. A Campex envia automaticamente a leitura da operação todos os dias.";
  tableTitle.textContent = "Relatório diário";
  tableHint.textContent = "Cada empresa recebe somente os dados da própria operação.";
  filters.innerHTML = "";
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  body.closest("table")?.setAttribute("aria-hidden", "true");
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");

  if (!tenants.length) {
    primaryAction.textContent = "Atualizar";
    primaryAction.onclick = () => loadPage(window.location.pathname);

    cards.innerHTML = `
      <section class="cx-empty-state">
        <strong>Nenhuma empresa cadastrada.</strong>
        <p>Cadastre uma empresa antes de configurar o relatório diário.</p>
      </section>
    `;
    return;
  }

  const url = new URL(window.location.href);
  const requestedTenant = url.searchParams.get("tenant_id");

  let selectedTenant = tenants.find(
    (tenant) => String(tenant.id) === String(requestedTenant)
  );

  if (!selectedTenant) {
    const rememberedTenant = localStorage.getItem("campex_reports_tenant");

    selectedTenant = tenants.find(
      (tenant) => String(tenant.id) === String(rememberedTenant)
    );
  }

  if (!selectedTenant) {
    selectedTenant = tenants[0];
  }

  const tenantId = String(selectedTenant.id);

  localStorage.setItem("campex_reports_tenant", tenantId);

  const encodedTenant = encodeURIComponent(tenantId);

  const [schedulePayload, previewPayload] = await Promise.all([
    requestJson(`/reports/schedule?tenant_id=${encodedTenant}`),
    requestJson(`/reports/preview?tenant_id=${encodedTenant}`),
  ]);

  const schedule = schedulePayload.schedule || {};
  const preview = previewPayload.report || {};
  const summary = preview.summary || {};
  const machines = summary.machines || {};
  const events = preview.main_events || [];

  const enabled = schedule.enabled === undefined
    ? true
    : Boolean(schedule.enabled);

  const sendTime = schedule.send_time || "08:00";
  const destination = schedule.email || "";
  const recipientName = schedule.recipient_name || "";

  function nextSendLabel(timeValue) {
    const [hour, minute] = String(timeValue || "08:00")
      .split(":")
      .map(Number);

    const now = new Date();
    const next = new Date();

    next.setHours(hour || 0, minute || 0, 0, 0);

    if (next <= now) {
      next.setDate(next.getDate() + 1);
    }

    const day = next.toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "short",
    });

    const time = next.toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
    });

    return `${day} às ${time}`;
  }

  const tenantSelector = tenants.length > 1
    ? `
      <label>
        Empresa
        <select data-report-tenant>
          ${tenants.map((tenant) => `
            <option
              value="${sanitize(tenant.id)}"
              ${String(tenant.id) === tenantId ? "selected" : ""}
            >
              ${sanitize(tenant.nome)}
            </option>
          `).join("")}
        </select>
        <small>
          A visualização e o envio abaixo pertencem somente a esta empresa.
        </small>
      </label>
    `
    : `
      <div class="cx-report-company-fixed">
        <span>Empresa</span>
        <strong>${sanitize(selectedTenant.nome)}</strong>
      </div>
    `;

  const importantEvents = events.slice(0, 5);
  const nextSend = enabled ? nextSendLabel(sendTime) : "Desativado";
  const lastDeliveryStatus = schedule.last_status === "sent"
    ? "Enviado"
    : schedule.last_status === "failed"
      ? "Falha"
      : "Aguardando";

  primaryAction.textContent = "Enviar agora";

  cards.innerHTML = `
    <section class="cx-reports-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar relatórios, empresas, entregas...</div>
        <div class="cx-home-topbar-actions">
          <span>Relatórios</span>
          <span class="${enabled ? "is-online" : ""}">${enabled ? "Entrega ativa" : "Entrega desativada"}</span>
        </div>
      </div>

      <header class="cx-report-hero">
        <div>
          <span class="cx-report-eyebrow">Relatórios</span>
          <h2>Leituras da sua operação, entregues automaticamente.</h2>
          <p>Configure quando receber e acompanhe os relatórios gerados pela Campex.</p>
        </div>

        <aside class="cx-report-next">
          <div>
            <span>Próximo envio</span>
            <strong>${nextSend}</strong>
          </div>
          <div>
            <span>Entrega</span>
            <strong class="cx-report-status ${enabled ? "active" : "pending"}">${enabled ? "Ativa" : "Entrega desativada"}</strong>
          </div>
          <div>
            <span>Empresa</span>
            <strong>${sanitize(selectedTenant.nome)}</strong>
          </div>
        </aside>
      </header>

      <section class="cx-report-tabs-shell">
        <div class="cir-tabs" role="tablist" aria-label="Seções de relatórios">
          <input class="cir-tabs__r" type="radio" name="reportTabs" id="reportTabReport" checked />
          <label class="cir-tabs__t" for="reportTabReport">Relatório</label>
          <input class="cir-tabs__r" type="radio" name="reportTabs" id="reportTabHistory" />
          <label class="cir-tabs__t" for="reportTabHistory">Histórico de envios</label>
        </div>

        <div class="cx-report-tab-content cx-report-tab-report">
          <section class="cx-report-layout">

            <section class="cx-report-settings marque-checkset">
              <div class="cx-report-section-heading">
                <div>
                  <span class="cx-report-eyebrow">Configuração de entrega</span>
                  <h3 class="marque-checkset__legend">Entrega automática</h3>
                  <p class="marque-checkset__hint">A Campex envia o relatório no horário configurado.</p>
                </div>

                <label class="cx-report-switch marque-check">
                  <input
                    type="checkbox"
                    name="enabled"
                    form="reportScheduleForm"
                    ${enabled ? "checked" : ""}
                  />
                  <span class="marque-check__box" aria-hidden="true">
                    <svg viewBox="0 0 14 14" fill="none">
                      <path d="M3 7.1 5.7 10 11 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
                    </svg>
                  </span>
                  <span class="marque-check__copy">
                    <span class="marque-check__title">Entrega automática</span>
                    <span class="marque-check__meta">${enabled ? "Ativa" : "Desativada"} · ${nextSend}</span>
                  </span>
                </label>
              </div>

              <form id="reportScheduleForm" data-report-schedule-form>

                ${tenantSelector}

                <label>
                  Horário de envio
                  <input
                    type="time"
                    name="send_time"
                    value="${sanitize(sendTime)}"
                    required
                  />
                  <small>
                    Pode ser qualquer horário, como 08:00, 11:55 ou 18:37.
                  </small>
                </label>

                <label>
                  Canal
                  <select name="channel">
                    <option value="email" selected>Email</option>
                    <option value="whatsapp" disabled>
                      WhatsApp — requer integração
                    </option>
                  </select>
                </label>

                <label>
                  Nome do destinatário
                  <input
                    type="text"
                    name="recipient_name"
                    value="${sanitize(recipientName)}"
                    placeholder="Ex.: João"
                    required
                  />
                </label>

                <label>
                  Destinatário
                  <input
                    type="email"
                    name="email"
                    value="${sanitize(destination)}"
                    placeholder="diretoria@empresa.com"
                    required
                  />
                </label>

                <input
                  type="hidden"
                  name="timezone"
                  value="${sanitize(schedule.timezone || "America/Sao_Paulo")}"
                />

                <div class="cx-report-form-actions">
                  <button type="submit">
                    Salvar configuração
                  </button>

                  <button
                    type="button"
                    class="secondary"
                    data-report-send-now
                  >
                    Enviar agora
                  </button>
                </div>

                <p
                  class="cx-report-form-status"
                  data-report-status
                ></p>
              </form>

              <div class="cx-report-delivery-status">
                <div>
                  <span>Último envio</span>
                  <strong>
                    ${schedule.last_sent_at
                      ? eventDateLabel(schedule.last_sent_at)
                      : "Ainda não enviado"}
                  </strong>
                </div>

                <div>
                  <span>Status</span>
                  <strong class="cx-report-status ${schedule.last_status || "pending"}">${lastDeliveryStatus}</strong>
                </div>
              </div>
            </section>

            <section class="cx-report-preview">
              <div class="cx-report-section-heading">
                <div>
                  <span class="cx-report-eyebrow">Prévia do relatório</span>
                  <h3>Relatório Operacional Campex</h3>
                </div>

                <span class="cx-report-preview-badge">
                  Modelo diário
                </span>
              </div>

              <p class="cx-report-preview-period">
                Últimas 24 horas · ${sanitize(selectedTenant.nome)}
              </p>

              <div class="cx-report-preview-meta">
                <span>Período: últimas 24 horas</span>
                <span>Modelo: diário</span>
                <span>Atualizado ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
              </div>

              <div class="cx-report-metrics">
                <article>
                  <span>Acontecimentos</span>
                  <strong>${events.length}</strong>
                </article>

                <article>
                  <span>Tempo ativo</span>
                  <strong>${secondsLabel(machines.active_seconds || 0)}</strong>
                </article>

                <article>
                  <span>Tempo parado</span>
                  <strong>${secondsLabel(machines.stopped_seconds || 0)}</strong>
                </article>

                <article>
                  <span>Sem leitura</span>
                  <strong>${secondsLabel(machines.unknown_seconds || 0)}</strong>
                </article>
              </div>

              <section class="cx-report-events-preview">
                <div class="cx-report-preview-title">
                  <h4>Principais acontecimentos</h4>
                  <a href="/events">Ver todos</a>
                </div>

                ${importantEvents.length
                  ? importantEvents.map((event) => `
                      <article>
                        <div class="cx-report-event-time">
                          ${eventDateLabel(event.started_at)}
                        </div>

                        <div>
                          <strong>${eventTitle(event)}</strong>
                          <span>
                            ${event.duration_seconds
                              ? secondsLabel(event.duration_seconds)
                              : "Ocorrência registrada"}
                          </span>
                        </div>

                        <span class="cx-report-event-family">
                          ${familyLabel(event.event_family)}
                        </span>
                      </article>
                    `).join("")
                  : `
                    <div class="cx-empty-state">
                      <strong>Nenhum acontecimento relevante.</strong>
                      <p>
                        Os acontecimentos reais desta empresa aparecerão aqui.
                      </p>
                    </div>
                  `
                }
              </section>

              <div class="cx-report-fixed-model-note">
                <strong>Dados isolados por empresa.</strong>
                <span>
                  Este relatório é gerado usando exclusivamente os dados
                  operacionais da empresa selecionada.
                </span>
              </div>
            </section>
          </section>
        </div>

        <div class="cx-report-tab-content cx-report-tab-history">
          <section class="cx-report-history">
            <div class="cx-report-section-heading">
              <div>
                <span class="cx-report-eyebrow">Histórico de envios</span>
                <h3>Últimas entregas</h3>
              </div>
            </div>
            ${schedule.last_sent_at ? `
              <div class="cx-report-history-list">
                <div>
                  <span>${eventDateLabel(schedule.last_sent_at)}</span>
                  <strong>${sanitize(selectedTenant.nome)}</strong>
                  <span>Email</span>
                  <strong class="cx-report-status ${schedule.last_status || "pending"}">${lastDeliveryStatus}</strong>
                  <span>${sanitize(destination || "Destinatário não configurado")}</span>
                </div>
              </div>
            ` : `
              <div class="cx-empty-state">
                <strong>Nenhuma entrega registrada ainda.</strong>
                <p>Quando houver envio real de relatório, o histórico desta empresa aparecerá aqui.</p>
              </div>
            `}
          </section>
        </div>
      </section>
    </section>
  `;

  document
    .querySelector("[data-report-tenant]")
    ?.addEventListener("change", (event) => {
      const nextTenant = String(event.target.value);

      localStorage.setItem(
        "campex_reports_tenant",
        nextTenant
      );

      const nextUrl = new URL(window.location.href);
      nextUrl.searchParams.set("tenant_id", nextTenant);

      window.history.replaceState(
        {},
        "",
        `${nextUrl.pathname}${nextUrl.search}`
      );

      loadPage(nextUrl.pathname);
    });

  async function sendReportNow() {
    const statusEl = document.querySelector("[data-report-status]");

    if (statusEl) {
      statusEl.textContent = "Enviando relatório...";
    }

    try {
      await requestJson(
        `/reports/send-now?tenant_id=${encodedTenant}`,
        {
          method: "POST",
        }
      );

      if (statusEl) {
        statusEl.textContent = "Relatório enviado com sucesso.";
      }
    } catch (error) {
      if (statusEl) {
        statusEl.textContent =
          error?.message || "Não foi possível enviar o relatório.";
      }
    }
  }

  primaryAction.onclick = sendReportNow;

  document
    .querySelector("[data-report-send-now]")
    ?.addEventListener("click", sendReportNow);

  document
    .querySelector("[data-report-schedule-form]")
    ?.addEventListener("submit", async (event) => {
      event.preventDefault();

      const form = event.currentTarget;
      const data = new FormData(form);
      const statusEl = document.querySelector("[data-report-status]");

      const payload = {
        tenant_id: tenantId,
        enabled: Boolean(
          form.querySelector('[name="enabled"]')?.checked
        ),
        send_time: String(
          data.get("send_time") || "08:00"
        ),
        timezone: String(
          data.get("timezone") || "America/Sao_Paulo"
        ),
        channel: String(
          data.get("channel") || "email"
        ),
        email: String(
          data.get("email") || ""
        ).trim(),
        recipient_name: String(
          data.get("recipient_name") || ""
        ).trim(),
      };

      if (statusEl) {
        statusEl.textContent = "Salvando...";
      }

      try {
        await requestJson("/reports/schedule", {
          method: "PUT",
          body: JSON.stringify(payload),
        });

        if (statusEl) {
          statusEl.textContent = "Configuração salva.";
        }

        setTimeout(() => {
          loadPage(window.location.pathname);
        }, 400);
      } catch (error) {
        if (statusEl) {
          statusEl.textContent =
            error?.message || "Não foi possível salvar.";
        }
      }
    });
}


async function renderIntelligencePage(config) {
  const params = readModelQuery();
  const payload = await requestJson(`/operations/read-model/insights?${params}`);
  const allInsights = [...(payload.attention || []), ...(payload.patterns || [])];
  rowsCache = allInsights;
  title.textContent = "Intelligence";
  heading.textContent = "Intelligence";
  subtitle.textContent = "Padrões, comparações e resumos verificáveis da operação.";
  tableTitle.textContent = "Rastreabilidade dos insights";
  tableHint.textContent = "Cada insight pode ser rastreado até os eventos que o originaram.";
  primaryAction.textContent = "Atualizar";
  primaryAction.onclick = () => loadPage(window.location.pathname);
  filters.innerHTML = `
    <label>Período
      <select id="operationsPeriod">
        <option value="day" ${operationPeriod() === "day" ? "selected" : ""}>Hoje</option>
        <option value="turno" ${operationPeriod() === "turno" ? "selected" : ""}>Turno</option>
        <option value="week" ${operationPeriod() === "week" ? "selected" : ""}>Semana</option>
        <option value="month" ${operationPeriod() === "month" ? "selected" : ""}>Mês</option>
      </select>
    </label>
  `;
  const unknownCount = Number(payload.data_quality?.unknown_events || 0);
  const classifiedEvents = payload.data_quality?.classified_events ?? "Indisponível";
  cards.innerHTML = `
    <section class="cx-intel-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar padrões, ativos, causas...</div>
        <div class="cx-home-topbar-actions">
          <span>${classifiedEvents} evento(s) classificados</span>
          <span>Atualizado ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
        </div>
      </div>

      <header class="cx-intel-hero">
        <div>
          <span>INTELLIGENCE</span>
          <h2>Entenda o que está mudando na sua operação.</h2>
          <p>Padrões, comparações e leituras verificáveis a partir dos dados observados.</p>
        </div>
        <aside class="cx-intel-context">
          <div>
            <small>Período</small>
            <strong>${formatOperationsPeriod(payload.period)}</strong>
          </div>
          <div>
            <small>Cobertura</small>
            <strong>${homeCoverageState(payload.coverage).label}</strong>
          </div>
        </aside>
      </header>

      ${renderIntelligenceNotices(payload, unknownCount)}

      <section class="cx-intel-tabs-shell">
        <div class="cir-tabs" role="tablist" aria-label="Seções da Intelligence">
          <input class="cir-tabs__r" type="radio" name="intelTabs" id="intelTabOverview" checked />
          <label class="cir-tabs__t" for="intelTabOverview">Visão geral</label>
          <input class="cir-tabs__r" type="radio" name="intelTabs" id="intelTabInsights" />
          <label class="cir-tabs__t" for="intelTabInsights">Insights</label>
          <input class="cir-tabs__r" type="radio" name="intelTabs" id="intelTabCompare" />
          <label class="cir-tabs__t" for="intelTabCompare">Comparações</label>
          <input class="cir-tabs__r" type="radio" name="intelTabs" id="intelTabQuality" />
          <label class="cir-tabs__t" for="intelTabQuality">Qualidade dos dados</label>
        </div>

        <div class="cx-intel-tab-content cx-intel-tab-overview">
          ${renderIntelligencePrimaryInsight(payload, allInsights)}
          ${renderIntelligenceSummary(payload, allInsights)}
          <section class="cx-intel-layout">
            <div class="cx-intel-column">
              <section class="cx-intel-module">
                <h3>O que merece atenção</h3>
                ${renderInsightList(payload.attention, "Sem destaques sustentados pelos dados do período.")}
              </section>
            </div>
            <aside class="cx-intel-column">
              <section class="cx-intel-module">
                <h3>Ativos mais impactados</h3>
                ${renderImpactedAssets(payload, allInsights)}
              </section>
            </aside>
          </section>
        </div>

        <div class="cx-intel-tab-content cx-intel-tab-insights">
          <section class="cx-intel-module">
            <h3>O que merece atenção</h3>
            ${renderInsightList(payload.attention, "Sem destaques sustentados pelos dados do período.")}
          </section>
          <section class="cx-intel-module">
            <h3>Padrões verificáveis</h3>
            ${renderInsightList(payload.patterns, "Ainda não há padrões matematicamente verificáveis.")}
          </section>
          <section class="cx-intel-module">
            <h3>Rastreabilidade dos insights</h3>
            <p class="muted">Cada número exibido aqui aponta para eventos reais. A Campex mostra a evidência do cálculo, não uma conclusão solta.</p>
            ${allInsights.length ? `<div class="cx-intel-investigation">${allInsights.slice(0, 8).map((item) => `
              <div>
                <span>${humanInsightText(item.statement)}</span>
                ${insightTraceAction(item, "Ver eventos relacionados")}
              </div>
            `).join("")}</div>` : `<div class="cx-empty-state"><strong>Sem rastreabilidade disponível.</strong><p>Aguardando eventos classificados neste período.</p></div>`}
          </section>
        </div>

        <div class="cx-intel-tab-content cx-intel-tab-compare">
          <section class="cx-intel-layout">
            <div class="cx-intel-column">
              <section class="cx-intel-module">
                <h3>Comparação com período anterior</h3>
                ${renderIntelligenceComparison(payload)}
              </section>
              <section class="cx-intel-module">
                <h3>Indicadores analíticos</h3>
                ${renderIntelligenceKpiDetails(payload.kpis || [])}
              </section>
            </div>
            <aside class="cx-intel-column">
              <section class="cx-intel-module">
                <h3>Causas confirmadas</h3>
                <p class="muted">Somente informações registradas por pessoas entram aqui. Observações da câmera não viram causa automaticamente.</p>
                ${renderCauseRows(payload.confirmed_causes)}
              </section>
            </aside>
          </section>
        </div>

        <div class="cx-intel-tab-content cx-intel-tab-quality">
          ${renderIntelligenceQuality(payload, unknownCount)}
        </div>
      </section>
    </section>
  `;
  renderTabs(config);
  head.innerHTML = `<tr>${config.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
  body.innerHTML = rowsCache.length ? rowsCache.map((item) => `
    <tr>
      <td>${humanInsightText(item.statement)}</td>
      <td>${humanInsightText(item.number || "—")}</td>
      <td>${humanInsightText(item.why || "—")}</td>
      <td>${traceButton("Ver eventos", item.event_uuids)}</td>
      <td><a class="cx-link" href="/events">Investigar</a></td>
    </tr>
  `).join("") : `<tr><td colspan="${config.columns.length}">${emptyState(config)}</td></tr>`;
  grid.style.display = "none";
}

async function loadAlertsWorkspace() {
  const [deliveries, recipients, rules] = await Promise.all([
    requestJson("/alert-deliveries").catch(() => []),
    requestJson("/alert-recipients").catch(() => []),
    requestJson("/visual-rules").catch(() => []),
  ]);
  const deliveryRows = (Array.isArray(deliveries) ? deliveries : deliveries.deliveries || []).map((item) => ({ ...item, workspace_kind: "entrega" }));
  const recipientRows = (Array.isArray(recipients) ? recipients : recipients.recipients || []).map((item) => ({ ...item, workspace_kind: "destinatario" }));
  const ruleRows = (Array.isArray(rules) ? rules : rules.rules || []).map((item) => ({ ...item, workspace_kind: "regra" }));
  return [...ruleRows, ...recipientRows, ...deliveryRows];
}

async function loadHelpWorkspace() {
  const [health, systemHealth, cameras, deliveries] = await Promise.all([
    requestJson("/health").catch(() => ({ status: "erro" })),
    requestJson("/system/health").catch(() => ({})),
    requestJson("/cameras/estado").catch(() => []),
    requestJson("/alert-deliveries").catch(() => []),
  ]);
  const onlineCameras = cameras.filter((camera) => camera.status === "online").length;
  const failedDeliveries = deliveries.filter((delivery) => delivery.status === "failed").length;
  return [
    { name: "Primeiros passos", note: "Conecte uma câmera, configure uma zona, crie uma regra e valide os primeiros eventos.", status: "Disponível", href: "/settings/cameras" },
    { name: "Conectar câmera", note: "Cadastre o RTSP no backend. A senha fica protegida e não aparece no navegador.", status: "Disponível", href: "/settings/cameras" },
    { name: "Configurar zona", note: "Abra Live View, desenhe a área, revise os pontos e salve a configuração.", status: "Disponível", href: "/live-view" },
    { name: "Criar regra", note: "Use Regras para definir condição, duração mínima, severidade, cooldown e alertas.", status: "Disponível", href: "/rules" },
    { name: "Configurar alerta", note: "Cadastre destinatários e acompanhe entregas, falhas e testes.", status: failedDeliveries ? "Atenção" : "Disponível", href: "/alerts" },
    { name: "Revisar evento", note: "Abra Eventos, confira snapshot, timeline, metadados e reconheça quando analisado.", status: "Disponível", href: "/events" },
    { name: "Entender evidências", note: "Snapshots aparecem apenas quando eventos configurados registram ocorrência visual.", status: "Disponível", href: "/evidence" },
    { name: "Solução de problemas", note: "Verifique câmera online, último frame, API local, banco e entregas de alerta.", status: "Disponível", href: "/help" },
    { name: "Backend", note: `API local: ${health.status || "indisponível"}`, status: health.status === "ok" ? "Online" : "Atenção" },
    { name: "Banco", note: systemHealth.database || systemHealth.banco || "SQLite local configurado", status: "Local" },
    { name: "Câmera", note: `${onlineCameras} câmera(s) online de ${cameras.length}`, status: onlineCameras ? "Online" : "Sem histórico recente", href: "/cameras" },
    { name: "Último frame", note: latestFrameText(cameras), status: cameras.length ? "Disponível" : "Sem dados" },
    { name: "Processamento", note: "Status de IA e regras aparece por câmera na Live View e no status operacional.", status: "Local" },
    { name: "Alertas", note: `${failedDeliveries} falha(s) de entrega registradas`, status: failedDeliveries ? "Atenção" : "Sem falhas", href: "/alerts" },
    { name: "Armazenamento", note: "Snapshots e banco ficam no diretório local de dados da instalação.", status: "Local" },
    { name: "Contato com a Campex", note: "Use o acompanhamento assistido do piloto para suporte técnico e validação operacional.", status: "Assistido" },
  ];
}

function latestFrameText(cameras) {
  const values = cameras.map((camera) => camera.ultimo_frame).filter(Boolean).sort().reverse();
  return values[0] || "Nenhum frame recente informado";
}

function alertRow(item) {
  if (item.workspace_kind === "regra") {
    return [
      item.tipo_evento || item.nome || "Regra",
      item.destinatarios || "Destinatários configurados por cliente",
      item.canais || "e-mail",
      item.last_triggered_at || "—",
      item.alerta_inicio ? "Ao iniciar" : item.alerta_normalizacao ? "Ao normalizar" : "Sem envio",
      item.cooldown_seconds || 0,
      "—",
      badge(item.ativo ? "Ativa" : "Inativa"),
      rowMenu(),
    ];
  }
  if (item.workspace_kind === "destinatario") {
    return [
      item.event_types?.join?.(", ") || "Tipos configurados",
      `${item.nome || "—"} · ${item.email || "—"}`,
      "e-mail",
      "—",
      item.ativo ? "Disponível" : "Pausado",
      "—",
      "—",
      badge(item.ativo ? "Ativo" : "Inativo"),
      `<button type="button" data-test-recipient="${item.id}">Enviar teste</button>`,
    ];
  }
  return [
    item.evento_id || "Teste",
    item.destinatario || item.recipient_id || "—",
    item.channel || item.canal || "e-mail",
    item.sent_at || item.last_attempt_at || item.criado_em || "—",
    item.status === "sent" ? "Entregue" : item.status === "failed" ? "Falha" : "Em processamento",
    item.attempts || item.tentativas || 1,
    item.erro || item.error || "—",
    badge(alertStatusLabel(item.status)),
    item.status === "failed" ? '<button type="button" class="cx-row-menu" data-open-detail>•••</button>' : rowMenu(),
  ];
}

function eventStatusLabel(status) {
  if (status === "open") return "Aberto";
  if (status === "closed") return "Encerrado";
  return status || "Aberto";
}

function workflowLabel(status) {
  if (status === "acknowledged") return "Reconhecido";
  if (status === "resolved") return "Resolvido";
  return "Novo";
}

function eventSeverity(event) {
  const severity = String(event.severidade || event.severity || "").toLowerCase();
  if (severity) return severity;
  const text = `${event.tipo || ""} ${event.event_type || ""} ${event.new_state || ""}`.toLowerCase();
  if (text.includes("offline") || text.includes("parada") || text.includes("stoppage")) return "alta";
  if (text.includes("restricted") || text.includes("sem_operador")) return "média";
  return "normal";
}

function eventSeverityLabel(value) {
  const severity = String(value || "").toLowerCase();
  if (["critical", "critica", "crítica"].includes(severity)) return "Crítica";
  if (["high", "alta"].includes(severity)) return "Alta";
  if (["medium", "media", "média"].includes(severity)) return "Média";
  if (["low", "baixa"].includes(severity)) return "Baixa";
  return "Normal";
}

function eventSeverityTone(value) {
  const severity = String(value || "").toLowerCase();
  if (["critical", "critica", "crítica"].includes(severity)) return "critical";
  if (["high", "alta"].includes(severity)) return "high";
  if (["medium", "media", "média"].includes(severity)) return "medium";
  if (["low", "baixa"].includes(severity)) return "low";
  return "neutral";
}

function eventSeverityPill(event) {
  const severity = eventSeverity(event);
  return `<span class="cx-event-severity ${eventSeverityTone(severity)}"><i></i>${eventSeverityLabel(severity)}</span>`;
}

function eventFamily(event) {
  const explicit = event.event_family || event.business_taxonomy?.event_family;
  if (explicit) return explicit;
  const type = String(event.event_subtype || event.tipo || event.technical_type || event.event_type || "").toLowerCase();
  if (["machine_stoppage", "exceptionally_long_stoppage"].includes(type)) return "interruption";
  if (["workstation_unattended", "operator_absence"].includes(type)) return "absence";
  if (["restricted_area_occupied", "restricted_zone_occupied", "zone_occupancy"].includes(type)) return "flow";
  if (["camera_offline"].includes(type)) return "infrastructure";
  return "unknown";
}

function eventSubtype(event) {
  return event.event_subtype || event.business_taxonomy?.event_subtype || event.tipo || event.technical_type || "evento";
}

function eventTechnicalType(event) {
  return event.technical_type || event.tipo || event.event_type || eventSubtype(event);
}

function eventFamilyTitle(event) {
  const subtype = eventSubtype(event);
  if (subtype === "machine_stoppage") return "Parada operacional";
  if (subtype === "exceptionally_long_stoppage") return "Parada acima do padrão";
  if (subtype === "machine_running_without_operator") return "Máquina ativa sem operador";
  if (subtype === "machine_stopped_with_operator") return "Máquina parada com operador";
  if (subtype === "workstation_unattended") return "Posto sem operador";
  if (subtype === "camera_offline") return "Câmera offline";
  if (eventFamily(event) === "interruption") return "Interrupção operacional";
  if (eventFamily(event) === "wait") return "Espera operacional";
  if (eventFamily(event) === "absence") return "Ausência operacional";
  if (eventFamily(event) === "flow") return "Fluxo operacional";
  return "Evento não classificado";
}

function eventWorkflow(event) {
  return event.workflow_status || "new";
}

function eventPhysicalStatus(event) {
  return event.physical_status || event.status || "open";
}

function eventPhysicalStatusLabel(event) {
  return eventPhysicalStatus(event) === "closed" ? "Encerrado" : "Em andamento";
}

function eventStart(event) {
  return event.inicio || event.started_at || event.criado_em || "—";
}

function eventEnd(event) {
  return event.fim || event.ended_at || "";
}

function eventDuration(event) {
  const value = event.duracao ?? event.duration_seconds ?? event.read_duration_seconds;
  return value === null || value === undefined || value === "" ? "—" : secondsLabel(value);
}

function eventDisplayDuration(event) {
  if (eventPhysicalStatus(event) === "open") {
    const started = Date.parse(eventStart(event));
    if (!Number.isNaN(started)) return secondsLabel(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    return "Em andamento";
  }
  return eventDuration(event);
}

function eventDateLabel(value) {
  if (!value || value === "—") return "Indisponível";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Indisponível";
  const now = new Date();
  const sameDay = date.toLocaleDateString("pt-BR") === now.toLocaleDateString("pt-BR");
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const prefix = sameDay ? "Hoje" : date.toLocaleDateString("pt-BR") === yesterday.toLocaleDateString("pt-BR") ? "Ontem" : date.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
  return `${prefix} · ${date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

function eventTitle(event) {
  if (event.tipo === "visual_occurrence") {
    return "Mudança visual detectada";
  }
  return eventFamilyTitle(event);
}

function eventCategory(event) {
  const text = `${event.tipo || event.event_type || ""}`.toLowerCase();
  if (text === "visual_occurrence") return "Inteligência visual";
  if (text.includes("machine") || text.includes("stoppage")) return "Máquina";
  if (text.includes("person") || text.includes("restricted")) return "Pessoas";
  return "Operação";
}

function unitForEvent(event) {
  return event.unidade_id || event.unit_id || "—";
}

function evidenceLink(event) {
  return event.midia_path || event.snapshot_path ? `<a class="cx-link" href="/eventos/${event.id}/evidence" target="_blank">Evidência</a>` : "Sem evidência";
}

function rowMenu() {
  return '<button class="cx-row-menu" type="button" data-open-detail>•••</button>';
}

function eventContext(event) {
  const physical = event.physical_context || {};
  const asset = event.asset_name || event.asset_id || physical.asset_id || event.machine_name || event.machine_monitor_id || physical.machine_monitor_id;
  const process = event.process_name || event.process_id || physical.process_id;
  const area = event.area_name || event.area_context_id || physical.area_context_id || event.area_id || physical.area_id;
  const camera = event.camera_name || event.camera_id || physical.camera_id;
  const unit = event.unidade_id || event.unit_id || physical.unidade_id || physical.site_id;
  const primary = asset || process || area || camera || "Contexto não informado";
  const location = [area, process].filter(Boolean).join(" → ") || unit || camera || "Local não informado";
  return { primary, location, asset, process, area, camera, unit };
}

function eventDisplayContext(event) {
  const context = eventContext(event);
  const primary = homeContextName(context.primary, "");
  const area = operationsAreaLabel(context.area || context.location);
  const process = homeContextName(context.process, "");
  const camera = homeContextName(context.camera, "");
  const title = primary || area || process || camera || "Evento operacional";
  const location = [area, process].filter((item) => item && item !== title && item !== "Área não identificada").join(" · ");
  return {
    title,
    location: location || (area !== title ? area : ""),
  };
}

function eventTimeRange(event) {
  const start = eventStart(event);
  const end = eventEnd(event);
  if (event.tipo === "visual_occurrence") return eventDateLabel(start);
  if (!end || end === "—") return `${eventDateLabel(start)} → em andamento`;
  return `${eventDateLabel(start)} → ${eventDateLabel(end)}`;
}

function eventObservedSummary(event) {
  const visual = event.visual_understanding || {};
  if (event.tipo === "visual_occurrence" && visual.summary) {
    return visual.summary;
  }

  const observed = event.observed_context || event.metadata || event.metadados || {};
  const parts = [];
  if (observed.operator_absent_seconds) parts.push(`Operador ausente durante ${secondsLabel(observed.operator_absent_seconds)}`);
  if (observed.operator_present_seconds) parts.push(`Operador presente durante ${secondsLabel(observed.operator_present_seconds)}`);
  if (observed.duracao || event.duracao) parts.push(`Duração observada: ${eventDuration(event)}`);
  if (event.confianca || observed.confianca) parts.push(`Confiança: ${Number(event.confianca || observed.confianca).toFixed(2)}`);
  return parts.join(" · ") || "Fatos observados disponíveis no detalhe.";
}

function visualEvidenceSequence(event) {
  const items = Array.isArray(event.visual_evidence) ? event.visual_evidence : [];
  if (!items.length) return "";

  const phaseOrder = { before: 0, transition: 1, during: 2, after: 3 };
  const phaseLabels = {
    before: "Antes",
    transition: "Momento detectado",
    during: "Durante",
    after: "Depois",
  };

  const sorted = [...items].sort((a, b) => {
    const phaseDiff = (phaseOrder[a.phase] ?? 9) - (phaseOrder[b.phase] ?? 9);
    if (phaseDiff !== 0) return phaseDiff;
    return String(a.captured_at || "").localeCompare(String(b.captured_at || ""));
  });

  return `
    <section class="cx-visual-sequence-section">
      <div class="cx-visual-section-head">
        <div>
          <span class="cx-visual-eyebrow">Contexto visual</span>
          <h3>O que aconteceu ao redor do momento</h3>
        </div>
        <span>${sorted.length} evidência${sorted.length === 1 ? "" : "s"}</span>
      </div>

      <div class="cx-visual-sequence">
        ${sorted.map((item) => `
          <figure class="cx-visual-evidence-card">
            <div class="cx-visual-evidence-image">
              <img src="${item.url}" alt="${sanitize(phaseLabels[item.phase] || "Evidência visual")}" />
            </div>
            <figcaption>
              <strong>${sanitize(phaseLabels[item.phase] || "Evidência")}</strong>
              <span>${eventDateLabel(item.captured_at)}</span>
            </figcaption>
          </figure>
        `).join("")}
      </div>
    </section>
  `;
}


function eventHasEvidence(event) {
  return Boolean(event.midia_path || event.snapshot_path || event.evidence_id);
}

function eventContextSearchText(event) {
  const context = eventContext(event);
  return [context.primary, context.location, context.asset, context.area, context.process, context.camera].filter(Boolean).join(" ").toLowerCase();
}

function eventMatchesCompactFilters(event) {
  if (eventsSelectedFamily === "official" && eventFamily(event) === "unknown") return false;
  if (eventsSelectedFamily !== "all" && eventsSelectedFamily !== "official" && eventFamily(event) !== eventsSelectedFamily) return false;
  if (eventsSelectedStatus !== "all" && eventPhysicalStatus(event) !== eventsSelectedStatus) return false;
  if (eventsSelectedSeverity !== "all" && eventSeverityTone(eventSeverity(event)) !== eventsSelectedSeverity && eventSeverity(event) !== eventsSelectedSeverity) return false;
  if (eventsContextQuery && !eventContextSearchText(event).includes(eventsContextQuery.toLowerCase())) return false;
  return true;
}

function eventsSummaryMetrics(events) {
  const filtered = events.filter((event) => eventsSelectedFamily === "all" || eventFamily(event) !== "unknown");
  return [
    homeMetric("Em andamento", filtered.filter((event) => eventPhysicalStatus(event) === "open").length, "Ocorrências físicas abertas", "clock"),
    homeMetric("Alta prioridade", filtered.filter((event) => ["critical", "high"].includes(eventSeverityTone(eventSeverity(event)))).length, "Severidade alta ou crítica", "alert"),
    homeMetric("Encerrados", filtered.filter((event) => eventPhysicalStatus(event) === "closed").length, "Ocorrências finalizadas", "signal"),
    homeMetric("Com evidência", filtered.filter(eventHasEvidence).length, "Registros visuais disponíveis", "camera"),
  ].join("");
}

function renderEventsFilters() {
  return `
    <div class="cx-events-filters">
      <label>Período
        <select id="eventsPeriodFilter">
          <option value="all" ${eventsSelectedPeriod === "all" ? "selected" : ""}>Todo histórico</option>
          <option value="today" ${eventsSelectedPeriod === "today" ? "selected" : ""}>Hoje</option>
          <option value="week" ${eventsSelectedPeriod === "week" ? "selected" : ""}>Semana</option>
          <option value="month" ${eventsSelectedPeriod === "month" ? "selected" : ""}>Mês</option>
        </select>
      </label>
      <label>Status
        <select id="eventsStatusFilter">
          <option value="all" ${eventsSelectedStatus === "all" ? "selected" : ""}>Todos</option>
          <option value="open" ${eventsSelectedStatus === "open" ? "selected" : ""}>Em andamento</option>
          <option value="closed" ${eventsSelectedStatus === "closed" ? "selected" : ""}>Encerrado</option>
        </select>
      </label>
      <label>Severidade
        <select id="eventsSeverityFilter">
          <option value="all" ${eventsSelectedSeverity === "all" ? "selected" : ""}>Todas</option>
          <option value="critical" ${eventsSelectedSeverity === "critical" ? "selected" : ""}>Crítica</option>
          <option value="high" ${eventsSelectedSeverity === "high" ? "selected" : ""}>Alta</option>
          <option value="medium" ${eventsSelectedSeverity === "medium" ? "selected" : ""}>Média</option>
          <option value="low" ${eventsSelectedSeverity === "low" ? "selected" : ""}>Baixa</option>
        </select>
      </label>
      <label>Tipo
        <select id="eventsFamilyFilter">
          <option value="official" ${eventsSelectedFamily === "official" ? "selected" : ""}>Operacionais</option>
          <option value="interruption" ${eventsSelectedFamily === "interruption" ? "selected" : ""}>Interrupção</option>
          <option value="wait" ${eventsSelectedFamily === "wait" ? "selected" : ""}>Espera</option>
          <option value="absence" ${eventsSelectedFamily === "absence" ? "selected" : ""}>Ausência</option>
          <option value="flow" ${eventsSelectedFamily === "flow" ? "selected" : ""}>Fluxo</option>
          <option value="unknown" ${eventsSelectedFamily === "unknown" ? "selected" : ""}>Não classificados</option>
          <option value="all" ${eventsSelectedFamily === "all" ? "selected" : ""}>Todos</option>
        </select>
      </label>
      <label>Ativo/área
        <input id="eventsContextFilter" value="${sanitize(eventsContextQuery)}" placeholder="Buscar contexto" />
      </label>
    </div>
  `;
}

function eventPeriodMatches(event) {
  if (eventsSelectedPeriod === "all") return true;
  const started = Date.parse(eventStart(event));
  if (Number.isNaN(started)) return true;
  const now = new Date();
  const start = new Date(now);
  if (eventsSelectedPeriod === "today") start.setHours(0, 0, 0, 0);
  if (eventsSelectedPeriod === "week") start.setDate(now.getDate() - 7);
  if (eventsSelectedPeriod === "month") start.setMonth(now.getMonth() - 1);
  return started >= start.getTime();
}

function renderEventsList(events) {
  const filtered = events.filter(eventPeriodMatches).filter(eventMatchesCompactFilters);
  rowsCache = filtered;
  if (!filtered.length) {
    return `
      <div class="cx-events-empty">
        <strong>Nenhuma ocorrência encontrada neste período.</strong>
        <p>Quando houver eventos operacionais reais correspondentes aos filtros, eles aparecerão nesta memória operacional.</p>
      </div>
    `;
  }
  return `
    <div class="cx-events-list" aria-label="Ocorrências operacionais">
      <div class="cx-events-row cx-events-head" aria-hidden="true">
        <span>Evento</span>
        <span>Prioridade</span>
        <span>Estado</span>
        <span>Quando</span>
        <span>Evidência</span>
      </div>
      ${filtered.map((event, index) => {
        const context = eventDisplayContext(event);
        const hasEvidence = eventHasEvidence(event);
        return `
          <button class="cx-events-row" type="button" data-row-index="${index}">
            <span class="cx-events-primary">
              <i class="${eventPhysicalStatus(event)}" aria-hidden="true"></i>
              <span>
                <strong>${eventTitle(event)}</strong>
                <small>${context.location ? `${context.title} · ${context.location}` : context.title}</small>
              </span>
            </span>
            <span>${eventSeverityPill(event)}</span>
            <span class="cx-events-state"><strong>${eventPhysicalStatusLabel(event)}</strong><small>${workflowLabel(eventWorkflow(event))}</small></span>
            <span class="cx-events-time"><strong>${eventDateLabel(eventStart(event))}</strong><small>${eventDisplayDuration(event)}</small></span>
            <span class="cx-events-evidence ${hasEvidence ? "available" : "missing"}">${hasEvidence ? "<i></i>Evidência" : "Sem evidência"}</span>
            <span class="cx-events-arrow">›</span>
          </button>
        `;
      }).join("")}
    </div>
  `;
}

async function renderEventsPage(config) {
  const payload = await requestJson(config.endpoint);
  const sourceEvents = Array.isArray(payload) ? payload : (payload.events || []);
  const events = sourceEvents.filter((event) => eventsSelectedFamily === "all" || eventFamily(event) !== "unknown" || eventsSelectedFamily === "unknown");
  title.textContent = "Eventos";
  heading.textContent = "Ocorrências e incidentes registrados pela operação.";
  subtitle.textContent = "Memória operacional verificável, com evidência, contexto e tratamento.";
  tableTitle.textContent = "";
  tableHint.textContent = "";
  primaryAction.textContent = "Atualizar";
  primaryAction.onclick = () => loadPage(window.location.pathname);
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  body.closest("table")?.setAttribute("aria-hidden", "true");
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");
  cards.innerHTML = `
    <section class="cx-events-v1-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar ocorrências, ativos, áreas...</div>
        <div class="cx-home-topbar-actions">
          <span>${events.length} ocorrência(s)</span>
          <span>${eventsSelectedPeriod === "all" ? "Todo histórico" : eventsSelectedPeriod}</span>
          <button type="button" class="cx-events-clear-button" id="cx-events-clear">
            <span class="cx-events-clear-button__text">Limpar eventos</span>
            <span class="cx-events-clear-button__icon" aria-hidden="true">
              <svg class="cx-events-clear-button__svg" viewBox="0 0 24 24">
                <path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-1 11H8L7 9Zm3 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z"/>
              </svg>
            </span>
          </button>
        </div>
      </div>
      <header class="cx-events-hero">
        <div>
          <span>Eventos</span>
          <h2>Memória operacional da sua operação.</h2>
          <p>Veja ocorrências, evidências e o estado de cada evento registrado.</p>
        </div>
      </header>
      <section class="cx-home-kpi-grid cx-events-summary">${eventsSummaryMetrics(sourceEvents)}</section>
      <section class="cx-home-section cx-events-main">
        <div class="cx-home-section-head">
          <span>Memória operacional</span>
          <small>${rowsCache.length || events.length} ocorrência(s) na seleção</small>
        </div>
        ${renderEventsFilters()}
        ${renderEventsList(events)}
      </section>
    </section>
  `;

  document.querySelector("#cx-events-clear")?.addEventListener("click", async () => {
    const confirmed = window.confirm(
      "Apagar todos os eventos desta empresa?\n\nEsta ação limpa o histórico de eventos e evidências relacionadas, mas não altera câmeras, zonas ou calibração."
    );
    if (!confirmed) return;

    const button = document.querySelector("#cx-events-clear");
    if (button) button.disabled = true;

    try {
      const result = await requestJson("/eventos", { method: "DELETE" });
      window.alert(`${result.deleted || 0} evento(s) apagado(s).`);
      await loadPage(window.location.pathname);
    } catch (error) {
      window.alert(`Não foi possível limpar os eventos: ${error.message}`);
      if (button) button.disabled = false;
    }
  });
}

function filterCanonicalEvents(rows) {
  return (rows || []).filter((event) => {
    const family = eventFamily(event);
    return family !== "unknown" || currentTab === "não classificados";
  });
}

function eventRow(event) {
  const context = eventContext(event);
  return [
    `<div class="cx-event-cell"><strong>${eventTitle(event)}</strong><span>${familyLabel(eventFamily(event))}</span></div>`,
    `<div class="cx-event-cell"><strong>${context.primary}</strong><span>${context.location}</span></div>`,
    eventTimeRange(event),
    eventPhysicalStatus(event) === "open" ? "em andamento" : eventDuration(event),
    badge(workflowLabel(eventWorkflow(event))),
    evidenceLink(event),
    rowMenu(),
  ];
}

function eventCard(event) {
  const context = eventContext(event);
  const physical = eventPhysicalStatus(event);
  return `
    <article class="cx-event-card" data-event-card="${event.id || ""}">
      <div class="cx-event-card-head">
        <div>
          <strong>${eventTitle(event)}</strong>
          <span>${context.primary} · ${context.location}</span>
        </div>
        ${badge(physical === "open" ? "Em andamento" : "Encerrado")}
      </div>
      <p>${eventTimeRange(event)} · ${physical === "open" ? "em andamento" : eventDuration(event)}</p>
      <p>${eventObservedSummary(event)}</p>
      <div class="cx-event-card-actions">
        ${badge(workflowLabel(eventWorkflow(event)))}
        ${event.midia_path || event.snapshot_path ? `<a class="cx-link" href="/eventos/${event.id}/evidence" target="_blank">Evidência</a>` : `<span class="muted">Sem evidência</span>`}
        <button class="cx-linklike" type="button" data-open-detail>Abrir evento</button>
      </div>
    </article>
  `;
}

function cameraCard(camera) {
  return `
    <article class="cx-camera-tile">
      <div class="cx-camera-thumb"><span class="cx-nav-icon" data-icon="camera"></span></div>
      <div><strong>${camera.nome || "Câmera"}</strong><span>${camera.unidade_id || "Localização não informada"}</span></div>
      ${badge(cameraStatusLabel(camera.status))}
      <p>Último evento: ${camera.ultimo_erro || "sem registro"}</p>
      <p>Atualização: ${camera.ultimo_frame || camera.criado_em || "—"}</p>
      <button class="cx-row-menu" type="button" data-open-detail>•••</button>
    </article>
  `;
}

function evidenceCard(event) {
  return `
    <article class="cx-camera-tile">
      <div class="cx-camera-thumb"><span class="cx-nav-icon" data-icon="evidence"></span></div>
      <div><strong>${eventTitle(event)}</strong><span>${eventStart(event)}</span></div>
      ${badge(eventSeverity(event))}
      <p>Origem: ${event.camera_id || "—"}</p>
      ${evidenceLink(event)}
    </article>
  `;
}

function evidenceRow(event) {
  return [
    event.midia_path || event.snapshot_path ? "Disponível" : "—",
    eventTitle(event),
    eventStart(event),
    event.unidade_id || "—",
    event.area_id || event.regiao_id || "—",
    event.camera_id || "—",
    eventCategory(event),
    badge(eventSeverity(event)),
    eventDuration(event),
    event.retention || "Política local",
    badge(eventStatusLabel(event.status)),
    evidenceLink(event),
  ];
}

function eventTimelineSteps(event) {
  const workflow = eventWorkflow(event);
  return [
    eventStart(event) !== "—" ? ["Situação iniciada", eventStart(event)] : null,
    event.confirmed_at ? ["Condição confirmada", event.confirmed_at] : null,
    event.id ? ["Evento criado", event.criado_em || eventStart(event)] : null,
    event.midia_path || event.snapshot_path ? ["Evidência salva", "Disponível"] : null,
    event.alert_sent || event.alerta_enviado ? ["Alerta enviado", "Registrado"] : null,
    workflow === "acknowledged" || workflow === "resolved" ? ["Reconhecido", event.acknowledged_at || event.human_context?.acknowledged_at || "—"] : null,
    eventEnd(event) ? ["Normalizado", eventEnd(event)] : null,
    eventPhysicalStatus(event) === "closed" ? ["Encerrado fisicamente", eventEnd(event) || "—"] : null,
    workflow === "resolved" ? ["Resolvido pela gestão", event.resolved_at || event.human_context?.resolved_at || "—"] : null,
  ].filter(Boolean);
}

function renderTimelineList(steps) {
  if (!steps.length) return "<p>Sem etapas registradas.</p>";
  return `<ol class="cx-event-timeline">${steps.map(([label, value]) => `<li><strong>${label}</strong><span>${value}</span></li>`).join("")}</ol>`;
}

function eventDetail(event) {
  const context = eventContext(event);
  const physical = event.physical_context || {};
  const observed = event.observed_context || {};
  const human = event.human_context || {};
  const workflow = eventWorkflow(event);
  const evidence = event.midia_path || event.snapshot_path;
  const visual = event.visual_understanding || null;
  const hasVisualSequence = Array.isArray(event.visual_evidence) && event.visual_evidence.length > 0;
  return `
    <section class="cx-event-detail-v1">
      <header>
        <span>${familyLabel(eventFamily(event))}</span>
        <h2>${eventTitle(event)}</h2>
        <p>${homeContextName(context.primary, "Contexto não informado")} · ${homeContextName(context.location, "Local não informado")}</p>
      </header>
      <dl class="cx-event-detail-facts">
        <div><dt>Estado da ocorrência</dt><dd>${event.tipo === "visual_occurrence" ? "Registrada" : eventPhysicalStatusLabel(event)}</dd></div>
        <div><dt>Tratamento</dt><dd>${workflowLabel(workflow)}</dd></div>
        <div><dt>Severidade</dt><dd>${eventSeverityLabel(eventSeverity(event))}</dd></div>
        <div><dt>Horário</dt><dd>${eventTimeRange(event)}</dd></div>
        <div><dt>Duração</dt><dd>${event.tipo === "visual_occurrence" ? "Ocorrência pontual" : eventDisplayDuration(event)}</dd></div>
      </dl>

      ${event.tipo === "visual_occurrence" && hasVisualSequence
        ? visualEvidenceSequence(event)
        : `
          <section>
            <h3>Evidência</h3>
            <div class="cx-detail-frame cx-event-evidence-frame">${evidence ? `<img src="/eventos/${event.id}/evidence" alt="Frame da ocorrência" />` : "Nenhuma evidência visual disponível."}</div>
          </section>
        `
      }

      <section>
        <h3>O que a Campex observou</h3>

        ${visual ? `
          <div class="cx-visual-understanding">
            <span class="cx-visual-eyebrow">Análise visual</span>
            <p>${sanitize(visual.summary || "A Campex analisou as evidências visuais deste momento.")}</p>

            <div class="cx-visual-analysis-meta">
              <div>
                <span>Validação</span>
                <strong>${visual.status === "VALID" ? "Validada" : visual.status === "PARTIAL" ? "Com ressalvas" : sanitize(visual.status || "Não informada")}</strong>
              </div>
              <div>
                <span>Qualidade</span>
                <strong>${visual.quality === "complete" ? "Completa" : visual.quality === "partial" ? "Parcial" : sanitize(visual.quality || "Não informada")}</strong>
              </div>
              <div>
                <span>Incertezas</span>
                <strong>${Array.isArray(visual.uncertainties) ? visual.uncertainties.length : 0}</strong>
              </div>
            </div>
          </div>
        ` : `
          <dl>
            <div><dt>Operador presente</dt><dd>${observed.operador_presente === true ? "Sim" : observed.operador_presente === false ? "Não" : "Não informado"}</dd></div>
            <div><dt>Confiança</dt><dd>${observed.confianca ?? event.confianca ?? "Não informado"}</dd></div>
            <div><dt>Pessoas</dt><dd>${observed.quantidade_maxima ?? event.quantidade_maxima ?? event.quantidade_atual ?? "Não informado"}</dd></div>
            <div><dt>Resumo observado</dt><dd>${eventObservedSummary(event)}</dd></div>
          </dl>
        `}
      </section>

      <section>
        <h3>Contexto da operação</h3>
        <dl>
          <div><dt>Empresa</dt><dd>${homeContextName(event.cliente_name || event.cliente_id || physical.cliente_id, "Não informado")}</dd></div>
          <div><dt>Unidade</dt><dd>${homeContextName(event.unidade_name || event.unit_name || event.unidade_id || physical.unidade_id || physical.site_id, "Não informado")}</dd></div>
          <div><dt>Área</dt><dd>${homeContextName(context.area, "Não informado")}</dd></div>
          <div><dt>Processo</dt><dd>${homeContextName(context.process, "Não informado")}</dd></div>
          <div><dt>Ativo/posto</dt><dd>${homeContextName(context.asset, "Não informado")}</dd></div>
          <div><dt>Câmera</dt><dd>${homeContextName(context.camera, "Não informado")}</dd></div>
        </dl>
      </section>

      <section>
        <h3>Timeline</h3>
        ${renderTimelineList(eventTimelineSteps(event))}
      </section>

      <section>
        <h3>Tratamento</h3>
        <form class="cx-event-workflow-form" data-event-workflow-form data-event-id="${event.id || ""}" data-workflow="${workflow}">
          <label>Causa confirmada<input name="confirmed_cause" value="${human.confirmed_cause || event.confirmed_cause || ""}" placeholder="Ex.: falta de material" /></label>
          <label>Ação tomada<input name="action_taken" value="${human.action_taken || event.action_taken || ""}" placeholder="Ex.: abastecimento solicitado" /></label>
          <label>Notas<textarea name="human_notes" rows="3" placeholder="Observações da gestão">${human.human_notes || event.human_notes || ""}</textarea></label>
          <div class="cx-detail-actions">
            ${workflow === "new" ? `<button type="button" data-event-workflow-action="acknowledge" data-event-id="${event.id}">Reconhecer</button>` : ""}
            ${workflow !== "resolved" ? `<button type="button" data-event-workflow-action="save-human" data-event-id="${event.id}">Salvar contexto</button><button type="button" data-event-workflow-action="resolve" data-event-id="${event.id}">Resolver</button>` : `<span class="muted">Resolvido por ${human.resolved_by || event.resolved_by || "—"} em ${eventDateLabel(human.resolved_at || event.resolved_at)}</span>`}
          </div>
          <p class="muted" data-event-workflow-status></p>
        </form>
      </section>

      <details>
        <summary>Detalhes técnicos</summary>
        <pre>${JSON.stringify({ technical_type: eventTechnicalType(event), observed_context: observed, human_context: human }, null, 2)}</pre>
      </details>
    </section>
  `;
}

function evidenceDetail(event) {
  return `
    <h2>Evidência · ${eventTitle(event)}</h2>
    <div class="cx-detail-frame">${event.midia_path || event.snapshot_path ? `<img src="/eventos/${event.id}/evidence" alt="Evidência visual" />` : "Sem imagem disponível"}</div>
    <dl>
      <div><dt>Evento</dt><dd>${eventTitle(event)}</dd></div>
      <div><dt>Horário</dt><dd>${eventStart(event)}</dd></div>
      <div><dt>Área</dt><dd>${event.area_id || "—"}</dd></div>
      <div><dt>Câmera</dt><dd>${event.camera_id || "—"}</dd></div>
      <div><dt>Retenção</dt><dd>${event.retention || "Política local"}</dd></div>
      <div><dt>Link seguro</dt><dd>${event.midia_path || event.snapshot_path ? "Disponível pela API local" : "—"}</dd></div>
    </dl>
    <h3>Timeline</h3>
    ${renderTimelineList(eventTimelineSteps(event))}
    <h3>Metadados</h3>
    <pre>${JSON.stringify(event.metadados || event.metadata || {}, null, 2)}</pre>
  `;
}

function alertDeliveryDetail(delivery) {
  return `
    <h2>Entrega de alerta</h2>
    <dl>
      <div><dt>Evento</dt><dd>${delivery.evento_id || "Teste"}</dd></div>
      <div><dt>Destinatário</dt><dd>${delivery.destinatario || delivery.recipient_id || "—"}</dd></div>
      <div><dt>Canal</dt><dd>${delivery.channel || delivery.canal || "e-mail"}</dd></div>
      <div><dt>Horário</dt><dd>${delivery.sent_at || delivery.last_attempt_at || delivery.criado_em || "—"}</dd></div>
      <div><dt>Tentativas</dt><dd>${delivery.attempts || delivery.tentativas || 1}</dd></div>
      <div><dt>Status</dt><dd>${alertStatusLabel(delivery.status)}</dd></div>
      <div><dt>Erro</dt><dd>${delivery.erro || delivery.error || "—"}</dd></div>
    </dl>
  `;
}

function humanCondition(rule) {
  const type = rule.condicao?.type || rule.tipo_evento;
  const labels = {
    presence_in_zone: "Presença em zona",
    absence_in_zone: "Ausência em zona",
    count_between: "Contagem mínima/máxima",
    machine_state: "Estado da máquina",
    camera_status: "Câmera indisponível",
    no_motion_in_region: "Ausência de movimento",
    active_without_operator: "Máquina ativa sem operador",
    restricted_area_occupied: "Pessoa em área restrita",
  };
  return labels[type] || type || "Em desenvolvimento";
}

function reportLabel(key) {
  const labels = {
    eventos: "Eventos por período",
    cameras: "Disponibilidade das câmeras",
    tempo_maquina_ativa: "Tempo ativo",
    tempo_maquina_parada: "Tempo parado",
    quantidade_paradas: "Paradas",
    alertas: "Alertas",
    evidencias: "Evidências",
  };
  return labels[key] || key.replaceAll("_", " ");
}

function ruleDetail(rule) {
  return `
    <h2>${rule.nome || "Regra visual"}</h2>
    <dl>
      <div><dt>Câmera</dt><dd>${rule.camera_id || "—"}</dd></div>
      <div><dt>Tipo do evento</dt><dd>${rule.tipo_evento || "—"}</dd></div>
      <div><dt>Condição</dt><dd>${rule.condicao?.type || "—"}</dd></div>
      <div><dt>Duração mínima</dt><dd>${rule.tempo_minimo || 0}s</dd></div>
      <div><dt>Severidade</dt><dd>${rule.severidade || "medium"}</dd></div>
      <div><dt>Cooldown</dt><dd>${rule.cooldown_seconds || 0}s</dd></div>
      <div><dt>Alerta ao iniciar</dt><dd>${rule.alerta_inicio ? "Sim" : "Não"}</dd></div>
      <div><dt>Alerta ao normalizar</dt><dd>${rule.alerta_normalizacao ? "Sim" : "Não"}</dd></div>
      <div><dt>Status</dt><dd>${rule.ativo ? "Ativa" : "Inativa"}</dd></div>
    </dl>
    <pre>${JSON.stringify(rule.condicao || {}, null, 2)}</pre>
  `;
}

function visualRuleForm() {
  return `
    <h2>Configurar regra visual</h2>
    <ol class="cx-rule-steps">
      <li>Escolher câmera</li>
      <li>Escolher área ou zona</li>
      <li>Escolher condição</li>
      <li>Definir duração mínima</li>
      <li>Definir severidade</li>
      <li>Configurar alertas</li>
      <li>Revisar</li>
      <li>Ativar</li>
    </ol>
    <form id="visualRuleForm" class="form">
      <label>Nome da regra<input name="nome" required placeholder="Ex.: Máquina ativa sem operador" /></label>
      <label>Câmera<input name="camera_id" required placeholder="ID da câmera cadastrada" /></label>
      <label>Área ou zona<input name="regiao_id" placeholder="Ex.: operador, doca_1, zona_segurança" /></label>
      <label>Tipo do evento<input name="tipo_evento" required value="active_without_operator" /></label>
      <label>Condição
        <select name="condition_type">
          <option value="all">Máquina ativa + ausência em zona</option>
          <option value="presence_in_zone">Presença em zona</option>
          <option value="absence_in_zone">Ausência em zona</option>
          <option value="dwell_time">Permanência acima do limite</option>
          <option value="count_between">Contagem mínima e máxima</option>
          <option value="machine_state">Estado da máquina</option>
          <option value="camera_status">Status da câmera</option>
          <option value="no_motion_in_region">Ausência de movimento</option>
          <option disabled>Circulação em área configurada — em desenvolvimento</option>
          <option disabled>Proximidade — em desenvolvimento</option>
        </select>
      </label>
      <label>Duração mínima em segundos<input name="tempo_minimo" type="number" min="0" step="1" value="120" /></label>
      <label>Severidade
        <select name="severidade">
          <option value="low">Baixa</option>
          <option value="medium">Média</option>
          <option value="high">Alta</option>
          <option value="critical">Crítica</option>
        </select>
      </label>
      <label>Cooldown em segundos<input name="cooldown_seconds" type="number" min="0" step="1" value="300" /></label>
      <label><input name="alerta_inicio" type="checkbox" checked /> Enviar alerta ao iniciar</label>
      <label><input name="alerta_normalizacao" type="checkbox" /> Enviar alerta ao normalizar</label>
      <div class="cx-rule-human-summary">
        Quando a condição configurada permanecer pelo tempo mínimo, a Campex cria um evento único, registra evidência quando disponível e avisa os responsáveis selecionados.
      </div>
      <button type="submit">Salvar regra</button>
      <p id="visualRuleStatus" class="muted">A regra será salva no banco local e poderá ser testada no modo simulação.</p>
    </form>
  `;
}

function conditionFromForm(data) {
  const type = data.get("condition_type");
  const zone = data.get("regiao_id") || undefined;
  if (type === "all") {
    return {
      type: "all",
      conditions: [
        { type: "machine_state", state: "ATIVA" },
        { type: "absence_in_zone", zone_id: zone || "operator", max_count: 0 },
      ],
    };
  }
  if (type === "presence_in_zone") return { type, zone_id: zone, min_count: 1 };
  if (type === "dwell_time") return { type: "presence_in_zone", zone_id: zone, min_count: 1 };
  if (type === "absence_in_zone") return { type, zone_id: zone, max_count: 0 };
  if (type === "count_between") return { type, field: "people_count", min: 1, max: 5 };
  if (type === "machine_state") return { type, state: "PARADA" };
  if (type === "camera_status") return { type, status: "offline" };
  if (type === "no_motion_in_region") return { type, zone_id: zone, max_motion: 0 };
  return { type };
}

function matchesTab(row) {
  const text = JSON.stringify(row).toLowerCase();
  if ((currentTab === "all" || currentTab === "todas" || currentTab === "todos") && (row.tipo || row.event_family || row.event_uuid)) return eventFamily(row) !== "unknown";
  if (currentTab === "all" || currentTab === "todas" || currentTab === "todos" || currentTab === "grade" || currentTab === "lista") return true;
  if (currentTab === "ativa") return cameraStatusLabel(row.status).toLowerCase() === "ativa";
  if (currentTab === "sem sinal") return cameraStatusLabel(row.status).toLowerCase() === "sem sinal";
  if (currentTab === "em configuração") return cameraStatusLabel(row.status).toLowerCase() === "em configuração";
  if (currentTab === "pausada") return cameraStatusLabel(row.status).toLowerCase() === "pausada";
  if (currentTab === "abertos") return eventPhysicalStatus(row) === "open";
  if (currentTab === "encerrados") return eventPhysicalStatus(row) === "closed";
  if (currentTab === "novo") return eventWorkflow(row) === "new";
  if (currentTab === "reconhecido") return eventWorkflow(row) === "acknowledged";
  if (currentTab === "resolvido") return eventWorkflow(row) === "resolved";
  if (currentTab === "não classificados") return eventFamily(row) === "unknown";
  if (["aberto", "em análise", "encerrado", "descartado"].includes(currentTab)) return eventStatusLabel(row.status).toLowerCase() === currentTab;
  if (currentTab === "paradas") return text.includes("stoppage") || text.includes("parada");
  if (currentTab === "pessoas") return text.includes("restricted") || text.includes("pessoa");
  if (currentTab === "máquinas") return text.includes("machine") || text.includes("máquina");
  if (currentTab === "com evidência") return Boolean(row.midia_path || row.snapshot_path);
  if (currentTab === "regras de alerta") return row.workspace_kind === "regra";
  if (currentTab === "destinatários") return row.workspace_kind === "destinatario";
  if (currentTab === "entregas") return row.workspace_kind === "entrega";
  if (currentTab === "falhas") return row.workspace_kind === "entrega" && String(row.status).toLowerCase() === "failed";
  if (currentTab === "pendentes") return text.includes("pending") || text.includes("failed");
  if (currentTab === "enviados") return text.includes("sent");
  if (currentTab === "ativas") return row.ativo === true || row.ativo === 1;
  if (currentTab === "inativas") return row.ativo === false || row.ativo === 0;
  if (currentTab === "em desenvolvimento") return humanCondition(row) === "Em desenvolvimento";
  return true;
}

function includesSearch(row) {
  const query = (search.value || "").trim().toLowerCase();
  if (!query) return true;
  return JSON.stringify(row).toLowerCase().includes(query);
}

function renderTabs(config) {
  tabs.innerHTML = (config.tabs || []).map((tab, index) => `<button type="button" class="${index === 0 ? "active" : ""}" data-tab="${tab.toLowerCase()}">${tab}</button>`).join("");
  currentTab = (config.tabs?.[0] || "all").toLowerCase();
}

function renderFilters(config) {
  if (config.title === "Eventos") {
    filters.innerHTML = `
      <label>Período inicial<input type="date" data-filter="period_start" /></label>
      <label>Período final<input type="date" data-filter="period_end" /></label>
      <label>Unidade<input placeholder="Unidade" data-filter="unidade" /></label>
      <label>Área<input placeholder="Área" data-filter="area" /></label>
      <label>Processo<input placeholder="Processo" data-filter="processo" /></label>
      <label>Ativo<input placeholder="Ativo" data-filter="ativo" /></label>
      <label>Família
        <select data-filter="familia">
          <option value="">Todas</option>
          <option value="interruption">Interrupção</option>
          <option value="wait">Espera</option>
          <option value="flow">Fluxo</option>
          <option value="absence">Ausência</option>
          <option value="unknown">Não classificados</option>
        </select>
      </label>
      <label>Estado físico
        <select data-filter="estado_fisico">
          <option value="">Todos</option>
          <option value="open">Aberto</option>
          <option value="closed">Encerrado</option>
        </select>
      </label>
      <label>Workflow
        <select data-filter="workflow">
          <option value="">Todos</option>
          <option value="new">Novo</option>
          <option value="acknowledged">Reconhecido</option>
          <option value="resolved">Resolvido</option>
        </select>
      </label>
    `;
    return;
  }
  filters.innerHTML = (config.filters || []).map((label) => `
    <label>${label}<input placeholder="${label}" data-filter="${label}" /></label>
  `).join("");
}

function currentRouteConfig() {
  return routes[currentRouteKey()] || routes["/cameras"];
}

function activeRouteKey(path = window.location.pathname) {
  if (String(path).includes("?")) {
    return navigationKeyFromUrl(new URL(path, window.location.origin));
  }
  if (path === "/home-view") return "/home-view";
  if (path === "/settings" || path.startsWith("/settings/")) return "/settings/cameras";
  if (path === "/" || path === "/dashboard") return "/operations-view";
  return path;
}

function emptyState(config) {
  const action = config.actionHref
    ? `<a class="cx-primary-action" href="${config.actionHref}">${config.action || "Abrir"}</a>`
    : `<button type="button" data-refresh-workspace>${config.action || "Atualizar"}</button>`;
  return `
    <div class="cx-empty-state">
      <strong>${config.emptyTitle || `Nenhum registro em ${config.title}.`}</strong>
      <p>${config.emptyDescription || "Os dados aparecerão aqui quando forem registrados pela Campex."}</p>
      ${config.action ? action : ""}
    </div>
  `;
}

function loginState(config) {
  const next = encodeURIComponent(window.location.pathname || "/operations-view");
  return `
    <div class="cx-empty-state">
      <strong>Login necessário</strong>
      <p>Entre para carregar ${String(config.title || "esta área").toLowerCase()} e proteger os dados do cliente.</p>
      <a class="cx-primary-action" href="/login?next=${next}">Entrar</a>
    </div>
  `;
}

function usesProductMemoryShell(path) {
  return path === "/home-view" || path === "/operations-view" || path === "/events" || path === "/insights" || path === "/reports";
}

async function openEdgeInstaller() {
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawerContent.innerHTML = `
    <div class="cx-drawer-section">
      <p class="cx-eyebrow">Campex Edge</p>
      <h2 id="workspaceDrawerTitle">Instalar Campex Edge</h2>
      <p>Escolha a unidade onde este computador será instalado.</p>

      <label class="cx-field">
        <span>Unidade</span>
        <select id="cx-edge-install-unit">
          <option value="">Carregando unidades...</option>
        </select>
      </label>

      <div id="cx-edge-install-status" role="status"></div>

      <button
        id="cx-edge-install-download"
        class="cx-primary-action"
        type="button"
        disabled
      >
        Baixar Campex Edge
      </button>
    </div>
  `;

  drawer.focus({ preventScroll: true });

  const select = drawerContent.querySelector("#cx-edge-install-unit");
  const button = drawerContent.querySelector("#cx-edge-install-download");
  const status = drawerContent.querySelector("#cx-edge-install-status");

  try {
    const response = await fetch("/unidades", { credentials: "same-origin" });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const units = await response.json();

    if (!Array.isArray(units) || !units.length) {
      select.innerHTML = `<option value="">Nenhuma unidade cadastrada</option>`;
      status.textContent = "Cadastre uma unidade antes de instalar o Edge.";
      return;
    }

    select.innerHTML = `
      <option value="">Selecione uma unidade</option>
      ${units.map((unit) => `
        <option value="${unit.id}">
          ${unit.nome || unit.id}
        </option>
      `).join("")}
    `;

    select.addEventListener("change", () => {
      button.disabled = !select.value;
    });

    button.addEventListener("click", () => {
      if (!select.value) return;

      status.textContent = "Preparando instalador...";
      window.location.href =
        `/edge-installer/windows?unidade_id=${encodeURIComponent(select.value)}`;
    });
  } catch (error) {
    select.innerHTML = `<option value="">Não foi possível carregar</option>`;
    status.textContent = "Não foi possível carregar as unidades.";
  }
}

function renderOperationsAuthState(area = "Operação") {
  const target = area === "Início"
    ? "%2Foperations-view%3Fview%3Dhome"
    : area === "Relatórios"
      ? "%2Freports"
      : "%2Foperations-view";
  title.textContent = "";
  heading.textContent = "";
  subtitle.textContent = "";
  tableTitle.textContent = "";
  tableHint.textContent = "";
  primaryAction.textContent = "Entrar";


  primaryAction.onclick = () => {
    window.location.href = `/login?next=${target}`;
  };
  cards.innerHTML = `
    <section class="cx-ops-v1-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar ativos, incidentes, câmeras...</div>
        <div class="cx-home-topbar-actions">
          <span>Unidade principal</span>
          <span>Login necessário</span>
        </div>
      </div>
      <header class="${area === "Operação" ? "cx-ops-hero" : "cx-home-header"}">
        ${area === "Operação" ? `<span class="cx-ops-hero-icon" aria-hidden="true"><span class="cx-nav-icon" data-icon="operations"></span></span>` : ""}
        <div>
          <span>${area}</span>
          <h2>${area === "Início" ? "Visão atual da sua operação." : "Estado operacional da sua planta."}</h2>
          <p>${area === "Início" ? "Dados reais da instalação Campex, sem preenchimento demonstrativo." : "Veja o que está em operação, parado ou exigindo atenção agora."}</p>
        </div>
      </header>
      <section class="cx-home-section cx-ops-auth">
        <span>${area}</span>
        <strong>Entre para acessar os dados da operação.</strong>
        <p>A Campex protege os dados operacionais do cliente. Faça login para carregar esta instalação.</p>
        <a class="cx-primary-action" href="/login?next=${target}">Entrar</a>
      </section>
    </section>
  `;
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  rowsCache = [];
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");
}

function renderEventsAuthState() {
  title.textContent = "Eventos";
  heading.textContent = "Ocorrências e incidentes registrados pela operação.";
  subtitle.textContent = "Entre para carregar a memória operacional real.";
  tableTitle.textContent = "";
  tableHint.textContent = "";
  primaryAction.textContent = "Entrar";
  primaryAction.onclick = () => {
    window.location.href = "/login?next=%2Fevents";
  };
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  rowsCache = [];
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  body.closest("table")?.setAttribute("aria-hidden", "true");
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");
  cards.innerHTML = `
    <section class="cx-events-v1-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar ocorrências, ativos, áreas...</div>
        <div class="cx-home-topbar-actions">
          <span>Eventos</span>
          <span>Protegido</span>
        </div>
      </div>
      <header class="cx-events-hero">
        <div>
          <span>Eventos</span>
          <h2>Memória operacional da sua operação.</h2>
          <p>A Campex protege ocorrências, evidências, workflow e contexto operacional. Entre para investigar os dados reais da instalação.</p>
        </div>
      </header>
      <section class="cx-home-section cx-events-auth">
        <strong>Entre para acessar os eventos da operação.</strong>
        <p>Sem autenticação, a Campex não carrega ocorrências, evidências, workflow ou contexto operacional.</p>
        <a class="cx-primary-action" href="/login?next=%2Fevents">Entrar</a>
      </section>
    </section>
  `;
}

function renderIntelligenceAuthState() {
  title.textContent = "Intelligence";
  heading.textContent = "Intelligence";
  subtitle.textContent = "Padrões, comparações e resumos verificáveis da operação.";
  tableTitle.textContent = "";
  tableHint.textContent = "";
  primaryAction.textContent = "Entrar";
  primaryAction.onclick = () => {
    window.location.href = "/login?next=%2Finsights";
  };
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  rowsCache = [];
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  body.closest("table")?.setAttribute("aria-hidden", "true");
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");
  cards.innerHTML = `
    <section class="cx-intel-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar padrões, ativos, causas...</div>
        <div class="cx-home-topbar-actions">
          <span>Intelligence</span>
          <span>Protegido</span>
        </div>
      </div>
      <header class="cx-intel-hero">
        <div>
          <span>Intelligence</span>
          <h2>Entenda o que está mudando na sua operação.</h2>
          <p>Padrões, comparações e leituras verificáveis a partir dos dados observados.</p>
        </div>
        <aside class="cx-intel-context">
          <div><small>Período</small><strong>Protegido</strong></div>
          <div><small>Cobertura</small><strong>Indisponível</strong></div>
        </aside>
      </header>
      <section class="cx-intel-briefing">
        <small>Leitura do período</small>
        <strong>Entre para acessar padrões, comparações e resumos verificáveis da operação.</strong>
      </section>
      <section class="cx-intel-module">
        <h3>Dados protegidos</h3>
        <p>A Campex não carrega insights, causas, rastreabilidade ou eventos do cliente sem autenticação.</p>
        <a class="cx-primary-action" href="/login?next=%2Finsights">Entrar</a>
      </section>
    </section>
  `;
}

function renderReportsAuthState() {
  title.textContent = "Relatórios";
  heading.textContent = "Relatórios";
  subtitle.textContent = "Configure quando receber e acompanhe os relatórios gerados pela Campex.";
  tableTitle.textContent = "";
  tableHint.textContent = "";
  primaryAction.textContent = "Entrar";
  primaryAction.onclick = () => {
    window.location.href = "/login?next=%2Freports";
  };
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  rowsCache = [];
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  body.closest("table")?.setAttribute("aria-hidden", "true");
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");
  cards.innerHTML = `
    <section class="cx-reports-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar relatórios, empresas, entregas...</div>
        <div class="cx-home-topbar-actions">
          <span>Relatórios</span>
          <span>Protegido</span>
        </div>
      </div>
      <header class="cx-report-hero">
        <div>
          <span class="cx-report-eyebrow">Relatórios</span>
          <h2>Leituras da sua operação, entregues automaticamente.</h2>
          <p>Configure quando receber e acompanhe os relatórios gerados pela Campex.</p>
        </div>
        <aside class="cx-report-next">
          <div><span>Próximo envio</span><strong>Protegido</strong></div>
          <div><span>Empresa</span><strong>Indisponível</strong></div>
        </aside>
      </header>
      <section class="cx-report-history">
        <div class="cx-report-section-heading">
          <div>
            <span class="cx-report-eyebrow">Acesso</span>
            <h3>Login necessário</h3>
          </div>
        </div>
        <p class="muted">Entre para carregar configuração, prévia e histórico de entregas da operação.</p>
        <a class="cx-primary-action" href="/login?next=%2Freports">Entrar</a>
      </section>
    </section>
  `;
}

function renderHomeAuthState() {
  title.textContent = "Início";
  heading.textContent = "Visão atual da sua operação.";
  subtitle.textContent = "Entre para carregar dados reais da instalação.";
  tableTitle.textContent = "";
  tableHint.textContent = "";
  primaryAction.textContent = "Entrar";
  primaryAction.onclick = () => {
    window.location.href = "/login?next=%2Foperations-view%3Fview%3Dhome";
  };
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  rowsCache = [];
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  body.closest("table")?.setAttribute("aria-hidden", "true");
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");
  cards.innerHTML = `
    <section class="cx-home-page">
      <div class="cx-home-topbar">
        <div class="cx-home-search">Buscar ativos, incidentes, câmeras...</div>
        <div class="cx-home-topbar-actions">
          <span>Unidade principal</span>
          <span>Sessão necessária</span>
        </div>
      </div>
      <header class="cx-home-header">
        <div>
          <span>Início</span>
          <h2>Entre para acessar a operação da Campex.</h2>
          <p>Os dados de ativos, incidentes, evidências e inteligência ficam disponíveis apenas para usuários autenticados.</p>
        </div>
        <div class="cx-home-period">
          <small>Status</small>
          <strong>Sessão necessária</strong>
        </div>
      </header>
      <section class="cx-home-auth-gate">
        <div>
          <span>Acesso protegido</span>
          <strong>Entre para carregar a leitura operacional real.</strong>
          <p>Sem autenticação, a Campex não carrega tenant, ativos, incidentes, briefing, impacto ou cobertura.</p>
        </div>
        <a class="cx-primary-action" href="/login?next=%2Foperations-view%3Fview%3Dhome">Entrar</a>
      </section>
    </section>
  `;
}

function renderRows(config) {
  const rows = rowsCache.filter(matchesTab).filter(includesSearch);
  head.innerHTML = `<tr>${config.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="${config.columns.length}">${emptyState(config)}</td></tr>`;
  } else {
    body.innerHTML = rows.map((row, index) => `<tr data-row-index="${index}">${config.row(row).map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("");
  }
  const path = window.location.pathname;
  const useGrid = config.card && (viewMode === "grid" || path === "/cameras" || path === "/evidence" || path === "/events");
  grid.style.display = useGrid ? "grid" : "none";
  grid.innerHTML = useGrid ? (rows.length ? rows.map(config.card).join("") : emptyState(config)) : "";
  openEventFromQuery(config, rowsCache);
}

function openEventFromQuery(config, rows) {
  if (config.title !== "Eventos") return;
  const params = new URLSearchParams(window.location.search);
  const eventUuid = params.get("event_uuid");
  const eventId = params.get("event_id") || params.get("id");
  if (!eventUuid && !eventId) return;
  const event = rows.find((item) => item.event_uuid === eventUuid || item.id === eventId);
  if (event) {
    window.history.replaceState({ path: window.location.pathname }, "", window.location.pathname);
    openDrawer(event, config);
  }
}

function renderNotFound(path = window.location.pathname) {
  const config = {
    title: "Página não encontrada",
    heading: "Página não encontrada",
    subtitle: "O endereço acessado não corresponde a nenhuma área da plataforma.",
    columns: ["Mensagem"],
    action: "Voltar para Operação",
    actionHref: "/operations-view",
    emptyTitle: "Página não encontrada",
    emptyDescription: "O endereço acessado não corresponde a nenhuma área da plataforma.",
  };
  document.title = "Página não encontrada | Campex";
  title.textContent = config.title;
  heading.textContent = config.heading;
  subtitle.textContent = `${config.subtitle} (${path})`;
  tableTitle.textContent = config.title;
  tableHint.textContent = "Verifique o endereço ou volte para a Home.";
  cards.innerHTML = [
    `<article><strong>404</strong><span>Rota inválida</span></article>`,
    `<article><strong>Campex</strong><span>Shell carregado</span></article>`,
    `<article><strong>Seguro</strong><span>Nenhuma API foi substituída</span></article>`,
  ].join("");
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  rowsCache = [];
  grid.style.display = "none";
  head.innerHTML = "<tr><th>Mensagem</th></tr>";
  body.innerHTML = `<tr><td>${emptyState(config)}</td></tr>`;
  primaryAction.textContent = "Voltar para Operação";
  primaryAction.onclick = () => { window.location.href = "/operations-view"; };
  document.querySelectorAll("[data-route], .cx-nav a").forEach((link) => {
    link.classList.remove("active");
    link.setAttribute("aria-current", "false");
  });
}

async function openDrawer(row, config) {
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawerContent.innerHTML = "<p>Carregando detalhe...</p>";
  let detailRow = row;
  if (config.title === "Eventos" && row?.id) {
    detailRow = await requestJson(`/eventos/${row.id}/detail`).catch(() => row);
  }
  drawerContent.innerHTML = config.detail ? config.detail(detailRow) : `<h2>${config.title}</h2><pre>${JSON.stringify(detailRow, null, 2)}</pre>`;
  drawer.querySelector("h2")?.setAttribute("id", "workspaceDrawerTitle");
  drawer.focus({ preventScroll: true });
}

async function loadPage(path = window.location.pathname) {
  const key = currentRouteKey();
  const config = routes[key] || routes[path];
  if (!config) {
    renderNotFound(path);
    return;
  }
  document.body.classList.toggle("cx-home-mode", key === "/home-view");
  document.body.classList.toggle("cx-operations-mode", key === "/operations-view");
  document.body.classList.toggle("cx-events-mode", path === "/events");
  document.body.classList.toggle("cx-intelligence-mode", path === "/insights");
  document.body.classList.toggle("cx-reports-mode", path === "/reports");
  if (key !== "/home-view" && key !== "/operations-view" && path !== "/insights" && path !== "/reports") {
    document.querySelector(".cx-panel")?.classList.remove("cx-ops-hide-panel");
  }
  if (config.external) {
    window.location.href = path;
    return;
  }
  rowsCache = [];
  viewMode = "grid";
  closeSidePanels();
  closeDrawer();
  document.querySelectorAll("[data-route], .cx-nav a").forEach((link) => {
    const url = new URL(link.href, window.location.origin);
    const href = link.dataset.route || navigationKeyFromUrl(url);
    const active = activeRouteKey(href) === activeRouteKey(key);
    link.classList.toggle("active", active);
    link.setAttribute("aria-current", active ? "page" : "false");
    const label = link.textContent.trim();
    link.setAttribute("title", label);
    link.setAttribute("aria-label", label);
  });
  document.title = `${config.title} | Campex`;
  title.textContent = path === "/events" ? "Memória operacional" : config.title;
  heading.textContent = config.heading;
  subtitle.textContent = config.subtitle;
  tableTitle.textContent = path === "/events" ? "Eventos registrados" : config.title;
  tableHint.textContent = config.subtitle;
  body.closest("table")?.setAttribute("aria-hidden", "false");
  primaryAction.textContent = config.action || "Nova ação";
  primaryAction.onclick = () => {
    if (config.actionType === "install-edge") {
      openEdgeInstaller();
      return;
    }

    if (config.actionType === "visual-rule") {
      drawer.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
      drawerContent.innerHTML = visualRuleForm();
      drawer.querySelector("h2")?.setAttribute("id", "workspaceDrawerTitle");
      drawer.focus({ preventScroll: true });
      return;
    }
    if (config.actionHref) window.location.href = config.actionHref;
    else loadPage(window.location.pathname);
  };
  cards.innerHTML = usesProductMemoryShell(path) ? "" : [
    `<article><strong id="workspaceCount">—</strong><span>Registros</span></article>`,
    `<article><strong>Local</strong><span>SQLite persistente</span></article>`,
    `<article><strong>Seguro</strong><span>Sem credenciais no navegador</span></article>`,
  ].join("");
  renderTabs(config);
  renderFilters(config);
  try {
    const auth = await authStatus();
    if (!auth.authenticated && !auth.bootstrap && config.endpoint !== "/health") {
      if (key === "/home-view" || key === "/operations-view" || key === "/events" || key === "/insights" || key === "/reports") {
        if (key === "/home-view") renderHomeAuthState();
        else if (key === "/events") renderEventsAuthState();
        else if (key === "/insights") renderIntelligenceAuthState();
        else if (key === "/reports") renderReportsAuthState();
        else renderOperationsAuthState("Operação");
        document.querySelector(".cx-main")?.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      rowsCache = [];
      const workspaceCount = document.querySelector("#workspaceCount");
      if (workspaceCount) workspaceCount.textContent = "—";
      head.innerHTML = `<tr>${config.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
      body.innerHTML = `<tr><td colspan="${config.columns.length}">${loginState(config)}</td></tr>`;
      grid.style.display = "none";
      document.querySelector(".cx-main")?.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    if (config.customRender) {
      await config.customRender(config);
      document.querySelector(".cx-main")?.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const payload = config.load ? await config.load() : await requestJson(config.endpoint);
    let rows = config.transform ? config.transform(payload) : Array.isArray(payload) ? payload : payload.events || payload.deliveries || payload.recipients || payload.machines || [];
    rows = Array.isArray(rows) ? rows : [];
    rowsCache = config.filterRows ? config.filterRows(rows) : rows;
    const workspaceCount = document.querySelector("#workspaceCount");
    if (workspaceCount) workspaceCount.textContent = rowsCache.length;
    renderRows(config);
  } catch (error) {
    body.innerHTML = `<tr><td>Não foi possível carregar: ${error.message}</td></tr>`;
  }
  document.querySelector(".cx-main")?.scrollTo({ top: 0, behavior: "smooth" });
}

function navigateTo(path) {
  const url = new URL(path, window.location.origin);
  const key = navigationKeyFromUrl(url);
  if (!routes[key] && !routes[url.pathname]) {
    window.location.href = path;
    return;
  }
  const route = routes[key] || routes[url.pathname];
  if (route.external) {
    window.location.href = path;
    return;
  }
  const nextPath = `${url.pathname}${url.search}`;
  if (`${window.location.pathname}${window.location.search}` !== nextPath) {
    window.history.pushState({ path: nextPath }, "", nextPath);
  }
  loadPage(url.pathname);
}

tabs.addEventListener("click", (event) => {
  const button = event.target.closest("[data-tab]");
  if (!button) return;
  tabs.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  currentTab = button.dataset.tab;
  if (currentRouteConfig().customRender) {
    operationsSelectedPeriod = operationPeriod();
    loadPage(window.location.pathname);
    return;
  }
  viewMode = currentTab === "lista" ? "list" : currentTab === "grade" ? "grid" : viewMode;
  renderRows(currentRouteConfig());
});

filters.addEventListener("change", (event) => {
  const periodSelect = event.target.closest("#operationsPeriod");
  if (periodSelect) {
    operationsSelectedPeriod = periodSelect.value;
    loadPage(window.location.pathname);
  }
  const stateSelect = event.target.closest("#operationsStateFilter");
  if (stateSelect) {
    operationsSelectedState = stateSelect.value;
    loadPage(window.location.pathname);
  }
  const assetSelect = event.target.closest("#operationsAssetFilter");
  if (assetSelect) {
    operationsSelectedAsset = assetSelect.value;
    loadPage(window.location.pathname);
  }
  const eventsPeriod = event.target.closest("#eventsPeriodFilter");
  if (eventsPeriod) {
    eventsSelectedPeriod = eventsPeriod.value;
    loadPage(window.location.pathname);
  }
  const eventsStatus = event.target.closest("#eventsStatusFilter");
  if (eventsStatus) {
    eventsSelectedStatus = eventsStatus.value;
    loadPage(window.location.pathname);
  }
  const eventsSeverity = event.target.closest("#eventsSeverityFilter");
  if (eventsSeverity) {
    eventsSelectedSeverity = eventsSeverity.value;
    loadPage(window.location.pathname);
  }
  const eventsFamily = event.target.closest("#eventsFamilyFilter");
  if (eventsFamily) {
    eventsSelectedFamily = eventsFamily.value;
    loadPage(window.location.pathname);
  }
});

filters.addEventListener("input", (event) => {
  const eventsContext = event.target.closest("#eventsContextFilter");
  if (eventsContext) {
    eventsContextQuery = eventsContext.value;
    loadPage(window.location.pathname);
  }
});

document.body.addEventListener("click", async (event) => {
  const trace = event.target.closest("[data-event-uuids]");
  if (trace) {
    const uuids = String(trace.dataset.eventUuids || "").split(",").filter(Boolean);
    renderTraceDrawer(uuids);
    return;
  }

  const link = event.target.closest("a[href]");
  if (link) {
    const url = new URL(link.href, window.location.origin);
    const sameOrigin = url.origin === window.location.origin;
    const key = navigationKeyFromUrl(url);
    const route = routes[key] || routes[url.pathname];
    if (sameOrigin && route && !route.external && !link.target && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      navigateTo(`${url.pathname}${url.search}`);
      return;
    }
  }

  const testButton = event.target.closest("[data-test-recipient]");
  if (testButton) {
    testButton.textContent = "Enviando...";
    try {
      await requestJson(`/alert-recipients/${testButton.dataset.testRecipient}/test`, { method: "POST" });
      testButton.textContent = "Enviado";
    } catch (error) {
      testButton.textContent = `Erro`;
    }
    return;
  }
  const eventDetailAction = event.target.closest("[data-event-detail-action]");
  if (eventDetailAction) {
    eventDetailAction.textContent = "Salvando...";
    try {
      await requestJson(`/eventos/${eventDetailAction.dataset.eventId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: eventDetailAction.dataset.eventDetailAction }),
      });
      eventDetailAction.textContent = "Atualizado";
      await loadPage(window.location.pathname);
      closeSidePanels();
      closeDrawer();
    } catch (error) {
      eventDetailAction.textContent = "Erro";
    }
    return;
  }
  const workflowButton = event.target.closest("[data-event-workflow-action]");
  if (workflowButton) {
    const form = workflowButton.closest("[data-event-workflow-form]");
    const status = form?.querySelector("[data-event-workflow-status]");
    const data = new FormData(form);
    const payload = {
      confirmed_cause: String(data.get("confirmed_cause") || "").trim() || null,
      action_taken: String(data.get("action_taken") || "").trim() || null,
      human_notes: String(data.get("human_notes") || "").trim() || null,
    };
    const eventId = workflowButton.dataset.eventId;
    const action = workflowButton.dataset.eventWorkflowAction;
    workflowButton.textContent = "Salvando...";
    try {
      const path = action === "acknowledge"
        ? `/eventos/${eventId}/acknowledge`
        : action === "resolve"
          ? `/eventos/${eventId}/resolve`
          : `/eventos/${eventId}/human-context`;
      const method = action === "save-human" ? "PATCH" : "POST";
      const updated = await requestJson(path, { method, body: JSON.stringify(payload) });
      if (status) status.textContent = "Evento atualizado.";
      drawerContent.innerHTML = eventDetail(updated);
    } catch (error) {
      if (status) status.textContent = `Erro: ${error.message}`;
      workflowButton.textContent = "Erro";
    }
    return;
  }
  const refreshButton = event.target.closest("[data-refresh-workspace]");
  if (refreshButton) {
    await loadPage(window.location.pathname);
    return;
  }
  const ruleForm = event.target.closest("#visualRuleForm");
  if (ruleForm && event.type === "submit") return;
  const row = event.target.closest("[data-row-index]");
  const menu = event.target.closest("[data-open-detail]");
  if (!row && !menu) return;
  const index = row ? Number(row.dataset.rowIndex) : 0;
  const sourceRows = document.body.classList.contains("cx-events-mode")
    ? rowsCache
    : rowsCache.filter(matchesTab).filter(includesSearch);
  await openDrawer(sourceRows[index] || sourceRows[0] || rowsCache[0], currentRouteConfig());
});

document.body.addEventListener("submit", async (event) => {
  const form = event.target.closest("#visualRuleForm");
  if (!form) return;
  event.preventDefault();
  const status = form.querySelector("#visualRuleStatus");
  const data = new FormData(form);
  const payload = {
    nome: data.get("nome"),
    camera_id: data.get("camera_id"),
    tipo_evento: data.get("tipo_evento"),
    regiao_id: data.get("regiao_id") || null,
    tempo_minimo: Number(data.get("tempo_minimo") || 0),
    severidade: data.get("severidade"),
    cooldown_seconds: Number(data.get("cooldown_seconds") || 0),
    alerta_inicio: Boolean(data.get("alerta_inicio")),
    alerta_normalizacao: Boolean(data.get("alerta_normalizacao")),
    condicao: conditionFromForm(data),
    ativo: true,
  };
  status.textContent = "Salvando regra...";
  try {
    await requestJson("/visual-rules", { method: "POST", body: JSON.stringify(payload) });
    status.textContent = "Regra salva.";
    await loadPage("/rules");
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
  } catch (error) {
    status.textContent = `Erro ao salvar: ${error.message}`;
  }
});

drawerClose.addEventListener("click", () => {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
});

search.addEventListener("input", () => renderRows(currentRouteConfig()));
window.addEventListener("popstate", () => loadPage(window.location.pathname));
loadPage();
