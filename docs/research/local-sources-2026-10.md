# A. Source terms research — Beholden (beholden.vote)

Research date: 2026-10-03. Method: pages read as raw text via Python urllib (one request per page, no crawling). Quotes are verbatim from the page text as fetched; "terms not read" means the page could not be retrieved or was not found, and NO determination is inferred from memory.

Two determinations per source:
- (1) FREE REPUBLISH — may facts from it be republished on a free public website with attribution?
- (2) PAID DATASET — may those facts be included in a compiled dataset that is sold?

Status log (appended as sources complete): sections 1-7 read 2026-10-03; section 8 (MEDSL) and the summary table added later the same day.

---

## 1. Open States / Plural Policy (openstates.org -> open.pluralpolicy.com)

Read 2026-10-03. `https://openstates.org/downloads/` redirects to `https://open.pluralpolicy.com/data/`.

### 1a. Bulk data page: licence sentence (verbatim)
Source: https://open.pluralpolicy.com/data/ (read 2026-10-03)

> "Open States makes almost all of our data available in bulk. Unless otherwise noted data is provided under a public domain dedication but attribution is greatly appreciated and very helpful."

That one sentence is the ONLY licence statement on the bulk page; it is page-wide and covers every section (legislator data, bill & vote CSV, bill & vote JSON, geographic data, PostgreSQL dump). No section on the page carries an "otherwise noted" exception (I checked each section's Source / Documentation / Update Schedule text). The PostgreSQL section's source line reads only: "Combined people, bill, vote, etc. data, sources vary but are recorded in database." (the dump mixes upstream sources; see caveat in determinations). Geographic data: "Geographic boundary data is sourced primarily from the Census".

### 1a. Per-product facts (all from https://open.pluralpolicy.com/data/ unless stated)
- **Bill & Vote CSV (per session)**: "CSV files representing all bills & votes, available on a per-session basis." Stated update schedule: "This data will update monthly, get in touch if you need specific data." Docs: "Documentation TBD". Observed freshness on https://open.pluralpolicy.com/data/session-csv/ (read same day): Tennessee 114th Regular Session (2025-2026) "updated 2026-09-29"; Tennessee 114th First Extraordinary Session (January 2025) "updated 2026-07-27"; Alaska 34th Legislature "updated 2026-10-02"; Arizona 57th Second Regular "updated 2026-09-08". So the stated cadence is monthly, but active sessions were stamped within days of today.
- **Bill & Vote JSON (per session, includes full bill text)**: same "update monthly" sentence. Observed on https://open.pluralpolicy.com/data/session-json/ : Alabama 2026 Regular Session "updated 2026-10-03". Known defect (GitHub issue #1419, opened 2026-09-20, https://github.com/openstates/issues/issues/1419): the JSON export omits each vote's `id` (CSV and API v3 have it), so prefer CSV for votes.
- **Keyless? NO for session CSV/JSON.** Both session pages show "Please log in to access download links." and every download link (e.g. all Tennessee sessions) points at `/accounts/login/?next=/data/session-csv/` when logged out. A free account is needed to get the links. I did NOT create an account (not something I may do; you would need to). Account sign-up is the only gate I saw; I saw no separate click-through licence beyond the Terms of Use below.
- **URL pattern for one state's session archive: NOT readable logged-out.** From GitHub issue #1419 the archive file names look like `AZ_57th-2nd-regular_csv_4i6qmMeOcBg7IK8YPvNNtZ.zip` and `AZ_57th-2nd-regular_json_1CEE4VL4FsezvzDsKmbug3.zip`, i.e. a random token suffix, so the URL is NOT guessable. Get it from the logged-in page, or from the API v3 `LegislativeSession.downloads` field (added 2021.11.12 per https://docs.openstates.org/api-v3/changelog/ ; field present in the schema at https://v3.openstates.org/openapi.json). Zip contents per the issue and https://openstates.github.io/pyopenstates/downloads/ : `<ST>_<session>_bills.csv`, `<ST>_<session>_votes.csv`, plus actions, sponsorships, versions, version links, vote people/counts/sources, organizations, people.
- **Legislator CSV: KEYLESS, "nightly" (stated).** https://open.pluralpolicy.com/data/legislator-csv/ : "CSV files are published nightly, and available at https://data.openstates.org/people/current/ [ABBR] .csv, where [ABBR] is a state's postal code." Verified by HTTP HEAD (no file body downloaded): `https://data.openstates.org/people/current/tn.csv` -> 200, text/csv, 113,500 bytes, Last-Modified Thu, 24 Sep 2026 16:37:31 GMT (9 days old despite "nightly"). UPPERCASE `TN.csv` -> 403 Forbidden, so use LOWERCASE `tn.csv`. Columns listed on the page: id (ocd-person), name, current_party, current_district, current_chamber, given_name, family_name, gender, biography, birth_date, death_date, image, email, links, sources, capitol_address/voice/fax, district_address/voice/fax, twitter, youtube, instagram, facebook.
- **PostgreSQL dump: KEYLESS.** Links on the page: `https://data.openstates.org/postgres/monthly/2026-10-public.pgdump` and `https://data.openstates.org/postgres/schema/2026-10-schema.pgdump`; pattern "https://data.openstates.org/postgres/monthly/YYYY-MM-public.pgdump". HEAD (no body downloaded) on the October file -> 200, binary/octet-stream, 10,768,629,207 bytes (~10.8 GB), Last-Modified Thu, 01 Oct 2026 01:54:34 GMT. Page text: "Nearly-complete database dump of Open States' public data." Update: "This data updates regularly throughout the month, typically no more than a day or two behind what is online. At the beginning of the month, the auto-generated link above may point to files that don't exist yet." Support: "Currently only supported in the context of restoring a database for development. No guarantees are made about internal schema changes or availability." Consequence: keyless route to ALL state votes, but 10.8 GB and unsupported.
- Geographic boundaries: static JSON, pattern `https://data.openstates.org/boundaries/2018/ocd-division/country:us/state:ks/sldl:1.json` (page https://open.pluralpolicy.com/data/geo/); "The latest iteration of this data was created in November 2018."

### 1a'. Terms of Use & Privacy (governs API, bulk downloads and website)
Source: https://open.pluralpolicy.com/tos/ ("These terms effective September 15, 2021.") read 2026-10-03.

> "Open States offers data via an API, bulk downloads, and the website OpenStates.org (collectively, the 'Services')."
> Scope: "All of the content, documentation, and related materials made available to you by Open States is subject to these terms unless otherwise noted."
> Attribution: "No attribution is required for using data obtained via Open States. We make no copyright claim over any of the data we collect & publish. Of course, attribution is always appreciated but no affiliation or endorsement may be implied on your derivative product."
> Right to Limit: "Use of the Services may be subject to certain limitations on access as set forth within this Agreement or otherwise noted. If we reasonably believe you have attempted to exceed or circumvent these limits, your ability to use the service may be permanently or temporarily blocked."
> General Representations: "You hereby warrant that (1) your use of the Services will be in strict accordance with this Agreement and all applicable laws and regulations, and (2) your use of the Services will not infringe or misappropriate the intellectual property rights of any third party."
> Disclaimer: Open States provides the Services "as-is" and "as-available"; no warranty the Services "will be error free". (Source page uses curly quotes that my fetch rendered as replacement characters; wording otherwise as shown.)

No NonCommercial, ShareAlike, no-resale or no-redistribution clause appears anywhere on the Terms page. I read the full page text, including the Privacy Policy.

### 1b. `openstates/people` repository
Source: https://raw.githubusercontent.com/openstates/people/main/README.md (read 2026-10-03):

> "Also, please note that this portion of the project is in the public domain in the United States with all copyright waived via a CC0 dedication.  By contributing you agree to waive all copyright claims."

Source: https://raw.githubusercontent.com/openstates/people/main/LICENSE : the file is the CC0 1.0 Universal legal code ("Creative Commons Legal Code / CC0 1.0 Universal"). Its statement of purpose says works are released so others can reuse them "as freely as possible in any form whatsoever and for any purposes, including without limitation commercial purposes."

Repo scope (README): "YAML files with official information on state legislators, governors, and some municipal leaders". Directories: legislature, executive, "municipalities - people currently serving in local government (e.g. mayors)", retired, committees. "the data/us directory is also directly ported from the congress-legislators repo". The data includes contact fields (email, phones, addresses): official public contact data, but keep to official/public roles.

### 1c. API v3
Source: https://docs.openstates.org/api-v3/ (read 2026-10-03):
> "The root URL for the API is https://v3.openstates.org/ . API keys are required. You can register for an API key and once activated, you'll pass your API key via the X-API-KEY header or ?apikey query parameter."
- No separate API licence/terms page found: the API is covered by the single Terms of Use above ("Open States offers data via an API ...").
- Format: JSON over GET; endpoints /jurisdictions, /people, /people.geo, /bills (include=votes), /committees, /events. OpenAPI spec https://v3.openstates.org/openapi.json (version "2021.11.12"; its text says the people data is "limited to state legislators and US Congress.  Governors & mayors are not included.").
- **Rate limits: NOT CONFIRMED from a readable page.** The only first-party statement I could read is the 2020 beta post https://blog.openstates.org/open-states-api-v3-beta/ : "API limits are not yet determined or enforced on v3." (stale). A web-search summary claimed a default of 10 requests/minute and 500/day (and a "bronze" tier of 40/min, 5,000/day) citing github.com/openstates/issues/discussions/205, but that page returned HTTP 404 when I fetched it, so treat those numbers as UNVERIFIED. The key dashboard is behind login (https://open.pluralpolicy.com/accounts/profile/ redirects to login).

### 1 DETERMINATIONS
- **(1) Free public site with attribution: YES.** Bulk page = "public domain dedication"; Terms = "No attribution is required ... We make no copyright claim over any of the data"; people repo = CC0. Attribution is optional, but "no affiliation or endorsement may be implied".
- **(2) Paid compiled dataset: YES on Open States' own claims.** Public-domain dedication / CC0, and no NonCommercial/ShareAlike/resale clause anywhere in the Terms. Residual caveats (none is an NC clause): (i) Open States disclaims only ITS OWN copyright; the dump's source line says "sources vary" and the Terms make YOU warrant you won't "infringe or misappropriate the intellectual property rights of any third party". The 50 upstream state-legislature sites' terms (and any state copyright claims on bill text/annotations) were NOT read, so FULL BILL TEXT is undetermined; limit the paid product to facts (names, districts, parties, vote positions, bill IDs/titles/dates). (ii) "Right to Limit" lets them block you if you circumvent API limits. (iii) The PostgreSQL dump is explicitly unsupported and may change or vanish. (iv) Do not imply Open States endorsement.
- Attribution wording: none required. Suggested courtesy line (my wording, not theirs): "Includes data from Open States (open.pluralpolicy.com)."
- Bulk instead of rate-limited API: YES for people (keyless per-state CSV, lowercase `tn.csv`) and for votes via the keyless monthly PostgreSQL dump (10.8 GB, unsupported). Per-session bill+vote CSV/JSON zips need a free login to see their (tokenised) links.
- Confidence: **read in full** (bulk page, TOS, people README+LICENSE, API v3 docs page); API rate limits **not read**; upstream state-site terms **not read**.

---

## 2. UT County Technical Assistance Service (CTAS) county officials directory (ctas.tennessee.edu)

Read 2026-10-03 (pages: /counties, /county/sumner, /official/billy-barnfield, /county-commissioners, /county-executives-and-mayors, /privacy-statement, /robots.txt; CSV header only, via a 900-byte range request; nothing saved). `/directory` is a page of county links (each `/directory/<County>`, which mirrors the `/county/<slug>` pages); the site's own list page is `/counties`.

### 2a. What the directory itself says about the data
Source: https://www.ctas.tennessee.edu/counties (read 2026-10-03):

> "Welcome to the CTAS Directory of Tennessee counties. Click on a county name to see detailed county information and a listing of elected or appointed county officials and select county staff. This directory is maintained as an information resource. We rely on county officials and staff to report updates to their information, therefore accuracy cannot be guaranteed."

### 2b. Terms / copyright statements found
Source: https://www.ctas.tennessee.edu/privacy-statement ("Privacy Statement", read 2026-10-03), section "Intellectual property", the ONLY copyright/reuse text I could read on the site:

> "The content of ctas.tennessee.edu web pages is copyrighted and may contain some third party graphics/images that are used with the copyright holder's consent. If you wish to use any of this content, you must obtain permission from the copyright holder before reproducing or otherwise using those graphics/images."

Same page, "External links": "CTAS makes no representation concerning their content and is not responsible for their content."

- **The footer "Disclaimer" page could NOT be read.** https://www.ctas.tennessee.edu/disclaimer (footer link) returns HTTP 403 for every variant I tried; the body is a Drupal page reading "Access denied / You are not authorized to access this page." Terms of that page: **terms not read.** (The "Indicia" and "Accessibility" footer pages were not read; not relevant to reuse.)
- No page I read carries any open licence (no CC, no public-domain statement, no "you may reuse" grant). The `/county/...` and `/official/...` pages carry no copyright line other than the Privacy-page sentence above.
- UT System policy that governs ownership: https://policy.tennessee.edu/policy/bt0024-statement-of-policy-on-patents-copyrights-and-other-intellectual-property/ (page title shows "BT0011 - Statement of Policy on Patents, Copyrights, and Other Intellectual Property"), read 2026-10-03:
  > "Extension and Public Service Agencies – The University retains all rights to copyrightable materials developed by staff of its extension and public service agencies as a part of their routine employment duties."
  CTAS is part of the UT Institute for Public Service, so CTAS-authored material is University-owned. I found no UT System page granting a general reuse licence for CTAS web content (https://tennessee.edu/about/divisions/general-counsel/copyright/ is general copyright education, "NOT legal advice", not a reuse licence).
- robots.txt (https://www.ctas.tennessee.edu/robots.txt) is standard Drupal; for `User-agent: *` it does NOT disallow `/county/`, `/official/`, `/county-commissioners` or `/csv-*`. It disallows `/search/`, `/printable/`, `/node/*/printable/pdf`, `/update_officials_data/`, `/search_ctas`, and blocks SemrushBot/AhrefsBot/PetalBot/Zoombot entirely. No Crawl-delay.
- Public-records note (privacy page): information voluntarily submitted to CTAS "is subject to the disclosure pursuant to the requirements of the Tennessee Public Records Act." (about forms submitted to CTAS, not about the directory).

### 2c. Structure of the data
**Is it structured? YES, partly, and there is an export.** Drupal 10-style site; data is rendered by Drupal Views tables (class names `views-field-...`), plus a built-in CSV export (Drupal `views_data_export`). No JSON endpoint or API found.

- **/counties**: one `<table>` of 95 county rows. Cell classes: `td.views-field-title.views-align-left > a[href="/county/<slug>"]` (county), `td.views-field-field-zip` (street, city, ZIP), `td.views-field-field-website` (`a` county website + `<br>` + phone). Example row: Sumner -> `/county/sumner`, 355 Belvedere Drive, Gallatin 37066, `https://sumnercountytn.gov/`, (615) 452-3604.
- **/county/sumner** (read in full; read for Sumner only; the slug pattern for all 95 counties is lowercase and hyphenated per the `/counties` links, e.g. `van-buren`):
  - Header block: name, address, phone, website; "COUNTY DETAILS" (Year Originated 1786; County Road Miles; Number of Parcels; Incorporated Cities or Towns with populations, e.g. "Hendersonville (51372)"), "POPULATION" (2020/2010), "COUNTY STRUCTURE" (County Structure: Traditional; Development District; Judicial District: 18), "LEGAL AUTHORITY" (fiscal/budget/purchasing laws, private acts).
  - Two Bootstrap tabs (`ul.nav-tabs`): **"County Officials"** and **"Legislative Body"**. Tab pane ids are auto-generated (e.g. `tab-wr4krh-1`, `tab-wr4krh-2`), so select by tab order/label, not by id.
  - Each tab pane contains `table.cols-0 > tbody > tr` with three `td`: `td.views-field-title` = office title (e.g. "County Executive"), `td.views-field-field-web-display-name > a[href="/official/<slug>"]` = person name, `td.views-field-title-1` = phone, `<br>`, `a[href^="mailto:"]` (phone often absent).
  - **County Officials tab (Sumner, 2026-10-03):** County Executive; Hwy Chief Admin Off; Administrator of Elections; Assessor Of Property; Circuit Court Clerk; Clerk & Master; County Attorney; County Clerk; Director of Schools; Executive Director - Sumner County Resource Authority; Finance/Budget Director; General Sessions Court Judge (x4); Register of Deeds; Sheriff; Solid Waste Director; Trustee. Entries carry name + (usually) phone + (usually) email. NO party, NO term start/end dates, NO district numbers.
  - **Legislative Body tab:** `<b>Number of Commissioners: </b>24`, `<b>Number of Commission Districts: </b>24`, `<b>County Legislative Meeting Information: </b>7:00 p.m. - 3rd Monday of each month`, then 24 rows of title "County Commissioner" + name + email only (alphabetical by surname; no phone). **A commissioner's DISTRICT NUMBER DOES NOT APPEAR anywhere** on the county page (only the count of districts), nor on the person page, nor in the CSV header. So CTAS cannot supply a commissioner-to-district mapping. (Sumner shows 24 names = 24 districts, one per district, but nothing says which.)
  - Footer of the page: CTAS consultant names, side menu to office-type lists.
- **/official/<slug>** (read for one Sumner commissioner): fields shown: name, title ("County Commissioner"), county, a mailing street address and city/ZIP (for commissioners this can be a residential-style address; treat as personal data), Email, "CTAS Consultant" and consultant email, and a "REQUEST UPDATE" button. No district, party or term dates.
- **Statewide lists by office** (each with the same table markup, one row per official): `/county-commissioners` (about 1,500 rows; cells `td.views-field-field-county`, `td.views-field-field-web-display-name`, `td.views-field-field-zip-preferred` = street/city/ZIP + mailto), `/county-executives-and-mayors` (95 rows incl. phone+email), `/sheriffs`, `/trustees`, `/county-clerks`, `/registers-of-deeds`, `/clerks-of-court`, `/assessors-property`, `/county-attorneys`, `/finance-directors`, `/highway-officials` (all linked from the side menu). Also "Judicial Officials", "State Legislators", "Meeting Times", "Population", "Websites" lists and "Printable Directories" (`/countydirprint`).
- **CSV export EXISTS:** `https://www.ctas.tennessee.edu/csv-county-commissioners` (link is the CSV icon at the top of `/county-commissioners`) -> HTTP 200, `text/csv; charset=UTF-8`, ~164,024 bytes, `Content-Disposition: attachment; filename="ctas_county_commissioners_10/03/2026.csv"` (date-stamped today, i.e. generated live). Header row exactly: `County,Name,Title,Address,City,"Zip Code",Fax,"Email Address"`. Likewise `/csv-county-executives-and-mayors`. Both are keyless. (I read only the header line; I did not save or parse the file.)
- Update mechanism: "We rely on county officials and staff to report updates"; per-person "REQUEST UPDATE" form. No "last updated" date shown on county pages and no term-end dates, so staleness after elections cannot be detected from the data; the CSV filename date is just the export date.

### 2 DETERMINATIONS
- **(1) Free public site with attribution: UNDETERMINED.** The site states its content "is copyrighted" and that to use "any of this content, you must obtain permission from the copyright holder" and grants no licence; the Disclaimer page that might say more is access-denied (terms not read). Factual elements (a person's name, office, county, public email) are generally not copyrightable in the US, but that is a legal judgment I will not make for you, and the compiled directory and CSV are the University's work (BT0024). Do not treat it as cleared.
- **(2) Paid compiled dataset: UNDETERMINED**, same reason, and it is the riskier use (resale of a University-owned compilation without a licence). No NonCommercial clause was found, but there is no grant at all.
- Attribution wording: none specified.
- Rate limits / API key: none stated; no key; normal HTML + CSV over HTTPS; robots.txt allows these paths.
- Practical routes: (a) ask CTAS in writing for permission (page names "Liz Gossett, CTAS Marketing Director" for "Questions about county information?"; phone 615.532.3555) and save the reply; or (b) source officials from primary county/election-commission pages instead. CTAS cannot give commissioner districts either way.
- Confidence: **read partially** (directory pages + Privacy statement read in full; footer Disclaimer **terms not read**, HTTP 403).

---

## 3. UT Municipal Technical Advisory Service (MTAS) municipal officials directory (mtas.tennessee.edu)

Read 2026-10-03 (pages: /directories/cities, /directories/municipal-staff-and-officials, /directories/cities/hendersonville, /disclaimer, /privacy-statement, /robots.txt, the site's JSON search endpoint for one city, and the first line only of two CSV exports; nothing saved).

**Yes, MTAS has a statewide municipal directory.** "Directories" menu has: "Cities & Towns" (https://www.mtas.tennessee.edu/directories/cities, 345 municipalities in the city selector), "Municipal Staff & Officials" (https://www.mtas.tennessee.edu/directories/municipal-staff-and-officials), "MTAS Staff & Consultants", "Office Locations".

### 3a. What the directory itself says about the data
Source: https://www.mtas.tennessee.edu/directories/cities and .../municipal-staff-and-officials (same notice on both, read 2026-10-03):

> "This information is provided to MTAS by each Tennessee municipality and is intended for general informational purposes only. MTAS does not independently verify the information contained herein. While this agency makes every effort to provide complete and accurate information, the agency does not guarantee the accuracy, completeness, or timeliness of this information. Information contained herein should be verified prior to use."

City page intro (https://www.mtas.tennessee.edu/directories/cities/hendersonville): "The following information is provided to MTAS by each municipality and is intended for general informational purposes only." Official-list intro: "Find contact information for elected and appointed officials of Tennessee cities and towns. This listing also provides information on MTAS consultants assigned to each municipality."

### 3b. Terms / copyright statements found
Source: https://www.mtas.tennessee.edu/privacy-statement ("Privacy Statement", read 2026-10-03), section "Intellectual property" (identical wording to CTAS with the site name swapped):

> "The content of mtas.tennessee.edu web pages is copyrighted and may contain some third party graphics/images that are used with the copyright holder's consent. If you wish to use any of this content, you must obtain permission from the copyright holder before reproducing or otherwise using those graphics/images."

Source: https://www.mtas.tennessee.edu/disclaimer (read in full, 2026-10-03; unlike the CTAS Disclaimer this one loads). Its two operative paragraphs:

> "Links to commercial sites are provided for information and convenience only. Inclusion of sites does not imply University of Tennessee approval of their product or service to the exclusion of others that may be similar, nor does it guarantee or warrant the standard of the products or service offered."
> "Information written by MTAS staff was created based upon the law at the time and/or a specific sets of facts. The laws referenced in those writings may have changed and/or the technical advice provided may not be applicable to your city or circumstances. Always consult with your city attorney."

Neither the Disclaimer nor the Privacy page grants any licence or says anything about reuse, republication or bulk use of the directory. Ownership of staff-created material: same UT System policy as in section 2 (BT0024: "The University retains all rights to copyrightable materials developed by staff of its extension and public service agencies as a part of their routine employment duties."). The listings themselves are said to be supplied by the municipalities. robots.txt (https://www.mtas.tennessee.edu/robots.txt) has `User-agent: *` and no Disallow rule for `/directories`, `/rocket_search` or `/mtas_api`.

### 3c. Structure of the data (much richer than CTAS for machine access)
**Is it structured? YES, and there are keyless machine endpoints**, found in the page source (not documented as an API anywhere I read):
- **CSV exports (keyless, generated live, date-stamped today):**
  - `https://www.mtas.tennessee.edu/mtas_api/v1/csv/official` -> `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="MTAS_Official_2026-10-03.csv"`. Header row exactly: `Organization,Salutation,First,Middle,Last,Generational,Credentials,"Preferred Name",Title,Phone,"Phone Extension",Fax,Email,Address,City,State,Zip,"Billing Address","Billing Zip"`. (Statewide officials/staff; "Organization" is the municipality. Includes Billing Address columns: do not republish those.)
  - `https://www.mtas.tennessee.edu/mtas_api/v1/csv/city` -> `MTAS_City_2026-10-03.csv`, header `City,Address,Zip,"Office Hours",Population,County,"Grand Division"`.
  - Matching PDF exports at `/mtas_api/v1/pdf/official` and `/mtas_api/v1/pdf/city` (links "Download PDF"/"Download CSV" on the list pages).
- **JSON search endpoints used by the list pages:** `https://www.mtas.tennessee.edu/rocket_search/city` and `/rocket_search/official` (GET, `Content-Type: application/json`; fields `PageIndex`, `PageSize` (12), `TotalCount`, `Results` (an HTML fragment of cards), `DownloadResults`). Example I called: `/rocket_search/city?cityname=736` (736 = Hendersonville's option value) returned one card: Hendersonville, county Sumner, "Population: 64,266", link `/directories/cities/hendersonville`. City page URL pattern: `/directories/cities/<city-slug>`.
- **City page markup (Hendersonville, read in full):**
  - "Municipal Statistics" key/value table: County Sumner; Municipality City; "Population (Certified by TNECD*)" 2026 Estimated 64,266 and 2010 Census 51,372; **Next Election 11-03-2026**; Grand Division Middle; Time Zone Central; Employees 387; Social Media.
  - "Municipal Data" table (`<th>`/`<td>` rows): Meets "2nd and 4th Tuesday at 7:00 PM at City Hall"; Office Hours; Charter "General Law Mayor-Aldermanic (TCA 6-1-101 et seq.)"; Incorporation Act; Incorporation Date 12/01/1901; Links -> "Link To Districts" (which points to https://www.capitol.tn.gov/legislators/ i.e. STATE legislative districts, not city wards).
  - "Municipal Staff and Elected Officials": tabs `#profile-listing--governance`, `--staff`, `--legal`, `--consultants` (ids are stable text, not generated). Inside each, `div.profile-listing__grid > div.card-profile` with `h3.card-profile__name` and `p.card-profile__position` (text like "Mayor, Hendersonville" / "Alderman, Hendersonville") plus `a.card-profile__link[href="#profile-N"]`. Contact details live in `<dialog id="profile-N" class="modal-profile">`: `h2.modal-profile__name`, `p.modal-profile__position`, `li.modal-profile__item--phone > a[href^="tel:"]`, `li.modal-profile__item--email > a[href^="mailto:"]`, `p.modal-profile__address` (street + city/state/ZIP), then a "Suggest an Update?" form. 41 profile cards on the page.
  - **Governance tab (Hendersonville):** 1 Mayor + 12 "Alderman". Staff tab: departmental directors etc. (Finance Director, Police Chief, Fire Chief, City Recorder, City Court Clerk, City Judge...). Legal tab: City Attorney. Consultants tab: 9 MTAS consultants.
  - **Offices covered:** elected governing body, appointed staff and department heads, plus the MTAS consultants assigned to the city. Phone and email for elected members are the city-hall main number and a city e-mail address; address is the city hall address.
  - **NOT present:** party, term start/end dates, ward/district numbers for aldermen (only a "Next Election" date for the city as a whole), vice-mayor flag. Titles are free text ("Alderman").
- Update mechanism: per-person "Suggest an Update?" form; no per-record last-updated date.

### 3 DETERMINATIONS
- **(1) Free public site with attribution: UNDETERMINED.** The only reuse-relevant sentence is the same "content ... is copyrighted ... you must obtain permission from the copyright holder" notice; the Disclaimer (read) grants nothing. The listings are submitted by the municipalities, but MTAS asserts copyright over its pages and offers no licence. Facts like a mayor's name and city-hall contact are likely thin-copyright material, but that is a legal call I will not make for you.
- **(2) Paid compiled dataset: UNDETERMINED**, same reason. No NonCommercial wording found; no grant at all either.
- Attribution wording: none specified.
- Rate limits / API key: none stated; the CSV and rocket_search endpoints are keyless GETs and appear intended for the page's own use (undocumented, may change).
- Practical routes: request written permission from MTAS (contact on the Disclaimer/Privacy pages: Knoxville office 865-974-0411, mtas@tennessee.edu) and keep the reply; or use each city's own official site / the Tennessee Secretary of State and county election commissions for primary data. The MTAS directory cannot supply ward/district or term dates in any case.
- Confidence: **read in full** (directory notice, Disclaimer, Privacy statement, Hendersonville page, CSV headers); I found no other terms/copyright/policy link in the site navigation (checked link text on the Disclaimer page: only Privacy and Accessibility, plus the Disclaimer itself); Accessibility not read.

---

## 4. Legistar Web API (webapi.legistar.com, Granicus)

Read 2026-10-03 (pages: https://webapi.legistar.com/ , /Home/Examples , /Help (index); https://granicus.com/trust-center/terms-of-use/ ; https://granicus.com/legal-licensing/ ; Granicus Subscription and Services Agreement US/Canada, July 2024 PDF, read as text and not kept).

### 4a. API terms of use: NONE PUBLISHED
- https://webapi.legistar.com/ (home) reads in full: "Legistar Web API exposes Legistar data to the web directly over HTTPS." Footer "© 2026 - Granicus Version: 26.4.2.0". It has no terms, licence, copyright-grant, rate-limit or attribution text; the only nav links are Home, API (Help), Examples. A search of the full Help index page (https://webapi.legistar.com/Help, ~42 KB of HTML) for "terms", "licence", "copyright", "rate limit", "throttle", "attribution" found nothing. **No API terms of use exist on the API site.**

### 4b. What the docs say about tokens and limits
Source: https://webapi.legistar.com/Home/Examples (read 2026-10-03):
> "To use the URLs below, replace {Client} with your client name. Some clients require use of an API Token."
> "Some clients require use of API tokens for access. If the read-only operations above give an unauthorized response, please refer to that client for their token policy."
> "If you have a token, it can be provided as a URL parameter to the https endpoint of this API. For example: https://webapi.legistar.com/v1/{Client}/matters?token=verylongbase64token"
> "Note that queries replies are limited to 1000 responses."
> "Items returned to GET requests are limited to those items marked as public and available for view on InSite."
> "Limiting queries by paging and filtering will reduce both the load on the server and the time needed to return the requested data."
> "Fields in the API do not reflect any label customization done for your specific site."
- So token policy is **per client government** (the city/county that licenses Legistar), not set by Granicus; there is no Granicus-wide key registration and no published rate limit. Paging via OData (`$top`, `$skip`, `$filter`); `http` and `https` both work for GET.
- Live check (single request): `GET https://webapi.legistar.com/v1/nashville/bodies?$top=1` -> HTTP 200 `application/json` with no token and no rate-limit headers, so at least that client is keyless today. Other clients may return unauthorized.
- Data format: JSON (OData-style) with GET; the Help index also lists POST/PUT/DELETE (write) methods, which are client-only. Votes: `/matters/{id}/histories` then `/eventitems/{id}/votes` per the Examples page.

### 4c. Who owns the content
- No page on the API site says who owns the data. The relevant Granicus text is the **Subscription and Services Agreement US/Canada (Version July 2024)**, a contract between Granicus and its government "Client" (not a public licence). Source: https://granicus.com/wp-content/uploads/Subscription-and-Services-Agreement-live-July-15-2024-1.pdf (linked from https://granicus.com/legal-licensing/), section 2(e):
  > "Granicus does not own the Content submitted by Client nor is Granicus responsible for any Content used, uploaded or migrated by Client or any third party."
  and the definition: "'Content' means any material or data: (i) displayed or published on Client's website; (ii) provided by Client to Granicus to perform the Services; or (iii) uploaded into Products by Client or on Client's behalf. Content expressly excludes Granicus Data". "Granicus Data" is "data owned, generated or collected by Granicus separately from Content provided by Client, including data generated by use of the Products or personal information related to individuals who use the Products". So meeting/agenda/vote content is the client government's, not Granicus's. Caveat: this is the template posted in July 2024; each client's signed contract may differ, and it creates no rights for third parties/the public.
- Granicus **website** terms (https://granicus.com/trust-center/terms-of-use/, dated "July 20, 2026"), section "Copyright and Use of Material": "All text, including, but not limited to, downloadable forms are copyrighted materials owned by GRANICUS, Inc." and "Use of the information contained on this website is solely intended for individual and private use. You agree not to rent, lease, or sell any or all portions of the material contained on this website ... without the specific written permission of GRANICUS, Inc." These terms govern granicus.com (the marketing/trust pages), NOT the Legistar client data served by the Web API; I found nothing that extends them to the API.
- https://granicus.com/legal-licensing/ lists contracts and product flow-downs; its dropdown includes "Agenda LE (Legistar Agenda Management)" which points only to the Legistar marketing page (https://granicus.com/product/agenda-management-legistar/), not a terms document. The "Meeting Add-Ons" flow-down PDF (Sep 2025) covers only closed-captioning subcontractors. Neither mentions the Web API.
- Each city/county's own website terms or open-records stance (e.g. the client's InSite site and its public-records policy) were NOT read; those are what actually govern reuse of a given jurisdiction's agendas, minutes and votes, and they must be read per jurisdiction before it ships.

### 4 DETERMINATIONS
- **(1) Free public site with attribution: UNDETERMINED at the Granicus level; effectively "no stated restriction", but nothing grants permission.** The API publishes no terms, so nothing forbids or permits republication; ownership of the content sits with each client government (Granicus contract template), and public meeting records of governments are generally public, but the governing terms are per-jurisdiction and unread.
- **(2) Paid compiled dataset: UNDETERMINED**, same reason, per jurisdiction. No NonCommercial clause found because no terms exist.
- Attribution: none specified. Rate limits: none published (1000 rows per query, per Examples); API key: required only if the specific client requires one (client-issued token).
- Practical note: before relying on a jurisdiction, read that client's own website/open-data terms and confirm its API is keyless; consider emailing Granicus (the Examples page says "we'd be happy to help you find the appropriate calls") only for technical questions, not licensing.
- Confidence: **read in full** for the API site (no terms exist there); Granicus contract/ToU **read partially** (Subscription Agreement scanned for ownership clauses only); per-client terms **not read**.

---

## 5. `unitedstates/congress-legislators` (GitHub)

Read 2026-10-03: https://raw.githubusercontent.com/unitedstates/congress-legislators/main/README.md (full) and .../main/LICENSE (CC0 legal code). There is no LICENSE.md/LICENSE.txt (both 404); the file is plain `LICENSE`.

### 5a. Licence statement (verbatim)
Source: README.md, section "Public domain":

> "This project is dedicated to the public domain. As spelled out in CONTRIBUTING:"
> "The project is in the public domain within the United States, and copyright and related rights in the work worldwide are waived through the CC0 1.0 Universal public domain dedication."
> "All contributions to this project will be released under the CC0 dedication. By submitting a pull request, you are agreeing to comply with this waiver of copyright interest."

Source: https://raw.githubusercontent.com/unitedstates/congress-legislators/main/LICENSE : the full "Creative Commons Legal Code / CC0 1.0 Universal" text, whose statement of purpose says the work may be reused "as freely as possible in any form whatsoever and for any purposes, including without limitation commercial purposes." (The README text above is quoted from the README's markdown, with link syntax removed. I did not separately open CONTRIBUTING.md; the README quotes it.)

### 5b. Data, format, freshness (from the same README)
- Content: "Members of the United States Congress (1789-Present), congressional committees (1973-Present), committee membership (current only), and presidents and vice presidents of the United States in YAML, JSON, and CSV format." Files: legislators-current, legislators-historical, legislators-social-media, committees-current, committee-membership-current, committees-historical, legislators-district-offices, executive.
- Per-legislator record: id crosswalks (bioguide = "the best field to use as a primary key", thomas, lis, fec, govtrack, opensecrets, votesmart, icpsr = Voteview ID, cspan, wikipedia, ballotpedia, maplight, house_history, pictorial), name, bio (birthday, gender), and chronological `terms` (type, start, end, state, party, district, url, address, phone, fax, contact_form, office).
- Keyless static downloads on GitHub Pages, e.g. https://unitedstates.github.io/congress-legislators/legislators-current.csv (HEAD: 200, 181,149 bytes, Last-Modified Thu, 24 Sep 2026 10:21:30 GMT) and .../legislators-current.json (1,469,059 bytes, same timestamp); YAML is maintained on the `main` branch, CSV/JSON on `gh-pages`. No API key, no stated rate limit (GitHub Pages / raw.githubusercontent.com normal limits).
- Provenance: "maintained through a combination of manual edits by volunteers ... and automated imports from a variety of sources" including GovTrack.us, the Congressional Biographical Directory (bioguide.congress.gov), "Congressional Committees, Historical Standing Committees data set by Garrison Nelson and Charles Stewart", Martis's atlas "via Rosenthal, Howard L., and Keith T. Poole. United States Congressional Roll Call Voting Records, 1789-1990 (voteview.com)", the Sunlight Labs Congress API, THOMAS, and C-SPAN. The CC0 dedication is the project's own; I did not read the terms of those upstream sources (Nelson/Stewart committee data is the one most likely to carry its own terms; it is only in the committees-historical files, not the legislator files).

### 5 DETERMINATIONS
- **(1) Free public site with attribution: YES.** CC0 public-domain dedication; attribution not required (courteous: "congress-legislators project, unitedstates/congress-legislators on GitHub").
- **(2) Paid compiled dataset: YES.** CC0 expressly allows commercial purposes; no NonCommercial/ShareAlike clause. Caveat: the CC0 covers what the project owns; upstream-source terms (e.g. Nelson/Stewart committee data) were not read, so for the legislator files (names, party, state, district, terms, IDs, official contact) the risk is low, for historical committees treat as undetermined.
- Attribution wording required: none.
- Confidence: **read in full** (README + LICENSE); upstream-source terms **not read**.

---

## 6. Voteview (voteview.com, UCLA)

Read 2026-10-03: https://voteview.com/about (full), https://voteview.com/data (full), https://voteview.com/articles/data_help_members (full), https://voteview.com/articles/data_help_votes (scanned for licence/citation words), https://github.com/voteview/WebVoteView LICENSE + README + views/about.tpl, plus the first line only of the members CSV and its HTTP headers. The site has NO terms-of-use, licence or privacy link in its navigation (links on /about: search/chamber/party/committee/data/about, Colophon, a contact mailto).

### 6a. Terms / citation requirement (verbatim)
Source: https://voteview.com/data (read 2026-10-03):

> "This section contains download links for NOMINATE scores and other data that we make available to the public, in addition to tutorial articles explaining how to generate popular ancillary data from our data exports."
> "Please cite the dataset as: Lewis, Jeffrey B., Keith Poole, Howard Rosenthal, Adam Boche, Aaron Rudkin, and Luke Sonnet (2026). Voteview: Congressional Roll-Call Votes Database. https://voteview.com/"
> "Data is updated live, as new votes are taken."
> Complete database dump: "for users interested in building a website based on Voteview.com data, we make available a complete dump of our MongoDB database. This release is updated weekly and is provided without warranty."

Source: https://voteview.com/articles/data_help_members (dated January 22, 2026), section "Citation": "To cite this data, please use the following citation: Lewis, Jeffrey B., Keith Poole, Howard Rosenthal, Adam Boche, Aaron Rudkin, and Luke Sonnet (2026). Voteview: Congressional Roll-Call Votes Database. https://voteview.com/". The same "To cite this data" block is on https://voteview.com/articles/data_help_votes. Also recommended there: Boche, Lewis, Rudkin and Sonnet, "The new Voteview.com: preserving and continuing Keith Poole's infrastructure for scholars, students and observers of Congress", Public Choice 176(1-2) (for NOMINATE scores).

Source: https://voteview.com/about : "UCLA's Department of Political Science and Social Science Computing host and maintain NOMINATE score data and voteview.com." and "Some open source components used under license."

**What I did NOT find: any licence for the DATA.** No Creative Commons, public-domain, or "free for any use" statement, and no prohibition (no NonCommercial wording either) on /about, /data, the data documentation pages, or the footer. The only condition stated is the citation request ("Please cite").

The only licence text I found anywhere on the project is for the SOFTWARE: https://raw.githubusercontent.com/voteview/WebVoteView/master/LICENSE : "MIT License / Copyright (c) 2018 voteview (maintained by UCLA Political Science) / Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software ..." This covers the website source code repo, not the NOMINATE data. (A web-search summary claimed "the entire project is offered under the MIT public license"; I could not confirm that sentence on any page I could read, since the cited Springer article page would not load for me, so I do not rely on it.)

### 6b. nominate_dim2 confirmation
Source: https://voteview.com/articles/data_help_members ("Member Ideology Data", Ideological Fields): "nominate_dim1 : NOMINATE first dimension estimate. nominate_dim2 : NOMINATE second dimension estimate." CONFIRMED in the actual file too: header line of https://voteview.com/static/data/out/members/HSall_members.csv (HTTP 200, `application/octet-stream`, 6,201,422 bytes, Last-Modified Sat, 03 Oct 2026 06:11:02 GMT; I read only the first line, nothing saved):

`congress,chamber,icpsr,state_icpsr,district_code,state_abbrev,party_code,occupancy,last_means,bioname,bioguide_id,born,died,nominate_dim1,nominate_dim2,nominate_log_likelihood,nominate_geo_mean_probability,nominate_number_of_votes,nominate_number_of_errors,conditional,nokken_poole_dim1,nokken_poole_dim2`

Note: the doc page names the likelihood fields `log_likelihood` / `geo_mean_probability` / `number_of_votes`, but the real CSV columns are `nominate_log_likelihood`, `nominate_geo_mean_probability`, `nominate_number_of_votes`, `nominate_number_of_errors` (so code against the CSV header, not the prose). Also notable: the file includes `chamber` value "President" rows, `bioguide_id` (join key to congress-legislators), and `icpsr` (same as congress-legislators `id.icpsr`).

### 6c. Format, access, freshness
- Data type menu: Member Ideology, Congressional Votes, Members' Votes, Congressional Parties; per-chamber and per-Congress or "All"; formats CSV (recommended), JSON, DAT, ORD. Quick link for all members: https://voteview.com/static/data/out/members/HSall_members.csv (keyless, plain GET). Data "updated live", the CSV timestamp is today. Complete MongoDB dump (~500 MB zipped) updated weekly, "provided without warranty". No API key and no stated rate limit; an R package (Rvoteview) is advertised.
- Contact for questions (about page): Current Lead Developer Barney Chen, barneychen@ucla.edu; Project Lead Jeffrey B. Lewis (UCLA).

### 6 DETERMINATIONS
- **(1) Free public site with attribution: UNDETERMINED, leaning permitted in practice but NOT established.** The site says the data is made "available to the public" and asks for a citation, but states no licence. Absent a licence the data are the UCLA team's work product; a citation request is not a grant.
- **(2) Paid compiled dataset: UNDETERMINED**, same reason (no NC clause exists because no terms exist; equally no right to resell is granted). NOMINATE scores are derived estimates (the one Voteview-specific thing Beholden would be redistributing), whereas roll-call vote facts are public government records.
- Attribution wording requested (cite exactly): "Lewis, Jeffrey B., Keith Poole, Howard Rosenthal, Adam Boche, Aaron Rudkin, and Luke Sonnet (2026). Voteview: Congressional Roll-Call Votes Database. https://voteview.com/" (also recommended for the NOMINATE scores: Boche et al., Public Choice 176(1-2)).
- Practical route: email the project lead/lead developer (above) asking for an explicit statement that NOMINATE data may be republished, including in a commercial compilation, with citation; save the reply. If refused or no answer, drop `nominate_dim2` and NOMINATE scores from the paid product and keep them out of any bulk download.
- Confidence: **read in full** for the site pages (nothing licensing the data exists); the Springer paper (**terms not read**, page would not load).

---

## 7. Congress.gov API (api.congress.gov, Library of Congress)

Read 2026-10-03: https://api.congress.gov/ (home: only links "Legal" -> https://www.loc.gov/legal and "Visit Congress.gov"), https://api.congress.gov/sign-up/ (only link: Legal -> loc.gov/legal), the API's GitHub repo README (https://raw.githubusercontent.com/LibraryOfCongress/api.congress.gov/main/README.md, full), https://www.loc.gov/legal/ (full), https://www.loc.gov/legal/understanding-copyright/ (scanned), https://api.data.gov/docs/developer-manual/ (full). **Could not read:** https://www.congress.gov/help/legal-notices (HTTP 403); no standalone "API terms of use" page exists that I could find (the API home and sign-up pages link only to loc.gov/legal).

### 7a. Purpose and key (verbatim)
Source: README "Introduction": 
> "The Congress.gov Application Programming Interface (API) provides a method for Congress and the public to view, retrieve, and re-use machine-readable data from collections available on Congress.gov."

README "Keys": "An API key is required for access. Sign up for a key [here](https://api.congress.gov/sign-up/). Learn more on how you can use your API key to access the Congress.gov API on [api.data.gov](https://api.data.gov/docs/api-key/)." Keys are free and issued via api.data.gov (40-character string, passed as `api_key` query parameter or HTTP basic-auth username, per https://api.data.gov/docs/developer-manual/).

### 7b. Rate limit (verbatim)
Source: README "Rate Limit": 
> "The rate limit is set to 5,000 requests per hour."
(the api.data.gov default of "Hourly Limit: 1,000 requests per hour" applies to other agencies; Congress.gov's own README sets 5,000/hour). Paging: "By default, the API returns 20 results starting with the first record. The 20 results limit can be adjusted up to 250 results." api.data.gov says exceeding limits "will lead to your API key being temporarily blocked ... The block will automatically be lifted by waiting an hour."
Separately, https://www.loc.gov/legal/ (general Library websites section "Security") says: "We reserve the right to block IP addresses that fail to honor our websites' robot.txt files, or submit requests at a rate that negatively impacts service delivery to patrons. Current guidelines recommend that software programs submit a total of no more than 10 requests per minute to our applications, regardless of the number of machines used to submit requests. We also reserve the right to terminate programs that require more than 24 hours to complete." (This is the Library's website-wide guidance; the API-specific stated limit is the 5,000/hour above. Treat both as binding in practice.)

### 7c. Copyright / reuse statements found
- https://www.loc.gov/legal/understanding-copyright/ (Library of Congress, read 2026-10-03): "Importantly, works produced by federal government employees in the course of their employment are generally not protected by copyright and are in the public domain in the U.S. This includes works produced by Library of Congress employees in the course of their duties at the Library. Unless otherwise indicated on this site, the Library of Congress has no objection to the international use and reuse of Library U.S. Government works on loc.gov. These works are also available for worldwide use and reuse under CC0 1.0 Universal."  (Written about loc.gov items, not specifically about Congress.gov API data.)
- https://www.loc.gov/legal/ "About Copyright and the Collections": "As a publicly supported institution, we generally do not own the rights to materials in our collections. You should determine for yourself whether or not an item is protected by copyright or in the public domain, and then satisfy any copyright or use restrictions when publishing or distributing materials from our collections."
- README "Reporting suspected missing, inaccurate, or incomplete data": "The data available on the website and via the API are what have been delivered by chambers to Congress.gov." (i.e. the data come from the House, Senate, GPO and Library staff.)
- Privacy: "API keys and user registration follow the data.gov privacy policy." / "API content follows the Library of Congress privacy policy."
- The repo has no LICENSE file (root listing: .gitignore, ChangeLog.md, Documentation, README.md, api_client, java, python). No attribution wording is specified anywhere I read.
- Not read: Congress.gov's own legal notices page (403), so any Congress.gov-specific copyright statement is unconfirmed. CRS report PDFs and some Congress.gov content can include third-party copyrighted material (not read, not needed for bills/members/votes).

### 7d. Data and format
JSON or XML (`<api-root>` wrapper for XML). Endpoint docs in the repo cover amendment, bill, Congressional Record, committee (and reports/meetings/prints), congress, CRS report, hearing, House communication, House requirement, **House roll call vote (BETA)**, member, nomination, Senate communication, summaries, treaty. House roll call vote doc: "Beta House Roll Call Vote data in the API currently includes all House roll call votes in the 118th and 119th Congresses associated with a piece of legislation. Non-legislation related votes (e.g., 'Election of the Speaker') will be added at a later date." There is no Senate roll-call endpoint in the docs listing (Senate vote data must come from elsewhere). Coverage/update timing page referenced: https://www.congress.gov/help/coverage-dates (not read).

### 7 DETERMINATIONS
- **(1) Free public site with attribution: YES, on read evidence, with one unread page.** The API's stated purpose is for "the public to view, retrieve, and re-use machine-readable data"; the Library states federal-employee works are generally public domain and (for loc.gov works) CC0; no restriction, NonCommercial clause or attribution requirement was found. The Congress.gov Legal Notices page (403) was not read.
- **(2) Paid compiled dataset: YES for bill/member/House-vote facts, same basis**, with those same caveats: no commercial-use prohibition found; the API key and rate limit (5,000/hour; stay under with caching) are the only conditions. Exclude third-party copyrighted content (e.g. some CRS products) and do not imply Library/Congress endorsement.
- Attribution wording: none specified. API key: required (free, api.data.gov). Rate limit: 5,000 requests per hour; max 250 results per page.
- Confidence: **read partially** (README, loc.gov legal and copyright pages, api.data.gov manual read; congress.gov legal-notices **terms not read**; no dedicated API ToS exists to read).

---

## 8. MIT Election Data + Science Lab (MEDSL): County Presidential Election Returns 2000-2024 (Harvard Dataverse)

Read 2026-10-03. Pages and endpoints read: the Dataverse dataset record via its metadata API (`https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/VOQCHQ`, plus `/versions/:latest/metadata` and `/versions/:latest/citation`); the guestbook definition `https://dataverse.harvard.edu/api/guestbooks/458`; the file-level tabular metadata `https://dataverse.harvard.edu/api/access/datafile/13573089/metadata/ddi`; the Harvard Dataverse General Terms of Use via `https://dataverse.harvard.edu/api/info/applicationTermsOfUse` (the human page https://support.dataverse.harvard.edu/harvard-dataverse-general-terms-use returned HTTP 403 to my fetch; the dataset HTML landing page returned HTTP 202 with no content, i.e. a script or bot challenge, so I used the API); the lab's data index https://electionlab.mit.edu/data (the lab site's only terms-like link found on its home page is /about; no separate data-terms page found). I did NOT download the data file (see 8c).

### 8a. Licence statement (verbatim, machine-readable field on the dataset record)
Source: dataset record, `latestVersion.license` (read 2026-10-03):

> name "CC0 1.0", uri "http://creativecommons.org/publicdomain/zero/1.0", rightsIdentifier "CC0-1.0" (SPDX)

The same record's free-text terms fields are all empty: `termsOfUse`, `confidentialityDeclaration`, `specialPermissions`, `restrictions`, `citationRequirements`, `depositorRequirements`, `conditions`, `disclaimer` are each null. The JSON-LD export says `"schema:license":"http://creativecommons.org/publicdomain/zero/1.0"` and `"dvcore:fileRequestAccess": false` (files are not restricted). No NonCommercial, ShareAlike, attribution-required or no-resale wording exists anywhere on the record.

Platform terms (https://dataverse.harvard.edu/api/info/applicationTermsOfUse, "Harvard Dataverse General Terms of Use"), the operative sentences:

> "You acknowledge that Harvard Dataverse's default data usage license agreement for all uploaded materials is a Creative Commons Zero ('CC0') Public Domain Dedication Waiver."
> "Downloaders must be registered Users of the Site or agree to the Guest Terms of Use in order to take advantage of the Site's Services, including downloading any materials or datasets."
> Downloaders represent that they "will abide by the applicable data usage license agreement attached to the dataset" and "acknowledge that their account information (for Users) or temporary site identification information (for Guests) may be recorded upon download, which can then be viewed by the owner of the User Upload".

(The fetched text rendered curly quotes as replacement characters; wording otherwise as shown.) The Terms also disclaim accuracy: "DOES NOT WARRANT THAT: (A) THE CONTENT OR USER UPLOADS ARE TIMELY, ACCURATE, COMPLETE, RELIABLE OR CORRECT IN THEIR POSTED FORMS ON THE SERVICE".

### 8b. What the dataset is
- Title "County Presidential Election Returns 2000-2024", author "MIT Election Data and Science Lab" (Massachusetts Institute of Technology). DOI https://doi.org/10.7910/DVN/VOQCHQ. Description: "This dataset contains county-level returns for presidential elections from 2000 to 2024." Version 20.0, `lastUpdateTime` 2026-02-25T19:00:32Z, first published 2018-10-11. Dataverse-generated citation: MIT Election Data and Science Lab, 2018, "County Presidential Election Returns 2000-2024", https://doi.org/10.7910/DVN/VOQCHQ, Harvard Dataverse, V20, UNF:6:xvsJJxrfXMIvzAuDYlfvVw== [fileUNF]. The licence requires no citation; this is the platform's suggested citation.
- Files (all `restricted: false`): `countypres_2000-2024.tab` (9,845,506 bytes, tab-separated, file id 13573089), `County Presidential Returns 2000-2024.md` (codebook, 2,604 bytes, id 11723285), `sources-president.tab` (5,038 bytes, per-state sources, id 10493708).
- Columns (from the file's DDI metadata): `state, county_name, year, state_po, county_fips, office, candidate, party, candidatevotes, totalvotes, version, mode`; 12 variables, 94,151 cases. It is election RESULTS by county (candidate vote counts), not a list of officials.
- Provenance: a per-state `sources-president.tab` file ships with it (so the underlying state and county official sources are recorded); I did not read it or those sources' terms, since the file is behind the guestbook.

### 8c. Access: not keyless in the strict sense
Every file download returned HTTP 400 for an anonymous GET:

> {"status":"ERROR","message":"You may not download this file without the required Guestbook response for guestbookID 458."}

Guestbook 458 ("General guestbook", enabled) requires name, email, institution and position (`nameRequired`, `emailRequired`, `institutionRequired`, `positionRequired` all true; no custom questions). So a person must submit those four fields to download, even though the licence is CC0. I did not submit a guestbook response (a form submission with personal data; that is for the maintainers to decide), and I did not use the API route that supplies a guestbook response with a download request. The metadata (variables, sizes, licence) is readable with no key. Consequence for the pipeline: a nightly keyless fetch of the file does not work as-is; options are a one-off manual download by a maintainer (the data change only after each presidential election, so one download per cycle is realistic) with the guestbook response recorded, or asking the lab whether a no-guestbook mirror exists. The dataset's contact is listed in the record's metadata (an MIT address; not copied here).

### 8 DETERMINATIONS
- **(1) Free public site with attribution: YES.** The dataset record carries CC0 1.0, the platform's stated default, and no other terms field is filled. Attribution is not required by CC0; citing "MIT Election Data and Science Lab, County Presidential Election Returns 2000-2024, https://doi.org/10.7910/DVN/VOQCHQ" is the courteous form and fits the provenance envelope.
- **(2) Paid compiled dataset: YES on the stated terms.** CC0 permits commercial reuse; no NC/SA/resale clause found on the record or in the platform Terms. Caveats: (i) CC0 covers what MEDSL owns; the figures are official results compiled from state and county sources (recorded in `sources-president.tab`, not read), so the underlying official-source terms are unread, though election returns are public government records; (ii) the guestbook gate and the "agree to Guest Terms" step mean a human accepts a click-through on download; (iii) the lab's own site states no data terms that I could find, so the CC0 on the Dataverse record is the only grant; (iv) accuracy is disclaimed, so keep the `version` column and the DOI/version in each source envelope; (v) no implied MIT endorsement.
- Attribution wording: none required. Rate limit / key: none stated for metadata; file download is gated by the guestbook, not by an API key.
- Confidence: **read in full** for the dataset record, licence field, guestbook definition, DDI and the Dataverse Terms of Use (via the API text); the lab's /about page, the codebook `.md` and the sources file **not read** (behind the guestbook; not submitted).

---

## Summary table (all eight sources)

Verdict key: YES, NO, UNDETERMINED. (1) = free public republish with attribution; (2) = inclusion in a sold compiled dataset. Verdicts record what the published wording supports; they are not legal advice, and where terms are silent the verdict is UNDETERMINED.

| # | Source | Licence wording found (short) | Keyless? | (1) Free site | (2) Paid dataset | Main caveat |
|---|---|---|---|---|---|---|
| 1 | Open States / Plural | "public domain dedication"; ToS: "No attribution is required" | People CSV and Postgres dump yes; session CSV/JSON need free login; API needs key | YES | YES | Upstream state-site terms and full bill text unread; dump unsupported |
| 2 | UT CTAS county officials (TN) | "content ... is copyrighted"; permission needed; no grant | Yes (HTML + CSV) | UNDETERMINED | UNDETERMINED | Disclaimer page 403; awaits written permission; no commissioner districts |
| 3 | UT MTAS municipal officials (TN) | "content ... is copyrighted"; no grant | Yes (CSV + undocumented JSON endpoints) | UNDETERMINED | UNDETERMINED | Awaits written permission; no wards or term dates |
| 4 | Legistar Web API (Granicus) | No API terms exist; content owned by each client government | Per client (token only if the client requires one) | UNDETERMINED | UNDETERMINED | Terms are per jurisdiction and unread |
| 5 | unitedstates/congress-legislators | CC0 1.0 | Yes | YES | YES | Upstream committee-history sources unread |
| 6 | Voteview (UCLA) | No data licence; citation requested | Yes | UNDETERMINED | UNDETERMINED | Ask for an explicit statement; else drop NOMINATE |
| 7 | Congress.gov API (LoC) | "view, retrieve, and re-use machine-readable data"; no restriction found | Key required (free) | YES | YES | Legal-notices page 403; 5,000 requests/hour |
| 8 | MEDSL county presidential returns (Harvard Dataverse) | Dataset licence field "CC0 1.0"; no other terms | No: download needs a guestbook response (name, email, institution, position) | YES | YES | Guestbook gate; underlying state sources unread; accuracy disclaimed |
