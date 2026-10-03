# Terms of reuse: Sumner County and Hendersonville, TN roster pages

> **DRAFT - not a determination until the owner signs off in the PR.**
> Until then this file records what the two sites publish about reuse, verbatim, and a
> proposed reading. It is the `terms_ref` of the `tn-sumner-county` and `tn-hendersonville`
> roster specs (`pipelines/beholden_etl/sources/tn_local.py`), as DATA-CONTRACTS §8.8 requires.

Read 2026-10-03, by plain GET with the pipeline's own User-Agent. Only the terms, copyright
and robots pages were read; no other page of either site was fetched for this note.

## Sumner County (`sumnercountytn.gov`)

**Roster page used:** `https://sumnercountytn.gov/government/county-commission/`

**Terms page:** `https://sumnercountytn.gov/terms-of-use/` (linked "Terms of Use" from the
site footer). Its full operative text, verbatim:

> Sumner County Government is committed to providing accurate and timely information to the
> county citizens. Sumner County Government maintains this web site in an effort to enhance
> public access to the county. Every effort is made to keep this information current and
> correct; however, Sumner County Government cannot guarantee the accuracy of this
> information. Information provided on this web site should not be used as a substitute for
> legal, business, tax or other professional advice. The reader should contact appropriate
> regulating agencies to determine accuracy or suitability of the data for a particular use.
> Sumner County Government assumes no liability whatsoever for any losses that could occur
> from the use, misuse, or inability to use this web site or the materials or information
> contained on this web site.
>
> This site includes links to websites provided by outside government and private sources.
> While every effort is made to assure that these links are accurate and active, and that
> the information contained on those sites is appropriate, each of these sites is
> independently operated. Questions and comments about these links should be addressed to
> the webmaster at webmaster@sumnercountytn.gov.
>
> Sumner County Government assumes no liability for improper or incorrect use of information
> contained on its web site. All materials appearing herein are transmitted "as is" without
> warranty of any kind and subject to the terms on this disclaimer.

No copyright notice, licence or permission requirement appears on the terms page or the roster page.

**robots.txt**, verbatim:

```
User-agent: *
Disallow:
```

(plus a `Sitemap:` line). Nothing is disallowed.

## Hendersonville (`www.hvilletn.org`)

**Roster page used:** `https://www.hvilletn.org/409/Board-of-Mayor-Aldermen`

**Copyright page:** `https://www.hvilletn.org/copyright` (linked "Copyright Notices" from the
footer). Its full operative text, verbatim:

> All content © 2006-2026 Hendersonville, TN and its representatives. All rights reserved.

(The same page also carries the hosting vendor's notice for its content-management software:
"© 1997-2026 CivicPlus. All rights reserved.") No terms-of-use page is linked. The footer
also links a privacy policy, which covers visitors' data, not reuse, and was not relied on.

**robots.txt** (abridged to the rules that apply to a generic agent): `User-agent: *`
disallows `/activedit`, `/admin`, `/common/admin/`, `/OJA`, `/support`, `/Search*`,
`/CurrentEvents*`, `/Map*`, `/RSS.aspx`. `/409/…` is not disallowed. Baiduspider and Yandex
are disallowed everywhere, and Siteimprove agents get `Crawl-delay: 20`. None of this applies to us.

## What we take from each page

Facts only, never expression: each official's name, office and seat (district or ward),
the official contact address or phone published for the office, the URL of the official's
own page, and the URL of the photo the government itself hosts. The photo is **linked**
(`photo_url` points at the government's server); it is not copied or re-hosted. One fetch
of each page per refresh (SLA 7 days), and the raw page is kept in our lake for reproducibility.

## Proposed reading (for the owner to accept or reject)

1. **Sumner County:** the terms are a disclaimer of accuracy and liability. They place no
   restriction on reuse and require no permission. Reuse of the roster facts is compatible,
   and the "as is" / accuracy caveat is already how a grade-B web roster is presented.
2. **Hendersonville:** a blanket "All rights reserved" covers the site's *content*, meaning its
   text, design and images. Who holds which public office, and the official contact details
   the city publishes for that office, are facts, and facts are not copyrightable expression
   (*Feist v. Rural*, 499 U.S. 340 (1991)). We copy no text beyond names and titles, and we
   link the photo rather than copying it. Proposed: compatible for the fact set above, with
   the photo only ever linked, never re-hosted.
3. **Re-examine** if either site adds a terms page that restricts automated access or reuse,
   if robots.txt starts to disallow the roster path, or if we ever want to copy photos or
   text rather than link them.

## Sign-off

- [ ] Owner determination recorded (name the decision, date it, and remove the DRAFT banner).
