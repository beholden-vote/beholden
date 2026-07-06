/** Small shared UI atoms: party chip, avatar, section shell, provenance line. */
import type { ReactNode } from "react";
import type { Dossier, Provenance } from "../types";
import { PARTY_COLORS } from "../map";
import { STRINGS } from "../strings";
import { formatDate } from "../lib/data";

export function PartyChip({ code, display }: { code: string; display?: string }) {
  return (
    <span className="chip" style={{ background: PARTY_COLORS[code] ?? PARTY_COLORS.NP }}>
      {display ?? code}
    </span>
  );
}

export function Avatar({ url, name, size = 64 }: { url: string | null | undefined; name: string; size?: number }) {
  const initials = name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return url ? (
    <img className="avatar" src={url} alt={name} width={size} height={size} loading="lazy"
         onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
  ) : (
    <div className="avatar avatar-fallback" style={{ width: size, height: size }}>{initials}</div>
  );
}

/** Every section is cited or it doesn't ship: the provenance line is part of
 *  the section shell, not an optional extra (rule #1). */
export function Section({ title, provenance, children }: {
  title: string; provenance?: Provenance; children: ReactNode;
}) {
  return (
    <section className="panel-section">
      <div className="section-head">
        <h3>{title}</h3>
        {provenance && (
          <a className="source-tag" href={provenance.source_url} target="_blank" rel="noopener noreferrer"
             title={`Source: ${provenance.source}`}>
            {provenance.source} ↗
          </a>
        )}
      </div>
      {children}
      {provenance && (
        <p className="retrieved">
          {STRINGS.retrievedLabel} {formatDate(provenance.retrieved_at) ?? provenance.retrieved_at}
        </p>
      )}
    </section>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="empty-note">{children}</p>;
}

/** Header action row (WO-16): Call / Email / Contact / Website. Each button
 *  renders ONLY when its own contact field is published — no empty row, no
 *  disabled placeholders (absence stays honest and invisible). The four
 *  fields are mutually exclusive by source (federal ships contact_form/
 *  website, never email; state ships email, never contact_form) so gating on
 *  field presence alone already yields "Email: state only" / "Contact:
 *  federal only" — no chamber check needed. Identical button treatment for
 *  every party (Rule 0): amber-outline ghost buttons, hard edges, no color
 *  varies by anything except which fields exist. */
export function HeaderActions({ contact }: { contact: Dossier["identity"]["contact"] }) {
  if (!contact) return null;
  const { phone, email, contact_form, website } = contact;
  if (!phone && !email && !contact_form && !website) return null;
  return (
    <div className="dossier-actions">
      {phone && (
        <a className="dossier-action" href={`tel:${phone}`}>{STRINGS.actionCall}</a>
      )}
      {email && (
        <a className="dossier-action" href={`mailto:${email}`}>{STRINGS.actionEmail}</a>
      )}
      {contact_form && (
        <a className="dossier-action" href={contact_form} target="_blank" rel="noopener noreferrer">
          {STRINGS.actionContactForm} ↗
        </a>
      )}
      {website && (
        <a className="dossier-action" href={website} target="_blank" rel="noopener noreferrer">
          {STRINGS.actionWebsite} ↗
        </a>
      )}
    </div>
  );
}
