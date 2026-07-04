/**
 * Beholden map shell (tickets E7-1/2/3).
 * Static SPA: MapLibre + PMTiles protocol (range requests straight to R2/CDN —
 * no tile server), style feed joined client-side per data-contracts §5.
 */
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";
import "maplibre-gl/dist/maplibre-gl.css";

const DATA = import.meta.env.VITE_DATA_BASE ?? "https://data.beholden.vote";
const VINTAGE = "2024";

// PMTiles protocol: the browser reads byte ranges of a single archive on the CDN.
const protocol = new Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

type StyleFeed = Record<string, { party: string; ideology_dim1: number | null; vacant: boolean }>;

const PARTY_COLORS: Record<string, string> = {
  // O5 note: party via pin form + muted fills; cyan->magenta ramp reserved for ideology.
  D: "#3d6f9e", R: "#a04a4a", I: "#7a7a52", NP: "#555f66",
};

async function loadStyleFeed(layer: string): Promise<StyleFeed> {
  const res = await fetch(`${DATA}/stylefeeds/${layer}.json`);
  return res.json();
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
    const feed = await loadStyleFeed("cd");

    map.addSource("cd", {
      type: "vector",
      url: `pmtiles://${DATA}/tiles/us-cd-${VINTAGE}.pmtiles`,
      promoteId: "ocd_id",
    });
    map.addLayer({
      id: "cd-fill", source: "cd", "source-layer": "districts", type: "fill",
      paint: { "fill-color": ["coalesce", ["feature-state", "fill"], "#0a2233"], "fill-opacity": 0.8 },
    });
    map.addLayer({
      id: "cd-line", source: "cd", "source-layer": "districts", type: "line",
      paint: { "line-color": "#0e3a52", "line-width": 0.6 },
    });

    // Join the style feed to geometry via feature-state — tiles stay immutable,
    // colors update daily. Map and dossier can never disagree (contracts §5).
    map.on("sourcedata", (e) => {
      if (e.sourceId !== "cd" || !e.isSourceLoaded) return;
      for (const [ocdId, s] of Object.entries(feed)) {
        map.setFeatureState({ source: "cd", sourceLayer: "districts", id: ocdId },
          { fill: s.vacant ? "#2b2f33" : PARTY_COLORS[s.party] ?? PARTY_COLORS.NP });
      }
    });

    // Dossier open: tap district -> fetch pre-built JSON (zero backend, <300ms from CDN)
    map.on("click", "cd-fill", async (e) => {
      const ocdId = e.features?.[0]?.id as string | undefined;
      if (!ocdId) return;
      const pins = await (await fetch(`${DATA}/pins/cd.json`)).json();
      const officer = pins.find((p: { ocd_id: string }) => p.ocd_id === ocdId);
      if (officer) {
        const dossier = await (await fetch(`${DATA}/dossiers/${officer.person_id}.json`)).json();
        window.dispatchEvent(new CustomEvent("beholden:dossier", { detail: dossier }));
      }
    });
  });
  return map;
}

initMap(document.getElementById("root")!);
