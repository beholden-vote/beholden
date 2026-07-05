/** Full accountability dossier for one official. Renders ONLY published,
 *  provenance-carrying contract data; sections that haven't synced yet say so
 *  honestly instead of showing fabricated zeros. */
import type { Dossier } from "../types";
import { STRINGS } from "../strings";
import { formatDate, formatMoneyCents, legislativeIsStub } from "../lib/data";
import { Avatar, EmptyNote, PartyChip, Section } from "./bits";
import { IdeologyScale } from "./Ideology";

/** WO-6a: committee role enum -> display label. Party-agnostic (rule #3): the
 *  same mapping regardless of which party holds the chair. */
const COMMITTEE_ROLE_LABEL: Record<string, string> = {
  chair: "Chair", ranking: "Ranking Member", vice_chair: "Vice Chair", member: "Member",
};
const committeeRole = (role: string) => COMMITTEE_ROLE_LABEL[role] ?? role;

export function DossierView({ dossier, onBack }: { dossier: Dossier; onBack?: () => void }) {
  const { identity, ideology, legislative, money } = dossier;
  const vacant = identity.status === "vacant";
  const tenureStart = formatDate(identity.tenure.first_took_office);
  const tenureEnd = formatDate(identity.tenure.current_term_ends);

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

      <Section title="Tenure" provenance={identity.provenance}>
        <dl className="kv">
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
        </Section>
      )}

      {!ideology && !legislative && (
        <Section title="Record">
          <EmptyNote>{STRINGS.stateLegPending}</EmptyNote>
        </Section>
      )}

      {legislative && (
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
            {legislative.committees.length > 0 && (
              <>
                <h4>Committees</h4>
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
              </>
            )}
            {legislative.key_votes.length > 0 && (
              <>
                <h4>Key votes</h4>
                <ul className="vote-list">
                  {legislative.key_votes.map((v) => (
                    <li key={v.roll_call_id}>
                      <span className={`vote vote-${v.position}`}>{v.position}</span>
                      <span className="vote-q">{v.question}</span>
                      <span className="vote-date">{formatDate(v.held_at)}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {legislative.recent_bills.length > 0 && (
              <>
                <h4>Recent bills</h4>
                <ul className="plain-list">
                  {legislative.recent_bills.map((b) => (
                    <li key={b.bill_id}>{b.title} <span className="muted">· {b.status}</span></li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </Section>
      )}

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

      <footer className="dossier-foot">
        <p>{STRINGS.provenanceTagline}</p>
        <p className="muted">
          pipeline {identity.provenance.pipeline_version} · generated {formatDate(dossier.generated_at)}
        </p>
      </footer>
    </div>
  );
}
