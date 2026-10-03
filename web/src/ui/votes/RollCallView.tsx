/** #/v/{roll_call_id}: one vote -- the question, the official tally, the tally
 *  by party in the file's order, the bill, and each current member's position. */
import { useEffect, useState } from "react";
import type { RollCall } from "../../types";
import { formatDate } from "../../lib/data";
import { loadRollCall } from "../../lib/votes";
import { billHash, personHash } from "../../router";
import { STRINGS } from "../../strings";
import { EmptyNote, PartyChip, Section } from "../bits";
import type { RecordViewProps } from "../nav/registry";
import { Position, Wait, useHeadingFocus } from "./bits";

const PAGE = 100;

export default function RollCallView({ route, onTitle }: RecordViewProps<"vote">) {
  const [rc, setRc] = useState<RollCall | null | undefined>(undefined);
  const [shown, setShown] = useState(PAGE);
  const heading = useHeadingFocus(rc !== undefined);

  useEffect(() => {
    let live = true;
    setRc(undefined);
    void loadRollCall(route.rollCallId).then((r) => { if (live) setRc(r); });
    return () => { live = false; };
  }, [route.rollCallId]);
  useEffect(() => { if (rc) onTitle(rc.question); }, [rc, onTitle]);

  if (rc === undefined) return <Wait text={STRINGS.viewLoading} />;
  if (rc === null) {
    return (
      <div className="not-found">
        <h2 ref={heading} tabIndex={-1}>{STRINGS.rollNotPublished}</h2>
        <p className="mono not-found-id">{route.rollCallId}</p>
      </div>
    );
  }
  const tally = (n: number | null) => (n === null ? STRINGS.tallyNotGiven : n);
  return (
    <div className="votes-view">
      <h2 ref={heading} tabIndex={-1}>{rc.question}</h2>
      <p className="vv-meta mono">{rc.chamber} · {formatDate(rc.held_at) ?? rc.held_at} · {rc.result}</p>
      {rc.description && <p className="vv-desc">{rc.description}</p>}
      {rc.bill_id && (
        <p><a className="kv-link" href={billHash(rc.bill_id)}>{rc.bill_title ?? rc.bill_id} →</a></p>
      )}

      <Section title="Official tally" provenance={rc.provenance}>
        <div className="stat-row">
          <div className="stat"><b>{tally(rc.totals.yea)}</b><span>yea</span></div>
          <div className="stat"><b>{tally(rc.totals.nay)}</b><span>nay</span></div>
        </div>
        {rc.url && (
          <p className="links">
            <a className="kv-link" href={rc.url} target="_blank" rel="noopener noreferrer">{STRINGS.officialRecord} ↗</a>
          </p>
        )}
        <p className="vv-note">{STRINGS.rollCoverNote}</p>
      </Section>

      {rc.by_party.length > 0 && (
        <Section title="By party">
          <table className="vr-table vv-party">
            <thead>
              <tr><th scope="col">Party</th><th scope="col">Yea</th><th scope="col">Nay</th><th scope="col">Present</th><th scope="col">Not voting</th></tr>
            </thead>
            <tbody>
              {rc.by_party.map((p) => (
                <tr key={p.party}>
                  <th scope="row"><PartyChip code={p.party} /></th>
                  <td data-label="Yea" className="mono">{p.yea}</td>
                  <td data-label="Nay" className="mono">{p.nay}</td>
                  <td data-label="Present" className="mono">{p.present}</td>
                  <td data-label="Not voting" className="mono">{p.not_voting}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      <Section title="Positions">
        {rc.positions.length === 0 ? <EmptyNote>{STRINGS.rollNoPositions}</EmptyNote> : (
          <>
            <table className="vr-table">
              <thead>
                <tr><th scope="col">Member</th><th scope="col">Party</th><th scope="col">State</th><th scope="col">Position</th></tr>
              </thead>
              <tbody>
                {rc.positions.slice(0, shown).map((p) => (
                  <tr key={p.person_id}>
                    <td data-label="Member"><a href={personHash(p.person_id)}>{p.name}</a></td>
                    <td data-label="Party"><PartyChip code={p.party} /></td>
                    <td data-label="State" className="mono">{p.state}</td>
                    <td data-label="Position"><Position value={p.position} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rc.positions.length > shown && (
              <button type="button" className="fix-ghost" onClick={() => setShown((n) => n + PAGE)}>
                {STRINGS.recordMore} ({rc.positions.length - shown})
              </button>
            )}
          </>
        )}
      </Section>
    </div>
  );
}
