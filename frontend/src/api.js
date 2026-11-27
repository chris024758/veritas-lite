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

function sendJson(method, path, data) {
  return request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
const postJson = (path, data) => sendJson("POST", path, data);

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

export const submitStatement = (sessionId, text, segmentId, requestId) =>
  postJson(`/sessions/${sessionId}/statements`, {
    text, transcript_segment_id: segmentId, request_id: requestId,
  });

export const saveQuestion = (sessionId, text) =>
  postJson(`/sessions/${sessionId}/questions`, { text });

export const listTranscripts = (caseId) => request(`/cases/${caseId}/transcripts`);

export const getTranscript = (caseId, sessionId) => request(`/cases/${caseId}/transcripts/${sessionId}`);

// Speech-to-text saves the original text and returns it for review.
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
