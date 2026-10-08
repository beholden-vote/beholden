/** Loaders for the votes artifacts (contracts 8.3). One object per call, fetched
 *  on open and cached like loadDossier. Nothing here lists or enumerates them.
 *  A 404 is "not published", returned as null -- never an error. */
import type { Bill, PersonVotes, RollCall } from "../types";
import { DATA } from "./data";

// 8.3: ids use only [a-z0-9/._-]. Anything else is refused before it becomes a
// request path (fail closed), and so is a dot-segment.
const SAFE_ID = /^[a-z0-9/._-]+$/;
const okId = (id: string) => SAFE_ID.test(id) && !id.split("/").some((s) => s === "" || s === "." || s === "..");

function cached<T>(dir: string, validId: (id: string) => boolean) {
  const hits = new Map<string, T>();
  return async (id: string): Promise<T | null> => {
    const hit = hits.get(id);
    if (hit) return hit;
    if (!validId(id)) return null;
    try {
      const res = await fetch(`${DATA}/${dir}/${id}.json`);
      if (!res.ok) return null;
      const body = (await res.json()) as T;
      hits.set(id, body);
      return body;
    } catch {
      return null;
    }
  };
}

// A person id is a bare uuid: no slashes.
export const loadVotes = cached<PersonVotes>("votes", (id) => okId(id) && !id.includes("/"));
export const loadRollCall = cached<RollCall>("rollcalls", okId);
export const loadBill = cached<Bill>("bills", okId);

/** "us/119/hr/2384" -> congress.gov search-free fallback link for a bill with no page. */
export function congressGovUrl(billId: string): string | null {
  const m = /^us\/(\d+)\/(hr|s|hjres|sjres|hconres|sconres|hres|sres)\/(\d+)$/.exec(billId);
  if (!m) return null;
  const kind = { hr: "house-bill", s: "senate-bill", hjres: "house-joint-resolution", sjres: "senate-joint-resolution",
    hconres: "house-concurrent-resolution", sconres: "senate-concurrent-resolution", hres: "house-resolution", sres: "senate-resolution" }[m[2]]!;
  const n = Number(m[1]);
  const sfx = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `https://www.congress.gov/bill/${n}${sfx}-congress/${kind}/${m[3]}`;
}
