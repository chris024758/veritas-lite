import { Quote } from "./AlibiAlert.jsx";
import { assetUrl } from "./api.js";
import { StatusBadge, STATUS_ORDER } from "./ClaimsTable.jsx";
import VeritasLoader from "./VeritasLoader.jsx";
import { KIND_LABEL, turnLabel } from "./findings.js";

const when = (iso) => (iso ? new Date(iso).toLocaleString() : "");

function evidenceLine(item) {
  const r = item.result ?? {};
  if (item.tool === "check_route" && r.actual_minutes !== undefined) {
    return `Route ${r.origin} → ${r.destination}: ${r.actual_minutes} min actual${r.claimed_minutes !== undefined ? ` vs ${r.claimed_minutes} claimed` : ""}, ${r.distance_km} km`;
  }
  if (item.tool === "search_case_file") {
    const hits = (r.evidence ?? []).map((e) => e.evidence_type.replaceAll("_", " "));
    return `Case file: ${hits.length ? hits.join(", ") : "no matching record"}`;
  }
  if (item.tool === "web_search") return `Web: ${r.answer ?? r.error ?? ""}`;
  return item.tool;
}

function Report({ report, snapshot }) {
  const s = report.summary;
  return (
    <article className="report-doc">
      <header className="report-head">
        <div>
          <p className="report-kicker">VERITAS · Interview report</p>
          <h1>{report.case.name}</h1>
          <p>Case {report.case.id} · {report.case.location}</p>
        </div>
        <dl>
          <div><dt>Subject</dt><dd>{report.subject ? `${report.subject.full_name} (${report.subject.role})` : "Unknown"}</dd></div>
          <div><dt>Started</dt><dd>{when(report.started_at)}</dd></div>
          <div><dt>Ended</dt><dd>{when(report.ended_at)}</dd></div>
        </dl>
      </header>

      <section>
        <h2>Summary</h2>
        {s ? (
          <>
            <p className="report-overview">{s.overview}</p>
            <div className="report-cols">
              {[["Key findings", s.key_findings], ["Unresolved", s.unresolved], ["Next steps", s.next_steps]].map(([title, items]) => (
                <div key={title}>
                  <h3>{title}</h3>
                  <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="muted">{report.summary_error}</p>
        )}
        <ul className="tally report-tally">
          {STATUS_ORDER.map((status) => report.tally[status] > 0 && (
            <li key={status} className={`tally-item ${status.toLowerCase()}`}><b>{report.tally[status]}</b> {status}</li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Alibi-check findings ({report.alibi_findings.length})</h2>
        {report.alibi_findings.length === 0 ? <p className="muted">None.</p> : (
          <ol className="report-findings">
            {report.alibi_findings.map((f) => (
              <li key={f.id}>
                <p className="report-finding-head">
                  <span className={`source-chip ${f.kind.toLowerCase()}`}>{KIND_LABEL[f.kind]}</span>
                  <b>{f.severity}</b> · {turnLabel(f.claim.turn_index)}
                </p>
                <p><b>Said:</b> <Quote text={f.claim.text} quote={f.new_quote} /></p>
                <p><b>{f.source.type === "evidence" ? "Record" : f.source.speaker}:</b> <Quote text={f.source.text} quote={f.prior_quote} /></p>
                <p className="muted">{f.explanation}</p>
              </li>
            ))}
          </ol>
        )}
      </section>

      {snapshot && (
        <section className="report-snapshot">
          <h2>Timeline</h2>
          <img src={snapshot} alt="Snapshot of the 3D case timeline" />
        </section>
      )}

      <section>
        <h2>Claims and verdicts</h2>
        {report.statements.map((st) => (
          <div key={st.turn_index} className="report-turn">
            <p className="report-turn-text"><b>{turnLabel(st.turn_index)}</b> {st.text}</p>
            <table className="report-table">
              <tbody>
                {st.claims.map((c) => (
                  <tr key={c.id}>
                    <td><StatusBadge status={c.status} /></td>
                    <td>
                      <p>{c.text}</p>
                      <p className="muted small">{c.reason}</p>
                      {c.evidence.length > 0 && (
                        <ul className="report-evidence">{c.evidence.map((e, i) => <li key={i}>{evidenceLine(e)}</li>)}</ul>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </section>

      {report.attachments?.length > 0 && (
        <section className="report-attachments">
          <h2>Images added during the interview</h2>
          <ul>
            {report.attachments.map((a) => (
              <li key={a.url}>
                <img src={assetUrl(a.url)} alt={a.caption || a.original_name || "Added image"} />
                <span>{a.caption || a.original_name} · after {turnLabel(Math.max(a.after_turn - 1, 0))}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {report.open_followups.length > 0 && (
        <section>
          <h2>Open follow-ups</h2>
          <ul>{report.open_followups.map((q) => <li key={q.question}>{q.question}</li>)}</ul>
        </section>
      )}
      <footer className="report-foot">Generated by VERITAS-Lite. Illustrative images are excluded; verdicts cite the tool results they relied on.</footer>
    </article>
  );
}

// Opens over the interview page once the interview has ended. Printing shows only the report.
export default function ReportPanel({ report, busy, error, onGenerate, onClose, snapshot, docxUrl }) {
  return (
    <div className="report-overlay" role="dialog" aria-modal="true" aria-label="Interview report">
      <div className="report-actions no-print">
        <strong>Interview report</strong>
        <span className="spacer" />
        {report && <button type="button" className="secondary" onClick={onGenerate} disabled={busy}>Regenerate</button>}
        {report && <button type="button" className="secondary" onClick={() => window.print()}>Export PDF</button>}
        {report && <a className="primary" href={docxUrl} download>Download .docx</a>}
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close report">×</button>
      </div>
      <div className="report-scroll">
        {error && <p className="error" role="alert">{error}</p>}
        {busy && (
          <div className="report-loading" role="status">
            <VeritasLoader size={0.9} label="Generating report" />
            <p>Summarising the interview…</p>
          </div>
        )}
        {!busy && !report && !error && (
          <div className="report-loading">
            <button type="button" className="primary big" onClick={onGenerate}>Generate report</button>
          </div>
        )}
        {report && !busy && <Report report={report} snapshot={snapshot} />}
        {report && !snapshot && <p className="muted small no-print report-hint">Open the Timeline view once to include a timeline picture.</p>}
      </div>
    </div>
  );
}
