export default function FollowUps({ questions, onPick, onHover, error, disabled }) {
  if (error) return <p className="muted small">{error}</p>;
  if (!questions || questions.length === 0) return null;
  return (
    <section className="followups" aria-label="Suggested follow-up questions">
      <h3 className="eyebrow">Ask next</h3>
      <ul>
        {questions.map((q) => (
          <li key={q.question}>
            <button
              type="button"
              disabled={disabled}
              className={`followup-chip ${q.from_finding ? "from-finding" : ""}`}
              onClick={() => onPick(q.question)}
              onMouseEnter={() => onHover(q.targets_claim_ids)}
              onMouseLeave={() => onHover([])}
              onFocus={() => onHover(q.targets_claim_ids)}
              onBlur={() => onHover([])}
              title={q.rationale}
            >
              <span>{q.question}</span>
              <small>{q.rationale}</small>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
