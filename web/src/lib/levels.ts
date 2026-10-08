/** Level-of-government axis, shared by the stack panel and the ballot (WO-22).
 *
 *  These two tables were duplicated verbatim in App.tsx and Ballot.tsx. Adding a
 *  level to one and not the other produced no error — the ballot silently sorted
 *  the new level last and labelled it by raw layer id — so they live here now and
 *  a new level is one edit, not two.
 */
import type { LayerId } from "../map";

export const LEVEL_TITLES: Record<string, string> = {
  cd: "U.S. House",
  states: "U.S. Senate",
  sldu: "State Senate",
  sldl: "State House",
  county: "County",
  place: "City",
};

/** Federal first, most-local last: the order a ballot is read in. */
export const LEVEL_ORDER: Record<string, number> = {
  cd: 0, states: 1, sldu: 2, sldl: 3, county: 4, place: 5,
};

/** Panel sections mirror the layer control's level axis. */
export const PANEL_SECTIONS: { level: string; layers: LayerId[] }[] = [
  { level: "Federal", layers: ["cd", "states"] },
  { level: "State", layers: ["sldu", "sldl"] },
  { level: "Local", layers: ["county", "place"] },
];

/* ── Zoom gates ───────────────────────────────────────────────────────────────
 *
 * Zooming in hands the map from one level of government to the next. That
 * handover already happened — the state and county fades have always been there —
 * but nothing ever SAID so, which is why zooming felt like layers arriving at
 * random rather than a deliberate descent from federal to local.
 *
 * A gate's zoom is DERIVED from the layer fades rather than restated, because
 * two copies of "6" drift the moment someone retunes a fade and the UI then
 * announces a level that isn't on screen yet.
 */
export type GateId = "federal" | "state" | "county" | "place";

export interface Gate {
  id: GateId;
  label: string;
  /** Zoom at which this level's geometry begins to appear; null = not mapped. */
  minzoom: number | null;
  layers: LayerId[];
  /** What the reader gains at this gate — shown in the level rail. */
  blurb: string;
}

/* ── The zoom table: ONE place for every boundary show/hide number ─────────────
 *
 * One PRIMARY boundary level per zoom band, drawn at full strength; the level it
 * replaces recedes to a faint REFERENCE line and then fades out. Each row is a
 * list of [zoom, primary, reference] stops, linearly interpolated: `primary` is
 * 0..1 (fill + solid line), `reference` is the opacity of the thin dashed-or-faint
 * line. map.ts paints from this table and GATES below derives from it, so the
 * rail, the toast and the map can never disagree.
 *
 * Fading out is visual only: a level past its band keeps hit-testing, so a click
 * at city zoom still lists the state legislators and the U.S. House member.
 * Below its fade-in a chamber/county/city layer is hidden (as before).
 */
export type BandStop = [zoom: number, primary: number, reference: number];
export const BANDS: Record<LayerId, BandStop[]> = {
  states: [[0, 1, 0]],
  cd:     [[0, 1, 0], [6, 1, 0], [7, 0, 0]],
  sldu:   [[6, 0, 0], [7, 1, 0], [8, 1, 0], [9, 0, 0.35], [10.5, 0, 0]],
  sldl:   [[6, 0, 0], [7, 1, 0], [8, 1, 0], [9, 0, 0.35], [10.5, 0, 0]],
  county: [[8, 0, 0], [9, 1, 0], [10, 1, 0], [11, 0, 0.4]],
  place:  [[10, 0, 0], [11, 1, 0]],
};

/** Zoom at which a layer first has any strength (0 = always on). */
export function bandStart(id: LayerId): number {
  const stops = BANDS[id];
  const i = stops.findIndex(([, p, r]) => p > 0 || r > 0);
  return i <= 0 ? 0 : stops[i - 1][0];
}

/** Interpolated primary / reference strength of a layer at a zoom. */
export function bandAt(id: LayerId, z: number): { primary: number; ref: number } {
  const st = BANDS[id];
  if (z <= st[0][0]) return { primary: st[0][1], ref: st[0][2] };
  for (let i = 1; i < st.length; i++) {
    if (z <= st[i][0]) {
      const t = (z - st[i - 1][0]) / (st[i][0] - st[i - 1][0]);
      return {
        primary: st[i - 1][1] + t * (st[i][1] - st[i - 1][1]),
        ref: st[i - 1][2] + t * (st[i][2] - st[i - 1][2]),
      };
    }
  }
  const last = st[st.length - 1];
  return { primary: last[1], ref: last[2] };
}

/** Lowest first-strength zoom among a gate's layers (0 for always-on federal levels). */
function gateZoom(layers: LayerId[]): number {
  return Math.min(...layers.map(bandStart));
}

export const GATES: Gate[] = [
  { id: "federal", label: "Federal", layers: ["cd", "states"],
    minzoom: gateZoom(["cd", "states"]), blurb: "U.S. House · U.S. Senate" },
  { id: "state", label: "State", layers: ["sldu", "sldl"],
    minzoom: gateZoom(["sldu", "sldl"]), blurb: "Both state chambers" },
  { id: "county", label: "County", layers: ["county"],
    minzoom: gateZoom(["county"]), blurb: "County commissions" },
  // WO-37: incorporated-place boundaries (contracts 8.5) are mapped.
  { id: "place", label: "City", layers: ["place"],
    minzoom: gateZoom(["place"]), blurb: "City councils" },
];

/** The deepest mapped level currently on screen. */
export function gateForZoom(zoom: number): Gate {
  let active = GATES[0];
  for (const g of GATES) {
    if (g.minzoom !== null && zoom >= g.minzoom) active = g;
  }
  return active;
}
