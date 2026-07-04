/**
 * Beholden entry point (tickets E7-1/2/3).
 * map.ts owns MapLibre + PMTiles + interactions; ui/App.tsx owns the panel UI.
 * They meet here: map clicks flow into the React app through a handle ref.
 */
import { createRoot } from "react-dom/client";
// Self-hosted civic type (DESIGN.md §3): Space Grotesk display, IBM Plex Mono
// for every fact. Bundled locally — no third-party font CDN (privacy ethos).
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import { initMap, type BeholdenMap, type RawStackHit } from "./map";
import { App, type AppHandle } from "./ui/App";
import "./styles.css";

const mapRef: { current: BeholdenMap | null } = { current: null };
const handleRef: { current: AppHandle | null } = { current: null };

mapRef.current = initMap(
  document.getElementById("root")!,
  (hits: RawStackHit[], lngLat) => handleRef.current?.onMapSelect(hits, lngLat),
);

createRoot(document.getElementById("ui")!).render(
  <App mapRef={mapRef} handleRef={handleRef} />,
);

// Dev/test hook: drive the map programmatically (never used by product code).
declare global { interface Window { __beholden?: { map: BeholdenMap } } }
if (import.meta.env.DEV) window.__beholden = { map: mapRef.current };
