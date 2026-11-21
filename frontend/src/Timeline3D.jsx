import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Edges, Html, OrbitControls, QuadraticBezierLine, RoundedBox } from "@react-three/drei";
import VeritasLoader from "./VeritasLoader.jsx";
import { StatusBadge } from "./ClaimsTable.jsx";
import { KIND_LABEL, clock, turnLabel } from "./findings.js";

// Axes: x = time, z = one lane per person (evidence nearest the camera), y = only for arcs.
const X_SPAN = 30;
const LANE_GAP = 4.6;
const CAMERA = [-3, 14, 27];
const STATUS_COLOR = {
  CONFLICT: "#f9b17a", FLAGGED: "#5a4a55", CONSISTENT: "#ffffff", PENDING: "#676f9d", EVIDENCE: "#b9bedb",
};
const PROBLEM = new Set(["CONFLICT", "FLAGGED"]);

function useLayout(data) {
  return useMemo(() => {
    if (!data?.axis) return null;
    const { start, end } = data.axis;
    const scale = X_SPAN / Math.max(end - start, 1);
    const x = (m) => (m - start) * scale - X_SPAN / 2;
    const n = data.lanes.length;
    const laneZ = Object.fromEntries(data.lanes.map((lane, i) => [lane.id, ((n - 1) / 2 - i) * LANE_GAP]));
    const pos = {};
    for (const e of data.events) {
      const center = e.end !== null ? (x(e.start) + x(e.end)) / 2 : x(e.start);
      pos[e.id] = [center, e.kind === "evidence" ? 2.3 : 0.7, laneZ[e.lane]];
    }
    const ticks = [];
    for (let m = Math.ceil(start / 15) * 15; m <= end; m += 15) ticks.push(m);
    return { x, scale, laneZ, pos, ticks, depth: n * LANE_GAP, front: ((n - 1) / 2) * LANE_GAP + 2.2 };
  }, [data]);
}

// New objects drop into place; existing ones stay put.
function FlyIn({ children, position }) {
  const ref = useRef();
  useFrame((_, delta) => {
    if (!ref.current) return;
    ref.current.position.y += (position[1] - ref.current.position.y) * Math.min(1, delta * 4);
  });
  return <group ref={ref} position={[position[0], position[1] + 7, position[2]]}>{children}</group>;
}

function ClaimMesh({ event, layout, selected, dimmed, onSelect }) {
  const [hover, setHover] = useState(false);
  const color = STATUS_COLOR[event.status] ?? "#888";
  const glow = event.status === "CONFLICT" ? 0.7 : event.status === "FLAGGED" ? 0.3 : 0;
  const material = (
    <meshStandardMaterial
      color={color}
      emissive={event.status === "FLAGGED" ? "#f9b17a" : color}
      emissiveIntensity={glow}
      transparent
      opacity={dimmed ? 0.15 : event.approx ? 0.6 : 0.95}
      roughness={0.35}
      metalness={0.1}
    />
  );
  const handlers = {
    onClick: (e) => { e.stopPropagation(); onSelect({ type: "event", id: event.id }); },
    onPointerOver: (e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = "pointer"; },
    onPointerOut: () => { setHover(false); document.body.style.cursor = ""; },
  };
  const edge = selected ? "#ffffff" : event.status === "FLAGGED" ? "#f9b17a" : null;
  const isRange = event.end !== null;
  const width = isRange ? Math.max((event.end - event.start) * layout.scale, 0.4) : 0;
  return (
    <FlyIn position={layout.pos[event.id]}>
      <group scale={selected || hover ? 1.15 : 1}>
        {event.kind === "evidence" ? (
          <mesh {...handlers} position={[0, -1.15, 0]}>
            <cylinderGeometry args={[0.32, 0.32, 3.2, 20]} />
            {material}
            {edge && <Edges color={edge} />}
          </mesh>
        ) : isRange ? (
          <RoundedBox args={[width, 0.55, 1]} radius={0.12} {...handlers}>
            {material}
            {edge && <Edges color={edge} />}
          </RoundedBox>
        ) : (
          <mesh {...handlers}>
            <octahedronGeometry args={[0.5]} />
            {material}
            {edge && <Edges color={edge} />}
          </mesh>
        )}
        {(hover || selected) && (
          <Html center position={[0, 1.3, 0]} className="t3-label" zIndexRange={[20, 0]}>
            <span>{event.start !== null && clock(event.start)}{event.end !== null && `–${clock(event.end)}`}</span>
            {event.text.length > 70 ? `${event.text.slice(0, 70)}…` : event.text}
          </Html>
        )}
      </group>
    </FlyIn>
  );
}

function Arc({ link, layout, fresh, selected, onSelect }) {
  const a = layout.pos[link.from];
  const b = layout.pos[link.to];
  const line = useRef();
  useFrame(({ clock: c }) => {
    if (!line.current?.material) return;
    const pulse = fresh ? 3 + Math.sin(c.elapsedTime * 6) * 1.5 : 2.5;
    line.current.material.linewidth = selected ? 5 : pulse;
  });
  if (!a || !b) return null;
  const height = 3.2 + Math.abs(a[2] - b[2]) * 0.35 + Math.abs(a[0] - b[0]) * 0.08;
  const mid = [(a[0] + b[0]) / 2, height, (a[2] + b[2]) / 2];
  return (
    <group>
      <QuadraticBezierLine ref={line} start={a} end={b} mid={mid} color="#f9b17a" lineWidth={2.5} transparent opacity={0.95} />
      <mesh
        position={[mid[0], height / 2 + 0.4, mid[2]]}
        onClick={(e) => { e.stopPropagation(); onSelect({ type: "link", id: link.id }); }}
        onPointerOver={() => { document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { document.body.style.cursor = ""; }}
      >
        <sphereGeometry args={[0.28, 16, 16]} />
        <meshStandardMaterial color="#f9b17a" emissive="#f9b17a" emissiveIntensity={fresh ? 1.4 : 0.8} />
      </mesh>
    </group>
  );
}

function Scene({ data, layout, visibleLanes, problemsOnly, selection, onSelect, freshLinks, laneFocus, controlsRef }) {
  const linked = new Set(data.links.flatMap((l) => [l.from, l.to]));
  const show = (e) => visibleLanes.has(e.lane) && (!problemsOnly || PROBLEM.has(e.status) || linked.has(e.id));
  const halfDepth = layout.depth / 2;

  useEffect(() => { controlsRef.current?.saveState(); }, [controlsRef]);

  return (
    <>
      <color attach="background" args={["#1b1f30"]} />
      <fog attach="fog" args={["#1b1f30", 30, 70]} />
      <ambientLight intensity={0.9} />
      <directionalLight position={[10, 20, 15]} intensity={1.1} />
      <pointLight position={[0, 6, 0]} color="#8c93c4" intensity={14} distance={30} />

      {data.lanes.map((lane) => (
        <group key={lane.id} position={[0, 0, layout.laneZ[lane.id]]}>
          <mesh position={[0, -0.06, 0]} onClick={() => onSelect(null)}>
            <boxGeometry args={[X_SPAN + 4, 0.08, 2.6]} />
            <meshStandardMaterial
              color={laneFocus === lane.id ? "#676f9d" : lane.role === "Suspect" ? "#424769" : "#2d3250"}
              transparent opacity={visibleLanes.has(lane.id) ? 1 : 0.25}
            />
          </mesh>
          <Html position={[-X_SPAN / 2 - 1.8, 0.2, 0]} className={`t3-lane ${lane.role.toLowerCase()}`}>
            <b>{lane.label}</b><span>{lane.role}</span>
          </Html>
        </group>
      ))}

      {layout.ticks.map((m) => (
        <group key={m} position={[layout.x(m), 0, 0]}>
          <mesh position={[0, 0.01, 0]}>
            <boxGeometry args={[0.03, 0.01, layout.depth]} />
            <meshBasicMaterial color={m % 60 === 0 ? "#676f9d" : "#3a3f63"} />
          </mesh>
          <Html position={[0, 0, layout.front]} center className="t3-tick">{clock(m)}</Html>
        </group>
      ))}

      {data.incident && (() => {
        const x0 = layout.x(data.incident.start);
        const x1 = layout.x(data.incident.end);
        return (
          <group>
            <mesh position={[(x0 + x1) / 2, 1.9, 0]}>
              <boxGeometry args={[x1 - x0, 3.8, layout.depth]} />
              <meshBasicMaterial color="#b9bedb" transparent opacity={0.06} depthWrite={false} />
              <Edges color="#8c93c4" />
            </mesh>
            <Html position={[(x0 + x1) / 2, 4.3, -halfDepth]} center className="t3-incident">
              Incident {clock(data.incident.start)}–{clock(data.incident.end)}
            </Html>
          </group>
        );
      })()}

      {data.gaps.filter((g) => visibleLanes.has(g.lane)).map((g) => (
        <mesh key={`${g.lane}-${g.start}`} position={[(layout.x(g.start) + layout.x(g.end)) / 2, 0.0, layout.laneZ[g.lane]]}>
          <boxGeometry args={[layout.x(g.end) - layout.x(g.start), 0.1, 2.2]} />
          <meshStandardMaterial color="#10131f" />
          <Edges color="#d98a52" />
          <Html position={[0, 0.25, 1.4]} center className="t3-gap">alibi gap {clock(g.start)}–{clock(g.end)}</Html>
        </mesh>
      ))}

      {data.events.map((e) => (
        <ClaimMesh
          key={e.id}
          event={e}
          layout={layout}
          dimmed={!show(e)}
          selected={selection?.type === "event" && selection.id === e.id}
          onSelect={onSelect}
        />
      ))}

      {data.links
        .filter((l) => data.events.some((e) => e.id === l.from && show(e)))
        .map((l) => (
          <Arc key={l.id} link={l} layout={layout} fresh={freshLinks.includes(l.id)}
            selected={selection?.type === "link" && selection.id === l.id} onSelect={onSelect} />
        ))}

      <OrbitControls ref={controlsRef} makeDefault enableDamping maxPolarAngle={Math.PI / 2.1} minDistance={8} maxDistance={60} />
    </>
  );
}

function Inspector({ data, selection, onClose }) {
  if (!selection) {
    return (
      <div className="t3-inspector glass">
        <p className="eyebrow">Inspector</p>
        <p className="muted small">Click a claim, a record pillar, or a red arc to see its details. Drag to orbit, scroll to zoom.</p>
      </div>
    );
  }
  const byId = Object.fromEntries([...data.events, ...data.untimed].map((e) => [e.id, e]));
  if (selection.type === "link") {
    const link = data.links.find((l) => l.id === selection.id);
    if (!link) return null;
    const from = byId[link.from];
    const to = byId[link.to];
    return (
      <div className="t3-inspector glass">
        <div className="record-detail-head">
          <span className={`source-chip ${link.kind.toLowerCase()}`}>{KIND_LABEL[link.kind]}</span>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        <p className="t3-explain">{link.explanation}</p>
        {[["Now", from], ["Then", to]].map(([label, e]) => e && (
          <div key={label} className="t3-side">
            <p className="eyebrow">{label} · {e.speaker}</p>
            <p>{e.text}</p>
          </div>
        ))}
      </div>
    );
  }
  const event = byId[selection.id];
  if (!event) return null;
  const links = data.links.filter((l) => l.from === event.id || l.to === event.id);
  return (
    <div className="t3-inspector glass">
      <div className="record-detail-head">
        {event.kind === "evidence" ? <span className="source-chip evidence">Evidence</span> : <StatusBadge status={event.status} />}
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">×</button>
      </div>
      <p className="eyebrow">
        {event.speaker}{event.turn_index !== undefined && ` · ${turnLabel(event.turn_index)}`}
        {event.start !== null && ` · ${clock(event.start)}${event.end !== null ? `–${clock(event.end)}` : ""}`}
        {event.approx && " (approx.)"}
      </p>
      <p>{event.text}</p>
      {event.reason && <p className="muted small">{event.reason}</p>}
      {links.length > 0 && (
        <ul className="linked-list">
          {links.map((l) => (
            <li key={l.id}><span className={`source-chip ${l.kind.toLowerCase()}`}>{KIND_LABEL[l.kind]}</span><span>{l.explanation}</span></li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Timeline3D({ data, error, focus, freshLinks, snapshotRef, onSnapshot }) {
  const layout = useLayout(data);
  const [selection, setSelection] = useState(null);
  const [hiddenLanes, setHiddenLanes] = useState(new Set());
  const [problemsOnly, setProblemsOnly] = useState(false);
  const controlsRef = useRef();
  const glRef = useRef(null);

  useEffect(() => {
    if (!focus) return;
    if (focus.startsWith("lane:")) setSelection(null);
    else setSelection({ type: "event", id: focus });
  }, [focus]);

  // Keep a picture of the scene for the report, and hand the report a way to take a fresh one.
  useEffect(() => {
    snapshotRef.current = () => glRef.current?.domElement.toDataURL("image/png") ?? null;
    return () => {
      const shot = snapshotRef.current?.();
      if (shot) onSnapshot(shot);
      snapshotRef.current = null;
    };
  }, [snapshotRef, onSnapshot]);

  if (error) return <div className="timeline-empty"><p className="error">{error}</p></div>;
  if (!data) return <div className="timeline-empty"><VeritasLoader size={0.8} label="Loading timeline" /></div>;
  if (!layout) {
    return <div className="timeline-empty"><p className="muted">Nothing on the timeline yet: no claim or record has a time.</p></div>;
  }

  const visibleLanes = new Set(data.lanes.map((l) => l.id).filter((id) => !hiddenLanes.has(id)));
  const toggleLane = (id) => setHiddenLanes((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const laneFocus = focus?.startsWith("lane:") ? focus.slice(5) : null;

  return (
    <div className="timeline">
      <Canvas
        camera={{ position: CAMERA, fov: 42 }}
        gl={{ preserveDrawingBuffer: true, antialias: true }}
        onCreated={({ gl }) => { glRef.current = gl; }}
        onPointerMissed={() => setSelection(null)}
      >
        <Suspense fallback={null}>
          <Scene data={data} layout={layout} visibleLanes={visibleLanes} problemsOnly={problemsOnly}
            selection={selection} onSelect={setSelection} freshLinks={freshLinks} laneFocus={laneFocus}
            controlsRef={controlsRef} />
        </Suspense>
      </Canvas>

      <div className="t3-toolbar glass" role="toolbar" aria-label="Timeline controls">
        {data.lanes.map((lane) => (
          <button key={lane.id} type="button" aria-pressed={!hiddenLanes.has(lane.id)}
            className={`chip-toggle ${hiddenLanes.has(lane.id) ? "" : "on"}`} onClick={() => toggleLane(lane.id)}>
            {lane.label}
          </button>
        ))}
        <span className="divider" />
        <button type="button" aria-pressed={problemsOnly} className={`chip-toggle ${problemsOnly ? "on red" : ""}`}
          onClick={() => setProblemsOnly((p) => !p)}>Problems only</button>
        <button type="button" className="chip-toggle" onClick={() => controlsRef.current?.reset()}>Reset view</button>
        <span className="divider" />
        <ul className="t3-legend" aria-label="Legend">
          <li><i className="lg conflict" />Conflict</li>
          <li><i className="lg flagged" />Flagged</li>
          <li><i className="lg consistent" />Consistent</li>
          <li><i className="lg pending" />Pending</li>
          <li><i className="lg arc" />Alibi clash</li>
          <li><i className="lg gap" />Alibi gap</li>
        </ul>
      </div>

      <Inspector data={data} selection={selection} onClose={() => setSelection(null)} />

      {data.untimed.length > 0 && (
        <div className="t3-tray glass">
          <p className="eyebrow">Untimed ({data.untimed.length})</p>
          <ul>
            {data.untimed.map((e) => (
              <li key={e.id}>
                <button type="button" onClick={() => setSelection({ type: "event", id: e.id })}
                  className={data.links.some((l) => l.from === e.id || l.to === e.id) ? "linked" : ""}>
                  <i className={`lg ${(e.status ?? "pending").toLowerCase()}`} />
                  <span>{e.speaker}{e.turn_index !== undefined && ` · ${turnLabel(e.turn_index)}`}</span>
                  {e.text}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
