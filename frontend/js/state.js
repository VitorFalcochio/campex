export const routes = {
  dashboard: {
    title: "Painel",
    message: "Resumo operacional de câmeras, eventos, zonas e investigações.",
  },
  wall: {
    title: "Mural",
    message: "Monitoramento operacional de múltiplas câmeras.",
  },
  live: {
    title: "Ao vivo",
    message: "Monitoramento ao vivo de uma camera com Vision overlay.",
  },
  "video-analysis": {
    title: "Análise MP4",
    message: "Upload e interpretação operacional de vídeo gravado.",
  },
  events: {
    title: "Eventos",
    message: "Fila operacional de eventos detectados pelo CAMPEX.",
  },
  productivity: {
    title: "Produtividade",
    message: "Sinais objetivos de produtividade operacional, máquinas e comportamento.",
  },
  investigations: {
    title: "Investigações",
    message: "Workspace de apuracao e acompanhamento de incidentes.",
  },
  cameras: {
    title: "Câmeras",
    message: "Gerenciamento de fontes de camera.",
  },
  zones: {
    title: "Áreas & zonas",
    message: "Configuracao espacial de areas e zonas por camera.",
  },
  machines: {
    title: "Máquinas",
    message: "Mapeamento de ativos operacionais por câmera.",
  },
  rules: {
    title: "Regras",
    message: "Regras operacionais que transformam observacoes em eventos.",
  },
  settings: {
    title: "Configurações",
    message: "Configuracoes de runtime e preferencias locais.",
  },
  evidence: {
    title: "Evidências",
    message: "Biblioteca de snapshots e mídias associados aos eventos.",
  },
  diagnostics: {
    title: "Diagnóstico",
    message: "Saúde local do banco, visão, câmeras e regras.",
  },
};

export function currentRoute() {
  const route = window.location.hash.replace("#", "");
  return routes[route] ? route : "dashboard";
}
