/** THE approved string table (CONTRIBUTING: copy touching money or legal-adjacent
 *  surfaces comes from here only — never composed inline). Reviewed strings only;
 *  every entry applies identically to every official (symmetric by construction). */

export const STRINGS = {
  // Money / legal-adjacent surfaces
  netWorthTitle: "Estimated net worth",
  netWorthNote:
    "Disclosed as a range — federal filings report brackets, not exact values.",
  tradesTitle: "STOCK Act trades",
  tradesLateFlag: "filed late",
  tradesLateNote:
    "The STOCK Act requires disclosure within 45 days of a transaction.",
  campaignFinanceTitle: "Campaign finance",
  campaignFinanceNote: "Itemized totals as reported to the FEC.",
  disclosuresTitle: "Stock-trade disclosures",
  disclosuresNote:
    "Periodic Transaction Reports filed with the House Clerk. Each links to the official filing — the itemized trades are inside the document.",
  moneyPending:
    "Financial disclosures (STOCK Act trades, net worth ranges, campaign finance) are added to every profile as the money pipeline comes online. The same sections, sourced the same way, for every official.",

  // Legislative surfaces
  legislativePending:
    "Vote-by-vote records and sponsorship history are being synced from congress.gov. They appear here for every member as the sync lands.",
  stateLegPending:
    "Ideology scores, voting records, and campaign finance for state legislators are being added. Identity, party, and district are sourced from OpenStates.",
  ideologyPendingInsufficientVotes:
    "Not enough recorded votes yet this Congress to estimate a score.",

  // Money & votes, side by side (WO-8) — DESCRIPTIVE JUXTAPOSITION ONLY. This
  // module places two independently-sourced facts next to each other; it makes
  // no claim of influence, coordination, or causation. The caveat is verbatim
  // and counsel-reviewable, and mirrors the WO-4 shared-donor caveat pattern.
  moneyVotesTitle: "Money & votes, side by side",
  moneyVotesLede:
    "Two public records, placed next to each other: who gave to this member's campaign, and how this member voted. Nothing here links a specific contribution to a specific vote.",
  moneyVotesContributorsHead: "Top contributors",
  moneyVotesVotesHead: "Key votes",
  // THE non-causation caveat — rendered verbatim, always, wherever this module
  // appears. Left side is as reported to the FEC; right side is the public
  // roll-call record; their adjacency asserts no relationship between them.
  moneyVotesCaveat:
    "Contributions are as reported to the FEC. Votes are the public roll-call record. These two records are shown side by side for reference only — their presentation implies no causal relationship between any contribution and any vote.",
  // Policy-area chips are congress.gov's own taxonomy on the bill, not our
  // inference — the note states that plainly so the chip is never read as a link.
  moneyVotesPolicyNote:
    "Policy-area labels are congress.gov's own classification of each bill, not a connection drawn by Beholden.",
  moneyVotesMethodLink: "How is this computed?",
  // Generic "how is this computed?" affordance linking a metric to its
  // /methodology anchor. Reused across ideology, key votes, and party agreement.
  methodologyLink: "How is this computed?",

  // Connections (entity graph, WO-4) — descriptive, symmetric copy only.
  connectionsTitle: "Connections",
  connectionsLoading: "Loading connections…",
  connectionsEmpty:
    "No connections published yet. Connections are computed from shared bills, votes, committees, and reported contributors — they appear as those records sync.",
  connectionsNote:
    "Each connection is computed from public records and links to its source. A shared connection describes overlap only — it implies no coordination.",
  connectionsEvidenceMore: "+{n} more, in the full record",

  // Provenance
  sourceLabel: "Source",
  retrievedLabel: "retrieved",
  provenanceTagline: "Every fact on this screen traces to an official source.",
} as const;
