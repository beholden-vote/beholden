# WO-38 — Where they stand: a profile, never a score

**Lane F · prereq: WO-36 (merged, `positions/{chamber}.json` live) · read `AGENTS.md`,
`docs/workplan/README.md`, `web/DESIGN.md` (Rule 0 outranks everything in it),
`docs/DATA-CONTRACTS.md` §8.7, and `web/src/ui/Ideology.tsx` + `web/src/ui/Methodology.tsx`
first. §8.7 is normative.**

## Why this exists

The dossier shows one left-right bar. WO-36 published what a fairer picture is made of — two
Voteview dimensions, four plain measures, a similarity layout — and nothing draws it. This work
order draws it, replacing the single bar, and lets the reader colour the map by a published
measure instead of only by party. There is no composite number anywhere (repo rule: no scores).

## Objective

1. **Profile card** in the dossier (replaces the single bar in `Ideology.tsx`): the member's four
   measures each as `n of of (pct)` with the formula one click away (`/methodology`), `null`
   rendered as "not enough votes" or "not applicable (independent)" — never as 0.
2. **Chamber plot**: all members on `nominate.dim1` x `dim2`, the viewed member highlighted.
3. **Similarity map**: all members at their `layout` coordinates, viewed member highlighted;
   members with `layout: null` listed beneath as "not placed (too few votes)". No cluster
   labels, no hulls, no names for groups — the file names none and the UI invents none.
4. **Map colour modes** in the layer control: party (today) · position (`nominate.dim1`,
   continuous) · with-own-party rate. One neutral, matched-luminance, colour-vision-safe ramp
   for the two numeric modes with a stated midpoint; legend explains it; local layers stay
   coverage-coloured and ignore the mode. Stylefeed colours come from `positions/` joined by
   `person_id`; fall back to party colour when a member has no value, and say so.
5. **Compare** (`#/c/{id}/{id}`): two officials side by side — measures, plot positions, and
   how often they voted together (from the two `votes/` files, decided votes on shared roll
   calls only; show `n`). Register `compare` in `ui/nav/registry.ts`.

## Files

**OWNED** — new `web/src/ui/stand/` · new `web/src/lib/positions.ts`

**SHARED — marked insertion points only** — `web/src/ui/Ideology.tsx` (mount the profile card;
retire the bar) · `web/src/ui/nav/registry.ts` (one entry: `compare`) · `web/src/map.ts` and
`web/src/lib/levels.ts` (colour modes only; do **not** touch the boundary band table) ·
`web/src/ui/chrome.tsx` (layer-control mode selector only) · `web/src/ui/Methodology.tsx`
(links to the existing measure entries) · `web/src/types.ts`, `web/src/styles.css`,
`web/src/strings.ts` (append under a `WO-38` banner) · `web/DESIGN.md` (document the ramp)

## Constraints

- **Symmetric by construction.** Same shapes, sizes and weights for every member and both
  parties; party appears only as the existing data hue, never ordering or emphasis. A written
  symmetry check (swap-parties screenshot comparison) goes in the PR.
- **No composite, no rank, no label** such as "moderate", "extreme", "bloc". Review fails it.
- **Ranges and absence are honest:** show `n`/`of` beside every percentage; omit, never zero-fill.
- **Accessibility:** plots have a text/table alternative; position is never colour-only;
  keyboard-operable; reduced-motion respected; contrast checked. 390px usable.
- **Cost:** one `positions/{chamber}.json` per chamber, loaded on first need and cached; no
  per-member fetch.
- Build against `web/fixtures/` (add realistic `positions/senate.json`); verify once against
  live data.

## Acceptance

1. `cd web && npm run build` clean. 2. Fixtures and live: profile card, chamber plot, similarity
map render for a House member, a Senate member, and an independent (`with_other_party: null`).
3. Colour modes switch without reload; legend and midpoint stated; falls back with notice.
4. Compare page for two members; agreement equals a hand count from their `votes/` files.
5. Playwright screenshots at 1280px and 390px; keyboard pass.

## Out of scope

State legislators (WO-17b) · new pipeline output · clustering or naming blocs · anything
predictive.
