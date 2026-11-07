import { useRef, useState } from "react";
import { startSession, submitAudio, submitStatement } from "./api.js";
import ClaimsTable from "./ClaimsTable.jsx";

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}

export default function InterviewPanel({ caseId, caseData }) {
  const [sessionId, setSessionId] = useState(null);
  const [text, setText] = useState("");
  const [statements, setStatements] = useState([]);
  const [busy, setBusy] = useState(null);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const recorderRef = useRef(null);

  const subject = caseData?.subjects.find((s) => s.role === "Suspect") ?? caseData?.subjects[0];

  async function ensureSession() {
    if (sessionId !== null) return sessionId;
    const { session_id } = await startSession(caseId, subject.full_name);
    setSessionId(session_id);
    return session_id;
  }

  async function runTurn(label, submit) {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      const id = await ensureSession();
      return await submit(id);
    } catch (e) {
      setError(e.message);
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const statement = text.trim();
    if (!statement) return;
    const result = await runTurn("Checking statement…", (id) => submitStatement(id, statement));
    if (result) {
      setStatements((prev) => [...prev, result]);
      setText("");
      if (result.claims.length === 0) setNotice("No checkable claims in that statement.");
    }
  }

  async function sendClip(blob) {
    const result = await runTurn("Transcribing and checking clip…", (id) => submitAudio(id, blob));
    if (!result) return;
    if (!result.transcript) {
      setNotice("No speech detected in that clip.");
      return;
    }
    setStatements((prev) => [...prev, result]);
    if (result.claims.length === 0) setNotice("No checkable claims in that clip.");
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current.stop();
      setRecording(false);
      return;
    }
    setError(null);
    setNotice(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const chunks = [];
      recorder.ondataavailable = (event) => chunks.push(event.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        sendClip(new Blob(chunks, { type: recorder.mimeType }));
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch (e) {
      setError(`Microphone unavailable: ${e.message}`);
    }
  }

  const claims = statements.flatMap((statement) => statement.claims);
  const disabled = busy !== null || !caseData;

  return (
    <main className="workspace">
      <section className="card">
        <div className="card-head">
          <h2>Interview</h2>
          {subject && (
            <span className="muted small">
              Subject <strong className="subject-inline">{subject.full_name}</strong>
            </span>
          )}
        </div>

        <h3 className="eyebrow">Transcript</h3>
        {statements.length === 0 ? (
          <p className="muted empty">No statements yet.</p>
        ) : (
          <ol className="transcript">
            {statements.map((statement) => (
              <li key={statement.id}>
                <span className="turn">T{String(statement.turn_index + 1).padStart(2, "0")}</span>
                <p>{statement.text}</p>
              </li>
            ))}
          </ol>
        )}

        <form onSubmit={handleSubmit}>
          <label htmlFor="statement" className="eyebrow">Statement</label>
          <textarea
            id="statement"
            rows={4}
            placeholder="Type what the subject said, or record a short clip."
            value={text}
            onChange={(event) => setText(event.target.value)}
            disabled={busy !== null}
          />
          <div className="actions">
            <button type="submit" className="primary" disabled={disabled || recording || !text.trim()}>
              Submit
            </button>
            <button
              type="button"
              onClick={toggleRecording}
              disabled={disabled}
              className={recording ? "secondary recording" : "secondary"}
            >
              {recording ? <span className="rec-dot" aria-hidden="true" /> : <MicIcon />}
              {recording ? "Stop and send" : "Record clip"}
            </button>
            {busy && (
              <span className="status" role="status">
                <span className="spinner" aria-hidden="true" />
                {busy}
              </span>
            )}
            {recording && <span className="status" role="status">Recording…</span>}
          </div>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
        {notice && <p className="notice" role="status">{notice}</p>}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Claims</h2>
        </div>
        <ClaimsTable claims={claims} />
      </section>
    </main>
  );
}
