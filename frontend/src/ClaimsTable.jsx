import { API_URL } from "./api.js";
import FlagPopover, { FindingBody } from "./FlagPopover.jsx";
import { KIND_LABEL, sourceLabel } from "./findings.js";

export const STATUS_ORDER = ["CONFLICT", "FLAGGED", "CONSISTENT", "PENDING"];
const STATUS_ICON = { CONFLICT: "✕", FLAGGED: "!", CONSISTENT: "✓", PENDING: "…" };

function ToolTrace({ claim }) {
  const calls = claim.details?.tool_calls ?? [];
  if (calls.length === 0) return null;
  const names = [...new Set(calls.map((call) => call.name))];
  return (
    <div className="tools">
      {names.map((name) => <code key={name}>{name}</code>)}
    </div>
  );
}

// Generated images stay visible on the claim card, labelled so nobody mistakes them for evidence.
function GeneratedImages({ claim }) {
  const images = (claim.details?.tool_calls ?? []).filter((call) => call.result?.image_url);
  return images.map((call) => (
    <figure key={call.result.image_url} className="tool-image">
      <img src={`${API_URL}${call.result.image_url}`} alt={call.result.description} />
      <figcaption>Generated image of the vehicle as described · illustrative only, not evidence</figcaption>
    </figure>
  ));
}

export function Tally({ claims }) {
  return (
    <ul className="tally" aria-label="Claims by status">
      {STATUS_ORDER.map((status) => {
        const count = claims.filter((claim) => claim.status === status).length;
        if (count === 0) return null;
        return (
          <li key={status} className={`tally-item ${status.toLowerCase()}`}>
            <b>{count}</b> {status}
          </li>
        );
      })}
    </ul>
  );
}

export function StatusBadge({ status }) {
  return (
    <span className={`badge ${status.toLowerCase()}`}>
      <span aria-hidden="true">{STATUS_ICON[status]}</span> {status}
    </span>
  );
}

// Claim rows for one turn. A claim with alibi-check findings gets a red edge and one chip
// per finding, each opening the notched flag popover.
export default function ClaimRows({ claims, findings, highlighted, sessionId, freshFindingIds, onJump }) {
  if (claims.length === 0) return <p className="muted small no-claims">No checkable claims in this turn.</p>;
  return (
    <ul className="claim-rows">
      {claims.map((claim) => {
        const mine = findings.filter((f) => f.claim.id === claim.id);
        const classes = [
          "claim-row", `row-${claim.status.toLowerCase()}`,
          mine.length ? "has-finding" : "", highlighted.includes(claim.id) ? "highlight" : "",
        ];
        return (
          <li key={claim.id} id={`claim-${claim.id}`} className={classes.join(" ")}>
            <div className="claim-main">
              <StatusBadge status={claim.status} />
              <span className="type">{claim.claim_type}</span>
              <p className="claim-text">{claim.text}</p>
            </div>
            {mine.length > 0 && (
              <div className="flag-chips">
                {mine.map((f) => (
                  <FlagPopover
                    key={f.id}
                    autoOpenKey={freshFindingIds.includes(f.id) ? f.id : null}
                    content={<FindingBody finding={f} onJump={onJump} />}
                  >
                    <span className="flag-chip">
                      <span aria-hidden="true">⚠</span> Clashes with {KIND_LABEL[f.kind].toLowerCase()} · {sourceLabel(f, sessionId)}
                    </span>
                  </FlagPopover>
                ))}
              </div>
            )}
            <details className="claim-details">
              <summary>{claim.reason}</summary>
              <ToolTrace claim={claim} />
            </details>
            <GeneratedImages claim={claim} />
          </li>
        );
      })}
    </ul>
  );
}
