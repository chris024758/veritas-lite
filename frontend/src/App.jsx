import { useEffect, useState } from "react";
import { getCase } from "./api.js";
import CaseFilePanel from "./CaseFilePanel.jsx";
import InterviewPanel from "./InterviewPanel.jsx";

const CASE_ID = "2026-PUN-0219";

export default function App() {
  const [caseData, setCaseData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getCase(CASE_ID).then(setCaseData).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="wordmark">VERITAS<span>Lite</span></h1>
        <span className="case-id">CASE {CASE_ID}</span>
      </header>
      <div className="layout">
        <CaseFilePanel caseData={caseData} error={error} />
        <InterviewPanel caseId={CASE_ID} caseData={caseData} />
      </div>
    </div>
  );
}
