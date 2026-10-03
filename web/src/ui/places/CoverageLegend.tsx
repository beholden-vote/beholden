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

/** What the boundary lines mean. Levels differ by width, dash and strength, never
 *  by hue, so no level reads as louder for any party. */
export function LineLegend() {
  return (
    <div className="legend" aria-label="Boundary line legend">
      <span className="legend-title">Lines = boundary</span>
      <span className="legend-item legend-wide"><span className="line-swatch line-state" aria-hidden="true" />State outline, always on</span>
      <span className="legend-item legend-wide"><span className="line-swatch line-primary" aria-hidden="true" />Level you are zoomed to</span>
      <span className="legend-item legend-wide"><span className="line-swatch line-ref" aria-hidden="true" />Level just left, fading</span>
    </div>
  );
}
