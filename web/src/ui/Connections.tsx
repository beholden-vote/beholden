/** Connections view (WO-4): a dossier's entity-graph neighborhood, list-first.
 *
 *  Each connection is a ROW — the connected official, edge chips describing the
 *  tie ("cosponsored 18 bills", "votes together 94%", "3 shared top contributors",
 *  "2 shared committees"), and expandable evidence linking to the source record.
 *  Correlation edges render their `caveat` verbatim (contract requirement). Party
 *  color appears as a data chip only, never as chrome emphasis (DESIGN Rule 0).
 *
 *  This module is dynamic-imported by DossierView so the graph code + the ~one
 *  neighborhood fetch stay out of the main chunk (WO-4: lazy-load). */
import { useEffect, useState } from "react";
import { STRINGS } from "../strings";
import { formatMoneyCents } from "../lib/data";
import { loadNeighborhood, otherEnd, type Evidence, type GraphEdge, type GraphNode, type Neighborhood } from "../lib/graph";
import { EmptyNote, PartyChip } from "./bits";

/** Descriptive chip label per edge type. Symmetric by construction: the same
 *  wording for every official regardless of party (never a value judgement). */
function edgeChipLabel(edge: GraphEdge): string {
  const n = edge.evidence_total;
  switch (edge.type) {
    case "cosponsorship":
      return `cosponsored ${n} bill${n === 1 ? "" : "s"}`;
    case "co_voting":
      return `votes together ${edge.weight}%`;
    case "shared_donor":
      return `${n} shared top contributor${n === 1 ? "" : "s"}`;
    case "committee":
      return `${n} shared committee${n === 1 ? "" : "s"}`;
    default:
      return `${n}`;
  }
}

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
 *  evidence. (The graph is undirected; each edge appears once per neighbor.) */
function ConnectionRow({ edge, node }: { edge: GraphEdge; node: GraphNode | undefined }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="conn-row">
      <button type="button" className="conn-head" aria-expanded={open}
              onClick={() => setOpen((v) => !v)}>
        <span className="conn-caret" aria-hidden>{open ? "▾" : "▸"}</span>
        <span className="conn-name">{node?.name ?? "Unknown official"}</span>
        {node && <PartyChip code={node.party} />}
        <span className="conn-chip">{edgeChipLabel(edge)}</span>
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
        </div>
      )}
    </li>
  );
}

export function Connections({ personId }: { personId: string }) {
  const [state, setState] = useState<{ loading: boolean; data: Neighborhood | null }>(
    { loading: true, data: null });

  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, data: null });
    loadNeighborhood(personId).then((data) => {
      if (!cancelled) setState({ loading: false, data });
    });
    return () => { cancelled = true; };
  }, [personId]);

  if (state.loading) return <EmptyNote>{STRINGS.connectionsLoading}</EmptyNote>;
  const nb = state.data;
  if (!nb || nb.edges.length === 0) return <EmptyNote>{STRINGS.connectionsEmpty}</EmptyNote>;

  const nodeById = new Map(nb.nodes.map((n) => [n.person_id, n]));
  return (
    <>
      <ul className="conn-list">
        {nb.edges.map((edge, i) => (
          <ConnectionRow key={`${edge.type}-${edge.a}-${edge.b}-${i}`}
                         edge={edge} node={nodeById.get(otherEnd(edge, nb.center))} />
        ))}
      </ul>
      <p className="muted conn-foot">{STRINGS.connectionsNote}</p>
    </>
  );
}

export default Connections;
