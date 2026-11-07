const label = (evidenceType) => evidenceType.replaceAll("_", " ");

const initials = (name) =>
  name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2);

export default function CaseFilePanel({ caseData, error }) {
  if (error) {
    return (
      <aside className="sidebar">
        <h2 className="eyebrow">Case file</h2>
        <p className="error" role="alert">{error}</p>
      </aside>
    );
  }
  if (!caseData) {
    return (
      <aside className="sidebar">
        <h2 className="eyebrow">Case file</h2>
        <p className="muted">Loading…</p>
      </aside>
    );
  }
  return (
    <aside className="sidebar">
      <div className="case-card">
        <p className="eyebrow accent">Active investigation</p>
        <h2>{caseData.name}</h2>
        <p className="muted small">{caseData.location}</p>
      </div>
      <p className="summary">{caseData.summary}</p>

      <h3 className="eyebrow">Subjects</h3>
      <ul className="records">
        {caseData.subjects.map((subject) => (
          <li key={subject.id} className="subject">
            <span className="avatar" aria-hidden="true">{initials(subject.full_name)}</span>
            <div>
              <div className="subject-name">
                <strong>{subject.full_name}</strong>
                <span className="tag">{subject.role}</span>
              </div>
              <p>{subject.notes}</p>
            </div>
          </li>
        ))}
      </ul>

      <h3 className="eyebrow">Evidence</h3>
      <ul className="records">
        {caseData.evidence.map((item) => (
          <li key={item.id}>
            <strong className="capitalize">{label(item.evidence_type)}</strong>
            <p>{item.description}</p>
          </li>
        ))}
      </ul>
    </aside>
  );
}
