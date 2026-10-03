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
  // WO-19: shown when the section's provenance source is wa_pdc — the state
  // counterpart of campaignFinanceNote, same section, same rendering rules.
  campaignFinanceNoteWaPdc:
    "Totals as reported to the Washington State Public Disclosure Commission. Top contributors are rollups of itemized contributions by reported employer.",
  disclosuresTitle: "Stock-trade disclosures",
  disclosuresNote:
    "Periodic Transaction Reports filed with the House Clerk. Each links to the official filing — the itemized trades are inside the document.",
  moneyPending:
    "Financial disclosures (STOCK Act trades, net worth ranges, campaign finance) are added to every profile as the money pipeline comes online. The same sections, sourced the same way, for every official.",

  // Legislative surfaces
  legislativePending:
    "Vote-by-vote records and sponsorship history are being synced from congress.gov. They appear here for every member as the sync lands.",
  // WO-22: local officials are NOT state legislators and their data does not
  // come from OpenStates. Showing them stateLegPending named a source that has
  // never heard of them — a false attribution on the one screen whose whole
  // promise is that every fact names where it came from.
  localPending:
    "Voting records and campaign finance are not published for local officials yet. Identity, office, and contact details come from this government's own published roster, linked above.",
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

  // Dossier tab labels (WO-11; WO-16 adds Social) — the same tabs, in the same
  // order, for every official; tabs without published data hide identically
  // for everyone.
  tabOverview: "Overview",
  tabRecord: "Record",
  tabCommittees: "Committees",
  tabMoney: "Money",
  tabConnections: "Connections",
  tabSocial: "Social",

  // Header action row (WO-16) — Call/Email/Contact/Website. Identical labels
  // and treatment regardless of party (Rule 0); each renders only when its own
  // contact field is published (absence stays invisible, never a dead button).
  actionCall: "Call",
  actionEmail: "Email",
  actionContactForm: "Contact",
  actionWebsite: "Website",

  // Overview additions (WO-16)
  previousRolesTitle: "Previous roles",
  birthYearLabel: "Born",
  educationTitle: "Education",
  // Wikidata is a crowd-edited source (not an official government filing) —
  // this verbatim note renders wherever education appears, styled with the
  // same always-visible weight as the money/votes non-causation caveat, never
  // a tooltip or collapsed aside (contract requirement, see WO-15/16).
  educationCredibilityFallback:
    "Sourced from Wikidata, a publicly edited encyclopedia — verify against the member's official biography.",

  // Social tab (WO-16) — link-out cards only, no embeds/iframes/third-party
  // widgets (privacy/zero-tracker requirement). Identical card treatment per
  // platform regardless of party.
  socialTitle: "Social",
  socialEmpty:
    "No social media accounts published yet for this official.",

  // Connections (entity graph, WO-4) — descriptive, symmetric copy only.
  connectionsTitle: "Connections",
  connectionsLoading: "Loading connections…",
  connectionsEmpty:
    "No connections published yet. Connections are computed from shared bills, votes, committees, and reported contributors — they appear as those records sync.",
  connectionsNote:
    "Each connection is computed from public records and links to its source. A shared connection describes overlap only — it implies no coordination.",
  connectionsEvidenceMore: "+{n} more, in the full record",
  // WO-13 interactive graph — the SVG is a decorative spatial lens; this note
  // tells assistive tech where the equivalent (cited) content lives.
  connectionsGraphNote:
    "Interactive connection chart. The list below contains the same {n} connections with evidence.",
  connectionsOpenDossier: "Open dossier →",

  // Provenance
  sourceLabel: "Source",
  retrievedLabel: { checked: "checked", unchanged: "unchanged since" },

  // Credibility grades (WO-28) — DESCRIPTIVE OF METHOD, NEVER OF THE OFFICIAL.
  // A grade says how Beholden obtained a fact, not how trustworthy the person
  // is. Copy is identical for every official and every locality (Rule 0); a
  // county whose records are scanned rather than exported must never read as
  // though its officials were less legitimate. A failed quality gate is NOT a
  // low grade — that data is withheld entirely and shows as an honest absence.
  gradeFilterTitle: "Source quality",
  // Kept short because it sits in the floating map dock. The full scale is on
  // /methodology#source-quality. The half that must never be cut is the second
  // clause: without it, a filter reads as a way to make problems disappear.
  gradeFilterHint:
    "Graded by how it was obtained. Records failing a quality check are withheld, never downgraded.",
  gradeLabels: {
    A: "Official structured source",
    B: "Official document, machine-readable text",
    C: "Official document, text recovered by OCR",
    D: "Derived or inferred from official records",
  } as Record<string, string>,
  // Filter options are phrased as THRESHOLDS ("and above"), because picking a
  // grade sets the weakest grade still shown — labelling them with the grade's
  // own name would read as "show only B".
  gradeFilterOptions: {
    A: "Bulk official data only",
    B: "Official documents and above",
    C: "Include scanned documents",
    D: "Show everything",
  } as Record<string, string>,
  gradeChipTitle: "Source quality grade",
  // Shown IN PLACE OF a hidden section — the reader is always told something
  // exists and why it is not rendered. A filtered dossier is never a silently
  // shorter one.
  gradeHiddenNote:
    "Hidden by your source-quality filter — adjust it under Layers · Source quality.",
  provenanceTagline: "Every fact on this screen traces to an official source.",

  // ---- Reader shell (WO-35) --------------------------------------------------
  // The place view: the same list, in the same order, for every point on the
  // map and every official in it (Rule 0).
  placeLede:
    "Everyone who represents this place, federal to local. Open anyone for their full cited dossier.",
  // A #/d/ link names one division and carries no point, so the levels that
  // cannot be derived from the id are not listed. Say so rather than let a
  // short list read as the whole answer.
  placeLinkNote:
    "Opened from a link to one division, so only its own offices and the statewide ones are listed. Search an address to see every level.",
  placeLoading: "Loading officials…",
  placeCopyLink: "Copy link to this place",
  placeCopied: "Link copied",
  placeCopyManual: "Copy this link",
  termEnds: "Term ends",
  rowContact: "Contact",
  rowContactLoading: "Loading contact details…",
  rowContactNone: "No contact details are published for this official.",
  rowContactFailed: "Contact details could not be loaded. Check your connection and try again.",

  // Arrival and the remembered place. PRIVACY-ADJACENT: these lines tell the
  // reader what the page knows about where they are and what it keeps. They are
  // a public promise and must stay true to ui/place/remembered.ts and to the
  // Privacy page (ui/chrome.tsx) -- change all three together or none.
  approxBadge: "Approximate",
  approxNote:
    "An estimate from your internet connection. The statewide offices are right; a district may differ at your actual address.",
  fixLocate: "Use my exact location",
  fixAddress: "Type an address",
  promptTitle: "Find who represents you",
  promptNote: "We could not place you automatically.",
  savedBadge: "Your place",
  savedNote:
    "Saved in this browser, on this device only, so your next visit opens here. It is never sent anywhere.",
  forgetPlace: "Forget this place",
  notSavedNote: "This place is not saved on this device.",
  nothingThere: "No districts found at that point — try an address inside the United States.",
  locateDenied: "Location permission denied — type your address instead.",
  locateFailed: "Couldn't get your location — type your address instead.",

  // A dossier link that leads nowhere.
  dossierLoading: "Loading dossier…",
  notFoundTitle: "No dossier at this link",
  notFoundBody:
    "Nothing is published at this address. A dossier is removed when its holder leaves office, so this official may no longer be serving — or the link may be incomplete.",
  notFoundOffline: "Your device also appears to be offline, which would have the same effect.",
  notFoundAction: "Back to the map",

  // Panel chrome.
  viewLoading: "Loading…",
  panelClose: "Close panel",
  sheetHandle: "Panel height",
  sheetHandleHint: "Up and Down arrow keys resize the panel.",
  sheetStops: { peek: "collapsed", half: "half", full: "full" } as Record<string, string>,

  // ---- Votes UI (WO-23b) ------------------------------------------------------
  // Nothing here varies by party. Counts and positions are the files' own.
  recordTitle: "Full voting record",
  recordLoading: "Loading the full record…",
  recordAbsent: "The full voting record for this official is not published.",
  recordEmpty: "No recorded votes for this official in this scope.",
  recordFilters: "Filter the record",
  filterTopic: "Topic",
  filterTopicAll: "All topics",
  filterResult: "Result",
  filterResultAll: "All results",
  filterAgainst: "Voted against own party",
  filterNoMatch: "No votes match these filters.",
  filterClear: "Clear filters",
  recordMore: "Show more",
  notOnBill: "Not on a bill",
  againstTag: "against party",
  billNotPublished:
    "This bill’s page is not published yet — read it on congress.gov.",
  billReadOn: "Read it on congress.gov",
  billNoRecord: "This vote is not attached to a bill in our records.",
  rollNotPublished: "This roll call is not published.",
  rollCoverNote:
    "Positions and the party breakdown cover current members only, so they do not add up to the official tally.",
  rollNoPositions: "No positions are published for this roll call.",
  officialRecord: "Official record",
  tallyNotGiven: "not given",
  sponsorNone: "No sponsor is listed.",
  cosponsorsNone: "No current cosponsors.",
  repsTitle: "How your representatives voted",
} as const;
