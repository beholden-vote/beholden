/** Money & votes, side by side (WO-8) — DESCRIPTIVE JUXTAPOSITION ONLY.
 *
 *  This module places two INDEPENDENTLY-SOURCED, already-provenanced facts next
 *  to each other:
 *    LEFT  — the member's top contributors (FEC employer rollups, from WO-3's
 *            money.campaign_finance.top_contributors).
 *    RIGHT — the member's key votes (roll-call record, from WO-1's
 *            legislative.key_votes), each optionally carrying congress.gov's own
 *            policy-area chip on the decided bill.
 *
 *  IT ASSERTS NO LINK BETWEEN THEM. There is no sorting, pairing, or highlighting
 *  that ties a specific donor to a specific vote — the two columns are rendered in
 *  their source order (contributors by FEC-reported total; votes by the key-vote
 *  salience formula) and never cross-referenced. The policy-area chip is the only
 *  "relatedness" shown, and it is congress.gov's taxonomy on the bill, NOT a
 *  connection Beholden draws. The verbatim non-causation caveat (STRINGS
 *  .moneyVotesCaveat) renders on every instance — the same pattern as WO-4's
 *  shared-donor caveat.
 *
 *  Symmetric by construction (DESIGN Rule 0): identical layout and behavior for
 *  every member, regardless of party. If either side lacks data the module does
 *  not render at all (absent is not an implied blank) — the parent gates on that.
 */
import type { Dossier } from "../types";
import { STRINGS } from "../strings";
import { formatDate, formatMoneyCents } from "../lib/data";
import { methodologyHash } from "../router";

type KeyVote = NonNullable<Dossier["legislative"]>["key_votes"][number];
type Contributor = NonNullable<
  NonNullable<Dossier["money"]>["campaign_finance"]
>["top_contributors"];

/** True when BOTH sides carry real data — the only condition under which the
 *  module renders (absent ≠ implied). Kept here so DossierView can gate mounting
 *  without duplicating the rule. */
export function hasMoneyVotes(dossier: Dossier): boolean {
  const contribs = dossier.money?.campaign_finance?.top_contributors;
  const votes = dossier.legislative?.key_votes;
  return !!contribs && contribs.length > 0 && !!votes && votes.length > 0;
}

/** One key-vote row on the RIGHT column: position, question, date, and — when the
 *  decided bill carries congress.gov policy areas — descriptive chip(s). No donor
 *  is referenced here; the chip is the bill's own classification only. */
function VoteRow({ v }: { v: KeyVote }) {
  return (
    <li className="mv-vote">
      <div className="mv-vote-top">
        <span className={`vote vote-${v.position}`}>{v.position}</span>
        <span className="mv-vote-q">{v.question}</span>
      </div>
      <div className="mv-vote-meta">
        {v.policy_areas && v.policy_areas.length > 0 && (
          <span className="mv-policy-chips">
            {v.policy_areas.map((pa) => (
              <span className="mv-policy-chip" key={pa}>{pa}</span>
            ))}
          </span>
        )}
        <span className="mv-vote-date">{formatDate(v.held_at)}</span>
      </div>
    </li>
  );
}

/** One contributor row on the LEFT column: FEC-reported employer + total. Order
 *  is the FEC-reported ranking, untouched — never re-sorted to face any vote. */
function ContributorRow({ name, total_cents }: { name: string; total_cents: number }) {
  return (
    <li className="mv-donor">
      <span className="mv-donor-name">{name}</span>
      <span className="mv-donor-amt mono">{formatMoneyCents(total_cents)}</span>
    </li>
  );
}

export function MoneyVotes({ dossier }: { dossier: Dossier }) {
  // Gate: render only when both sides exist. Defensive even though DossierView
  // also checks — the module must never render a one-sided (implying) view.
  if (!hasMoneyVotes(dossier)) return null;
  const contributors = dossier.money!.campaign_finance!.top_contributors as NonNullable<Contributor>;
  const votes = dossier.legislative!.key_votes;

  return (
    <section className="panel-section mv">
      <div className="section-head">
        <h3>{STRINGS.moneyVotesTitle}</h3>
        {/* "How is this computed?" → the public methodology page. Both metrics
            behind this module (donor rollups + key-vote selection) are documented
            there; the money and votes provenance envelopes' methodology_id fields
            point at the same anchors. */}
        <a className="source-tag" href={methodologyHash("donor-rollups")}>
          {STRINGS.moneyVotesMethodLink}
        </a>
      </div>
      <p className="mv-lede muted">{STRINGS.moneyVotesLede}</p>

      <div className="mv-cols">
        <div className="mv-col">
          <h4>{STRINGS.moneyVotesContributorsHead}</h4>
          <ul className="mv-list">
            {contributors.map((c) => (
              <ContributorRow key={c.name} name={c.name} total_cents={c.total_cents} />
            ))}
          </ul>
        </div>
        <div className="mv-col">
          <h4>{STRINGS.moneyVotesVotesHead}</h4>
          <ul className="mv-list">
            {votes.map((v) => (
              <VoteRow key={v.roll_call_id} v={v} />
            ))}
          </ul>
          <p className="mv-policy-note muted">{STRINGS.moneyVotesPolicyNote}</p>
        </div>
      </div>

      {/* The verbatim non-causation caveat — rendered on every instance, styled
          like the WO-4 correlation caveat (amber left-rule). This is the entire
          point of the module: honesty that adjacency is not a claim. */}
      <p className="mv-caveat">{STRINGS.moneyVotesCaveat}</p>
    </section>
  );
}

export default MoneyVotes;
