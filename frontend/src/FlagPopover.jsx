// Notched popover adapted from Uiverse.io by BishalSaini. Opens on hover, focus or click (so it
// works on touch and with a keyboard), stays open while the pointer is over it, and can open
// itself for a few seconds when a new flag arrives.
import { useEffect, useId, useRef, useState } from "react";
import { KIND_LABEL } from "./findings.js";
import { Quote } from "./AlibiAlert.jsx";

export function FindingBody({ finding, onJump }) {
  return (
    <>
      <span className={`source-chip ${finding.kind.toLowerCase()}`}>{KIND_LABEL[finding.kind]}</span>
      <p className="fp-line"><b>Now</b> <Quote text={finding.claim.text} quote={finding.new_quote} /></p>
      <p className="fp-line">
        <b>{finding.source.type === "evidence" ? "Record" : `${finding.source.speaker}`}</b>{" "}
        <Quote text={finding.source.text} quote={finding.prior_quote} />
      </p>
      <p className="fp-explain">{finding.explanation}</p>
      {onJump && <button type="button" className="fp-jump" onClick={() => onJump(finding)}>Jump to →</button>}
    </>
  );
}

export default function FlagPopover({ children, content, autoOpenKey, placement = "top", className = "" }) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const timer = useRef(null);
  const id = useId();

  useEffect(() => {
    if (autoOpenKey === undefined || autoOpenKey === null) return undefined;
    setOpen(true);
    const t = setTimeout(() => setOpen(false), 3000);
    return () => clearTimeout(t);
  }, [autoOpenKey]);

  const show = () => { clearTimeout(timer.current); setOpen(true); };
  const hide = () => { if (!pinned) timer.current = setTimeout(() => setOpen(false), 120); };

  return (
    <span
      className={`fp ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) { setPinned(false); setOpen(false); } }}
      onKeyDown={(e) => { if (e.key === "Escape") { setPinned(false); setOpen(false); } }}
    >
      <span
        className="fp-trigger"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => { setPinned((p) => !p); setOpen(true); }}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPinned((p) => !p); setOpen(true); } }}
      >
        {children}
      </span>
      <span id={id} role="tooltip" className={`fp-content ${placement} ${open ? "open" : ""}`}>
        {content}
      </span>
    </span>
  );
}
