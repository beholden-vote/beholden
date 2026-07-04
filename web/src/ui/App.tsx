/** UI layer over the map: address search, the representation-stack panel
 *  ("who represents this point"), and the drill-down dossier view. */
import { useCallback, useEffect, useRef, useState } from "react";
import type { Dossier, Pin, StackEntry } from "../types";
import type { BeholdenMap, RawStackHit } from "../map";
import { loadDossier, loadPins, ocdShortLabel, type PinIndex } from "../lib/data";
import { geocode } from "../lib/lookup";
import { Avatar, EmptyNote, PartyChip } from "./bits";
import { DossierView } from "./DossierView";

const LEVEL_TITLES: Record<string, string> = {
  cd: "U.S. House",
  states: "U.S. Senate",
  sldu: "State Senate",
  sldl: "State House",
};
// Federal first, then state chambers — the same order for every point on the map.
const LEVEL_ORDER: Record<string, number> = { cd: 0, states: 1, sldu: 2, sldl: 3 };

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
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => { loadPins().then(setPins); }, []);

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
      if (e.key === "Escape") { setPanel({ kind: "closed" }); mapRef.current?.clearSelection(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mapRef]);

  const submitSearch = async (ev: React.FormEvent) => {
    ev.preventDefault();
    const q = searchRef.current?.value.trim();
    if (!q) return;
    setBusy(true); setSearchMsg(null);
    const loc = await geocode(q);
    setBusy(false);
    if (!loc) { setSearchMsg("Address not found — try adding city and state."); return; }
    mapRef.current?.goTo(loc.lng, loc.lat, 8);
  };

  const close = () => { setPanel({ kind: "closed" }); mapRef.current?.clearSelection(); };

  return (
    <>
      <div className="topbar">
        <div className="brand">
          <span className="brand-name">Beholden</span>
          <span className="brand-tag">see who they answer to</span>
        </div>
        <form className="search" onSubmit={submitSearch}>
          <input ref={searchRef} type="text" placeholder="Your address — find your representatives"
                 aria-label="Address search" />
          <button type="submit" disabled={busy}>{busy ? "…" : "Find"}</button>
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
    </>
  );
}
