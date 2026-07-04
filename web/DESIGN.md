# Beholden — "Public Record" DESIGN.md

Civic-accountability aesthetic at the intersection of government digital service
and modern political tech. The look of the **public record itself** — disclosure
filings, roll-call sheets, official seals — rendered as a high-contrast,
interactive instrument. Data-dense × editorial × cinematic-dark.

> **Rule 0 (outranks this doc):** *symmetric by construction.* No color, weight,
> motion, or copy choice may favor a party. The chrome is party-neutral amber;
> blue and red appear **only** as equal-weight data encodings (map fills,
> ideology dots), never in UI chrome, never with unequal emphasis.

## 1. Visual theme & atmosphere
Deep sonar-navy field, like sounding depth. Content surfaces are raised, sharp-
edged, hairline-ruled — closer to an official document than a SaaS card. One warm
signal (amber/gold) carries action, focus, and "flagged for review" moments — the
color of a seal, not a party. Numbers, dates, and sources are set in mono: the
paper trail is visible, always. Mood: serious, transparent, confident, alive on
interaction.

## 2. Color palette & roles
```
--bg:            #06131d   /* sounding-depth base */
--bg-raise:      #0a1f2e   /* topbar / rail wash */
--surface:       #0e2536   /* panel + cards */
--surface-2:     #123049   /* nested row, hover wash */
--line:          #17384f   /* hairline rules */
--line-strong:   #21506e   /* active/hover borders */
--ink:           #eaf2f8   /* primary text (high contrast, ~13:1 on bg) */
--muted:         #8ba3b4   /* secondary */
--dim:           #5e788a   /* tertiary / axis */
--signal:        #f2b134   /* AMBER: action, focus ring, links, active nav */
--signal-hover:  #ffc451
--on-signal:     #06131d   /* ink on amber */
--flag:          #e8842b   /* late-filing / attention — warm, ≠ party red */
--good:          #56b98a   /* yea / within-SLA */
--bad:           #cf6b6b   /* nay / breach (still ≠ party red hue) */

/* DATA ENCODINGS — symmetric, equal luminance, never in chrome */
--party-D:       #4b83bd
--party-R:       #c25b5b
--party-I:       #8f8f5e
--party-L:       #9a8a5a
--party-G:       #5b9a63
--party-NP:      #64717c
--vacant:        #2b2f33
```
Roles: **amber = the only chromatic action color** (anti-slop: no teal, one accent).
Party hues are tuned to matched luminance so neither reads "louder." `--flag`/
`--bad` are deliberately off the party-red hue so accountability signals never
look like a partisan cue.

## 3. Typography
- **Display + UI:** `Space Grotesk` (500/700). Headlines 700, tracking −1%.
  Distinctive, civic-modern — *not* Inter/Roboto/system-ui.
- **Data, numerals, dates, provenance, OCD ids, tickers:** `IBM Plex Mono` (400/500),
  tabular. The govtech "receipts" voice; everything factual is monospaced.
- Section micro-labels: Space Grotesk 500, 11px, uppercase, tracking +8%.
- Scale: 11 / 12 / 13 / 14 / 16 / 20 / 26 / 34 / 46. Money/counts always mono-tabular.
- Fonts self-hosted via `@fontsource/*` (no third-party font CDN — privacy ethos).

## 4. Components
- **Buttons** — Primary: amber fill, `--on-signal` text, radius 4, weight 700.
  Ghost: text + amber on hover. No shadows.
- **Panel** — right dock, `--surface`, 1px `--line` left border, slides in 160ms.
  Header is a document masthead: name (display), office (mono), party chip.
- **Person row (stack)** — avatar + name + party chip + →. Hover: `--surface-2`,
  left border goes amber (the *one* semantic left-rule: "selectable"). Anti-slop:
  no decorative left-rules elsewhere.
- **Section** — hairline top rule + uppercase micro-label + a mono `[SOURCE ↗]`
  provenance tag pinned right. Provenance is a first-class design element, not fine print.
- **Stat** — big mono-tabular number, uppercase caption. Count-up on reveal.
- **Chips/party** — filled pill, party hue, `--ink`. Vacant = `--vacant`.
- **Ideology scale** — muted symmetric axis; the member dot is the hero, party-
  colored, with party & chamber median ticks. Dot eases to position on open.
- Container depth ≤ 2. Icon policy: type + a single set of inline glyphs (→ ↗ ×), no icon lib.

## 5. Layout
- Map is the full-bleed hero. Chrome floats over it (topbar gradient scrim, dock panel).
- 4px base: 4/8/12/16/24/32/48. Panel 300–440px, full-width < 560px.
- Editorial rhythm inside the dock: generous vertical breathing, max readable measure.

## 6. Depth, edges & motion — *light brutalist*
Exposed structure over polish: **hard edges (radius 0)** on the dock, sections,
chips, tags, and buttons; avatars are **squared** (an ID/dossier grid, not social
round). Depth is a **hard offset shadow, no blur** (`4px 4px 0` in ink or amber),
used selectively on the primary action and the selected row — the brutalist
signature, applied *lightly*. Structural dividers are visible **1–2px rules**, not
whisper-hairlines; section headers can carry a short leading amber block. Motion is
**stateful only**: selection glow on the chosen polygon, dock slide, ideology-dot
ease, number count-up. No ambient particles, no pulsing "live" dots.
`prefers-reduced-motion` disables all of it.

## 7. Do / Don't
**Do:** amber for every action; mono for every fact; hard square edges; exposed
1–2px rules; offset hard shadows on the one primary action + selection; squared
avatars and rectangular stamp-chips; matched-luminance party hues; visible
provenance; verb-first CTAs ("Find your reps").
**Don't:** teal accent; a second accent; party colors in chrome; soft rounded pills
or blurred drop-shadows; animated status dots; system-ui as the primary face; any
asymmetric-by-party emphasis.

## 8. Responsive
Dock → full-width sheet < 560px; topbar wraps search under brand; stats become a
2-up grid; mono tables → stacked KV. Type scales down one step per breakpoint.

## 9. Agent prompt guide
Bias: sounding-navy field, one amber civic signal, Space Grotesk display + IBM
Plex Mono data, sharp 4px edges, hairline rules, visible provenance tags, stateful
motion, strictly symmetric party encodings.
Reject: teal, second accent, party color in chrome, shadowed cards, Inter/system-ui
primary, pulsing dots, three-column hero grids, any partisan asymmetry.
