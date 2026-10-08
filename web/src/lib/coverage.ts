/** Coverage: what the pipeline did (coverage.json) and which local divisions it
 *  covers (coverage/{st}.json, contracts 8.10).
 *
 *  A 404 is "nothing published", never an error: a state with no file has no
 *  locality attempted, so every division in it is "not covered yet".
 */
import type { CoverageDivision, CoverageShard, CoverageState } from "../types";
import { DATA, loadCoverage, type Coverage } from "./data";

/** Fetch JSON. 404 -> null and is remembered; any other failure -> null and is retried next time. */
export function getJSONCached<T>(cache: Map<string, Promise<T | null>>, path: string): Promise<T | null> {
  const hit = cache.get(path);
  if (hit) return hit;
  const p = (async () => {
    try {
      const res = await fetch(`${DATA}${path}`);
      if (res.status === 404) return null;
      if (!res.ok) { cache.delete(path); return null; }
      return (await res.json()) as T;
    } catch {
      cache.delete(path);
      return null;
    }
  })();
  cache.set(path, p);
  return p;
}

const shards = new Map<string, Promise<CoverageShard | null>>();

/** States whose shard this session has asked for: the ones the reader has reached. */
export const reachedStates = new Set<string>();

/** One request per state per session. */
export function loadStateCoverage(st: string): Promise<CoverageShard | null> {
  reachedStates.add(st.toLowerCase());
  return getJSONCached(shards, `/coverage/${st.toLowerCase()}.json`);
}

/** The fill / words state of a division. Absence from the shard is "none". */
export type CoverageKey = CoverageState | "none";

export function coverageOf(shard: CoverageShard | null, ocdId: string): CoverageKey {
  return shard?.divisions[ocdId]?.state ?? "none";
}

export function divisionCoverage(shard: CoverageShard | null, ocdId: string): CoverageDivision | null {
  return shard?.divisions[ocdId] ?? null;
}

/** coverage.json as the coverage page reads it. `changed_at` is optional and
 *  per source: when that source's published content last changed (the "unchanged
 *  since" half of contracts 8.1). Absent = the page says only when it was checked. */
export interface CoverageDoc extends Coverage {
  generated_at?: string;
  pipeline_version?: string;
  counts?: Record<string, number>;
  sources?: Record<string, {
    retrieved_at?: string | null; changed_at?: string | null;
    age_hours?: number; sla_hours?: number; within_sla?: boolean;
  } | undefined>;
}

/** coverage.json is fetched once per page load by lib/data; the page reads the same copy. */
export function loadCoverageDoc(): Promise<CoverageDoc | null> {
  return loadCoverage() as Promise<CoverageDoc | null>;
}

/** US state / territory codes the page can list shards for (lowercase USPS). */
export const STATE_CODES = [
  "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi", "id", "il", "in", "ia",
  "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm",
  "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa",
  "wv", "wi", "wy",
] as const;
