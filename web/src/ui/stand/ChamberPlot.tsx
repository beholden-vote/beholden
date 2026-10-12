/** A scatter of every member of a chamber, with the viewed member(s) ringed.
 *  Symmetric by construction: one dot size, one opacity, one shape for everyone;
 *  party is only the existing data hue; draw order is file order (person_id), never
 *  by party; the ringed member is drawn last. Position is never colour-only: the ring
 *  is a shape, and a table of every coordinate sits beside the plot. */
import { PARTY_COLORS } from "../../map";
import { personHash } from "../../router";
import { STRINGS } from "../../strings";

export interface PlotPoint { id: string; name: string; party: string; x: number; y: number }
export interface PlotMark { id: string; label: string }

const SIZE = 300, PAD = 14;
const px = (v: number) => PAD + ((v + 1) / 2) * (SIZE - 2 * PAD);
const py = (v: number) => SIZE - PAD - ((v + 1) / 2) * (SIZE - 2 * PAD);

export function ChamberPlot({ title, points, marks, xName, yName, fmt = (n) => n.toFixed(2) }: {
  title: string; points: PlotPoint[]; marks: PlotMark[]; xName: string; yName: string;
  fmt?: (n: number) => string;
}) {
  const markIds = new Set(marks.map((m) => m.id));
  const rest = points.filter((p) => !markIds.has(p.id));
  const shown = marks.map((m) => ({ m, p: points.find((p) => p.id === m.id) }))
    .filter((x): x is { m: PlotMark; p: PlotPoint } => !!x.p);
  const summary = `${title}. ${points.length} members.` +
    shown.map(({ m, p }) => ` ${m.label ? m.label + ": " : ""}${p.name} at ${xName} ${fmt(p.x)}, ${yName} ${fmt(p.y)}.`).join("");
  const sorted = [...points].sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
  return (
    <figure className="stand-plot">
      <figcaption className="stand-plot-title">{title}</figcaption>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={summary} className="stand-plot-svg">
        <rect x={PAD} y={PAD} width={SIZE - 2 * PAD} height={SIZE - 2 * PAD} className="stand-plot-frame" />
        <line x1={px(0)} x2={px(0)} y1={PAD} y2={SIZE - PAD} className="stand-plot-axis" />
        <line y1={py(0)} y2={py(0)} x1={PAD} x2={SIZE - PAD} className="stand-plot-axis" />
        {rest.map((p) => (
          <circle key={p.id} cx={px(p.x)} cy={py(p.y)} r={2.6} className="stand-dot"
                  style={{ fill: PARTY_COLORS[p.party] ?? PARTY_COLORS.NP }}>
            <title>{`${p.name} (${p.party})`}</title>
          </circle>
        ))}
        {shown.map(({ m, p }, i) => (
          <g key={m.id} className={i ? "stand-mark stand-mark-b" : "stand-mark"}>
            <circle cx={px(p.x)} cy={py(p.y)} r={2.6} className="stand-dot" style={{ fill: PARTY_COLORS[p.party] ?? PARTY_COLORS.NP }} />
            <circle cx={px(p.x)} cy={py(p.y)} r={7.5} className="stand-ring" />
            {m.label && <text x={px(p.x)} y={py(p.y) - 11} textAnchor="middle" className="stand-mark-label">{m.label}</text>}
            <title>{`${p.name} (${p.party})`}</title>
          </g>
        ))}
        <text x={SIZE / 2} y={SIZE - 2} textAnchor="middle" className="stand-axis-name">{xName} →</text>
        <text x={8} y={SIZE / 2} textAnchor="middle" className="stand-axis-name" transform={`rotate(-90 8 ${SIZE / 2})`}>{yName} →</text>
      </svg>
      <details className="stand-plot-table">
        <summary>{STRINGS.standTable}</summary>
        <div className="stand-plot-scroll" tabIndex={0} role="region" aria-label={`${title}, table`}>
          <table className="vr-table">
            <thead><tr><th scope="col">Member</th><th scope="col">Party</th><th scope="col">{xName}</th><th scope="col">{yName}</th></tr></thead>
            <tbody>
              {sorted.map((p) => (
                <tr key={p.id} className={markIds.has(p.id) ? "is-marked" : undefined}>
                  <th scope="row" data-label="Member"><a href={personHash(p.id)}>{p.name}</a></th>
                  <td data-label="Party">{p.party}</td>
                  <td data-label={xName} className="mono">{fmt(p.x)}</td>
                  <td data-label={yName} className="mono">{fmt(p.y)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
