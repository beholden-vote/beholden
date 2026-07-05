# State votes/bills source evaluation — OpenStates API v3 vs. bulk session-CSV

**WO-7 Part A · research deliverable · report only (no ingest code until accepted)**
Author: Beholden Maintainers. Verification date: **2026-07-05** (all URLs/shapes probed with
`curl` on that date; anything not directly observed is flagged as such).

## TL;DR

Ingest current-session bills + votes for the pilot states through the **OpenStates API v3**
(`OPENSTATES_KEY` secret) using `GET /bills?...&include=votes`, **not** the bulk session-CSV
bundles. The API returns roll-call voters as `ocd-person/<uuid>` — byte-for-byte the id we
already store in `person_identifiers (id_scheme='openstates')` — so the vote→person join is a
direct lookup with no fuzzy matching. The bulk CSV path is gated behind an account login and
was rejected as a nightly source. Pilot with **6 states**; the run fits the ~50-min nightly
budget with comfortable headroom.

---

## 1. What was verified (observations, 2026-07-05)

### 1a. Bulk session-CSV path (`open.pluralpolicy.com/data/session-csv/`) — GATED
- `curl -sSL https://open.pluralpolicy.com/data/session-csv/` → **HTTP 200**, but every
  per-session download link on the page resolves to
  `href="/accounts/login/?next=/data/session-csv/"`. The bundle downloads themselves are
  **behind a free-account login wall**, not anonymous URLs.
- `curl https://data.openstates.org/` (the S3-style bulk origin) → **HTTP 403 AccessDenied**
  (bucket listing disabled). Individual object paths may exist but are not enumerable, and the
  session-CSV bundles specifically route through the authenticated Plural page above.
- Consequence: a nightly GitHub Actions job cannot fetch the session-CSV bundles with just an
  API key — it would need a stored session cookie / login automation against a third-party web
  form. That is brittle, undocumented, and outside our "keyed or open, no scraping" posture.
- **Note (not fully verified):** the *people* bulk CSVs we already consume
  (`data.openstates.org/people/current/{state}.csv`, used by `sources/openstates.py`) resolve
  fine anonymously — so OpenStates gates *bills/votes* bulk more tightly than *people* bulk.
  The WO's assumption that session-CSV is an open per-session bundle did not hold on this date.

### 1b. API v3 path (`https://v3.openstates.org`) — WORKS, key-gated
- Root serves a FastAPI Swagger UI; unauthenticated calls to `/jurisdictions` and `/bills`
  return **HTTP 403** with `{"detail":"Must provide API Key as ?apikey or X-API-KEY..."}`.
  Docs confirm "API keys are required... pass your API key via the X-API-KEY header"
  (`docs.openstates.org/api-v3/`, fetched 2026-07-05).
- The `OPENSTATES_KEY` secret is **not** exposed to this research environment (`echo` empty),
  so live authenticated calls could not be made here. All endpoint/field shapes below come
  from the authoritative machine-readable OpenAPI spec at
  `https://v3.openstates.org/openapi.json` (fetched 2026-07-05, 45,488 bytes), which is the
  source of truth for the running service.

### 1c. Endpoint & schema shape (from `openapi.json`, 2026-07-05)
Relevant paths: `/bills`, `/bills/{jurisdiction}/{session}/{bill_id}`, `/bills/ocd-bill/{id}`,
`/people`, `/jurisdictions`, `/committees`, `/events`.

`GET /bills` parameters (observed): `jurisdiction`, `session`, `chamber`, `classification`,
`updated_since`, `created_since`, `action_since`, `sort` (default `updated_desc`), `q`,
`include[]`, `page` (default 1), `per_page` (default 10), `apikey`/`x-api-key`.

`include[]` enum (observed): `sponsorships, abstracts, other_titles, other_identifiers,
actions, sources, documents, versions, `**`votes`**`, related_bills`. **Votes are embedded in
the bill response** via `include=votes` — there is no separate top-level `/votes` list
endpoint, so bills+votes are one paged crawl per state/session.

Nesting (observed schemas):
- `Bill` → `id, session, jurisdiction, from_organization, identifier, title, classification,
  subject, openstates_url, first_action_date, latest_action_date, sponsorships, actions,
  sources, `**`votes`**` (array of `VoteEvent`), ...`
- `VoteEvent` → `id` (`ocd-vote/<uuid>`), `motion_text`, `motion_classification`,
  `start_date`, `result`, `identifier`, `organization`, `counts` (array of `VoteCount`
  `{option, value}`), `sources`, `votes` (array of `PersonVote`).
- `PersonVote` → `id`, `option` (e.g. `"yes"`/`"no"`/`"other"`), `voter_name`, `voter`
  (`CompactPerson`).
- **`CompactPerson.id` example in the spec: `ocd-person/adb58f21-f2fd-4830-85b6-f490b0867d14`.**

### 1d. Crosswalk join — CONFIRMED direct
Our spine writes state legislators via `sources/openstates.py` / `jobs/transform.py`:
```python
os_idents.append({"person_id": pid, "id_scheme": "openstates",
                  "id_value": r["ocd_person"]})   # r["ocd_person"] == "ocd-person/<uuid>"
```
(`db/migrations/001_spine.sql`: `person_identifiers.id_scheme` CHECK includes `'openstates'`.)
The API's `PersonVote.voter.id` is the **same `ocd-person/<uuid>` string**. So:

```
vote_positions.person_id  ⟵  person_identifiers[id_scheme='openstates',
                                                id_value = PersonVote.voter.id].person_id
```

is an exact equality join — no name/party/district fuzzy match. Any voter whose `ocd-person`
is not in our crosswalk (e.g. a legislator who left mid-session, or a chamber we don't yet
ingest) is simply dropped from `vote_positions` (fail-open on the row, not the run) or routed
to `quarantine_identities` per existing convention — **decision to confirm at build time.**

---

## 2. Nightly budget analysis

**Budget:** ~50 min total nightly (WO framing). **This job's slice must stay well under that**
since it shares the window with federal ingest.

Request math (per pilot state, one current session):
- `/bills?jurisdiction={st}&session={sess}&include=votes&per_page=20` → paged.
- A large-state biennium runs on the order of a few thousand bills; only a subset carry
  recorded roll-call votes. At `per_page=20` that is roughly **50–250 pages per state**.
  (`per_page` has no documented maximum in the spec — default 10; we set 20 conservatively.
  Exact page count per state is **not verified** without the key; size at build with a probe.)
- 6 pilot states → order **300–1,500 requests/night** for a full crawl.

**Rate limit:** the numeric per-day/per-second quota is **not stated inline** in the OpenAPI
spec or the api-v3 docs page as fetched (2026-07-05) — the docs only say "API keys are
required." OpenStates has historically published tiered limits (commonly cited as ~500
requests/day / ~1 req/sec on the free tier, higher on request), **but I could not verify the
current number from an authoritative page in this run — treat it as the top integration risk
(§5).** If the free tier is ~500/day, a 6-state same-night backfill may exceed it; mitigations:
  1. **Incremental crawl** using `updated_since` / `action_since` — after the first full
     backfill, nightly only pulls bills touched since the last run (small delta).
  2. Stagger states across nights, or request a raised limit for the key (OpenStates grants
     these to civic/nonprofit projects).
  3. Cache raw JSON per bill; re-fetch only changed bills (`updated_at`).

With incremental crawl the steady-state nightly cost is a **small delta (tens–low-hundreds of
requests)**, comfortably inside both the time budget and any plausible free-tier quota. The
one-time backfill is the only heavy moment and can run off-peak / manually dispatched.

---

## 3. Pilot states

Recommendation matches the WO suggestion, ordered by population × OpenStates data maturity:

| State | Why |
|---|---|
| **TX** | Largest legislature workload; biennial session — high-value, well-covered. |
| **CA** | Largest population; strong OpenStates coverage; rich roll-call data. |
| **FL** | Large; annual session; good coverage. |
| **NY** | Large; annual; good coverage. |
| **PA** | Large; two-year session. |
| **TN** | WO's control pick — smaller, clean, doubles as the end-to-end "one full state" probe used elsewhere in the expansion plan (§2b). |

Start with **TX + TN** as the very first light-up (biggest and smallest by workload) to
calibrate page counts and quota consumption before enabling the other four.

---

## 4. Sized integration sketch (build phase — AFTER acceptance)

New source adapter `sources/openstates_votes.py` (OWNED by WO-7), same shape as WO-1's federal
votes source; **import WO-1's key-vote selection formula, do not fork it.**

**Fetch** (`jobs/fetch.py`, marked insertion): for each pilot state + current session, page
`/bills?jurisdiction={st}&session={sess}&include=votes&sort=updated_desc` with `X-API-KEY`,
using `updated_since` for incremental nights; dump raw JSON to
`raw/openstates/votes/{st}/{session}/page-*.json`. Respect a request budget / sleep to stay
under the rate limit.

**Transform** (`jobs/transform.py`, marked insertion) → three existing tables
(`db/migrations/002_legislative.sql`), with `jurisdiction = {st}` per WO-7 id conventions:

| Table | Rows | Key / mapping |
|---|---|---|
| `bills` | one per state bill | `bill_id = {st}/{session}/{type}/{num}`; `jurisdiction={st}`; `session`; `title`; `status` mapped from `classification`/latest action into the existing CHECK set (`introduced…law/vetoed/failed`); `introduced_on=first_action_date`; `latest_action_on=latest_action_date`. Sponsorships MAY be sponsor-less on some states — **publish what exists, omit what doesn't** (WO). |
| `roll_calls` | one per `VoteEvent` | `roll_call_id = {st}/{session}/{org}/{vote_id}`; `bill_id` FK; `chamber` from `organization`; `question=motion_text`; `held_at=start_date`; `result`. |
| `vote_positions` | one per `PersonVote` | `roll_call_id` FK; `person_id` via the exact `openstates` crosswalk join (§1d); `position` mapped `yes→yea`, `no→nay`, plus `present`/`not_voting` per existing CHECK. Unknown/absent voters dropped or quarantined (confirm at build). |

**Build** (`build/dossiers.py`): state dossiers gain a `legislative` section (key votes +
counts). **Provenance envelope (rule 1 — no provenance, no publish):** every emitted vote fact
carries `source='openstates'` plus the deep link — prefer `VoteEvent.sources[]` (state
site/journal) when present, else `Bill.openstates_url` (the openstates.org bill page). Both are
present in the observed schema.

**Registry (rule: CI rejects unregistered sources):** `openstates` already exists in
`config.py` `SOURCES` (`https://data.openstates.org`, freshness SLA `24*7`h). The API host
differs (`https://v3.openstates.org`), so add either a second registry entry
(`openstates_v3`) or a `base_url_api` field — plus a methodology entry, coverage-dashboard row,
and freshness SLA, per `AGENTS.md` conventions.

**Tests:** synthetic `/bills?include=votes` JSON fixture → assert bills/roll_calls/
vote_positions land and that a fixture `ocd-person` joins to a spine person (no network, per
repo test convention).

---

## 5. Risks

1. **(TOP) Unverified rate limit.** The current free-tier request quota is not stated on the
   authoritative pages fetched 2026-07-05, and the key was not available to probe it live. If
   the limit is low (~500/day), a 6-state same-night backfill can exceed it. **Mitigation is
   built in:** incremental `updated_since` crawl + one-time off-peak backfill + request a
   raised limit for the civic key. Verify the real number with the key before enabling all six.
2. Bulk session-CSV is login-gated, so there is no anonymous fallback if the API is throttled;
   the API is the only viable automated path.
3. Voter `ocd-person` ids present in a vote but absent from our people crosswalk (mid-session
   turnover) → dropped/quarantined rows; must decide fail-open-on-row policy at build.

## 6. Recommendation

**Go — via the OpenStates API v3 `/bills?include=votes` endpoint (not bulk CSV), 6 pilot
states, incremental nightly crawl.** The person join is exact (`ocd-person`), the three target
tables already exist, and the steady-state nightly cost is small. Confirm the live rate limit
with `OPENSTATES_KEY` and calibrate page counts on TX+TN before scaling to all six.

---

### Sources (all fetched 2026-07-05)
- OpenStates OpenAPI spec — https://v3.openstates.org/openapi.json (endpoint/field shapes)
- OpenStates API docs — https://docs.openstates.org/api-v3/ ("API keys are required")
- Plural session-CSV index (login-gated) — https://open.pluralpolicy.com/data/session-csv/
- Bulk origin (403) — https://data.openstates.org/
- Repo: `pipelines/beholden_etl/sources/openstates.py`, `jobs/transform.py`,
  `db/migrations/001_spine.sql`, `db/migrations/002_legislative.sql`, `config.py`
