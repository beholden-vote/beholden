/** Position profile data (contracts 8.7, WO-38): the loader, the colour ramp and the
 *  map colour-mode store. One file per chamber, fetched on first need and cached; a
 *  404 is "not published" (null), never an error. No score, rank or label lives here:
 *  every function treats every member and both parties identically. */
import type { PositionMember, PositionsFile } from "../types";
import { DATA } from "./data";

export type Chamber = "house" | "senate";

const files = new Map<Chamber, Promise<PositionsFile | null>>();
export function loadPositions(chamber: Chamber): Promise<PositionsFile | null> {
  let p = files.get(chamber);
  if (!p) {
    p = fetch(`${DATA}/positions/${chamber}.json`)
      .then((r) => (r.ok ? (r.json() as Promise<PositionsFile>) : null))
      .catch(() => null);
    files.set(chamber, p);
  }
  return p;
}

export interface Found { file: PositionsFile; member: PositionMember }
/** The member and the file that holds them. The House file is read first, then the
 *  Senate's; each is fetched at most once per session, never one request per member. */
export async function findMember(personId: string): Promise<Found | null> {
  for (const c of ["house", "senate"] as const) {
    const file = await loadPositions(c);
    const member = file?.members.find((m) => m.person_id === personId);
    if (file && member) return { file, member };
  }
  return null;
}

/* ── Colour ramp (DESIGN.md "Position ramp") ───────────────────────────────────
 * Generated and checked by ui/stand/ramp.check.mjs: nine stops at one OKLab lightness
 * (relative luminance 0.27-0.29), the same chroma at both ends, neutral grey in the
 * middle. Cool violet to olive is a blue-yellow axis, which protan and deutan viewers
 * keep. It is not a party hue and neither end is louder. */
export const RAMP = ["#a47dcf", "#9f83c1", "#9b89b1", "#968ea2", "#929292", "#96937d", "#9b9467", "#a0944c", "#a49325"];

const rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
/** t in [-1, 1] (-1 = low end, 0 = midpoint, 1 = high end) -> hex. */
export function rampColor(t: number): string {
  const x = ((Math.max(-1, Math.min(1, t)) + 1) / 2) * (RAMP.length - 1);
  const i = Math.min(RAMP.length - 2, Math.floor(x));
  const a = rgb(RAMP[i]), b = rgb(RAMP[i + 1]), f = x - i;
  return "#" + a.map((v, k) => Math.round(v + (b[k] - v) * f).toString(16).padStart(2, "0")).join("");
}

/* ── Map colour modes ──────────────────────────────────────────────────────── */
export type ColourMode = "party" | "position" | "own_party";
export const COLOUR_MODES: ColourMode[] = ["party", "position", "own_party"];

/** The value a mode colours by; null where the file publishes none. */
export function modeValue(m: PositionMember, mode: ColourMode): number | null {
  if (mode === "position") return m.nominate?.dim1 ?? null;
  if (mode === "own_party") return m.measures.with_own_party?.pct ?? null;
  return null;
}

export interface Scale { mid: number; half: number; lo: number; hi: number }
/** Position: the fixed Voteview axis, midpoint 0. With-own-party: midpoint is the
 *  chamber's median rate (stated in the legend), the ends are the furthest member
 *  from it, so the ramp spreads over the values that exist. */
export function scaleFor(mode: ColourMode, members: PositionMember[]): Scale {
  if (mode === "position") return { mid: 0, half: 1, lo: -1, hi: 1 };
  const v = members.map((m) => modeValue(m, mode)).filter((x): x is number => x !== null).sort((a, b) => a - b);
  if (!v.length) return { mid: 50, half: 50, lo: 0, hi: 100 };
  const mid = v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2;
  const half = Math.max(1e-6, mid - v[0], v[v.length - 1] - mid);
  return { mid, half, lo: mid - half, hi: mid + half };
}
export const colourFor = (value: number, s: Scale) => rampColor((value - s.mid) / s.half);

export interface ColourState {
  mode: ColourMode;
  status: "idle" | "loading" | "ready" | "unavailable";
  /** U.S. House districts coloured by value / falling back to party colour. */
  placed: number; fallback: number;
  scale: Scale | null;
}
const KEY = "beholden.colourMode";
function initialMode(): ColourMode {
  try { const v = localStorage.getItem(KEY); if (COLOUR_MODES.includes(v as ColourMode)) return v as ColourMode; } catch { /* ok */ }
  return "party";
}
let state: ColourState = { mode: initialMode(), status: "idle", placed: 0, fallback: 0, scale: null };
const subs = new Set<() => void>();
export const colourState = () => state;
export function subscribeColour(fn: () => void) { subs.add(fn); return () => { subs.delete(fn); }; }
function set(next: Partial<ColourState>) { state = { ...state, ...next }; subs.forEach((f) => f()); }
export function setColourMode(mode: ColourMode) {
  try { localStorage.setItem(KEY, mode); } catch { /* ok */ }
  set({ mode, status: mode === "party" ? "idle" : "loading", placed: 0, fallback: 0, scale: null });
}
export const reportColour = (r: Pick<ColourState, "status" | "placed" | "fallback" | "scale">) => set(r);

let cdPeople: Promise<Map<string, string>> | undefined;
/** ocd_id -> person_id for the U.S. House pins (the stylefeed carries no person id). */
export function loadCdPeople(): Promise<Map<string, string>> {
  cdPeople ??= fetch(`${DATA}/pins/cd.json`)
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => [])
    .then((rows: { ocd_id: string; person_id: string; vacant?: boolean }[]) =>
      new Map(rows.filter((p) => !p.vacant).map((p) => [p.ocd_id, p.person_id])));
  return cdPeople;
}

/** Decided votes both members cast on the same roll calls, and how many matched
 *  (yea/nay only, shared roll calls only). */
export function agreement(a: { roll_call_id: string; position: string }[], b: { roll_call_id: string; position: string }[]) {
  const bm = new Map(b.map((v) => [v.roll_call_id, v.position]));
  let shared = 0, same = 0;
  for (const v of a) {
    const w = bm.get(v.roll_call_id);
    if ((v.position !== "yea" && v.position !== "nay") || (w !== "yea" && w !== "nay")) continue;
    shared++;
    if (v.position === w) same++;
  }
  return { n: same, of: shared, pct: shared ? Math.round((same / shared) * 1000) / 10 : null };
}
