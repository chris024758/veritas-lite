import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import {
  endSession, generateReport, getCase, getTimeline, reportDocxUrl, startSession, submitStatement,
} from "./api.js";
import CaseDirectory from "./CaseDirectory.jsx";
import LoginPage, { useSignIn } from "./LoginPage.jsx";
import CaseFile from "./CaseFile.jsx";
import CaseFilePanel from "./CaseFilePanel.jsx";
import FlagPopover, { FindingBody } from "./FlagPopover.jsx";
import IntervieweePanel from "./IntervieweePanel.jsx";
import ReportPanel from "./ReportView.jsx";
import SidePanel from "./SidePanel.jsx";
import VeritasLoader from "./VeritasLoader.jsx";
import VoiceStage from "./VoiceStage.jsx";
import { casePath, navigate, useRoute } from "./router.js";

const Timeline3D = lazy(() => import("./Timeline3D.jsx"));
const STAGES = ["Extracting claims", "Verifying", "Alibi check", "Follow-ups"];
const VIEWS = [
  { id: "file", label: "Case file" },
  { id: "interview", label: "Interview" },
  { id: "timeline", label: "Timeline" },
];

function Dialog({ title, children, onCancel }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal glass" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export default function App() {
  const [signedIn, signIn] = useSignIn();
  if (!signedIn) return <LoginPage onEnter={signIn} />;
  return <Workspace />;
}

function Workspace() {
  const route = useRoute();
  const caseId = route.name === "case" ? route.caseId : null;
  const [caseData, setCaseData] = useState(null);
  const [caseError, setCaseError] = useState(null);
  const [interview, setInterview] = useState(null); // {caseId, subject, sessionId, statements, ended, report}
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [asking, setAsking] = useState(null);
  const [freshFindingIds, setFreshFindingIds] = useState([]);
  const [timeline, setTimeline] = useState(null);
  const [timelineError, setTimelineError] = useState(null);
  const [timelineFocus, setTimelineFocus] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const snapshotRef = useRef(null);
  const stageTimer = useRef(null);

  const refreshCase = useCallback((id) => {
    getCase(id).then((data) => { setCaseData(data); setCaseError(null); }).catch((e) => setCaseError(e.message));
  }, []);
  const refreshTimeline = useCallback((id) => {
    getTimeline(id).then((data) => { setTimeline(data); setTimelineError(null); }).catch((e) => setTimelineError(e.message));
  }, []);

  useEffect(() => {
    setCaseData(null);
    setTimeline(null);
    if (caseId) {
      refreshCase(caseId);
      refreshTimeline(caseId);
    }
  }, [caseId, refreshCase, refreshTimeline]);
  useEffect(() => { if (caseId && route.view === "timeline") refreshTimeline(caseId); }, [caseId, route.view, refreshTimeline]);

  const active = interview && interview.caseId === caseId ? interview : null;
  const findings = active ? active.statements.flatMap((s) => s.alibi_findings ?? []) : [];
  const latestFinding = findings[findings.length - 1];

  async function beginInterview(subject) {
    setPickerOpen(false);
    setError(null);
    try {
      const { session_id } = await startSession(caseId, subject.id);
      setInterview({ caseId, subject, sessionId: session_id, statements: [], attachments: [], ended: false, report: null });
      setFreshFindingIds([]);
      setAsking(null);
      setSnapshot(null);
      refreshCase(caseId);
    } catch (e) {
      setError(e.message);
    }
  }

  // One person per interview: choosing someone else ends the current one first.
  function choosePerson(subject) {
    if (active && active.subject.id === subject.id && !active.ended) {
      setPickerOpen(false);
      return;
    }
    if (active && !active.ended && active.statements.length > 0) {
      setConfirm({
        title: `End the interview with ${active.subject.full_name}?`,
        body: `Then start a new interview with ${subject.full_name}. Both are kept, each with its own report.`,
        action: "End and switch",
        run: async () => { await endSession(active.sessionId); await beginInterview(subject); },
      });
      return;
    }
    beginInterview(subject);
  }

  function startFromCaseFile(subject) {
    navigate(casePath(caseId, "interview"));
    if (subject) choosePerson(subject);
  }

  async function send(text) {
    setBusy({ stages: STAGES, stage: 0, text });
    setError(null);
    stageTimer.current = setInterval(() => {
      setBusy((b) => (b && b.stage < b.stages.length - 1 ? { ...b, stage: b.stage + 1 } : b));
    }, 1400);
    try {
      const result = await submitStatement(active.sessionId, text);
      setInterview((iv) => ({ ...iv, statements: [...iv.statements, { ...result, asked: asking }] }));
      setFreshFindingIds((result.alibi_findings ?? []).map((f) => f.id));
      setAsking(null);
      refreshTimeline(caseId);
      if (result.new_records?.length) refreshCase(caseId);
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      clearInterval(stageTimer.current);
      setBusy(null);
    }
  }

  function askEnd() {
    setConfirm({
      title: "End this interview?",
      body: "No more statements can be added. You can then generate the report.",
      action: "End interview",
      run: async () => {
        await endSession(active.sessionId);
        setInterview((iv) => ({ ...iv, ended: true }));
        refreshCase(caseId);
      },
    });
  }

  async function makeReport() {
    setReportOpen(true);
    setReportBusy(true);
    setReportError(null);
    try {
      const report = await generateReport(active.sessionId);
      setInterview((iv) => ({ ...iv, report }));
    } catch (e) {
      setReportError(e.message);
    } finally {
      setReportBusy(false);
    }
  }

  function jumpTo(finding) {
    const source = finding.source;
    const target = source.type === "claim" ? document.getElementById(`claim-${source.id}`) : null;
    if (target) {
      target.closest("details")?.setAttribute("open", "");
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("pinged");
      setTimeout(() => target.classList.remove("pinged"), 1600);
      return;
    }
    setTimelineFocus(source.type === "claim" ? `c${source.id}` : `e${source.id}`);
    navigate(casePath(caseId, "timeline"));
  }

  // An upload is read, filed as a record, and may clash with other people's claims. Its clashes
  // belong to the latest turn, as on the server.
  function attached(upload) {
    const raised = upload.alibi_findings ?? [];
    setInterview((iv) => {
      const statements = [...iv.statements];
      if (raised.length && statements.length) {
        const last = statements[statements.length - 1];
        statements[statements.length - 1] = { ...last, alibi_findings: [...(last.alibi_findings ?? []), ...raised] };
      }
      return { ...iv, statements, attachments: [...iv.attachments, upload] };
    });
    if (raised.length) setFreshFindingIds(raised.map((f) => f.id));
    if (upload.evidence) {
      refreshCase(caseId);
      refreshTimeline(caseId);
    }
  }

  const onSnapshot = useCallback((shot) => setSnapshot(shot), []);

  return (
    <div className="app">
      <header className="topbar glass">
        <nav className="crumbs" aria-label="Breadcrumb">
          <a href="#/cases" className="wordmark">VERITAS<span>Lite</span></a>
          <span className="crumb-sep">/</span>
          <a href="#/cases" className={route.name === "cases" ? "crumb current" : "crumb"}>Cases</a>
          {caseData && caseId && (
            <>
              <span className="crumb-sep">/</span>
              <a href={casePath(caseId)} className="crumb current">{caseData.name}</a>
            </>
          )}
        </nav>
        {caseId && (
          <nav className="tabs" aria-label="Case views">
            {VIEWS.map((v) => (
              <a key={v.id} href={casePath(caseId, v.id)} className={`tab ${route.view === v.id ? "active" : ""}`}
                aria-current={route.view === v.id ? "page" : undefined}>{v.label}</a>
            ))}
          </nav>
        )}
        <div className="topbar-right">
          {active && (
            <FlagPopover
              placement="bottom"
              className="counter-pop"
              autoOpenKey={freshFindingIds.length ? freshFindingIds[0] : null}
              content={latestFinding ? <FindingBody finding={latestFinding} onJump={jumpTo} /> : <span>No alibi clashes yet.</span>}
            >
              <span className={`alibi-counter ${findings.length ? "hot" : ""}`}>
                <span aria-hidden="true">⚠</span> {findings.length} alibi clash{findings.length === 1 ? "" : "es"}
              </span>
            </FlagPopover>
          )}
        </div>
      </header>

      {route.name === "cases" && <CaseDirectory />}

      {caseId && route.view === "file" && (
        <CaseFile caseData={caseData} error={caseError} findings={findings}
          onStartInterview={startFromCaseFile}
          onShowOnTimeline={(id) => { setTimelineFocus(id); navigate(casePath(caseId, "timeline")); }} />
      )}

      {caseId && route.view === "interview" && (
        !caseData ? <main className="page center-load">{caseError ? <p className="error">{caseError}</p> : <VeritasLoader size={0.6} />}</main> : (
          <div className={`interview-layout ${drawerOpen ? "drawer-open" : ""}`}>
            <CaseFilePanel caseData={caseData} error={caseError} findings={findings} collapsed={!drawerOpen}
              onToggle={() => setDrawerOpen((o) => !o)}
              onShowOnTimeline={(id) => { setTimelineFocus(id); navigate(casePath(caseId, "timeline")); }} />

            <main className="stage">
              {active && (
                <div className="stage-head">
                  <button type="button" className="who" onClick={() => setPickerOpen((o) => !o)} aria-expanded={pickerOpen}>
                    <span className="muted">{caseData.name} ›</span> <b>{active.subject.full_name}</b>
                    <span className="tag">{active.subject.role}</span>
                    <span className={`live ${active.ended ? "ended" : "on"}`}>{active.ended ? "Ended" : "Live"}</span>
                  </button>
                  {!active.ended && (
                    <button type="button" className="secondary" onClick={askEnd} disabled={!!busy}>End interview</button>
                  )}
                </div>
              )}
              {(!active || pickerOpen) && (
                <IntervieweePanel
                  caseData={caseData}
                  current={active?.subject}
                  onPick={choosePerson}
                  onAdded={(person) => { refreshCase(caseId); refreshTimeline(caseId); choosePerson(person); }}
                  onClose={active ? () => setPickerOpen(false) : null}
                />
              )}
              {active && !pickerOpen && (
                <VoiceStage
                  key={active.sessionId}
                  subject={active.subject}
                  sessionId={active.sessionId}
                  statements={active.statements}
                  attachments={active.attachments}
                  onAttached={attached}
                  asking={asking}
                  onClearAsking={() => setAsking(null)}
                  onSend={send}
                  busy={busy}
                  ended={active.ended}
                  reportReady={!!active.report}
                  onReport={() => (active.report ? setReportOpen(true) : makeReport())}
                />
              )}
              {error && <p className="error stage-error" role="alert">{error}</p>}
            </main>

            {active ? (
              <SidePanel statements={active.statements} attachments={active.attachments} sessionId={active.sessionId} freshFindingIds={freshFindingIds}
                onPickQuestion={setAsking} onJump={jumpTo} />
            ) : (
              <aside className="side glass" aria-label="Findings">
                <h2 className="side-title">Findings</h2>
                <p className="muted small">Choose who you're interviewing to begin.</p>
              </aside>
            )}
          </div>
        )
      )}

      {caseId && route.view === "timeline" && (
        <Suspense fallback={<div className="timeline-empty"><VeritasLoader size={0.8} label="Loading timeline" /></div>}>
          <Timeline3D data={timeline} error={timelineError} focus={timelineFocus} freshLinks={freshFindingIds}
            snapshotRef={snapshotRef} onSnapshot={onSnapshot} />
        </Suspense>
      )}

      {reportOpen && active && (
        <ReportPanel report={active.report} busy={reportBusy} error={reportError} onGenerate={makeReport}
          onClose={() => setReportOpen(false)} snapshot={snapshot} docxUrl={reportDocxUrl(active.sessionId)} />
      )}

      {confirm && (
        <Dialog title={confirm.title} onCancel={() => setConfirm(null)}>
          <p className="muted">{confirm.body}</p>
          <div className="actions">
            <button type="button" className="primary" autoFocus
              onClick={async () => { const c = confirm; setConfirm(null); try { await c.run(); } catch (e) { setError(e.message); } }}>
              {confirm.action}
            </button>
            <button type="button" className="secondary" onClick={() => setConfirm(null)}>Cancel</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
