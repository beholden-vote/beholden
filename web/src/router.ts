/** Client routes (docs/DATA-CONTRACTS.md section 8.6). Deep links live entirely
 *  in the URL hash, so a static SPA restores state on load with no backend:
 *
 *    #/p/{person_id}[/{tab}]        a dossier, optionally on a tab
 *    #/d/{ocd_id}                   a place: a division and who represents it
 *    #/b/{bill_id}                  a bill
 *    #/v/{roll_call_id}             a roll call
 *    #/c/{person_id}/{person_id}    two officials compared
 *
 *  Ids are written with encodeURIComponent. This file only parses and builds
 *  hashes; WHEN a hash is pushed or replaced is the history model's business
 *  (ui/nav/history.ts), and which component draws a bill, a roll call or a
 *  comparison is the view registry's (ui/nav/registry.ts).
 *
 *  These coexist with the flat info hashes (#about / #privacy / #sources /
 *  #methodology[/anchor]), which predate routing. Only `#/`-prefixed hashes are
 *  routes; anything else is left to the info overlay.
 *
 *  A reader's own location is never written into a URL: a place is addressed by
 *  division id, and a remembered place lives in the browser's storage only.
 */

/** The dossier tabs (WO-11; WO-16 adds "social"), in display order. The hash's
 *  optional tab segment is whitelisted against this -- an unknown segment
 *  degrades to the default tab, it never breaks the person link. */
export const DOSSIER_TABS = ["overview", "record", "committees", "money", "connections", "social"] as const;
export type DossierTab = (typeof DOSSIER_TABS)[number];

/** A parsed deep link. `home` means no route hash is active (info hashes, the
 *  empty hash and anything malformed all land here). A person route's `tab` is
 *  null when the hash names none, or names junk -- the caller defaults. */
export type Route =
  | { kind: "home" }
  | { kind: "person"; personId: string; tab: DossierTab | null }
  | { kind: "division"; ocdId: string }
  | { kind: "bill"; billId: string }
  | { kind: "vote"; rollCallId: string }
  | { kind: "compare"; a: string; b: string };

const HOME: Route = { kind: "home" };

/** decodeURIComponent throws on a stray "%"; a mangled link is home, not a crash. */
function decode(segment: string | undefined): string {
  try { return decodeURIComponent(segment ?? ""); } catch { return ""; }
}

/** Parse a hash (default: the current one) into a route. */
export function parseHash(hash: string = location.hash): Route {
  const m = /^#\/([pdbvc])\/(.+)$/.exec(hash);
  if (!m) return HOME;
  // Split BEFORE decoding: a literal "/" inside an id is written %2F, so the
  // segment boundary is unambiguous.
  const segs = m[2].split("/");
  const first = decode(segs[0]);
  switch (m[1]) {
    case "p": {
      // Segment 2 is a tab only if whitelisted; extra segments are ignored.
      const tab = (DOSSIER_TABS as readonly string[]).includes(segs[1]) ? (segs[1] as DossierTab) : null;
      return first ? { kind: "person", personId: first, tab } : HOME;
    }
    case "d": {
      // The whole remainder: a hand-typed, unencoded OCD id carries its own slashes.
      const ocdId = decode(m[2]);
      return ocdId ? { kind: "division", ocdId } : HOME;
    }
    case "b": return first ? { kind: "bill", billId: first } : HOME;
    case "v": return first ? { kind: "vote", rollCallId: first } : HOME;
    default: {
      const second = decode(segs[1]);
      return first && second ? { kind: "compare", a: first, b: second } : HOME;
    }
  }
}

/** True when a hash is one of ours (`#/x/...`), so the info-hash handling can
 *  ignore it and vice versa -- the two schemes never fight over the same hash. */
export function isRouteHash(hash: string = location.hash): boolean {
  return /^#\/[pdbvc]\//.test(hash);
}

/** Person permalink. The tab segment is appended only for a non-default tab,
 *  so old links stay bit-identical and copied links stay short. */
export function personHash(personId: string, tab?: DossierTab | null): string {
  const base = `#/p/${encodeURIComponent(personId)}`;
  return tab && tab !== "overview" ? `${base}/${tab}` : base;
}
export function divisionHash(ocdId: string): string {
  return `#/d/${encodeURIComponent(ocdId)}`;
}
export function billHash(billId: string): string {
  return `#/b/${encodeURIComponent(billId)}`;
}
export function voteHash(rollCallId: string): string {
  return `#/v/${encodeURIComponent(rollCallId)}`;
}
export function compareHash(a: string, b: string): string {
  return `#/c/${encodeURIComponent(a)}/${encodeURIComponent(b)}`;
}

/** The hash that addresses a route ("" for home). */
export function routeHash(route: Route): string {
  switch (route.kind) {
    case "person": return personHash(route.personId, route.tab);
    case "division": return divisionHash(route.ocdId);
    case "bill": return billHash(route.billId);
    case "vote": return voteHash(route.rollCallId);
    case "compare": return compareHash(route.a, route.b);
    default: return "";
  }
}

/** Methodology page hash (WO-8). A flat info hash like #about/#privacy/#sources --
 *  NOT a `#/`-prefixed route. An optional in-page anchor rides after a slash
 *  (`#methodology/key-votes`) so a dossier's "how is this computed?" link opens
 *  the page scrolled to the right section. */
export function methodologyHash(anchor?: string): string {
  return anchor ? `#methodology/${anchor}` : "#methodology";
}

/** Parse a hash into a methodology target, or null if it isn't one.
 *  `{ anchor: null }` = the page with no specific section. */
export function parseMethodologyHash(hash: string = location.hash): { anchor: string | null } | null {
  const h = hash.replace(/^#/, "");
  if (h === "methodology") return { anchor: null };
  if (h.startsWith("methodology/")) return { anchor: h.slice("methodology/".length) || null };
  return null;
}

// TEMPORARY (WO-35 recovery commit only): App.tsx still calls these until it is
// rewired onto ui/nav/history.ts in the next commit, which deletes them.
export function replaceHash(hash: string): void {
  if (location.hash === hash) return;
  history.replaceState(null, "", hash || location.pathname + location.search);
}
export function clearRouteHash(): void {
  if (isRouteHash()) history.replaceState(null, "", location.pathname + location.search);
}
