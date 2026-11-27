// Layered hover card adapted from Uiverse.io by Smit-Prajapati: the corner boxes slide in on
// hover (or focus) and each one is an action. The original's social icons are replaced.
import { useEffect, useState } from "react";
import { assetUrl } from "./api.js";

const ICONS = {
  witness: <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0" />,
  suspect: <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0M4 4l16 16" />,
  lock: <path d="M7 11V8a5 5 0 0 1 10 0v3M5 11h14v9H5z" />,
  cabinet: <path d="M4 4h16v16H4zM4 12h16M10 8h4M10 16h4" />,
  claim: <path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6" />,
  record: <path d="M6 3h12v18H6zM9 8h6M9 12h6M9 16h4" />,
};

export const iconFor = (item) =>
  item.role === "Witness" ? "witness" : item.role === "Suspect" ? "suspect"
    : /lock|shutter/.test(item.evidence_type ?? "") ? "lock"
      : /cabinet/.test(item.evidence_type ?? "") ? "cabinet"
        : /claim|insurance/.test(item.evidence_type ?? "") ? "claim" : "record";

export function Glyph({ name, className = "" }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

const ACTIONS = [
  { key: "view", label: "View record", path: <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" /> },
  { key: "timeline", label: "Show on timeline", path: <path d="M3 12h18M7 8v8M12 6v12M17 9v6" /> },
  { key: "linked", label: "Linked claims", path: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /> },
];

export default function EvidenceCard({ item, cited, linkedCount, onAction, active }) {
  const [burst, setBurst] = useState(false);
  useEffect(() => {
    if (!cited) return undefined;
    setBurst(true);
    const t = setTimeout(() => setBurst(false), 2000);
    return () => clearTimeout(t);
  }, [cited]);

  return (
    <div
      className={`ecard ${item.image ? "has-img" : ""} ${cited ? "cited" : ""} ${burst ? "burst" : ""} ${active ? "active" : ""}`}
      tabIndex={0}
      role="button"
      aria-label={`${item.title}. ${item.subtitle}. Open details`}
      onClick={(e) => { if (!e.target.closest(".ebox")) onAction("view", item); }}
      onKeyDown={(e) => { if (e.key === "Enter" && e.target === e.currentTarget) onAction("view", item); }}
    >
      <div className="ecard-bg" />
      {item.image && <img className="ecard-img" src={assetUrl(item.image)} alt="" aria-hidden="true" />}
      <div className="ecard-logo">
        <Glyph name={iconFor(item)} className="ecard-glyph" />
        <span className="ecard-title">{item.title}</span>
        <span className="ecard-sub">{item.subtitle}</span>
      </div>
      {ACTIONS.map((action, i) => (
        <button
          key={action.key}
          type="button"
          className={`ebox ebox${i + 1}`}
          aria-label={action.label}
          title={action.key === "linked" ? `${action.label} (${linkedCount})` : action.label}
          onClick={() => onAction(action.key, item)}
        >
          <svg viewBox="0 0 24 24" className="ebox-icon" fill="none" stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{action.path}</svg>
          {action.key === "linked" && linkedCount > 0 && <span className="ebox-count">{linkedCount}</span>}
        </button>
      ))}
      <div className="ebox ebox4" aria-hidden="true" />
      {cited && <span className="ecard-flag" aria-label="Cited by an alibi check">!</span>}
    </div>
  );
}
