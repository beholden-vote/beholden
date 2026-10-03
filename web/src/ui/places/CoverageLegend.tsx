/** Legend for the local-polygon fills (contracts 8.10). Every fill is explained
 *  in words as well as shown; the swatches use the same patterns as the map. */
import { STRINGS } from "../../strings";

const ORDER = ["covered", "partial", "withheld", "none"] as const;

export function CoverageLegend() {
  return (
    <div className="legend cov-legend" aria-label={STRINGS.coverageLegendTitle}>
      <span className="legend-title">{STRINGS.coverageLegendTitle}</span>
      {ORDER.map((k) => (
        <span className="legend-item legend-wide" key={k} title={STRINGS.coverageMeaning[k]}>
          <span className="area-cov-swatch" aria-hidden="true" data-cov={k} />
          {STRINGS.coverageLabels[k]}
        </span>
      ))}
      <span className="layer-ctl-hint">{STRINGS.coverageLegendNote}</span>
    </div>
  );
}
