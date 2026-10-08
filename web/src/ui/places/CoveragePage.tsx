/** The coverage page: what the pipeline did (coverage.json) and which local
 *  governments it covers (coverage/{st}.json, contracts 8.10). No state is
 *  fetched until the reader picks one, or has already reached it on the map. */
import { useEffect, useState } from "react";
import {
  loadCoverageDoc, loadStateCoverage, reachedStates, STATE_CODES, type CoverageDoc,
} from "../../lib/coverage";
import { formatDate } from "../../lib/data";
import type { CoverageShard } from "../../types";
import { STRINGS } from "../../strings";
import { CoverageLegend } from "./CoverageLegend";

const prettyKey = (k: string) => k.replace(/_/g, " ");
const localityOf = (ocd: string) => ocd.replace(/^ocd-division\/country:us\/state:[a-z]{2}\//, "");

/** "checked (date) - unchanged since (date)": two dates, two facts (contracts 8.1). */
function checkedLine(checked?: string | null, changed?: string | null): string {
  const c = formatDate(checked);
  const ch = formatDate(changed);
  if (c && ch) return `${STRINGS.retrievedLabel.checked} ${c} · ${STRINGS.retrievedLabel.unchanged} ${ch}`;
  if (c) return `${STRINGS.retrievedLabel.checked} ${c}`;
  return "—";
}

function StateList() {
  const [st, setSt] = useState<string>(() => [...reachedStates][0] ?? "");
  const [shard, setShard] = useState<CoverageShard | null | undefined>(undefined);
  useEffect(() => {
    if (!st) { setShard(undefined); return; }
    let live = true;
    setShard(undefined);
    void loadStateCoverage(st).then((s) => live && setShard(s));
    return () => { live = false; };
  }, [st]);
  const rows = Object.entries(shard?.divisions ?? {}).sort(([a], [b]) => a.localeCompare(b));
  return (
    <>
      <label className="cov-pick">
        <span className="layer-group-label">{STRINGS.coverageStatePick}</span>
        <select className="grade-select" value={st} onChange={(e) => setSt(e.target.value)}>
          <option value="">&mdash;</option>
          {STATE_CODES.map((c) => <option key={c} value={c}>{c.toUpperCase()}</option>)}
        </select>
      </label>
      {st && shard === null && <p className="empty-note">{STRINGS.coverageStateNone}</p>}
      {rows.length > 0 && (
        <table className="cov-table">
          <thead><tr><th>Division</th><th>State</th><th>Seats</th><th>Roster as of</th></tr></thead>
          <tbody>
            {rows.map(([ocd, d]) => (
              <tr key={ocd}>
                <td className="mono">{localityOf(ocd)}</td>
                <td>
                  <span className="area-cov-swatch" aria-hidden="true" data-cov={d.state} /> {STRINGS.coverageLabels[d.state]}
                  {d.reason && <span className="cov-reason">{d.reason}</span>}
                </td>
                <td className="mono">{d.seats_listed}/{d.seats_expected}</td>
                <td className="mono">{formatDate(d.roster_as_of) ?? d.roster_as_of}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

export default function CoveragePage() {
  const [doc, setDoc] = useState<CoverageDoc | null | undefined>(undefined);
  useEffect(() => { void loadCoverageDoc().then(setDoc); }, []);
  const sources = Object.entries(doc?.sources ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const counts = Object.entries(doc?.counts ?? {});
  const isLocal = ([k]: [string, number]) => k.startsWith("localities_");
  const localities = counts.filter(isLocal);
  const rest = counts.filter((c) => !isLocal(c)).sort(([a], [b]) => a.localeCompare(b));
  return (
    <>
      <h1>{STRINGS.coveragePageTitle}</h1>
      <p className="lede">{STRINGS.coveragePageLede}</p>
      {doc === undefined && <p className="empty-note">{STRINGS.viewLoading}</p>}
      {doc === null && <p className="empty-note">{STRINGS.coverageUnavailable}</p>}
      {doc && (
        <>
          <h2>{STRINGS.coverageSourcesTitle}</h2>
          <table className="cov-table">
            <thead><tr><th>Source</th><th>Last checked</th></tr></thead>
            <tbody>
              {sources.map(([name, s]) => (
                <tr key={name}>
                  <td className="mono">{name}</td>
                  <td className="mono">
                    {checkedLine(s?.retrieved_at, s?.changed_at)}
                    {s?.within_sla === false && <span className="cov-reason">past its freshness limit</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>{STRINGS.coverageLocalitiesTitle}</h2>
          <dl className="area-facts">
            {localities.length === 0 && <p className="empty-note">{STRINGS.coverageLocalitiesNone}</p>}
            {localities.map(([k, v]) => (
              <div key={k}><dt>{prettyKey(k)}</dt><dd className="mono">{v.toLocaleString("en-US")}</dd></div>
            ))}
          </dl>
          <h2>{STRINGS.coverageCountsTitle}</h2>
          <dl className="area-facts">
            {rest.map(([k, v]) => (
              <div key={k}><dt>{prettyKey(k)}</dt><dd className="mono">{v.toLocaleString("en-US")}</dd></div>
            ))}
          </dl>
        </>
      )}
      <h2>{STRINGS.coverageStateTitle}</h2>
      <StateList />
      <CoverageLegend />
      {doc?.generated_at && <p className="info-note">Generated {formatDate(doc.generated_at)}.</p>}
    </>
  );
}
