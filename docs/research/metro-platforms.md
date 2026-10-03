# Metro legislative platforms: 50 largest US cities and 30 largest counties

Research date: 2026-10-03. Population: US Census Bureau Vintage 2024 estimates (July 1, 2024), read from the Bureau's files `sub-est2024.csv` (places) and `co-est2024-alldata.csv` (counties), https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/ . Cities: incorporated places and consolidated governments; for consolidated governments (Indianapolis, Louisville/Jefferson County, Nashville-Davidson) the consolidated total is used.

## Method and limits (read first)

- For each jurisdiction I made ONE GET to `https://webapi.legistar.com/v1/{client}/bodies?$top=1` with User-Agent `Beholden research, maintainers@beholden.vote`, 1 second apart, no token, no retries, no second guess for the same jurisdiction. The `{client}` slug is my best guess from the jurisdiction's usual Legistar host name (the API has no public client list). So: HTTP 200 = a Legistar client of that name exists and answers WITHOUT a token; HTTP 500 with message 'LegistarConnectionString setting is not set up in InSite for client: X' = no client with that slug (wrong guess OR not on Legistar; this does NOT show the city is not on Legistar); 403 = refused.
- **The run was stopped at the first 403 (client `nyc`, New York City), as the research rules require.** The clients that sort after `nyc` alphabetically were NOT probed (marked 'not probed'): that includes several large jurisdictions (for example Philadelphia, Phoenix, San Antonio, San Diego, San Jose, San Francisco, Seattle, Tampa) whose slugs I have not tested. Re-running those needs a decision from the maintainers on whether a single 403 should stop the whole run or only that client.
- Platform column is evidence-based only: where the API did not answer I do not assert a platform. Non-Legistar platforms (Granicus, Municode, CivicPlus, PrimeGov, other) were NOT identified in this pass; that needs a per-city page read and is open work.
- Roll-call votes: whether EventItems carry votes was not cheaply visible in a `bodies` response, so the 'Votes' column is blank for all rows (it needs `/events`, `/eventitems`, `/votes` calls, outside the one-GET budget).
- Slug collisions: a 200 proves only that the slug exists; I saw only the first characters of the first body name. `maricopa` returned a body starting 'Cit' (likely the City of Maricopa, a small town in Pinal County, not Maricopa County); `lacounty` returned a body starting 'Finan' and `broward` one starting 'Coun'; treat those three as UNCONFIRMED as to which government they are until a body list is read.
- Counties that are not governments: Kings, Queens, New York and Bronx counties (NYC boroughs) have no county legislature separate from the NYC Council; Philadelphia County is the City of Philadelphia; Middlesex County MA's government was abolished (from my own knowledge, not checked here); Suffolk/Nassau etc. are real county governments.
- A 200 means the API answers without a token today. It says nothing about reuse terms, which are per jurisdiction (see local-sources-2026-10.md section 4).

## Cities (top 50)

| Rank | City | Pop. 2024 | Client slug tried | Platform / evidence | HTTP | Votes |
|---|---|---|---|---|---|---|
| 1 | New York, New York | 8,478,072 | nyc | Legistar client likely; API refused | 403 |  |
| 2 | Los Angeles, California | 3,878,704 | lacity | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 3 | Chicago, Illinois | 2,721,308 | chicago | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 4 | Houston, Texas | 2,390,125 | houston | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 5 | Phoenix, Arizona | 1,673,164 |  | not probed (stopped after nyc 403) | not probed |  |
| 6 | Philadelphia, Pennsylvania | 1,573,916 |  | not probed (stopped after nyc 403) | not probed |  |
| 7 | San Antonio, Texas | 1,526,656 |  | not probed (stopped after nyc 403) | not probed |  |
| 8 | San Diego, California | 1,404,452 |  | not probed (stopped after nyc 403) | not probed |  |
| 9 | Dallas, Texas | 1,326,087 | dallascityhall | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 10 | Jacksonville, Florida | 1,009,833 | jaxcityc | Legistar; keyless | 200 |  |
| 11 | Fort Worth, Texas | 1,008,106 | fortworthtexas | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 12 | San Jose, California | 997,368 |  | not probed (stopped after nyc 403) | not probed |  |
| 13 | Austin, Texas | 993,588 | austintexas | Legistar; keyless | 200 |  |
| 14 | Charlotte, North Carolina | 943,476 | charlottenc | Legistar; keyless | 200 |  |
| 15 | Columbus, Ohio | 933,263 | columbus | Legistar; keyless | 200 |  |
| 16 | Indianapolis, Indiana | 900,896 | indy | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 17 | San Francisco, California | 827,526 |  | not probed (stopped after nyc 403) | not probed |  |
| 18 | Louisville/Jefferson County metro government, Kentucky | 793,881 | louisville | Legistar; keyless | 200 |  |
| 19 | Seattle, Washington | 780,995 |  | not probed (stopped after nyc 403) | not probed |  |
| 20 | Nashville-Davidson metropolitan government, Tennessee | 729,505 | nashville | Legistar; keyless | 200 |  |
| 21 | Denver, Colorado | 729,019 | denver | Legistar; keyless | 200 |  |
| 22 | Oklahoma City, Oklahoma | 712,919 |  | not probed (stopped after nyc 403) | not probed |  |
| 23 | El Paso, Texas | 681,723 | elpasotexas | Legistar; keyless | 200 |  |
| 24 | Las Vegas, Nevada | 678,922 | lasvegas | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 25 | Boston, Massachusetts | 673,458 | boston | Legistar; keyless | 200 |  |
| 26 | Detroit, Michigan | 645,705 | detroitmi | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 27 | Portland, Oregon | 635,749 |  | not probed (stopped after nyc 403) | not probed |  |
| 28 | Memphis, Tennessee | 610,919 | memphistn | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 29 | Baltimore, Maryland | 568,271 | baltimore | Legistar; keyless | 200 |  |
| 30 | Milwaukee, Wisconsin | 563,531 | milwaukee | Legistar; keyless | 200 |  |
| 31 | Albuquerque, New Mexico | 560,326 | cabq | Legistar; keyless | 200 |  |
| 32 | Tucson, Arizona | 554,013 |  | not probed (stopped after nyc 403) | not probed |  |
| 33 | Fresno, California | 550,105 | fresno | Legistar; keyless | 200 |  |
| 34 | Sacramento, California | 535,798 | cityofsacramento | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 35 | Atlanta, Georgia | 520,070 | atlantacityga | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 36 | Mesa, Arizona | 517,151 | mesa | Legistar; keyless | 200 |  |
| 37 | Kansas City, Missouri | 516,032 | kansascity | Legistar; keyless | 200 |  |
| 38 | Raleigh, North Carolina | 499,825 |  | not probed (stopped after nyc 403) | not probed |  |
| 39 | Colorado Springs, Colorado | 493,554 | coloradosprings | Legistar; keyless | 200 |  |
| 40 | Omaha, Nebraska | 489,265 |  | not probed (stopped after nyc 403) | not probed |  |
| 41 | Miami, Florida | 487,014 | miamifl | Legistar; keyless | 200 |  |
| 42 | Virginia Beach, Virginia | 454,808 |  | not probed (stopped after nyc 403) | not probed |  |
| 43 | Long Beach, California | 450,901 | longbeach | Legistar; keyless | 200 |  |
| 44 | Oakland, California | 443,554 |  | not probed (stopped after nyc 403) | not probed |  |
| 45 | Minneapolis, Minnesota | 428,579 | minneapolismn | Legistar; keyless | 200 |  |
| 46 | Bakersfield, California | 417,468 | bakersfield | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 47 | Tulsa, Oklahoma | 415,154 |  | not probed (stopped after nyc 403) | not probed |  |
| 48 | Tampa, Florida | 414,547 |  | not probed (stopped after nyc 403) | not probed |  |
| 49 | Arlington, Texas | 403,672 | arlingtontx | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 50 | Aurora, Colorado | 403,130 | aurora | slug not a Legistar client, or different slug; platform undetermined | 500 |  |

## Counties (top 30)

| Rank | County | Pop. 2024 | Client slug tried | Platform / evidence | HTTP | Votes |
|---|---|---|---|---|---|---|
| 1 | Los Angeles County, California | 9,757,179 | lacounty | Legistar; keyless | 200 |  |
| 2 | Cook County, Illinois | 5,182,617 | cook-county | Legistar; keyless | 200 |  |
| 3 | Harris County, Texas | 5,009,302 | harriscounty | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 4 | Maricopa County, Arizona | 4,673,096 | maricopa | Legistar; keyless | 200 |  |
| 5 | San Diego County, California | 3,298,799 |  | not probed (stopped after nyc 403) | not probed |  |
| 6 | Orange County, California | 3,170,435 |  | not probed (stopped after nyc 403) | not probed |  |
| 7 | Miami-Dade County, Florida | 2,838,461 | miamidade | Legistar; keyless | 200 |  |
| 8 | Dallas County, Texas | 2,656,028 | dallascounty | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 9 | Kings County, New York | 2,617,631 |  | no client guess (see note) |  |  |
| 10 | Riverside County, California | 2,529,933 |  | not probed (stopped after nyc 403) | not probed |  |
| 11 | Clark County, Nevada | 2,398,871 | clarkcountynv | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 12 | King County, Washington | 2,340,211 | kingcounty | Legistar; keyless | 200 |  |
| 13 | Queens County, New York | 2,316,841 |  | no client guess (see note) |  |  |
| 14 | Tarrant County, Texas | 2,230,708 |  | not probed (stopped after nyc 403) | not probed |  |
| 15 | San Bernardino County, California | 2,214,281 |  | not probed (stopped after nyc 403) | not probed |  |
| 16 | Bexar County, Texas | 2,127,737 | bexar | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 17 | Broward County, Florida | 2,037,472 | broward | Legistar; keyless | 200 |  |
| 18 | Santa Clara County, California | 1,926,325 |  | not probed (stopped after nyc 403) | not probed |  |
| 19 | Wayne County, Michigan | 1,771,063 |  | not probed (stopped after nyc 403) | not probed |  |
| 20 | Middlesex County, Massachusetts | 1,668,956 | middlesex | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 21 | New York County, New York | 1,660,664 |  | no client guess (see note) |  |  |
| 22 | Alameda County, California | 1,649,060 | alamedacounty | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 23 | Sacramento County, California | 1,611,231 |  | not probed (stopped after nyc 403) | not probed |  |
| 24 | Palm Beach County, Florida | 1,582,055 |  | not probed (stopped after nyc 403) | not probed |  |
| 25 | Hillsborough County, Florida | 1,581,426 | hillsborough | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 26 | Philadelphia County, Pennsylvania | 1,573,916 |  | no client guess (see note) |  |  |
| 27 | Suffolk County, New York | 1,535,909 |  | not probed (stopped after nyc 403) | not probed |  |
| 28 | Orange County, Florida | 1,533,646 |  | not probed (stopped after nyc 403) | not probed |  |
| 29 | Nassau County, New York | 1,392,438 | nassaucountyny | slug not a Legistar client, or different slug; platform undetermined | 500 |  |
| 30 | Bronx County, New York | 1,384,724 |  | no client guess (see note) |  |  |

## First ten Legistar jurisdictions by population that answered without a token

Among the jurisdictions probed (cities and counties together; the three unconfirmed slugs excluded; jurisdictions not probed cannot appear, so this ranking may change once the remaining clients are tested):

| # | Jurisdiction | Pop. 2024 | Client |
|---|---|---|---|
| 1 | Cook County, Illinois | 5,182,617 | cook-county |
| 2 | Miami-Dade County, Florida | 2,838,461 | miamidade |
| 3 | King County, Washington | 2,340,211 | kingcounty |
| 4 | Jacksonville city, Florida | 1,009,833 | jaxcityc |
| 5 | Austin city, Texas | 993,588 | austintexas |
| 6 | Charlotte city, North Carolina | 943,476 | charlottenc |
| 7 | Columbus city, Ohio | 933,263 | columbus |
| 8 | Louisville/Jefferson County metro government, Kentucky | 793,881 | louisville |
| 9 | Nashville-Davidson metropolitan government, Tennessee | 729,505 | nashville |
| 10 | Denver city, Colorado | 729,019 | denver |

Full list of keyless 200s found: Cook County (cook-county), Miami-Dade County (miamidade), King County (kingcounty), Jacksonville city (jaxcityc), Austin city (austintexas), Charlotte city (charlottenc), Columbus city (columbus), Louisville/Jefferson County metro government (louisville), Nashville-Davidson metropolitan government (nashville), Denver city (denver), El Paso city (elpasotexas), Boston city (boston), Baltimore city (baltimore), Milwaukee city (milwaukee), Albuquerque city (cabq), Fresno city (fresno), Mesa city (mesa), Kansas City city (kansascity), Colorado Springs city (coloradosprings), Miami city (miamifl), Long Beach city (longbeach), Minneapolis city (minneapolismn).

## Open work

- Probe the unprobed clients (decision needed on the 403 stop rule), and re-guess the slugs that returned 'not set up'.
- Identify the non-Legistar platforms by reading each city/county meeting page.
- Fill the Votes column.
