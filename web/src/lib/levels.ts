/** Level-of-government axis, shared by the stack panel and the ballot (WO-22).
 *
 *  These two tables were duplicated verbatim in App.tsx and Ballot.tsx. Adding a
 *  level to one and not the other produced no error — the ballot silently sorted
 *  the new level last and labelled it by raw layer id — so they live here now and
 *  a new level is one edit, not two.
 */
import { LAYERS, type LayerId } from "../map";

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
  { level: "Local", layers: ["county"] },
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

/** Lowest fade-in zoom among a gate's layers (0 for always-on federal levels). */
function gateZoom(layers: LayerId[]): number {
  const starts = layers
    .map((id) => LAYERS.find((L) => L.id === id)?.autoFade?.start)
    .filter((z): z is number => typeof z === "number");
  return starts.length ? Math.min(...starts) : 0;
}

export const GATES: Gate[] = [
  { id: "federal", label: "Federal", layers: ["cd", "states"],
    minzoom: gateZoom(["cd", "states"]), blurb: "U.S. House · U.S. Senate" },
  { id: "state", label: "State", layers: ["sldu", "sldl"],
    minzoom: gateZoom(["sldu", "sldl"]), blurb: "Both state chambers" },
  { id: "county", label: "County", layers: ["county"],
    minzoom: gateZoom(["county"]), blurb: "County commissions" },
  // Cities publish officials (a mayor and a board of aldermen are in the data
  // today) but no incorporated-place geometry exists yet, so there is nothing
  // to draw or click. Listed anyway, and labelled as unmapped: a level we cover
  // but cannot yet show is a fact about coverage, not something to hide.
  { id: "place", label: "City", layers: [], minzoom: null,
    blurb: "Awaiting place boundaries" },
];

/** The deepest mapped level currently on screen. */
export function gateForZoom(zoom: number): Gate {
  let active = GATES[0];
  for (const g of GATES) {
    if (g.minzoom !== null && zoom >= g.minzoom) active = g;
  }
  return active;
}
