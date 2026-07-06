/** Full accountability dossier for one official. Renders ONLY published,
 *  provenance-carrying contract data; sections that haven't synced yet say so
 *  honestly instead of showing fabricated zeros.
 *
 *  WO-11: the dossier is organized into tabs — Overview | Record | Committees |
 *  Money | Connections. This is a REGROUPING: each tab is the same Section
 *  components as before, moved verbatim into a per-tab component below. Tabs
 *  whose data isn't published are HIDDEN (not disabled) — the same rule for
 *  every official, so a sparse dossier never shows dead chrome (symmetric by
 *  construction). Only the active tab renders (a hidden tab's content — and
 *  Connections' lazy fetch — defers to first activation).
 *
 *  WO-16 adds: a header action row (Call/Email/Contact/Website, gated per
 *  field — see HeaderActions in bits.tsx), Overview additions (previous
 *  roles, birth year, Wikidata education with its verbatim credibility
 *  note), and a sixth Social tab (link-out cards only, no embeds). */
import { lazy, Suspense, useEffect, useRef } from "react";
import type { Dossier } from "../types";
import { STRINGS } from "../strings";
import { formatDate, formatMoneyCents, legislativeIsStub } from "../lib/data";
import { Avatar, EmptyNote, HeaderActions, PartyChip, Section } from "./bits";
import { IdeologyScale } from "./Ideology";
import { methodologyHash, type DossierTab } from "../router";
import { TabBar } from "./Tabs";

// WO-4: the Connections view + entity-graph code load only when a dossier opens
// (dynamic import keeps the graph fetch/types out of the main bundle).
const Connections = lazy(() => import("./Connections"));

// WO-8: the money-&-votes juxtaposition module. Imported eagerly (its data is
// already in the dossier, no extra fetch) but gated on hasMoneyVotes — it renders
// only when BOTH top contributors and key votes exist (absent ≠ implied).
import { MoneyVotes, hasMoneyVotes } from "./MoneyVotes";

/** WO-6a: committee role enum -> display label. Party-agnostic (rule #3): the
 *  same mapping regardless of which party holds the chair. */
const COMMITTEE_ROLE_LABEL: Record<string, string> = {
  chair: "Chair", ranking: "Ranking Member", vice_chair: "Vice Chair", member: "Member",
};
const committeeRole = (role: string) => COMMITTEE_ROLE_LABEL[role] ?? role;

/** WO-16: past terms from our own warehoused `terms` table, most-recent-first
 *  (already sorted upstream — never re-sorted here). Role/chamber/date range
 *  + a party chip per row, same chip component used everywhere else so a
 *  past term's party reads with identical (data-only) weight to any other
 *  party mention. */
function PreviousRoles({ roles, provenance }: {
  roles: NonNullable<Dossier["identity"]["previous_roles"]>;
  provenance: Dossier["identity"]["provenance"];
}) {
  return (
    <Section title={STRINGS.previousRolesTitle} provenance={provenance}>
      <ul className="plain-list prev-roles">
        {roles.map((r, i) => (
          <li key={`${r.role}-${r.start_date}-${i}`} className="prev-role-row">
            <span className="prev-role-name">{r.role}</span>
            <span className="muted"> · {r.chamber}</span>
            <span className="prev-role-dates muted">
              {" "}· {formatDate(r.start_date) ?? r.start_date}–{formatDate(r.end_date) ?? r.end_date}
            </span>
            <PartyChip code={r.party} />
          </li>
        ))}
      </ul>
    </Section>
  );
}

/** WO-16: federal-only Wikidata education. A crowd-edited source is a lower
 *  trust tier than the government-filing facts elsewhere on the page, so its
 *  credibility_note is rendered VERBATIM, always visible, styled with the
 *  same always-on weight as the money/votes non-causation caveat (never a
 *  tooltip, never collapsed) — education must never carry the same
 *  unqualified visual weight as an official-source fact. */
function Education({ education }: { education: NonNullable<Dossier["identity"]["education"]> }) {
  return (
    <Section title={STRINGS.educationTitle} provenance={education.provenance}>
      <ul className="plain-list">
        {education.items.map((it, i) => (
          <li key={`${it.institution}-${i}`}>
            {it.institution}
            {it.degree && <span className="muted"> · {it.degree}</span>}
            {it.year && <span className="muted"> · {it.year}</span>}
          </li>
        ))}
      </ul>
      <p className="mv-caveat">{education.credibility_note || STRINGS.educationCredibilityFallback}</p>
    </Section>
  );
}

/** Overview: tenure + ideological lean (and the honest pending note when
 *  neither a legislative record nor an ideology score is published yet).
 *  WO-16 adds, when published: birth year alongside tenure, previous roles,
 *  and (federal-only) Wikidata education with its credibility note. */
function OverviewTab({ dossier }: { dossier: Dossier }) {
  const { identity, ideology, legislative } = dossier;
  const tenureStart = formatDate(identity.tenure.first_took_office);
  const tenureEnd = formatDate(identity.tenure.current_term_ends);
  return (
    <>
      <Section title="Tenure" provenance={identity.provenance}>
        <dl className="kv">
          {identity.birth_year && (<><dt>{STRINGS.birthYearLabel}</dt><dd>{identity.birth_year}</dd></>)}
          {tenureStart && (<><dt>In office since</dt><dd>{tenureStart}</dd></>)}
          {tenureEnd && (<><dt>Current term ends</dt><dd>{tenureEnd}</dd></>)}
          {identity.next_election && (<><dt>Next election</dt><dd>{formatDate(identity.next_election)}</dd></>)}
        </dl>
        {identity.official_links.length > 0 && (
          <p className="links">
            {identity.official_links.map((l) => (
              <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer">
                Official {l.type} record ↗
              </a>
            ))}
          </p>
        )}
      </Section>

      {ideology && (
        <Section title="Ideological lean" provenance={ideology.provenance}>
          <IdeologyScale ideology={ideology} partyCode={identity.party.code} />
          {/* WO-8: resolve the ideology explainer to the real methodology anchor.
              The provenance envelope's methodology_id ("dw-nominate") points at
              the same section. */}
          <p className="links">
            <a href={methodologyHash("dw-nominate")}>{STRINGS.methodologyLink}</a>
          </p>
        </Section>
      )}

      {!ideology && !legislative && (
        <Section title="Record">
          <EmptyNote>{STRINGS.stateLegPending}</EmptyNote>
        </Section>
      )}

      {identity.previous_roles && identity.previous_roles.length > 0 && (
        <PreviousRoles roles={identity.previous_roles} provenance={identity.provenance} />
      )}

      {identity.education && <Education education={identity.education} />}
    </>
  );
}

/** Record: sponsorship counts + key votes + recent bills. WO-11 also surfaces
 *  the already-published-but-unrendered key-vote fields: the roll call's result,
 *  its official record link, the decided bill's link/title, and congress.gov's
 *  policy-area chips (the bill's own taxonomy — never our inference). */
function RecordTab({ dossier }: { dossier: Dossier }) {
  const legislative = dossier.legislative!;
  return (
    <Section title="Legislative record" provenance={legislative.provenance}>
      {legislativeIsStub(dossier) ? (
        <EmptyNote>{STRINGS.legislativePending}</EmptyNote>
      ) : (
        <>
          <div className="stat-row">
            <div className="stat"><b>{legislative.counts.sponsored}</b><span>sponsored</span></div>
            <div className="stat"><b>{legislative.counts.cosponsored}</b><span>cosponsored</span></div>
            <div className="stat"><b>{legislative.counts.became_law}</b><span>became law</span></div>
          </div>
          {legislative.key_votes.length > 0 && (
            <>
              <h4>Key votes</h4>
              <ul className="kv-vote-list">
                {legislative.key_votes.map((v) => (
                  <li key={v.roll_call_id} className="kv-vote">
                    <div className="kv-vote-top">
                      <span className={`vote vote-${v.position}`}>{v.position}</span>
                      <span className="vote-q">{v.question}</span>
                      <span className="vote-date">{formatDate(v.held_at)}</span>
                    </div>
                    {v.bill_title && <p className="kv-bill-title">{v.bill_title}</p>}
                    {(v.result || v.url || v.bill_url || (v.policy_areas && v.policy_areas.length > 0)) && (
                      <div className="kv-vote-meta">
                        {v.result && <span className="kv-result">{v.result}</span>}
                        {v.policy_areas && v.policy_areas.length > 0 && (
                          <span className="mv-policy-chips">
                            {v.policy_areas.map((pa) => (
                              <span className="mv-policy-chip" key={pa}>{pa}</span>
                            ))}
                          </span>
                        )}
                        {v.url && (
                          <a className="kv-link" href={v.url} target="_blank" rel="noopener noreferrer">
                            roll call ↗
                          </a>
                        )}
                        {v.bill_url && (
                          <a className="kv-link" href={v.bill_url} target="_blank" rel="noopener noreferrer">
                            bill ↗
                          </a>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              {/* WO-8: key-vote selection is a computed metric → link its formula. */}
              <p className="links">
                <a href={methodologyHash("key-votes")}>{STRINGS.methodologyLink}</a>
              </p>
            </>
          )}
          {legislative.recent_bills.length > 0 && (
            <>
              <h4>Recent bills</h4>
              <ul className="plain-list">
                {legislative.recent_bills.map((b) => (
                  <li key={b.bill_id}>
                    {b.url ? (
                      <a href={b.url} target="_blank" rel="noopener noreferrer">{b.title} ↗</a>
                    ) : (
                      b.title
                    )}{" "}
                    <span className="muted">· {b.status}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Section>
  );
}

/** Committees: the membership list, under its own envelope (WO-6a publishes a
 *  dedicated committees_provenance when the member sits on any). */
function CommitteesTab({ dossier }: { dossier: Dossier }) {
  const legislative = dossier.legislative!;
  return (
    <Section title="Committees" provenance={legislative.committees_provenance ?? legislative.provenance}>
      <ul className="plain-list">
        {legislative.committees.map((c) => (
          <li key={c.name}>
            {c.name}{c.role && c.role !== "member" ? ` — ${committeeRole(c.role)}` : ""}
            {c.subcommittees && c.subcommittees.length > 0 && (
              <ul className="plain-list">
                {c.subcommittees.map((s) => (
                  <li key={s.name}>
                    {s.name}{s.role && s.role !== "member" ? ` — ${committeeRole(s.role)}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

/** Money: net worth + trades + campaign finance + the WO-8 juxtaposition module
 *  + disclosures — or the honest pending note when none have published. */
function MoneyTab({ dossier }: { dossier: Dossier }) {
  const { money } = dossier;
  return (
    <>
      {money?.net_worth && (
        <Section title={STRINGS.netWorthTitle} provenance={money.net_worth.provenance}>
          <p className="money-band">
            {formatMoneyCents(money.net_worth.band.min_cents)} – {formatMoneyCents(money.net_worth.band.max_cents)}
            <span className="muted"> · {money.net_worth.disclosure_year} disclosure</span>
          </p>
          <p className="muted">{STRINGS.netWorthNote}</p>
          <p className="links">
            <a href={money.net_worth.filing_url} target="_blank" rel="noopener noreferrer">Original filing ↗</a>
          </p>
        </Section>
      )}

      {money?.trades && money.trades.items.length > 0 && (
        <Section title={STRINGS.tradesTitle} provenance={money.trades.provenance}>
          <ul className="trade-list">
            {money.trades.items.map((t, i) => (
              <li key={`${t.filing_url}-${i}`}>
                <span className="trade-asset">{t.asset_name}{t.ticker ? ` (${t.ticker})` : ""}</span>
                <span className="trade-meta">
                  {t.txn_type} · {t.amount.replace(/_/g, "–")} · {formatDate(t.transacted_on)}
                  {t.late_by_days > 0 && <em className="late-flag"> {STRINGS.tradesLateFlag} +{t.late_by_days}d</em>}
                </span>
                <a href={t.filing_url} target="_blank" rel="noopener noreferrer">filing ↗</a>
              </li>
            ))}
          </ul>
          <p className="muted">{STRINGS.tradesLateNote}</p>
        </Section>
      )}

      {money?.campaign_finance && (
        <Section title={STRINGS.campaignFinanceTitle} provenance={money.campaign_finance.provenance}>
          {money.campaign_finance.cycles.map((c) => (
            <div className="stat-row" key={c.cycle}>
              <div className="stat"><b>{c.total_raised_cents != null ? formatMoneyCents(c.total_raised_cents) : "—"}</b><span>raised ({c.cycle})</span></div>
              <div className="stat"><b>{c.total_spent_cents != null ? formatMoneyCents(c.total_spent_cents) : "—"}</b><span>spent</span></div>
              <div className="stat"><b>{c.cash_on_hand_cents != null ? formatMoneyCents(c.cash_on_hand_cents) : "—"}</b><span>cash on hand</span></div>
            </div>
          ))}
          {money.campaign_finance.top_contributors && money.campaign_finance.top_contributors.length > 0 && (
            <>
              <h4>Top contributors</h4>
              <ul className="plain-list">
                {money.campaign_finance.top_contributors.map((c) => (
                  <li key={c.name}>{c.name} <span className="muted">· {formatMoneyCents(c.total_cents)}</span></li>
                ))}
              </ul>
            </>
          )}
          <p className="muted">{STRINGS.campaignFinanceNote}</p>
        </Section>
      )}

      {/* WO-8: "Money & votes, side by side" — placed after Campaign finance.
          Renders ONLY when both top contributors and key votes are published;
          purely descriptive juxtaposition with a verbatim non-causation caveat. */}
      {hasMoneyVotes(dossier) && <MoneyVotes dossier={dossier} />}

      {money?.disclosures && money.disclosures.count > 0 && (
        <Section title={STRINGS.disclosuresTitle} provenance={money.disclosures.provenance}>
          <p className="muted">
            {money.disclosures.count} periodic transaction report{money.disclosures.count === 1 ? "" : "s"} filed
          </p>
          <ul className="plain-list">
            {money.disclosures.filings.map((f, i) => (
              <li key={`${f.filing_url}-${i}`}>
                <a href={f.filing_url} target="_blank" rel="noopener noreferrer">
                  {formatDate(f.filed_on) ?? "Filing"} ↗
                </a>
              </li>
            ))}
          </ul>
          <p className="muted">{STRINGS.disclosuresNote}</p>
        </Section>
      )}

      {!money && (
        <section className="panel-section">
          <h3>Money</h3>
          <EmptyNote>{STRINGS.moneyPending}</EmptyNote>
        </section>
      )}
    </>
  );
}

/** Connections: the WO-4 entity-graph neighborhood, lazy as before. Living in
 *  a tab means its code + fetch now naturally defer to first activation. */
function ConnectionsTab({ personId, onOpenPerson }: {
  personId: string; onOpenPerson?: (personId: string) => void;
}) {
  return (
    <section className="panel-section">
      <div className="section-head"><h3>{STRINGS.connectionsTitle}</h3></div>
      <Suspense fallback={<EmptyNote>{STRINGS.connectionsLoading}</EmptyNote>}>
        <Connections personId={personId} onOpenPerson={onOpenPerson} />
      </Suspense>
    </section>
  );
}

/** WO-16: verbatim-handle -> profile URL per platform. Every field here is a
 *  handle exactly as published by the source (legislators-social-media.json
 *  for federal; the OpenStates CSV for state) — never a guessed/derived one,
 *  only the LINK TARGET is constructed. No embeds, no iframes, no third-party
 *  widgets: this module only ever produces an <a> to the platform.
 *
 *  twitter/facebook/instagram are bare handles on both sources -> straight
 *  path append. youtube is inconsistent in the source data (a legacy custom
 *  name, a modern "@handle", or a raw "UC..." channel id) — handled by shape,
 *  not by chamber. mastodon (federal only) already ships as a full
 *  "@user@instance" mention; the instance is part of the handle, so it maps
 *  straight onto that instance's profile path. */
const SOCIAL_LABEL: Record<string, string> = {
  twitter: "X (Twitter)", facebook: "Facebook", instagram: "Instagram",
  youtube: "YouTube", mastodon: "Mastodon",
};
function socialUrl(platform: string, handle: string): string {
  switch (platform) {
    case "twitter":
      return `https://x.com/${handle}`;
    case "facebook":
      return `https://facebook.com/${handle}`;
    case "instagram":
      return `https://instagram.com/${handle}`;
    case "youtube":
      if (/^UC[A-Za-z0-9_-]{22}$/.test(handle)) return `https://youtube.com/channel/${handle}`;
      return handle.startsWith("@") ? `https://youtube.com/${handle}` : `https://youtube.com/@${handle}`;
    case "mastodon": {
      // "@user@instance.tld" -> https://instance.tld/@user
      const m = /^@?([^@]+)@(.+)$/.exec(handle);
      return m ? `https://${m[2]}/@${m[1]}` : handle;
    }
    default:
      return handle;
  }
}

/** Social: link-out cards to each published platform handle. NO embedded
 *  feeds/iframes/third-party scripts — a deliberate privacy/zero-tracker
 *  requirement, not a style choice. Hidden entirely (by the caller's gate)
 *  when identity.social has no handle at all. */
function SocialTab({ social }: { social: NonNullable<Dossier["identity"]["social"]> }) {
  const platforms = (["twitter", "facebook", "instagram", "youtube", "mastodon"] as const)
    .filter((p) => social[p]);
  return (
    <section className="panel-section">
      <div className="section-head"><h3>{STRINGS.socialTitle}</h3></div>
      <ul className="social-cards">
        {platforms.map((p) => (
          <li key={p} className="social-card">
            <a href={socialUrl(p, social[p]!)} target="_blank" rel="noopener noreferrer">
              <span className="social-card-platform">{SOCIAL_LABEL[p]}</span>
              <span className="social-card-handle mono">{social[p]} ↗</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function DossierView({ dossier, tab, onSelectTab, onBack, onOpenPerson }: {
  dossier: Dossier;
  tab: DossierTab;
  onSelectTab: (tab: DossierTab) => void;
  onBack?: () => void;
  /** WO-13: the Connections graph + list open a neighbor's dossier through this. */
  onOpenPerson?: (personId: string) => void;
}) {
  const { identity, legislative } = dossier;
  const vacant = identity.status === "vacant";

  // Tab visibility — hide, don't disable. Data-driven and identical for every
  // official: record iff a legislative section exists; committees iff any
  // membership is published; social (WO-16) iff any handle is published;
  // overview/money/connections always.
  const hasSocial = !!identity.social && Object.keys(identity.social).length > 0;
  const tabs: { id: DossierTab; label: string }[] = [{ id: "overview", label: STRINGS.tabOverview }];
  if (legislative) tabs.push({ id: "record", label: STRINGS.tabRecord });
  if (legislative && legislative.committees.length > 0) tabs.push({ id: "committees", label: STRINGS.tabCommittees });
  tabs.push({ id: "money", label: STRINGS.tabMoney }, { id: "connections", label: STRINGS.tabConnections });
  if (hasSocial) tabs.push({ id: "social", label: STRINGS.tabSocial });

  // A deep link to a hidden tab clamps to overview WITHOUT rewriting the hash —
  // the link stays shareable as written; we just don't render dead chrome.
  const active: DossierTab = tabs.some((t) => t.id === tab) ? tab : "overview";

  // On a tab CHANGE (same person), scroll the panel so the tab's content starts
  // under the sticky bar (scroll-margin-top matches the bar height). A fresh
  // dossier — open or person-switch — keeps the header in view instead.
  const tabpanelRef = useRef<HTMLDivElement>(null);
  const lastPersonRef = useRef<string | null>(null);
  useEffect(() => {
    const samePerson = lastPersonRef.current === dossier.person_id;
    lastPersonRef.current = dossier.person_id;
    if (samePerson) tabpanelRef.current?.scrollIntoView({ block: "start", inline: "nearest" });
  }, [active, dossier.person_id]);

  return (
    <div className="dossier">
      {onBack && (
        <button className="back-btn" onClick={onBack}>← All representation here</button>
      )}

      <header className="dossier-head">
        <Avatar url={identity.photo_url} name={identity.full_name} size={72} />
        <div>
          <h2>{identity.full_name}</h2>
          <p className="office-line">{identity.office.display}</p>
          <p className="chips">
            <PartyChip code={identity.party.code} display={identity.party.display} />
            {vacant && <span className="chip chip-vacant">Vacant seat</span>}
          </p>
        </div>
      </header>

      <HeaderActions contact={identity.contact} />

      <TabBar tabs={tabs} active={active} onSelect={onSelectTab} idPrefix="dossier" />

      <div
        ref={tabpanelRef}
        className="dossier-tabpanel"
        role="tabpanel"
        id={`dossier-panel-${active}`}
        aria-labelledby={`dossier-tab-${active}`}
      >
        {active === "overview" && <OverviewTab dossier={dossier} />}
        {active === "record" && legislative && <RecordTab dossier={dossier} />}
        {active === "committees" && legislative && <CommitteesTab dossier={dossier} />}
        {active === "money" && <MoneyTab dossier={dossier} />}
        {active === "connections" && <ConnectionsTab personId={dossier.person_id} onOpenPerson={onOpenPerson} />}
        {active === "social" && hasSocial && <SocialTab social={identity.social!} />}
      </div>

      <footer className="dossier-foot">
        <p>{STRINGS.provenanceTagline}</p>
        <p className="muted">
          pipeline {identity.provenance.pipeline_version} · generated {formatDate(dossier.generated_at)}
        </p>
      </footer>
    </div>
  );
}
