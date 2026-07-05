# WO-8 — Donor ↔ vote juxtaposition (+ methodology pages)

**INTEGRATION lane, AFTER WO-4 merges (needs WO-1 votes + WO-3 donors) · read README +
`AGENTS.md` first. This WO carries the highest editorial risk — the constraints below are
not suggestions.**

## Objective
A dossier module that places money and votes side by side, each independently cited, with
zero causal language — and the public methodology pages that every explainer link already
points to (`/methodology#...`).

## The juxtaposition module
- In the dossier, after Campaign finance: **"Money & votes, side by side"** — left column:
  top contributors (from WO-3); right column: key votes on bills whose `policy_areas`
  exist (from WO-1/E2). A `policy_area` chip on each vote row is the only "relatedness"
  shown — chips are congress.gov's own policy-area taxonomy, not our inference.
- **Hard constraints:**
  - No sorting/highlighting that pairs a specific donor with a specific vote.
  - Copy comes from `strings.ts` and must be counsel-reviewable; the module carries the
    verbatim caveat: contributions are as reported to the FEC; votes are the public record;
    "presentation implies no causal relationship."
  - Identical layout/behavior for every member (symmetric by construction).
  - If either side lacks data, the module doesn't render (absent ≠ implied).

## Methodology pages (`/methodology`)
Static page (hash-anchored sections) in the SPA — the info-overlay pattern from
`web/src/ui/chrome.tsx` extended, or a scrollable page route via WO-5's router:
- `#dw-nominate` (ideology explainer — the dossier already links to it),
- `#key-votes` (WO-1's selection formula, verbatim),
- `#donor-rollups` (what FEC employer aggregates are and aren't),
- `#co-voting` (agreement math), `#shared-donors` (edge definition + caveat),
- `#sources` (link to the Sources overlay/registry).
Every formula must match the shipped code — cite the source file in a code comment.

## Files
- OWNED: NEW `web/src/ui/MoneyVotes.tsx`, NEW `web/src/ui/Methodology.tsx`,
  `web/src/strings.ts` (new strings — this WO owns the file for its duration).
- SHARED (marked insertions): `web/src/ui/DossierView.tsx` (mount the module),
  `web/src/ui/chrome.tsx` or `router.ts` (methodology route), `web/src/styles.css`.
- Pipeline: none (reads existing dossier fields).

## Acceptance
- Every dossier explainer/methodology link resolves to a real anchor.
- The module renders only when both sides exist; caveat text present verbatim; no string
  outside strings.ts; `npm run build` green; visual check on one R and one D member showing
  byte-identical structure.

## Out of scope
Industry classification of donors; any scoring/grading; press/share cards.
