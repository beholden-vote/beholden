// Offline check: node web/functions/api/handlers.check.mjs
import assert from "node:assert/strict";
import { onRequestGet as geocode } from "./geocode.js";
import { onRequestGet as whereami } from "./whereami.js";

const H = "https://beholden.vote";
const req = (path, headers = {}, cf) => { const r = new Request(H + path, { headers }); if (cf) Object.defineProperty(r, "cf", { value: cf }); return { request: r }; };
const same = { "sec-fetch-site": "same-origin" };
const cross = { "sec-fetch-site": "cross-site", origin: "https://evil.example" };

// whereami
assert.equal((await whereami(req("/api/whereami", cross, { latitude: "1", longitude: "2" }))).status, 403);
assert.equal((await whereami(req("/api/whereami", {}, { latitude: "1", longitude: "2" }))).status, 403);
let r = await whereami(req("/api/whereami", same, { latitude: "38.9", longitude: "-77.0", city: "X", region: "DC" }));
assert.equal(r.status, 200);
assert.equal(r.headers.get("cache-control"), "private, no-store");
assert.equal(r.headers.get("access-control-allow-origin"), null);
assert.equal((await r.json()).lat, 38.9);
assert.equal((await whereami(req("/api/whereami", { origin: H }, { latitude: "1", longitude: "2" }))).status, 200);

// geocode (upstream stubbed)
let upstream = 0;
globalThis.fetch = async (u, o) => { upstream++; assert.ok(o.headers["user-agent"]); return new Response(JSON.stringify({ result: { addressMatches: [{ matchedAddress: "A", coordinates: { x: 1, y: 2 } }] } })); };
assert.equal((await geocode(req("/api/geocode?q=1600+Pennsylvania+Ave", cross))).status, 403);
assert.equal((await geocode(req("/api/geocode?q=1600+Pennsylvania+Ave", {}))).status, 403);
assert.equal(upstream, 0);
r = await geocode(req("/api/geocode?q=1600+Pennsylvania+Ave", same));
assert.deepEqual(await r.json(), [{ label: "A", lng: 1, lat: 2 }]);
assert.equal(r.headers.get("access-control-allow-origin"), null);
assert.equal((await geocode(req("/api/geocode?q=" + "a".repeat(201), same))).status, 400);
assert.equal((await geocode(req("/api/geocode?q=abcd&benchmark=x", same))).status, 400);
assert.equal((await geocode(req("/api/geocode?q=abcd%0Aefg", same))).status, 400);
assert.deepEqual(await (await geocode(req("/api/geocode?q=ab", same))).json(), []);
console.log("handlers.check ok");
