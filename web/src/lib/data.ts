/** Data access for the published contracts: pins, dossiers (contracts §3).
 *  Everything is static JSON on the CDN — cache aggressively, degrade to empty. */
import type { Dossier, Pin } from "../types";

export const DATA = import.meta.env.VITE_DATA_BASE ?? "https://data.beholden.vote";

async function fetchJSON<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${DATA}${path}`);
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

/** layer feed id -> (ocd_id -> pins at that division). Senate = 2 per state. */
export type PinIndex = Map<string, Map<string, Pin[]>>;

const PIN_FEEDS = ["states", "cd", "sldu", "sldl"] as const;

export async function loadPins(): Promise<PinIndex> {
  const index: PinIndex = new Map();
  await Promise.all(
    PIN_FEEDS.map(async (feed) => {
      const rows = (await fetchJSON<Pin[]>(`/pins/${feed}.json`)) ?? [];
      const byOcd = new Map<string, Pin[]>();
      for (const p of rows) {
        const list = byOcd.get(p.ocd_id) ?? [];
        list.push(p);
        byOcd.set(p.ocd_id, list);
      }
      index.set(feed, byOcd);
    }),
  );
  return index;
}

/** One row of the flat people search index (WO-5): search/people.json, emitted
 *  by the build for every current officeholder. Just enough to rank a name match
 *  and jump to the dossier — no dossier fan-out until a person is picked. */
export interface PersonSearchRow {
  person_id: string;
  full_name: string;
  office: string;
  party: string;
  ocd_id: string;
}

/** A ready-to-query people index: name ranking + id lookup. */
export interface PeopleIndex {
  /** Ranked name matches, best first, capped at `limit`. */
  search(query: string, limit?: number): PersonSearchRow[];
  /** person_id -> row, for resolving a #/p/ deep-link to a name/office. */
  byId(personId: string): PersonSearchRow | undefined;
}

/** Lazy people-index loader. The index (~500KB) plus minisearch are pulled only
 *  on the first name query (keeps the main chunk lean, per the WO), then cached.
 *  minisearch is dynamically imported here so it code-splits out of the initial
 *  bundle. Returns null if the index is unavailable — search then degrades to
 *  address-only and never throws. */
let peopleSearchPromise: Promise<PeopleIndex | null> | null = null;

export function loadPeopleIndex(): Promise<PeopleIndex | null> {
  peopleSearchPromise ??= buildPeopleIndex();
  return peopleSearchPromise;
}

async function buildPeopleIndex(): Promise<PeopleIndex | null> {
  const [rows, { default: MiniSearch }] = await Promise.all([
    fetchJSON<PersonSearchRow[]>("/search/people.json"),
    import("minisearch"),
  ]);
  if (!rows || rows.length === 0) return null;
  const byId = new Map(rows.map((r) => [r.person_id, r]));
  const mini = new MiniSearch<PersonSearchRow>({
    idField: "person_id",
    fields: ["full_name", "office"],   // office lets "senator tennessee" resolve too
    storeFields: ["person_id"],
    searchOptions: { prefix: true, fuzzy: 0.2, boost: { full_name: 3 } },
  });
  mini.addAll(rows);
  return {
    search(query, limit = 6) {
      return mini.search(query).slice(0, limit)
        .map((r) => byId.get(String(r.id)))
        .filter((r): r is PersonSearchRow => !!r);
    },
    byId: (personId) => byId.get(personId),
  };
}

const dossierCache = new Map<string, Dossier>();

export async function loadDossier(personId: string): Promise<Dossier | null> {
  const hit = dossierCache.get(personId);
  if (hit) return hit;
  const d = await fetchJSON<Dossier>(`/dossiers/${personId}.json`);
  if (d) dossierCache.set(personId, d);
  return d;
}

/** True when the legislative section is the pre-E2 stub (counts all zero and
 *  no items) — rendered as "syncing", never as a factual zero. */
export function legislativeIsStub(d: Dossier): boolean {
  const l = d.legislative;
  if (!l) return false;
  return (
    l.counts.sponsored === 0 &&
    l.counts.cosponsored === 0 &&
    l.counts.became_law === 0 &&
    l.recent_bills.length === 0 &&
    l.key_votes.length === 0
  );
}

export function formatMoneyCents(cents: number): string {
  const dollars = cents / 100;
  if (Math.abs(dollars) >= 1_000_000) return `$${(dollars / 1_000_000).toFixed(1)}M`;
  if (Math.abs(dollars) >= 1_000) return `$${Math.round(dollars / 1_000)}K`;
  return `$${dollars.toFixed(0)}`;
}

export function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

/** "TN-6" / "AK-AL" / state name tail from an ocd_id, for compact labels. */
export function ocdShortLabel(ocdId: string): string {
  const state = /state:(\w\w)/.exec(ocdId)?.[1]?.toUpperCase() ?? "?";
  const cd = /cd:(\d+)/.exec(ocdId)?.[1];
  const sldu = /sldu:([\w-]+)/.exec(ocdId)?.[1];
  const sldl = /sldl:([\w-]+)/.exec(ocdId)?.[1];
  if (cd) return `${state}-${cd}`;
  if (sldu) return `${state} Senate ${sldu.toUpperCase()}`;
  if (sldl) return `${state} House ${sldl.toUpperCase()}`;
  return state;
}
