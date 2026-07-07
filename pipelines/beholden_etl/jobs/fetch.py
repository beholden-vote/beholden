"""Stage 1 — land raw snapshots (immutable) into dist/raw/{source}/.

Pulls the federal legislative slice plus the state / money / disclosure sources.
Writes a manifest.json recording, per source, the retrieved_at + source_url that
transform/build stamp into provenance envelopes, and (WO-10) each source's
**status, item count, and wall-time**.

Raw is write-once per run: transform reads only from here, never the network, so
a published fact is always reproducible from the lake (contracts §7).

WO-10 — resilient · incremental · parallel:
  * **Hydrate** dist/raw from R2 `raw/latest/…` at the start so an interrupted /
    re-dispatched run resumes from the last-good lake instead of re-crawling.
  * **Incremental:** a source whose hydrated snapshot is still within its
    `config.SOURCES[key].freshness_sla_hours` is kept verbatim (carrying its
    ORIGINAL retrieved_at — never restamped) rather than re-fetched. `full=True`
    (the `--full` dispatch input) bypasses this and re-fetches everything.
  * **Parallel:** congress.gov (5k/hr) and FEC (1k/hr) are separate services with
    independent rate limits, so their loops — and the other bulk pulls — run
    concurrently in a thread pool. Each source keeps its own in-client governor,
    so wall-clock ≈ max(loops), not sum, without exceeding any cap.
  * **Parallel, nested:** within `fetch_openstates`, the 52 state/territory CSV
    pulls are themselves independent, unauthenticated GETs against a static host
    with no documented rate limit, so they fan out across their own small thread
    pool rather than one source-level thread walking 52 states serially. Same
    idea within `fetch_congress_gov`'s ~537-member loop, sharing one client
    whose throttle is now lock-protected (congress_gov.CongressGovClient) so
    concurrent callers still respect the one hourly cap — the loop was actually
    bottlenecked on congress.gov's per-request latency, not the rate ceiling.
  * **Fail-closed preserved:** on a transient per-item failure we fall back to that
    item's last-good hydrated snapshot (correct, slightly stale) rather than
    dropping it. We only hard-fail when there is no prior snapshot AND absence
    would fabricate a value (legislation counts ⇒ a false "sponsored 0"). Where
    absence is honest (FEC ⇒ no money section), a missing item stays absent.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .. import rawlake
from ..config import CONGRESS, FEC_CYCLE, RAW_DIST, STATE_VOTES_SLUGS, WA_PDC_ENABLED
from ..sources import congress_gov, fec, house_clerk, legislators, openstates, voteview
from ..sources import openstates_votes                           # WO-17 (state votes/bills)
from ..sources import wa_pdc                                     # WO-9 (trusted extraction)
from ..sources import wikidata                                   # WO-15 (education)

LEGISLATORS_URL = legislators.URL
VOTEVIEW_URL = voteview.members_url(CONGRESS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")))


# ---------------------------------------------------------------------------
# Per-source fetch functions. Each returns the manifest fragment for its source
# key; each is self-contained (builds its own client, so its rate governor is
# private to the calling thread) and prints its own progress. `prior` is the
# hydrated last-good manifest; `raw` is the (already-hydrated) lake root.
# ---------------------------------------------------------------------------
def fetch_unitedstates_legislators(raw: Path, prior: dict) -> dict:
    """Identity crosswalk + committee roster/memberships (bulk YAML, one source
    family under the unitedstates_legislators envelope). WO-15 adds district
    offices + social-media handles — same repo, same GitHub Pages mirror, so
    both land under this one envelope rather than a new source key."""
    legs = legislators.fetch_current()
    _write_json(raw / "unitedstates_legislators" / "legislators-current.json", legs)
    committees = legislators.fetch_committees()
    membership = legislators.fetch_committee_membership()
    _write_json(raw / "unitedstates_legislators" / "committees-current.json", committees)
    _write_json(raw / "unitedstates_legislators" / "committee-membership-current.json", membership)
    district_offices = legislators.fetch_district_offices()
    _write_json(raw / "unitedstates_legislators" / "legislators-district-offices.json", district_offices)
    social_media = legislators.fetch_social_media()
    _write_json(raw / "unitedstates_legislators" / "legislators-social-media.json", social_media)
    return {
        "retrieved_at": _now(), "source_url": LEGISLATORS_URL, "count": len(legs),
        "committees": len(committees),
        "committee_memberships": sum(len(v or []) for v in membership.values()),
        "district_offices": sum(len(r.get("offices") or []) for r in district_offices),
        "social_media": len(social_media)}


_CONGRESS_MEMBER_WORKERS = 8


def _fetch_one_member(client, raw: Path, leg_dir: Path, detail_dir: Path, bio: str) -> dict:
    """One member's legislation + member-detail calls, on the shared, now
    thread-safe-throttled client (congress_gov.CongressGovClient._throttle
    holds a lock, so concurrent callers still respect the one hourly cap —
    this buys overlap on congress.gov's per-request latency, not a higher
    dispatch rate). Returns counters for the caller to accumulate; a fail-
    closed legislation failure with no prior snapshot raises through, same
    as the old serial loop."""
    reused = 0
    rel = Path("congress.gov") / "legislation" / f"{bio}.json"
    try:
        _write_json(leg_dir / f"{bio}.json", {
            "bioguide": bio,
            "sponsored": client.sponsored_legislation(bio),
            "cosponsored_count": client.cosponsored_count(bio)})
    except Exception as e:
        # Transient per-item failure. Absence here fabricates (a missing
        # legislation file ⇒ counts 0). Fall back to the last-good snapshot if
        # the lake has one (correct, slightly stale); otherwise fail closed.
        snap = rawlake.last_good(raw, rel)
        if snap is None:
            raise
        _write_json(leg_dir / f"{bio}.json", snap)   # keep the last-good file
        reused = 1
        print(f"fetch: congress.gov {bio} reused last-good snapshot ({type(e).__name__})")

    detail_ok = 0
    detail_rel = Path("congress.gov") / "member-detail" / f"{bio}.json"
    try:
        _write_json(detail_dir / f"{bio}.json", client.member_detail(bio))
        detail_ok = 1
    except Exception as e:
        # Honest-absent: contact/bio extras only, never a fabricated
        # legislative count. Fall back to a last-good snapshot if one
        # exists; otherwise the member simply has no member-detail file
        # this run (build.py treats that as honest absence).
        snap = rawlake.last_good(raw, detail_rel)
        if snap is not None:
            _write_json(detail_dir / f"{bio}.json", snap)
            detail_ok = 1
        print(f"fetch: congress.gov member-detail {bio} skipped ({type(e).__name__})")
    return {"reused": reused, "detail_ok": detail_ok}


def fetch_congress_gov(raw: Path, prior: dict) -> dict:
    """Current membership + per-member sponsored/cosponsored legislation, PLUS
    (WO-15) member-detail (birthYear/partyHistory/leadership/DC office) — one
    extra call per member on the SAME client/rate governor. The long pole;
    runs concurrently with FEC, and fans its own ~537 members across a thread
    pool sharing one client — congress.gov's per-request latency (not the
    hourly cap) was the actual bottleneck, so overlapping in-flight requests
    cuts wall time without exceeding the rate governor (now lock-protected;
    see congress_gov.CongressGovClient._throttle). FAIL-CLOSED for legislation:
    a per-member failure does NOT skip — a dropped member would publish a false
    'sponsored 0'. Instead we fall back to that member's last-good hydrated
    snapshot; only when there is no prior snapshot does the exception propagate
    and sink the run (never fabricate). Member-detail is HONEST-ABSENT instead:
    a failure there costs only contact/bio extras, never a fabricated
    legislative count, so it degrades to the last-good snapshot or simply
    stays absent."""
    client = congress_gov.CongressGovClient()
    members = list(client.current_members(CONGRESS))
    _write_json(raw / "congress.gov" / f"members-{CONGRESS}.json", members)

    leg_dir = raw / "congress.gov" / "legislation"
    detail_dir = raw / "congress.gov" / "member-detail"
    bioguides = [m["bioguideId"] for m in members if m.get("bioguideId")]
    reused = 0
    detail_count = 0
    done = 0
    with ThreadPoolExecutor(max_workers=_CONGRESS_MEMBER_WORKERS) as pool:
        futures = {pool.submit(_fetch_one_member, client, raw, leg_dir, detail_dir, bio): bio
                   for bio in bioguides}
        for fut in as_completed(futures):
            result = fut.result()   # re-raises a fail-closed legislation exception, sinking the run
            reused += result["reused"]
            detail_count += result["detail_ok"]
            done += 1
            if done % 100 == 0 or done == len(bioguides):
                print(f"fetch: legislation {done}/{len(bioguides)} members")

    meta = {
        "retrieved_at": _now(),
        "source_url": f"https://www.congress.gov/members?q=%7B%22congress%22%3A{CONGRESS}%7D",
        "count": len(members), "legislation_members": len(bioguides),
        "member_detail": detail_count}
    if reused:
        meta["legislation_reused"] = reused
    return meta


def fetch_voteview(raw: Path, prior: dict) -> dict:
    """DW-NOMINATE member scores + roll-call metadata + per-member vote casts
    (static CSV bulk pulls)."""
    csv_text = voteview.member_scores_csv(CONGRESS)
    (raw / "voteview").mkdir(parents=True, exist_ok=True)
    # Explicit UTF-8: bionames carry accents; platform-default cp1252 would corrupt.
    (raw / "voteview" / f"HS{CONGRESS}_members.csv").write_text(csv_text, encoding="utf-8")
    rollcalls_text = voteview.rollcalls_csv(CONGRESS)
    (raw / "voteview" / f"HS{CONGRESS}_rollcalls.csv").write_text(rollcalls_text, encoding="utf-8")
    votes_text = voteview.votes_csv(CONGRESS)   # the ~9 MB long pole
    (raw / "voteview" / f"HS{CONGRESS}_votes.csv").write_text(votes_text, encoding="utf-8")
    return {
        "retrieved_at": _now(), "source_url": VOTEVIEW_URL,
        "count": max(csv_text.count("\n") - 1, 0),
        "rollcalls": max(rollcalls_text.count("\n") - 1, 0),
        "votes": max(votes_text.count("\n") - 1, 0)}


def fetch_fec(raw: Path, prior: dict) -> dict:
    """FEC candidate cycle totals + itemized contributor rollups (E3 + WO-3). The
    run's other long pole; runs concurrently with congress.gov. A per-candidate
    failure skips rather than sinking the federal slice — FEC absence is HONEST
    (no money section, never a fabricated $0), so no last-good fallback is needed.
    Progress prints every 50 so a stall is visible live (PYTHONUNBUFFERED)."""
    # The legislators snapshot lands from its own task (which is run to completion
    # before the pool starts) or from the hydrated lake — read it once available.
    legs = _read_legislators(raw)
    fec_client = fec.FECClient()
    fec_dir = raw / "fec" / "totals"
    contrib_dir = raw / "fec" / "contributors"
    # One FEC candidate id per legislator (deduped).
    fec_cands: list[str] = []
    seen_cand: set[str] = set()
    for leg in legs:
        fec_ids = (leg.get("id") or {}).get("fec") or []
        cand = fec_ids[0] if fec_ids else None
        if cand and cand not in seen_cand:
            seen_cand.add(cand)
            fec_cands.append(cand)
    for i, cand in enumerate(fec_cands, 1):
        try:
            totals = fec_client.candidate_totals(cand, FEC_CYCLE)
            if totals:
                _write_json(fec_dir / f"{cand}.json",
                            {"candidate_id": cand, "cycle": FEC_CYCLE, "totals": totals})
            committee_id = fec_client.principal_committee(cand, FEC_CYCLE)
            if committee_id:
                by_employer = fec_client.top_contributors_by_employer(committee_id, FEC_CYCLE)
                _write_json(contrib_dir / f"{cand}.json",
                            {"candidate_id": cand, "cycle": FEC_CYCLE,
                             "committee_id": committee_id, "by_employer": by_employer})
        except Exception as e:                     # one candidate must not sink the run
            print(f"fetch: fec {cand} skipped ({type(e).__name__})")
        if i % 50 == 0 or i == len(fec_cands):
            print(f"fetch: fec {i}/{len(fec_cands)} candidates")
    fec_count = len(list(fec_dir.glob("*.json"))) if fec_dir.exists() else 0
    contrib_count = len(list(contrib_dir.glob("*.json"))) if contrib_dir.exists() else 0
    return {
        "retrieved_at": _now(),
        "source_url": f"https://www.fec.gov/data/candidates/?cycle={FEC_CYCLE}",
        "count": fec_count, "contributors": contrib_count}


_OPENSTATES_WORKERS = 10


def _fetch_one_state(state: str) -> tuple[str, str | None]:
    try:
        return state, openstates.fetch_people_csv(state)
    except Exception as e:  # a single state hiccup shouldn't sink the run
        print(f"fetch: openstates {state} skipped ({type(e).__name__})")
        return state, None


def _fetch_one_state_votes(client, raw: Path, state: str) -> tuple[str, dict | None]:
    """WO-17: one state's incremental bills+votes crawl on the shared,
    thread-safe-throttled v3 client. Reads the prior lake snapshot for the
    since-cursor, merges the delta, writes the state file back. A per-state
    failure skips WITHOUT touching the hydrated prior file — that state keeps
    its last-good snapshot (correct, slightly stale) or stays honestly absent;
    either way nothing is fabricated and the run continues. Schema drift
    (SchemaDriftError) raises through: a half-parsed state must halt, not ship."""
    rel = Path("openstates") / "votes" / f"{state}.json"
    try:
        prior_doc = rawlake.last_good(raw, rel)
        doc = openstates_votes.crawl_state(
            client, state, openstates_votes.biennium_start(CONGRESS), prior_doc)
        _write_json(raw / rel, doc)
        return state, doc
    except openstates_votes.SchemaDriftError:
        raise                                     # fail closed — never swallowed
    except Exception as e:
        print(f"fetch: openstates votes {state} skipped ({type(e).__name__})")
        return state, None


def fetch_openstates(raw: Path, prior: dict) -> dict:
    """State legislators, bulk CSV per state (E4), PLUS (WO-17) state bills +
    roll-call votes for the STATE_VOTES_SLUGS pilot via the keyed v3 API —
    one source family, one manifest row, one SLA. The 52 people CSVs are
    independent, unauthenticated GETs against a static host with no documented
    rate limit (openstates.py), so they fan out across a small thread pool —
    wall time is bounded by the slowest state, not the sum of all 52. A single
    state hiccup skips — state coverage is honest-absent, not fabricated.

    The votes crawl fans its pilot states across a second pool sharing ONE
    v3 client whose throttle is lock-protected (openstates_votes.
    OpenStatesVotesClient), so concurrency overlaps request latency without
    exceeding the API cap. Without OPENSTATES_KEY the votes crawl is skipped
    entirely (every pilot state stays honest-absent — identity-only dossiers,
    exactly like today); the people crawl still lands either way."""
    os_dir = raw / "openstates" / "people"
    os_count = 0
    with ThreadPoolExecutor(max_workers=_OPENSTATES_WORKERS) as pool:
        for state, csv_text in pool.map(_fetch_one_state, openstates.STATE_SLUGS):
            if csv_text is None:
                continue
            os_dir.mkdir(parents=True, exist_ok=True)
            (os_dir / f"{state}.csv").write_text(csv_text, encoding="utf-8")
            os_count += max(csv_text.count("\n") - 1, 0)
    meta = {"retrieved_at": _now(), "source_url": "https://openstates.org/", "count": os_count}

    # --- WO-17: state bills + votes (v3 API, incremental per-state crawl) ---
    if STATE_VOTES_SLUGS and openstates_votes.api_key_available():
        client = openstates_votes.OpenStatesVotesClient()
        votes_states, votes_bills, votes_fetched = [], 0, 0
        with ThreadPoolExecutor(max_workers=min(4, len(STATE_VOTES_SLUGS))) as pool:
            futures = [pool.submit(_fetch_one_state_votes, client, raw, s)
                       for s in STATE_VOTES_SLUGS]
            for fut in as_completed(futures):
                state, doc = fut.result()   # re-raises SchemaDriftError (fail closed)
                if doc is None:
                    continue
                votes_states.append(state)
                votes_bills += len(doc.get("bills") or {})
                votes_fetched += doc.get("fetched", 0)
        meta["votes_states"] = sorted(votes_states)
        meta["votes_bills"] = votes_bills
        meta["votes_fetched"] = votes_fetched
    elif STATE_VOTES_SLUGS:
        print("fetch: openstates votes skipped (OPENSTATES_KEY not set) — "
              "pilot states stay honest-absent")
    return meta


def fetch_house_clerk(raw: Path, prior: dict) -> dict:
    """House Clerk STOCK Act Periodic Transaction Reports (per-year index). A
    per-year hiccup skips — disclosure absence is honest (no filings surfaced)."""
    hc_filings: list[dict] = []
    for yr in (2024, 2025, 2026):   # the current term, plus late-prior-year trades
        try:
            hc_filings.extend(house_clerk.ptr_filings(yr))
        except Exception as e:
            print(f"fetch: house_clerk {yr} skipped ({type(e).__name__})")
    _write_json(raw / "house_clerk" / "ptr.json", hc_filings)
    return {"retrieved_at": _now(), "source_url": house_clerk.DISCLOSURE_URL,
            "count": len(hc_filings)}


def fetch_wa_pdc(raw: Path, prior: dict) -> dict | None:
    """WA PDC bulk disclosure (WO-9, Tier A). Gated OFF via config.WA_PDC_ENABLED
    until the itemized↔summary reconciliation is fixed; when off, returns None and
    the source is absent from the manifest (unchanged behavior). A network hiccup
    skips the source for this run rather than sinking the federal slice."""
    if not WA_PDC_ENABLED:
        return None
    try:
        wa_items = wa_pdc.fetch_itemized()
        wa_summary = wa_pdc.fetch_summary()
        wa_bytes = wa_pdc.snapshot_bytes(wa_items)
        wa_sha = wa_pdc.sha256(wa_bytes)
        wa_retrieved = _now()
        _write_json(raw / "wa_pdc" / "itemized.json", wa_items)
        _write_json(raw / "wa_pdc" / "summary.json", wa_summary)
        _write_json(raw / "wa_pdc" / "manifest.json", {
            "file_sha256": wa_sha, "retrieved_at": wa_retrieved,
            "header": list(wa_pdc.CONTRACT.header),
            "contract_version": wa_pdc.CONTRACT.contract_version,
            "window": f"election_year>={wa_pdc.PILOT_MIN_ELECTION_YEAR}",
            "itemized_count": len(wa_items), "summary_count": len(wa_summary)})
        return {"retrieved_at": wa_retrieved,
                "source_url": wa_pdc.CONTRACT.retrieval["itemized_json"],
                "count": len(wa_items), "file_sha256": wa_sha}
    except Exception as e:
        print(f"fetch: wa_pdc skipped ({type(e).__name__})")
        return None


def fetch_wikidata(raw: Path, prior: dict) -> dict:
    """Education (P69 + P512/P582 qualifiers) for every person with a stored
    `wikidata_qid` (WO-15). A per-person entity-fetch failure skips that person
    (education absence is honest — never sinks the federal slice); label
    resolution is batched across every referenced item id in as few
    wbgetentities calls as possible."""
    legs = _read_legislators(raw)
    qids = sorted({q for leg in legs if (q := (leg.get("id") or {}).get("wikidata"))})

    claims_dir = raw / "wikidata" / "claims"
    ok, skipped = 0, 0
    all_item_ids: set[str] = set()
    per_person_claims: dict[str, list[dict]] = {}
    for i, qid in enumerate(qids, 1):
        try:
            entity = wikidata.fetch_entity(qid)
            claims = wikidata.educated_at_claims(entity, qid)
        except Exception as e:   # a single person's entity fetch must not sink the run
            print(f"fetch: wikidata {qid} skipped ({type(e).__name__})")
            skipped += 1
            continue
        per_person_claims[qid] = claims
        for c in claims:
            all_item_ids.add(c["institution_qid"])
            if c.get("degree_qid"):
                all_item_ids.add(c["degree_qid"])
        ok += 1
        if i % 100 == 0 or i == len(qids):
            print(f"fetch: wikidata {i}/{len(qids)} persons")
    _write_json(claims_dir / "educated_at.json", per_person_claims)

    # Batch every referenced institution/degree id across ALL persons into as
    # few wbgetentities calls as possible (chunked at Wikidata's documented cap).
    labels = wikidata.resolve_labels(all_item_ids)
    _write_json(raw / "wikidata" / "labels.json", labels)

    return {"retrieved_at": _now(), "source_url": f"{wikidata.BASE}/wiki/Wikidata:Main_Page",
            "count": ok, "skipped": skipped, "labels": len(labels)}


def _read_legislators(raw: Path) -> list[dict]:
    """The landed crosswalk, needed by the FEC task to enumerate candidate ids.
    The lead source lands it before the pool starts and it also survives in the
    hydrated lake, so this is normally a direct read; the short wait only guards a
    reorder if the lead is ever moved into the pool."""
    path = raw / "unitedstates_legislators" / "legislators-current.json"
    for _ in range(600):                 # up to ~60s; legislators is a fast bulk pull
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(0.1)
    raise RuntimeError("fetch: legislators snapshot never landed for FEC candidate enumeration")


# Registry: source keys in run order. unitedstates_legislators must resolve before
# FEC (FEC reads its snapshot), so it is the serial lead; congress.gov and FEC are
# the long poles, fanned out in parallel with the remaining bulk pulls.
_LEAD = "unitedstates_legislators"
_FETCHERS = {
    "unitedstates_legislators": fetch_unitedstates_legislators,
    "congress.gov": fetch_congress_gov,
    "voteview": fetch_voteview,
    "fec": fetch_fec,
    "openstates": fetch_openstates,
    "house_clerk": fetch_house_clerk,
    "wa_pdc": fetch_wa_pdc,
    "wikidata": fetch_wikidata,      # WO-15: education, needs the legislators snapshot
}
# Manifest source-key -> the config.SOURCES key whose SLA governs its freshness.
# wa_pdc has no config.SOURCES entry (experimental, gated off); it is never
# freshness-skipped and always runs its (no-op-when-disabled) fetcher.
_SLA_KEY = {"wa_pdc": None}


def _run_source(key: str, raw: Path, prior: dict, full: bool) -> tuple[str, dict | None, str, float]:
    """Execute one source, returning (key, manifest_fragment|None, status, seconds).
    Honors the freshness gate: a fresh hydrated snapshot is kept verbatim (status
    'fresh', carrying its ORIGINAL retrieved_at) unless `full`. Never restamps
    reused data as freshly fetched."""
    started = time.monotonic()
    sla_key = _SLA_KEY.get(key, key)
    # Incremental skip: a hydrated snapshot still within its SLA is reused as-is.
    if not full and sla_key is not None and rawlake.source_is_fresh(prior, sla_key):
        frag = dict(rawlake.prior_source(prior, sla_key) or {})   # ORIGINAL retrieved_at
        return key, frag, "fresh", time.monotonic() - started
    frag = _FETCHERS[key](raw, prior)
    status = "fetched" if frag is not None else "absent"
    return key, frag, status, time.monotonic() - started


def run(raw_dir: str | Path = RAW_DIST, *, full: bool = False,
        max_workers: int = 4) -> dict:
    """Fetch every source into `raw_dir` and write manifest.json.

    full=True re-fetches everything (the `--full` / full_rebuild dispatch input),
    bypassing hydration + freshness. Otherwise the lake is hydrated from R2
    `raw/latest/…` and each source re-fetches only when its snapshot is stale.
    """
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)

    if full:
        print("fetch: full rebuild — bypassing hydration + freshness")
        prior: dict = {}
    else:
        rawlake.hydrate(raw)
        prior = rawlake.hydrated_manifest(raw)

    manifest: dict = {"generated_at": _now(), "congress": CONGRESS, "sources": {}}
    timings: dict = {}

    # unitedstates_legislators is a hard predecessor of FEC (FEC enumerates
    # candidates from its snapshot). Run it to completion first so its snapshot is
    # present, then fan the rest — including the two long poles congress.gov + FEC
    # — out in parallel. Each source's own in-client rate governor keeps it under
    # its cap; the pool only overlaps INDEPENDENT services, so no cap is exceeded.
    key, frag, status, secs = _run_source(_LEAD, raw, prior, full)
    if frag is not None:
        manifest["sources"][key] = frag
    timings[key] = {"status": status, "seconds": round(secs, 1)}

    rest = [k for k in _FETCHERS if k != _LEAD]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_source, k, raw, prior, full): k for k in rest}
        for fut in as_completed(futures):
            key, frag, status, secs = fut.result()
            if frag is not None:
                manifest["sources"][key] = frag
            timings[key] = {"status": status, "seconds": round(secs, 1)}

    manifest["fetch_timings"] = timings
    _write_json(raw / "manifest.json", manifest)
    for src, meta in manifest["sources"].items():
        t = timings.get(src, {})
        print(f"fetch: {src:28} {meta['count']:>7} records  "
              f"[{t.get('status', '?'):7} {t.get('seconds', 0):>6.1f}s]")
    return manifest


if __name__ == "__main__":
    import sys

    run(full="--full" in sys.argv[1:])
