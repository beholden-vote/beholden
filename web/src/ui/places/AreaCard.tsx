/** The facts about a county or city: who we cover there, and what the Census
 *  says about it (contracts 8.4, 8.10).
 *
 *  Honest numbers: an estimate is printed with its margin of error. Where the
 *  Bureau publishes none (a controlled count such as a county's population) the
 *  card says so in words rather than implying an exact figure. A field the file
 *  omits is not shown at all, never as a zero. Nothing here is derived: no rates,
 *  no rounding beyond the Bureau's own precision. The same card for every place.
 */
import { useEffect, useState } from "react";
import { loadAreaFacts, type AreaLookup } from "../../lib/areas";
import { divisionCoverage, loadCoverageDoc, loadStateCoverage, type CoverageDoc } from "../../lib/coverage";
import { formatDate } from "../../lib/data";
import type { AreaEstimate, CoverageShard, Provenance, StackEntry } from "../../types";
import { STRINGS } from "../../strings";

const num = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });

function Estimate({ field, e }: { field: string; e: AreaEstimate }) {
  const money = field === "median_household_income";
  const fmt = (n: number) => (money ? `$${num(n)}` : num(n));
  return (
    <>
      {fmt(e.estimate)}
      {e.moe !== null
        ? <span className="area-moe"> &plusmn; {fmt(e.moe)}</span>
        : <span className="area-moe"> &middot; {STRINGS.areaNoMargin}</span>}
    </>
  );
}

const FIELDS = ["population", "households", "median_household_income", "median_age"] as const;

/** "checked (coverage date) - unchanged since (envelope date)" (contracts 8.1). */
function Cite({ label, vintage, p, doc }: {
  label: string; vintage: string | number; p: Provenance; doc: CoverageDoc | null;
}) {
  const since = formatDate(p.retrieved_at) ?? p.retrieved_at;
  const checkedAt = doc?.sources?.[p.source]?.retrieved_at;
  const checked = checkedAt && Date.parse(checkedAt) >= Date.parse(p.retrieved_at) ? formatDate(checkedAt) : null;
  return (
    <li>
      <a className="source-tag" href={p.source_url} target="_blank" rel="noopener noreferrer">
        {label}, {vintage} &#8599;
      </a>
      <span className="retrieved">
        {checked ? `${STRINGS.retrievedLabel.checked} ${checked} · ` : ""}{STRINGS.retrievedLabel.unchanged} {since}
      </span>
    </li>
  );
}

/** Coverage state in words: the fill is never the only carrier. `shard` is
 *  undefined while loading, null when the state has no file. */
export function CoverageLine({ ocdId, shard }: { ocdId: string; shard: CoverageShard | null | undefined }) {
  const d = shard === undefined ? null : divisionCoverage(shard, ocdId);
  const key = d?.state ?? "none";
  return (
    <div className="area-coverage">
      <span className="area-cov-swatch" aria-hidden="true" data-cov={key} />
      <div>
        <p className="area-cov-state">
          <strong>{shard === undefined ? "…" : STRINGS.coverageLabels[key]}</strong>
          {d && (
            <span className="mono">
              {" · "}{STRINGS.coverageSeats(d.seats_listed, d.seats_expected)}
              {" · "}{STRINGS.coverageAsOf} {formatDate(d.roster_as_of) ?? d.roster_as_of}
            </span>
          )}
        </p>
        <p className="area-cov-why">{d?.reason ?? (shard === undefined ? "" : STRINGS.coverageMeaning[key])}</p>
      </div>
    </div>
  );
}

export function AreaCard({ entry }: { entry: StackEntry }) {
  const kind: "county" | "place" = entry.layer === "place" ? "place" : "county";
  const st = (entry.props?.state ?? /state:([a-z]{2})/.exec(entry.ocdId)?.[1] ?? "").toLowerCase();
  const geoid = entry.props?.geoid;
  const [shard, setShard] = useState<CoverageShard | null | undefined>(undefined);
  const [facts, setFacts] = useState<AreaLookup | null | undefined>(undefined);
  const [doc, setDoc] = useState<CoverageDoc | null>(null);

  useEffect(() => {
    let live = true;
    setShard(undefined); setFacts(undefined);
    if (!st) { setShard(null); setFacts(null); return; }
    void loadStateCoverage(st).then((s) => live && setShard(s));
    if (geoid) void loadAreaFacts(kind, st, geoid).then((f) => live && setFacts(f));
    else setFacts(null);
    void loadCoverageDoc().then((c) => live && setDoc(c));
    return () => { live = false; };
  }, [kind, st, geoid, entry.ocdId]);

  return (
    <div className="area-card">
      <CoverageLine ocdId={entry.ocdId} shard={shard} />
      <h5 className="area-h">{STRINGS.areaTitle}</h5>
      {facts === undefined ? <p className="empty-note">{STRINGS.areaLoading}</p>
        : facts === null ? <p className="empty-note">{geoid ? STRINGS.areaNone : STRINGS.areaNoGeoid}</p>
        : (
          <>
            <dl className="area-facts">
              {FIELDS.map((f) => {
                const e = facts.facts[f];
                return e ? (
                  <div key={f}>
                    <dt>{STRINGS.areaFields[f]}</dt>
                    <dd className="mono"><Estimate field={f} e={e} /></dd>
                  </div>
                ) : null;
              })}
              {facts.facts.land_sqmi !== undefined && (
                <div>
                  <dt>{STRINGS.areaLand}</dt>
                  <dd className="mono">{num(facts.facts.land_sqmi)} sq mi</dd>
                </div>
              )}
            </dl>
            <p className="area-note">{STRINGS.areaMoeNote}</p>
            <ul className="area-cites">
              <Cite label={STRINGS.areaSurvey} vintage={facts.file.survey.vintage}
                    p={facts.file.survey.provenance} doc={doc} />
              <Cite label={STRINGS.areaGeography} vintage={facts.file.geography.vintage}
                    p={facts.file.geography.provenance} doc={doc} />
            </ul>
          </>
        )}
    </div>
  );
}
