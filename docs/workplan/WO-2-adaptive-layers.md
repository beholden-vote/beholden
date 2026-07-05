# WO-2 — Zoom-adaptive layers + panel level sections

**Lane F · no prerequisites · read `docs/workplan/README.md` + `AGENTS.md` first**

## Objective
The map manages layer visibility by zoom by default ("Auto"), manual control preserved; the
representation panel groups officials into collapsible level sections. Prepares the UX for
county/city levels before they exist.

## Behavior spec
- **Auto mode (default ON, new master toggle in the existing `.layer-ctl`):**
  z<6 → `states`+`cd` visible, sld* hidden; z≥6 → sld* fade in (fill-opacity ramps 0→0.8
  over z6–7 via a zoom-interpolated paint expression, lines too); (future county layer slots
  at z≥8.5 — leave a commented registration point). No popping: use `interpolate` expressions
  rather than toggling visibility where possible; visibility:none only below the fade floor.
- **Manual mode:** touching any per-layer checkbox sets `mode:"manual"` (persisted in the
  existing `beholden:layers` localStorage blob, versioned). "Auto" re-check returns to auto.
- **Never auto-hide the selected level:** if a selection includes layer L, L stays interactive
  until the panel closes (track in map.ts selection state).
- **Panel level sections:** group `StackEntry[]` under headers Federal / State (County/City
  reserved); each section collapsible (default open), header shows count when collapsed.
  Preserve the one-person fast-path (single hit still opens the dossier directly).

## Files
- OWNED: `web/src/map.ts` (zoom logic, DEFAULT_VISIBLE → mode-aware controller),
  `web/src/ui/chrome.tsx` (LayerControl gains Auto toggle), `web/src/ui/App.tsx`
  (panel sections; layer-pref state shape), `web/src/styles.css` (section styles).
- SHARED: none beyond those (this lane owns web/ chrome; do not touch DossierView).

## Constraints
- Design per `web/DESIGN.md`: amber signal only, hard edges, mono for facts, stateful motion,
  `prefers-reduced-motion` respected for fades.
- Migrate old localStorage shape gracefully (missing `mode` → `"auto"` unless prefs differ
  from the old defaults, then `"manual"` — don't silently change what a user chose).
- `npm run build` green; no new deps.

## Acceptance
- Local preview: at z4 sld* invisible; zooming past 6.5 shows them without a pop; unchecking
  a box flips the mode indicator to manual and sticks across reload; re-checking Auto restores
  zoom behavior. Clicking a point with 4 hits shows two grouped sections.
- Live after deploy: beholden.vote renders, layer control shows Auto, console error-free.

## Out of scope
Permalinks/search/my-ballot (WO-5); county data (WO-6b provides tiles later; you only leave
the registration point).
