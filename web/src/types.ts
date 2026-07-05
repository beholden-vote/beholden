/** Types mirroring the published data contracts (docs/DATA-CONTRACTS.md §3/§5).
 *  The frontend renders ONLY what the contracts define — no invented fields. */

export interface Provenance {
  source: string;
  source_url: string;
  retrieved_at: string;
  pipeline_version: string;
  methodology_id: string | null;
}

export interface Pin {
  person_id: string;
  ocd_id: string;
  party: string;
  photo_url: string | null;
  /** Present from pipeline ≥ etl-2026.27; older feeds degrade gracefully. */
  full_name?: string;
  office?: string;
  chamber?: string;
  vacant?: boolean;
}

export interface Dossier {
  schema_version: string;
  person_id: string;
  generated_at: string;
  identity: {
    full_name: string;
    photo_url: string | null;
    office: { role: string; ocd_id: string; display: string; chamber: string };
    party: { code: string; display: string };
    tenure: { first_took_office: string | null; current_term_ends: string | null };
    next_election: string | null;
    status: "incumbent" | "vacant";
    official_links: { type: string; url: string }[];
    provenance: Provenance;
  };
  /** Federal-only for now; a state legislator's dossier omits it (E4). */
  ideology?: {
    scheme: string;
    score: number | null;
    status: string;
    context: { party_median: number | null; chamber_median: number | null };
    scope: string;
    explainer_url: string;
    provenance: Provenance;
  };
  /** Federal-only for now; render only when present. */
  legislative?: {
    counts: { sponsored: number; cosponsored: number; became_law: number };
    recent_bills: { bill_id: string; title: string; status: string; url?: string }[];
    key_votes: {
      roll_call_id: string; question: string; position: string; held_at: string;
      url?: string;
      /** WO-1: the roll call's outcome, and the bill it decided (null for
       *  procedural votes with no bill). bill_url links the bill page when known. */
      result?: string; bill_id?: string | null; bill_url?: string | null;
      /** WO-8: congress.gov's own policy-area taxonomy for the decided bill, if
       *  any — a descriptive chip, never our inference. Absent for procedural
       *  votes or bills with no classified policy area. */
      policy_areas?: string[] | null;
    }[];
    committees: { name: string; role?: string; subcommittees?: { name: string; role?: string }[] }[];
    provenance: Provenance;
    /** WO-6a: committee memberships come from the unitedstates YAML, so they
     *  carry their own envelope; present only when the member sits on one. */
    committees_provenance?: Provenance | null;
  };
  /** Money sections publish with the E3 pipeline; render only when present. */
  money?: {
    net_worth?: {
      band: { min_cents: number; max_cents: number };
      disclosure_year: number;
      filing_url: string;
      provenance?: Provenance;
    };
    trades?: {
      items: {
        asset_name: string; ticker: string | null; txn_type: string;
        amount: string; transacted_on: string; filed_on: string;
        late_by_days: number; filing_url: string;
      }[];
      provenance?: Provenance;
    };
    campaign_finance?: {
      cycles: {
        cycle: number; total_raised_cents: number | null;
        total_spent_cents: number | null; cash_on_hand_cents: number | null;
        as_of: string;
      }[];
      top_contributors?: { name: string; total_cents: number }[];
      provenance?: Provenance;
    };
    /** STOCK Act periodic transaction reports — links to the official filings. */
    disclosures?: {
      filings: { filed_on: string | null; filing_url: string }[];
      count: number;
      provenance?: Provenance;
    };
  };
  graph_ref: string;
}

/** One rendered polygon level under a clicked point. Mirrors map.ts's LayerId
 *  (kept inline so this contract file stays free of engine imports). */
export interface StackEntry {
  layer: "states" | "cd" | "sldu" | "sldl" | "county";
  ocdId: string;
  pins: Pin[];
}
