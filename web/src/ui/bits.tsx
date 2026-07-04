/** Small shared UI atoms: party chip, avatar, section shell, provenance line. */
import type { ReactNode } from "react";
import type { Provenance } from "../types";
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
      <h3>{title}</h3>
      {children}
      {provenance && (
        <p className="provenance">
          {STRINGS.sourceLabel}:{" "}
          <a href={provenance.source_url} target="_blank" rel="noopener noreferrer">
            {provenance.source}
          </a>{" "}
          · {STRINGS.retrievedLabel} {formatDate(provenance.retrieved_at) ?? provenance.retrieved_at}
        </p>
      )}
    </section>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="empty-note">{children}</p>;
}
