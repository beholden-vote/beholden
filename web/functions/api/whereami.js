// Cloudflare Pages Function — coarse "you are here" bearings at /api/whereami
//
// Returns the visitor's APPROXIMATE (city-level) location, derived by Cloudflare
// from the request IP at our own edge. No third party, no cookie, nothing stored
// or logged to a profile — it's handed straight back to the browser to drop a
// faint bearings marker without any geolocation permission prompt. The precise
// "locate me" button (browser geolocation) is separate and stays on the device.

export function onRequestGet({ request }) {
  if (!sameOrigin(request)) return new Response("Forbidden", { status: 403, headers: { "cache-control": "private, no-store" } });
  const cf = request.cf || {};
  const lat = parseFloat(cf.latitude);
  const lng = parseFloat(cf.longitude);
  const body = Number.isFinite(lat) && Number.isFinite(lng)
    ? { lat, lng, city: cf.city || null, region: cf.region || null, approximate: true }
    : {};
  return new Response(JSON.stringify(body), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      // Per-visitor answer: never let a shared cache hand one visitor's city to another.
      "cache-control": "private, no-store",
    },
  });
}

// Same-origin only: browsers set Sec-Fetch-Site (unforgeable from page JS); fall back to Origin.
function sameOrigin(request) {
  const site = request.headers.get("sec-fetch-site");
  if (site) return site === "same-origin";
  const o = request.headers.get("origin");
  return !!o && o === new URL(request.url).origin;
}
