import { useEffect, useRef, useState } from "react";
import { addAttachment, assetUrl, extractAttachment, transcribe } from "./api.js";
import { eventVerdict } from "./ImageExtraction.jsx";
import VeritasLoader from "./VeritasLoader.jsx";
import { turnLabel } from "./findings.js";

const Recognition = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

// Prepared answers for rehearsal; picking one fills the draft, which still needs Send.
export const DEMO_SCRIPT = [
  { label: "Street cleaner · the SUV", text: "Around quarter past ten I was sweeping near the jewellers on FC Road. A black SUV was standing in the back lane with its engine running. It had a big round sticker on the rear glass, a red trident I think. Two men got in and it drove off towards Shivajinagar." },
  { label: "Suresh · his evening", text: "I was at my friend Ramesh's place in Hadapsar till about nine. Then I rode to the shop to check on things, left at 9:40, and was home in Kothrud by 9:50." },
  { label: "Ramesh · the concert", text: "No, Suresh didn't come over that evening. I wasn't even home. I was at the Indian Ocean concert in Pune on 21 November. Here's my ticket." },
];

// The statement with the words an alibi check clashed on underlined.
function Marked({ text, quotes }) {
  const spans = [];
  const lower = text.toLowerCase();
  for (const q of quotes) {
    const at = q ? lower.indexOf(q.toLowerCase()) : -1;
    if (at >= 0) spans.push([at, at + q.length]);
  }
  spans.sort((a, b) => a[0] - b[0]);
  const out = [];
  let cursor = 0;
  spans.forEach(([s, e], i) => {
    if (s < cursor) return;
    out.push(text.slice(cursor, s), <mark key={i} className="said-clash">{text.slice(s, e)}</mark>);
    cursor = e;
  });
  out.push(text.slice(cursor));
  return <>{out}</>;
}

function Orb({ level, state }) {
  return (
    <div className={`orb orb-${state}`} style={{ "--level": level }} aria-hidden="true">
      <span className="orb-ring r1" />
      <span className="orb-ring r2" />
      <span className="orb-ring r3" />
      <span className="orb-core">
        <svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          {state === "listening" ? <rect x="7" y="7" width="10" height="10" rx="2" /> : <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>}
        </svg>
      </span>
    </div>
  );
}

const BAR_COUNT = 28;

function Bars({ bars }) {
  return (
    <div className="bars" aria-hidden="true">
      {bars.map((h, i) => <span key={i} style={{ height: `${Math.max(6, h * 100)}%` }} />)}
    </div>
  );
}

function Attachment({ a, checkingId, uploading, onCheck }) {
  const check = a.extraction?.event_verification;
  function showFinding() {
    const finding = document.getElementById(`image-finding-${a.id}`);
    finding?.focus({ preventScroll: true });
    finding?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  return (
    <li className="talk-attachment">
      <figure>
        <img src={assetUrl(a.url ?? `/uploads/${a.filename}`)} alt={a.caption || a.original_name || "Added image"} />
        <figcaption>
          <span className="tag">{a.evidence_id ? "Filed as evidence" : "Image added"}</span> {a.caption || a.original_name}
        </figcaption>
        {a.extraction ? (
          <button type="button" className="secondary attachment-check" onClick={showFinding} aria-controls={`image-finding-${a.id}`}>
            {check ? eventVerdict(check.verified) : "View extracted details"}
          </button>
        ) : (
          <button type="button" className="secondary attachment-check" disabled={uploading || checkingId !== null}
            onClick={() => onCheck(a)}>
            {checkingId === a.id ? "Checking image…" : "Extract & check"}
          </button>
        )}
      </figure>
    </li>
  );
}

export default function VoiceStage({ subject, sessionId, statements, attachments = [], onAttached, asking, onClearAsking, onSend, busy, ended, onReport, reportReady }) {
  const [state, setState] = useState("ready"); // ready | listening | transcribing
  const [level, setLevel] = useState(0);
  const [caption, setCaption] = useState("");
  const [draft, setDraft] = useState(null); // null = no draft; string = review before Send
  const [error, setError] = useState(null);
  const [demoOpen, setDemoOpen] = useState(false);
  const [bars, setBars] = useState(() => Array(BAR_COUNT).fill(0));
  const [pendingImage, setPendingImage] = useState(null); // {file, preview, caption, busy}
  const [checkingId, setCheckingId] = useState(null);
  const preview = pendingImage?.preview;
  const fileRef = useRef(null);
  const media = useRef({});
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [statements.length, attachments.length, draft, busy]);
  useEffect(() => () => stopEverything(), []);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  function stopEverything() {
    const m = media.current;
    cancelAnimationFrame(m.raf);
    m.recognition?.abort?.();
    m.stream?.getTracks().forEach((t) => t.stop());
    m.audio?.close?.();
    media.current = {};
  }

  async function startListening() {
    setError(null);
    setCaption("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const chunks = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = () => handleClip(new Blob(chunks, { type: recorder.mimeType }));

      // Live level for the orb.
      const audio = new AudioContext();
      const analyser = audio.createAnalyser();
      analyser.fftSize = 512;
      audio.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      const freq = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) sum += ((v - 128) / 128) ** 2;
        setLevel(Math.min(1, Math.sqrt(sum / data.length) * 4));
        // Voice sits in the lower bins; spread those across the bars.
        analyser.getByteFrequencyData(freq);
        const span = Math.floor(freq.length * 0.45 / BAR_COUNT);
        setBars(Array.from({ length: BAR_COUNT }, (_, i) => {
          let peak = 0;
          for (let j = i * span; j < (i + 1) * span; j++) peak = Math.max(peak, freq[j]);
          return peak / 255;
        }));
        media.current.raf = requestAnimationFrame(tick);
      };
      tick();

      // Rough live captions where the browser supports them; Whisper's text is the one kept.
      let recognition = null;
      if (Recognition) {
        recognition = new Recognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = "en-IN";
        recognition.onresult = (e) => setCaption(Array.from(e.results).map((r) => r[0].transcript).join(" "));
        recognition.onerror = () => {};
        try { recognition.start(); } catch { recognition = null; }
      }
      recorder.start();
      media.current = { stream, recorder, audio, recognition, raf: media.current.raf };
      setState("listening");
    } catch (e) {
      setError(`Microphone unavailable: ${e.message}`);
    }
  }

  function stopListening() {
    const m = media.current;
    m.recorder?.stop();
    m.recognition?.stop?.();
    cancelAnimationFrame(m.raf);
    m.stream?.getTracks().forEach((t) => t.stop());
    m.audio?.close?.();
    setLevel(0);
    setBars(Array(BAR_COUNT).fill(0));
    setState("transcribing");
  }

  async function handleClip(blob) {
    try {
      const { transcript } = await transcribe(sessionId, blob);
      if (!transcript) setError("No speech detected in that clip.");
      else setDraft(transcript);
    } catch (e) {
      setError(e.message);
    } finally {
      setState("ready");
      setCaption("");
    }
  }

  async function send() {
    const text = draft.trim();
    if (!text) return;
    setDraft(null); // the turn shows above while it's checked
    const ok = await onSend(text);
    if (!ok) setDraft(text);
  }

  function pickImage(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) { setError("Only images can be added."); return; }
    setError(null);
    setPendingImage({ file, preview: URL.createObjectURL(file), caption: "", busy: false });
  }

  async function uploadImage() {
    if (!pendingImage || pendingImage.busy || checkingId !== null) return;
    setError(null);
    setPendingImage((p) => ({ ...p, busy: true }));
    try {
      const saved = await addAttachment(sessionId, pendingImage.file, pendingImage.caption.trim());
      onAttached(saved);
      setPendingImage(null);
      await checkAttachment(saved);
    } catch (e) {
      setError(e.message);
      setPendingImage((p) => ({ ...p, busy: false }));
    }
  }

  async function checkAttachment(attachment) {
    if (checkingId !== null) return;
    setCheckingId(attachment.id);
    setError(null);
    try {
      const extraction = await extractAttachment(sessionId, attachment.id);
      onAttached({ ...attachment, extraction });
    } catch (e) {
      setError(`Image added. Extraction failed: ${e.message}`);
    } finally {
      setCheckingId(null);
    }
  }

  const byTurn = (n) => attachments.filter((a) => a.after_turn === n).map((a) => (
    <Attachment key={a.id} a={a} checkingId={checkingId} uploading={pendingImage?.busy}
      onCheck={checkAttachment} />
  ));

  const canTalk = !ended && !busy && draft === null && state !== "transcribing";

  return (
    <section className="voice-stage">
      <ol className="talk">
        {statements.length === 0 && draft === null && state === "ready" && !busy && !ended && (
          <li className="talk-empty muted">Click the mic and let {subject.full_name.split(" ")[0]} speak. You'll see the text before anything is checked.</li>
        )}
        {byTurn(0)}
        {statements.map((s, index) => {
          const quotes = (s.alibi_findings ?? []).map((f) => f.new_quote);
          return [
            <li key={s.id} className="talk-turn">
              {s.asked && <p className="talk-q"><span>Q</span>{s.asked}</p>}
              <p className="talk-a">
                <span className="turn-no">{turnLabel(s.turn_index)}</span>
                <span><Marked text={s.text} quotes={quotes} /></span>
              </p>
            </li>,
            ...byTurn(index + 1),
          ];
        })}
        {busy && (
          <li className="talk-turn pending">
            <p className="talk-a"><span className="turn-no">…</span><span>{busy.text}</span></p>
            <div className="progress-strip">
              <VeritasLoader size={0.28} label="Checking statement" />
              <ol>
                {busy.stages.map((stage, i) => (
                  <li key={stage} className={i < busy.stage ? "done" : i === busy.stage ? "now" : ""}>{stage}</li>
                ))}
              </ol>
            </div>
          </li>
        )}
        <li ref={endRef} aria-hidden="true" />
      </ol>

      {ended ? (
        <div className="stage-controls ended">
          <p className="muted">Interview ended.</p>
          <button type="button" className="primary big" onClick={onReport}>{reportReady ? "Open report" : "Generate report"}</button>
        </div>
      ) : draft !== null ? (
        <div className="draft">
          {asking && <p className="talk-q"><span>Q</span>{asking}</p>}
          <div className="draft-head">
            <span className="draft-tag">Not sent yet</span>
            <span className="muted small">Check the words, fix any mistakes, then send it to be checked.</span>
          </div>
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} aria-label="Statement to send" autoFocus />
          <div className="actions">
            <button type="button" className="primary" onClick={send} disabled={!draft.trim() || !!busy}>Send</button>
            <button type="button" className="secondary" onClick={() => setDraft(null)} disabled={!!busy}>Discard</button>
          </div>
        </div>
      ) : (
        <div className="stage-controls">
          {asking && (
            <p className="asking"><span>Asking</span>{asking}
              <button type="button" className="icon-btn" onClick={onClearAsking} aria-label="Clear question">×</button>
            </p>
          )}
          {pendingImage && (
            <div className="image-pending">
              <img src={pendingImage.preview} alt="Selected" />
              <div>
                <input value={pendingImage.caption} placeholder="Caption, e.g. photo shown by the subject"
                  aria-label="Image caption" disabled={pendingImage.busy}
                  onChange={(e) => setPendingImage((p) => ({ ...p, caption: e.target.value }))} autoFocus />
                <p className="muted small">Files the image as evidence and sends it to Groq. Detected events are checked on the web.</p>
                <div className="actions">
                  <button type="button" className="primary" onClick={uploadImage} disabled={pendingImage.busy || checkingId !== null}>
                    {pendingImage.busy ? "Adding image…" : "Add & check"}
                  </button>
                  <button type="button" className="secondary" disabled={pendingImage.busy} onClick={() => setPendingImage(null)}>Cancel</button>
                </div>
              </div>
            </div>
          )}
          <div className="orb-row">
          <button type="button" className="plus-btn" onClick={() => fileRef.current?.click()}
            disabled={!canTalk || state !== "ready" || !!pendingImage || checkingId !== null}
            aria-label="Add an image" title="Add an image">+</button>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={pickImage} />
          <button
            type="button"
            className="orb-btn"
            onClick={state === "listening" ? stopListening : startListening}
            disabled={!canTalk && state !== "listening"}
            aria-label={state === "listening" ? "Stop recording" : "Start recording"}
          >
            <Orb level={level} state={state} />
          </button>
          <span className="plus-spacer" aria-hidden="true" />
          </div>
          {state === "listening" && <Bars bars={bars} />}
          <p className="stage-state" role="status">
            {state === "listening" ? "Listening… click to stop" : state === "transcribing" ? "Converting speech to text…" : busy ? "Checking…" : "Ready"}
          </p>
          {state === "listening" && (
            <p className="caption">{caption || (Recognition ? "…" : "Live captions aren't supported in this browser; the text appears when you stop.")}</p>
          )}
          {state === "transcribing" && <VeritasLoader size={0.3} label="Converting speech to text" />}
          <div className="stage-links">
            <button type="button" className="link-btn" onClick={() => setDraft("")} disabled={!canTalk}>Type instead</button>
            <div className="demo-menu">
              <button type="button" className="link-btn" onClick={() => setDemoOpen((o) => !o)} disabled={!canTalk} aria-expanded={demoOpen}>Demo script</button>
              {demoOpen && (
                <ul className="demo-list glass">
                  {DEMO_SCRIPT.map((t) => (
                    <li key={t.label}>
                      <button type="button" onClick={() => { setDraft(t.text); setDemoOpen(false); }}>
                        <b>{t.label}</b><span>{t.text}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
