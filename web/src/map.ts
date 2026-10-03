/**
 * Beholden map engine (tickets E7-1/2/3).
 * Static SPA: MapLibre + PMTiles protocol (range requests straight to R2/CDN —
 * no tile server), style feeds joined client-side per data-contracts v1 §5.
 * Interaction model: hover highlights the polygon under the cursor; click
 * resolves the FULL representation stack at that point (CD + state + chambers)
 * and hands it to the UI layer.
 */
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";
import "maplibre-gl/dist/maplibre-gl.css";
import { DATA } from "./lib/data";
import { loadStateCoverage } from "./lib/coverage";
import { BANDS, bandAt, bandStart, type BandStop } from "./lib/levels";
import type { DivisionProps } from "./types";

export type { DivisionProps };

const VINTAGE = "2025";

// PMTiles protocol: the browser reads byte ranges of a single archive on the CDN.
const protocol = new Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

type StyleRow = { party: string; ideology_dim1: number | null; vacant: boolean };
type StyleFeed = Record<string, StyleRow>;

export const PARTY_COLORS: Record<string, string> = {
  // Matched-luminance, symmetric by construction (DESIGN.md §2): neither party louder.
  D: "#4b83bd", R: "#c25b5b", I: "#8f8f5e", L: "#9a8a5a", G: "#5b9a63", NP: "#64717c",
  // Split U.S. Senate delegation (WO-14): a neutral purple-gray blend held to the
  // same luminance band as D/R — deliberately reads as "neither red nor blue",
  // and stays distinct from the I/G/L hues. Never used for a person, only for a
  // state's two-seat delegation.
  SPLIT: "#7a6a8f",
};
export const VACANT_FILL = "#2b2f33";
const DEFAULT_FILL = "#0a2233";

// One vector archive per geometry family (§5); sldu+sldl share the us-sld archive.
type ArchiveId = "states" | "cd" | "sld" | "counties" | "places";
const ARCHIVE_FILE: Record<ArchiveId, string> = {
  states: "us-states",
  cd: "us-cd",
  sld: "us-sld",
  counties: "us-counties",
  places: "us-places",   // WO-37, contracts 8.5
};

export type LayerId = "states" | "cd" | "sldu" | "sldl" | "county" | "place";
interface LayerDef {
  id: LayerId;           // also the {layer}-fill id root and the pins/stylefeed name
  archive: ArchiveId;
  sourceLayer: string;   // tippecanoe layer name inside the archive
  minzoom: number;
}
export const LAYERS: LayerDef[] = [
  { id: "states", archive: "states", sourceLayer: "states", minzoom: 0 },
  { id: "cd", archive: "cd", sourceLayer: "districts", minzoom: 0 },
  // State chambers fade in past ~z6 so zooming in reveals them without popping.
  { id: "sldu", archive: "sld", sourceLayer: "sldu", minzoom: 6 },
  { id: "sldl", archive: "sld", sourceLayer: "sldl", minzoom: 6 },
  // Local tier (WO-6b): counties fade in past ~z8 — the metro band — so they join
  // only when you're zoomed into a place, keeping the national/state views clean.
  // Geometry + OCD-ID only for now (no member data), so it renders line-only.
  { id: "county", archive: "counties", sourceLayer: "counties", minzoom: 7 },
  // WO-37: incorporated places (the archive starts at z7). One zoom past counties,
  // so a city draws inside its county the way a council sits inside a commission.
  { id: "place", archive: "places", sourceLayer: "places", minzoom: 8 },
];
const FILL_IDS = LAYERS.map((L) => `${L.id}-fill`);

// Seed visibility: federal levels on, state-legislative overlays off — stacking
// every level at once is the "confusing overlap" on zoom-in. In AUTO mode the
// zoom controller drives what's actually shown (this is only the starting point);
// in MANUAL mode the user's stored per-layer choices win.
export const DEFAULT_VISIBLE: Record<LayerId, boolean> = {
  // WO-22: counties ship people now, so the layer is on by default like the
  // federal ones. It still only appears from z7 with an 8->9 fade (LAYERS).
  states: true, cd: true, sldu: false, sldl: false, county: true, place: true,
};

/** Layer-visibility mode: "auto" = zoom-driven, "manual" = explicit per-layer. */
export type LayerMode = "auto" | "manual";

async function loadStyleFeed(feed: string): Promise<StyleFeed> {
  try {
    const res = await fetch(`${DATA}/stylefeeds/${feed}.json`);
    return res.ok ? await res.json() : {};
  } catch {
    return {};
  }
}

function fillFor(row: StyleRow): string {
  if (row.vacant) return VACANT_FILL;
  return PARTY_COLORS[row.party] ?? PARTY_COLORS.NP;
}

// The base feature-state opacity case: 0.95 selected / 0.92 hover / 0.8 otherwise.
const FILL_OPACITY_CASE = [
  "case",
  ["boolean", ["feature-state", "selected"], false], 0.95,
  ["boolean", ["feature-state", "hover"], false], 0.92,
  0.8,
] as const;
const SELECTED = ["boolean", ["feature-state", "selected"], false];

// MapLibre requires "zoom" to be the DIRECT input of a top-level "interpolate",
// so the zoom ramp is the outer expression and per-feature cases live in its stop
// values. Stops come from the one zoom table in lib/levels.ts (BANDS).
function ramp(stops: BandStop[], at: (primary: number, ref: number) => unknown): unknown {
  if (stops.length === 1) return at(stops[0][1], stops[0][2]);
  return ["interpolate", ["linear"], ["zoom"], ...stops.flatMap(([z, p, r]) => [z, at(p, r)])];
}
/** Primary fill: full where primary, none where reference/off -- except a selected
 *  division, which is always shown. `pinned` (manual, or the chosen layer) = no ramp. */
const fillExpr = (id: LayerId, manual: boolean, off: boolean): unknown =>
  off ? 0 : manual ? FILL_OPACITY_CASE
    : ramp(BANDS[id], (p) => (p > 0 ? FILL_OPACITY_CASE : ["case", SELECTED, 0.95, 0]));
const lineExpr = (id: LayerId, manual: boolean, off: boolean): unknown =>
  off ? ["case", SELECTED, 1, 0] : manual ? 1 : ramp(BANDS[id], (p) => ["case", SELECTED, 1, p]);
const refExpr = (id: LayerId, manual: boolean, off: boolean): unknown =>
  off || manual ? 0 : ramp(BANDS[id], (_p, r) => r);

// Join a style feed to already-loaded geometry via feature-state — tiles stay
// immutable, colors update daily, and map + dossier can never disagree (§5).
function applyFeed(map: maplibregl.Map, source: string, sourceLayer: string, feed: StyleFeed) {
  for (const [ocdId, row] of Object.entries(feed)) {
    map.setFeatureState({ source, sourceLayer, id: ocdId }, { fill: fillFor(row) });
  }
}

/* ── Coverage fills (WO-37, contracts 8.10) ────────────────────────────────────
 *
 * Local polygons are filled by coverage state, never by party (local sources
 * publish none). One neutral scale held to a lightness ramp, so it survives every
 * colour-vision deficiency, and each step also has a pattern, so it survives
 * greyscale: covered = solid light, partial = mid with dots, withheld = dark with
 * hatching, not covered yet = no fill, outline only. DESIGN.md section 2. */
export const COVERAGE_FILL = { covered: "#aab4bc", partial: "#7d878f", withheld: "#4a545c" } as const;
const LOCAL: LayerId[] = ["county", "place"];
/** [layer suffix, coverage state it draws for, pattern image] */
const PATTERNS = [["dots", "partial", "cov-dots"], ["hatch", "withheld", "cov-hatch"]] as const;

function patternOpacityExpr(id: LayerId, manual: boolean, cov: string): unknown {
  const here = ["case", ["==", ["feature-state", "cov"], cov], 0.9, 0];
  return manual ? here : ramp(BANDS[id], (p) => (p > 0 ? here : 0));
}

/** Pattern tiles, drawn in code so no sprite sheet is published. */
function patternImage(kind: "dots" | "hatch"): { width: number; height: number; data: Uint8Array } {
  const n = 8;
  const data = new Uint8Array(n * n * 4);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const on = kind === "hatch" ? (x + y) % n < 2 : (x % 4 === 1 || x % 4 === 2) && (y % 4 === 1 || y % 4 === 2);
    if (!on) continue;
    const c = kind === "hatch" ? [234, 242, 248] : [6, 19, 29];   // --ink on dark, --bg on mid
    data.set([...c, 255], (y * n + x) * 4);
  }
  return { width: n, height: n, data };
}

/** What the UI receives on click: rendered divisions under the point, top-first.
 *  `props` is the clicked polygon's own tile attributes, so the panel can say
 *  WHERE you clicked and not only who represents it. */
export interface RawStackHit { layer: LayerId; ocdId: string; props: DivisionProps }
export type SelectHandler = (hits: RawStackHit[], lngLat: { lng: number; lat: number }) => void;
/** Fired when zooming crosses into a different level of government. */
export type LevelHandler = (zoom: number) => void;

export interface BeholdenMap {
  map: maplibregl.Map;
  /** Programmatic selection (search results, arrival, tests): fly there, then
   *  select. `offsetY` (px, negative = up) lands the point above the screen
   *  centre -- on a phone the bottom sheet covers the lower half of the map. */
  goTo(lng: number, lat: number, zoom?: number, offsetY?: number): void;
  clearSelection(): void;
  /** Toggle an administrative level on/off (also affects hit-testing). In AUTO
   *  mode this seeds the desired set but zoom still governs sld* fades; call
   *  setLayerMode("manual") first for an explicit toggle to stick. */
  setLayerVisible(id: LayerId, visible: boolean): void;
  /** Switch between zoom-driven ("auto") and explicit ("manual") visibility. */
  setLayerMode(mode: LayerMode): void;
  /** Which state chamber auto mode draws (one at a time; both = manual only). */
  setChamber(chamber: "sldl" | "sldu"): void;
  /** Drop/move the "you are here" marker. precise=false renders the fainter
   *  "approximate area" style (coarse IP location); true = exact (geolocation). */
  setUserLocation(lng: number, lat: number, precise?: boolean): void;
}

export function initMap(container: HTMLElement, onSelect: SelectHandler,
                        onZoomLevel?: LevelHandler): BeholdenMap {
  const map = new maplibregl.Map({
    container,
    style: { version: 8, sources: {},
      // Self-hosted glyphs (tiles-build publishes Noto PBF ranges to R2) — the
      // only text on the map is orientation labels, served from our own origin.
      glyphs: `${DATA}/fonts/{fontstack}/{range}.pbf`,
      layers: [
      { id: "bg", type: "background", paint: { "background-color": "#04121c" } }, // sonar depth base
    ]},
    center: [-96.5, 38.5], zoom: 4, minZoom: 3, maxZoom: 12,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  // Report zoom so the UI can name the level of government now on screen. Fires
  // on every zoom frame; the UI derives the gate and ignores anything that
  // doesn't change it, which keeps the "you crossed into State" announcement
  // tied to the crossing rather than to the scroll wheel.
  if (onZoomLevel) {
    map.on("zoom", () => onZoomLevel(map.getZoom()));
    map.once("load", () => onZoomLevel(map.getZoom()));
  }

  // Per-layer visibility. Hidden layers also drop out of hover/click hit-testing
  // (queryRenderedFeatures ignores visibility:none), so toggling a level off
  // removes it from the map AND the representation stack.
  //
  // Two modes (WO-2):
  //  - "auto" (default): zoom drives the show/hide. Federal levels stay on;
  //    faded layers (sld*) go visibility:none below their fade floor and fade in
  //    above it via a zoom-interpolated paint opacity — no popping.
  //  - "manual": the user's explicit per-layer choices (desiredVis) win at all
  //    zooms; fades are pinned fully on so a checked layer is never dimmed away.
  // A layer that is part of the LIVE SELECTION is never auto-hidden — it stays
  // interactive until the panel closes, regardless of mode or zoom.
  const desiredVis: Record<LayerId, boolean> = { ...DEFAULT_VISIBLE };
  let mode: LayerMode = "auto";
  const selectedLayers = new Set<LayerId>();
  // Auto mode draws ONE state chamber at a time (the other stays hit-testable but
  // invisible, so the place view still lists both). Both together: manual only.
  let chamber: "sldl" | "sldu" = "sldl";
  const chamberOff = (id: LayerId) => mode === "auto" && (id === "sldu" || id === "sldl") && id !== chamber;

  // Should this layer be present (visibility:visible) at all right now?
  // In auto, a faded layer hides below its floor; but a selected or manually-on
  // layer is always kept present.
  const layerPresent = (id: LayerId): boolean => {
    if (selectedLayers.has(id)) return true;
    if (mode === "manual") return desiredVis[id];
    const start = bandStart(id);
    if (!start) return desiredVis[id];       // federal: honor seed (always on)
    return map.getZoom() >= start;           // present past its fade-in; past its band it only fades out
  };
  const applyVis = (id: LayerId) => {
    const v = layerPresent(id) ? "visible" : "none";
    for (const suffix of ["fill", "line", "ref", "hatch", "dots"] as const) {
      if (map.getLayer(`${id}-${suffix}`)) map.setLayoutProperty(`${id}-${suffix}`, "visibility", v);
    }
  };
  const applyAllVis = () => LAYERS.forEach((L) => applyVis(L.id));

  map.on("load", async () => {
    map.addImage("cov-dots", patternImage("dots"));
    map.addImage("cov-hatch", patternImage("hatch"));
    // One vector source per archive. promoteId lifts ocd_id to the feature id so
    // feature-state (style-feed fill, hover, selection) all key on it.
    map.addSource("states", {
      type: "vector", url: `pmtiles://${DATA}/tiles/${ARCHIVE_FILE.states}-${VINTAGE}.pmtiles`,
      promoteId: { states: "ocd_id" },
    });
    map.addSource("cd", {
      type: "vector", url: `pmtiles://${DATA}/tiles/${ARCHIVE_FILE.cd}-${VINTAGE}.pmtiles`,
      promoteId: { districts: "ocd_id" },
    });
    map.addSource("sld", {
      type: "vector", url: `pmtiles://${DATA}/tiles/${ARCHIVE_FILE.sld}-${VINTAGE}.pmtiles`,
      promoteId: { sldu: "ocd_id", sldl: "ocd_id" },
    });
    // Local tier (WO-6b): county geometry only — no member style feed yet, so it
    // renders as outlines (see the transparent default fill below).
    map.addSource("places", {
      type: "vector", url: `pmtiles://${DATA}/tiles/${ARCHIVE_FILE.places}-${VINTAGE}.pmtiles`,
      promoteId: { places: "ocd_id" },
    });
    map.addSource("counties", {
      type: "vector", url: `pmtiles://${DATA}/tiles/${ARCHIVE_FILE.counties}-${VINTAGE}.pmtiles`,
      promoteId: { counties: "ocd_id" },
    });

    // Fill + outline per layer, drawn states -> cd -> sld (bottom-up). Hover and
    // selection are feature-states so they cost nothing to toggle. Every layer
    // with a style feed (states = Senate delegation, cd, sldu, sldl) colors via
    // the same feature-state fill path; the coalesce default below only shows
    // where the feed has no row.
    for (const L of LAYERS) {
      // Overlay layers (state chambers + counties) default to a TRANSPARENT fill
      // so a division their feed doesn't cover — or counties, which carry no
      // officials at all (honest: outline-only) — overlays the colored layers
      // beneath as outlines instead of blanketing them; they still hit-test on
      // geometry. Base layers (states, cd) keep the opaque navy default.
      const overlay = L.id === "sldu" || L.id === "sldl" || L.id === "county" || L.id === "place";
      const defaultFill = overlay ? "rgba(10,34,51,0)" : DEFAULT_FILL;
      // Build for whatever mode is current at construction time (usually "auto",
      // but a persisted manual preference can already be set if setLayerMode ran
      // before "load" fired — see setLayerMode's own note below).
        map.addLayer({
        id: `${L.id}-fill`, source: L.archive, "source-layer": L.sourceLayer, type: "fill",
        minzoom: L.minzoom,
        paint: {
          "fill-color": ["coalesce", ["feature-state", "fill"], defaultFill],
          // Base feature-state opacity, scaled by the zoom-fade factor (WO-2).
          "fill-opacity": 0,   // set by applyPaint from the zoom table
        },
      });
      map.addLayer({
        id: `${L.id}-line`, source: L.archive, "source-layer": L.sourceLayer, type: "line",
        minzoom: L.minzoom,
        paint: {
          // Primary boundary: solid, mid strength. Selection / hover are blue-grey
          // line states shared by every level (no new hues).
          "line-color": [
            "case",
            ["boolean", ["feature-state", "selected"], false], "#9fd4ff",
            ["boolean", ["feature-state", "hover"], false], "#5f93b8",
            "#2a6486",
          ],
          "line-width": [
            "case",
            ["boolean", ["feature-state", "selected"], false], 2.2,
            ["boolean", ["feature-state", "hover"], false], 1.4,
            0.9,
          ],
          "line-opacity": 0,
        },
      });
      if (L.id !== "states" && L.id !== "cd") {
        // Reference boundary: the level a primary one replaced. Thin and faint;
        // county and city lines are dashed. Never in hit-testing (not a -fill).
        map.addLayer({
          id: `${L.id}-ref`, source: L.archive, "source-layer": L.sourceLayer, type: "line",
          minzoom: L.minzoom,
          paint: {
            "line-color": "#4a7f9d", "line-width": 0.7, "line-opacity": 0,
            ...(L.id === "county" || L.id === "place" ? { "line-dasharray": [3, 2] } : {}),
          },
        });
      }
      if (LOCAL.includes(L.id)) {
        // Coverage patterns (WO-37): the state is never carried by colour alone.
        for (const [suffix, , image] of PATTERNS) {
          map.addLayer({
            id: `${L.id}-${suffix}`, source: L.archive, "source-layer": L.sourceLayer, type: "fill",
            minzoom: L.minzoom,
            paint: {
              "fill-pattern": image,
              "fill-opacity": 0,
            },
          });
        }
      }
    }

    // The one permanent reference: the state outline, solid, widest and pale,
    // above every fill. Not a -fill layer, so it never takes a click.
    map.addLayer({
      id: "states-outline", source: "states", "source-layer": "states", type: "line",
      paint: {
        "line-color": "#a9c0cf", "line-opacity": 0.85,
        "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.9, 10, 2.2],
      },
    });

    // Sync paint + visibility to the CURRENT mode. If the UI restored a manual
    // preference before "load" fired, `mode`/`desiredVis` already reflect it but
    // the paint expressions were built for auto — setLayerMode reconciles both.
    setLayerMode(mode);

    // Re-evaluate faded-layer presence as the user zooms (auto mode). Cheap:
    // only touches layout visibility, and only when a layer's present-ness flips.
    // The opacity fade itself is a paint expression, so it interpolates for free.
    map.on("zoom", () => {
      if (mode !== "auto") return;
      for (const L of LAYERS) if (bandStart(L.id)) applyVis(L.id);
    });

    // ---- orientation context (Natural Earth): barely-visible interstates +
    // city labels ABOVE the district fills, deliberately subordinate to them.
    // Non-interactive: never hit-tested, never in the representation stack.
    map.addSource("context", {
      type: "vector", url: `pmtiles://${DATA}/tiles/us-context-${VINTAGE}.pmtiles`,
    });
    map.addLayer({
      id: "ctx-roads", source: "context", "source-layer": "roads", type: "line",
      minzoom: 4,
      paint: {
        "line-color": "#31536b",
        "line-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0.12, 7, 0.3, 10, 0.4],
        "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.4, 8, 1.1],
      },
    });
    map.addLayer({
      id: "ctx-place-dots", source: "context", "source-layer": "places", type: "circle",
      minzoom: 5,
      paint: { "circle-radius": 1.6, "circle-color": "#7f97a8", "circle-opacity": 0.45 },
    });
    // Major cities label early; smaller ones only as you zoom in. Light text on
    // a heavy near-black halo so names stay readable over any district fill,
    // while the muted color keeps them subordinate to the data.
    map.addLayer({
      id: "ctx-place-labels", source: "context", "source-layer": "places", type: "symbol",
      minzoom: 3.5,
      filter: ["<=", ["get", "rank"], 2],
      layout: {
        "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"],
        "text-size": 12.5, "text-anchor": "bottom", "text-offset": [0, -0.35],
      },
      paint: {
        "text-color": "#d7e3ec", "text-opacity": 0.95,
        "text-halo-color": "#020a12", "text-halo-width": 2, "text-halo-blur": 0.4,
      },
    });
    map.addLayer({
      id: "ctx-place-labels-minor", source: "context", "source-layer": "places", type: "symbol",
      minzoom: 6,
      filter: [">", ["get", "rank"], 2],
      layout: {
        "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"],
        "text-size": 11.5, "text-anchor": "bottom", "text-offset": [0, -0.35],
      },
      paint: {
        "text-color": "#b6c7d3", "text-opacity": 0.9,
        "text-halo-color": "#020a12", "text-halo-width": 1.8, "text-halo-blur": 0.4,
      },
    });

    // Load every feed up front; apply once the matching source has tiles.
    const feeds = new Map<string, StyleFeed>();
    await Promise.all(LAYERS.map(async (L) => feeds.set(L.id, await loadStyleFeed(L.id))));

    const applied = new Set<string>();
    map.on("sourcedata", (e) => {
      if (!e.isSourceLoaded) return;
      for (const L of LAYERS) {
        if (L.archive !== e.sourceId || applied.has(L.id)) continue;
        applyFeed(map, L.archive, L.sourceLayer, feeds.get(L.id) ?? {});
        applied.add(L.id);
      }
    });
  });

  // ---- coverage fills (WO-37): one shard per state the reader has reached ----
  // A state is reached when a local polygon of it is on screen or in a click. Its
  // shard is fetched once; divisions it names get their coverage state, and every
  // other local polygon keeps the "not covered yet" default (outline only).
  const covRequested = new Set<string>();
  const reach = (states: Iterable<string | undefined>) => {
    for (const raw of states) {
      const st = raw?.toLowerCase();
      if (!st || covRequested.has(st)) continue;
      covRequested.add(st);
      void loadStateCoverage(st).then((shard) => {
        for (const [ocdId, d] of Object.entries(shard?.divisions ?? {})) {
          const L = LAYERS.find((x) => LOCAL.includes(x.id) && (x.id === "place" ? /\/place:/ : /\/(county|parish|borough):/).test(ocdId));
          if (!L) continue;
          map.setFeatureState({ source: L.archive, sourceLayer: L.sourceLayer, id: ocdId },
            { fill: COVERAGE_FILL[d.state], cov: d.state });
        }
      });
    }
  };
  const reachViewport = () => {
    const ids = LOCAL.map((id) => `${id}-fill`).filter((l) => !!map.getLayer(l));
    if (!ids.length) return;
    reach(map.queryRenderedFeatures({ layers: ids }).map((f) => (f.properties as DivisionProps).state));
  };
  map.on("moveend", reachViewport);
  map.on("idle", reachViewport);

  // ---- hover: one feature per layer family gets the hover state ----
  type FeatRef = { source: string; sourceLayer: string; id: string };
  let hovered: FeatRef | null = null;
  const setHover = (ref: FeatRef | null) => {
    if (hovered) map.setFeatureState(hovered, { hover: false });
    hovered = ref;
    if (hovered) map.setFeatureState(hovered, { hover: true });
    map.getCanvas().style.cursor = hovered ? "pointer" : "";
  };
  map.on("mousemove", (e) => {
    const feats = map.queryRenderedFeatures(e.point, {
      layers: FILL_IDS.filter((l) => !!map.getLayer(l)),
    });
    // The primary level takes the hover; a reference-only or faded-out level never does.
    const live = feats.filter((f) => {
      const id = f.layer.id.replace(/-fill$/, "") as LayerId;
      if (mode === "manual" || selectedLayers.has(id)) return true;
      return !chamberOff(id) && bandAt(id, map.getZoom()).primary > 0;
    });
    const top = live.reduce<typeof feats[number] | undefined>((best, f) => {
      const p = (f2: typeof f) => bandAt(f2.layer.id.replace(/-fill$/, "") as LayerId, map.getZoom()).primary;
      return !best || p(f) > p(best) ? f : best;
    }, undefined);
    if (!top || top.id == null) return setHover(null);
    setHover({ source: top.source, sourceLayer: top.sourceLayer!, id: String(top.id) });
  });
  map.on("mouseout", () => setHover(null));

  // ---- click: resolve the full stack at the point, topmost first ----
  let selected: FeatRef[] = [];
  const clearSelection = () => {
    for (const ref of selected) map.setFeatureState(ref, { selected: false });
    selected = [];
    // Selection released: those levels may auto-hide again per the current zoom.
    if (selectedLayers.size) {
      selectedLayers.clear();
      applyAllVis();
    }
  };
  const selectAtPoint = (point: maplibregl.PointLike, lngLat: { lng: number; lat: number }) => {
    const feats = map.queryRenderedFeatures(point, {
      layers: FILL_IDS.filter((l) => !!map.getLayer(l)),
    });
    clearSelection();
    const seen = new Set<string>();
    const hits: RawStackHit[] = [];
    for (const f of feats) {
      const layer = f.layer.id.replace(/-fill$/, "") as LayerId;
      if (f.id == null || seen.has(layer)) continue;   // one hit per level
      seen.add(layer);
      // The polygon's own attributes travel with the hit so the panel can name
      // the division ("Sumner County", "TN-5") rather than only the officials
      // standing in it. Tile properties, not a lookup — no extra request.
      hits.push({ layer, ocdId: String(f.id), props: (f.properties ?? {}) as DivisionProps });
      if (LOCAL.includes(layer)) reach([(f.properties as DivisionProps).state]);
      const ref = { source: f.source, sourceLayer: f.sourceLayer!, id: String(f.id) };
      map.setFeatureState(ref, { selected: true });
      selected.push(ref);
      selectedLayers.add(layer);   // never auto-hide a level in the live selection
    }
    // Keep every selected level present (e.g. a sld* hit clicked below its fade
    // floor stays interactive until the panel closes).
    applyAllVis();
    onSelect(hits, lngLat);
  };
  // Arrival (WO-35) flies somewhere without being asked, so a flight can now be
  // overtaken -- by a click, or by the address the reader typed meanwhile. Only
  // the latest request selects; an overtaken one must not land on top of it.
  let flight = 0;
  map.on("click", (e) => { flight++; selectAtPoint(e.point, e.lngLat); });

  const goTo = (lng: number, lat: number, zoom = 8, offsetY = 0) => {
    const mine = ++flight;
    map.flyTo({ center: [lng, lat], zoom, duration: 1200, offset: [0, offsetY] });
    map.once("idle", () => {
      if (mine !== flight) return;
      const point = map.project([lng, lat]);
      selectAtPoint(point, { lng, lat });
    });
  };

  const setLayerVisible = (id: LayerId, visible: boolean) => {
    desiredVis[id] = visible;
    applyVis(id);
  };

  // Paint every layer from the zoom table for the current mode and chamber.
  // Auto = zoom ramp (primary, then reference, then off); manual = pinned on, so a
  // layer the reader checked is never dimmed away.
  const applyPaint = () => {
    const manual = mode === "manual";
    const set = (layer: string, prop: string, v: unknown) => {
      if (map.getLayer(layer)) map.setPaintProperty(layer, prop, v as never);
    };
    for (const L of LAYERS) {
      const off = chamberOff(L.id);
      set(`${L.id}-fill`, "fill-opacity", fillExpr(L.id, manual, off));
      set(`${L.id}-line`, "line-opacity", lineExpr(L.id, manual, off));
      set(`${L.id}-ref`, "line-opacity", refExpr(L.id, manual, off));
      for (const [suffix, cov] of PATTERNS) {
        if (LOCAL.includes(L.id)) set(`${L.id}-${suffix}`, "fill-opacity", off ? 0 : patternOpacityExpr(L.id, manual, cov));
      }
    }
  };
  const setLayerMode = (next: LayerMode) => {
    mode = next;
    applyPaint();
    applyAllVis();
  };
  const setChamber = (next: "sldl" | "sldu") => {
    chamber = next;
    applyPaint();
  };

  // "You are here" marker. Coarse (IP) on load for ambient bearings; exact when
  // the user taps locate. A DOM marker so it never enters tile hit-testing.
  let userMarker: maplibregl.Marker | null = null;
  const setUserLocation = (lng: number, lat: number, precise = true) => {
    if (!userMarker) {
      const el = document.createElement("div");
      el.className = "you-marker";
      userMarker = new maplibregl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map);
    } else {
      userMarker.setLngLat([lng, lat]);
    }
    userMarker.getElement().classList.toggle("you-marker-approx", !precise);
  };

  return { map, goTo, clearSelection, setLayerVisible, setLayerMode, setChamber, setUserLocation };
}
