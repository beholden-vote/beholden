/** Map chrome: the layer control, the footer, and the info overlays
 *  (why Beholden exists, privacy, and the source registry). */
import { type LayerId } from "../map";

const LAYER_LABELS: Record<LayerId, string> = {
  cd: "U.S. House", states: "U.S. Senate", sldu: "State Senate", sldl: "State House",
  county: "Counties",
};
// Layers sorted by level of government — the axis users actually think in.
// Local now carries county boundaries (workplan WO-6b); off by default, fades in
// as you zoom into a metro. City/place geometry joins the group in a later WO.
const LEVEL_GROUPS: { level: string; layers: LayerId[] }[] = [
  { level: "Federal", layers: ["cd", "states"] },
  { level: "State", layers: ["sldu", "sldl"] },
  { level: "Local", layers: ["county"] },
];

export function LayerControl({ visible, auto, onToggle, onAuto }: {
  visible: Record<LayerId, boolean>;
  auto: boolean;
  onToggle: (id: LayerId, v: boolean) => void;
  onAuto: (v: boolean) => void;
}) {
  return (
    <div className="layer-ctl" role="group" aria-label="Map layers">
      <span className="layer-ctl-title">Layers</span>
      {/* Master toggle: ON = zoom decides which levels show; touching any per-layer
          box below drops to manual (the parent flips `auto` off). */}
      <label className="layer-auto">
        <input type="checkbox" checked={auto} onChange={(e) => onAuto(e.target.checked)} />
        <span>Auto by zoom</span>
      </label>
      {LEVEL_GROUPS.map((g) => (
        <div className="layer-group" key={g.level}>
          <span className="layer-group-label">{g.level}</span>
          {g.layers.length === 0 ? (
            <span className="layer-soon">Counties · coming soon</span>
          ) : (
            g.layers.map((id) => (
              <label className="layer-row" key={id}>
                <input type="checkbox" checked={!!visible[id]}
                       onChange={(e) => onToggle(id, e.target.checked)} />
                <span>{LAYER_LABELS[id]}</span>
              </label>
            ))
          )}
        </div>
      ))}
      <span className="layer-ctl-hint">
        {auto ? "State districts show as you zoom in." : "Manual — Auto by zoom is off."}
      </span>
    </div>
  );
}

export type InfoPage = "about" | "privacy" | "sources";

export function Footer({ onOpen }: { onOpen: (p: InfoPage) => void }) {
  return (
    <footer className="site-foot">
      <button type="button" onClick={() => onOpen("about")}>Why Beholden</button>
      <button type="button" onClick={() => onOpen("sources")}>Sources</button>
      <button type="button" onClick={() => onOpen("privacy")}>Privacy</button>
    </footer>
  );
}

export function InfoOverlay({ page, onClose }: { page: InfoPage; onClose: () => void }) {
  return (
    <div className="info-scrim" role="dialog" aria-modal="true" aria-label={page}
         onClick={onClose}>
      <article className="info-page" onClick={(e) => e.stopPropagation()}>
        <button className="close-btn" onClick={onClose} aria-label="Close">×</button>
        {page === "about" && <About />}
        {page === "privacy" && <Privacy />}
        {page === "sources" && <Sources />}
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
    ["U.S. Census Bureau", "District boundaries (TIGER) and address geocoding."],
  ];
  return (
    <>
      <h1>Sources</h1>
      <p className="lede">
        Every section of every dossier names the official source it draws from and links
        to the underlying record. Adding a source means adding it here, with a methodology
        and a freshness commitment — no unregistered source may appear on the site.
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
