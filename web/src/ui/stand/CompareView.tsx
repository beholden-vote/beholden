/** #/c/{id}/{id}: two officials side by side -- each one's own measures, where both
 *  sit on the chamber plots, and how often they voted together. The two columns are
 *  built by the same code from the same fields; nothing combines them into a verdict. */
import { useEffect, useState } from "react";
import type { PersonVotes } from "../../types";
import { agreement, findMember, type Found } from "../../lib/positions";
import { loadVotes } from "../../lib/votes";
import { personHash } from "../../router";
import { STRINGS } from "../../strings";
import { EmptyNote, PartyChip, Section } from "../bits";
import type { RecordViewProps } from "../nav/registry";
import { Wait, useHeadingFocus } from "../votes/bits";
import { MeasureValue } from "./Measures";
import { Plots } from "./Plots";

type Loaded = { a: Found | null; b: Found | null; va: PersonVotes | null; vb: PersonVotes | null };

export default function CompareView({ route, onTitle }: RecordViewProps<"compare">) {
  const [d, setD] = useState<Loaded | undefined>(undefined);
  const heading = useHeadingFocus(d !== undefined);

  useEffect(() => {
    let live = true;
    setD(undefined);
    void Promise.all([findMember(route.a), findMember(route.b), loadVotes(route.a), loadVotes(route.b)])
      .then(([a, b, va, vb]) => { if (live) setD({ a, b, va, vb }); });
    return () => { live = false; };
  }, [route.a, route.b]);
  useEffect(() => { if (d?.a && d.b) onTitle(`${d.a.member.name} and ${d.b.member.name}`); }, [d, onTitle]);

  if (d === undefined) return <Wait text={STRINGS.viewLoading} />;
  if (!d.a || !d.b) {
    return (
      <div className="not-found">
        <h2 ref={heading} tabIndex={-1}>{STRINGS.compareNotFound}</h2>
        <p className="mono not-found-id">{route.a} · {route.b}</p>
      </div>
    );
  }
  const people = [d.a, d.b].map((f, i) => ({ ...f, tag: i ? "B" : "A" }));
  const together = d.va && d.vb ? agreement(d.va.votes, d.vb.votes) : null;
  const same = d.a.file.chamber === d.b.file.chamber;
  const f = (n: number | null | undefined) => (n == null ? STRINGS.standNotPublishedValue : n.toFixed(3));
  const rows: { label: string; cell: (m: Found["member"]) => React.ReactNode }[] = [
    { label: STRINGS.standMeasures.with_own_party, cell: (m) => <MeasureValue m={m.measures.with_own_party} naText={STRINGS.standNotApplicable} /> },
    { label: STRINGS.standMeasures.with_other_party, cell: (m) => <MeasureValue m={m.measures.with_other_party} naText={STRINGS.standNotApplicable} /> },
    { label: STRINGS.standMeasures.missed, cell: (m) => <MeasureValue m={m.measures.missed} naText={STRINGS.standNotApplicable} /> },
    { label: STRINGS.standDim1, cell: (m) => <span className="mono">{f(m.nominate?.dim1)}</span> },
    { label: STRINGS.standDim2, cell: (m) => <span className="mono">{f(m.nominate?.dim2)}</span> },
  ];
  return (
    <div className="votes-view stand-compare-view">
      <h2 ref={heading} tabIndex={-1}>{STRINGS.compareTitle}</h2>
      <p className="vv-note">{STRINGS.compareNote}</p>

      <Section title={STRINGS.compareTogether}>
        {together === null ? <EmptyNote>{STRINGS.compareVotesMissing}</EmptyNote>
          : together.of === 0 ? <EmptyNote>{STRINGS.compareNoShared}</EmptyNote>
          : (
            <div className="stat-row">
              <div className="stat">
                <b className="stand-together">{STRINGS.compareTogetherOf(together.n, together.of)} ({together.pct?.toFixed(1)}%)</b>
                <span>{STRINGS.compareTogetherNote}</span>
              </div>
            </div>
          )}
      </Section>

      <Section title={STRINGS.standTitle} provenance={d.a.file.provenance}>
        <table className="vr-table stand-compare-table">
          <caption className="visually-hidden">{STRINGS.compareTitle}</caption>
          <thead>
            <tr>
              <th scope="col"><span className="visually-hidden">Measure</span></th>
              {people.map((p) => (
                <th scope="col" key={p.tag}>
                  {p.tag}: <a href={personHash(p.member.person_id)}>{p.member.name}</a>{" "}
                  <PartyChip code={p.member.party} /> <span className="mono">{p.member.state}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label}>
                <th scope="row">{r.label}</th>
                {people.map((p) => <td key={p.tag} data-label={`${r.label}, ${p.tag}`}>{r.cell(p.member)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title={same ? d.a.file.chamber : STRINGS.standTitle}>
        {same ? (
          <Plots file={d.a.file} marks={people.map((p) => ({ id: p.member.person_id, label: p.tag }))} />
        ) : (
          people.map((p) => (
            <div key={p.tag}>
              <h4 className="stand-h">{p.tag}: {p.member.name}, {p.file.chamber}</h4>
              <Plots file={p.file} marks={[{ id: p.member.person_id, label: p.tag }]} />
            </div>
          ))
        )}
      </Section>
    </div>
  );
}
