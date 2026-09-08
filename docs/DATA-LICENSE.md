# Data licence — the published record

> **Draft. Not yet in force.** `LICENSE` (MIT) covers the *code* in this repo.
> The *published dataset* at `data.beholden.vote` has never declared terms, and
> this file exists to fix that. It is a prerequisite to WO-30 (metered bulk
> access): selling access to a dataset whose own terms are undeclared is not a
> position this project should be in. **Needs counsel review before it ships**,
> in the same way `docs/PRD.md` open question O3 already contemplates.

## The position

Beholden compiles public records. The underlying facts — how someone voted, what
committee they sit on, what their campaign reported raising — are records of
government activity, and this project does not claim ownership of them. Anyone
may use them, including commercially, and never needs our permission to do so.

What Beholden adds is the compilation: the identity spine that unifies a dozen
incompatible ID schemes, the provenance envelope on every fact, the credibility
grade, and the shape of the documents. **The intended terms for that compilation
are CC0 / public domain** — the same position the PRD takes when it calls the
Builder a first-class persona and says "the commons we build compounds."

This has a direct consequence that must not be lost: **the paid tier sells
delivery, not rights.** A buyer of the bulk artifact is paying for one download
instead of ~8,000 requests, for digests that let them pull only what changed, and
(eventually) for support and a freshness commitment. They are not buying
permission, because permission was never ours to sell. Anyone who prefers to
fetch the free objects one at a time may do so forever.

## Attribution

Not a condition, but asked for plainly: cite **Beholden (beholden.vote)** and,
better, cite the underlying official source — every fact carries its
`source_url`, so the receipt travels with the data.

## Per-source terms

The compilation's terms cannot be more permissive than the terms of what goes
into it. Each source carries its own determination, recorded verbatim in
`pipelines/beholden_etl/config.py` next to the source itself and enforced by
`redistributable` (TRUSTED-EXTRACTION §8).

| Source | Determination | May enter a paid artifact |
|---|---|---|
| `congress.gov` | US Government work, 17 U.S.C. §105 | ✅ |
| `fec` | US Government work, 17 U.S.C. §105 | ✅ |
| `house_clerk` | US Government work, 17 U.S.C. §105 | ✅ |
| `senate_efd` | US Government work, 17 U.S.C. §105 | ✅ |
| `census_tiger` | US Government work, 17 U.S.C. §105 | ✅ |
| `wa_pdc` | Public Domain, per TRUSTED-EXTRACTION §12 | ✅ |
| `unitedstates_legislators` | **Undetermined** — CC0 claimed upstream, not yet read and recorded here | ❌ |
| `voteview` | **Undetermined** — roll calls are government works; DW-NOMINATE is Voteview's own scholarship, a separate question | ❌ |
| `openstates` | **Undetermined** — the blocking one; ~7,400 of ~7,928 dossiers | ❌ |
| `wikidata` | **Undetermined** | ❌ |
| `sumner_county` | **Undetermined** | ❌ |
| `hendersonville` | **Undetermined** | ❌ |

"Undetermined" means nobody has read and recorded the terms — not that the terms
are bad. Facts from these sources publish freely on the site exactly as they do
today; they are withheld only from a paid artifact, until someone does the
reading. Until that happens the bulk artifact is **empty**, which is the correct
behaviour rather than a bug to route around.

## What this project will not do

- Ship data on a licence assumption. FollowTheMoney was a documented NO-GO on a
  NonCommercial clause (`docs/research/state-money-evaluation.md`); Ballotpedia,
  VoteSmart, TransparencyUSA and LegiScan were rejected on licensing too. The
  same standard applies to our own outbound terms.
- Charge for a fact anyone can read for free on the site.
- Let a paid tier become a reason to publish less. If those two ever conflict,
  the free surface wins.
