/** Zero-server permalink routing (WO-5). Shareable deep-links live entirely in
 *  the URL hash so a static SPA restores state on load with no backend:
 *
 *    #/p/{person_id}   open that official's dossier
 *    #/d/{ocd_id}      select that division — its full representation stack + ballot
 *
 *  These coexist with the flat info hashes (#about / #privacy / #sources), which
 *  predate routing. Only `#/`-prefixed hashes are routes; anything else (a bare
 *  info hash or empty) is left for the existing InfoPage handling. Hash updates as
 *  the user navigates use replaceState so opening dossiers doesn't spam history.
 */

/** A parsed deep-link. `home` means no route hash is active (info hashes and the
 *  empty hash both fall here — the caller keeps owning those). */
export type Route =
  | { kind: "home" }
  | { kind: "person"; personId: string }
  | { kind: "division"; ocdId: string };

/** Parse the CURRENT location.hash into a route. Non-route hashes → home so the
 *  info-page handler keeps working unchanged. */
export function parseHash(hash: string = location.hash): Route {
  const h = hash.replace(/^#/, "");
  if (h.startsWith("/p/")) {
    const personId = decodeURIComponent(h.slice(3));
    return personId ? { kind: "person", personId } : { kind: "home" };
  }
  if (h.startsWith("/d/")) {
    const ocdId = decodeURIComponent(h.slice(3));
    return ocdId ? { kind: "division", ocdId } : { kind: "home" };
  }
  return { kind: "home" };
}

/** True when a hash is one of ours (`#/…`), so the info-hash handler can ignore
 *  it and vice-versa — the two schemes never fight over the same hash. */
export function isRouteHash(hash: string = location.hash): boolean {
  return /^#\/(p|d)\//.test(hash);
}

export function personHash(personId: string): string {
  return `#/p/${encodeURIComponent(personId)}`;
}
export function divisionHash(ocdId: string): string {
  return `#/d/${encodeURIComponent(ocdId)}`;
}

/** Write a route hash WITHOUT a history entry (replaceState) — opening dossiers
 *  as the user browses shouldn't stack the back button. */
export function replaceHash(hash: string): void {
  if (location.hash === hash) return;
  history.replaceState(null, "", hash || location.pathname + location.search);
}

/** Clear any route hash back to home (Escape / close), leaving path + query. */
export function clearRouteHash(): void {
  if (isRouteHash()) history.replaceState(null, "", location.pathname + location.search);
}
