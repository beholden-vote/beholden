/** The two chamber plots for a positions file: DW-NOMINATE and the similarity map. */
import type { PositionsFile } from "../../types";
import { STRINGS } from "../../strings";
import { personHash } from "../../router";
import { ChamberPlot, type PlotMark, type PlotPoint } from "./ChamberPlot";

export function Plots({ file, marks }: { file: PositionsFile; marks: PlotMark[] }) {
  const nom: PlotPoint[] = [], lay: PlotPoint[] = [];
  const unplaced: { id: string; name: string }[] = [];
  for (const m of file.members) {
    const b = { id: m.person_id, name: m.name, party: m.party };
    if (m.nominate && m.nominate.dim1 != null && m.nominate.dim2 != null) nom.push({ ...b, x: m.nominate.dim1, y: m.nominate.dim2 });
    if (m.layout) lay.push({ ...b, x: m.layout.x, y: m.layout.y }); else unplaced.push(b);
  }
  unplaced.sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
  const absent = (pts: PlotPoint[]) => marks.filter((m) => !pts.some((p) => p.id === m.id));
  return (
    <>
      <ChamberPlot title={STRINGS.standPlotNominate} points={nom} marks={marks}
                   xName={STRINGS.standDim1} yName={STRINGS.standDim2} />
      {absent(nom).map((m) => (
        <p className="empty-note" key={m.id}>{m.label ? `${m.label}: ` : ""}{STRINGS.standDim1} / {STRINGS.standDim2} {STRINGS.standNotPublishedValue}.</p>
      ))}
      <ChamberPlot title={STRINGS.standPlotLayout} points={lay} marks={marks} xName="Map x" yName="Map y" fmt={(n) => n.toFixed(3)} />
      {absent(lay).map((m) => (
        <p className="empty-note" key={m.id}>{m.label ? `${m.label}: ` : ""}{STRINGS.standNotPlaced}.</p>
      ))}
      <p className="stand-note">{STRINGS.standPlotNote}</p>
      <p className="stand-unplaced">
        <b>{STRINGS.standNotPlaced}: </b>
        {unplaced.length === 0 ? STRINGS.standNotPlacedNone : unplaced.map((u, i) => (
          <span key={u.id}>{i > 0 && ", "}<a href={personHash(u.id)}>{u.name}</a></span>
        ))}
      </p>
    </>
  );
}
