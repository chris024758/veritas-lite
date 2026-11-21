import { useEffect, useState } from "react";

// #/cases · #/case/:id · #/case/:id/interview · #/case/:id/timeline
export function parseRoute(hash) {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "case" && parts[1]) {
    const view = ["interview", "timeline"].includes(parts[2]) ? parts[2] : "file";
    return { name: "case", caseId: parts[1], view };
  }
  return { name: "cases" };
}

export const navigate = (path) => { window.location.hash = path; };

export const casePath = (caseId, view = "file") =>
  `#/case/${encodeURIComponent(caseId)}${view === "file" ? "" : `/${view}`}`;

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
