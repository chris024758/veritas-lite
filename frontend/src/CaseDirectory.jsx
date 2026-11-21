import { useEffect, useState } from "react";
import { listCases } from "./api.js";
import { casePath } from "./router.js";
import VeritasLoader from "./VeritasLoader.jsx";

const when = (iso) => (iso ? new Date(iso).toLocaleDateString() : "No interviews yet");

export function useCases() {
  const [cases, setCases] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    listCases().then(setCases).catch((e) => setError(e.message));
  }, []);
  return { cases, error };
}

export default function CaseDirectory() {
  const { cases, error } = useCases();
  return (
    <main className="page directory">
      <header className="page-head">
        <p className="eyebrow">Case directory</p>
        <h1>Cases</h1>
        <p className="muted">Choose a case to open its file, interview someone, or explore its timeline.</p>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {!cases && !error && <div className="center-load"><VeritasLoader size={0.6} label="Loading cases" /></div>}
      {cases && (
        <ul className="case-grid">
          {cases.map((c) => (
            <li key={c.id}>
              <a className="case-card" href={casePath(c.id)}>
                <span className="case-card-top">
                  <span className="case-id">{c.id}</span>
                  <span className="status-pill">{c.status}</span>
                </span>
                <strong>{c.name}</strong>
                <span className="muted small">{c.location}</span>
                <span className="case-stats">
                  <span><b>{c.people}</b> people</span>
                  <span><b>{c.evidence}</b> records</span>
                  <span><b>{c.interviews}</b> interviews</span>
                </span>
                <span className="muted small">Last activity: {when(c.last_activity)}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
