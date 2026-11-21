import { KIND_LABEL, sourceLabel, turnLabel } from "./findings.js";

// The text with the clashing words marked; the quote on its own when it is not in the text.
export function Quote({ text, quote }) {
  if (!quote) return <span>{text}</span>;
  const at = text.toLowerCase().indexOf(quote.toLowerCase());
  if (at < 0) {
    return <span>{text} <mark className="clash">{quote}</mark></span>;
  }
  return (
    <span>
      {text.slice(0, at)}
      <mark className="clash">{text.slice(at, at + quote.length)}</mark>
      {text.slice(at + quote.length)}
    </span>
  );
}

export function AlibiBanner({ findings, pulseKey }) {
  if (findings.length === 0) return null;
  const kinds = [...new Set(findings.map((f) => KIND_LABEL[f.kind]))];
  return (
    <div className="alibi-banner" key={pulseKey} role="alert">
      <span className="alibi-banner-icon" aria-hidden="true">!</span>
      <div>
        <strong>Alibi check failed</strong>
        <span>
          {findings.length} clash{findings.length > 1 ? "es" : ""} with {kinds.join(", ").toLowerCase()}
        </span>
      </div>
    </div>
  );
}

export function ThenVsNow({ finding, sessionId, fresh, onJump, id }) {
  const source = finding.source;
  return (
    <article id={id} className={`tvn ${fresh ? "fresh" : ""}`}>
      <header>
        <span className={`source-chip ${finding.kind.toLowerCase()}`}>{KIND_LABEL[finding.kind]}</span>
        <span className={`sev sev-${finding.severity.toLowerCase()}`}>{finding.severity}</span>
      </header>
      <div className="tvn-sides">
        <div className="tvn-side">
          <p className="tvn-who">
            {source.type === "evidence" ? "Case record" : source.speaker}
            <span>{sourceLabel(finding, sessionId)}</span>
          </p>
          <p className="tvn-text"><Quote text={source.text} quote={finding.prior_quote} /></p>
        </div>
        <span className="tvn-vs" aria-hidden="true">vs</span>
        <div className="tvn-side now">
          <p className="tvn-who">
            {finding.claim.speaker}
            <span>{turnLabel(finding.claim.turn_index)} · now</span>
          </p>
          <p className="tvn-text"><Quote text={finding.claim.text} quote={finding.new_quote} /></p>
        </div>
      </div>
      <footer>
        <p>{finding.explanation}</p>
        {onJump && <button type="button" className="link-btn" onClick={() => onJump(finding)}>Show source →</button>}
      </footer>
    </article>
  );
}
