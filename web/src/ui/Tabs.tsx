/** Generic accessible tab bar (WO-11). WAI-ARIA tabs pattern with AUTOMATIC
 *  activation (selection follows focus): roving tabindex, ArrowLeft/Right cycle
 *  with wrap, Home/End jump. Unhandled keys are left alone — no stopPropagation
 *  or preventDefault — so App's window keydown stays the only Escape owner.
 *  Purely presentational: the active tab is owned by the caller. */
import { useRef } from "react";

export function TabBar<T extends string>({ tabs, active, onSelect, idPrefix }: {
  tabs: readonly { id: T; label: string }[];
  active: T;
  onSelect: (id: T) => void;
  idPrefix: string;
}) {
  const btnRefs = useRef(new Map<T, HTMLButtonElement>());

  // Select a tab and keep it in view inside the (horizontally scrollable) bar.
  const select = (id: T, focus: boolean) => {
    onSelect(id);
    const el = btnRefs.current.get(id);
    if (focus) el?.focus();
    el?.scrollIntoView({ inline: "nearest", block: "nearest" });
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === active);
    let next: number;
    if (e.key === "ArrowRight") next = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;   // unhandled keys (Escape included) bubble untouched
    e.preventDefault();
    select(tabs[next].id, true);   // automatic activation: selection follows focus
  };

  return (
    <div className="dtab-bar" role="tablist" onKeyDown={onKeyDown}>
      {tabs.map((t) => (
        <button
          key={t.id} type="button" role="tab" className="dtab"
          id={`${idPrefix}-tab-${t.id}`}
          aria-selected={t.id === active}
          aria-controls={`${idPrefix}-panel-${t.id}`}
          tabIndex={t.id === active ? 0 : -1}
          ref={(el) => { if (el) btnRefs.current.set(t.id, el); else btnRefs.current.delete(t.id); }}
          onClick={() => select(t.id, false)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
