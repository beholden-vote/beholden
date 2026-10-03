/** A member's full record (contracts 8.3 /votes/{person_id}.json): every roll
 *  call they were eligible for, newest first, with filters that combine.
 *  The summary line is the file's own; it is never recomputed here. */
import { useEffect, useId, useMemo, useState } from "react";
import type { PersonVotes, RecordedVote } from "../../types";
import { formatDate } from "../../lib/data";
import { loadVotes } from "../../lib/votes";
import { billHash, voteHash } from "../../router";
import { STRINGS } from "../../strings";
import { EmptyNote, Section } from "../bits";
import { Position } from "./bits";

const PAGE = 50;

/** The published party-agreement rule: only yea/nay, only where the party had a position. */
const againstParty = (v: RecordedVote) =>
  (v.position === "yea" || v.position === "nay") && v.party_position !== null && v.position !== v.party_position;

const distinct = (xs: (string | null)[]) =>
  [...new Set(xs.filter((x): x is string => !!x))].sort((a, b) => a.localeCompare(b));

export function VoteRecord({ personId }: { personId: string }) {
  const [file, setFile] = useState<PersonVotes | null | undefined>(undefined);
  const [topic, setTopic] = useState("");
  const [result, setResult] = useState("");
  const [against, setAgainst] = useState(false);
  const [shown, setShown] = useState(PAGE);
  const id = useId();

  useEffect(() => {
    let live = true;
    void loadVotes(personId).then((f) => { if (live) setFile(f); });
    return () => { live = false; };
  }, [personId]);

  const votes = file?.votes;
  const topics = useMemo(() => distinct((votes ?? []).map((v) => v.policy_area)), [votes]);
  const results = useMemo(() => distinct((votes ?? []).map((v) => v.result)), [votes]);
  const rows = useMemo(
    () => (votes ?? []).filter((v) => (!topic || v.policy_area === topic) && (!result || v.result === result) && (!against || againstParty(v))),
    [votes, topic, result, against],
  );

  if (file === undefined) return <EmptyNote>{STRINGS.recordLoading}</EmptyNote>;
  if (file === null) return <EmptyNote>{STRINGS.recordAbsent}</EmptyNote>;
  const s = file.summary;
  const filtered = !!(topic || result || against);
  const reset = () => { setTopic(""); setResult(""); setAgainst(false); setShown(PAGE); };
  // A filter change starts the list over at the newest rows.
  const on = <T,>(set: (v: T) => void) => (v: T) => { set(v); setShown(PAGE); };

  return (
    <Section title={STRINGS.recordTitle} provenance={file.provenance}>
      <p className="vr-summary mono">
        {file.scope} · {s.total} votes: {s.yea} yea, {s.nay} nay, {s.present} present, {s.not_voting} not voting.
        {" "}With own party on {s.with_party} of {s.party_decided} party-decided votes; against on {s.against_party}.
      </p>
      {file.votes.length === 0 ? <EmptyNote>{STRINGS.recordEmpty}</EmptyNote> : (
        <>
          <form className="vr-filters" aria-label={STRINGS.recordFilters} onSubmit={(e) => e.preventDefault()}>
            <label htmlFor={`${id}-t`}>{STRINGS.filterTopic}</label>
            <select id={`${id}-t`} className="grade-select" value={topic} onChange={(e) => on(setTopic)(e.target.value)}>
              <option value="">{STRINGS.filterTopicAll}</option>
              {topics.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <label htmlFor={`${id}-r`}>{STRINGS.filterResult}</label>
            <select id={`${id}-r`} className="grade-select" value={result} onChange={(e) => on(setResult)(e.target.value)}>
              <option value="">{STRINGS.filterResultAll}</option>
              {results.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <label className="vr-check">
              <input type="checkbox" checked={against} onChange={(e) => on(setAgainst)(e.target.checked)} />
              {STRINGS.filterAgainst}
            </label>
            {filtered && <button type="button" className="fix-ghost" onClick={reset}>{STRINGS.filterClear}</button>}
          </form>
          <p className="vr-count mono" role="status" aria-live="polite">
            {rows.length} of {file.votes.length} votes shown
          </p>
          {rows.length === 0 ? <EmptyNote>{STRINGS.filterNoMatch}</EmptyNote> : (
            <table className="vr-table">
              <caption className="visually-hidden">{STRINGS.recordTitle}, newest first</caption>
              <thead>
                <tr><th scope="col">Date</th><th scope="col">Vote</th><th scope="col">Position</th><th scope="col">Result</th></tr>
              </thead>
              <tbody>
                {rows.slice(0, shown).map((v) => (
                  <tr key={v.roll_call_id}>
                    <td data-label="Date" className="mono">{formatDate(v.held_at) ?? v.held_at}</td>
                    <td data-label="Vote">
                      <a href={voteHash(v.roll_call_id)} data-nav-id={v.roll_call_id}>{v.question}</a>
                      {v.bill_id && v.bill_title
                        ? <span className="vr-bill"><a href={billHash(v.bill_id)}>{v.bill_title}</a></span>
                        : <span className="vr-bill muted">{STRINGS.notOnBill}</span>}
                      {v.policy_area && <span className="mv-policy-chip">{v.policy_area}</span>}
                    </td>
                    <td data-label="Position">
                      <Position value={v.position} />
                      {againstParty(v) && <span className="vr-against">{STRINGS.againstTag}</span>}
                    </td>
                    <td data-label="Result" className="mono">{v.result} · {v.yea_count}–{v.nay_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {rows.length > shown && (
            <button type="button" className="fix-ghost" onClick={() => setShown((n) => n + PAGE)}>
              {STRINGS.recordMore} ({rows.length - shown})
            </button>
          )}
        </>
      )}
    </Section>
  );
}
