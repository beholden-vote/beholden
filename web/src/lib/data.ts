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
