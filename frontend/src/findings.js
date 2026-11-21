export const KIND_LABEL = { SELF: "Own statement", WITNESS: "Witness", EVIDENCE: "Evidence" };

export const turnLabel = (index) => `T${String(index + 1).padStart(2, "0")}`;

export const clock = (minutes) => {
  if (minutes === null || minutes === undefined) return "";
  const h = Math.floor(minutes / 60) % 24;
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};

// Where the other side of a finding came from, in a few words.
export function sourceLabel(finding, sessionId) {
  const source = finding.source;
  if (source.type === "evidence") return source.evidence_type.replaceAll("_", " ");
  const turn = turnLabel(source.turn_index);
  return source.session_id === sessionId ? `${turn} · this interview` : `${turn} · ${source.speaker}`;
}
