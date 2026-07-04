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
}

export function initMap(container: HTMLElement, onSelect: SelectHandler): BeholdenMap {
  const map = new maplibregl.Map({
    container,
    style: { version: 8, sources: {}, layers: [
      { id: "bg", type: "background", paint: { "background-color": "#04121c" } }, // sonar depth base
    ]},
    center: [-96.5, 38.5], zoom: 4, minZoom: 3, maxZoom: 12,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

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

  return { map, goTo, clearSelection };
}
