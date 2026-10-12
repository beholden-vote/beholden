/** The map colour-mode selector and its legend, mounted once in the layer control.
 *  One ramp for both numeric modes; the legend states the midpoint and what keeps
 *  party colour. Local layers ignore the mode (they are coverage-coloured). */
import { useSyncExternalStore } from "react";
import { COLOUR_MODES, RAMP, colourState, setColourMode, subscribeColour, type ColourMode } from "../../lib/positions";
import { STRINGS } from "../../strings";

export function ColourModeControl() {
  const s = useSyncExternalStore(subscribeColour, colourState);
  const fmt = (v: number) => (s.mode === "position" ? v.toFixed(2) : `${v.toFixed(1)}%`);
  return (
    <div className="layer-group colour-mode">
      <label className="grade-row">
        <span className="layer-group-label">{STRINGS.modeTitle}</span>
        <select className="grade-select" value={s.mode} onChange={(e) => setColourMode(e.target.value as ColourMode)}>
          {COLOUR_MODES.map((m) => <option key={m} value={m}>{STRINGS.modeLabels[m]}</option>)}
        </select>
      </label>
      {s.mode !== "party" && (
        <div className="legend ramp-legend" role="group" aria-label={STRINGS.modeLabels[s.mode]}>
          <div className="ramp-bar" aria-hidden="true" style={{ background: `linear-gradient(to right, ${RAMP.join(", ")})` }} />
          {s.status === "loading" && <span className="layer-ctl-hint" role="status">{STRINGS.modeLoading}</span>}
          {s.status === "unavailable" && <span className="layer-ctl-hint" role="status">{STRINGS.modeUnavailable}</span>}
          {s.status === "ready" && s.scale && (
            <>
              <div className="ramp-ends mono" aria-hidden="true">
                <span>{fmt(s.scale.lo)}</span><span>{fmt(s.scale.mid)}</span><span>{fmt(s.scale.hi)}</span>
              </div>
              <span className="layer-ctl-hint">
                {s.mode === "position"
                  ? STRINGS.modeRampPosition(fmt(s.scale.lo), fmt(s.scale.hi))
                  : STRINGS.modeRampRate(fmt(s.scale.mid), fmt(s.scale.lo), fmt(s.scale.hi))}
              </span>
              {s.fallback > 0 && <span className="layer-ctl-hint" role="status">{STRINGS.modeFallback(s.fallback)}</span>}
            </>
          )}
          <span className="layer-ctl-hint">{STRINGS.modeNotGoodBad}</span>
          <span className="layer-ctl-hint">{STRINGS.modeOthers}</span>
        </div>
      )}
    </div>
  );
}
