/**
 * Address -> representation stack, with zero backend (ticket E7-4 / arch §1.8):
 * 1. Census Bureau geocoder (free public API) -> lat/lng
 * 2. queryRenderedFeatures at that point -> every district polygon containing it
 * The tiles ARE the point-in-polygon index.
 */
import type maplibregl from "maplibre-gl";

const CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress";

export async function geocode(address: string): Promise<{ lng: number; lat: number } | null> {
  const url = `${CENSUS}?address=${encodeURIComponent(address)}&benchmark=Public_AR_Current&format=json`;
  const res = await fetch(url);
  const match = (await res.json())?.result?.addressMatches?.[0];
  return match ? { lng: match.coordinates.x, lat: match.coordinates.y } : null;
}

export function representationStack(map: maplibregl.Map, lngLat: { lng: number; lat: number }) {
  const point = map.project([lngLat.lng, lngLat.lat]);
  const features = map.queryRenderedFeatures(point, {
    layers: ["states-fill", "cd-fill", "sldu-fill", "sldl-fill"].filter((l) => !!map.getLayer(l)),
  });
  // Full OCD stack for the point — state, CD, and both state chambers.
  return features.map((f) => f.id as string);
}
