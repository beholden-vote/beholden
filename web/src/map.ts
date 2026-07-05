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

const VINTAGE = "2024";

// PMTiles protocol: the browser reads byte ranges of a single archive on the CDN.
const protocol = new Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

type StyleRow = { party: string; ideology_dim1: number | null; vacant: boolean };
type StyleFeed = Record<string, StyleRow>;

export const PARTY_COLORS: Record<string, string> = {
  // Matched-luminance, symmetric by construction (DESIGN.md §2): neither party louder.
  D: "#4b83bd", R: "#c25b5b", I: "#8f8f5e", L: "#9a8a5a", G: "#5b9a63", NP: "#64717c",
};
const VACANT_FILL = "#2b2f33";
const DEFAULT_FILL = "#0a2233";

// One vector archive per geometry family (§5); sldu+sldl share the us-sld archive.
type ArchiveId = "states" | "cd" | "sld";
const ARCHIVE_FILE: Record<ArchiveId, string> = {
  states: "us-states",
  cd: "us-cd",
  sld: "us-sld",
};

export type LayerId = "states" | "cd" | "sldu" | "sldl";
interface LayerDef {
  id: LayerId;           // also the {layer}-fill id root and the pins/stylefeed name
  archive: ArchiveId;
  sourceLayer: string;   // tippecanoe layer name inside the archive
  minzoom: number;
}
export const LAYERS: LayerDef[] = [
  { id: "states", archive: "states", sourceLayer: "states", minzoom: 0 },
  { id: "cd", archive: "cd", sourceLayer: "districts", minzoom: 0 },
  { id: "sldu", archive: "sld", sourceLayer: "sldu", minzoom: 6 },
  { id: "sldl", archive: "sld", sourceLayer: "sldl", minzoom: 6 },
];
const FILL_IDS = LAYERS.map((L) => `${L.id}-fill`);

// Default: federal levels on, state-legislative overlays off — stacking every
// level at once is the "confusing overlap" on zoom-in. Users opt the rest in.
export const DEFAULT_VISIBLE: Record<LayerId, boolean> = {
  states: true, cd: true, sldu: false, sldl: false,
};

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
  /** Toggle an administrative level on/off (also affects hit-testing). */
  setLayerVisible(id: LayerId, visible: boolean): void;
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
  const desiredVis: Record<LayerId, boolean> = { ...DEFAULT_VISIBLE };
  const applyVis = (id: LayerId) => {
    const v = desiredVis[id] ? "visible" : "none";
    for (const suffix of ["fill", "line"] as const) {
      if (map.getLayer(`${id}-${suffix}`)) map.setLayoutProperty(`${id}-${suffix}`, "visibility", v);
    }
  };

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

    // Fill + outline per layer, drawn states -> cd -> sld (bottom-up). Hover and
    // selection are feature-states so they cost nothing to toggle. State-chamber
    // polygons default to TRANSPARENT until their style feed publishes, so they
    // overlay the colored CD layer as outlines instead of blanketing it — they
    // still hit-test for hover/click (geometry, not pixels).
    for (const L of LAYERS) {
      const defaultFill = L.id === "sldu" || L.id === "sldl" ? "rgba(10,34,51,0)" : DEFAULT_FILL;
      map.addLayer({
        id: `${L.id}-fill`, source: L.archive, "source-layer": L.sourceLayer, type: "fill",
        minzoom: L.minzoom,
        paint: {
          "fill-color": ["coalesce", ["feature-state", "fill"], defaultFill],
          "fill-opacity": [
            "case",
            ["boolean", ["feature-state", "selected"], false], 0.95,
            ["boolean", ["feature-state", "hover"], false], 0.92,
            0.8,
          ],
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
        },
      });
    }

    LAYERS.forEach((L) => applyVis(L.id)); // apply initial (default) visibility

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
    }
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

  return { map, goTo, clearSelection, setLayerVisible, setUserLocation };
}
