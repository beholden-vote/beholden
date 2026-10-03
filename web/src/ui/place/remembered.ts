/** The remembered place: the one thing about the reader this site keeps.
 *
 *  WHAT   one map point -- a longitude and a latitude -- that the reader
 *         confirmed by searching an address or by granting the browser's
 *         location permission. Never the approximate arrival fix, never the
 *         address text, never a history of places: a new one overwrites it.
 *  WHERE  this browser's localStorage, under the key below. Nowhere else: not
 *         a cookie, not the URL, not history.state, not a request.
 *  WHY    so the next visit opens on the reader's own representatives.
 *  GONE   forgetPlace() removes the key at once.
 *
 *  This is a public promise (see Privacy() in ui/chrome.tsx and the arrival
 *  strings in strings.ts). If what is stored here changes, that copy changes in
 *  the same commit.
 */
const KEY = "beholden:place";

export interface PlacePoint { lng: number; lat: number }

export function loadPlace(): PlacePoint | null {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return p && Number.isFinite(p.lng) && Number.isFinite(p.lat) ? { lng: p.lng, lat: p.lat } : null;
  } catch {
    return null;   // storage blocked, or a value we did not write
  }
}

export function savePlace(p: PlacePoint): void {
  try { localStorage.setItem(KEY, JSON.stringify({ v: 1, lng: p.lng, lat: p.lat })); } catch { /* not remembered; the place still opens */ }
}

export function forgetPlace(): void {
  try { localStorage.removeItem(KEY); } catch { /* nothing was stored */ }
}

/** Is this point the one saved on the device right now? Read from storage each
 *  time, so a "saved" label can never outlive the value it describes. */
export function isSavedPlace(p: PlacePoint | undefined): boolean {
  const s = loadPlace();
  return !!p && !!s && s.lng === p.lng && s.lat === p.lat;
}
