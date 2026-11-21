import { useState } from "react";
import { AlibiBanner, ThenVsNow } from "./AlibiAlert.jsx";
import ClaimRows, { Tally } from "./ClaimsTable.jsx";
import FollowUps from "./FollowUps.jsx";
import MapsPanel from "./MapsPanel.jsx";
import ImageExtraction from "./ImageExtraction.jsx";
import { assetUrl } from "./api.js";
import { turnLabel } from "./findings.js";

const routeChecks = (statement) =>
  statement.claims.flatMap((claim) =>
    (claim.details?.tool_calls ?? [])
      .filter((call) => call.name === "check_route" && call.result?.actual_minutes !== undefined)
      .map((call, i) => ({ key: `${claim.id}-${i}`, claim, result: call.result })));

// Everything the checks produce, kept out of the conversation: alerts, follow-ups,
// the maps check, then-vs-now cards, and each claim's verdict.
function AddedRecords({ statements, attachments }) {
  const latest = statements[statements.length - 1];
  const added = [
    ...statements.flatMap((s) => (s.new_records ?? []).map((r) => ({ ...r, fresh: s === latest }))),
    ...attachments.filter((a) => a.evidence).map((a, i, all) => ({ ...a.evidence, fresh: i === all.length - 1 })),
  ];
  if (added.length === 0) return null;
  return (
    <section className="side-section">
      <h3 className="eyebrow">Added to the case file ({added.length})</h3>
      {added.map((r) => (
        <article key={r.id} className={`added-record ${r.fresh ? "fresh" : ""}`}>
          {r.image && <img src={assetUrl(r.image)} alt="" />}
          <div>
            <p><span className="tag">{r.evidence_type.replaceAll("_", " ")}</span></p>
            <p className="small">{r.description}</p>
            <p className="muted small">
              {r.image_kind === "generated" ? "Image generated from the description · not evidence"
                : r.image_kind === "photo" ? "Uploaded photo" : ""}
            </p>
          </div>
        </article>
      ))}
    </section>
  );
}

export default function SidePanel({ statements, attachments = [], sessionId, freshFindingIds, onPickQuestion, onJump }) {
  const [highlighted, setHighlighted] = useState([]);
  const latest = statements[statements.length - 1];
  const findings = statements.flatMap((s) => s.alibi_findings ?? []);
  const claims = statements.flatMap((s) => s.claims);
  // Newest turn first; within a turn, trips that fail the check first.
  const maps = [...statements].reverse().flatMap((s) => routeChecks(s)
    .sort((a, b) => Number(!!b.result.exceeds_tolerance) - Number(!!a.result.exceeds_tolerance))
    .map((m) => ({ ...m, fresh: s === latest })));
  const imageChecks = attachments.filter((a) => a.extraction).reverse();
  const imageFindings = imageChecks.length > 0 && (
    <section className="side-section" aria-label="Image checks" aria-live="polite">
      {imageChecks.map((attachment) => <ImageExtraction key={attachment.id} attachment={attachment} />)}
    </section>
  );

  if (statements.length === 0) {
    return (
      <aside className="side glass" id="findings" aria-label="Findings">
        <h2 className="side-title">Findings</h2>
        {!imageFindings && !attachments.some((a) => a.evidence) && <p className="muted small">
          Each answer is checked against the case records, the person's earlier answers and other people's statements.
          Clashes, maps checks, suggested questions and verdicts appear here.
        </p>}
        {imageFindings}
        <AddedRecords statements={statements} attachments={attachments} />
      </aside>
    );
  }

  return (
    <aside className="side glass" id="findings" aria-label="Findings">
      <div className="section-head">
        <h2 className="side-title">Findings</h2>
        <Tally claims={claims} />
      </div>
      <AlibiBanner findings={latest?.alibi_findings ?? []} pulseKey={latest?.id} />
      <FollowUps questions={latest?.followups} error={latest?.followup_error} onPick={onPickQuestion} onHover={setHighlighted} />

      {imageFindings}
      <AddedRecords statements={statements} attachments={attachments} />

      {maps.length > 0 && (
        <section className="side-section">
          {maps.map((m) => <MapsPanel key={m.key} result={m.result} claimText={m.claim.text} fresh={m.fresh} />)}
        </section>
      )}

      {findings.length > 0 && (
        <section className="side-section">
          <h3 className="eyebrow">Alibi clashes ({findings.length})</h3>
          <div className="tvn-list">
            {[...findings].reverse().map((f) => (
              <ThenVsNow key={f.id} id={`finding-${f.id}`} finding={f} sessionId={sessionId}
                fresh={freshFindingIds.includes(f.id)} onJump={onJump} />
            ))}
          </div>
        </section>
      )}

      <section className="side-section">
        <h3 className="eyebrow">Claims and verdicts</h3>
        {[...statements].reverse().map((s) => (
          <details key={s.id} className="turn-claims" open={s === latest}>
            <summary>{turnLabel(s.turn_index)} · {s.claims.length} claim{s.claims.length === 1 ? "" : "s"}</summary>
            <ClaimRows
              claims={s.claims}
              findings={s.alibi_findings ?? []}
              highlighted={highlighted}
              sessionId={sessionId}
              freshFindingIds={freshFindingIds}
              onJump={onJump}
            />
            {s.alibi_error && <p className="muted small">{s.alibi_error}</p>}
          </details>
        ))}
      </section>
    </aside>
  );
}
