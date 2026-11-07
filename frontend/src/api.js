export const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8018";

async function request(path, options) {
  let response;
  try {
    response = await fetch(`${API_URL}${path}`, options);
  } catch {
    throw new Error(`Cannot reach the backend at ${API_URL}.`);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return body;
}

function postJson(path, data) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export const getCase = (caseId) => request(`/cases/${caseId}`);

export const startSession = (caseId, subjectName) =>
  postJson("/sessions/start", { case_id: caseId, subject_name: subjectName });

export const submitStatement = (sessionId, text) =>
  postJson(`/sessions/${sessionId}/statements`, { text });

export function submitAudio(sessionId, blob) {
  const form = new FormData();
  form.append("audio", blob, "clip.webm");
  return request(`/sessions/${sessionId}/audio`, { method: "POST", body: form });
}
