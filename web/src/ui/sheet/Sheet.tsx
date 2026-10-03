/** The panel shell: a right-hand drawer on a wide screen, a bottom sheet on a
 *  narrow one.
 *
 *  Below 720px the old panel was a drawer the full width of the phone, so the
 *  map vanished the moment it became useful. The sheet keeps it: three stops --
 *  PEEK (the header strip), HALF, FULL -- with the map visible and interactive
 *  above it at peek and half.
 *
 *  No library: the stop is a data attribute, the position is a CSS transform
 *  (styles.css), and a drag is pointer events on the handle writing that
 *  transform directly until release. The handle is a real button -- click steps the sheet, Up and
 *  Down arrows resize it, Home/End jump to the ends. Focus is trapped only at
 *  FULL, where the sheet is the whole screen; at peek and half the map and the
 *  search bar stay reachable. At peek the hidden body is inert, so Tab cannot
 *  wander into content that is off screen. prefers-reduced-motion drops the
 *  slide (styles.css).
 */
import {
  useEffect, useRef, useSyncExternalStore,
  type KeyboardEvent, type PointerEvent, type ReactNode, type RefObject,
} from "react";
import { STRINGS } from "../../strings";

export type SheetStop = "peek" | "half" | "full";
const STOPS: SheetStop[] = ["peek", "half", "full"];

/** The width below which the panel is a sheet. Mirrors the media query in styles.css. */
export const NARROW = "(max-width: 719px)";
/** Height of the strip left showing at peek. Mirrors --sheet-peek in styles.css. */
const PEEK_PX = 76;

function watchNarrow(onChange: () => void) {
  const m = window.matchMedia(NARROW);
  m.addEventListener("change", onChange);
  return () => m.removeEventListener("change", onChange);
}
export function useNarrow(): boolean {
  return useSyncExternalStore(watchNarrow, () => window.matchMedia(NARROW).matches);
}

const FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

export function Sheet({ sheetRef, label, stop, onStop, onClose, header, children }: {
  sheetRef: RefObject<HTMLElement | null>;
  label: string;
  stop: SheetStop;
  onStop: (s: SheetStop) => void;
  onClose: () => void;
  /** The non-scrolling strip: what stays visible at peek. */
  header: ReactNode;
  children: ReactNode;
}) {
  const narrow = useNarrow();
  const handleRef = useRef<HTMLButtonElement>(null);
  const drag = useRef<{ y0: number; base: number; dy: number; live: boolean } | null>(null);
  const dragged = useRef(false);
  const modal = narrow && stop === "full";

  /** Distance the sheet is pushed down at a stop, for a sheet `h` tall. */
  const yOf = (s: SheetStop, h: number) => (s === "full" ? 0 : s === "half" ? h / 2 : h - PEEK_PX);
  const at = (i: number) => STOPS[Math.min(STOPS.length - 1, Math.max(0, i))];
  const step = (d: number) => onStop(at(STOPS.indexOf(stop) + d));

  // At FULL the sheet is the screen: bring focus inside so the trap holds.
  useEffect(() => {
    if (modal && !sheetRef.current?.contains(document.activeElement)) handleRef.current?.focus();
  }, [modal, sheetRef]);

  const onPointerDown = (e: PointerEvent<HTMLButtonElement>) => {
    const el = sheetRef.current;
    dragged.current = false;
    if (!narrow || !el) return;
    // Captured from the first touch: a quick flick leaves the handle within a
    // frame, and its moves must keep arriving here.
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { y0: e.clientY, base: yOf(stop, el.offsetHeight), dy: 0, live: false };
  };
  const onPointerMove = (e: PointerEvent<HTMLButtonElement>) => {
    const d = drag.current, el = sheetRef.current;
    if (!d || !el) return;
    d.dy = e.clientY - d.y0;
    if (!d.live) {
      if (Math.abs(d.dy) < 6) return;          // a tap, not a drag -- leave it to click
      d.live = true;
      el.classList.add("is-dragging");
    }
    const max = el.offsetHeight - PEEK_PX;
    el.style.transform = `translateY(${Math.min(max, Math.max(0, d.base + d.dy))}px)`;
  };
  const onPointerEnd = () => {
    const d = drag.current, el = sheetRef.current;
    drag.current = null;
    if (!d?.live || !el) return;
    dragged.current = true;
    el.classList.remove("is-dragging");
    el.style.transform = "";
    // Settle on the nearest stop; a short, deliberate flick still moves one.
    const h = el.offsetHeight, y = d.base + d.dy;
    let next = STOPS.reduce((a, b) => (Math.abs(yOf(b, h) - y) < Math.abs(yOf(a, h) - y) ? b : a));
    if (next === stop && Math.abs(d.dy) > 40) next = at(STOPS.indexOf(stop) + (d.dy < 0 ? 1 : -1));
    onStop(next);
  };

  const onHandleKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowUp") step(1);
    else if (e.key === "ArrowDown") step(-1);
    else if (e.key === "Home") onStop("full");
    else if (e.key === "End") onStop("peek");
    else return;
    e.preventDefault();
  };

  const trapTab = (e: KeyboardEvent<HTMLElement>) => {
    const el = sheetRef.current;
    if (e.key !== "Tab" || !modal || !el) return;
    const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((n) => n.offsetParent !== null);
    if (items.length === 0) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey ? document.activeElement === first : document.activeElement === last) {
      e.preventDefault();
      (e.shiftKey ? last : first).focus();
    }
  };

  return (
    <aside ref={sheetRef} className="panel" data-stop={stop} role="dialog" aria-label={label}
           aria-modal={modal || undefined} onKeyDown={trapTab}>
      <div className="sheet-grip">
        <button ref={handleRef} type="button" className="sheet-handle"
                onPointerDown={onPointerDown} onPointerMove={onPointerMove}
                onPointerUp={onPointerEnd} onPointerCancel={onPointerEnd}
                aria-label={`${STRINGS.sheetHandle}: ${STRINGS.sheetStops[stop]}. ${STRINGS.sheetHandleHint}`}
                onClick={() => { if (!dragged.current) onStop(stop === "half" ? "full" : "half"); }}
                onKeyDown={onHandleKey}>
          <span aria-hidden="true" />
        </button>
      </div>
      <div className="sheet-head">
        {header}
        <button type="button" className="close-btn" onClick={onClose} aria-label={STRINGS.panelClose}>&times;</button>
      </div>
      <div className="sheet-body" inert={narrow && stop === "peek"}>
        {children}
      </div>
    </aside>
  );
}
