export function eventVerdict(verified) {
  if (verified === true) return "True · Event confirmed";
  if (verified === false) return "False · Event details contradicted";
  return "Unverified · Inconclusive";
}

export default function ImageExtraction({ attachment }) {
  const result = attachment.extraction;
  const { event, event_verification: check } = result;
  const flagged = check?.verified === false;
  const advertised = event && [event.date, event.time, event.venue, event.city].filter(Boolean).join(" · ");

  return (
    <article id={`image-finding-${attachment.id}`} tabIndex={-1}
      className={`maps-panel image-finding${flagged ? " flagged" : ""}`}>
      <header>
        <h3 className="eyebrow">Image check</h3>
        <span className={`map-verdict${flagged ? " bad" : ""}`}>
          {check ? eventVerdict(check.verified) : "Details extracted"}
        </span>
      </header>
      <p className="muted small">{attachment.caption || attachment.original_name || "Interview image"}</p>
      {check && (
        <>
          <h3>{event.title}</h3>
          {advertised && <p className="muted small">{advertised}</p>}
          <p className="muted small">{check.reason}</p>
          {check.sources.length > 0 && <ul className="small" aria-label="Web sources">
            {check.sources.map((source) => (
              <li key={source.uri}><a href={source.uri} target="_blank" rel="noopener noreferrer">{source.title}</a></li>
            ))}
          </ul>}
        </>
      )}
      <details className="image-finding-details small" open={check ? undefined : true}>
        <summary>Extracted details</summary>
        <p className="muted small">AI-generated draft · Verify against the original image</p>
        <h3>Visible text</h3><p className="extraction-text">{result.transcribed_text || "No readable text found."}</p>
        <h3>Observations</h3>{result.observations.length ? <ul>{result.observations.map((v, i) => <li key={i}>{v}</li>)}</ul> : <p>None reported.</p>}
        <h3>Uncertainties</h3>{result.uncertainties.length ? <ul>{result.uncertainties.map((v, i) => <li key={i}>{v}</li>)}</ul> : <p>None reported.</p>}
      </details>
    </article>
  );
}
