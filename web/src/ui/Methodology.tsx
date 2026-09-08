/** Methodology page (WO-8) — the public, hash-anchored explainer every
 *  "how is this computed?" link points to.
 *
 *  Each section surfaces ONE computed metric's exact formula, transcribed from
 *  the pipeline code that produces the number so a reader can reproduce it. Every
 *  formula cites its source file in a comment; the anchors here are the SAME ids
 *  the dossier provenance envelopes carry in `methodology_id` (jobs/build.py
 *  METHODOLOGY_* constants) and the ideology `explainer_url`. Keep them in sync:
 *
 *    #dw-nominate    ideology score          (sources/voteview.py + Voteview)
 *    #key-votes      key-vote selection      (build/key_votes.py select_key_votes)
 *    #co-voting      party agreement math    (build/key_votes.py agreement_pct;
 *                                             build/graph.py co_voting_edges)
 *    #donor-rollups  FEC employer aggregates (sources/fec.py by_employer)
 *    #state-donor-rollups  WA PDC employer aggregates (jobs/build.py, WO-19)
 *    #shared-donors  graph shared-donor edge (build/graph.py shared_donor_edges)
 *    #sources        pointer to the Sources registry overlay
 *
 *  Rendered inside the existing info overlay (chrome.tsx InfoOverlay), so it
 *  reuses the .info-page shell and coexists with about/privacy/sources. Party-
 *  neutral throughout (DESIGN Rule 0): describes the same formula for everyone. */
import { useEffect, useRef } from "react";
import type { InfoPage } from "./chrome";

/** Sections of this page, in order — the id is the in-page anchor a dossier links
 *  to (e.g. #methodology/key-votes scrolls here). */
const SECTION_IDS = [
  "source-quality", "dw-nominate", "key-votes", "co-voting", "donor-rollups",
  "state-donor-rollups", "shared-donors", "sources",
] as const;

export function Methodology({ anchor, onOpenInfo }: {
  /** Optional in-page section to scroll to on open (from #methodology/<anchor>). */
  anchor?: string | null;
  /** Cross-link to another info overlay (used by #sources → the Sources registry). */
  onOpenInfo?: (p: InfoPage) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  // Scroll the requested section into view once mounted. Guarded to a known id so
  // a bad anchor is a no-op (never throws), and it runs after paint.
  useEffect(() => {
    if (!anchor || !(SECTION_IDS as readonly string[]).includes(anchor)) return;
    const el = rootRef.current?.querySelector(`#${CSS.escape(anchor)}`);
    el?.scrollIntoView({ block: "start", behavior: "auto" });
  }, [anchor]);

  return (
    <div ref={rootRef}>
      <h1>Methodology</h1>
      <p className="lede">
        Every number Beholden computes is produced by a fixed formula from official
        data — no hand-picking, no per-member or per-party tuning. Each formula below
        is transcribed from the code that ships it, so any published figure is
        reproducible from the public record.
      </p>

      {/* ---- WO-28 credibility grades ---- */}
      <h2 id="source-quality">Source quality grades</h2>
      <p>
        Records differ in how they reach us. A congressional roll call arrives as a
        bulk data feed; a county commission's roll call may only exist inside a PDF
        of the meeting minutes. Both are official, but we should not present them as
        if we obtained them the same way — so every fact carries a grade describing
        how it was obtained.
      </p>
      <dl className="kv">
        <dt>A</dt>
        <dd>
          Official structured source — a bulk data feed, API, or a direct link to an
          official filing. Read deterministically, with no model in the path.
        </dd>
        <dt>B</dt>
        <dd>
          Official document with machine-readable text. Parsed by fixed rules and
          checked against a total the document itself states.
        </dd>
        <dt>C</dt>
        <dd>
          Official document whose text we recovered by OCR, then verified against the
          document and reconciled against its own stated totals.
        </dd>
        <dt>D</dt>
        <dd>
          Derived or inferred — the fact is our reasoning over official records rather
          than a transcription of them, such as a district boundary assembled from
          precinct data, or a member's position taken from a vote the minutes record
          only as unanimous.
        </dd>
      </dl>
      <p>
        <strong>A grade describes our method, never the official.</strong> A low grade
        means the record was harder for us to read — it is not a finding about the
        person, the office, or the locality. Records held to a lower standard are
        never presented as equivalent to bulk official data, and equally, a county
        that publishes scanned minutes is not thereby less legitimate than one that
        publishes a data feed.
      </p>
      <p>
        Grades are also not a way to publish doubtful numbers. Data that fails a
        quality check — itemized amounts that do not sum to the total on the filing,
        a vote whose named tally does not match its own count — is withheld entirely
        and shown as an absence. It is never downgraded and published anyway. The
        scale reflects how a record was obtained; correctness is not on the scale.
      </p>
      <p>
        You can hide grades below a threshold under Layers · Source quality. The
        default shows everything, and a hidden section always says that it is hidden
        rather than quietly disappearing.
      </p>

      {/* ---- DW-NOMINATE ideology ---- */}
      <h2 id="dw-nominate">Ideology score (DW-NOMINATE)</h2>
      <p>
        The ideology dot is a member's first-dimension DW-NOMINATE coordinate,
        estimated by Voteview from that member's recorded roll-call votes this
        Congress. Beholden does not compute the score — it is republished verbatim
        from Voteview, joined to the member through the ICPSR identifier crosswalk.
      </p>
      <p>
        A score is withheld (shown as pending) below a minimum number of recorded
        votes, so a member with too thin a voting record never gets a
        falsely-precise position. Party and chamber medians shown for context are
        the median of the published scores in that group.
      </p>

      {/* ---- Key-vote selection ---- */}
      <h2 id="key-votes">Key-vote selection</h2>
      <p>
        A member's "key votes" are the ten most salient roll calls on which they
        cast a <em>yea</em> or <em>nay</em> (present / not-voting are excluded — the
        member took no side). Salience is fixed and identical for every member:
      </p>
      <pre className="method-formula mono">{`salience      = closeness + recency_bonus
closeness     = 1 − |yea − nay| / (yea + nay)     # 1.0 == a tie
recency_bonus = 0.25 × (rank / n)                 # newest vote → 0.25`}</pre>
      <p>
        The top ten by salience are kept; ties break on vote date (newer first)
        then roll-call id, so the selection is deterministic across runs. The
        displayed list is then re-sorted newest-first. This is exactly
        <span className="mono"> build/key_votes.py · select_key_votes</span>.
      </p>

      {/* ---- Party agreement + co-voting ---- */}
      <h2 id="co-voting">Party agreement &amp; co-voting</h2>
      <p>
        Party agreement is the share of a member's decided votes that match their
        own party's majority position on each roll call:
      </p>
      <pre className="method-formula mono">{`party_agreement_pct
  = 100 × (decided votes matching the member's party majority)
        / (decided votes where that party had a majority)`}</pre>
      <p>
        A roll call where the party splits evenly has no majority and doesn't count.
        The percentage is withheld below a minimum number of qualifying votes so a
        tiny denominator can't publish false precision
        (<span className="mono">build/key_votes.py · agreement_pct</span>).
      </p>
      <p>
        In the Connections graph, a "votes together" edge between two members uses
        the parallel formula — the share of shared decided roll calls on which both
        cast the same position — published only above a minimum shared-vote base
        (<span className="mono">build/graph.py · co_voting_edges</span>). Both are
        arithmetic on the public roll-call record.
      </p>

      {/* ---- Donor rollups ---- */}
      <h2 id="donor-rollups">Top contributors (FEC employer rollups)</h2>
      <p>
        "Top contributors" are the Federal Election Commission's <em>own</em>
        aggregation of itemized individual contributions to a member's principal
        campaign committee, grouped by the contributor's reported employer, for a
        cycle. Beholden requests them sorted by total descending and keeps the top
        ten (<span className="mono">sources/fec.py · top_contributors_by_employer</span>).
      </p>
      <p>
        Rank is the only field Beholden computes, by one fixed rule for every
        candidate. Employer strings are shown verbatim as filed — categories like
        <span className="mono"> RETIRED</span>, <span className="mono">NOT EMPLOYED</span>,
        or a blank employer are legitimate FEC values, kept as-is and never
        editorialized or filtered.
      </p>
      <p className="info-note">
        These are employer aggregates of individual donors — not a company's
        donation, not a PAC, and not a measure of influence. They describe who is
        reported to have given, and nothing more.
      </p>

      {/* ---- State donor rollups (WO-19) ---- */}
      <h2 id="state-donor-rollups">Top contributors (state disclosure rollups)</h2>
      <p>
        For state legislators whose campaign finance comes from a state disclosure
        agency (currently the Washington Public Disclosure Commission), "top
        contributors" are computed by Beholden with one fixed rule, applied
        identically to every filer regardless of party: itemized contributions
        that reconciled against the agency's own summary totals are grouped by the
        contributor's verbatim reported employer, summed, and ranked by total
        descending (<span className="mono">jobs/build.py · _wa_top_contributors</span>).
        Contributions filed without a reported employer are not part of the
        employer rollup.
      </p>
      <p>
        A state legislator's dossier carries this money section only where the
        campaign's filer record is linked to the legislator by an exact,
        human-reviewed identifier match — never by name matching. Unlinked
        campaigns stay unlinked; the same employer-aggregate caveats as the FEC
        rollups above apply.
      </p>

      {/* ---- Shared-donor graph edge ---- */}
      <h2 id="shared-donors">Shared top contributors (graph edge)</h2>
      <p>
        In the Connections graph, a "shared top contributors" edge between two
        members exists when the <em>same</em> contributor-employer string — the
        verbatim FEC rollup label, matched exactly, never fuzzily — appears in both
        members' top-contributor lists for the same cycle
        (<span className="mono">build/graph.py · shared_donor_edges</span>).
      </p>
      <p>
        This edge carries a fixed caveat wherever it appears:
      </p>
      <p className="method-caveat">
        shared top contributors are reported-employer aggregates; no coordination is
        implied
      </p>
      <p>
        The same honesty governs the dossier's "Money &amp; votes, side by side":
        contributions and votes are shown next to each other as two independent
        public records, and their adjacency implies no causal relationship.
      </p>

      {/* ---- Sources pointer ---- */}
      <h2 id="sources">Sources</h2>
      <p>
        Every figure above traces to an official source, listed with its freshness
        commitment in the source registry.{" "}
        {onOpenInfo ? (
          <button type="button" className="method-inline-link"
                  onClick={() => onOpenInfo("sources")}>
            Open the Sources registry ↗
          </button>
        ) : null}
      </p>
    </div>
  );
}

export default Methodology;
