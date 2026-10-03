# WO-35 — The reader shell: arrive, move, and get back out

**Lane F · prereq: WO-32 (merged) · read `AGENTS.md`, `docs/workplan/README.md`,
`web/DESIGN.md` (Rule 0 outranks everything in it), and `docs/DATA-CONTRACTS.md` §8.2 and
§8.6 first. §8.6 is normative for this work order.**

## Why this exists

The site answers "who represents me?" only after the reader has done the work: it opens on a
national map, waits for an address, and puts the answer in a drawer that is the full width
of a phone — so on the device most people use, the map disappears the moment it becomes
useful. And once in, there is no way back out: every navigation uses `history.replaceState`
(`web/src/router.ts`), so the browser's Back button leaves the site, and Escape closes
everything at once.

Later work orders add a voting record, bill pages, place facts and a stance profile. Each
needs somewhere to live and a way to reach it and leave it. This work order builds that
frame, so those lanes can each fill one slot without editing the same file.

## Objective

Five things, in this order of importance.

### 1. Three altitudes with real history

The reader is always at one of three altitudes — **place** (an area and everyone who
represents it), **person** (a dossier), **record** (a bill or a vote; arrives in a later work
order). Moving between altitudes **pushes** a history entry; flipping a tab inside a dossier
**replaces** it, as today. Consequences that must hold:

- Browser Back steps up exactly one altitude, and Forward returns.
- Escape steps up one altitude; from the top it closes the panel. (Today it closes
  everything from anywhere.)
- A breadcrumb shows the trail actually walked — `Hendersonville › TN-6 › Rep. X` — every
  crumb is a link, and a page opened cold from a shared link shows only itself.
- Opening a dossier that no longer exists (the official left office and the object was
  removed) says so plainly instead of doing nothing, which is what happens today.

Implement the route table in §8.6. `#/b/`, `#/v/` and `#/c/` are parsed and routed but their
views arrive later: build a **view registry** — route kind → lazily imported component —
under `web/src/ui/nav/`, so a later lane adds one entry and one file in its own directory.
An unregistered route kind falls back to home; do not ship placeholder screens.

### 2. A phone layout that keeps the map

Below 720px the panel becomes a **bottom sheet** with three stops — peek (a header strip),
half, full — draggable by a handle, operable by keyboard, with the map visible and
interactive above it at peek and half. Wider than that, the existing right-hand drawer
stays. No new dependency: pointer events and a CSS transform are enough. Honour
`prefers-reduced-motion`. Do not trap focus at peek or half; do at full.

### 3. Arrive on your own area

On a first load with no route in the URL, use the coarse location the edge already returns
(`/api/whereami`, called today in `App.tsx` only to drop a marker): fly there and open the
place view for that point, headed **approximate**. Say what that means in one line — the
statewide offices are right; a district may differ at the reader's actual address — and put
the two ways to fix it directly underneath: use my exact location, or type an address. If the
edge returns nothing, keep today's national view and show the same two actions as a prompt.
Never do this when the URL already carries a route or an info hash.

### 4. Remember a confirmed place, on the device only

When the reader confirms a place — by address or by granting location, never from the
approximate fix — store it in `localStorage` and open on it next visit, ahead of the
approximate arrival. Show a visible **Forget this place** control wherever the remembered
place is shown, and make it remove the stored value at once.

This changes a public promise, so the copy must be exact. The Privacy overlay
(`web/src/ui/chrome.tsx`, `Privacy()`) currently says the reader's location is "never sent to
us or stored". Rewrite that paragraph to say precisely what is now true: what is kept (the
place the reader confirmed), where (this browser's storage, on this device), what is not done
with it (it is never sent anywhere), and how to remove it. The remembered place must never
appear in a URL — shared links keep addressing a place by division id (`#/d/…`), exactly as
`Ballot.tsx` does now.

### 5. Act from the list

Each official's row in the place view currently shows a name and a party chip, and is one big
button into the dossier. Add:

- the **term end** from `pin.term_ends` (§8.2; absent or `null` renders nothing);
- a **Contact** control that reveals the same actions the dossier header has —
  `HeaderActions` in `web/src/ui/bits.tsx` — loading that official's dossier on demand through
  the existing cached `loadDossier`. Do not add contact fields to the pins feeds: they are
  fetched eagerly at startup for every official in the country.

A row therefore holds two controls, so it can no longer be a single `<button>`; restructure
it without nesting interactive elements.

Fold the stack view and the "Your ballot" view into one place view — they are the same list
in the same order — keeping the copy-link behaviour from `Ballot.tsx`.

## Files

**OWNED** — `web/src/ui/App.tsx` · `web/src/router.ts` · `web/src/ui/Ballot.tsx` ·
`web/src/main.tsx` · new `web/src/ui/nav/` · new `web/src/ui/sheet/` · new
`web/src/ui/place/` · `web/src/strings.ts` (additions)

Split `App.tsx` as you go: navigation into `ui/nav/`, the sheet into `ui/sheet/`, the place
view and its rows into `ui/place/`. Leave `App.tsx` as composition. Create empty-but-wired
`web/src/ui/votes/` and `web/src/ui/stand/` only if the view registry needs a directory to
point at — otherwise let the lanes that own them create them.

**SHARED — marked insertion points only** — `web/src/styles.css` (append your blocks; do not
reorder existing rules) · `web/src/ui/chrome.tsx` (**the `Privacy()` copy only** — the
Sources table and the layer control belong to other lanes this wave) · `web/src/map.ts` (only
what arrival needs) · `web/src/ui/bits.tsx` (**use** `HeaderActions`; do not edit the
provenance line, which WO-33 is changing) · `web/src/ui/DossierView.tsx` (only if the
breadcrumb or back control requires it; the footer is WO-33's) · `web/src/lib/data.ts`
(WO-33 is adding `loadCoverage` there — add, do not rearrange)

## Constraints

- **Rule 0.** Amber is the only chrome colour; party hues are data and never decorate
  navigation. Nothing here may treat officials differently by party.
- **Accessibility is part of the work, not a pass afterwards.** Focus moves to the new
  view's heading on every altitude change and returns to the control that opened it on the
  way back; the breadcrumb is a `nav` with `aria-current`; the sheet handle is a real control
  with a name and arrow-key support; touch targets are at least 44px.
- **No new runtime dependency** without a line in the PR saying why the platform could not
  do it.
- **Copy** that is money- or legal-adjacent belongs in `web/src/strings.ts`; overlay prose
  such as the Privacy page stays inline where it is.
- Keep the first-load budget: nothing in this work order may be added to the eager bundle
  that could be lazy.

## Acceptance

1. `cd web && npm run build` clean (it type-checks), and the pipeline gates still pass
   untouched.
2. Walk these in a real browser against live data (`npm run dev`), at **390px** and
   **1280px** wide, and say in the PR what you saw:
   - cold load → approximate place opens and is labelled approximate;
   - address → place → official → Back → Back returns to the map, and Forward retraces it;
   - Escape steps up one altitude each press;
   - at 390px the map is visible and pannable with the sheet at half;
   - Contact on a row reveals call / email / form actions without leaving the list;
   - confirm an address, reload → the same place opens; Forget this place, reload → the
     approximate arrival returns and `localStorage` no longer holds it;
   - a shared `#/d/…` link opens that place and contains no coordinates;
   - a `#/p/` link to a nonexistent id shows the not-found message.
3. Keyboard only: reach an official, open the dossier, and get back, with focus visible
   throughout.

## Out of scope

The voting record, bill and roll-call views (WO-23b) · the city layer, place facts card and
coverage page (WO-37) · the stance profile, map colour modes and compare view (WO-38) · real
path URLs and prerendering · any pipeline change.
