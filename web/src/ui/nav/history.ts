/** The history model: three altitudes with real history.
 *
 *  The reader is always at one altitude -- a PLACE (an area and everyone who
 *  represents it), a PERSON (a dossier) or a RECORD (a bill, a roll call, a
 *  comparison) -- or at HOME, the map with nothing open. The rules:
 *
 *    - moving between views PUSHES a history entry, so the browser's Back
 *      button steps up one level and Forward returns;
 *    - changing a tab inside a dossier, or clicking from one explored district
 *      to the next, REPLACES the entry, so neither stacks up Back presses;
 *    - Escape steps up one entry of the trail; from its top it closes the panel.
 *
 *  Each entry carries only an index in history.state. What that entry SHOWS is
 *  kept here, in memory, for as long as the page is open. That is deliberate:
 *  a place is the list of districts under a point, and for the reader's own
 *  place neither the point nor the list belongs in a URL or in session history.
 *  After a reload the memory is gone and an entry is rebuilt from its URL alone,
 *  which is exactly what a shared link gets.
 *
 *  Entries the browser makes by itself -- a plain <a href="#/p/...">, an info
 *  link such as #methodology/key-votes, a hand-edited address -- arrive with no
 *  state and are adopted as a push on top of the current entry. So any view can
 *  link to any other with an ordinary anchor and still get Back, the trail and
 *  focus handling.
 */
import { useSyncExternalStore } from "react";
import type { RawStackHit } from "../../map";
import { isRouteHash, parseHash, personHash, routeHash, divisionHash, type DossierTab, type Route } from "../../router";
import { hitTitle, hitsFromOcd, smallestDivision } from "../place/divisions";
import { RECORD_LABELS, RECORD_VIEWS, type RecordRoute } from "./registry";

/** How a place came to be on screen. The first three are the reader's OWN
 *  place and are never written into the address bar. */
export type PlaceOrigin =
  | "approximate"   // the edge's coarse guess on arrival
  | "confirmed"     // an address, or the browser's location, this visit
  | "remembered"    // the confirmed place from an earlier visit
  | "map"           // a click on the map
  | "link";         // a #/d/ link

export interface PlaceState {
  kind: "place";
  hits: RawStackHit[];
  origin: PlaceOrigin;
  title: string;
  /** The point behind an own place. Memory only: it decides whether this is
   *  the place saved on the device, and is never serialised from here. */
  point?: { lng: number; lat: number };
}

export type View =
  | { kind: "home" }
  | PlaceState
  | { kind: "person"; personId: string; tab: DossierTab; title?: string }
  | { kind: "record"; route: RecordRoute; title?: string };

const HOME: View = { kind: "home" };

export const isOwnPlace = (v: View): boolean => v.kind === "place" && v.origin !== "map" && v.origin !== "link";

/** What a route opens. A kind the registry cannot draw, or a division we do
 *  not map, is home -- never a placeholder. */
export function viewFromRoute(route: Route): View {
  switch (route.kind) {
    case "person":
      return { kind: "person", personId: route.personId, tab: route.tab ?? "overview" };
    case "division": {
      const hits = hitsFromOcd(route.ocdId);
      return hits ? { kind: "place", hits, origin: "link", title: hitTitle(hits[0]) } : HOME;
    }
    case "bill": case "vote": case "compare":
      return RECORD_VIEWS[route.kind] ? { kind: "record", route } : HOME;
    default:
      return HOME;
  }
}

/** The hash that addresses a view. The reader's own place has none: it lives
 *  at the bare URL, so nothing about where they are reaches the address bar. */
function hashFor(view: View): string {
  switch (view.kind) {
    case "person": return personHash(view.personId, view.tab);
    case "record": return routeHash(view.route);
    case "place": {
      const local = isOwnPlace(view) ? null : smallestDivision(view.hits);
      return local ? divisionHash(local.ocdId) : "";
    }
    default: return "";
  }
}
const urlFor = (view: View) => location.pathname + location.search + hashFor(view);

export function titleOf(view: View): string {
  switch (view.kind) {
    case "place": return view.title;
    case "person": return view.title ?? "Dossier";
    case "record": return view.title ?? RECORD_LABELS[view.route.kind];
    default: return "Map";
  }
}

/* ---- the store ---------------------------------------------------------- */

export type Move = "boot" | "push" | "replace" | "back" | "forward";
export interface NavSnapshot { index: number; view: View; move: Move }

const views = new Map<number, View>();
/** What had focus when the reader left an entry going forward, so coming back
 *  can return it: the element itself if it is still on the page, else the
 *  element now carrying the same data-nav-id (a re-rendered row). */
const openers = new Map<number, { el: Element | null; id?: string }>();
let cur = 0;
let snap: NavSnapshot | null = null;
const listeners = new Set<() => void>();

function emit(move: Move) {
  snap = { index: cur, view: views.get(cur)!, move };
  listeners.forEach((l) => l());
}
function prune() {
  for (const k of [...views.keys()]) if (k > cur) { views.delete(k); openers.delete(k); }
}
function leave() {
  const el = document.activeElement;
  const id = el?.closest<HTMLElement>("[data-nav-id]")?.dataset.navId;
  openers.set(cur, { el, id });
}
function indexOf(state: unknown): number | null {
  const i = (state as { i?: unknown } | null)?.i;
  return typeof i === "number" ? i : null;
}

/** history.go() lands later, on a popstate. Until it does, a second Escape (a
 *  held key repeats) or a second click must not start another traversal: two
 *  would walk straight off the site. The timer covers a go() that had nowhere
 *  to go and so never lands. */
let travelling = 0;
function go(delta: number) {
  if (travelling || delta === 0) return;
  travelling = window.setTimeout(() => { travelling = 0; }, 600);
  history.go(delta);
}

function sync() {
  window.clearTimeout(travelling); travelling = 0;
  const i = indexOf(history.state);
  if (i === null) {
    // The browser made this entry itself (see the header). Adopt it as a push.
    // A route hash opens its view; anything else -- an info hash -- lies over
    // the view already showing.
    const under = views.get(cur)!;
    leave();
    cur += 1; prune();
    const route = isRouteHash();
    const view = route ? viewFromRoute(parseHash()) : under;
    views.set(cur, view);
    history.replaceState({ i: cur }, "", route ? urlFor(view) : location.href);
    return emit(route ? "push" : "replace");
  }
  // popstate and hashchange both fire for one traversal; the second is a no-op.
  if (i === cur && views.has(i)) return;
  const move: Move = i < cur ? "back" : "forward";
  cur = i;
  // An entry from before a reload: all we have is its URL.
  if (!views.has(i)) views.set(i, viewFromRoute(parseHash()));
  emit(move);
}

function boot() {
  cur = indexOf(history.state) ?? 0;
  const view = viewFromRoute(parseHash());
  views.set(cur, view);
  // A route we cannot draw must not sit in the address bar claiming otherwise.
  history.replaceState({ i: cur }, "", isRouteHash() ? urlFor(view) : location.href);
  window.addEventListener("popstate", sync);
  window.addEventListener("hashchange", sync);
  snap = { index: cur, view, move: "boot" };
}

function getSnapshot(): NavSnapshot {
  if (!snap) boot();
  return snap!;
}
function subscribe(l: () => void) {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

/** The current entry. Re-renders on every navigation. */
export function useNav(): NavSnapshot {
  return useSyncExternalStore(subscribe, getSnapshot);
}

export interface Crumb { label: string; href: string; delta: number }

export const nav = {
  current: (): View => getSnapshot().view,

  /** Go to a view as a new history entry. */
  push(view: View) {
    getSnapshot();
    leave();
    cur += 1; prune();
    views.set(cur, view);
    history.pushState({ i: cur }, "", urlFor(view));
    emit("push");
  },

  /** Swap the current entry's view in place (a tab, the next district). */
  replace(view: View) {
    getSnapshot();
    views.set(cur, view);
    history.replaceState({ i: cur }, "", urlFor(view));
    emit("replace");
  },

  /** Name the current view for the trail once its name is known. Leaves the
   *  URL alone -- an info overlay may be lying over it. */
  retitle(title: string) {
    const v = getSnapshot().view;
    if (v.kind === "home" || v.kind === "place" || v.title === title) return;
    v.title = title;
    emit("replace");
  },

  /** The trail actually walked, oldest first, ending at the current view. It
   *  stops at home and at anything from before a reload, so a page opened cold
   *  shows only itself. `delta` is the history.go() distance to that crumb. */
  trail(): Crumb[] {
    getSnapshot();
    const out: Crumb[] = [];
    let above: View | null = null;
    for (let j = cur; views.has(j); j--) {
      const v = views.get(j)!;
      if (v.kind === "home") break;
      if (v === above) continue;        // an info-overlay entry over the same view
      above = v;
      out.unshift({ label: titleOf(v), href: urlFor(v), delta: j - cur });
    }
    return out;
  },

  /** Walk the browser's history by `delta` entries (a breadcrumb click). */
  go,

  /** Close the panel: back to the map. If the map-only entry sits directly
   *  under the trail, closing IS going back to it; otherwise it is a new entry,
   *  so Back reopens what was closed. */
  close() {
    if (getSnapshot().view.kind === "home") return;
    let j = cur;
    while (views.has(j - 1) && views.get(j - 1)!.kind !== "home") j--;
    if (views.get(j - 1)?.kind === "home") go(j - 1 - cur);
    else nav.push(HOME);
  },

  /** Step up one altitude (Escape); from the top of the trail, close. */
  up() {
    if (nav.trail().length > 1) go(-1);
    else nav.close();
  },

  /** Lay an info page (#about, #methodology/...) over the current view. A new
   *  entry with the same view beneath; page-to-page inside the overlay swaps. */
  overlay(hash: string, swap: boolean) {
    const view = getSnapshot().view;
    if (swap) history.replaceState({ i: cur }, "", hash);
    else {
      leave();
      cur += 1; prune();
      views.set(cur, view);
      history.pushState({ i: cur }, "", hash);
    }
    emit("replace");
  },

  /** Take the info page away again: back to the entry it was laid over, or,
   *  for a page opened cold from an info link, drop the hash. */
  closeOverlay() {
    getSnapshot();
    if (views.get(cur - 1) === views.get(cur)) go(-1);
    else nav.replace(views.get(cur)!);
  },

  /** The control to return focus to after coming back to the current entry. */
  opener(): HTMLElement | null {
    const o = openers.get(cur);
    if (!o) return null;
    if (o.el instanceof HTMLElement && o.el.isConnected && o.el !== document.body) return o.el;
    return o.id ? document.querySelector<HTMLElement>(`[data-nav-id="${CSS.escape(o.id)}"]`) : null;
  },
};
