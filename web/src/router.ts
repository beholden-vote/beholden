/** Zero-server permalink routing (WO-5). Shareable deep-links live entirely in
 *  the URL hash so a static SPA restores state on load with no backend:
 *
 *    #/p/{person_id}         open that official's dossier
 *    #/p/{person_id}/{tab}   …opened on a specific dossier tab (WO-11)
 *    #/d/{ocd_id}            select that division — its full representation stack + ballot
 *
 *  These coexist with the flat info hashes (#about / #privacy / #sources), which
 *  predate routing. Only `#/`-prefixed hashes are routes; anything else (a bare
 *  info hash or empty) is left for the existing InfoPage handling. Hash updates as
 *  the user navigates use replaceState so opening dossiers doesn't spam history.
 */

/** The dossier tabs (WO-11), in display order. The hash's optional tab segment is
 *  whitelisted against this — an unknown segment degrades to the default tab, it
 *  never breaks the person link. */
export const DOSSIER_TABS = ["overview", "record", "committees", "money", "connections"] as const;
export type DossierTab = (typeof DOSSIER_TABS)[number];

/** A parsed deep-link. `home` means no route hash is active (info hashes and the
 *  empty hash both fall here — the caller keeps owning those). A person route's
 *  `tab` is null when the hash names none (or names junk) — the caller defaults. */
export type Route =
  | { kind: "home" }
  | { kind: "person"; personId: string; tab: DossierTab | null }
  | { kind: "division"; ocdId: string };

/** Parse the CURRENT location.hash into a route. Non-route hashes → home so the
 *  info-page handler keeps working unchanged. */
export function parseHash(hash: string = location.hash): Route {
  const h = hash.replace(/^#/, "");
  if (h.startsWith("/p/")) {
    // Split BEFORE decoding: ids are written via encodeURIComponent, so a literal
    // "/" inside an id is %2F — the segment boundary is unambiguous. Segment 2 is
    // a tab only if whitelisted (junk like #/p/X/banana degrades to the default
    // tab, never breaks the person link); extra segments are ignored.
    const segs = h.slice(3).split("/");
    const personId = decodeURIComponent(segs[0]);
    const tab = segs.length > 1 && (DOSSIER_TABS as readonly string[]).includes(segs[1])
      ? (segs[1] as DossierTab)
      : null;
    return personId ? { kind: "person", personId, tab } : { kind: "home" };
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

/** Person permalink. The tab segment is appended only when it's a non-default
 *  tab — old links stay bit-identical and copy-links stay short/canonical. */
export function personHash(personId: string, tab?: DossierTab): string {
  const base = `#/p/${encodeURIComponent(personId)}`;
  return tab && tab !== "overview" ? `${base}/${tab}` : base;
}
export function divisionHash(ocdId: string): string {
  return `#/d/${encodeURIComponent(ocdId)}`;
}

/** Methodology page hash (WO-8). A flat info hash like #about/#privacy/#sources —
 *  NOT a `#/`-prefixed route — so it coexists with the router without either
 *  scheme touching the other. An optional in-page anchor rides after a slash
 *  (`#methodology/key-votes`) so a dossier's "how is this computed?" link opens
 *  the page scrolled to the right section. `parseMethodologyHash` reads it back. */
export function methodologyHash(anchor?: string): string {
  return anchor ? `#methodology/${anchor}` : "#methodology";
}

/** Parse the CURRENT hash into a methodology target, or null if it isn't one.
 *  `{ anchor: null }` = the page with no specific section. Recognizes both the
 *  flat `#methodology` and `#methodology/<anchor>` forms. */
export function parseMethodologyHash(hash: string = location.hash): { anchor: string | null } | null {
  const h = hash.replace(/^#/, "");
  if (h === "methodology") return { anchor: null };
  if (h.startsWith("methodology/")) {
    const anchor = h.slice("methodology/".length);
    return { anchor: anchor || null };
  }
  return null;
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
