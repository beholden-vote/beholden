/** Address → coordinates, typeahead suggestions, and one-tap geolocation (E7-4).
 *
 *  The map tiles ARE the point-in-polygon index (arch §1.8): we only need a
 *  lng/lat, then the map resolves the full representation stack at that point.
 *
 *  Geocoding goes through our OWN origin — the /api/geocode Pages Function, which
 *  proxies the official U.S. Census geocoder. So no third-party sees the user's
 *  address, and there's no cross-origin call. Isolated here: swapping the geocoder
 *  is a one-line change to GEOCODE. Geolocation and the browser's own address
 *  autofill are fully client-side.
 */
export interface Place {
  label: string;
  lng: number;
  lat: number;
}

const GEOCODE = "/api/geocode";

/** Debounced typeahead: up to 5 US matches for a query. Empty under 4 chars (no
 *  request). Pass an AbortSignal so stale in-flight lookups cancel. The Census
 *  geocoder is authoritative but wants a fairly complete address, so matches
 *  firm up as the user finishes typing — never a wrong-but-confident guess. */
export async function suggest(query: string, signal?: AbortSignal): Promise<Place[]> {
  if (query.trim().length < 4) return [];
  try {
    const res = await fetch(`${GEOCODE}?q=${encodeURIComponent(query)}`, { signal });
    if (!res.ok) return [];
    return (await res.json()) as Place[];
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
