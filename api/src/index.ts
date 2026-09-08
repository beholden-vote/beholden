/**
 * api.beholden.vote — metered bulk access to the published record.
 *
 * It sells packaging, never facts. Everything inside these artifacts is free,
 * one object at a time, at data.beholden.vote, and stays free: the facts are
 * public records and charging for them would be both wrong and unenforceable.
 * What costs money is getting ~8,000 of them in one request instead of ~8,000
 * requests — which is worth paying for precisely because we made the free path
 * deliberately unsuited to bulk (see the rate-limiting rule and robots.txt).
 *
 * Deliberately stateless: no accounts, no API keys, no database. That is not
 * minimalism for its own sake. The Privacy page promises "no accounts, no
 * sign-in", and x402 settles per request without the seller ever learning who
 * the buyer is — so the paid path keeps a promise an account system would break.
 *
 * It is also deliberately DELETABLE. It owns no state whose loss breaks
 * anything: the artifacts live in R2 and are rebuilt nightly from the pipeline.
 * When Cloudflare's Monetization Gateway leaves the waitlist, a declarative
 * edge rule replaces this file and the Worker goes away. Adding KV, D1, or a
 * key table would end that property — don't, without deciding to.
 */
import { Hono } from "hono";
import { paymentMiddleware } from "x402-hono";

/**
 * Wrangler delivers every [vars] entry as a plain string, but x402 narrows these
 * to `0x${string}` and its own Network union. The casts below are the boundary
 * where a runtime-configured value meets a compile-time type — declared here
 * once, deliberately, rather than sprinkled at the call site. A wrong value
 * fails at the facilitator, not at the type checker, which is why wrangler.toml
 * carries TODO markers on both.
 */
type Env = {
  BULK: R2Bucket;
  PAY_TO: string;
  FACILITATOR: string;
  NETWORK: string;
};

type PayTo = Parameters<typeof paymentMiddleware>[0];
type Routes = Parameters<typeof paymentMiddleware>[1];
type RouteNetwork = Extract<Routes[string], { network: unknown }>["network"];

const PRICE = "$2.00";

const app = new Hono<{ Bindings: Env }>();

/**
 * Free, and the product's own advertisement: what exists, how big, and the
 * sha256 of each artifact. A buyer compares digests and re-pulls only what
 * changed, so nobody pays twice for a snapshot they already hold. Making this
 * free is the difference between a shop window and a locked door.
 */
app.get("/v1/manifest.json", async (c) => {
  const obj = await c.env.BULK.get("v1/manifest.json").catch(() => null);
  if (!obj) return c.json({ error: "manifest unavailable" }, 503);
  return new Response(obj.body, {
    headers: {
      "content-type": "application/json",
      "cache-control": "public, max-age=300",
      "access-control-allow-origin": "*",
    },
  });
});

const ARTIFACTS = new Set(["dossiers.ndjson.gz", "graph.ndjson.gz"]);

/**
 * Runs BEFORE the payment middleware, and that order is the whole point.
 *
 * x402 settles the payment and then calls the next handler. If the object turns
 * out to be missing or R2 is unreachable at that point, the buyer has paid and
 * received an error — money moved, nothing delivered, and no refund path exists
 * because settlement is on-chain and final. So everything that can be known
 * before taking money is checked before taking money: the name is on the
 * allowlist, and the object is actually there.
 *
 * This leaves only a genuine race (the object vanishing between head and get),
 * which is as narrow as it gets without holding a lock we have no way to hold.
 */
app.use("/v1/bulk/*", async (c, next) => {
  const name = c.req.path.slice("/v1/bulk/".length);
  // An allowlist, not sanitising: the key space is two files, and an allowlist
  // cannot be traversed out of.
  if (!ARTIFACTS.has(name)) return c.json({ error: "no such artifact" }, 404);

  const head = await c.env.BULK.head(`v1/${name}`).catch(() => null);
  if (!head) {
    return c.json(
      { error: "artifact temporarily unavailable — not charging for it" },
      503,
    );
  }
  return next();
});

// Mounted per-request rather than at module scope so price and network read
// from env — testnet and mainnet differ by a variable, not a code change.
app.use("/v1/bulk/*", async (c, next) => {
  const network = c.env.NETWORK as RouteNetwork;
  return paymentMiddleware(
    c.env.PAY_TO as PayTo,
    {
      "GET /v1/bulk/dossiers.ndjson.gz": { price: PRICE, network },
      "GET /v1/bulk/graph.ndjson.gz": { price: PRICE, network },
    },
    { url: c.env.FACILITATOR as `${string}://${string}` },
  )(c, next);
});

app.get("/v1/bulk/:name", async (c) => {
  // Name already checked against the allowlist, and the object already known to
  // exist, by the guard above — both before any payment was taken.
  const name = c.req.param("name");

  // onlyIf forwards If-None-Match, so an unchanged snapshot answers 304 in a
  // few hundred bytes instead of resending tens of MB. This is the delta pull
  // the manifest's digests exist to enable.
  const obj = await c.env.BULK.get(`v1/${name}`, { onlyIf: c.req.raw.headers })
    .catch(() => null);
  // Only reachable via the narrow race described in the guard. Loud on purpose:
  // this is the one path where someone may have paid and got nothing.
  if (!obj) return c.json({ error: "artifact vanished mid-request" }, 503);
  if (!("body" in obj)) return new Response(null, { status: 304, headers: { etag: obj.httpEtag } });

  // Streamed straight from R2: the bytes never buffer in the isolate, so piping
  // a 40 MB body is I/O rather than CPU and the 10ms budget is untouched.
  return new Response(obj.body, {
    headers: {
      "content-type": "application/gzip",
      etag: obj.httpEtag,
      // NEVER edge-cache a paid response. A URL-keyed cache entry would hand
      // the artifact to the next caller for free — the one mistake here that
      // silently gives away the product rather than breaking loudly.
      "cache-control": "private, no-store",
    },
  });
});

export default app;
