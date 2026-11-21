import { useEffect } from "react";
import { assetUrl } from "./api.js";
import { KIND_LABEL, turnLabel } from "./findings.js";

// The opened evidence card, over a blurred backdrop. Closes on ×, Escape or a click outside.
export default function EvidenceModal({ item, onClose, onShowOnTimeline }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop blur" onClick={onClose}>
      <article className="evidence-modal glass" role="dialog" aria-modal="true" aria-label={item.title}
        onClick={(e) => e.stopPropagation()}>
        <header className="em-head">
          <div>
            <p className="eyebrow">{item.kind === "subject" ? item.subtitle
              : item.source === "statement" ? `Added from ${item.providedBy}'s interview`
                : item.source === "upload" ? `Uploaded by ${item.providedBy}` : "Evidence record"}</p>
            <h2 className="capitalize">{item.title}</h2>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close" autoFocus>×</button>
        </header>

        <div className="em-body">
          {item.image && (
            <figure className="em-figure">
              <img src={assetUrl(item.image)} alt={`Illustration: ${item.title}`} />
              <figcaption>{item.imageKind === "generated" ? "Generated from the witness's description · illustrative only, not evidence"
                : item.imageKind === "photo" ? "Photo uploaded during the interview"
                  : "Illustration for the demo, not a real photograph"}</figcaption>
            </figure>
          )}
          <div className="em-text">
            <p>{item.detail}</p>
            {item.metadata && Object.keys(item.metadata).length > 0 && (
              <dl className="meta">
                {Object.entries(item.metadata).map(([k, v]) => (
                  <div key={k}><dt>{k.replaceAll("_", " ")}</dt><dd>{String(v)}</dd></div>
                ))}
              </dl>
            )}
            {item.linked.length > 0 && (
              <section className="em-linked">
                <h3 className="eyebrow">Cited by alibi checks ({item.linked.length})</h3>
                <ul className="linked-list">
                  {item.linked.map((f) => (
                    <li key={f.id}>
                      <span className={`source-chip ${f.kind.toLowerCase()}`}>{KIND_LABEL[f.kind]}</span>
                      <span>{turnLabel(f.claim.turn_index)} · {f.claim.text}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {onShowOnTimeline && (
              <button type="button" className="secondary" onClick={() => { onClose(); onShowOnTimeline(); }}>Show on timeline</button>
            )}
          </div>
        </div>

        {item.items?.length > 0 && (
          <section className="em-items">
            <h3 className="eyebrow">Items ({item.items.length})</h3>
            <ul>
              {item.items.map((it) => (
                <li key={it.id} className="em-item">
                  {it.image && <img src={assetUrl(it.image)} alt={`Illustration: ${it.name}`} />}
                  <div>
                    <strong>{it.name}</strong>
                    <p className="muted small">{it.description}</p>
                    <p className="em-item-facts"><span>{it.weight}</span><span>{it.value}</span></p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
      </article>
    </div>
  );
}
