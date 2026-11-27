import { useState } from "react";
import EvidenceCard from "./EvidenceCard.jsx";
import EvidenceModal from "./EvidenceModal.jsx";
import Transcripts from "./Transcripts.jsx";
import VeritasLoader from "./VeritasLoader.jsx";

const label = (evidenceType) => evidenceType.replaceAll("_", " ");
const initials = (name) => name.split(" ").map((p) => p[0]).join("").slice(0, 2);

// Card data for evidence records, shared by the case file page and the interview drawer.
export function evidenceCards(caseData, findings) {
  return caseData.evidence.map((e) => ({
    key: `e${e.id}`, kind: "evidence", evidence_type: e.evidence_type, title: label(e.evidence_type),
    subtitle: e.source === "statement" ? `From ${e.provided_by ? `${e.provided_by}'s` : "an"} interview${e.metadata.time ? ` · ${e.metadata.time}` : ""}`
      : e.source === "upload" ? `Shown by ${e.provided_by ?? "a witness"}`
        : e.items?.length ? `${e.items.length} items` : e.metadata.time ? `Record · ${e.metadata.time}` : "Record",
    source: e.source, imageKind: e.image_kind, providedBy: e.provided_by,
    detail: e.description, metadata: e.metadata, image: e.image, items: e.items ?? [], timelineId: `e${e.id}`,
    linked: findings.filter((f) => f.source.type === "evidence" && f.source.id === e.id),
  }));
}

export default function CaseFile({ caseData, error, findings, onStartInterview, onShowOnTimeline }) {
  const [open, setOpen] = useState(null);
  if (error) return <main className="page"><p className="error" role="alert">{error}</p></main>;
  if (!caseData) return <main className="page center-load"><VeritasLoader size={0.6} label="Loading case" /></main>;

  const records = evidenceCards(caseData, findings);
  const current = records.find((r) => r.key === open);

  return (
    <main className="page case-file">
      <section className="case-hero">
        <div>
          <p className="eyebrow">Case {caseData.id}</p>
          <h1>{caseData.name}</h1>
          <p className="muted">{caseData.location}</p>
          {caseData.incident_start && (
            <p className="incident-pill">Incident window {caseData.incident_start}–{caseData.incident_end}</p>
          )}
        </div>
        <p className="case-summary">{caseData.summary}</p>
      </section>

      <div className="case-cols">
        <section className="panel">
          <div className="section-head">
            <h2>Evidence</h2>
            <span className="muted small">{records.length} records · click a card to open it</span>
          </div>
          {records.length === 0 ? (
            <p className="muted empty-note">No records on this case yet.</p>
          ) : (
            <div className="ecard-grid wide">
              {records.map((item) => (
                <EvidenceCard
                  key={item.key}
                  item={item}
                  cited={item.linked.length}
                  linkedCount={item.linked.length}
                  active={item.key === open}
                  onAction={(action) => (action === "timeline" ? onShowOnTimeline(item.timelineId) : setOpen(item.key))}
                />
              ))}
            </div>
          )}
          <Transcripts key={caseData.id} caseId={caseData.id} />
        </section>

        <section className="panel">
          <div className="section-head">
            <h2>People involved</h2>
            <span className="muted small">{caseData.subjects.length}</span>
          </div>
          {caseData.subjects.length === 0 ? (
            <p className="muted empty-note">Nobody is on this case yet. Add people from the interview page.</p>
          ) : (
            <ul className="people-list">
              {caseData.subjects.map((s) => (
                <li key={s.id} className="person-row">
                  <span className={`avatar ${s.role.toLowerCase()}`} aria-hidden="true">{initials(s.full_name)}</span>
                  <div className="person-info">
                    <p><strong>{s.full_name}</strong> <span className="tag">{s.role}</span></p>
                    <p className="muted small">{[s.notes, s.plate && !(s.notes ?? "").includes(s.plate) && `${s.vehicle ?? ""} · ${s.plate}`].filter(Boolean).join(" · ")}</p>
                    <p className="muted small">{s.interviews} interview{s.interviews === 1 ? "" : "s"}</p>
                  </div>
                  <button type="button" className="secondary" onClick={() => onStartInterview(s)}>Interview</button>
                </li>
              ))}
            </ul>
          )}
          <button type="button" className="ghost full" onClick={() => onStartInterview(null)}>Open interview page</button>
        </section>
      </div>

      {current && (
        <EvidenceModal item={current} onClose={() => setOpen(null)}
          onShowOnTimeline={() => onShowOnTimeline(current.timelineId)} />
      )}
    </main>
  );
}
