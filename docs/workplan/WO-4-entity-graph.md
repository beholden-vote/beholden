# WO-4 — Entity graph + neighborhood view

**INTEGRATION lane, AFTER WO-1 and WO-3 merge · read README + `AGENTS.md` +
`docs/DATA-CONTRACTS.md` §4 (the binding contract) first**

## Objective
Materialize the §4 entity graph nightly and render it: every dossier's `graph_ref` resolves to
`/graph/neighborhood/{person_id}.json`, and the dossier UI gains a "Connections" view.
**Every edge carries evidence; correlation edges carry their caveat string. An edge with no
receipts is a bug.**

## Edges (compute from the spine; all pairwise within chamber/jurisdiction)
1. `cosponsorship` — count of shared bills (sponsor/cosponsor overlap) in the current
   congress. Evidence: up to 25 bill refs (`{kind:"bill", id, url}`) + `evidence_total`.
   NOTE: spine currently holds sponsors only — build sponsor↔sponsor shared-bill edges from
   what exists; extend to cosponsor rows only if WO-1/E2 data provides them (do not fetch new).
2. `co_voting` — agreement % over shared yea/nay roll calls (min 50 shared votes), top-N
   partners per person. Evidence: sample of 25 shared roll-call refs. Caveat NOT required
   (it's arithmetic on public votes) but state the formula in the payload (`method` field).
3. `shared_donor` — same contributor org in both members' top-25 for the cycle. Evidence:
   the FEC aggregate rows (`{kind:"fec_employer", name, a_total_cents, b_total_cents}`).
   **caveat (verbatim, from contract):** "shared top contributors are reported-employer
   aggregates; no coordination is implied".
4. `committee` — skip unless WO-6a has merged (then: count of shared committees).

## Files
- OWNED: NEW `pipelines/beholden_etl/build/graph.py` (edge computation + neighborhood
  emitter), NEW `web/src/ui/Connections.tsx` (view), NEW `web/src/lib/graph.ts` (fetch/types).
- SHARED (marked insertions): `jobs/build.py` (call graph builder; write
  `dist/data/graph/neighborhood/{person_id}.json`), `tests/test_pipeline.py`,
  `web/src/ui/DossierView.tsx` (a "Connections" section linking/embedding the view),
  `web/src/styles.css` (graph styles).

## Payload (contract §4 shape)
`{center, as_of, nodes:[{person_id,name,party,office_display}], edges:[{type,a,b,weight,
window,evidence:[...],evidence_total,caveat?}]}` — cap ~25 strongest edges per person,
strongest-first, symmetric truncation rule (same formula for everyone).

## Frontend
- Lazy-load the view (dynamic import — keep it out of the main chunk).
- Render: simple force layout or concentric list-first design; **list-first is acceptable and
  preferred over a heavy graph lib** — each connection is a row: person, edge chips
  (`cosponsored 18 bills`, `votes together 94%`, `3 shared top contributors`), expandable
  evidence with links. Party colors as data only; design per `web/DESIGN.md`.
- Caveat strings render verbatim wherever a `caveat` edge appears (contract requirement).

## Acceptance
- Tests: fixture proving edge math (cosponsorship count, agreement %, shared-donor match),
  evidence caps, caveat presence, symmetric truncation.
- Live: `data.beholden.vote/graph/neighborhood/{id}.json` serves; dossier shows Connections
  with evidence links resolving to congress.gov/FEC.

## Out of scope
Donor↔vote juxtaposition (WO-8), trade_cluster edges (needs itemized trades — vendor-gated),
cross-jurisdiction edges.
