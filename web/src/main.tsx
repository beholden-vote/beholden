/**
 * Beholden map shell (tickets E7-1/2/3).
 * Static SPA: MapLibre + PMTiles protocol (range requests straight to R2/CDN —
 * no tile server), style feeds joined client-side per data-contracts v1 §5.
 */
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";
import "maplibre-gl/dist/maplibre-gl.css";

const DATA = import.meta.env.VITE_DATA_BASE ?? "https://data.beholden.vote";
const VINTAGE = "2024";

// PMTiles protocol: the browser reads byte ranges of a single archive on the CDN.
const protocol = new Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

type StyleRow = { party: string; ideology_dim1: number | null; vacant: boolean };
type StyleFeed = Record<string, StyleRow>;

const PARTY_COLORS: Record<string, string> = {
  // O5 note: party via pin form + muted fills; cyan->magenta ramp reserved for ideology.
  D: "#3d6f9e", R: "#a04a4a", I: "#7a7a52", L: "#8a7d55", G: "#4f7a52", NP: "#555f66",
};

// One vector archive per geometry family (§5); sldu+sldl share the us-sld archive.
type ArchiveId = "states" | "cd" | "sld";
const ARCHIVE_FILE: Record<ArchiveId, string> = {
  states: "us-states",
  cd: "us-cd",
  sld: "us-sld",
};

// Each rendered layer: which archive + source-layer it draws from, the style
// feed that colors it, and the zoom floor (state chambers only at closer zoom).
interface LayerDef {
  id: string;            // 'states' | 'cd' | 'sldu' | 'sldl' — also the {layer}-fill id root
  archive: ArchiveId;
  sourceLayer: string;   // tippecanoe layer name inside the archive
  feed: string;          // /stylefeeds/{feed}.json  and  /pins/{feed}.json
  minzoom: number;
}
const LAYERS: LayerDef[] = [
  { id: "states", archive: "states", sourceLayer: "states", feed: "states", minzoom: 0 },
  { id: "cd", archive: "cd", sourceLayer: "districts", feed: "cd", minzoom: 0 },
  { id: "sldu", archive: "sld", sourceLayer: "sldu", feed: "sldu", minzoom: 6 },
  { id: "sldl", archive: "sld", sourceLayer: "sldl", feed: "sldl", minzoom: 6 },
];

async function loadStyleFeed(feed: string): Promise<StyleFeed> {
  // Feeds may not exist yet for every layer (e.g. state chambers pre-ETL):
  // a missing feed leaves polygons at their default fill rather than erroring.
  try {
    const res = await fetch(`${DATA}/stylefeeds/${feed}.json`);
    return res.ok ? await res.json() : {};
  } catch {
    return {};
  }
}

function fillFor(row: StyleRow): string {
  if (row.vacant) return "#2b2f33";
  return PARTY_COLORS[row.party] ?? PARTY_COLORS.NP;
}

// Join a style feed to already-loaded geometry via feature-state — tiles stay
// immutable, colors update daily, and map + dossier can never disagree (§5).
function applyFeed(map: maplibregl.Map, source: string, sourceLayer: string, feed: StyleFeed) {
  for (const [ocdId, row] of Object.entries(feed)) {
    map.setFeatureState(
      { source, sourceLayer, id: ocdId },
      { fill: fillFor(row) },
    );
  }
}

export async function initMap(container: HTMLElement) {
  const map = new maplibregl.Map({
    container,
    style: { version: 8, sources: {}, layers: [
      { id: "bg", type: "background", paint: { "background-color": "#04121c" } }, // sonar depth base
    ]},
    center: [-96.5, 38.5], zoom: 4, minZoom: 3, maxZoom: 12,
  });

  map.on("load", async () => {
    // One vector source per archive. promoteId lifts ocd_id to the feature id so
    // the style-feed join keys on it; sld carries two source-layers.
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

    // Fill + hairline outline per layer, drawn states -> cd -> sld (bottom-up).
    for (const L of LAYERS) {
      map.addLayer({
        id: `${L.id}-fill`, source: L.archive, "source-layer": L.sourceLayer, type: "fill",
        minzoom: L.minzoom,
        paint: { "fill-color": ["coalesce", ["feature-state", "fill"], "#0a2233"], "fill-opacity": 0.8 },
      });
      map.addLayer({
        id: `${L.id}-line`, source: L.archive, "source-layer": L.sourceLayer, type: "line",
        minzoom: L.minzoom,
        paint: { "line-color": "#0e3a52", "line-width": 0.6 },
      });
    }

    // Load every feed up front; apply once the matching source has tiles.
    const feeds = new Map<string, StyleFeed>();
    await Promise.all(LAYERS.map(async (L) => feeds.set(L.id, await loadStyleFeed(L.feed))));

    const applied = new Set<string>();
    map.on("sourcedata", (e) => {
      if (!e.isSourceLoaded) return;
      for (const L of LAYERS) {
        if (L.archive !== e.sourceId || applied.has(L.id)) continue;
        applyFeed(map, L.archive, L.sourceLayer, feeds.get(L.id) ?? {});
        applied.add(L.id);
      }
    });

    // Dossier open: tap a district -> resolve the office-holder from the layer's
    // pin feed -> fetch the pre-built dossier JSON (zero backend, <300ms from CDN).
    for (const L of LAYERS) {
      map.on("click", `${L.id}-fill`, async (e) => {
        const ocdId = e.features?.[0]?.id as string | undefined;
        if (!ocdId) return;
        try {
          const pins = await (await fetch(`${DATA}/pins/${L.feed}.json`)).json();
          const officer = pins.find((p: { ocd_id: string }) => p.ocd_id === ocdId);
          if (!officer) return;
          const dossier = await (await fetch(`${DATA}/dossiers/${officer.person_id}.json`)).json();
          window.dispatchEvent(new CustomEvent("beholden:dossier", { detail: dossier }));
        } catch {
          /* no pin/dossier published for this division yet */
        }
      });
    }
  });
  return map;
}

initMap(document.getElementById("root")!);
