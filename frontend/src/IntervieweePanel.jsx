import { useState } from "react";
import { addSubject } from "./api.js";

const ROLES = ["Suspect", "Witness", "Victim", "Other"];
const EMPTY = { full_name: "", role: "Witness", notes: "", phone: "", vehicle: "", plate: "", relation: "" };
const initials = (name) => name.split(" ").map((p) => p[0]).join("").slice(0, 2);

// "Who are you interviewing?": pick someone on the case, or add a new person.
export default function IntervieweePanel({ caseData, onPick, onAdded, current, onClose }) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [match, setMatch] = useState(null);

  const people = [...caseData.subjects].sort((a, b) => (a.role !== "Suspect") - (b.role !== "Suspect"));
  const set = (key) => (e) => { setForm((f) => ({ ...f, [key]: e.target.value })); setMatch(null); };

  async function save(event) {
    event.preventDefault();
    const name = form.full_name.trim();
    if (!name) return;
    const existing = caseData.subjects.find((s) => s.full_name.toLowerCase() === name.toLowerCase());
    if (existing && !match) {
      setMatch(existing);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const person = await addSubject(caseData.id, { ...form, full_name: name });
      setForm(EMPTY);
      setAdding(false);
      onAdded(person);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="interviewee" aria-labelledby="who-title">
      <div className="section-head">
        <h2 id="who-title">{current ? "Interviewee" : "Who are you interviewing?"}</h2>
        {onClose && <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">×</button>}
      </div>

      {!adding && (
        <>
          <ul className="person-cards">
            {people.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className={`person-card ${current?.id === s.id ? "selected" : ""}`}
                  onClick={() => onPick(s)}
                >
                  <span className={`avatar ${s.role.toLowerCase()}`} aria-hidden="true">{initials(s.full_name)}</span>
                  <span className="person-card-body">
                    <strong>{s.full_name}</strong>
                    <span className="tag">{s.role}</span>
                    <span className="muted small">{s.notes || "No notes"}</span>
                    {s.plate && !(s.notes ?? "").includes(s.plate) && <span className="muted small">{s.vehicle}{s.plate ? ` · ${s.plate}` : ""}</span>}
                    <span className="muted small">{s.interviews ?? 0} earlier interview{s.interviews === 1 ? "" : "s"}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="ghost full" onClick={() => setAdding(true)}>+ Add person</button>
        </>
      )}

      {adding && (
        <form className="person-form" onSubmit={save}>
          <label>Name<input value={form.full_name} onChange={set("full_name")} autoFocus required /></label>
          <label>Role
            <select value={form.role} onChange={set("role")}>
              {ROLES.map((r) => <option key={r}>{r}</option>)}
            </select>
          </label>
          <label className="span-2">Notes<input value={form.notes} onChange={set("notes")} placeholder="e.g. neighbouring shopkeeper" /></label>
          <details className="span-2">
            <summary>More details (optional)</summary>
            <div className="form-grid">
              <label>Phone<input value={form.phone} onChange={set("phone")} /></label>
              <label>Relation to case<input value={form.relation} onChange={set("relation")} /></label>
              <label>Vehicle<input value={form.vehicle} onChange={set("vehicle")} placeholder="e.g. white Honda Activa" /></label>
              <label>Plate<input value={form.plate} onChange={set("plate")} /></label>
            </div>
          </details>
          {match && (
            <div className="match-note span-2">
              <span><b>{match.full_name}</b> is already on this case.</span>
              <button type="button" className="secondary" onClick={() => { setAdding(false); setMatch(null); onPick(match); }}>
                Interview {match.full_name.split(" ")[0]}
              </button>
            </div>
          )}
          {error && <p className="error span-2">{error}</p>}
          <div className="actions span-2">
            <button type="submit" className="primary" disabled={busy || !form.full_name.trim() || !!match}>Add and select</button>
            <button type="button" className="secondary" onClick={() => { setAdding(false); setMatch(null); }}>Cancel</button>
          </div>
        </form>
      )}
    </section>
  );
}
