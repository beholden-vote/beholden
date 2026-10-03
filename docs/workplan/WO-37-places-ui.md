# WO-37 — Every place, on the map and in the panel

**Lane F · prereq: WO-21, WO-34, WO-35 (all merged) · read `AGENTS.md`,
`docs/workplan/README.md`, `web/DESIGN.md` (Rule 0 outranks everything in it), and
`docs/DATA-CONTRACTS.md` §8.4, §8.5, §8.10 and §8.11 first.**

## Why this exists

Every city in the country now has a boundary tile (§8.5), every county and city has Census
facts (§8.4), and `coverage.json` says what the pipeline did — and the site shows none of it.
The city level is still labelled "Awaiting place boundaries", clicking a county gives a name and
a FIPS code, and a reader cannot tell "no officials here" from "we do not cover this yet".

## Objective

1. **City layer and its zoom gate.** Add the `places` layer from
   `tiles/us-places-{vintage}.pmtiles` (§8.5) to the map and give the `place` entry in
   `web/src/lib/levels.ts` `GATES` a real layer and `minzoom`, ending the "unmapped" label.
2. **Area card.** Clicking a county or city shows its facts from `/areas/{level}/{st}.json`
   (§8.4), joined by `geoid`: population, households, median income, median age — **each with
   its margin of error** (a margin or no number; a field the file omits shows nothing, never a
   zero). The card cites its two sources and the vintages, and carries the Bureau's API
   notice if the Sources page does not already.
3. **Coverage-state fills.** Local polygons (counties' commissions, cities) are filled by
   coverage state from `/coverage/{st}.json` (§8.10): covered · partial · withheld · not
   covered yet. **Never by party** — local sources publish none. One neutral, accessible scale
   (not red/blue, not green/red); state is also stated in words on the card and in the legend.
4. **Pins by state.** Replace the eager `PIN_FEEDS` fetch of the county layer with the
   per-state shards of §8.11 (and the place layer), loaded when a division of that state first
   matters, cached for the session. `states`, `cd`, `sldu`, `sldl` stay as they are.
5. **A coverage page.** Reads `coverage.json` (nothing reads it today): per source, last
   checked and last changed (the §8.1 wording "checked ‹date› · unchanged since ‹date›"), counts,
   and the locality totals; plus the per-state coverage lists from §8.10.

## Files

**OWNED** — new `web/src/ui/places/` (area card, coverage page, legend) · new
`web/src/lib/areas.ts` · new `web/src/lib/coverage.ts`

**SHARED — marked insertion points only** — `web/src/lib/levels.ts` (`GATES`, the `place` entry
only) · `web/src/map.ts` (add the places source/layer and the coverage fill; follow `LAYERS`)
· `web/src/lib/data.ts` (**the pin loader only** — `PIN_FEEDS` / `loadPins`; keep the returned
`PinIndex` shape so the place view needs no change) · `web/src/ui/place/PlaceView.tsx` (mount
the area card at one marked point) · `web/src/ui/chrome.tsx` (the Sources table rows and the
layer control only) · `web/src/types.ts` (append under a `// WO-37` banner) ·
`web/src/styles.css` (append) · `web/src/strings.ts` (additions) ·
`web/src/ui/nav/registry.ts` is **not** touched: the coverage page is opened from the layer
control or footer, not through the record router.

## Constraints

- **Build against `web/fixtures/`.** Coverage and pin shards do not exist on the live site yet
  (WO-22b publishes them); `areas/` exists once the next nightly with the Census key has run.
  The loaders treat 404 as "nothing published" — an empty list, a "not covered yet" card — and
  never as an error.
- **Rule 0.** Amber is the only chrome colour; the coverage scale is data, matched-luminance,
  distinguishable without colour (pattern or label), and checked for the common colour-vision
  deficiencies. Document the scale in `web/DESIGN.md`.
- **Symmetric by construction.** Nothing about a place's presentation may depend on party.
- **Cost.** One shard per state reached; one areas file per state per level; no per-polygon
  request. Do not prefetch states the reader has not reached.
- **Accessibility.** The card is reachable and readable without the map; coverage state is text.
- **Honest numbers.** An estimate is shown with its margin or not at all; no derived rates, no
  rounding that hides the margin.

## Acceptance

1. `cd web && npm run build` clean.
2. Against fixtures at 1280px and 390px: the city layer appears at its gate and not before; a
   county and a city each open a card with correct facts and margins; a place with no coverage
   entry reads "not covered yet"; a withheld one says so and why; the legend explains every fill.
3. Network panel: no `/pins/county.json` request after the loader change, and one shard request
   per state reached.
4. The coverage page renders from a fixture `coverage.json` and states "checked … · unchanged
   since …" correctly when the two dates differ.
5. Live, once the next nightly has run: Sumner County (`47165`) shows a population estimate and
   its margin.

## Out of scope

Coverage-state *data* (WO-22b) · colour modes by position (WO-38) · school and special
districts · New England towns (`cousub`) · removing the monolithic `/pins/county.json`.
