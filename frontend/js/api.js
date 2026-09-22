const queryApiBaseUrl = new URLSearchParams(window.location.search).get("api");
const defaultApiBaseUrl = `${window.location.protocol}//${window.location.hostname}:8000/api/v1`;
const API_BASE_URL =
  queryApiBaseUrl || window.CAMPEX_API_BASE_URL || defaultApiBaseUrl;

function apiHeaders(extra = {}) {
  const apiToken = localStorage.getItem("campex.api_token") || "";
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
    ...(apiToken ? { "X-CAMPEX-Token": apiToken } : {}),
    ...extra,
  };
}

function uploadHeaders(extra = {}) {
  const apiToken = localStorage.getItem("campex.api_token") || "";
  return {
    Accept: "application/json",
    ...(apiToken ? { "X-CAMPEX-Token": apiToken } : {}),
    ...extra,
  };
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: apiHeaders(options.headers || {}),
    ...options,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export async function getHealth() {
  return requestJson("/health");
}

export function getRuntimeSettings() {
  return requestJson("/settings/runtime");
}

export function getOperationsSummary() {
  return requestJson("/operations/summary");
}

export function getOperationsDiagnostics() {
  return requestJson("/operations/diagnostics");
}

export function getProductivitySummary() {
  return requestJson("/operations/productivity");
}

export function listEvidence() {
  return requestJson("/operations/evidence");
}

export function listRules() {
  return requestJson("/operations/rules");
}

export function getOperationalTaxonomy() {
  return requestJson("/operations/taxonomy");
}

export function createRule(payload) {
  return requestJson("/operations/rules", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateRule(ruleId, payload) {
  return requestJson(`/operations/rules/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteRule(ruleId) {
  const response = await fetch(`${API_BASE_URL}/operations/rules/${ruleId}`, {
    method: "DELETE",
    headers: apiHeaders(),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
}

export function cleanupEvidence(days = 7) {
  return requestJson("/operations/evidence/cleanup", {
    method: "POST",
    body: JSON.stringify({ days }),
  });
}

export function setupDemo() {
  return requestJson("/operations/demo/setup", { method: "POST" });
}

export function operationsStreamUrl() {
  return `${API_BASE_URL}/operations/stream`;
}

export function simulateRule(payload) {
  return requestJson("/operations/rules/simulate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listInvestigations(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, value);
    }
  });
  return requestJson(`/investigations${query.toString() ? `?${query}` : ""}`);
}

export function createInvestigation(payload) {
  return requestJson("/investigations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateInvestigation(investigationId, payload) {
  return requestJson(`/investigations/${investigationId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteInvestigation(investigationId) {
  const response = await fetch(`${API_BASE_URL}/investigations/${investigationId}`, {
    method: "DELETE",
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
}

export function listCameras() {
  return requestJson("/cameras");
}

export function createCamera(payload) {
  return requestJson("/cameras", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCamera(cameraId, payload) {
  return requestJson(`/cameras/${cameraId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function testCameraSource(payload) {
  return requestJson("/cameras/test-source", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listEvents(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, value);
    }
  });
  return requestJson(`/events${query.toString() ? `?${query}` : ""}`);
}

export function updateEvent(eventId, payload) {
  return requestJson(`/events/${eventId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function eventEvidenceUrl(eventId, variant = "overlay") {
  return `${API_BASE_URL}/events/${eventId}/evidence?variant=${encodeURIComponent(variant)}`;
}

export async function deleteEvent(eventId) {
  const response = await fetch(`${API_BASE_URL}/events/${eventId}`, {
    method: "DELETE",
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
}

export function listZones(cameraId = "") {
  const query = cameraId ? `?camera_id=${encodeURIComponent(cameraId)}` : "";
  return requestJson(`/zones${query}`);
}

export function listMachines(cameraId = "") {
  const query = cameraId ? `?camera_id=${encodeURIComponent(cameraId)}` : "";
  return requestJson(`/machines${query}`);
}

export function createMachine(payload) {
  return requestJson("/machines", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateMachine(machineId, payload) {
  return requestJson(`/machines/${machineId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteMachine(machineId) {
  const response = await fetch(`${API_BASE_URL}/machines/${machineId}`, {
    method: "DELETE",
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
}

export function createZone(payload) {
  return requestJson("/zones", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateZone(zoneId, payload) {
  return requestJson(`/zones/${zoneId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteZone(zoneId) {
  const response = await fetch(`${API_BASE_URL}/zones/${zoneId}`, {
    method: "DELETE",
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
}

export async function deleteCamera(cameraId) {
  const response = await fetch(`${API_BASE_URL}/cameras/${cameraId}`, {
    method: "DELETE",
    headers: apiHeaders(),
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
}

export function testCamera(cameraId) {
  return requestJson(`/cameras/${cameraId}/test`, {
    method: "POST",
  });
}

export function getCameraHealth(cameraId) {
  return requestJson(`/cameras/${cameraId}/health`);
}

export function getCameraDiagnostics(cameraId) {
  return requestJson(`/cameras/${cameraId}/diagnostics`);
}

export function startVision(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/start`, {
    method: "POST",
  });
}

export function restartVision(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/restart`, {
    method: "POST",
  });
}

export function stopVision(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/stop`, {
    method: "POST",
  });
}

export function startMapping(cameraId) {
  return requestJson(`/cameras/${cameraId}/mapping/start`, {
    method: "POST",
  });
}

export function stopMapping(cameraId) {
  return requestJson(`/cameras/${cameraId}/mapping/stop`, {
    method: "POST",
  });
}

export function getVisionStatus(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/status`);
}

export function getVisionObjects(cameraId) {
  return requestJson(`/cameras/${cameraId}/vision/objects`);
}

export function getMappingPoses(cameraId) {
  return requestJson(`/cameras/${cameraId}/mapping/poses`);
}

export function getCameraProductivity(cameraId) {
  return requestJson(`/cameras/${cameraId}/productivity`);
}

export function getStreamInfo(cameraId) {
  return requestJson(`/cameras/${cameraId}/stream/info`);
}

export function cameraStreamUrl(cameraId) {
  return `${API_BASE_URL}/cameras/${cameraId}/stream`;
}

export function cameraVideoUrl(cameraId) {
  return `${API_BASE_URL}/cameras/${cameraId}/video`;
}

export function cameraSnapshotUrl(cameraId) {
  return `${API_BASE_URL}/cameras/${cameraId}/snapshot?t=${Date.now()}`;
}

export async function analyzeVideo(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API_BASE_URL}/videos/analyze`, {
    method: "POST",
    headers: uploadHeaders(),
    body: formData,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
  return response.json();
}

export function listVideoAnalyses() {
  return requestJson("/videos");
}

export function getVideoAnalysisStatus(analysisId) {
  return requestJson(`/videos/${analysisId}/status`);
}

export function uploadedVideoUrl(analysisId) {
  return `${API_BASE_URL}/videos/${analysisId}/video`;
}

export function debugVideoUrl(analysisId) {
  return `${API_BASE_URL}/videos/${analysisId}/debug-video`;
}

export function getNotificationPreferences() {
  return requestJson("/notifications/preferences");
}

export function updateNotificationPreferences(payload) {
  return requestJson("/notifications/preferences", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function testTelegramNotification() {
  return requestJson("/notifications/test/telegram", { method: "POST" });
}

export function testEmailNotification() {
  return requestJson("/notifications/test/email", { method: "POST" });
}

export function sendNotificationReportNow() {
  return requestJson("/notifications/send-report", { method: "POST" });
}

export function listNotificationDeliveries() {
  return requestJson("/notifications/deliveries");
}
