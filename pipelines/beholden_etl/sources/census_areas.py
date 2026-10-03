"""Facts about every county and city: Census ACS 5-year + Gazetteer (WO-34).

Two public-domain products of the U.S. Census Bureau feed one artifact:

  census_acs        Census Data API, American Community Survey 5-year, four tables
                    (B01003 population, B11001 households, B19013 median household
                    income, B01002 median age), each as estimate and margin of error.
  census_gazetteer  The Gazetteer national counties + places files: the Bureau's own
                    name and land area (ALAND_SQMI) for each geography.

TERMS, as the Bureau states them (census.gov/data/developers/about/terms-of-service,
page revised 2026-04-14):
  * Attribution: services using the API "should display the following notice
    prominently within the application: 'This product uses the Census Bureau Data API
    but is not endorsed or certified by the Census Bureau.'"  It is on the public
    Sources page (web/src/ui/chrome.tsx).
  * "You may not modify or falsely represent content accessed through the API and still
    claim the source is the Census Bureau." That is why a withheld value is OMITTED
    below rather than rewritten, and why nothing here computes anything.
  * A key is required. The Data API User Guide (revised 2026-05-12) says "An API key must
    be used with all data queries"; observed 2026-10-03, a keyless data call is answered
    with a 302 to /data/missing_key.html (an HTML page, HTTP 200) and a bad key with an
    HTML "Invalid Key" page. Metadata endpoints are open. The key is free; read from
    CENSUS_API_KEY and never written to the raw lake, the manifest or an error message.

VINTAGES ARE PINNED, not discovered (ACS_YEAR, GAZETTEER_VINTAGE). ACS 2020-2024 is the
newest 5-year release the API serves (api.census.gov/data/2025/acs/acs5 does not exist
yet). The Gazetteer vintage matches the ACS geography year, not the tile vintage: ACS
2024 tabulates 2024 geography, so a 2025 Gazetteer would disagree with it about which
places exist and the row-count gate below would (rightly) refuse.

SENTINELS ARE THE TRAP. The API reports a withheld value as a large negative number and
annotates it. Documented at census.gov/data/developers/data-sets/acs-1year/
notes-on-acs-estimate-and-annotation-values (revised 2026-07-20):
  -666666666  could not be computed: too few sample observations, or a median that falls
              in an open-ended interval, or a 5-year median whose margin exceeds it
  -999999999  (annotation N)   cannot be displayed: too few sample cases
  -888888888  (annotation (X)) not applicable or not available
  -222222222  (annotation **)  margin could not be computed: too few observations
  -333333333  (annotation ***) margin could not be computed: open-ended median interval
  -555555555  (annotation *****) margin not appropriate: the estimate is controlled to an
              independent total (a county's population), so it has no sampling error
  null        no data for the geography
  median-/median+ (annotation, value varies)  the median sits in the lowest/highest
              open-ended interval: the number is a bound, not an estimate
Rule: an ESTIMATE that is a sentinel, null or annotated is OMITTED for that area; a MARGIN
that is a sentinel, null or annotated is published as null. Any other negative number is an
undocumented sentinel and halts the run: guessing is how minus six hundred million dollars
gets a citation.

GATES (all fail closed; nothing here is wrapped in try/except):
  schema     ACS header and Gazetteer header must match the pinned layout exactly
  control    per state, sum(county population) == state population from the same API,
             within the rounding bound of independently rounded integers
  row count  per state, ACS rows vs the Gazetteer's (see check_row_counts)
  domain     no negative population, households, income, age, margin or land area
Extraction copies verbatim cells; it never infers or computes (docs/TRUSTED-EXTRACTION.md).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

# -- Pinned vintages -----------------------------------------------------------------
ACS_YEAR = 2024
ACS_PERIOD = "2020-2024"
GAZETTEER_VINTAGE = 2024
ACS_API = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
ACS_SOURCE_URL = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5.html"
GAZETTEER_SOURCE_URL = ("https://www.census.gov/geographies/reference-files/time-series/geo/"
                        f"gazetteer-files.{GAZETTEER_VINTAGE}.html")
_GAZETTEER_FILE = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
                   "{v}_Gazetteer/{v}_Gaz_{name}_national.zip")
_GAZETTEER_NAMES = {"county": "counties", "place": "place"}   # the Bureau's own spelling

# The four facts, as published field -> ACS variable. Estimate (E), its annotation (EA),
# margin of error (M) and its annotation (MA) are requested together: the annotation is
# what says a number is not a plain estimate.
VARIABLES = {"population": "B01003_001", "households": "B11001_001",
             "median_household_income": "B19013_001", "median_age": "B01002_001"}
ACS_COLUMNS = ["NAME"] + [f"{v}{s}" for v in VARIABLES.values() for s in ("E", "EA", "M", "MA")]

# 50 states + DC, FIPS -> lowercase USPS. Territories are out of scope (WO-34).
STATES = {
    "01": "al", "02": "ak", "04": "az", "05": "ar", "06": "ca", "08": "co", "09": "ct",
    "10": "de", "11": "dc", "12": "fl", "13": "ga", "15": "hi", "16": "id", "17": "il",
    "18": "in", "19": "ia", "20": "ks", "21": "ky", "22": "la", "23": "me", "24": "md",
    "25": "ma", "26": "mi", "27": "mn", "28": "ms", "29": "mo", "30": "mt", "31": "ne",
    "32": "nv", "33": "nh", "34": "nj", "35": "nm", "36": "ny", "37": "nc", "38": "nd",
    "39": "oh", "40": "ok", "41": "or", "42": "pa", "44": "ri", "45": "sc", "46": "sd",
    "47": "tn", "48": "tx", "49": "ut", "50": "vt", "51": "va", "53": "wa", "54": "wv",
    "55": "wi", "56": "wy",
}

SENTINELS = frozenset({-666666666, -999999999, -888888888, -222222222, -333333333, -555555555})

# Gazetteer layouts, pinned. NB the 2025 files changed delimiter (tab -> pipe) and gained a
# GEOIDFQ column, so a vintage bump is a reviewed change to these lines, never a silent one.
_GAZETTEER_HEADERS = {
    "county": ["USPS", "GEOID", "ANSICODE", "NAME", "ALAND", "AWATER", "ALAND_SQMI",
               "AWATER_SQMI", "INTPTLAT", "INTPTLONG"],
    "place": ["USPS", "GEOID", "ANSICODE", "NAME", "LSAD", "FUNCSTAT", "ALAND", "AWATER",
              "ALAND_SQMI", "AWATER_SQMI", "INTPTLAT", "INTPTLONG"],
}
_GEOID_LEN = {"county": 5, "place": 7}
# census.gov/library/reference/code-lists/functional-status-codes: every code the Bureau
# defines. A code outside this set means the file is not what we pinned.
FUNCSTAT_CODES = frozenset("ABCEFGILMNS")
# "Active government ... providing primary general-purpose functions" (A) and its
# partially-consolidated-with-separate-officials variant for incorporated places (B).
# S statistical (CDPs), I inactive and N nonfunctioning have no government to describe.
ACTIVE_PLACE_FUNCSTAT = frozenset("AB")


def has_government(funcstat: str, name: str) -> bool:
    """Does this Gazetteer place row describe a government, so that we publish it?

    A and B, plus ONE rule for consolidated city-county governments. Nashville, Indianapolis,
    Louisville, Augusta, Athens, Butte-Silver Bow, Greeley County and Milford exist in the
    Gazetteer only as the Bureau's "(balance)" row - the consolidated government less the
    separately incorporated places inside it - with functional status F (fictitious), because
    the whole city-county has no place record of its own. The tile layer (WO-21) ships exactly
    those polygons, so a reader who clicks Nashville must get Nashville's facts. Rule, not
    list: F and "(balance)" in the name. An F row without "(balance)" stays out, and so does
    a "(balance)" row that is not F."""
    return funcstat in ACTIVE_PLACE_FUNCSTAT or (funcstat == "F" and "(balance)" in name)

# Every estimate is rounded to an integer independently of the one above it, so county
# populations can sum to a few people off the state's own figure: up to half a person per
# county. The gate allows one person per county, or this fraction of the state, whichever
# is larger, and nothing more.
CONTROL_TOTAL_RELATIVE = 1e-5


class CensusError(RuntimeError):
    """A Census source failed a gate or came back in a shape we did not pin."""


# -- Values --------------------------------------------------------------------------
def _num(raw: str, what: str) -> int | float:
    if not isinstance(raw, str) or not re.fullmatch(r"-?\d+(\.\d*)?", raw.strip()):
        raise CensusError(f"{what}: {raw!r} is not a number")
    raw = raw.strip()
    return float(raw) if "." in raw else int(raw)


def value(raw: str | None, annotation: str | None, what: str) -> int | float | None:
    """The number the Bureau published, or None when it withheld it.

    None means: null, annotated, or one of the documented SENTINELS. A caller omits a
    withheld estimate and nulls a withheld margin; neither is ever published as a number.
    Any other negative number is an undocumented sentinel and raises."""
    if raw is None or annotation is not None:
        return None
    n = _num(raw, what)
    if n in SENTINELS:
        return None
    if n < 0:
        raise CensusError(f"{what}: undocumented negative value {raw} "
                          "(not in the Bureau's sentinel list) - refusing to guess")
    return n


def survey_fields(rec: dict, what: str) -> dict[str, dict]:
    """{field: {"estimate", "moe"}} for one ACS row. A withheld estimate omits the field;
    a withheld margin is None."""
    out = {}
    for field, var in VARIABLES.items():
        est = value(rec[f"{var}E"], rec[f"{var}EA"], f"{what} {var}E")
        if est is not None:
            out[field] = {"estimate": est,
                          "moe": value(rec[f"{var}M"], rec[f"{var}MA"], f"{what} {var}M")}
    return out


# -- Parsers (pure: text in, rows out) -----------------------------------------------
def parse_acs(text: str, geo: tuple[str, ...], label: str,
              state: str | None = None) -> dict[str, dict]:
    """Census Data API response -> {GEOID: row}. Schema gate: the header must be exactly
    the columns we asked for, then the geography columns. Rows outside STATES (Puerto
    Rico) are dropped; rows must not repeat a GEOID."""
    try:
        data = json.loads(text)
    except ValueError:
        raise CensusError(
            f"{label}: response is not JSON ({text[:60]!r}...). A missing or invalid "
            "CENSUS_API_KEY is answered with an HTML page, not an error status.") from None
    if not isinstance(data, list) or len(data) < 2 or not all(isinstance(r, list) for r in data):
        raise CensusError(f"{label}: expected a header row plus data rows")
    head, n = data[0], len(ACS_COLUMNS)
    if head[:n] != ACS_COLUMNS or sorted(head[n:]) != sorted(geo):
        raise CensusError(f"{label}: header changed - schema drift, refusing to best-effort "
                          f"parse (got {head!r})")
    out: dict[str, dict] = {}
    for r in data[1:]:
        if len(r) != len(head):
            raise CensusError(f"{label}: row of {len(r)} cells under a {len(head)}-cell header")
        rec = dict(zip(head, r))
        if rec["state"] not in STATES:
            continue
        if state is not None and rec["state"] != state:
            raise CensusError(f"{label}: row for state {rec['state']} in a state-{state} call")
        geoid = "".join(rec[g] for g in geo)
        if geoid in out:
            raise CensusError(f"{label}: GEOID {geoid} appears twice")
        out[geoid] = rec
    return out


def parse_gazetteer(text: str, level: str) -> dict[str, dict]:
    """Gazetteer national file -> {GEOID: {usps, name, land_sqmi[, funcstat, active]}} for
    the 50 states + DC. Values are copied; padding the Bureau adds to the last column is
    trimmed."""
    header = _GAZETTEER_HEADERS[level]
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    if [h.strip() for h in lines[0].split("\t")] != header:
        raise CensusError(f"Gazetteer {level} header changed - schema drift "
                          f"(got {lines[0][:120]!r})")
    out: dict[str, dict] = {}
    for ln in lines[1:]:
        if not ln.strip():
            continue
        rec = dict(zip(header, (f.strip() for f in ln.split("\t"))))
        if len(ln.split("\t")) != len(header):
            raise CensusError(f"Gazetteer {level}: malformed row {ln[:80]!r}")
        geoid = rec["GEOID"]
        if geoid[:2] not in STATES:
            continue                                   # territories
        if not re.fullmatch(rf"\d{{{_GEOID_LEN[level]}}}", geoid) \
                or STATES[geoid[:2]] != rec["USPS"].lower():
            raise CensusError(f"Gazetteer {level}: GEOID {geoid!r} disagrees with USPS "
                              f"{rec['USPS']!r}")
        if geoid in out:
            raise CensusError(f"Gazetteer {level}: GEOID {geoid} appears twice")
        land = _num(rec["ALAND_SQMI"], f"Gazetteer {geoid} ALAND_SQMI")
        if land < 0 or not rec["NAME"]:
            raise CensusError(f"Gazetteer {level} {geoid}: negative land area or no name")
        row = {"usps": rec["USPS"].lower(), "name": rec["NAME"], "land_sqmi": float(land)}
        if level == "place":
            if rec["FUNCSTAT"] not in FUNCSTAT_CODES:
                raise CensusError(f"Gazetteer place {geoid}: unknown FUNCSTAT {rec['FUNCSTAT']!r}")
            row["active"] = has_government(rec["FUNCSTAT"], rec["NAME"])
            if row["active"] and (rec["LSAD"] == "57" or rec["NAME"].endswith(" CDP")):
                raise CensusError(f"Gazetteer place {geoid} {rec['NAME']!r} is both an active "
                                  "government and a census designated place - cannot tell "
                                  "which is true, so publishing neither")
        out[geoid] = row
    return out


# -- Gates ---------------------------------------------------------------------------
def check_control_totals(counties: dict[str, dict], states: dict[str, dict]) -> None:
    """Per state, sum(county population) must equal the state's own figure from the same
    API. Both are controlled to the same independent estimate, so they agree up to
    rounding. A withheld population cannot be reconciled and is a failure, not a skip."""
    def pop(rec: dict, what: str) -> int | float:
        p = value(rec["B01003_001E"], rec["B01003_001EA"], what)
        if p is None:
            raise CensusError(f"{what}: population withheld - control total cannot be checked")
        return p

    for fips, usps in STATES.items():
        parts = [pop(r, f"county {g}") for g, r in counties.items() if g.startswith(fips)]
        if not parts or fips not in states:
            raise CensusError(f"{usps.upper()}: no county rows or no state row - control total missing")
        total, state_pop = sum(parts), pop(states[fips], f"state {fips}")
        slack = max(len(parts), state_pop * CONTROL_TOTAL_RELATIVE)
        if abs(total - state_pop) > slack:
            raise CensusError(f"{usps.upper()}: county populations sum to {total:,} but the state's "
                              f"own figure is {state_pop:,} (tolerance {slack:,.0f}) - "
                              "the parse is wrong or the vintages disagree")


def check_row_counts(level: str, acs: dict[str, dict], gaz: dict[str, dict]) -> None:
    """Per state, the survey and the Gazetteer must describe the same geographies.
    A county in one and not the other, a city we would publish with no survey row, or a
    survey row the Gazetteer has never heard of (a GEOID reused across vintages) all halt."""
    for fips, usps in STATES.items():
        a = {g for g in acs if g.startswith(fips)}
        z = {g for g in gaz if g.startswith(fips)}
        want = z if level == "county" else {g for g in z if gaz[g]["active"]}
        unknown, missing = sorted(a - z), sorted(want - a)
        if not a or unknown or missing:
            raise CensusError(
                f"{usps.upper()} {level}: {len(a)} survey rows vs {len(z)} Gazetteer rows "
                f"({len(want)} to publish); in the survey only {unknown[:5]}, in the "
                f"Gazetteer only {missing[:5]}")


# -- Fetch (network) -----------------------------------------------------------------
def api_key() -> str | None:
    return os.environ.get("CENSUS_API_KEY") or None


def _redact(text: str) -> str:
    key = api_key()
    return text.replace(key, "<CENSUS_API_KEY>") if key else text


def _transient(e: BaseException) -> bool:
    return isinstance(e, httpx.TransportError) or (
        isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500)


@retry(retry=retry_if_exception(_transient), stop=stop_after_attempt(4),
       wait=wait_exponential(multiplier=2, max=60), reraise=True)
def _get(url: str) -> httpx.Response:
    r = httpx.get(url, timeout=120.0, follow_redirects=True,
                  headers={"User-Agent": "beholden.vote ETL (+https://beholden.vote)"})
    r.raise_for_status()
    return r


def _get_text(url: str) -> str:
    try:
        return _get(url).text
    except httpx.HTTPError as e:     # the URL (and so the key) is in the message
        raise CensusError(_redact(f"{type(e).__name__}: {e}")) from None


def _get_bytes(url: str) -> bytes:
    try:
        return _get(url).content
    except httpx.HTTPError as e:
        raise CensusError(_redact(f"{type(e).__name__}: {e}")) from None


def _acs_url(**predicates: str) -> str:
    q = {"get": ",".join(ACS_COLUMNS), **predicates, "key": api_key()}
    return f"{ACS_API}?{urlencode(q, safe=':*,')}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_acs(raw: Path, prior: dict) -> dict | None:
    """One national county call, one national state call (the control total), and one
    place call per state: 53 requests. Returns None when CENSUS_API_KEY is unset, so
    the source is simply absent from the manifest and the build writes no area files at
    all - the area files already published are left exactly as they are (honest absence,
    the same shape as the OpenStates votes crawl). Only reached when a fetch is due: a
    snapshot still inside its SLA is reused without a key."""
    if not api_key():
        msg = ("CENSUS_API_KEY is NOT SET - census_acs SKIPPED: no county or city facts will "
               "be fetched or built this run; area files already published are left untouched")
        # In GitHub Actions the workflow command turns the line into a run-summary annotation
        # instead of one more line in a long log.
        print(f"::warning title=census_acs skipped::{msg}" if os.environ.get("GITHUB_ACTIONS")
              else f"fetch: WARNING {msg}")
        return None
    d = raw / "census_acs"
    (d / "place").mkdir(parents=True, exist_ok=True)
    landed = {"county.json": _get_text(_acs_url(**{"for": "county:*"})),
              "state.json": _get_text(_acs_url(**{"for": "state:*"}))}
    for fips in STATES:
        landed[f"place/{fips}.json"] = _get_text(_acs_url(**{"for": "place:*", "in": f"state:{fips}"}))
    digest = hashlib.sha256()
    for name in sorted(landed):
        body = landed[name].encode("utf-8")
        (d / name).write_bytes(body)                       # bytes: no newline translation
        digest.update(name.encode() + body)
    counties, places = load_acs(raw)[:2]                   # schema + value-domain gates
    print(f"fetch: census_acs {len(counties)} counties, {len(places)} places")
    return {"retrieved_at": _now(), "source_url": ACS_SOURCE_URL,
            "count": len(counties) + len(places), "vintage": ACS_YEAR,
            "file_sha256": digest.hexdigest()}


def fetch_gazetteer(raw: Path, prior: dict) -> dict:
    d = raw / "census_gazetteer"
    d.mkdir(parents=True, exist_ok=True)
    digest, count = hashlib.sha256(), 0
    for level, name in _GAZETTEER_NAMES.items():
        with zipfile.ZipFile(io.BytesIO(_get_bytes(
                _GAZETTEER_FILE.format(v=GAZETTEER_VINTAGE, name=name)))) as z:
            members = z.namelist()
            if len(members) != 1:
                raise CensusError(f"Gazetteer {level} zip holds {members!r}, expected one file")
            data = z.read(members[0])
        (d / f"{level}.txt").write_bytes(data)
        digest.update(level.encode() + data)
        count += len(parse_gazetteer(data.decode("utf-8"), level))   # schema + domain gates
    print(f"fetch: census_gazetteer {count} geographies")
    return {"retrieved_at": _now(), "source_url": GAZETTEER_SOURCE_URL, "count": count,
            "vintage": GAZETTEER_VINTAGE, "file_sha256": digest.hexdigest()}


# -- Load landed snapshots (build) ---------------------------------------------------
def load_acs(raw: Path) -> tuple[dict, dict, dict]:
    """(counties, places, states) from the landed snapshot, every gate applied. Raises on
    a missing file: a snapshot we cannot read in full is not a smaller snapshot."""
    d = raw / "census_acs"

    def read(name: str) -> str:
        return (d / name).read_text(encoding="utf-8")

    counties = parse_acs(read("county.json"), ("state", "county"), "ACS county")
    states = parse_acs(read("state.json"), ("state",), "ACS state")
    places: dict[str, dict] = {}
    for fips in STATES:
        places.update(parse_acs(read(f"place/{fips}.json"), ("state", "place"),
                                f"ACS place {fips}", state=fips))
    check_control_totals(counties, states)
    for geoid, rec in {**counties, **places}.items():            # value-domain gate
        survey_fields(rec, geoid)
    return counties, places, states


def load_gazetteer(raw: Path) -> tuple[dict, dict]:
    d = raw / "census_gazetteer"
    return tuple(parse_gazetteer((d / f"{level}.txt").read_text(encoding="utf-8"), level)
                 for level in ("county", "place"))                    # type: ignore[return-value]
