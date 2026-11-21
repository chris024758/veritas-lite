import { useState } from "react";
import { assetUrl, generateIllustration, reviewIllustration } from "./api.js";

export default function ImageGenPanel({ record, sourceText, onChange }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const preview = record.illustration_preview;

  async function run(label, action) {
    if (busy) return;
    setBusy(label);
    setError(null);
    try {
      onChange(await action());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="illustration-review" aria-label="Illustration review">
      <h4 className="eyebrow">Suggested image prompt</h4>
      <p className="small">{record.illustration_prompt}</p>
      {sourceText && <details className="small muted">
        <summary>Source statement</summary>
        <p>{sourceText}</p>
      </details>}
      {preview ? (
        <>
          <figure className="image-gen-result">
            <img src={assetUrl(preview)} alt="Draft illustration based on the interview statement" />
            <figcaption className="muted">Draft illustration for review. Approval adds it to the case record as an illustration.</figcaption>
          </figure>
          <div className="actions">
            <button type="button" className="primary" disabled={!!busy}
              onClick={() => run("Approving…", () => reviewIllustration(record.session_id, record.id, preview, true))}>
              Approve illustration
            </button>
            <button type="button" className="secondary" disabled={!!busy}
              onClick={() => run("Discarding…", () => reviewIllustration(record.session_id, record.id, preview, false))}>
              Discard preview
            </button>
          </div>
        </>
      ) : (
        <button type="button" className="secondary" disabled={!!busy}
          onClick={() => run("Generating preview…", () => generateIllustration(record.session_id, record.id))}>
          Generate preview
        </button>
      )}
      {busy && <p className="muted small" role="status">{busy}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
