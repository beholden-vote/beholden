// Cloudflare Pages Function — private address geocoding at /api/geocode?q=…
//
// Proxies the OFFICIAL U.S. Census Bureau geocoder server-side. Two wins:
//  - authoritative government source (matches Beholden's "official sources" ethos);
//  - the browser only ever talks to our own origin, so no third-party geocoder
//    sees the user's keystrokes and there's no cross-origin exposure.
// Returns [{ label, lng, lat }] — exactly the shape lib/lookup.ts expects.

const CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress";

export async function onRequestGet({ request }) {
  const q = (new URL(request.url).searchParams.get("q") || "").trim();
  if (q.length < 4) return json([]);

  const url = `${CENSUS}?address=${encodeURIComponent(q)}&benchmark=Public_AR_Current&format=json`;
  try {
    // Edge-cache identical lookups for 5 min to spare the Census API.
    const res = await fetch(url, { cf: { cacheTtl: 300, cacheEverything: true } });
    if (!res.ok) return json([]);
    const data = await res.json();
    const places = (data?.result?.addressMatches ?? []).slice(0, 5).map((m) => ({
      label: m.matchedAddress,
      lng: m.coordinates.x,
      lat: m.coordinates.y,
    }));
    return json(places);
  } catch {
    return json([]); // upstream hiccup — the UI degrades to "no matches"
  }
}

function json(body) {
  return new Response(JSON.stringify(body), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=300",
      "access-control-allow-origin": "*",
    },
  });
}
