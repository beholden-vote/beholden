# Beholden — Brand Identity

**Status:** v1.0, 2026 · the canonical, approved identity. Assets live in
[`docs/brand/`](brand/); this file is the long-term reference for what they mean,
how to use them, and the rules that keep the mark from drifting.

---

## The mark: `[B]`

**Beholden's mark is the letter B held inside a source bracket** — the same
`[SOURCE ↗]` bracket shape used everywhere in the app to cite a fact back to its
official record. It says the whole thesis in three glyphs: **a claim is only real
when it's cited**, and the mark itself is a citation tag around the brand's own
initial.

This was the converged pick of a four-round exploration (six early directions —
a sworn-check seal, scales of balance, a colonnade, a ledger, a magnifier — see
"why not the others" below) that kept circling back to one hard constraint: a
bold gold letterform on a filled disc reads as a cryptocurrency coin, not a
civic-transparency mark. Moving the gold to the *brackets* (stroke, not fill),
and keeping the letter itself in ink, breaks that read entirely — the amber
becomes punctuation around a fact, never a coin.

### Why not the others (exploration log)

Six early concepts were explored before the mark converged on `[B]`:

| Concept | Read | Why it lost |
|---|---|---|
| The Sworn Check | a stamped check inside a seal | Strong, but generic — closer to a notary/verification-service mark than a civic-data one. |
| The Balance | scales — literally Rule 0, symmetric by construction | Best *conceptual* fit, but scales are an extremely common civic-tech/legal cliché. |
| The Colonnade | a statehouse portico, reduced to brutalist geometry | Instantly civic, but a common government-tech shape — low ownability. |
| The Ledger | a roll-call sheet's line items | Quiet and on-voice (pairs with the mono "receipts" register), but weak as a small-size mark. |
| Scrutiny (magnifier + check) | watchdog scrutiny landing on a verified fact | Solid, but a bold gold circle-and-handle reads as a magnifying glass *or* — at a glance — a coin, depending on weight. |
| Bare "B" monogram | simplest possible avatar | Unownable on its own; bracket-around-a-letter is a genre no notable brand holds, and it *is* the product (a value inside a source tag) — the brackets were the missing piece. |

The brackets also do double duty: `[B]` **is** a lockup of `Beholden` (the
bracketed first letter of the wordmark) *and* a working citation glyph the app
already uses everywhere. One mark, two jobs.

## Geometry

```
BRACKETS   squared, radius 0 — never rounded
LETTER     Space Grotesk 700 (the same face as the wordmark)
WEIGHT     bracket stroke ≈ the B's own stem weight
STROKE     linecap: square · linejoin: miter (no rounded joints, ever)
CLEAR SPACE   ≥ one bracket-tip of space on every edge
MIN SIZE      20px on screen · 10mm in print
              (thicken the bracket stroke below ~32px so it doesn't vanish)
```

Construction reference: [`docs/brand/mark-source-tag.svg`](brand/mark-source-tag.svg).

## Colorways

| File | Use | Field | Brackets | Letter |
|---|---|---|---|---|
| [`mark-source-tag.svg`](brand/mark-source-tag.svg) | **Primary.** Hero lockups, dark UI, anywhere the mark stands with the wordmark. | Navy `#06131d` | Amber `#f2b134` | Ink `#eaf2f8` |
| [`avatar.svg`](brand/avatar.svg) | **Avatar / app tile.** GitHub avatar, favicon, social preview, anywhere the mark stands *alone* in a square. | Amber `#f2b134` | Navy `#06131d` | Navy `#06131d` |
| [`mark-mono.svg`](brand/mark-mono.svg) | Single-color contexts on a dark surface (e.g. a footer stamp). | Surface `#0e2536` | Ink `#eaf2f8` | Ink `#eaf2f8` |
| [`mark-knockout.svg`](brand/mark-knockout.svg) | Print on light paper. | Ink `#eaf2f8` | Navy `#06131d` | Navy `#06131d` |

**Never** a fifth colorway: no gradient, no second accent hue, no red/blue tint on
the mark itself (red/blue are data encodings for party — see Rule 0 below — and
tinting the mark itself would visually claim a side).

## GitHub avatar & app-tile sizes

The bracket stroke is drawn at a fixed proportion of the tile, so it thins as the
tile shrinks — past a point that reads as *nothing*, which is why the spec calls
for thickening below ~32px if you're hand-tuning a specific export. Reference
ladder (amber/navy colorway): **300 / 120 / 56 / 28 px.** A ready 512px export of
the avatar colorway is at [`docs/brand/avatar.svg`](brand/avatar.svg).

## Social / OG card (2:1)

[`docs/brand/social-card.svg`](brand/social-card.svg) — navy field, the mark +
wordmark lockup top-left, the headline ("See who represents you — and what
they've actually done."), and the mono amber tag line
`[ EVERY FACT LINKED TO ITS SOURCE ↗ ]`. A faint oversized bracket sits
decoratively on the right, echoing the mark at large scale without competing
with it.

*Note for exporting a PNG:* this file references Space Grotesk / IBM Plex Mono by
name. A real browser (or any renderer with access to those fonts — the app
already self-hosts both via `@fontsource`) renders it correctly; a font-less
headless SVG rasterizer will substitute a fallback face for the headline text.
Render it through a browser (or the app's own font-loaded context) before using
it as a real `og:image`/Twitter-card asset.

## Type & color

The identity shares its exact palette with the shipping app — this is not a
separate brand-vs-product palette, it is the SAME `:root` tokens defined in
[`web/src/styles.css`](../web/src/styles.css) and documented for UI use in
[`web/DESIGN.md`](../web/DESIGN.md). This file is the reference for the *mark*;
`web/DESIGN.md` is the reference for using these tokens in the UI.

| Token | Hex | Role |
|---|---|---|
| Sounding navy | `#06131D` | `--bg` · base field |
| Surface | `#0E2536` | `--surf` · panels |
| Signal amber | `#F2B134` | `--sig` · **the one action/chrome color** |
| Ink | `#EAF2F8` | `--ink` · primary text |
| Muted | `#8BA3B4` | `--mut` · secondary text |

**Space Grotesk** (500/700) — display & UI, including the mark's letterform and
every headline. **IBM Plex Mono** (400/500) — data, dates, provenance, and the
`[SOURCE ↗]` citation voice the mark itself echoes.

## Rule 0 (inherited from `web/DESIGN.md`, binding on the mark too)

> Amber is the only chrome/action color, everywhere — the mark included. Party
> hues (`--party-D`, `--party-R`, …) are data encodings only; they never
> decorate the mark, the wordmark, or any piece of navigational chrome.

This is why the mark's amber is always brackets/field, never a red or blue tint,
and why the layer-menu category headers (Federal/State/Local) are grouped by
amber-intensity weight rather than given their own hues — see
[`web/src/styles.css`](../web/src/styles.css)'s `.layer-group` rules.

## Do / Don't

**Do** — keep the brackets squared and hard-edged · match bracket weight to the
B's stem · amber-brackets-ink-B-on-navy is primary, navy-`[B]`-on-amber is the
avatar · thicken the brackets at small sizes · give the mark its full clear space.

**Don't** — round the brackets or use a circular avatar frame · fill a gold B on
a solid disc (the Bitcoin read) · add a second accent color or a gradient ·
tint the mark red or blue (those are data encodings only) · set the B in a
system/generic sans-serif.

## Where these assets are used in the repo today

| Asset | Used at |
|---|---|
| `avatar.svg` (rasterized to PNG) | GitHub account avatar for `beholden-vote` and the repo's social-preview image — **uploaded manually**; GitHub has no API for either, see below. |
| `mark-source-tag.svg` | The README hero ([`docs/hero.svg`](hero.svg)) lockup, alongside the wordmark. |
| `social-card.svg` | Template for the site's Open Graph / Twitter-card image (not yet wired into `web/index.html` meta tags — a follow-on). |

### Manually uploading the avatar / social preview

GitHub does not expose an API for either of these — both are web-UI-only:

1. **Account avatar** (shows next to the repo name everywhere): sign in as
   `beholden-vote` → [github.com/settings/profile](https://github.com/settings/profile)
   → upload a rendered PNG of `avatar.svg`.
2. **Repo social preview** (the card shown when the repo link is shared):
   repo → Settings → General → scroll to "Social preview" → upload the same PNG,
   or the wider `social-card.svg` render for a fuller card.

### Supersedes

An earlier ad-hoc mark (a "you are here" map-marker/eye motif, `docs/logo-square.svg`)
was designed before this identity system existed and is **retired** — this
document and `docs/brand/` are the only canonical mark going forward.

---

<p align="center"><sub>Beholden · power, on the public record</sub></p>
