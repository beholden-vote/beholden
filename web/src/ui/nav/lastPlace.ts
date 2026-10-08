/** The reader's last OWN place (an address, their location, or the remembered
 *  place), kept in memory so a record view can show "your representatives".
 *  history.ts fills it from emit(); nothing is stored or written to a URL, and a
 *  place opened from a map click or a #/d/ link never lands here. After a
 *  reload it is empty until the reader chooses a place again.
 *
 *  locate() and typeAddress() are the two ways to choose one. They drive the
 *  top bar's own controls, so the shell's behaviour stays in one place. */
import { useSyncExternalStore } from "react";
import type { RawStackHit } from "../../map";

let last: RawStackHit[] | null = null;
const listeners = new Set<() => void>();

export function setLastOwnPlace(hits: RawStackHit[]) {
  if (last === hits) return;
  last = hits;
  listeners.forEach((l) => l());
}

export const getLastOwnPlace = (): RawStackHit[] | null => last;

export function useLastOwnPlace(): RawStackHit[] | null {
  return useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l); }; }, getLastOwnPlace);
}

export function locate() {
  document.querySelector<HTMLButtonElement>(".topbar .loc-btn")?.click();
}

export function typeAddress() {
  document.querySelector<HTMLInputElement>('.topbar input[name="address"]')?.focus();
}
