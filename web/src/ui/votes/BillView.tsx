/** #/b/{bill_id}: a bill that has had at least one roll call (contracts 8.3). */
import { useEffect, useState } from "react";
import type { Bill, BillMember } from "../../types";
import { formatDate } from "../../lib/data";
import { congressGovUrl, loadBill } from "../../lib/votes";
import { personHash, voteHash } from "../../router";
import { STRINGS } from "../../strings";
import { EmptyNote, PartyChip, Section } from "../bits";
import type { RecordViewProps } from "../nav/registry";
import { Wait, useHeadingFocus } from "./bits";

function Member({ m }: { m: BillMember }) {
  return (
    <>
      {m.person_id ? <a href={personHash(m.person_id)}>{m.name}</a> : m.name}
      {" "}<PartyChip code={m.party} /> <span className="mono">{m.state}</span>
    </>
  );
}

export default function BillView({ route, onTitle }: RecordViewProps<"bill">) {
  const [bill, setBill] = useState<Bill | null | undefined>(undefined);
  const heading = useHeadingFocus(bill !== undefined);

  useEffect(() => {
    let live = true;
    setBill(undefined);
    void loadBill(route.billId).then((b) => { if (live) setBill(b); });
    return () => { live = false; };
  }, [route.billId]);
  useEffect(() => { if (bill) onTitle(bill.number); }, [bill, onTitle]);

  if (bill === undefined) return <Wait text={STRINGS.viewLoading} />;
  if (bill === null) {
    const out = congressGovUrl(route.billId);
    return (
      <div className="not-found">
        <h2 ref={heading} tabIndex={-1}>{STRINGS.billNotPublished}</h2>
        {out && <p><a className="kv-link" href={out} target="_blank" rel="noopener noreferrer">{STRINGS.billReadOn} ↗</a></p>}
        <p className="mono not-found-id">{route.billId}</p>
      </div>
    );
  }
  const co = bill.cosponsors;
  return (
    <div className="votes-view">
      <h2 ref={heading} tabIndex={-1}>{bill.title}</h2>
      <p className="vv-meta mono">
        {bill.number} · {bill.status.replace(/_/g, " ")}
        {bill.introduced_on && ` · introduced ${formatDate(bill.introduced_on)}`}
      </p>
      {bill.policy_area && <p><span className="mv-policy-chip">{bill.policy_area}</span></p>}
      <p className="links"><a className="kv-link" href={bill.url} target="_blank" rel="noopener noreferrer">{STRINGS.billReadOn} ↗</a></p>

      <Section title="Sponsor" provenance={bill.provenance}>
        {bill.sponsor ? <p><Member m={bill.sponsor} /></p> : <EmptyNote>{STRINGS.sponsorNone}</EmptyNote>}
      </Section>

      <Section title="Cosponsors">
        {co.total === 0 ? <EmptyNote>{STRINGS.cosponsorsNone}</EmptyNote> : (
          <>
            <p className="mono">{co.total} current</p>
            <ul className="vv-parties">
              {co.by_party.map((p) => <li key={p.party}><PartyChip code={p.party} /> <span className="mono">{p.count}</span></li>)}
            </ul>
            <details className="vv-members">
              <summary>Members ({co.members.length})</summary>
              <ul className="plain-list">
                {co.members.map((m, i) => <li key={m.person_id ?? `${m.name}-${i}`}><Member m={m} /></li>)}
              </ul>
            </details>
          </>
        )}
      </Section>

      <Section title="Roll calls">
        <table className="vr-table">
          <thead>
            <tr><th scope="col">Date</th><th scope="col">Vote</th><th scope="col">Result</th></tr>
          </thead>
          <tbody>
            {bill.roll_calls.map((r) => (
              <tr key={r.roll_call_id}>
                <td data-label="Date" className="mono">{formatDate(r.held_at) ?? r.held_at}</td>
                <td data-label="Vote"><a href={voteHash(r.roll_call_id)}>{r.question}</a></td>
                <td data-label="Result" className="mono">{r.result} · {r.yea_count}–{r.nay_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}
