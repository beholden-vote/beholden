/** Small atoms shared by the votes views. Nothing here knows about party. */
import { useEffect, useRef } from "react";
import type { VotePosition } from "../../types";

const LABEL: Record<VotePosition, string> = { yea: "yea", nay: "nay", present: "present", not_voting: "not voting" };

/** A position as a word, never as colour alone. */
export function Position({ value }: { value: VotePosition }) {
  return <span className={`vote vote-${value}`}>{LABEL[value] ?? value}</span>;
}

export function Wait({ text }: { text: string }) {
  return <div className="view-wait"><h2 tabIndex={-1}>{text}</h2></div>;
}

/** The wait heading is replaced by the real one; if focus was on (or fell off)
 *  the old one, put it on the new. Never steals focus from a control in use. */
export function useHeadingFocus(ready: boolean) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (!ready) return;
    const a = document.activeElement;
    if (!a || a === document.body) ref.current?.focus();
  }, [ready]);
  return ref;
}
