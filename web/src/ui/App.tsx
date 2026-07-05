/** UI layer over the map: address search, the representation-stack panel
 *  ("who represents this point"), and the drill-down dossier view. */
import { useCallback, useEffect, useRef, useState } from "react";
import type { Dossier, Pin, StackEntry } from "../types";
import { DEFAULT_VISIBLE } from "../map";
import type { BeholdenMap, RawStackHit, LayerId } from "../map";
import { loadDossier, loadPins, ocdShortLabel, type PinIndex } from "../lib/data";
import { geocode, geolocate, suggest, type Place } from "../lib/lookup";
import { Avatar, EmptyNote, PartyChip } from "./bits";
import { DossierView } from "./DossierView";
import { Footer, InfoOverlay, LayerControl, type InfoPage } from "./chrome";

const LEVEL_TITLES: Record<string, string> = {
  cd: "U.S. House",
  states: "U.S. Senate",
  sldu: "State Senate",
  sldl: "State House",
};
// Federal first, then state chambers — the same order for every point on the map.
const LEVEL_ORDER: Record<string, number> = { cd: 0, states: 1, sldu: 2, sldl: 3 };

const LAYER_PREFS_KEY = "beholden:layers";
function loadLayerPrefs(): Record<LayerId, boolean> {
  try {
    const raw = localStorage.getItem(LAYER_PREFS_KEY);
    if (raw) return { ...DEFAULT_VISIBLE, ...JSON.parse(raw) };
  } catch { /* fall through to defaults */ }
  return { ...DEFAULT_VISIBLE };
}
function hashToPage(): InfoPage | null {
  const h = location.hash.replace("#", "");
  return h === "about" || h === "privacy" || h === "sources" ? h : null;
}

type PanelState =
  | { kind: "closed" }
  | { kind: "stack"; entries: StackEntry[] }
  | { kind: "dossier"; dossier: Dossier; from?: StackEntry[] };

export interface AppHandle {
  onMapSelect: (hits: RawStackHit[], lngLat: { lng: number; lat: number }) => void;
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
  const [layerVis, setLayerVis] = useState<Record<LayerId, boolean>>(loadLayerPrefs);
  const [info, setInfo] = useState<InfoPage | null>(hashToPage);
  const searchRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<number | undefined>(undefined);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => { loadPins().then(setPins); }, []);

  // Push layer choices to the map and remember them on this device.
  useEffect(() => {
    const m = mapRef.current;
    if (m) (Object.keys(layerVis) as LayerId[]).forEach((id) => m.setLayerVisible(id, layerVis[id]));
    try { localStorage.setItem(LAYER_PREFS_KEY, JSON.stringify(layerVis)); } catch { /* ok */ }
  }, [layerVis, mapRef]);

  // Info pages are hash-linkable (#about / #privacy / #sources).
  useEffect(() => {
    const onHash = () => setInfo(hashToPage());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const openDossier = useCallback(async (pin: Pin, from?: StackEntry[]) => {
    setBusy(true);
    const dossier = await loadDossier(pin.person_id);
    setBusy(false);
    if (dossier) setPanel({ kind: "dossier", dossier, from });
  }, []);

  const onMapSelect = useCallback((hits: RawStackHit[], _lngLat: { lng: number; lat: number }) => {
    if (hits.length === 0) return setPanel({ kind: "closed" });
    const entries: StackEntry[] = hits
      .map((h) => ({
        layer: h.layer,
        ocdId: h.ocdId,
        pins: pins?.get(h.layer)?.get(h.ocdId) ?? [],
      }))
      .sort((a, b) => (LEVEL_ORDER[a.layer] ?? 9) - (LEVEL_ORDER[b.layer] ?? 9));
    // One person under the point (just a lone CD rep at low zoom)? Go straight in.
    const people = entries.flatMap((e) => e.pins);
    if (people.length === 1 && entries.length === 1) void openDossier(people[0], entries);
    else setPanel({ kind: "stack", entries });
  }, [pins, openDossier]);

  useEffect(() => { handleRef.current = { onMapSelect }; }, [onMapSelect, handleRef]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setInfo(null);
      setPanel({ kind: "closed" });
      mapRef.current?.clearSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mapRef]);

  const flyTo = useCallback((lng: number, lat: number) => {
    setPlaces([]); setSearchMsg(null);
    mapRef.current?.setUserLocation(lng, lat, true);   // exact "you are here"
    mapRef.current?.goTo(lng, lat, 9);
  }, [mapRef]);

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

  // Debounced typeahead; each keystroke cancels the last in-flight lookup.
  const onSearchInput = (ev: React.ChangeEvent<HTMLInputElement>) => {
    const q = ev.target.value;
    window.clearTimeout(debounceRef.current);
    if (q.trim().length < 4) { setPlaces([]); return; }
    debounceRef.current = window.setTimeout(async () => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setPlaces(await suggest(q, ac.signal));
    }, 320);
  };

  const submitSearch = async (ev: React.FormEvent) => {
    ev.preventDefault();
    const q = searchRef.current?.value.trim();
    if (!q) return;
    setBusy(true); setSearchMsg(null); setPlaces([]);
    const loc = await geocode(q);
    setBusy(false);
    if (!loc) { setSearchMsg("No match — try a full street address with city and state."); return; }
    flyTo(loc.lng, loc.lat);
  };

  const useMyLocation = async () => {
    setBusy(true); setSearchMsg(null); setPlaces([]);
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

  const close = () => { setPanel({ kind: "closed" }); mapRef.current?.clearSelection(); };
  const toggleLayer = (id: LayerId, v: boolean) => setLayerVis((prev) => ({ ...prev, [id]: v }));
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
                   enterKeyHint="search" placeholder="Your address — find your reps"
                   aria-label="Address search" onChange={onSearchInput}
                   onBlur={() => window.setTimeout(() => setPlaces([]), 150)} />
            {places.length > 0 && (
              <ul className="suggest">
                {places.map((p) => (
                  <li key={`${p.lng},${p.lat}`}>
                    <button type="button"
                            onMouseDown={(e) => { e.preventDefault(); flyTo(p.lng, p.lat); }}>
                      {p.label}
                    </button>
                  </li>
                ))}
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
              <h2>Representation here</h2>
              {panel.entries.map((entry) => (
                <section className="stack-level" key={`${entry.layer}:${entry.ocdId}`}>
                  <h3>
                    {LEVEL_TITLES[entry.layer] ?? entry.layer}
                    <span className="stack-div">{ocdShortLabel(entry.ocdId)}</span>
                  </h3>
                  {entry.pins.length === 0 ? (
                    <EmptyNote>
                      {entry.layer === "sldu" || entry.layer === "sldl"
                        ? "State-legislature profiles arrive with the state data layer."
                        : "No officeholder published for this division yet."}
                    </EmptyNote>
                  ) : (
                    entry.pins.map((pin) => (
                      <button className="person-row" key={pin.person_id}
                              onClick={() => void openDossier(pin, panel.entries)}>
                        <Avatar url={pin.photo_url} name={pin.full_name ?? "?"} size={40} />
                        <span className="person-name">
                          {pin.vacant ? "Vacant seat" : pin.full_name ?? "View profile"}
                        </span>
                        <PartyChip code={pin.party} />
                        <span className="person-go">→</span>
                      </button>
                    ))
                  )}
                </section>
              ))}
              <p className="stack-hint">Select anyone to open their full cited dossier.</p>
            </div>
          )}

          {panel.kind === "dossier" && (
            <DossierView
              dossier={panel.dossier}
              onBack={panel.from ? () => setPanel({ kind: "stack", entries: panel.from! }) : undefined}
            />
          )}
        </aside>
      )}

      <LayerControl visible={layerVis} onToggle={toggleLayer} />
      <Footer onOpen={openInfo} />
      {info && <InfoOverlay page={info} onClose={closeInfo} />}
    </>
  );
}
