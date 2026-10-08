/** Area facts (contracts 8.4): /areas/{level}/{st}.json, one file per state per
 *  level, joined to the clicked polygon by GEOID. 404 = nothing published. */
import type { AreaFacts, AreasFile } from "../types";
import { getJSONCached } from "./coverage";

const files = new Map<string, Promise<AreasFile | null>>();

export function loadAreas(level: "county" | "place", st: string): Promise<AreasFile | null> {
  return getJSONCached(files, `/areas/${level}/${st.toLowerCase()}.json`);
}

export interface AreaLookup { file: AreasFile; facts: AreaFacts }

/** The facts for one polygon, or null when the file or the GEOID is absent. */
export async function loadAreaFacts(level: "county" | "place", st: string, geoid: string): Promise<AreaLookup | null> {
  const file = await loadAreas(level, st);
  const facts = file?.areas[geoid];
  return file && facts ? { file, facts } : null;
}
