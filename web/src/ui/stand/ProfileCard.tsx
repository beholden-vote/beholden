/** WO-38: a member's position profile in the dossier -- the measures, the two
 *  Voteview dimensions, and where they sit among their chamber. No composite. */
import { useEffect, useState } from "react";
import { findMember, type Found } from "../../lib/positions";
import { STRINGS } from "../../strings";
import { compareHash, methodologyHash } from "../../router";
import { MeasureRows, Nominate, PolicyAreas } from "./Measures";
import { Plots } from "./Plots";

export function ProfileCard({ personId }: { personId: string }) {
  const [found, setFound] = useState<Found | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    setFound(undefined);
    void findMember(personId).then((f) => { if (live) setFound(f); });
    return () => { live = false; };
  }, [personId]);

  if (found === undefined) return <p className="empty-note">{STRINGS.standLoading}</p>;
  if (found === null) return <p className="empty-note">{STRINGS.standNotPublished}</p>;
  const { file, member } = found;
  const others = file.members.filter((m) => m.person_id !== personId)
    .sort((a, b) => a.name.localeCompare(b.name) || a.person_id.localeCompare(b.person_id));
  return (
    <div className="stand">
      <p className="stand-note">{STRINGS.standLede}</p>
      <MeasureRows member={member} />
      <PolicyAreas member={member} />
      <h4 className="stand-h">{STRINGS.standNominate} <a className="kv-link" href={methodologyHash("dw-nominate")}>{STRINGS.standFormula} ↗</a></h4>
      <Nominate member={member} />
      <Plots file={file} marks={[{ id: personId, label: "" }]} />
      <label className="grade-row stand-compare">
        <span className="layer-group-label">{STRINGS.standCompareWith}</span>
        <select className="grade-select" value=""
                onChange={(e) => { if (e.target.value) location.hash = compareHash(personId, e.target.value); }}>
          <option value="">{STRINGS.standComparePick}</option>
          {others.map((m) => <option key={m.person_id} value={m.person_id}>{m.name} ({m.party}-{m.state})</option>)}
        </select>
      </label>
      <p className="stand-prov mono">{file.scope} · {STRINGS.standProvenance} · {file.provenance.retrieved_at.slice(0, 10)}</p>
    </div>
  );
}
