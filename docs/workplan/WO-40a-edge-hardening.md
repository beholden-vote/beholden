# WO-40a — Edge hardening: geocode and whereami

**Lane F/edge · prereq: none · read `AGENTS.md`, `docs/ARCHITECTURE.md` §5.1 (never put a
Worker in front of `data.beholden.vote`), `web/functions/api/geocode.js` and
`web/functions/api/whereami.js` first. First item of WO-40's scope, done early because both are
cheap.**

## Why this exists

`/api/geocode` is an unthrottled open proxy to a third-party geocoder (anyone can use the
site's quota and identity), and `/api/whereami` answers any origin, so any website can read a
visitor's approximate location through the visitor's browser. Both are Pages Functions on the
site host, not on the data host.

## Objective

1. `/api/whereami`: respond only to same-origin requests (check `Origin`/`Sec-Fetch-Site`; no
   permissive CORS header); return only what the client uses (coarse area, no IP, no extra
   headers); `Cache-Control: private, no-store`.
2. `/api/geocode`: same-origin only; accept only the query shape the UI sends (length-capped,
   US-only, no passthrough of arbitrary upstream parameters); cap upstream response size;
   request an identifying `User-Agent` per the upstream's policy; short private cache of
   identical queries is allowed. Rate limiting stays a Cloudflare dashboard rule (the owner's) —
   document the suggested rule in the PR, do not apply it.
3. Add a small offline test script (`web/functions/api/*.check.mjs`, runnable with `node`) that
   exercises both handlers with fake Request objects: foreign origin refused, same-origin
   served, oversized/odd query refused.

## Files

**OWNED** — `web/functions/api/geocode.js` · `web/functions/api/whereami.js` · new
`web/functions/api/handlers.check.mjs`

**SHARED** — `docs/ARCHITECTURE.md` (a short note on the two endpoints' contract) ·
`web/src/ui/App.tsx` / `web/src/ui/nav/SearchBar.tsx` only if a call site must change (it
should not; same-origin fetches keep working)

## Constraints

- Privacy: never log or return the visitor's IP or raw coordinates beyond what the UI needs;
  no new storage; the remembered place stays on the device.
- Do not break arrival (WO-35): verify arrival, "use my location", and address search against
  a local `wrangler pages dev` or the preview deploy; Playwright if available.
- No dependency additions.

## Acceptance

`cd web && npm run build` clean; the check script passes; a cross-origin `fetch` from another
origin is refused; the live site's arrival and address search still work after deploy (the
owner merges; integrator verifies).

## Out of scope

The Cloudflare rate-limit rule · replacing the geocoder · any change to `data.beholden.vote`.
