/** Connections view (WO-4, WO-13): a dossier's entity-graph neighborhood —
 *  list-first, with an interactive force graph above it as a spatial lens.
 *
 *  Each connection is a ROW — the connected official, edge chips describing the
 *  tie ("cosponsored 18 bills", "votes together 94%", "3 shared top contributors",
 *  "2 shared committees"), and expandable evidence linking to the source record.
 *  Correlation edges render their `caveat` verbatim (contract requirement). Party
 *  color appears as a data chip only, never as chrome emphasis (DESIGN Rule 0).
 *
 *  WO-13: the graph (ConnectionsGraph, statically imported so d3-force lands in
 *  THIS lazy chunk) renders above the list when there are ≥3 edges. The list
 *  stays canonical and cited; the SVG is decorative. Row expansion is hoisted
 *  here so an edge click in the graph can expand + scroll to its row, and every
 *  expanded row carries an "Open dossier →" link — the list can do everything
 *  the graph can.
 *
 *  This module is dynamic-imported by DossierView so the graph code + the ~one
 *  neighborhood fetch stay out of the main chunk (WO-4: lazy-load). */
import { useEffect, useRef, useState } from "react";
import { STRINGS } from "../strings";
import { formatMoneyCents } from "../lib/data";
import { edgeKey, edgeLabel, loadNeighborhood, otherEnd, type Evidence, type GraphEdge, type GraphNode, type Neighborhood } from "../lib/graph";
import { personHash } from "../router";
import { EmptyNote, PartyChip } from "./bits";
import { ConnectionsGraph, prefersReducedMotion } from "./ConnectionsGraph";

/** One evidence line — a checkable receipt. Bills/roll calls link to the official
 *  record; committees and FEC rollups name the shared entity. */
function EvidenceRow({ ev }: { ev: Evidence }) {
  if (ev.kind === "bill" || ev.kind === "roll_call") {
    const label = ev.kind === "bill" ? ev.id : `Roll call ${ev.id}`;
    return ev.url ? (
      <a href={ev.url} target="_blank" rel="noopener noreferrer">{label} ↗</a>
    ) : (
      <span>{label}</span>
    );
  }
  if (ev.kind === "committee") {
    return <span>{ev.name ?? ev.id}</span>;
  }
  // fec_employer: name + both members' reported totals.
  return (
    <span>
      {ev.name}
      <span className="muted"> · {formatMoneyCents(ev.a_total_cents)} / {formatMoneyCents(ev.b_total_cents)}</span>
    </span>
  );
}

/** A single connection: one edge to one other official, expandable to its
 *  evidence. (The graph is undirected; each edge appears once per neighbor.)
 *  WO-13: expansion is CONTROLLED (open/onToggle) so the force graph can
 *  address rows; `flash` paints the transient amber left rule after an edge
 *  click routed here from the graph. */
function ConnectionRow({ edge, node, open, onToggle, onOpenPerson, flash, rowRef }: {
  edge: GraphEdge;
  node: GraphNode | undefined;
  open: boolean;
  onToggle: () => void;
  onOpenPerson: (id: string) => void;
  flash: boolean;
  rowRef: (el: HTMLLIElement | null) => void;
}) {
  return (
    <li className={`conn-row${flash ? " is-flash" : ""}`} ref={rowRef}>
      <button type="button" className="conn-head" aria-expanded={open} onClick={onToggle}>
        <span className="conn-caret" aria-hidden>{open ? "▾" : "▸"}</span>
        <span className="conn-name">{node?.name ?? "Unknown official"}</span>
        {node && <PartyChip code={node.party} />}
        <span className="conn-chip">{edgeLabel(edge)}</span>
      </button>
      {node?.office_display && <p className="conn-office">{node.office_display}</p>}
      {open && (
        <div className="conn-detail">
          <p className="conn-window muted">{edge.window}</p>
          <ul className="conn-evidence">
            {edge.evidence.map((ev, i) => (
              <li key={i}><EvidenceRow ev={ev} /></li>
            ))}
          </ul>
          {edge.evidence_total > edge.evidence.length && (
            <p className="muted conn-more">
              {STRINGS.connectionsEvidenceMore.replace("{n}", String(edge.evidence_total))}
            </p>
          )}
          {edge.method && <p className="muted conn-method">{edge.method}</p>}
          {edge.caveat && <p className="conn-caveat">{edge.caveat}</p>}
          {node && (
            <p className="links">
              <a href={personHash(node.person_id)}
                 onClick={(e) => { e.preventDefault(); onOpenPerson(node.person_id); }}>
                {STRINGS.connectionsOpenDossier}
              </a>
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function Connections({ personId, onOpenPerson }: {
  personId: string;
  /** Opens a neighbor's dossier in-app (threaded App → DossierView → here).
   *  Falls back to plain hash navigation — the router resolves it the same. */
  onOpenPerson?: (id: string) => void;
}) {
  const [state, setState] = useState<{ loading: boolean; data: Neighborhood | null }>(
    { loading: true, data: null });
  // Expansion, hoisted (WO-13) and keyed by edgeKey — the shared identity the
  // graph's onSelectEdge speaks. rowRefs lets an edge click scroll to its row.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [flashKey, setFlashKey] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLLIElement>());
  const flashTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, data: null });
    setExpanded(new Set());
    setFlashKey(null);
    loadNeighborhood(personId).then((data) => {
      if (!cancelled) setState({ loading: false, data });
    });
    return () => { cancelled = true; };
  }, [personId]);
  useEffect(() => () => window.clearTimeout(flashTimer.current), []);

  const openPerson = onOpenPerson ?? ((id: string) => { location.hash = personHash(id); });

  const toggle = (key: string) => setExpanded((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  /** Graph edge click → expand its row, scroll it into view, flash it. */
  const selectEdge = (key: string) => {
    setExpanded((prev) => new Set(prev).add(key));
    const reduced = prefersReducedMotion();
    // Scroll after the expansion commits so the opened detail is measured.
    requestAnimationFrame(() => {
      rowRefs.current.get(key)?.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
    });
    if (!reduced) {
      setFlashKey(key);
      window.clearTimeout(flashTimer.current);
      flashTimer.current = window.setTimeout(() => setFlashKey(null), 1200);
    }
  };

  if (state.loading) return <EmptyNote>{STRINGS.connectionsLoading}</EmptyNote>;
  const nb = state.data;
  if (!nb || nb.edges.length === 0) return <EmptyNote>{STRINGS.connectionsEmpty}</EmptyNote>;

  const nodeById = new Map(nb.nodes.map((n) => [n.person_id, n]));
  return (
    <>
      {/* The spatial lens earns its pixels only with enough structure to show;
          1–2 edges read better as the list alone. */}
      {nb.edges.length >= 3 && (
        <ConnectionsGraph nb={nb} onOpenPerson={openPerson} onSelectEdge={selectEdge} />
      )}
      <ul className="conn-list">
        {nb.edges.map((edge) => {
          const key = edgeKey(edge);
          return (
            <ConnectionRow key={key} edge={edge} node={nodeById.get(otherEnd(edge, nb.center))}
                           open={expanded.has(key)} onToggle={() => toggle(key)}
                           onOpenPerson={openPerson} flash={flashKey === key}
                           rowRef={(el) => {
                             if (el) rowRefs.current.set(key, el);
                             else rowRefs.current.delete(key);
                           }} />
          );
        })}
      </ul>
      <p className="muted conn-foot">{STRINGS.connectionsNote}</p>
    </>
  );
}

export default Connections;
