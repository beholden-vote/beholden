/** Map chrome: the layer control, the footer, and the info overlays
 *  (why Beholden exists, privacy, the source registry, and — WO-8 — the public
 *  methodology page). */
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { PARTY_COLORS, VACANT_FILL, type LayerId } from "../map";
import { STRINGS } from "../strings";
import { GRADES, type Grade } from "./gradeFilter";
// Layers sorted by level of government — the axis users actually think in.
// Shared with the stack panel so the two can never disagree (lib/levels.ts).
import { GATES, PANEL_SECTIONS as LEVEL_GROUPS, type Gate, type GateId } from "../lib/levels";

/** How long the layer dock stays open with no interaction before folding away.
 *  Long enough to read the rail and click a checkbox without being rushed;
 *  short enough that an accidental open doesn't sit on the map. */
const IDLE_COLLAPSE_MS = 6000;

// WO-8: the methodology page's content loads only when an info overlay opens on
// it (dynamic import keeps the formula copy out of the main bundle, matching the
// lazy-load discipline used for Connections).
const Methodology = lazy(() => import("./Methodology"));

const LAYER_LABELS: Record<LayerId, string> = {
  cd: "U.S. House", states: "U.S. Senate", sldu: "State Senate", sldl: "State House",
  county: "Counties",
};

// Legend swatches: every party code the feeds can carry, in a fixed
// party-agnostic order (alphabetical by code — same deterministic rule as
// committee ordering; symmetric by construction). SPLIT and vacant are keyed to
// map states, not parties, so they render as their own labeled rows below.
const LEGEND_PARTIES: [code: string, label: string][] = [
  ["D", "Democratic"], ["G", "Green"], ["I", "Independent"],
  ["L", "Libertarian"], ["NP", "Nonpartisan"], ["R", "Republican"],
];

/** Tiny mono legend for the map fills (WO-14). "Split delegation" appears only
 *  while the U.S. Senate (states) layer is on — it's the one fill that encodes
 *  a two-seat delegation rather than a person's party. */
function Legend({ showSplit }: { showSplit: boolean }) {
  return (
    <div className="legend" aria-label="Map fill legend">
      <span className="legend-title">Fill = party</span>
      <div className="legend-grid">
        {LEGEND_PARTIES.map(([code, label]) => (
          <span className="legend-item" key={code} title={label}>
            <span className="legend-swatch" aria-hidden="true"
                  style={{ background: PARTY_COLORS[code] }} />{code}
          </span>
        ))}
      </div>
      {showSplit && (
        <span className="legend-item legend-wide"
              title="The state's two U.S. senators are from different parties">
          <span className="legend-swatch" aria-hidden="true"
                style={{ background: PARTY_COLORS.SPLIT }} />Split delegation
        </span>
      )}
      <span className="legend-item legend-wide" title="Seat currently vacant">
        <span className="legend-swatch" aria-hidden="true"
              style={{ background: VACANT_FILL }} />Vacant
      </span>
    </div>
  );
}

/** Source-quality filter (WO-28).
 *
 *  A native <select>, not a radio list: four radios plus an explanatory
 *  paragraph nearly doubled the height of the layer dock, and the dock floats
 *  over the map — every row it grows is map the reader can't see. The full
 *  explanation of the scale lives on the methodology page; what has to stay
 *  visible here is the one line that stops the filter being misread as a way to
 *  hide problems.
 *
 *  Rule 0: options are fixed-order with identical treatment, and every label
 *  describes OUR extraction method, never the official. Default shows all.
 */
function GradeFilter({ minGrade, onMinGrade }: {
  minGrade: Grade; onMinGrade: (g: Grade) => void;
}) {
  return (
    <div className="layer-group grade-filter">
      <label className="grade-row">
        <span className="layer-group-label">{STRINGS.gradeFilterTitle}</span>
        <select className="grade-select" value={minGrade}
                onChange={(e) => onMinGrade(e.target.value as Grade)}>
          {GRADES.map((g) => (
            <option key={g} value={g}>{g} · {STRINGS.gradeFilterOptions[g]}</option>
          ))}
        </select>
      </label>
      <span className="layer-ctl-hint">{STRINGS.gradeFilterHint}</span>
    </div>
  );
}

/** The level-of-government rail: the descent federal → state → county → city,
 *  with the level currently on screen marked.
 *
 *  This is the piece that makes zooming legible. The fades were always there;
 *  what was missing was any statement of what they mean, so a layer appearing
 *  read as noise. Each row carries its own gate zoom, so the rail doubles as
 *  "how much further do I have to zoom to reach my city council".
 *
 *  City is listed and visibly unavailable rather than omitted. We publish a
 *  mayor and a board of aldermen today; what we lack is boundary geometry to
 *  draw them on. Omitting the row would imply we cover nothing there, which is
 *  a worse lie than showing an honest "not mapped yet".
 */
function LevelRail({ activeId, auto }: { activeId: GateId; auto: boolean }) {
  return (
    <div className="level-rail" aria-label="Levels of government">
      {GATES.map((g) => {
        const active = auto && g.id === activeId;
        const unmapped = g.minzoom === null;
        return (
          <div key={g.id}
               className={`level-step${active ? " is-active" : ""}${unmapped ? " is-unmapped" : ""}`}
               aria-current={active ? "true" : undefined}>
            <span className="level-step-dot" aria-hidden="true" />
            <span className="level-step-label">{g.label}</span>
            <span className="level-step-zoom mono">
              {unmapped ? "not mapped yet" : g.minzoom === 0 ? "always" : `z${g.minzoom}+`}
            </span>
            <span className="level-step-blurb">{g.blurb}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Map layers, collapsible.
 *
 *  Collapsed by default and auto-collapsing after a pause, because this panel
 *  sits ON the map: every row it occupies is country the reader came here to
 *  look at, and most sessions never touch a layer toggle at all. Controls you
 *  configure once should not hold territory permanently.
 *
 *  The collapsed state is not a bare "Layers" button — it carries the current
 *  level, so the one thing a reader always wants ("which government am I
 *  looking at?") survives the collapse. That is what makes collapsing free
 *  rather than a loss.
 *
 *  Auto-collapse never fires while the pointer is inside or focus is within:
 *  a panel that folds itself away mid-interaction is worse than one that never
 *  folds. It also never fires on the very first render — only after the reader
 *  has opened it themselves.
 */
export function LayerControl({
  visible, auto, onToggle, onAuto, minGrade, onMinGrade, activeGate,
}: {
  visible: Record<LayerId, boolean>;
  auto: boolean;
  onToggle: (id: LayerId, v: boolean) => void;
  onAuto: (v: boolean) => void;
  minGrade: Grade;
  onMinGrade: (g: Grade) => void;
  activeGate: GateId;
}) {
  const [open, setOpen] = useState(false);
  const holdRef = useRef(false);            // pointer inside / focus within
  const timerRef = useRef<number | undefined>(undefined);
  const gate = GATES.find((g) => g.id === activeGate) ?? GATES[0];

  // Re-arm the idle countdown on every interaction; cancel it while held.
  const rearm = useCallback(() => {
    window.clearTimeout(timerRef.current);
    if (!open || holdRef.current) return;
    timerRef.current = window.setTimeout(() => setOpen(false), IDLE_COLLAPSE_MS);
  }, [open]);

  useEffect(() => {
    rearm();
    return () => window.clearTimeout(timerRef.current);
  }, [rearm]);

  const hold = (held: boolean) => { holdRef.current = held; rearm(); };

  return (
    <div className={`layer-ctl${open ? " is-open" : " is-collapsed"}`}
         onPointerEnter={() => hold(true)} onPointerLeave={() => hold(false)}
         onFocusCapture={() => hold(true)} onBlurCapture={() => hold(false)}
         onPointerDown={rearm} onKeyDown={rearm}>
      <button type="button" className="layer-ctl-toggle" aria-expanded={open}
              aria-controls="layer-ctl-body" onClick={() => setOpen((v) => !v)}>
        <span className="layer-ctl-caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
        <span className="layer-ctl-title">Layers</span>
        {/* The always-visible answer to "what am I looking at". In manual mode
            the zoom no longer decides, so claiming a level would be a lie. */}
        <span className="layer-ctl-level mono">{auto ? gate.label : "Manual"}</span>
      </button>

      <div className="layer-ctl-body" id="layer-ctl-body" hidden={!open}>
        <LevelRail activeId={activeGate} auto={auto} />
        {/* Master toggle: ON = zoom decides which levels show; touching any per-layer
            box below drops to manual (the parent flips `auto` off). */}
        <label className="layer-auto">
          <input type="checkbox" checked={auto} onChange={(e) => onAuto(e.target.checked)} />
          <span>Auto by zoom</span>
        </label>
        {LEVEL_GROUPS.map((g) => (
          <div className="layer-group" key={g.level}>
            <span className="layer-group-label">{g.level}</span>
            {g.layers.map((id) => (
              <label className="layer-row" key={id}>
                <input type="checkbox" checked={!!visible[id]}
                       onChange={(e) => onToggle(id, e.target.checked)} />
                <span>{LAYER_LABELS[id]}</span>
              </label>
            ))}
          </div>
        ))}
        <GradeFilter minGrade={minGrade} onMinGrade={onMinGrade} />
        <Legend showSplit={!!visible.states} />
        <span className="layer-ctl-hint">
          {auto ? "State and county layers show as you zoom in." : "Manual — Auto by zoom is off."}
        </span>
      </div>
    </div>
  );
}

/** Transient "you crossed into a new level" marker.
 *
 *  The collapsed dock already states the level; this exists for the MOMENT of
 *  change, which is otherwise silent — polygons simply appear. Announced
 *  politely for screen readers, since the visual cue is a fade nobody hears.
 */
export function LevelToast({ gate }: { gate: Gate | null }) {
  return (
    <div className="level-toast-wrap" aria-live="polite" aria-atomic="true">
      {gate && (
        <div className="level-toast" key={gate.id}>
          <span className="level-toast-label">{gate.label}</span>
          <span className="level-toast-blurb">{gate.blurb}</span>
        </div>
      )}
    </div>
  );
}

export type InfoPage = "about" | "privacy" | "sources" | "methodology";

export function Footer({ onOpen }: { onOpen: (p: InfoPage) => void }) {
  return (
    <footer className="site-foot">
      <button type="button" onClick={() => onOpen("about")}>Why Beholden</button>
      <button type="button" onClick={() => onOpen("sources")}>Sources</button>
      <button type="button" onClick={() => onOpen("methodology")}>Methodology</button>
      <button type="button" onClick={() => onOpen("privacy")}>Privacy</button>
    </footer>
  );
}

export function InfoOverlay({ page, anchor, onClose, onOpenInfo }: {
  page: InfoPage;
  /** WO-8: in-page section for the methodology page (from #methodology/<anchor>). */
  anchor?: string | null;
  onClose: () => void;
  /** Lets one overlay cross-link to another (methodology → Sources registry). */
  onOpenInfo?: (p: InfoPage) => void;
}) {
  return (
    <div className="info-scrim" role="dialog" aria-modal="true" aria-label={page}
         onClick={onClose}>
      <article className="info-page" onClick={(e) => e.stopPropagation()}>
        <button className="close-btn" onClick={onClose} aria-label="Close">×</button>
        {page === "about" && <About />}
        {page === "privacy" && <Privacy />}
        {page === "sources" && <Sources />}
        {page === "methodology" && (
          <Suspense fallback={<p className="empty-note">Loading methodology…</p>}>
            <Methodology anchor={anchor} onOpenInfo={onOpenInfo} />
          </Suspense>
        )}
      </article>
    </div>
  );
}

function About() {
  return (
    <>
      <h1>Why Beholden</h1>
      <p className="lede">
        Every U.S. federal and state elected official on one interactive map — each
        openable into a fully-cited accountability dossier. Who represents you, how
        they vote, where their money comes from. Every fact traces to an official source.
      </p>
      <h2>The principles</h2>
      <dl className="info-defs">
        <dt>Provenance over polish</dt>
        <dd>Every published fact carries a link to the official record it came from.
          Nothing appears on screen that we can't cite. If a source can't vouch for
          something, we don't show it.</dd>
        <dt>Symmetric by construction</dt>
        <dd>The same treatment for every official, regardless of party. Same sections,
          same sourcing, same design — the tool has no thumb on the scale.</dd>
        <dt>Descriptive, not prescriptive</dt>
        <dd>We show the record and the receipts. We don't tell you what to conclude.
          Ranges stay ranges; disclosures stay disclosures.</dd>
      </dl>
      <h2>How it works</h2>
      <p>
        A nightly pipeline ingests official government data, runs quality gates that
        fail closed (a bad or unverifiable record halts the update rather than shipping
        half-right), and publishes a static, cited record to a global CDN. There is no
        runtime server deciding what you see — the published record is the same for
        everyone, and reproducible from public data.
      </p>
      <p className="info-note">
        Beholden is non-partisan and built for voters, journalists, and researchers.
      </p>
    </>
  );
}

function Privacy() {
  return (
    <>
      <h1>Privacy</h1>
      <p className="lede">
        Beholden is about public officials, not about you. There are no accounts, no
        sign-in, no advertising, and no cross-site trackers. We don't build a profile
        of you.
      </p>
      <h2>What stays on your device</h2>
      <p>
        <strong>Your location.</strong> If you tap "Use my location," your browser asks
        your permission and hands the coordinates to the page to pan the map. That
        happens entirely on your device — your location is never sent to us or stored.
      </p>
      <p>
        <strong>Your layer choices.</strong> Which map layers you show are remembered in
        your browser's local storage, on your device only.
      </p>
      <h2>Address search</h2>
      <p>
        When you type an address, the text is sent to our own geocoding endpoint, which
        relays it to the U.S. Census Bureau geocoder to look up coordinates, and returns
        them to your browser. We don't log the address to a profile or sell it to anyone.
        Prefer not to type an address? Use the location button or just click the map.
      </p>
      <h2>Analytics and hosting</h2>
      <p>
        The site is served by Cloudflare. Any traffic measurement we do is aggregate and
        cookieless — it never identifies you and sets no tracking cookies. We use no
        advertising networks and no data brokers.
      </p>
      <h2>Data about officials</h2>
      <p>
        The information on officials comes from public government records about their
        public conduct in office. See <em>Sources</em> for the full registry.
      </p>
    </>
  );
}

function Sources() {
  const rows: [string, string][] = [
    ["Congress.gov", "Members, bills, sponsorships, and legislative status."],
    ["unitedstates/congress-legislators", "The identity crosswalk linking every ID scheme."],
    ["Voteview (DW-NOMINATE)", "Ideology scores from recorded roll-call votes."],
    ["Federal Election Commission", "Campaign finance: money raised, spent, on hand."],
    ["Washington Public Disclosure Commission", "Washington state campaign finance: contributions and expenditures, reconciled against the PDC's own summary totals."],
    ["OpenStates", "State legislators nationwide, plus bills and roll-call votes in pilot states."],
    ["Wikidata", "Education history only, labeled as a publicly edited source wherever it appears."],
    ["U.S. Census Bureau", "District boundaries (TIGER) and address geocoding."],
    ["Sumner County, TN", "County commissioners: who holds each of the 24 district seats, from the county's own commission roster."],
    ["City of Hendersonville, TN", "The mayor and Board of Aldermen, from the city's own officials directory."],
  ];
  return (
    <>
      <h1>Sources</h1>
      <p className="lede">
        Every section of every dossier names the official source it draws from and links
        to the underlying record. Adding a source means adding it here, with a methodology
        and a freshness commitment — no unregistered source may appear on the site. Each
        fact also carries a grade for how it was obtained; the scale is on the
        methodology page.
      </p>
      <dl className="info-defs">
        {rows.map(([name, what]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{what}</dd>
          </div>
        ))}
      </dl>
      <p className="info-note">
        All public record. The pipeline that assembles it is reproducible by design — a
        transparent method is itself a credibility feature.
      </p>
    </>
  );
}
