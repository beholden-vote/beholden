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
  { level: "Local", layers: ["county"] },
];
