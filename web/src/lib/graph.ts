/** Entity-graph neighborhood fetch + types (WO-4, contract §4).
 *
 *  A neighborhood is served static at /graph/neighborhood/{person_id}.json — the
 *  same zero-server model as dossiers. Every edge carries evidence (an edge with
 *  no receipts is a bug); correlation edges carry a `caveat` that MUST render.
 *  Kept out of the main bundle: the Connections view dynamic-imports this + its
 *  component so a dossier that never opens Connections never pays for the graph. */
import type { Provenance } from "../types";

/** A node in a neighborhood: one connected official. `party` is data-only (map
 *  colors), never chrome emphasis (DESIGN Rule 0). */
export interface GraphNode {
  person_id: string;
  name: string;
  party: string;
  office_display: string;
  ideology_dim1: number | null;
}

/** One piece of receipts under an edge. Shape varies by edge type but always
 *  points at something checkable (a bill, a roll call, an FEC rollup, a committee). */
export type Evidence =
  | { kind: "bill"; id: string; url: string | null }
  | { kind: "roll_call"; id: string; url: string | null }
  | { kind: "committee"; id: string; name: string | null }
  | { kind: "fec_employer"; name: string; a_total_cents: number; b_total_cents: number };

export type EdgeType = "cosponsorship" | "co_voting" | "shared_donor" | "committee";

/** A typed, evidence-carrying edge between two officials. `weight` is
 *  type-specific: shared-bill count / agreement % / shared-committee count /
 *  shared-donor count. `caveat`, when present, renders verbatim. */
export interface GraphEdge {
  type: EdgeType;
  a: string;
  b: string;
  weight: number;
  window: string;
  evidence: Evidence[];
  evidence_total: number;
  caveat?: string;
  method?: string;   // co_voting: the agreement formula, stated for reproducibility
  cycle?: number;    // shared_donor: the FEC cycle the rollups are from
}

export interface Neighborhood {
  center: string;
  as_of: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Contract §1 optional: a graph-level envelope may accompany the doc. */
  provenance?: Provenance;
}

const DATA = import.meta.env.VITE_DATA_BASE ?? "https://data.beholden.vote";
const cache = new Map<string, Neighborhood | null>();

/** Fetch a member's neighborhood. Returns null on any failure or absence — the
 *  Connections view then shows an honest empty state and never throws. Cached so
 *  reopening the same dossier's Connections is free. */
export async function loadNeighborhood(personId: string): Promise<Neighborhood | null> {
  if (cache.has(personId)) return cache.get(personId) ?? null;
  let doc: Neighborhood | null = null;
  try {
    const res = await fetch(`${DATA}/graph/neighborhood/${encodeURIComponent(personId)}.json`);
    doc = res.ok ? ((await res.json()) as Neighborhood) : null;
  } catch {
    doc = null;
  }
  cache.set(personId, doc);
  return doc;
}

/** The other endpoint of an edge relative to a center person. */
export function otherEnd(edge: GraphEdge, center: string): string {
  return edge.a === center ? edge.b : edge.a;
}

/** Canonical identity for an edge, shared by the list rows and the WO-13 graph:
 *  a graph click addresses its list row by this exact string. */
export function edgeKey(e: GraphEdge): string {
  return `${e.type}:${e.a}:${e.b}`;
}

/** Descriptive label per edge type (moved from Connections.tsx for WO-13: the
 *  list chips and the graph tooltip share one wording). Symmetric by
 *  construction: the same phrasing for every official regardless of party —
 *  a count or a percentage, never a value judgement. */
export function edgeLabel(edge: GraphEdge): string {
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
