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
  moneyPending:
    "Financial disclosures (STOCK Act trades, net worth ranges, campaign finance) are added to every profile as the money pipeline comes online. The same sections, sourced the same way, for every official.",

  // Legislative surfaces
  legislativePending:
    "Vote-by-vote records and sponsorship history are being synced from congress.gov. They appear here for every member as the sync lands.",
  ideologyPendingInsufficientVotes:
    "Not enough recorded votes yet this Congress to estimate a score.",

  // Provenance
  sourceLabel: "Source",
  retrievedLabel: "retrieved",
  provenanceTagline: "Every fact on this screen traces to an official source.",
} as const;
