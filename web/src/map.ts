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
type ArchiveId = "states" | "cd" | "sld" | "counties";
const ARCHIVE_FILE: Record<ArchiveId, string> = {
  states: "us-states",
  cd: "us-cd",
  sld: "us-sld",
  counties: "us-counties",
};

export type LayerId = "states" | "cd" | "sldu" | "sldl" | "county";
interface LayerDef {
  id: LayerId;           // also the {layer}-fill id root and the pins/stylefeed name
  archive: ArchiveId;
  sourceLayer: string;   // tippecanoe layer name inside the archive
  minzoom: number;
  /** Auto mode: fade the fill/line opacity in over [start, end] (zoom); below
   *  `start` the layer drops to visibility:none. Absent = always-on in Auto
   *  (federal levels). The fade avoids the "pop" of toggling visibility on zoom. */
  autoFade?: { start: number; end: number };
}
export const LAYERS: LayerDef[] = [
  { id: "states", archive: "states", sourceLayer: "states", minzoom: 0 },
  { id: "cd", archive: "cd", sourceLayer: "districts", minzoom: 0 },
  // State chambers fade in past ~z6 so zooming in reveals them without popping.
  { id: "sldu", archive: "sld", sourceLayer: "sldu", minzoom: 6, autoFade: { start: 6, end: 7 } },
  { id: "sldl", archive: "sld", sourceLayer: "sldl", minzoom: 6, autoFade: { start: 6, end: 7 } },
  // Local tier (WO-6b): counties fade in past ~z8 — the metro band — so they join
  // only when you're zoomed into a place, keeping the national/state views clean.
  // Geometry + OCD-ID only for now (no member data), so it renders line-only.
  { id: "county", archive: "counties", sourceLayer: "counties", minzoom: 7, autoFade: { start: 8, end: 9 } },
];
const FILL_IDS = LAYERS.map((L) => `${L.id}-fill`);

// Seed visibility: federal levels on, state-legislative overlays off — stacking
// every level at once is the "confusing overlap" on zoom-in. In AUTO mode the
// zoom controller drives what's actually shown (this is only the starting point);
// in MANUAL mode the user's stored per-layer choices win.
export const DEFAULT_VISIBLE: Record<LayerId, boolean> = {
  states: true, cd: true, sldu: false, sldl: false, county: false,
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

// The base (non-faded) feature-state opacity case: 0.95 selected / 0.92 hover /
// 0.8 otherwise. Used directly when a layer has no fade or is pinned (manual).
const FILL_OPACITY_CASE = [
  "case",
  ["boolean", ["feature-state", "selected"], false], 0.95,
  ["boolean", ["feature-state", "hover"], false], 0.92,
  0.8,
] as const;

// MapLibre's style spec requires a "zoom" expression to be the DIRECT input to
// a TOP-LEVEL "interpolate"/"step" — it may not be nested inside "case"/"*"/etc.
// (nesting it fails style validation and silently drops the whole layer; this
// bit the sld*/county layers for their entire lifetime — WO-2/WO-6b built the
// fade as `["*", caseExpr, ["case", selected, 1, ["interpolate", zoom, ...]]]`,
// which validates but never actually adds the layer). The legal pattern instead
// makes the interpolate itself the top-level expression, with the CASE living
// in the interpolation stops (per-feature expressions as stop values are fully
// supported) — so a selected feature evaluates to full opacity at every stop,
// and an unselected one fades from 0 at `start` to the normal case at `end`.
function fillOpacityExpr(fade: { start: number; end: number } | undefined, manual: boolean): unknown {
  if (!fade || manual) return FILL_OPACITY_CASE;
  const selected = ["boolean", ["feature-state", "selected"], false];
  return ["interpolate", ["linear"], ["zoom"],
    fade.start, ["case", selected, 0.95, 0],
    fade.end, FILL_OPACITY_CASE,
  ];
}
function lineOpacityExpr(fade: { start: number; end: number } | undefined, manual: boolean): unknown {
  if (!fade || manual) return 1;
  const selected = ["boolean", ["feature-state", "selected"], false];
  return ["interpolate", ["linear"], ["zoom"],
    fade.start, ["case", selected, 1, 0],
    fade.end, 1,
  ];
}

// Join a style feed to already-loaded geometry via feature-state — tiles stay
// immutable, colors update daily, and map + dossier can never disagree (§5).
function applyFeed(map: maplibregl.Map, source: string, sourceLayer: string, feed: StyleFeed) {
  for (const [ocdId, row] of Object.entries(feed)) {
    map.setFeatureState({ source, sourceLayer, id: ocdId }, { fill: fillFor(row) });
  }
}

/** What the UI receives on click: rendered divisions under the point, top-first. */
export interface RawStackHit { layer: LayerId; ocdId: string }
export type SelectHandler = (hits: RawStackHit[], lngLat: { lng: number; lat: number }) => void;

export interface BeholdenMap {
  map: maplibregl.Map;
  /** Programmatic selection (search results, tests): fly there, then select. */
  goTo(lng: number, lat: number, zoom?: number): void;
  clearSelection(): void;
  /** Toggle an administrative level on/off (also affects hit-testing). In AUTO
   *  mode this seeds the desired set but zoom still governs sld* fades; call
   *  setLayerMode("manual") first for an explicit toggle to stick. */
  setLayerVisible(id: LayerId, visible: boolean): void;
  /** Switch between zoom-driven ("auto") and explicit ("manual") visibility. */
  setLayerMode(mode: LayerMode): void;
  /** Drop/move the "you are here" marker. precise=false renders the fainter
   *  "approximate area" style (coarse IP location); true = exact (geolocation). */
  setUserLocation(lng: number, lat: number, precise?: boolean): void;
}

export function initMap(container: HTMLElement, onSelect: SelectHandler): BeholdenMap {
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
  const fadeDef = (id: LayerId) => LAYERS.find((L) => L.id === id)?.autoFade;

  // Should this layer be present (visibility:visible) at all right now?
  // In auto, a faded layer hides below its floor; but a selected or manually-on
  // layer is always kept present.
  const layerPresent = (id: LayerId): boolean => {
    if (selectedLayers.has(id)) return true;
    if (mode === "manual") return desiredVis[id];
    const fade = fadeDef(id);
    if (!fade) return desiredVis[id];        // federal: honor seed (always on)
    return map.getZoom() >= fade.start;      // faded layer: present past the floor
  };
  const applyVis = (id: LayerId) => {
    const v = layerPresent(id) ? "visible" : "none";
    for (const suffix of ["fill", "line"] as const) {
      if (map.getLayer(`${id}-${suffix}`)) map.setLayoutProperty(`${id}-${suffix}`, "visibility", v);
    }
  };
  const applyAllVis = () => LAYERS.forEach((L) => applyVis(L.id));

  map.on("load", async () => {
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
      const overlay = L.id === "sldu" || L.id === "sldl" || L.id === "county";
      const defaultFill = overlay ? "rgba(10,34,51,0)" : DEFAULT_FILL;
      // Build for whatever mode is current at construction time (usually "auto",
      // but a persisted manual preference can already be set if setLayerMode ran
      // before "load" fired — see setLayerMode's own note below).
      const manualAtInit = mode === "manual";
      map.addLayer({
        id: `${L.id}-fill`, source: L.archive, "source-layer": L.sourceLayer, type: "fill",
        minzoom: L.minzoom,
        paint: {
          "fill-color": ["coalesce", ["feature-state", "fill"], defaultFill],
          // Base feature-state opacity, scaled by the zoom-fade factor (WO-2).
          "fill-opacity": fillOpacityExpr(L.autoFade, manualAtInit) as maplibregl.ExpressionSpecification,
        },
      });
      map.addLayer({
        id: `${L.id}-line`, source: L.archive, "source-layer": L.sourceLayer, type: "line",
        minzoom: L.minzoom,
        paint: {
          "line-color": [
            "case",
            ["boolean", ["feature-state", "selected"], false], "#9fd4ff",
            ["boolean", ["feature-state", "hover"], false], "#5f93b8",
            "#0e3a52",
          ],
          "line-width": [
            "case",
            ["boolean", ["feature-state", "selected"], false], 2.2,
            ["boolean", ["feature-state", "hover"], false], 1.4,
            0.6,
          ],
          "line-opacity": lineOpacityExpr(L.autoFade, manualAtInit) as maplibregl.ExpressionSpecification,
        },
      });
    }

    // Sync paint + visibility to the CURRENT mode. If the UI restored a manual
    // preference before "load" fired, `mode`/`desiredVis` already reflect it but
    // the paint expressions were built for auto — setLayerMode reconciles both.
    setLayerMode(mode);

    // Re-evaluate faded-layer presence as the user zooms (auto mode). Cheap:
    // only touches layout visibility, and only when a layer's present-ness flips.
    // The opacity fade itself is a paint expression, so it interpolates for free.
    map.on("zoom", () => {
      if (mode !== "auto") return;
      for (const L of LAYERS) if (L.autoFade) applyVis(L.id);
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
    const top = feats[0];
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
      hits.push({ layer, ocdId: String(f.id) });
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
  map.on("click", (e) => selectAtPoint(e.point, e.lngLat));

  const goTo = (lng: number, lat: number, zoom = 8) => {
    map.flyTo({ center: [lng, lat], zoom, duration: 1200 });
    map.once("idle", () => {
      const point = map.project([lng, lat]);
      selectAtPoint(point, { lng, lat });
    });
  };

  const setLayerVisible = (id: LayerId, visible: boolean) => {
    desiredVis[id] = visible;
    applyVis(id);
  };

  // Swap every faded layer's opacity expression to match the mode (auto = zoom
  // ramp, manual = pinned on), then re-evaluate visibility. Called on mode flips
  // and once on init if the restored mode is manual.
  const setLayerMode = (next: LayerMode) => {
    mode = next;
    const manual = mode === "manual";
    for (const L of LAYERS) {
      if (!L.autoFade) continue;                 // federal layers have no fade to swap
      if (map.getLayer(`${L.id}-fill`)) {
        map.setPaintProperty(`${L.id}-fill`, "fill-opacity",
          fillOpacityExpr(L.autoFade, manual) as maplibregl.ExpressionSpecification);
      }
      if (map.getLayer(`${L.id}-line`)) {
        map.setPaintProperty(`${L.id}-line`, "line-opacity",
          lineOpacityExpr(L.autoFade, manual) as maplibregl.ExpressionSpecification);
      }
    }
    applyAllVis();
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

  return { map, goTo, clearSelection, setLayerVisible, setLayerMode, setUserLocation };
}
