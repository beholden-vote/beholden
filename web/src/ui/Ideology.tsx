/** DW-NOMINATE lean scale (PRD: "lean slider"). Symmetric by construction:
 *  a fixed −1…+1 axis, identical for every official — the member's marker,
 *  their party's median, and the chamber median. Descriptive, not prescriptive:
 *  standard axis labels, no judgment copy. */
import type { Dossier } from "../types";
import { STRINGS } from "../strings";

const pct = (score: number) => `${((score + 1) / 2) * 100}%`;

export function IdeologyScale({ ideology, partyCode }: {
  ideology: NonNullable<Dossier["ideology"]>; partyCode: string;
}) {
  const { score, context, scope, status } = ideology;
  if (score == null) {
    return (
      <p className="empty-note">
        {status === "pending_insufficient_votes"
          ? STRINGS.ideologyPendingInsufficientVotes
          : `Score status: ${status}`}
      </p>
    );
  }
  return (
    <div className="lean">
      <div className="lean-track">
        <div className="lean-axis" />
        {context.chamber_median != null && (
          <div className="lean-tick lean-tick-chamber" style={{ left: pct(context.chamber_median) }}
               title={`Chamber median ${context.chamber_median.toFixed(2)}`} />
        )}
        {context.party_median != null && (
          <div className="lean-tick lean-tick-party" style={{ left: pct(context.party_median) }}
               title={`Party median ${context.party_median.toFixed(2)}`} />
        )}
        <div className={`lean-dot party-${partyCode}`} style={{ left: pct(score) }}
             title={`DW-NOMINATE ${score.toFixed(3)}`} />
      </div>
      <div className="lean-labels">
        <span>← more liberal</span>
        <span className="lean-score">{score.toFixed(2)}</span>
        <span>more conservative →</span>
      </div>
      <div className="lean-legend">
        <span><i className="lean-swatch lean-swatch-member" /> member</span>
        {context.party_median != null && <span><i className="lean-swatch lean-swatch-party" /> party median</span>}
        {context.chamber_median != null && <span><i className="lean-swatch lean-swatch-chamber" /> chamber median</span>}
        <span className="lean-scope">{scope}</span>
      </div>
    </div>
  );
}
