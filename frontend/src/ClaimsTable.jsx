import { useState } from "react";
import { API_URL } from "./api.js";

const STATUS_ORDER = ["CONFLICT", "FLAGGED", "CONSISTENT", "PENDING"];

function RouteMetrics({ result }) {
  const hasGap = result.gap_minutes !== undefined;
  return (
    <dl className="metrics">
      <div><dt>Actual</dt><dd>{result.actual_minutes} min</dd></div>
      {hasGap && <div><dt>Claimed</dt><dd>{result.claimed_minutes} min</dd></div>}
      {hasGap && (
        <div>
          <dt>Gap</dt>
          <dd className={result.exceeds_tolerance ? "over" : ""}>
            {result.gap_minutes > 0 ? "+" : ""}{result.gap_minutes} min
          </dd>
        </div>
      )}
      <div><dt>Distance</dt><dd>{result.distance_km} km</dd></div>
      {result.osrm_minutes !== null && <div><dt>OSRM raw</dt><dd>{result.osrm_minutes} min</dd></div>}
      {result.assumed_speed_kmh !== null && <div><dt>Assumed</dt><dd>{result.assumed_speed_kmh} km/h</dd></div>}
    </dl>
  );
}

function ToolTrace({ claim }) {
  const calls = claim.tool_calls ?? claim.details?.tool_calls ?? [];
  if (calls.length === 0) return null;
  const names = [...new Set(calls.map((call) => call.name))];
  const images = calls.filter((call) => call.result?.image_url);
  const routes = calls.filter((call) => call.name === "check_route" && call.result?.actual_minutes !== undefined);
  return (
    <>
      {routes.map((call, index) => <RouteMetrics key={index} result={call.result} />)}
      <div className="tools">
        {names.map((name) => <code key={name}>{name}</code>)}
      </div>
      {images.map((call) => (
        <figure key={call.result.image_url} className="tool-image">
          <img src={`${API_URL}${call.result.image_url}`} alt={call.result.description} />
          <figcaption>Illustrative only, not evidence</figcaption>
        </figure>
      ))}
    </>
  );
}

function Tally({ claims }) {
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

export default function ClaimsTable({ claims }) {
  const [expanded, setExpanded] = useState(new Set());
  if (claims.length === 0) {
    return <p className="muted empty">No claims yet. Submit a statement to check it.</p>;
  }
  return (
    <>
      <Tally claims={claims} />
      <div className="table-wrap">
        <table className="claims">
          <thead>
            <tr>
              <th>Claim</th>
              <th>Type</th>
              <th>Status</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim) => (
              <tr
                key={claim.id}
                className={`row-${claim.status.toLowerCase()} clickable`}
                onClick={() => setExpanded((current) => {
                  const next = new Set(current);
                  next.has(claim.id) ? next.delete(claim.id) : next.add(claim.id);
                  return next;
                })}
              >
                <td>{claim.text}</td>
                <td className="type">{claim.claim_type}</td>
                <td><span className={`badge ${claim.status.toLowerCase()}`}>{claim.status}</span></td>
                <td>
                  {claim.reason}
                  {expanded.has(claim.id) && <ToolTrace claim={claim} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
