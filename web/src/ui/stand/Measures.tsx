/** One member's measures as text: `n of of (pct)`, the formula one click away, and
 *  an absent value said in words and never drawn as zero. Same rows, same order,
 *  for every member. */
import type { Measure, PositionMember } from "../../types";
import { methodologyHash } from "../../router";
import { STRINGS } from "../../strings";

const ANCHOR: Record<string, string> = {
  with_own_party: "with-own-party", with_other_party: "with-other-party", missed: "missed-votes",
};
const num = (n: number) => n.toLocaleString("en-US");

export function MeasureValue({ m, naText }: { m: Measure | null; naText: string }) {
  if (!m) return <span className="stand-na">{naText}</span>;
  return (
    <span className="mono">
      {num(m.n)} of {num(m.of)}{" "}
      {m.pct === null ? <span className="stand-na">({STRINGS.standNotEnough})</span> : `(${m.pct.toFixed(1)}%)`}
    </span>
  );
}

export function MeasureRows({ member, withFormula = true }: { member: PositionMember; withFormula?: boolean }) {
  const rows = ["with_own_party", "with_other_party", "missed"] as const;
  return (
    <dl className="stand-measures">
      {rows.map((k) => (
        <div className="stand-measure" key={k}>
          <dt>{STRINGS.standMeasures[k]}{withFormula && (
            <> <a className="kv-link" href={methodologyHash(ANCHOR[k])}>{STRINGS.standFormula} ↗</a></>
          )}</dt>
          <dd><MeasureValue m={member.measures[k]} naText={STRINGS.standNotApplicable} /></dd>
        </div>
      ))}
    </dl>
  );
}

export function Nominate({ member }: { member: PositionMember }) {
  const f = (v: number | null | undefined) => (v == null ? STRINGS.standNotPublishedValue : v.toFixed(3));
  return (
    <dl className="stand-measures">
      <div className="stand-measure"><dt>{STRINGS.standDim1}</dt><dd className="mono">{f(member.nominate?.dim1)}</dd></div>
      <div className="stand-measure"><dt>{STRINGS.standDim2}</dt><dd className="mono">{f(member.nominate?.dim2)}</dd></div>
    </dl>
  );
}

export function PolicyAreas({ member }: { member: PositionMember }) {
  const rows = member.measures.party_line_by_policy_area;
  if (!rows.length) return null;
  return (
    <details className="stand-areas">
      <summary>{STRINGS.standPolicyArea}</summary>
      <p className="stand-note"><a className="kv-link" href={methodologyHash("party-line")}>{STRINGS.standFormula} ↗</a></p>
      <table className="vr-table">
        <thead><tr><th scope="col">Policy area</th><th scope="col">Votes</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.policy_area}><th scope="row" data-label="Policy area">{r.policy_area}</th>
              <td data-label="Votes"><MeasureValue m={r} naText="" /></td></tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
