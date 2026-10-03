/** The place view: an area and everyone who represents it.
 *
 *  One list, federal to local, the same sections in the same order for every
 *  point on the map (symmetric by construction). This is the old "stack" and
 *  the old "Your ballot" folded together -- they were the same list twice.
 *
 *  Above the list the view says how it got here, because that decides how far
 *  to trust it: an APPROXIMATE place (the edge's guess on arrival) says so and
 *  offers the two ways to fix it; the reader's SAVED place says where it is
 *  kept and offers to forget it; a place opened from a link says which levels
 *  a link cannot carry.
 */
import { useReducer, useRef, useState } from "react";
import type { Pin, StackEntry } from "../../types";
import type { PinIndex } from "../../lib/data";
import { LEVEL_ORDER, LEVEL_TITLES, PANEL_SECTIONS } from "../../lib/levels";
import { divisionHash } from "../../router";
import { STRINGS } from "../../strings";
import { EmptyNote } from "../bits";
import { isOwnPlace, type PlaceState } from "../nav/history";
import { divisionName, smallestDivision } from "./divisions";
import { PersonRow } from "./PersonRow";
import { forgetPlace, isSavedPlace } from "./remembered";

/** The two ways to turn a guess into the reader's real place. Shown under the
 *  approximate label, and alone as a prompt when the edge had no guess at all. */
export interface FixProps { onLocate: () => void; onTypeAddress: () => void; busy: boolean }

function FixActions({ onLocate, onTypeAddress, busy }: FixProps) {
  return (
    <div className="fix-actions">
      <button type="button" className="fix-primary" onClick={onLocate} disabled={busy}>
        {STRINGS.fixLocate}
      </button>
      <button type="button" className="fix-ghost" onClick={onTypeAddress}>
        {STRINGS.fixAddress}
      </button>
    </div>
  );
}

/** Shown over the national map when the edge returned no location: the same two
 *  actions, and nothing else. */
export function ArrivePrompt({ onDismiss, ...fix }: FixProps & { onDismiss: () => void }) {
  return (
    // The row takes a full line of the top bar; the card inside it does not.
    <div className="arrive-row">
      <section className="arrive-prompt" aria-labelledby="arrive-prompt-title">
        <button type="button" className="close-btn" aria-label="Dismiss" onClick={onDismiss}>&times;</button>
        <h2 id="arrive-prompt-title">{STRINGS.promptTitle}</h2>
        <p>{STRINGS.promptNote}</p>
        <FixActions {...fix} />
      </section>
    </div>
  );
}

/** The area you are looking at, above the people who represent it. The meta
 *  line is deliberately thin: identifiers we publish (FIPS/GEOID, the OCD id)
 *  plus counts over the pins already on screen. No party breakdown -- every
 *  row below carries its own chip. */
function DivisionCard({ entry }: { entry: StackEntry }) {
  const geoid = entry.props?.geoid;
  const seats = entry.pins.length;
  const vacant = entry.pins.filter((p) => p.vacant).length;
  return (
    <div className="division-card">
      <h4 className="division-name">{divisionName(entry.layer, entry.props ?? {}, entry.ocdId)}</h4>
      <p className="division-meta mono">
        <span>{LEVEL_TITLES[entry.layer] ?? entry.layer}</span>
        {geoid && <span title="Census GEOID / FIPS code">FIPS {geoid}</span>}
        <span>{seats === 1 ? "1 seat" : `${seats} seats`}</span>
        {vacant > 0 && <span className="division-vacant">{vacant} vacant</span>}
      </p>
      <p className="division-ocd mono" title="Open Civic Data division identifier">{entry.ocdId}</p>
    </div>
  );
}

function emptyNote(layer: StackEntry["layer"]): string {
  if (layer === "sldu" || layer === "sldl") return "State-legislature profiles arrive with the state data layer.";
  if (layer === "county") return "Beholden covers county officials in pilot counties only. This county isn't covered yet.";
  return "No officeholder published for this division yet.";
}

/** One collapsible level (Federal / State / Local). The officeholder count
 *  stays visible when collapsed, so the level's weight reads at a glance. */
function LevelSection({ level, entries, loading, onOpen }: {
  level: string; entries: StackEntry[]; loading: boolean; onOpen: (pin: Pin) => void;
}) {
  const [open, setOpen] = useState(true);
  const count = entries.reduce((n, e) => n + e.pins.length, 0);
  return (
    <section className="stack-section">
      <h3 className="stack-section-h">
        <button type="button" className="stack-section-head" aria-expanded={open}
                onClick={() => setOpen((v) => !v)}>
          <span className="stack-section-caret" aria-hidden="true">{open ? "\u25BE" : "\u25B8"}</span>
          <span className="stack-section-label">{level}</span>
          <span className="stack-section-count">{loading ? "\u2026" : count}</span>
        </button>
      </h3>
      {open && entries.map((entry) => (
        <div className="stack-level" key={`${entry.layer}:${entry.ocdId}`}>
          <DivisionCard entry={entry} />
          {loading ? <EmptyNote>{STRINGS.placeLoading}</EmptyNote>
            : entry.pins.length === 0 ? <EmptyNote>{emptyNote(entry.layer)}</EmptyNote>
            : (
              <ul className="prow-list">
                {entry.pins.map((pin) => <PersonRow key={pin.person_id} pin={pin} onOpen={onOpen} />)}
              </ul>
            )}
        </div>
      ))}
    </section>
  );
}

/** Copy a link to this place. The link names the most local division and
 *  nothing else -- never the point, so it is safe to hand to anyone. */
function CopyLink({ ocdId }: { ocdId: string }) {
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  const url = `${location.origin}${location.pathname}${divisionHash(ocdId)}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setState("copied");
      window.setTimeout(() => setState("idle"), 2000);
    } catch {
      // Clipboard blocked (permissions, insecure origin): show the link to copy
      // by hand rather than navigating to it, which would swap this full list
      // for the one-division view a link opens.
      setState("manual");
    }
  };
  return (
    <div className="place-share">
      <button type="button" className="ballot-copy" onClick={copy}>
        {state === "copied" ? `${STRINGS.placeCopied} \u2713` : `${STRINGS.placeCopyLink} \u2197`}
      </button>
      {state === "manual" && (
        <label className="place-share-manual">
          <span>{STRINGS.placeCopyManual}</span>
          <input type="text" readOnly value={url} onFocus={(e) => e.currentTarget.select()} />
        </label>
      )}
      <span className="visually-hidden" role="status">{state === "copied" ? STRINGS.placeCopied : ""}</span>
    </div>
  );
}

export function PlaceView({ view, pins, onOpenPerson, fix }: {
  view: PlaceState;
  /** null while the pin feeds are still loading. */
  pins: PinIndex | null;
  onOpenPerson: (pin: Pin) => void;
  fix: FixProps;
}) {
  // Forgetting changes storage, not props; re-read it.
  const [, refresh] = useReducer((n: number) => n + 1, 0);
  const heading = useRef<HTMLHeadingElement>(null);
  const entries: StackEntry[] = view.hits
    .map((h) => ({ layer: h.layer, ocdId: h.ocdId, props: h.props, pins: pins?.get(h.layer)?.get(h.ocdId) ?? [] }))
    .sort((a, b) => (LEVEL_ORDER[a.layer] ?? 9) - (LEVEL_ORDER[b.layer] ?? 9));
  const saved = isSavedPlace(view.point);
  const local = smallestDivision(view.hits);

  return (
    <div className="place">
      <h2 ref={heading} tabIndex={-1}>{view.title}</h2>

      {view.origin === "approximate" ? (
        <div className="place-banner">
          <p className="place-caveat">
            <span className="place-stamp">{STRINGS.approxBadge}</span> {STRINGS.approxNote}
          </p>
          <FixActions {...fix} />
        </div>
      ) : saved ? (
        <div className="place-banner place-banner-saved">
          <p className="place-saved">
            <span className="place-stamp">{STRINGS.savedBadge}</span> {STRINGS.savedNote}
          </p>
          {/* The control removes itself; hand focus to the heading rather than drop it. */}
          <button type="button" className="fix-ghost"
                  onClick={() => { forgetPlace(); refresh(); heading.current?.focus(); }}>
            {STRINGS.forgetPlace}
          </button>
        </div>
      ) : isOwnPlace(view) ? (
        <p className="place-saved" role="status">{STRINGS.notSavedNote}</p>
      ) : null}

      {view.origin === "link" && <p className="place-lede">{STRINGS.placeLinkNote}</p>}

      {PANEL_SECTIONS.map((sec) => {
        const here = entries.filter((e) => sec.layers.includes(e.layer));
        if (here.length === 0) return null;   // no division at this level: no section
        return <LevelSection key={sec.level} level={sec.level} entries={here}
                             loading={pins === null} onOpen={onOpenPerson} />;
      })}

      {/* Below the list, not above it: on a phone the first thing under the
          title should be a representative, not a sentence about them. */}
      <p className="place-hint">{STRINGS.placeLede}</p>
      {local && <CopyLink ocdId={local.ocdId} />}
    </div>
  );
}
