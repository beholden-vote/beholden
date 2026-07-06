/** WO-13: interactive force-directed view of a dossier's connection
 *  neighborhood — an Obsidian-style spatial lens rendered ABOVE the list. The
 *  LIST stays canonical and cited; this SVG re-presents the same edges and is
 *  aria-hidden decoration (every capability here — open a neighbor's dossier,
 *  inspect an edge — exists in the list too).
 *
 *  d3-force is imported HERE and only here. Connections.tsx imports this file
 *  statically, so Vite bundles d3-force into the existing lazy Connections
 *  chunk — the main bundle pays nothing.
 *
 *  Rule 0 (DESIGN.md): node fill is the party DATA encoding (allowed — same
 *  palette as the map); edges are NEUTRAL --line-2 at rest, never party-colored,
 *  never amber at rest. Edge TYPE is encoded by stroke STYLE, not color. Amber
 *  appears only as the hover/action signal, identically for every edge. */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY,
  type Simulation, type SimulationLinkDatum, type SimulationNodeDatum,
} from "d3-force";
import { PARTY_COLORS } from "../map";
import { personHash } from "../router";
import { edgeKey, edgeLabel, otherEnd, type EdgeType, type GraphEdge, type Neighborhood } from "../lib/graph";
import { STRINGS } from "../strings";

const VB_W = 400;
const VB_H = 300;
const CX = VB_W / 2;
const CY = VB_H / 2;
const PAD = 14;   // render clamp so nodes never draw off the viewBox edge

/** True when the user asked for no motion: the sim settles synchronously and
 *  drag/scroll/flash animation is disabled (DESIGN §6). */
export function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

interface SimNode extends SimulationNodeDatum {
  id: string;
  name: string;
  party: string;
  isCenter: boolean;
  r: number;
}

/** ONE sim link per node pair (see buildGraph); rendering uses DrawnEdge. */
interface SimLink extends SimulationLinkDatum<SimNode> {
  source: SimNode;
  target: SimNode;
  strength: number;
}

/** One RENDERED typed edge — all typed edges draw, parallel ones fanned. */
interface DrawnEdge {
  edge: GraphEdge;
  key: string;
  a: SimNode;
  b: SimNode;
  offset: number;   // perpendicular fan offset in viewBox px
  width: number;    // 1–3px by per-type-normalized weight
}

interface Graph {
  nodes: SimNode[];
  drawn: DrawnEdge[];
  sim: Simulation<SimNode, SimLink>;
}

/** Build cloned sim inputs + the simulation itself. d3-force MUTATES its node
 *  and link inputs (x/y/vx/vy, drag's fx/fy) — and lib/graph.ts caches the
 *  fetched neighborhood doc — so everything the sim touches is a fresh object;
 *  nb's own objects are only ever read. */
function buildGraph(nb: Neighborhood, reduced: boolean): Graph {
  // Edge weights are incommensurable across types (co_voting is a %, the rest
  // are counts) — normalize within each type before any cross-type math.
  const maxW: Partial<Record<EdgeType, number>> = {};
  for (const e of nb.edges) maxW[e.type] = Math.max(maxW[e.type] ?? 0, e.weight);
  const norm = (e: GraphEdge) => {
    const m = maxW[e.type] ?? 0;
    return m > 0 ? e.weight / m : 0;
  };

  // Neighbor radius 4–9px by summed per-type-normalized strength.
  const sums = new Map<string, number>();
  for (const e of nb.edges) {
    const nid = otherEnd(e, nb.center);
    sums.set(nid, (sums.get(nid) ?? 0) + norm(e));
  }
  const maxSum = Math.max(0, ...sums.values());

  const nodes: SimNode[] = nb.nodes.map((n) => {
    const isCenter = n.person_id === nb.center;
    const s = maxSum > 0 ? (sums.get(n.person_id) ?? 0) / maxSum : 0;
    return { id: n.person_id, name: n.name, party: n.party, isCenter,
             r: isCenter ? 10 : 4 + 5 * s };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));

  // Seed positions — neighbors on an ellipse around the pinned center — so the
  // first paint is sane and the sim only relaxes, never assembles from (0,0).
  const center = byId.get(nb.center);
  const others = nodes.filter((n) => !n.isCenter);
  others.forEach((n, i) => {
    const ang = (2 * Math.PI * i) / Math.max(1, others.length);
    n.x = CX + 95 * Math.cos(ang);
    n.y = CY + 70 * Math.sin(ang);
  });
  if (center) { center.x = CX; center.y = CY; center.fx = CX; center.fy = CY; }

  // PAIR-DEDUPED sim links: a pair can carry up to 4 typed edges — feeding all
  // of them to forceLink would quadruple attraction. One link per pair, with a
  // combined (mean of per-type-normalized weights) strength driving distance.
  const byPair = new Map<string, GraphEdge[]>();
  for (const e of nb.edges) {
    const k = e.a < e.b ? `${e.a}|${e.b}` : `${e.b}|${e.a}`;
    const list = byPair.get(k);
    if (list) list.push(e); else byPair.set(k, [e]);
  }
  const links: SimLink[] = [];
  const drawn: DrawnEdge[] = [];
  for (const es of byPair.values()) {
    const a = byId.get(es[0].a);
    const b = byId.get(es[0].b);
    if (!a || !b) continue;
    const strength = Math.min(1, es.reduce((t, e) => t + norm(e), 0) / es.length);
    links.push({ source: a, target: b, strength });
    // Rendered edges: ALL typed edges, parallel ones fanned ±3px perpendicular.
    es.forEach((e, i) => {
      drawn.push({ edge: e, key: edgeKey(e), a, b,
                   offset: (i - (es.length - 1) / 2) * 6,
                   width: 1 + 2 * norm(e) });
    });
  }

  const sim = forceSimulation<SimNode>(nodes)
    .force("link", forceLink<SimNode, SimLink>(links)
      .distance((l) => 60 + 40 * (1 - l.strength)))
    .force("charge", forceManyBody().strength(-90))
    .force("collide", forceCollide<SimNode>().radius((n) => n.r + 6))
    .force("x", forceX(CX).strength(0.05))
    .force("y", forceY(CY).strength(0.05))
    .stop();   // never runs on its own; the effect (or the line below) decides
  // Reduced motion: settle synchronously — static positions, zero animation.
  if (reduced) sim.tick(300);

  return { nodes, drawn, sim };
}

const clampX = (v: number | undefined) => Math.max(PAD, Math.min(VB_W - PAD, v ?? CX));
const clampY = (v: number | undefined) => Math.max(PAD, Math.min(VB_H - PAD, v ?? CY));

/** Abbreviated node label: the surname token. */
const lastName = (name: string) => name.trim().split(/\s+/).pop() ?? name;

/** Path for a drawn edge, offset perpendicular to fan parallel typed edges. */
function edgePath(d: DrawnEdge): string {
  const x1 = clampX(d.a.x), y1 = clampY(d.a.y);
  const x2 = clampX(d.b.x), y2 = clampY(d.b.y);
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const px = (-dy / len) * d.offset, py = (dx / len) * d.offset;
  return `M ${(x1 + px).toFixed(1)} ${(y1 + py).toFixed(1)} L ${(x2 + px).toFixed(1)} ${(y2 + py).toFixed(1)}`;
}

/** Edge TYPE → stroke style (color stays neutral; style is the encoding). */
const DASH: Partial<Record<EdgeType, string>> = {
  co_voting: "6 3",
  shared_donor: "1.5 4",
};

/** One typed edge: the visible stroke(s) + an invisible 10px hit-area overlay.
 *  committee draws as a double rule: a (w+2.5)px line-2 path under a w px
 *  surface path, reading as two parallel hairlines. */
function EdgeGlyph({ d, hot, onEnter, onMove, onLeave, onClick }: {
  d: DrawnEdge; hot: boolean;
  onEnter: () => void; onMove: (ev: React.PointerEvent) => void;
  onLeave: () => void; onClick: () => void;
}) {
  const path = edgePath(d);
  const stroke = hot ? "var(--sig)" : "var(--line-2)";
  return (
    <g>
      {d.edge.type === "committee" ? (
        <>
          <path d={path} fill="none" stroke={stroke} strokeWidth={d.width + 2.5} />
          <path d={path} fill="none" stroke="var(--surf)" strokeWidth={d.width} />
        </>
      ) : (
        <path d={path} fill="none" stroke={stroke} strokeWidth={d.width}
              strokeDasharray={DASH[d.edge.type]}
              strokeLinecap={d.edge.type === "shared_donor" ? "round" : undefined} />
      )}
      <path d={path} fill="none" stroke="transparent" strokeWidth={10}
            style={{ cursor: "pointer" }} pointerEvents="stroke"
            onPointerEnter={onEnter} onPointerMove={onMove}
            onPointerLeave={onLeave} onClick={onClick} />
    </g>
  );
}

/** Legend swatch: the same stroke encoding at rest color, 18px wide. */
function LegendSwatch({ type }: { type: EdgeType }) {
  return (
    <svg width="18" height="9" aria-hidden="true" focusable="false">
      {type === "committee" ? (
        <>
          <path d="M0 4.5 H18" stroke="var(--line-2)" strokeWidth={4.5} fill="none" />
          <path d="M0 4.5 H18" stroke="var(--surf)" strokeWidth={2} fill="none" />
        </>
      ) : (
        <path d="M0 4.5 H18" stroke="var(--line-2)" strokeWidth={2} fill="none"
              strokeDasharray={DASH[type]}
              strokeLinecap={type === "shared_donor" ? "round" : undefined} />
      )}
    </svg>
  );
}

const LEGEND: { type: EdgeType; label: string }[] = [
  { type: "cosponsorship", label: "cosponsored bills" },
  { type: "co_voting", label: "votes together" },
  { type: "shared_donor", label: "shared donors" },
  { type: "committee", label: "shared committees" },
];

export function ConnectionsGraph({ nb, onOpenPerson, onSelectEdge }: {
  nb: Neighborhood;
  onOpenPerson: (id: string) => void;
  onSelectEdge: (key: string) => void;
}) {
  const reduced = useMemo(() => prefersReducedMotion(), []);
  const graph = useMemo(() => buildGraph(nb, reduced), [nb, reduced]);
  const [, setFrame] = useState(0);
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; name: string; label: string } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  // Hand-rolled drag state (no d3-drag): the active node + whether the pointer
  // travelled far enough that the trailing click must NOT open a dossier.
  const dragRef = useRef<{ node: SimNode; sx: number; sy: number } | null>(null);
  const movedRef = useRef(false);

  // Normal mode: tick → re-render (a neighborhood is ≤ ~26 nodes; setState per
  // tick is trivial). Reduced motion already settled synchronously in buildGraph.
  useEffect(() => {
    if (reduced) return;
    graph.sim.on("tick", () => setFrame((f) => f + 1)).restart();
    return () => { graph.sim.stop(); };
  }, [graph, reduced]);

  const toSvg = (ev: { clientX: number; clientY: number }) => {
    const r = svgRef.current!.getBoundingClientRect();
    return { x: ((ev.clientX - r.left) / r.width) * VB_W,
             y: ((ev.clientY - r.top) / r.height) * VB_H };
  };

  const onNodeDown = (ev: React.PointerEvent, n: SimNode) => {
    if (reduced) return;   // static mode: no drag
    (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
    const p = toSvg(ev);
    dragRef.current = { node: n, sx: p.x, sy: p.y };
    movedRef.current = false;
    n.fx = n.x;
    n.fy = n.y;
    graph.sim.alphaTarget(0.3).restart();
  };
  const onNodeMove = (ev: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const p = toSvg(ev);
    if (Math.hypot(p.x - d.sx, p.y - d.sy) > 3) movedRef.current = true;
    d.node.fx = p.x;
    d.node.fy = p.y;
  };
  const onNodeUp = () => {
    const d = dragRef.current;
    if (!d) return;
    dragRef.current = null;
    graph.sim.alphaTarget(0);
    // Center stays pinned (where dropped); neighbors rejoin the sim freely.
    if (!d.node.isCenter) { d.node.fx = null; d.node.fy = null; }
  };

  const edgeMove = (ev: React.PointerEvent, d: DrawnEdge) => {
    const r = wrapRef.current!.getBoundingClientRect();
    const neighbor = d.a.isCenter ? d.b : d.a;
    setTip({ x: ev.clientX - r.left, y: ev.clientY - r.top,
             name: neighbor.name, label: edgeLabel(d.edge) });
  };

  const hot = hoverEdge ? graph.drawn.find((d) => d.key === hoverEdge) : undefined;
  const showAllLabels = graph.nodes.length <= 12;

  return (
    <div className="conn-graph" ref={wrapRef}>
      <p className="visually-hidden">
        {STRINGS.connectionsGraphNote.replace("{n}", String(nb.edges.length))}
      </p>
      <svg ref={svgRef} viewBox={`0 0 ${VB_W} ${VB_H}`} aria-hidden="true" focusable="false">
        {graph.drawn.map((d) => (
          <EdgeGlyph key={d.key} d={d} hot={hoverEdge === d.key}
                     onEnter={() => setHoverEdge(d.key)}
                     onMove={(ev) => edgeMove(ev, d)}
                     onLeave={() => { setHoverEdge(null); setTip(null); }}
                     onClick={() => onSelectEdge(d.key)} />
        ))}
        {graph.nodes.map((n) => {
          const cx = clampX(n.x), cy = clampY(n.y);
          const ringHot = !!hot && (hot.a === n || hot.b === n);   // amber ring on a hovered edge's endpoints
          const showLabel = n.isCenter || showAllLabels || hoverNode === n.id || ringHot;
          const glyph = (
            <g style={{ cursor: reduced ? (n.isCenter ? "default" : "pointer") : "grab" }}
               onPointerDown={(ev) => onNodeDown(ev, n)}
               onPointerMove={onNodeMove}
               onPointerUp={onNodeUp}
               onPointerEnter={() => setHoverNode(n.id)}
               onPointerLeave={() => setHoverNode(null)}>
              <circle cx={cx} cy={cy} r={n.r}
                      fill={PARTY_COLORS[n.party] ?? PARTY_COLORS.NP}
                      stroke={ringHot ? "var(--sig)" : n.isCenter ? "#eef4f8" : "none"}
                      strokeWidth={ringHot || n.isCenter ? 2 : 0} />
              {showLabel && (
                <text className={n.isCenter ? "conn-graph-center-label" : undefined}
                      x={cx} y={cy - n.r - 4} textAnchor="middle">
                  {lastName(n.name)}
                </text>
              )}
            </g>
          );
          // Neighbors are real links (middle-click / copy work natively); the
          // SPA click path goes through onOpenPerson. tabIndex −1 keeps the
          // decorative SVG at ZERO tab stops — the list below is the
          // keyboard-reachable equivalent.
          return n.isCenter ? (
            <g key={n.id}>{glyph}</g>
          ) : (
            <a key={n.id} href={personHash(n.id)} tabIndex={-1}
               onClick={(ev) => {
                 ev.preventDefault();
                 if (movedRef.current) { movedRef.current = false; return; }   // drag release ≠ click
                 onOpenPerson(n.id);
               }}>
              {glyph}
            </a>
          );
        })}
      </svg>
      {tip && (
        <div className="conn-graph-tip" style={{ left: tip.x, top: tip.y }}>
          {tip.name} — {tip.label}
        </div>
      )}
      <div className="conn-graph-legend">
        {LEGEND.map((l) => (
          <span key={l.type}><LegendSwatch type={l.type} />{l.label}</span>
        ))}
      </div>
    </div>
  );
}

export default ConnectionsGraph;
