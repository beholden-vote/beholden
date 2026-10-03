/** The search field: an address, or an official's name.
 *
 *  Moved out of App.tsx unchanged in behaviour (WO-5 typeahead over both
 *  indexes, keyboard traversal, the locate button). It finds things and reports
 *  them; what opening a place or a person MEANS -- a history entry, a saved
 *  place -- is the shell's business, so it arrives here as callbacks.
 */
import { useCallback, useRef, useState, type RefObject } from "react";
import { loadPeopleIndex, type PersonSearchRow } from "../../lib/data";
import { geocode, suggest, type Place } from "../../lib/lookup";

type Suggestion = { kind: "person"; row: PersonSearchRow } | { kind: "place"; place: Place };

export function SearchBar({ inputRef, busy, setBusy, message, setMessage, onPlace, onPerson, onLocate }: {
  inputRef: RefObject<HTMLInputElement | null>;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  message: string | null;
  setMessage: (message: string | null) => void;
  /** An address the reader chose or submitted, resolved to a point. */
  onPlace: (lng: number, lat: number) => void;
  onPerson: (row: PersonSearchRow) => void;
  onLocate: () => void;
}) {
  const [places, setPlaces] = useState<Place[]>([]);
  const [people, setPeople] = useState<PersonSearchRow[]>([]);   // name matches (WO-5)
  const [activeIdx, setActiveIdx] = useState(-1);                // keyboard nav across suggestions
  const debounceRef = useRef<number | undefined>(undefined);
  const abortRef = useRef<AbortController | null>(null);

  // Dismiss the suggestion dropdown (both groups) and reset keyboard focus.
  const clearSuggest = useCallback(() => {
    setPlaces([]); setPeople([]); setActiveIdx(-1);
  }, []);

  const pickPlace = (lng: number, lat: number) => {
    clearSuggest(); setMessage(null);
    onPlace(lng, lat);
  };
  const pickPerson = (row: PersonSearchRow) => {
    clearSuggest(); setMessage(null);
    if (inputRef.current) inputRef.current.value = "";
    onPerson(row);
  };

  // Debounced typeahead over BOTH indexes (WO-5): a query with no digits looks
  // like a name → search the lazy people index; anything address-shaped also
  // hits the Census geocoder. The two result groups render together in one
  // dropdown. Each keystroke cancels the last lookup.
  const onInput = (ev: React.ChangeEvent<HTMLInputElement>) => {
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

  // A flat, ordered suggestion list (People first, then Addresses) so the arrow
  // keys can traverse both groups with one active index.
  const suggestions: Suggestion[] = [
    ...people.map((row) => ({ kind: "person", row }) as const),
    ...places.map((place) => ({ kind: "place", place }) as const),
  ];

  const onSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    const q = inputRef.current?.value.trim();
    if (!q) return;
    // Enter with a highlighted suggestion picks it; otherwise fall through to a
    // geocode of the typed text.
    const active = suggestions[activeIdx];
    if (active) return active.kind === "person" ? pickPerson(active.row) : pickPlace(active.place.lng, active.place.lat);
    // A name-shaped query with a single confident person match jumps to them
    // rather than failing an address geocode.
    if (!/\d/.test(q)) {
      const idx = await loadPeopleIndex();
      const hits = idx?.search(q) ?? [];
      if (hits.length === 1) return pickPerson(hits[0]);
    }
    setBusy(true); setMessage(null); clearSuggest();
    const loc = await geocode(q);
    setBusy(false);
    if (!loc) { setMessage("No match — try a full address, or search an official by name."); return; }
    pickPlace(loc.lng, loc.lat);
  };

  const onKeyDown = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (suggestions.length === 0) return;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      setActiveIdx((i) => (i + 1) % suggestions.length);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      setActiveIdx((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (ev.key === "Escape") {
      // This Escape closes the dropdown and nothing else: prevented, so the
      // shell's own Escape (step up one altitude) leaves it alone.
      ev.preventDefault();
      clearSuggest();
    }
  };

  return (
    <>
      <form className="search" onSubmit={onSubmit} role="search">
        <div className="search-field">
          <input ref={inputRef} type="search" name="address" autoComplete="street-address"
                 enterKeyHint="search" placeholder="Address or official's name — find your reps"
                 aria-label="Search an address or an official's name"
                 role="combobox" aria-expanded={suggestions.length > 0} aria-controls="suggest-list"
                 aria-activedescendant={activeIdx >= 0 ? `suggest-${activeIdx}` : undefined}
                 onChange={onInput} onKeyDown={onKeyDown}
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
                            onMouseDown={(e) => { e.preventDefault(); pickPlace(p.lng, p.lat); }}>
                      {p.label}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <button type="submit" disabled={busy}>{busy ? "…" : "Find"}</button>
        <button type="button" className="loc-btn" onClick={onLocate} disabled={busy}
                aria-label="Use my location" title="Use my location">⌖</button>
      </form>
      {message && <p className="search-msg" role="status">{message}</p>}
    </>
  );
}
