/** Address → coordinates, typeahead suggestions, and one-tap geolocation (E7-4).
 *
 *  The map tiles ARE the point-in-polygon index (arch §1.8): we only need a
 *  lng/lat, then the map resolves the full representation stack at that point.
 *  Geocoding is isolated here behind one provider so it can be swapped in a
 *  single place — e.g. for a private Census-proxy Worker — without touching UI.
 *
 *  Provider: Photon (OpenStreetMap data, CORS-enabled, no API key). Note: the
 *  typeahead sends keystrokes to a third party; geolocation and the browser's
 *  own address autofill stay fully client-side.
 */
export interface Place {
  label: string;
  lng: number;
  lat: number;
}

const PHOTON = "https://photon.komoot.io/api";
// Bias suggestions toward the continental US centroid (soft — AK/HI still rank).
const US_BIAS = "lat=39.5&lon=-98.35";

interface PhotonFeature {
  geometry?: { coordinates?: [number, number] };
  properties?: Record<string, string | undefined>;
}

function toPlace(f: PhotonFeature): Place | null {
  const c = f.geometry?.coordinates;
  const p = f.properties ?? {};
  if (!c || p.countrycode !== "US") return null; // US officials only
  const line1 = [p.housenumber, p.street || p.name].filter(Boolean).join(" ");
  const line2 = [p.city || p.county, p.state, p.postcode].filter(Boolean).join(", ");
  const label = [line1, line2].filter(Boolean).join(", ") || p.name || "United States";
  return { label, lng: c[0], lat: c[1] };
}

/** Debounced typeahead: up to 5 US places for a partial query. Empty under 4
 *  chars (no request). Pass an AbortSignal so stale in-flight lookups cancel. */
export async function suggest(query: string, signal?: AbortSignal): Promise<Place[]> {
  if (query.trim().length < 4) return [];
  const url = `${PHOTON}?q=${encodeURIComponent(query)}&limit=8&lang=en&${US_BIAS}`;
  try {
    const res = await fetch(url, { signal });
    if (!res.ok) return [];
    const data = (await res.json()) as { features?: PhotonFeature[] };
    return (data.features ?? []).map(toPlace).filter((p): p is Place => p !== null).slice(0, 5);
  } catch {
    return []; // aborted or offline — the UI degrades to "no matches"
  }
}

/** Single best match for a submitted query (Enter without picking a suggestion). */
export async function geocode(query: string): Promise<Place | null> {
  return (await suggest(query))[0] ?? null;
}

/** Browser geolocation → coordinates. Fully client-side; the user consents via
 *  the native permission prompt. Rejects on denial/unsupported/timeout. */
export function geolocate(): Promise<{ lng: number; lat: number }> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) return reject(new Error("unsupported"));
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lng: pos.coords.longitude, lat: pos.coords.latitude }),
      (err) => reject(err),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  });
}
