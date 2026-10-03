/** "How your representatives voted": the reader's own federal representatives
 *  (from the last own place) and their recorded position on this vote or bill.
 *  A representative with no recorded position says so; nothing is inferred.
 *  Only federal offices vote in these files, so only they are listed. */
import { useEffect, useState } from "react";
import type { Pin, PersonVotes, RollCall, VotePosition } from "../../types";
import { loadPins, type PinIndex } from "../../lib/data";
import { loadVotes } from "../../lib/votes";
import { LEVEL_ORDER } from "../../lib/levels";
import { personHash, voteHash } from "../../router";
import { STRINGS } from "../../strings";
import { EmptyNote, PartyChip, Section } from "../bits";
import { locate, typeAddress, useLastOwnPlace } from "../nav/lastPlace";
import { Position } from "./bits";

let pinsPromise: Promise<PinIndex> | null = null;

type Target =
  | { kind: "vote"; rollCall: RollCall }
  | { kind: "bill"; billId: string };

function Line({ pin, target }: { pin: Pin; target: Target }) {
  const [file, setFile] = useState<PersonVotes | null | undefined>(target.kind === "bill" ? undefined : null);
  useEffect(() => {
    if (target.kind !== "bill") return;
    let live = true;
    void loadVotes(pin.person_id).then((f) => { if (live) setFile(f); });
    return () => { live = false; };
  }, [pin.person_id, target.kind]);

  let body;
  if (target.kind === "vote") {
    const p = target.rollCall.positions.find((x) => x.person_id === pin.person_id);
    body = p ? <Position value={p.position} /> : <span className="muted">{STRINGS.repsNone}</span>;
  } else if (file === undefined) {
    body = <span className="muted">{STRINGS.recordLoading}</span>;
  } else {
    const mine = (file?.votes ?? []).filter((v) => v.bill_id === target.billId);
    body = mine.length === 0 ? <span className="muted">{STRINGS.repsNone}</span> : (
      <ul className="plain-list">
        {mine.map((v) => (
          <li key={v.roll_call_id}>
            <Position value={v.position as VotePosition} />{" "}
            <a href={voteHash(v.roll_call_id)}>{v.question}</a>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <tr>
      <td data-label="Representative"><a href={personHash(pin.person_id)}>{pin.full_name ?? pin.person_id}</a></td>
      <td data-label="Party"><PartyChip code={pin.party} /></td>
      <td data-label="Position">{body}</td>
    </tr>
  );
}

export function Reps({ target }: { target: Target }) {
  const hits = useLastOwnPlace();
  const [pins, setPins] = useState<PinIndex | null>(null);
  useEffect(() => {
    pinsPromise ??= loadPins();
    let live = true;
    void pinsPromise.then((p) => { if (live) setPins(p); });
    return () => { live = false; };
  }, []);

  if (!hits) {
    return (
      <Section title={STRINGS.repsTitle}>
        <EmptyNote>{STRINGS.repsNoPlace}</EmptyNote>
        <div className="fix-actions">
          <button type="button" className="fix-primary" onClick={locate}>{STRINGS.fixLocate}</button>
          <button type="button" className="fix-ghost" onClick={typeAddress}>{STRINGS.fixAddress}</button>
        </div>
      </Section>
    );
  }
  const federal = hits.filter((h) => h.layer === "cd" || h.layer === "states")
    .sort((a, b) => (LEVEL_ORDER[a.layer] ?? 9) - (LEVEL_ORDER[b.layer] ?? 9));
  const rows = federal.flatMap((h) => pins?.get(h.layer)?.get(h.ocdId) ?? []).filter((p) => !p.vacant);
  return (
    <Section title={STRINGS.repsTitle}>
      {pins === null ? <EmptyNote>{STRINGS.placeLoading}</EmptyNote>
        : rows.length === 0 ? <EmptyNote>{STRINGS.repsNoFederal}</EmptyNote> : (
          <table className="vr-table">
            <thead><tr><th scope="col">Representative</th><th scope="col">Party</th><th scope="col">Position</th></tr></thead>
            <tbody>{rows.map((p) => <Line key={p.person_id} pin={p} target={target} />)}</tbody>
          </table>
        )}
    </Section>
  );
}
