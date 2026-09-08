# WO-30 — Metered bulk access (api.beholden.vote)

**Lane P+F · prereq: none · read `docs/workplan/README.md`, `AGENTS.md` first**

> **Status: not merged, and not mergeable yet.** The redistribution gate is built
> and passing, but no source outside the unambiguous US Government works has a
> recorded license determination — so the artifact this ships is currently
> *empty by design*. See Acceptance.

## Objective

Charge machines for bulk access to the published record while human access stays
exactly as free, as fast, and as unmetered as it is today.

The thing being sold is **packaging, never facts**. Every fact in the artifact is
already free, one object at a time, at `data.beholden.vote`, and stays that way —
they are public records, and charging for them would be both wrong and
unenforceable. What costs money is getting ~8,000 of them in one download instead
of ~8,000 requests. That is worth paying for only because the free path is
deliberately unsuited to bulk: `robots.txt` says so, and a rate-limiting rule on
`/dossiers/` + `/graph/` enforces it (shipped separately in `chore/edge-hygiene`).

## Data source

None new. The artifact is a repackaging of `dist/data`, which the nightly already
builds and validates.

## The constraint this work order exists inside

**A Worker must never sit in front of `data.beholden.vote`** — see
`docs/ARCHITECTURE.md` §5.1. Workers bill cache hits at the full per-request rate,
and a cold map load is 50–100 requests against the data host, so routing it
through compute exhausts the 100k/day free allowance at roughly 1,500 map loads a
day and turns every traffic spike into a bill. `api.beholden.vote` is a **separate
hostname** that only paying traffic touches; the free surface stays a bare bucket
behind a CDN, and its abuse controls live at zone level where they cost nothing.

## Files

**OWNED**
- `pipelines/beholden_etl/jobs/bulk.py` — stage 5, builds + uploads the artifact
- `api/{package.json,tsconfig.json,wrangler.toml,src/index.ts}` — the Worker
- `.github/workflows/deploy-api.yml`
- `docs/DATA-LICENSE.md`
- this file

**SHARED — marked insertion points only**
- `pipelines/beholden_etl/config.py` — `license` / `license_url` /
  `redistributable` on `Source`, and one determination per registry entry
- `pipelines/tests/test_pipeline.py` — appended WO-30 block
- `Makefile` — `bulk` target
- `.github/workflows/etl-nightly.yml` — one step after Publish
- `docs/workplan/README.md` — status-board row

**NOT TOUCHED:** `pipelines/beholden_etl/jobs/publish.py`, `web/src/lib/data.ts`,
`web/src/lib/graph.ts`, `web/src/map.ts`. The SPA does not change at all.

## Implementation notes

**The redistribution gate is the point of this work order.** A dossier enters the
artifact only when *every* provenance envelope in it names a source the registry
marks `redistributable=True`. `redistributable` defaults to `False`, and that
default is load-bearing: publishing a fact on a free public site and selling a
compiled copy of it are different acts under most terms. The FollowTheMoney
evaluation was a NO-GO on exactly a NonCommercial clause
(`docs/research/state-money-evaluation.md`), and §8 says a source with
incompatible terms does not ship. A source nobody has read the terms for is not
"probably fine" — it is undetermined, and undetermined stays out.

This is the same shape as *no provenance, no publish*: the registry refuses, so
forgetting cannot produce a leak. `_sources_in()` walks the document rather than
reading known section names, so a section added later cannot smuggle an
unlicensed source past the gate by virtue of being new.

**A separate bucket, not a prefix.** `beholden-private` has no custom domain, so
the Worker is the only route to it. A prefix inside the public bucket would be one
careless path change away from publishing the product for free. R2's free storage
tier is per-account, so the second bucket costs nothing.

**Stateless payment.** x402 settles per request without the seller learning who
the buyer is, which keeps the Privacy page's "no accounts, no sign-in" true on the
paid path too. No KV, no D1, no keys, no secrets — the Worker owns no state whose
loss breaks anything, so it can be deleted when Cloudflare's Monetization Gateway
(waitlist as of 2026-09-08) makes it a declarative edge rule.

**gzip, not zstd.** `zstandard` is a new dependency for ~10% on JSON that every
HTTP client already decodes as gzip. Revisit when the runtime reaches 3.14 and
`compression.zstd` is stdlib.

**Determinism.** `gzip` writes with `mtime=0` so identical inputs produce an
identical `sha256`. The manifest digest is then a real content identity a buyer
can compare across pulls, rather than a number that changes nightly because gzip
stamped the clock.

## Acceptance

1. `PYTHONPATH=pipelines python -m pytest pipelines/tests -q` green, including the
   WO-30 block: the gate is AND-across-sources, walks nested provenance, refuses
   unregistered sources, and the manifest digests match the bytes on disk.
2. `python -m ruff check pipelines/` clean; `cd api && npm ci && npm run typecheck`
   clean.
3. `make build && make bulk` locally produces `dist/bulk/{dossiers,graph}.ndjson.gz`
   and a `manifest.json` whose counts and digests match.
4. `wrangler dev --remote` returns the manifest free, `402` unpaid on
   `/v1/bulk/*`, `200` after payment on `base-sepolia`, and `304` on a repeat with
   `If-None-Match`.

**Blocking before merge — none of these are code:**

- [ ] **OpenStates license determination.** Underwrites ~7,400 of ~7,928 dossiers
      and decides whether a paid artifact can carry state coverage at all. Nothing
      about it is recorded anywhere in this repo.
- [ ] Determinations for `unitedstates_legislators` (CC0 is claimed in its own
      README but has not been read and recorded here — and it underwrites
      `identity` on *every* federal dossier, so the artifact is empty until this
      is done), `voteview`, `wikidata`, `sumner_county`, `hendersonville`.
- [ ] `docs/DATA-LICENSE.md` completed — the published dataset currently declares
      no terms at all. Prerequisite to a first sale.
- [ ] Cloudflare: create the `beholden-private` bucket; widen
      `CLOUDFLARE_API_TOKEN` to `Workers Scripts:Edit`; set the repo variable
      `R2_BULK_BUCKET`; put a real wallet in `PAY_TO` and flip `NETWORK` to `base`.
- [ ] **Explicitly allow Agent crawlers on `api.beholden.vote`** in AI Crawl
      Control. From 2026-09-15 Cloudflare blocks Agent crawlers by default on
      free-tier zones — which would block the exact traffic this product sells to,
      silently, before it ever sees a 402.
- [ ] Buy the dump once from a real wallet on mainnet. Do not ship a payment path
      nobody has paid.
- [ ] Copy: `README.md` ("nothing to meter"), the About overlay in
      `web/src/ui/chrome.tsx`, `docs/PRD.md` line 140 ("keyed, rate-limited").

## Out of scope (binding)

Self-serve checkout, Stripe, monthly usage metering, a key-management UI, and
per-call reads of individual dossiers — those are free at `data.beholden.vote`,
and charging for the same bytes at a different hostname is a toll booth beside a
free parallel road.

**Adding KV, D1, or a key table ends the Worker's deletability.** That property is
the reason this is ~90 lines instead of a service. Do not add state without
deciding to give that up.

If monthly quotas ever become genuinely necessary, use **D1** — one row, one
upsert, authoritative at request time — never Analytics Engine, which is sampled
and would give the artifact away.

## Follow-ons

- Commercial tier (flat annual, invoiced, HMAC key) — the revenue that actually
  matters at this scale. Deliberately not self-serve: selling it is an invoice and
  an email, which needs no checkout, dunning, or tax handling.
- A public API docs page (already on the board).
- Diff-based upload in `publish.py` — shipped separately in `chore/edge-hygiene`.
