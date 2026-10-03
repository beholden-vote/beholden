/** The reader shell. Composition only: the map chrome (search, layer dock,
 *  level toast, footer, info overlays) around ONE panel, which shows whichever
 *  view the history model says is current.
 *
 *    ui/nav/    where the reader is: history, breadcrumb, view registry, search
 *    ui/place/  a place and everyone who represents it; the remembered place
 *    ui/sheet/  the panel itself: a drawer when wide, a bottom sheet when narrow
 *
 *  What is left here is the wiring between them and the map: which place a map
 *  click or an address opens, when that pushes history and when it replaces,
 *  where focus goes, and how the reader arrives.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_VISIBLE } from "../map";
import type { BeholdenMap, RawStackHit, LayerId, LayerMode } from "../map";
import { loadPins, type PinIndex } from "../lib/data";
import { geolocate } from "../lib/lookup";
import { GATES, gateForZoom, type Gate } from "../lib/levels";
import { methodologyHash, parseMethodologyHash } from "../router";
import { STRINGS } from "../strings";
import { Footer, InfoOverlay, LayerControl, LevelToast, type InfoPage } from "./chrome";
import { GradeFilterProvider, loadMinGrade, saveMinGrade, type Grade } from "./gradeFilter";
import { Breadcrumb } from "./nav/Breadcrumb";
import { isOwnPlace, nav, titleOf, useNav, type PlaceOrigin, type View } from "./nav/history";
import { SearchBar } from "./nav/SearchBar";
import { PersonView, RecordView } from "./nav/views";
import { ArrivePrompt, PlaceView } from "./place/PlaceView";
import { placeTitle } from "./place/divisions";
import { loadPlace, savePlace } from "./place/remembered";
import { NARROW, Sheet, type SheetStop } from "./sheet/Sheet";

/** How long the "you crossed into a new level" marker stays up. Long enough to
 *  read four words, short enough not to sit over the map you just zoomed into. */
const LEVEL_TOAST_MS = 2400;

const LAYER_PREFS_KEY = "beholden:layers";
const LAYER_PREFS_VERSION = 2;
// Versioned prefs blob (WO-2): { version, mode, visible }. v1 was a bare
// Record<LayerId, boolean> (no mode) -- see loadLayerPrefs for the migration.
type LayerPrefs = { version: number; mode: LayerMode; visible: Record<LayerId, boolean> };

function loadLayerPrefs(): LayerPrefs {
  const fallback: LayerPrefs = { version: LAYER_PREFS_VERSION, mode: "auto", visible: { ...DEFAULT_VISIBLE } };
  try {
    const raw = localStorage.getItem(LAYER_PREFS_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    // v2+: full blob with an explicit mode.
    if (parsed && typeof parsed === "object" && "visible" in parsed) {
      const visible = { ...DEFAULT_VISIBLE, ...parsed.visible };
      const mode: LayerMode = parsed.mode === "manual" ? "manual" : "auto";
      return { version: LAYER_PREFS_VERSION, mode, visible };
    }
    // v1 migration: a bare visibility map with no mode. Default to "auto", but if
    // the user had deviated from the old defaults, honor that as a "manual" choice
    // rather than silently overriding what they'd picked.
    const visible = { ...DEFAULT_VISIBLE, ...parsed };
    const deviated = (Object.keys(DEFAULT_VISIBLE) as LayerId[])
      .some((id) => visible[id] !== DEFAULT_VISIBLE[id]);
    return { version: LAYER_PREFS_VERSION, mode: deviated ? "manual" : "auto", visible };
  } catch { /* fall through to defaults */ }
  return fallback;
}

// Info overlays are hash-linkable: the flat #about / #privacy / #sources, plus
// WO-8's #methodology (and #methodology/<anchor> to open a specific section).
type InfoState = { page: InfoPage; anchor?: string | null };
function hashToInfo(): InfoState | null {
  const h = location.hash.replace("#", "");
  if (h === "about" || h === "privacy" || h === "sources") return { page: h };
  const meth = parseMethodologyHash();
  if (meth) return { page: "methodology", anchor: meth.anchor };
  return null;
}

export interface AppHandle {
  onMapSelect: (hits: RawStackHit[], lngLat: { lng: number; lat: number }) => void;
  onZoomLevel: (zoom: number) => void;
}

/** A flight to the reader's OWN place, awaiting the map's answer. The map
 *  reports every selection the same way; the point is how one of ours is told
 *  from a click. */
interface OwnFlight {
  lng: number; lat: number;
  origin: PlaceOrigin;
  /** Refill the map-only entry instead of stepping past it (arrival after a reload). */
  fill: boolean;
}

export function App({ mapRef, handleRef }: {
  mapRef: { current: BeholdenMap | null };
  handleRef: { current: AppHandle | null };
}) {
  const snap = useNav();
  const { view, move } = snap;
  const [pins, setPins] = useState<PinIndex | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [prompt, setPrompt] = useState(false);
  const [stop, setStop] = useState<SheetStop>("half");
  const [prefs, setPrefs] = useState<LayerPrefs>(loadLayerPrefs);
  // WO-28 source-quality floor. Persisted like layer prefs; defaults to "D"
  // (show everything) so grading informs trust without hiding records.
  const [minGrade, setMinGrade] = useState<Grade>(loadMinGrade);
  const changeMinGrade = (g: Grade) => { setMinGrade(g); saveMinGrade(g); };
  // Level of government the current zoom is showing, and the transient marker
  // shown when we cross into it.
  const [gate, setGate] = useState<Gate>(GATES[0]);
  const [toast, setToast] = useState<Gate | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const sheetRef = useRef<HTMLElement>(null);
  const flight = useRef<OwnFlight | null>(null);
  /** The "you are here" marker already shows a confirmed point; a late guess must not move it. */
  const exact = useRef(false);
  /** The view about to open was not asked for (arrival): it must not take focus. */
  const unasked = useRef(false);
  // An info page is opened and closed only by navigations, and every navigation
  // yields a new snapshot -- so the hash is read once per snapshot.
  const info = useMemo(hashToInfo, [snap]);

  useEffect(() => { void loadPins().then(setPins); }, []);

  // Push mode + layer choices to the map and remember them on this device.
  // Order matters: set the mode first (it swaps the sld* fade expressions), then
  // seed the desired per-layer visibility so a manual set applies immediately.
  useEffect(() => {
    const m = mapRef.current;
    if (m) {
      m.setLayerMode(prefs.mode);
      (Object.keys(prefs.visible) as LayerId[]).forEach((id) => m.setLayerVisible(id, prefs.visible[id]));
    }
    try { localStorage.setItem(LAYER_PREFS_KEY, JSON.stringify(prefs)); } catch { /* ok */ }
  }, [prefs, mapRef]);

  /* ---- opening things ---------------------------------------------------- */

  const openPerson = useCallback((personId: string, title?: string) => {
    nav.push({ kind: "person", personId, tab: "overview", title });
  }, []);

  /** Fly to the reader's own place; the map answers through onMapSelect. */
  const goOwn = useCallback((lng: number, lat: number, origin: PlaceOrigin, fill = false) => {
    flight.current = { lng, lat, origin, fill };
    setMsg(null);
    const m = mapRef.current;
    exact.current = origin !== "approximate";
    m?.setUserLocation(lng, lat, exact.current);
    // A phone's sheet opens over the lower half of the map: land the point in
    // the band left visible between the search field and the sheet.
    m?.goTo(lng, lat, 9, window.matchMedia(NARROW).matches ? -0.2 * window.innerHeight : 0);
  }, [mapRef]);

  const onMapSelect = useCallback((hits: RawStackHit[], at: { lng: number; lat: number }) => {
    const f = flight.current;
    const own = f && f.lng === at.lng && f.lat === at.lat ? f : null;
    if (own) flight.current = null;
    if (hits.length === 0) {
      if (!own) nav.close();                                  // a click on open water closes the panel
      else if (own.origin === "confirmed") setMsg(STRINGS.nothingThere);
      else setPrompt(true);                                   // no districts under the guess: ask instead
      return;
    }
    const cur = nav.current();
    const next: View = {
      kind: "place", hits, title: placeTitle(hits),
      origin: own?.origin ?? "map", point: own ? { lng: at.lng, lat: at.lat } : undefined,
    };
    // Remembered only when the reader confirmed it -- never the edge's guess.
    if (own?.origin === "confirmed") savePlace(at);
    unasked.current = !!own && own.origin !== "confirmed";
    setPrompt(false);
    // The next district explored, or a guess corrected, takes the place of the
    // one on screen. Anything else is a step the Back button can undo.
    const swap = cur.kind === "place" ? isOwnPlace(cur) === isOwnPlace(next) : cur.kind === "home" && !!own?.fill;
    if (swap) nav.replace(next); else nav.push(next);
    // One division with one official under a click (only the U.S. House layer
    // on, say): go straight in, with the place one step back.
    const only = !own && hits.length === 1 ? pins?.get(hits[0].layer)?.get(hits[0].ocdId) : undefined;
    if (only?.length === 1) openPerson(only[0].person_id, only[0].full_name);
  }, [pins, openPerson]);

  // Which level of government the current zoom is showing. The map reports raw
  // zoom on every frame; we keep only the GATE, so state updates happen on the
  // handful of crossings rather than on every wheel tick.
  const onZoomLevel = useCallback((zoom: number) => {
    const next = gateForZoom(zoom);
    setGate((prev) => (prev.id === next.id ? prev : next));
  }, []);

  useEffect(() => { handleRef.current = { onMapSelect, onZoomLevel }; },
    [onMapSelect, onZoomLevel, handleRef]);

  // Announce a crossing, then let it go. Skips the first render: arriving at
  // "Federal" is the starting state, not a transition worth interrupting for.
  const firstGate = useRef(true);
  useEffect(() => {
    if (firstGate.current) { firstGate.current = false; return; }
    setToast(gate);
    const t = window.setTimeout(() => setToast(null), LEVEL_TOAST_MS);
    return () => window.clearTimeout(t);
  }, [gate]);

  /* ---- the reader's own place -------------------------------------------- */

  const locate = useCallback(async () => {
    setBusy(true); setMsg(null);
    try {
      const { lng, lat } = await geolocate();
      goOwn(lng, lat, "confirmed");
    } catch (err) {
      setMsg((err as GeolocationPositionError)?.code === 1 ? STRINGS.locateDenied : STRINGS.locateFailed);
      setStop((s) => (s === "full" ? "half" : s));            // the message sits by the search field
    } finally {
      setBusy(false);
    }
  }, [goOwn]);

  const typeAddress = useCallback(() => {
    setStop((s) => (s === "full" ? "half" : s));              // at full the sheet covers the search field
    searchRef.current?.focus();
  }, []);

  const fix = { onLocate: locate, onTypeAddress: typeAddress, busy };

  // Arrive on the reader's own area: once, and only on a load whose URL asked
  // for nothing. The place they confirmed on an earlier visit comes first; the
  // edge's coarse guess second; with neither, the national map and a prompt.
  // A load that DID ask for something keeps what it always had: the marker.
  const arrived = useRef(false);
  useEffect(() => {
    if (arrived.current) return;
    arrived.current = true;
    const cold = nav.current().kind === "home" && !hashToInfo();
    // After a reload this entry was already a step past the map: refill it.
    const fill = snap.index > 0;
    const saved = loadPlace();
    if (saved) {
      if (cold) goOwn(saved.lng, saved.lat, "remembered", fill);
      else mapRef.current?.setUserLocation(saved.lng, saved.lat, true);
      return;
    }
    fetch("/api/whereami")
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null)
      .then((w) => {
        const here = w && typeof w.lat === "number" && typeof w.lng === "number" ? w : null;
        // The reader may have opened or searched for something while we asked.
        if (cold && nav.current().kind === "home" && !flight.current) {
          if (here) goOwn(here.lng, here.lat, "approximate", fill); else setPrompt(true);
        } else if (here && !exact.current) mapRef.current?.setUserLocation(here.lng, here.lat, false);
      });
  }, [goOwn, mapRef, snap.index]);

  /* ---- moving between views ---------------------------------------------- */

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (hashToInfo()) nav.closeOverlay();
      else if (nav.current().kind === "home") setPrompt(false);
      else nav.up();                                          // one altitude; from the top, close
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const heading = () => sheetRef.current?.querySelector<HTMLElement>(".sheet-body h2") ?? null;

  // A view replaced its own heading (loading -> dossier, or -> not found). If
  // focus was on the old one it fell to the page; put it on the new one.
  const onReady = useCallback(() => {
    const a = document.activeElement;
    if (a && a !== document.body) return;
    const h = heading();
    if (h) { h.tabIndex = -1; h.focus(); }
  }, []);

  // On every change of view: a new view takes focus on its heading; a view
  // come back to returns focus to the control that left it.
  const shown = useRef(view);
  const wantFocus = useRef<"heading" | "opener" | null>(null);
  useEffect(() => {
    const prev = shown.current;
    shown.current = view;
    const quiet = unasked.current;
    unasked.current = false;
    if (prev === view) return;                                // renamed, or an info page over it
    if (view.kind === "home") mapRef.current?.clearSelection();
    else {
      // Show what was asked for: never leave a new view folded away at peek.
      setStop((s) => (s === "peek" || prev.kind === "home" ? "half" : s));
      if (prev.kind === "person" && view.kind === "person" && prev.personId === view.personId) return;   // a tab
      const body = sheetRef.current?.querySelector(".sheet-body");
      if (body) body.scrollTop = 0;
      // The reader is working the map (district after district): leave focus there.
      if (move === "replace" && document.activeElement?.closest("#root")) return;
      // Arrival opened this by itself. Taking focus would move a reader who did nothing.
      if (quiet) return;
    }
    wantFocus.current = move === "back" ? "opener" : view.kind === "home" ? null : "heading";
  }, [view, move, mapRef]);
  // Applied after the render in which the sheet's body is no longer inert.
  useEffect(() => {
    const want = wantFocus.current;
    if (!want || sheetRef.current?.querySelector(".sheet-body[inert]")) return;
    wantFocus.current = null;
    const el = (want === "opener" ? nav.opener() : null) ?? heading();
    if (!el) return;
    if (/^H\d$/.test(el.tagName)) el.tabIndex = -1;           // a heading takes focus by script only
    el.focus();
  });

  /* ---- map chrome -------------------------------------------------------- */

  // Touching any per-layer box is an explicit choice -> drop to manual and stick.
  const toggleLayer = (id: LayerId, v: boolean) =>
    setPrefs((p) => ({ ...p, mode: "manual", visible: { ...p.visible, [id]: v } }));
  // Auto master toggle. Re-checking Auto restores zoom-driven behavior; the stored
  // per-layer visibility is left intact so unchecking Auto again returns to it.
  const setAuto = (on: boolean) => setPrefs((p) => ({ ...p, mode: on ? "auto" : "manual" }));
  // An info page lies over the current view as its own history entry, so Back
  // closes it; moving between info pages swaps that entry.
  const openInfo = (p: InfoPage, anchor?: string | null) =>
    nav.overlay(p === "methodology" ? methodologyHash(anchor ?? undefined) : `#${p}`, !!info);

  return (
    <GradeFilterProvider value={minGrade}>
      <div className="topbar">
        <div className="brand">
          <span className="brand-name">Beholden</span>
          <span className="brand-tag">power, on the public record</span>
        </div>
        <SearchBar inputRef={searchRef} busy={busy} setBusy={setBusy} message={msg} setMessage={setMsg}
                   onPlace={(lng, lat) => goOwn(lng, lat, "confirmed")}
                   onPerson={(row) => openPerson(row.person_id, row.full_name)}
                   onLocate={locate} />
        {prompt && view.kind === "home" && <ArrivePrompt {...fix} onDismiss={() => setPrompt(false)} />}
      </div>

      {view.kind !== "home" && (
        <Sheet sheetRef={sheetRef} label={titleOf(view)} stop={stop} onStop={setStop} onClose={nav.close}
               header={<Breadcrumb trail={nav.trail()} />}>
          {view.kind === "place" && (
            <PlaceView view={view} pins={pins} fix={fix}
                       onOpenPerson={(pin) => openPerson(pin.person_id, pin.full_name)} />
          )}
          {view.kind === "person" && (
            <PersonView key={view.personId} personId={view.personId} tab={view.tab} onReady={onReady} />
          )}
          {view.kind === "record" && <RecordView route={view.route} onReady={onReady} />}
        </Sheet>
      )}

      <LevelToast gate={toast} />
      <LayerControl visible={prefs.visible} auto={prefs.mode === "auto"}
                    onToggle={toggleLayer} onAuto={setAuto}
                    minGrade={minGrade} onMinGrade={changeMinGrade}
                    activeGate={gate.id} />
      <Footer onOpen={openInfo} />
      {info && (
        <InfoOverlay page={info.page} anchor={info.anchor} onClose={nav.closeOverlay}
                     onOpenInfo={(p) => openInfo(p)} />
      )}
    </GradeFilterProvider>
  );
}
