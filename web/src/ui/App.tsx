/** UI layer over the map: address search, the representation-stack panel
 *  ("who represents this point"), and the drill-down dossier view. */
import { useCallback, useEffect, useRef, useState } from "react";
import type { Dossier, Pin, StackEntry } from "../types";
import { DEFAULT_VISIBLE } from "../map";
import type { BeholdenMap, RawStackHit, LayerId, LayerMode } from "../map";
import {
  loadDossier, loadPins, loadPeopleIndex, ocdShortLabel,
  type PinIndex, type PersonSearchRow,
} from "../lib/data";
import { geocode, geolocate, suggest, type Place } from "../lib/lookup";
import { Avatar, EmptyNote, PartyChip } from "./bits";
import { DossierView } from "./DossierView";
import { Ballot } from "./Ballot";
import { Footer, InfoOverlay, LayerControl, type InfoPage } from "./chrome";
import {
  parseHash, isRouteHash, personHash, replaceHash, clearRouteHash,
  type Route,
} from "../router";

const LEVEL_TITLES: Record<string, string> = {
  cd: "U.S. House",
  states: "U.S. Senate",
  sldu: "State Senate",
  sldl: "State House",
  county: "County",
};
// Federal first, then state chambers, then local (county) — the same order for
// every point on the map.
const LEVEL_ORDER: Record<string, number> = { cd: 0, states: 1, sldu: 2, sldl: 3, county: 4 };

// Panel sections mirror the layer control's level axis (Federal / State / Local;
// City reserved for later). Entries are bucketed by layer into these sections.
const PANEL_SECTIONS: { level: string; layers: LayerId[] }[] = [
  { level: "Federal", layers: ["cd", "states"] },
  { level: "State", layers: ["sldu", "sldl"] },
  { level: "Local", layers: ["county"] },
];

const LAYER_PREFS_KEY = "beholden:layers";
const LAYER_PREFS_VERSION = 2;
// Versioned prefs blob (WO-2): { version, mode, visible }. v1 was a bare
// Record<LayerId, boolean> (no mode) — see loadLayerPrefs for the migration.
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
function hashToPage(): InfoPage | null {
  const h = location.hash.replace("#", "");
  return h === "about" || h === "privacy" || h === "sources" ? h : null;
}

type PanelState =
  | { kind: "closed" }
  | { kind: "stack"; entries: StackEntry[] }
  | { kind: "ballot"; entries: StackEntry[] }
  | { kind: "dossier"; dossier: Dossier; from?: StackEntry[] };

// The pin-index feed a division's ocd_id belongs to (its map layer). Used to
// resolve a #/d/{ocd_id} deep-link to the pins under that division.
function layerOfOcd(ocdId: string): LayerId | null {
  if (/\/sldu:/.test(ocdId)) return "sldu";
  if (/\/sldl:/.test(ocdId)) return "sldl";
  if (/\/(county|parish|borough):/.test(ocdId)) return "county";
  if (/\/cd:/.test(ocdId)) return "cd";
  if (/\/state:[a-z]{2}$/.test(ocdId)) return "states";
  return null;
}

export interface AppHandle {
  onMapSelect: (hits: RawStackHit[], lngLat: { lng: number; lat: number }) => void;
}

/** One collapsible level section (Federal / State) in the representation stack.
 *  Default open; the header shows the officeholder count as a mono badge (kept
 *  visible when collapsed so the level's weight reads at a glance). */
function StackSection({ level, entries, onOpen }: {
  level: string;
  entries: StackEntry[];
  onOpen: (pin: Pin) => void;
}) {
  const [open, setOpen] = useState(true);
  const count = entries.reduce((n, e) => n + e.pins.length, 0);
  return (
    <section className="stack-section">
      <button type="button" className="stack-section-head" aria-expanded={open}
              onClick={() => setOpen((v) => !v)}>
        <span className="stack-section-caret" aria-hidden>{open ? "▾" : "▸"}</span>
        <span className="stack-section-label">{level}</span>
        <span className="stack-section-count">{count}</span>
      </button>
      {open && entries.map((entry) => (
        <div className="stack-level" key={`${entry.layer}:${entry.ocdId}`}>
          <h3>
            {LEVEL_TITLES[entry.layer] ?? entry.layer}
            <span className="stack-div">{ocdShortLabel(entry.ocdId)}</span>
          </h3>
          {entry.pins.length === 0 ? (
            <EmptyNote>
              {entry.layer === "sldu" || entry.layer === "sldl"
                ? "State-legislature profiles arrive with the state data layer."
                : entry.layer === "county"
                ? "County officials arrive with the local data layer."
                : "No officeholder published for this division yet."}
            </EmptyNote>
          ) : (
            entry.pins.map((pin) => (
              <button className="person-row" key={pin.person_id} onClick={() => onOpen(pin)}>
                <Avatar url={pin.photo_url} name={pin.full_name ?? "?"} size={40} />
                <span className="person-name">
                  {pin.vacant ? "Vacant seat" : pin.full_name ?? "View profile"}
                </span>
                <PartyChip code={pin.party} />
                <span className="person-go">→</span>
              </button>
            ))
          )}
        </div>
      ))}
    </section>
  );
}

export function App({ mapRef, handleRef }: {
  mapRef: { current: BeholdenMap | null };
  handleRef: { current: AppHandle | null };
}) {
  const [pins, setPins] = useState<PinIndex | null>(null);
  const [panel, setPanel] = useState<PanelState>({ kind: "closed" });
  const [busy, setBusy] = useState(false);
  const [searchMsg, setSearchMsg] = useState<string | null>(null);
  const [places, setPlaces] = useState<Place[]>([]);
  const [people, setPeople] = useState<PersonSearchRow[]>([]);   // name matches (WO-5)
  const [activeIdx, setActiveIdx] = useState(-1);                // keyboard nav across suggestions
  const [prefs, setPrefs] = useState<LayerPrefs>(loadLayerPrefs);
  const layerVis = prefs.visible;
  const [info, setInfo] = useState<InfoPage | null>(hashToPage);
  const searchRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<number | undefined>(undefined);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => { loadPins().then(setPins); }, []);

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

  // Info pages are hash-linkable (#about / #privacy / #sources).
  useEffect(() => {
    const onHash = () => setInfo(hashToPage());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Open a dossier by id. `byPin`/`from` are optional context: a map/stack open
  // carries the pin (for the back-target) — a #/p/ deep-link has neither and
  // fetches straight from the id. Writes the permalink hash (replaceState).
  const openDossier = useCallback(async (personId: string, from?: StackEntry[]) => {
    setBusy(true);
    const dossier = await loadDossier(personId);
    setBusy(false);
    if (dossier) {
      setPanel({ kind: "dossier", dossier, from });
      replaceHash(personHash(personId));
    }
  }, []);

  const entriesFromHits = useCallback((hits: RawStackHit[]): StackEntry[] =>
    hits
      .map((h) => ({ layer: h.layer, ocdId: h.ocdId, pins: pins?.get(h.layer)?.get(h.ocdId) ?? [] }))
      .sort((a, b) => (LEVEL_ORDER[a.layer] ?? 9) - (LEVEL_ORDER[b.layer] ?? 9)),
  [pins]);

  const onMapSelect = useCallback((hits: RawStackHit[], _lngLat: { lng: number; lat: number }) => {
    if (hits.length === 0) return setPanel({ kind: "closed" });
    const entries = entriesFromHits(hits);
    // One person under the point (just a lone CD rep at low zoom)? Go straight in.
    const people = entries.flatMap((e) => e.pins);
    if (people.length === 1 && entries.length === 1) void openDossier(people[0].person_id, entries);
    else setPanel({ kind: "stack", entries });
  }, [entriesFromHits, openDossier]);

  useEffect(() => { handleRef.current = { onMapSelect }; }, [onMapSelect, handleRef]);

  // Open a division's representation from a #/d/{ocd_id} deep-link. Zero-server:
  // we resolve the division's pins straight from the pin index (no coordinate /
  // no map fly needed to render "who represents this division"), and stack them.
  const openDivision = useCallback((ocdId: string) => {
    const layer = layerOfOcd(ocdId);
    const pinsHere = layer ? pins?.get(layer)?.get(ocdId) ?? [] : [];
    if (!layer) return setPanel({ kind: "closed" });
    const entries: StackEntry[] = [{ layer, ocdId, pins: pinsHere }];
    setPanel({ kind: "stack", entries });
  }, [pins]);

  // Permalink routing (WO-5): #/p/{id} and #/d/{ocd_id}. Runs on load once the
  // pin index is ready (division links need it), and on every user-driven
  // hashchange. Flat info hashes are handled by the info-hash effect below and
  // are ignored here. openDossier's own replaceState never fires hashchange, so
  // there's no restore loop. We only ACT on route hashes — a plain "#" from
  // closing an overlay leaves whatever panel is open untouched.
  const applyRoute = useCallback((route: Route) => {
    if (route.kind === "person") void openDossier(route.personId);
    else if (route.kind === "division") openDivision(route.ocdId);
  }, [openDossier, openDivision]);

  const routedOnLoad = useRef(false);
  useEffect(() => {
    // Wait for pins so a division deep-link resolves; a person link needs none,
    // but running once keeps the entry point single.
    if (routedOnLoad.current || !pins) return;
    routedOnLoad.current = true;
    applyRoute(parseHash());
  }, [pins, applyRoute]);

  useEffect(() => {
    const onHash = () => { if (isRouteHash()) applyRoute(parseHash()); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [applyRoute]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setInfo(null);
      setPanel({ kind: "closed" });
      mapRef.current?.clearSelection();
      clearRouteHash();   // Escape clears any deep-link back to home (#)
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mapRef]);

  // Dismiss the suggestion dropdown (both groups) and reset keyboard focus.
  const clearSuggest = useCallback(() => {
    setPlaces([]); setPeople([]); setActiveIdx(-1);
  }, []);

  const flyTo = useCallback((lng: number, lat: number) => {
    clearSuggest(); setSearchMsg(null);
    mapRef.current?.setUserLocation(lng, lat, true);   // exact "you are here"
    mapRef.current?.goTo(lng, lat, 9);
  }, [mapRef, clearSuggest]);

  // Pick a person from the People suggestions: jump straight to their dossier
  // (the permalink hash is written by openDossier), clearing the search UI.
  const pickPerson = useCallback((row: PersonSearchRow) => {
    clearSuggest(); setSearchMsg(null);
    if (searchRef.current) searchRef.current.value = "";
    void openDossier(row.person_id);
  }, [clearSuggest, openDossier]);

  // Ambient bearings without a permission prompt: coarse IP location from our own
  // edge (/api/whereami) drops a faint marker so the map isn't a blank field.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/whereami")
      .then((r) => (r.ok ? r.json() : null))
      .then((w) => {
        if (!cancelled && w && typeof w.lat === "number" && typeof w.lng === "number") {
          mapRef.current?.setUserLocation(w.lng, w.lat, false);
        }
      })
      .catch(() => { /* no bearings marker — fine */ });
    return () => { cancelled = true; };
  }, [mapRef]);

  // Debounced typeahead over BOTH indexes (WO-5): a query with no digits looks
  // like a name → search the lazy people index; anything address-shaped (or that
  // still returns people) also hits the Census geocoder. The two result groups
  // render together in one dropdown. Each keystroke cancels the last lookup.
  const onSearchInput = (ev: React.ChangeEvent<HTMLInputElement>) => {
    const q = ev.target.value;
    window.clearTimeout(debounceRef.current);
    setActiveIdx(-1);
    if (q.trim().length < 3) { clearSuggest(); return; }
    const looksLikeAddress = /\d/.test(q);   // digits ⇒ street number / ZIP
    debounceRef.current = window.setTimeout(async () => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      // People: only for name-shaped queries (no digits). Index + minisearch are
      // lazy-loaded on the first such keystroke, then cached.
      if (!looksLikeAddress) {
        loadPeopleIndex().then((idx) => {
          if (!ac.signal.aborted) setPeople(idx?.search(q) ?? []);
        });
      } else {
        setPeople([]);
      }
      // Addresses: the Census geocoder wants a fairly complete address, so short
      // name-only queries won't match — that's fine, the People group carries them.
      setPlaces(await suggest(q, ac.signal));
    }, 320);
  };

  const submitSearch = async (ev: React.FormEvent) => {
    ev.preventDefault();
    const q = searchRef.current?.value.trim();
    if (!q) return;
    // Enter with a highlighted suggestion picks it; otherwise fall through to a
    // geocode of the typed text.
    if (activeIdx >= 0 && activeIdx < suggestions.length) {
      return activateSuggestion(suggestions[activeIdx]);
    }
    // A name-shaped query with a single confident person match jumps to them
    // rather than failing an address geocode.
    if (!/\d/.test(q)) {
      const idx = await loadPeopleIndex();
      const hits = idx?.search(q) ?? [];
      if (hits.length === 1) return pickPerson(hits[0]);
    }
    setBusy(true); setSearchMsg(null); clearSuggest();
    const loc = await geocode(q);
    setBusy(false);
    if (!loc) { setSearchMsg("No match — try a full address, or search an official by name."); return; }
    flyTo(loc.lng, loc.lat);
  };

  const useMyLocation = async () => {
    setBusy(true); setSearchMsg(null); clearSuggest();
    try {
      const { lng, lat } = await geolocate();
      flyTo(lng, lat);
    } catch (err) {
      const denied = (err as GeolocationPositionError)?.code === 1;
      setSearchMsg(denied
        ? "Location permission denied — type your address instead."
        : "Couldn't get your location — type your address instead.");
    } finally {
      setBusy(false);
    }
  };

  // A flat, ordered suggestion list (People first, then Addresses) so the arrow
  // keys can traverse both groups with one active index.
  type Suggestion = { kind: "person"; row: PersonSearchRow } | { kind: "place"; place: Place };
  const suggestions: Suggestion[] = [
    ...people.map((row) => ({ kind: "person", row }) as const),
    ...places.map((place) => ({ kind: "place", place }) as const),
  ];
  const activateSuggestion = (s: Suggestion) =>
    s.kind === "person" ? pickPerson(s.row) : flyTo(s.place.lng, s.place.lat);

  const onSearchKeyDown = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (suggestions.length === 0) return;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      setActiveIdx((i) => (i + 1) % suggestions.length);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      setActiveIdx((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (ev.key === "Escape") {
      clearSuggest();
    }
  };

  const close = () => {
    setPanel({ kind: "closed" });
    mapRef.current?.clearSelection();
    clearRouteHash();
  };
  // Touching any per-layer box is an explicit choice → drop to manual and stick.
  const toggleLayer = (id: LayerId, v: boolean) =>
    setPrefs((p) => ({ ...p, mode: "manual", visible: { ...p.visible, [id]: v } }));
  // Auto master toggle. Re-checking Auto restores zoom-driven behavior; the stored
  // per-layer visibility is left intact so unchecking Auto again returns to it.
  const setAuto = (on: boolean) => setPrefs((p) => ({ ...p, mode: on ? "auto" : "manual" }));
  const openInfo = (p: InfoPage) => { location.hash = p; setInfo(p); };
  const closeInfo = () => {
    history.replaceState(null, "", location.pathname + location.search);
    setInfo(null);
  };

  return (
    <>
      <div className="topbar">
        <div className="brand">
          <span className="brand-name">Beholden</span>
          <span className="brand-tag">power, on the public record</span>
        </div>
        <form className="search" onSubmit={submitSearch} role="search">
          <div className="search-field">
            <input ref={searchRef} type="search" name="address" autoComplete="street-address"
                   enterKeyHint="search" placeholder="Address or official's name — find your reps"
                   aria-label="Search an address or an official's name"
                   role="combobox" aria-expanded={suggestions.length > 0} aria-controls="suggest-list"
                   aria-activedescendant={activeIdx >= 0 ? `suggest-${activeIdx}` : undefined}
                   onChange={onSearchInput} onKeyDown={onSearchKeyDown}
                   onBlur={() => window.setTimeout(clearSuggest, 150)} />
            {suggestions.length > 0 && (
              <ul className="suggest" id="suggest-list" role="listbox">
                {people.length > 0 && <li className="suggest-group" role="presentation">Officials</li>}
                {people.map((row, i) => (
                  <li key={row.person_id} role="option" aria-selected={activeIdx === i}>
                    <button type="button" id={`suggest-${i}`}
                            className={`suggest-person${activeIdx === i ? " is-active" : ""}`}
                            onMouseEnter={() => setActiveIdx(i)}
                            onMouseDown={(e) => { e.preventDefault(); pickPerson(row); }}>
                      <span className="suggest-name">{row.full_name}</span>
                      <span className="suggest-office">{row.office}</span>
                    </button>
                  </li>
                ))}
                {places.length > 0 && <li className="suggest-group" role="presentation">Addresses</li>}
                {places.map((p, j) => {
                  const idx = people.length + j;
                  return (
                    <li key={`${p.lng},${p.lat}`} role="option" aria-selected={activeIdx === idx}>
                      <button type="button" id={`suggest-${idx}`}
                              className={activeIdx === idx ? "is-active" : undefined}
                              onMouseEnter={() => setActiveIdx(idx)}
                              onMouseDown={(e) => { e.preventDefault(); flyTo(p.lng, p.lat); }}>
                        {p.label}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <button type="submit" disabled={busy}>{busy ? "…" : "Find"}</button>
          <button type="button" className="loc-btn" onClick={useMyLocation} disabled={busy}
                  aria-label="Use my location" title="Use my location">⌖</button>
        </form>
        {searchMsg && <p className="search-msg">{searchMsg}</p>}
      </div>

      {panel.kind !== "closed" && (
        <aside className="panel" role="dialog" aria-label="Representation details">
          <button className="close-btn" onClick={close} aria-label="Close">×</button>

          {panel.kind === "stack" && (
            <div className="stack">
              <div className="stack-head">
                <h2>Representation here</h2>
                <button type="button" className="ballot-link"
                        onClick={() => setPanel({ kind: "ballot", entries: panel.entries })}>
                  Your ballot ↗
                </button>
              </div>
              {PANEL_SECTIONS.map((sec) => {
                const entries = panel.entries.filter((e) => sec.layers.includes(e.layer));
                if (entries.length === 0) return null;   // no hits at this level → no section
                return (
                  <StackSection key={sec.level} level={sec.level} entries={entries}
                                onOpen={(pin) => void openDossier(pin.person_id, panel.entries)} />
                );
              })}
              <p className="stack-hint">Select anyone to open their full cited dossier.</p>
            </div>
          )}

          {panel.kind === "ballot" && (
            <Ballot
              entries={panel.entries}
              onOpen={(pin) => void openDossier(pin.person_id, panel.entries)}
              onBack={() => setPanel({ kind: "stack", entries: panel.entries })}
            />
          )}

          {panel.kind === "dossier" && (
            <DossierView
              dossier={panel.dossier}
              onBack={panel.from ? () => {
                setPanel({ kind: "stack", entries: panel.from! });
                clearRouteHash();   // leaving a dossier drops its #/p/ permalink
              } : undefined}
            />
          )}
        </aside>
      )}

      <LayerControl visible={layerVis} auto={prefs.mode === "auto"}
                    onToggle={toggleLayer} onAuto={setAuto} />
      <Footer onOpen={openInfo} />
      {info && <InfoOverlay page={info} onClose={closeInfo} />}
    </>
  );
}
