/** Naming and addressing a place.
 *
 *  A place is the set of divisions under one point -- a congressional district,
 *  a state, two state-legislative districts, a county -- plus who holds office
 *  in each. Everything here is derived from what the tiles and the OCD ids
 *  already carry: formatting, never a new fact.
 */
import type { LayerId, RawStackHit } from "../../map";
import type { DivisionProps } from "../../types";
import { ocdShortLabel } from "../../lib/data";

/** The pin feed (and map layer) a division id belongs to. */
export function layerOfOcd(ocdId: string): LayerId | null {
  if (/\/sldu:/.test(ocdId)) return "sldu";
  if (/\/sldl:/.test(ocdId)) return "sldl";
  if (/\/(county|parish|borough):/.test(ocdId)) return "county";
  if (/\/cd:/.test(ocdId)) return "cd";
  if (/\/state:[a-z]{2}$/.test(ocdId)) return "states";
  return null;
}

const stateOf = (ocdId: string) => /state:(\w\w)/.exec(ocdId)?.[1]?.toUpperCase() ?? "";

/** A human name for a division, built only from what the tile carries
 *  (spike/stamp_ocd_ids.py, feature_props).
 *
 *  States and counties ship a real `name`. Districts do not and never will -- a
 *  congressional district has no name, only a number -- so theirs is composed
 *  from `state` + `district_num`. Nothing here reaches for a fact the tile
 *  doesn't hold: no population, no area. Those need a source.
 */
export function divisionName(layer: LayerId, props: DivisionProps, ocdId: string): string {
  const st = props.state ?? stateOf(ocdId);
  const n = props.district_num;
  if (layer === "states") return props.name ?? st;
  if (layer === "cd") {
    if (props.at_large) return `${st} at-large congressional district`;
    return n ? `${st}-${n} congressional district` : "Congressional district";
  }
  if (layer === "sldu") return n ? `${st} Senate district ${n}` : `${st} Senate district`;
  if (layer === "sldl") return n ? `${st} House district ${n}` : `${st} House district`;
  if (layer === "county") {
    // TIGER ships the bare name ("Sumner"); the OCD path knows whether this
    // state calls them counties, parishes or boroughs.
    const kind = /\/(county|parish|borough):/.exec(ocdId)?.[1] ?? "county";
    const word = kind.charAt(0).toUpperCase() + kind.slice(1);
    return props.name ? `${props.name} ${word}` : ocdShortLabel(ocdId);
  }
  return ocdShortLabel(ocdId);
}

/** Most local first. Not the ballot's reading order (lib/levels.ts puts the
 *  U.S. House ahead of the state): a congressional district is smaller than the
 *  state it sits in. */
const MOST_LOCAL: LayerId[] = ["county", "sldl", "sldu", "cd", "states"];

/** The most local division of a place. It carries the shareable #/d/ link: a
 *  division id says which district, never where in it the reader stood. */
export function smallestDivision(hits: RawStackHit[]): RawStackHit | null {
  for (const layer of MOST_LOCAL) {
    const hit = hits.find((h) => h.layer === layer);
    if (hit) return hit;
  }
  return hits[0] ?? null;
}

/** What to call one division as a place: "Sumner County, TN", "TN-6
 *  congressional district". */
export function hitTitle(hit: RawStackHit): string {
  const name = divisionName(hit.layer, hit.props, hit.ocdId);
  const st = stateOf(hit.ocdId);
  return hit.layer === "county" && st ? `${name}, ${st}` : name;
}

/** What to call a place: its most local division. */
export function placeTitle(hits: RawStackHit[]): string {
  const local = smallestDivision(hits);
  return local ? hitTitle(local) : "This place";
}

/** A place opened from a #/d/{ocd_id} link. There is no point in that path and
 *  no polygon, so the place is the division itself plus the one parent an id
 *  implies without geometry: its state, whose statewide offices represent every
 *  address inside it. The tile attributes a click would have carried are read
 *  back out of the id, which holds the same state code, district number and
 *  county name. Null when the id is not a division we map. */
export function hitsFromOcd(ocdId: string): RawStackHit[] | null {
  const layer = layerOfOcd(ocdId);
  if (!layer) return null;
  const state = stateOf(ocdId);
  const num = /\/(?:cd|sldu|sldl):([\w-]+)$/.exec(ocdId)?.[1]?.toUpperCase();
  const props: DivisionProps = { state };
  if (num) props.district_num = num;
  if (layer === "county") props.name = ocdShortLabel(ocdId);
  const hits: RawStackHit[] = [{ layer, ocdId, props }];
  const parent = /^(.*\/state:[a-z]{2})\/./.exec(ocdId)?.[1];
  if (parent) hits.push({ layer: "states", ocdId: parent, props: { state } });
  return hits;
}
