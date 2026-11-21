import { useState } from "react";
import { evidenceCards } from "./CaseFile.jsx";
import EvidenceCard from "./EvidenceCard.jsx";
import EvidenceModal from "./EvidenceModal.jsx";

// The case file as a collapsible drawer beside the interview. Cards open in the same pop-up
// as on the case file page.
export default function CaseFilePanel({ caseData, error, findings, collapsed, onToggle, onShowOnTimeline }) {
  const [open, setOpen] = useState(null);

  if (error || !caseData) {
    return (
      <aside className="sidebar">
        <h2 className="eyebrow">Case file</h2>
        {error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}
      </aside>
    );
  }
  if (collapsed) {
    return (
      <aside className="sidebar collapsed">
        <button type="button" className="icon-btn" onClick={onToggle} aria-label="Show case file" title="Case file">»</button>
      </aside>
    );
  }

  const items = evidenceCards(caseData, findings);
  const current = items.find((i) => i.key === open);

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <p className="eyebrow accent">Case file</p>
        <button type="button" className="icon-btn" onClick={onToggle} aria-label="Hide case file">«</button>
      </div>
      <h2 className="case-name">{caseData.name}</h2>
      <p className="muted small">{caseData.location}</p>
      {caseData.incident_start && (
        <p className="incident-pill">Incident window {caseData.incident_start}–{caseData.incident_end}</p>
      )}
      <p className="summary">{caseData.summary}</p>

      <h3 className="eyebrow">Evidence</h3>
      <div className="ecard-grid">
        {items.map((item) => (
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
      {current && (
        <EvidenceModal item={current} onClose={() => setOpen(null)}
          onShowOnTimeline={() => onShowOnTimeline(current.timelineId)} />
      )}
    </aside>
  );
}
