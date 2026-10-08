# WO-23b — Votes you can drill into

**Lane F · prereq: WO-35 (merged), WO-23a (merged) · read `AGENTS.md`,
`docs/workplan/README.md`, `web/DESIGN.md` (Rule 0 outranks everything in it), and
`docs/DATA-CONTRACTS.md` §8.3 and §8.6 first. §8.3 is normative for this work order.**

## Why this exists

A dossier shows ten "key votes" and nothing else. WO-23a published the full record — every
roll call a member was eligible for, one object per roll call, one per bill with cosponsors —
and nothing reads it. This work order is the reader's way in: from a person to their whole
record, from a vote to the bill, from a bill to **how their own representatives voted**.

## Objective

1. **A person's full record.** In the dossier's record tab, load `/votes/{person_id}.json` and
   list every vote newest first, with filters: by topic (`policy_area`), "voted against own
   party", and result. Filters combine; the count of matches is shown; the summary line uses
   the file's own `summary` and never recomputes it.
2. **Roll-call page** (`#/v/{roll_call_id}`): question, description, result, official tally,
   the **tally by party** (`by_party`, in the file's order — never sorted by size), the bill
   link, and the positions list. Say what `positions_cover` says: the list covers current
   members only and does not sum to the tally.
3. **Bill page** (`#/b/{bill_id}`): title, number, status, sponsor, cosponsor totals by party,
   members, roll calls, link out to congress.gov.
4. **How your representatives voted.** On a bill and on a roll call, a block listing the
   reader's representatives (from the place view's current stack, via the existing ballot
   lookup) and their position on that vote. With no place chosen it says so and offers the two
   ways to choose one. A representative with no recorded position says so; nothing is inferred.

## Files

**OWNED** — new `web/src/ui/votes/` · new `web/src/lib/votes.ts` (loaders, cached like
`loadDossier`)

**SHARED — marked insertion points only** — `web/src/ui/nav/registry.ts` (**two entries, `bill`
and `vote`, exactly as that file's header describes**) · `web/src/types.ts` (append the §8.3
types under a `// WO-23b` banner) · `web/src/ui/DossierView.tsx` (`RecordTab` only: mount the
new record list) · `web/src/styles.css` (append your block) · `web/src/strings.ts` (additions)

Do **not** touch `App.tsx`, `router.ts` or anything under `ui/nav/` other than the registry —
the shell already parses, pushes history for, labels and focuses these routes. Link to a
record with a plain `<a href={billHash(id)}>`. A view renders an `<h2>` and calls `onTitle`.

## Constraints

- **Build against `web/fixtures/`**, not the network (see its README). The fixtures follow
  §8.3 exactly. Live bill pages only exist once the first nightly after the bill fetch has run
  (`bills/index.json` is empty until then): handle an absent bill with a plain "this bill's
  page is not published yet — read it on congress.gov" and a link, never a blank view.
- **Rule 0 and symmetry.** Party hues are data; parties appear in alphabetical order by code
  everywhere; no sentence differs by party. Ordering of members: family name, as the file has it.
- **Accessibility is part of the work.** Filters are labelled form controls with a live count;
  tables have headers; a position is never conveyed by colour alone.
- **Cost.** One object per person-record load; roll-call and bill objects load on open only.
  Never fetch a list of them. Respect the `Disallow` in robots.txt by not adding crawlable links
  that enumerate them.
- **Honest absence.** `bill_id` null → show the question and no bill link. Dates render as
  calendar dates (the source has no time of day).

## Acceptance

1. `cd web && npm run build` clean; the pipeline gates unaffected.
2. Against fixtures at 1280px and 390px: record list filters work and combine; a vote opens its
   roll-call page; the page opens the bill; Back ×N returns through each altitude; Escape steps
   up one; the breadcrumb reads correctly after a cold load of `#/v/…`.
3. Keyboard-only pass over a filter, a roll-call page and a bill page.
4. Live, once the bill artifacts exist: one member's record's count equals their file's
   `summary.total`; one roll call's tally matches the House Clerk's page.

## Out of scope

Per-state or local votes (the same views, later) · the stance profile and charts (WO-38) ·
compare view (`#/c/`) · editing the shell · new pipeline output.
