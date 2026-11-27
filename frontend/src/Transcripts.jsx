import { useEffect, useRef, useState } from "react";
import { getTranscript, listTranscripts } from "./api.js";

const startedAt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const subjectName = (interview) => interview.subject_name ?? "Unknown interviewee";

function TranscriptDialog({ caseId, interview, onClose }) {
  const dialog = useRef(null);
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);

  useEffect(() => {
    let active = true;
    getTranscript(caseId, interview.session_id)
      .then((data) => { if (active) setEntries(data.entries); })
      .catch((err) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [caseId, interview.session_id]);

  function close() {
    dialog.current.close();
    onClose();
  }

  return (
    <dialog ref={dialog} className="transcript-dialog" aria-labelledby="transcript-title"
      onCancel={(event) => { event.preventDefault(); close(); }}>
      <header className="em-head">
        <div>
          <h2 id="transcript-title">{subjectName(interview)}</h2>
          <p className="muted small">{startedAt.format(new Date(interview.started_at))} · Interview #{interview.session_id}</p>
        </div>
        <button type="button" className="icon-btn" onClick={close} aria-label="Close transcript">×</button>
      </header>
      {error ? <p className="error" role="alert">{error}</p> : entries ? (
        <ol className="transcript-entries">
          {entries.map((entry) => (
            <li key={entry.id}>
              <span className="eyebrow">{entry.source === "recorded" ? "Recorded" : "Typed"}</span>
              <p>{entry.raw_text}</p>
            </li>
          ))}
        </ol>
      ) : <p className="muted" role="status">Loading transcript…</p>}
    </dialog>
  );
}

export default function Transcripts({ caseId }) {
  const [interviews, setInterviews] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    listTranscripts(caseId)
      .then((rows) => { if (active) setInterviews(rows); })
      .catch((err) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [caseId]);

  if (!interviews.length && !error) return null;

  return (
    <section className="transcripts" aria-labelledby="transcripts-heading">
      <div className="section-head">
        <h2 id="transcripts-heading">Transcripts</h2>
        {!error && <span className="muted small">{interviews.length} interview{interviews.length === 1 ? "" : "s"}</span>}
      </div>
      {error ? <p className="error" role="alert">{error}</p> : (
        <ul className="transcript-list">
          {interviews.map((interview) => (
            <li key={interview.session_id}>
              <button type="button" className="transcript-row" onClick={() => setSelected(interview)}>
                <span>
                  <strong>{subjectName(interview)}</strong>
                  <span className="muted small">{startedAt.format(new Date(interview.started_at))} · Interview #{interview.session_id}</span>
                </span>
                <span className="muted small">{interview.entry_count} {interview.entry_count === 1 ? "entry" : "entries"}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {selected && <TranscriptDialog caseId={caseId} interview={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}
