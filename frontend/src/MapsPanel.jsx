// Maps check. The map is a placeholder SVG for now; the numbers are the real route check.
// A later version swaps the SVG for Google Maps and keeps this panel's data.
export default function MapsPanel({ result, claimText, fresh }) {
  const flagged = result.exceeds_tolerance;
  return (
    <article className={`maps-panel ${flagged ? "flagged" : ""} ${fresh ? "fresh" : ""}`}>
      <header>
        <span className="eyebrow">Maps check</span>
        <span className={`map-verdict ${flagged ? "bad" : ""}`}>{flagged ? "Not possible in claimed time" : "Plausible"}</span>
      </header>
      <svg viewBox="0 0 320 150" className="map-svg" role="img"
        aria-label={`Route from ${result.origin} to ${result.destination}, ${result.distance_km} km`}>
        <rect width="320" height="150" rx="10" className="map-bg" />
        {[30, 70, 110].map((y) => <path key={y} d={`M0 ${y} Q 160 ${y + 14} 320 ${y - 6}`} className="map-road" />)}
        {[60, 150, 250].map((x) => <path key={x} d={`M${x} 0 Q ${x + 12} 75 ${x - 8} 150`} className="map-road" />)}
        <path d="M0 128 C 90 118 170 140 320 120" className="map-river" />
        <path d="M54 104 C 110 30, 200 130, 266 46" className="map-route" />
        <g transform="translate(54 104)"><circle r="7" className="map-pin start" /><text y="22" textAnchor="middle">A</text></g>
        <g transform="translate(266 46)"><circle r="7" className="map-pin end" /><text y="-12" textAnchor="middle">B</text></g>
        <text x="310" y="142" textAnchor="end" className="map-note">illustrative map</text>
      </svg>
      <dl className="map-facts">
        <div className="span-2"><dt>A</dt><dd>{result.origin_matched || result.origin}</dd></div>
        <div className="span-2"><dt>B</dt><dd>{result.destination_matched || result.destination}</dd></div>
        <div><dt>Distance</dt><dd>{result.distance_km} km</dd></div>
        <div><dt>Actual</dt><dd>{result.actual_minutes} min</dd></div>
        {result.claimed_minutes !== undefined && <div><dt>Claimed</dt><dd>{result.claimed_minutes} min</dd></div>}
        {result.gap_minutes !== undefined && (
          <div><dt>Gap</dt><dd className={flagged ? "bad" : ""}>{result.gap_minutes > 0 ? "+" : ""}{result.gap_minutes} min</dd></div>
        )}
      </dl>
      <p className="muted small">{claimText}{result.assumed_speed_kmh ? ` · assumes ${result.assumed_speed_kmh} km/h in town` : ""}</p>
    </article>
  );
}
