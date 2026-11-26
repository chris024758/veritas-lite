const defaultApiUrl = import.meta.env.DEV
  ? `http://${window.location.hostname}:8018`
  : window.location.origin;
export const API_URL = (import.meta.env.VITE_API_URL || defaultApiUrl).replace(/\/+$/, "");

async function request(path, options) {
  let response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, credentials: "include" });
  } catch {
    throw new Error(`Cannot reach the backend at ${API_URL}.`);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !["/auth/login", "/auth/session"].includes(path)) {
      window.dispatchEvent(new Event("veritas-session-expired"));
    }
    const detail = typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return body;
}

function sendJson(method, path, data) {
  return request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
const postJson = (path, data) => sendJson("POST", path, data);

export const checkSession = () => request("/auth/session");
export const login = (username, password) => postJson("/auth/login", { username, password });
export const logout = () => request("/auth/logout", { method: "POST" });

export const generateIllustration = (sessionId, target, id) =>
  request(`/sessions/${sessionId}/${target}/${id}/illustration`, { method: "POST" });

export const reviewIllustration = (sessionId, target, id, preview, approve) =>
  postJson(`/sessions/${sessionId}/${target}/${id}/illustration/review`, { preview, approve });

export const listCases = () => request("/cases");

export const getCase = (caseId) => request(`/cases/${caseId}`);

export const addSubject = (caseId, person) => postJson(`/cases/${caseId}/subjects`, person);

export const updateSubject = (subjectId, changes) => sendJson("PATCH", `/subjects/${subjectId}`, changes);

export const startSession = (caseId, subjectId) =>
  postJson("/sessions/start", { case_id: caseId, subject_id: subjectId });

export const submitStatement = (sessionId, text) =>
  postJson(`/sessions/${sessionId}/statements`, { text });

// Speech-to-text only: the text comes back for review and nothing is checked yet.
export function transcribe(sessionId, blob) {
  const form = new FormData();
  form.append("audio", blob, "clip.webm");
  return request(`/sessions/${sessionId}/transcribe`, { method: "POST", body: form });
}

export function addAttachment(sessionId, file, caption) {
  const form = new FormData();
  form.append("image", file, file.name);
  if (caption) form.append("caption", caption);
  return request(`/sessions/${sessionId}/attachments`, { method: "POST", body: form });
}

export const extractAttachment = (sessionId, attachmentId) =>
  request(`/sessions/${sessionId}/attachments/${attachmentId}/extract`, { method: "POST" });

export const assetUrl = (path) => (path ? `${API_URL}${path}` : null);

export const getTimeline = (caseId) => request(`/cases/${caseId}/timeline`);

export const endSession = (sessionId) => postJson(`/sessions/${sessionId}/end`, {});

export const generateReport = (sessionId) => postJson(`/sessions/${sessionId}/report`, {});

export const reportDocxUrl = (sessionId) => `${API_URL}/sessions/${sessionId}/report.docx`;
