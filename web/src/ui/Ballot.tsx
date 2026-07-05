/** "Your ballot" (WO-5): the full representation stack at one located point,
 *  rendered as a single ordered card — Federal → State → Local — with every
 *  officeholder linking to their dossier permalink, plus a copy-link button for
 *  the point itself (#/d/{smallest division}). A shareable summary of who
 *  represents a place; same sections in the same order for every point (symmetric
 *  by construction). */
import { useState } from "react";
import type { Pin, StackEntry } from "../types";
import { ocdShortLabel } from "../lib/data";
import { divisionHash } from "../router";
import { Avatar, PartyChip } from "./bits";

const LEVEL_TITLES: Record<string, string> = {
  cd: "U.S. House",
  states: "U.S. Senate",
  sldu: "State Senate",
  sldl: "State House",
  county: "County",
};
// Federal first, then state chambers, then local — the same order for every point.
const LEVEL_ORDER: Record<string, number> = { cd: 0, states: 1, sldu: 2, sldl: 3, county: 4 };

/** The smallest (most local) division under the point carries the shareable
 *  #/d/ link — restoring it re-selects that division and re-derives the ballot. */
function smallestDivision(entries: StackEntry[]): string | null {
  let best: StackEntry | null = null;
  for (const e of entries) {
    if (!best || (LEVEL_ORDER[e.layer] ?? 9) > (LEVEL_ORDER[best.layer] ?? 9)) best = e;
  }
  return best?.ocdId ?? null;
}

export function Ballot({ entries, onOpen, onBack }: {
  entries: StackEntry[];
  onOpen: (pin: Pin) => void;
  onBack: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const ordered = [...entries].sort(
    (a, b) => (LEVEL_ORDER[a.layer] ?? 9) - (LEVEL_ORDER[b.layer] ?? 9),
  );
  const smallest = smallestDivision(ordered);

  const copyLink = async () => {
    if (!smallest) return;
    const url = `${location.origin}${location.pathname}${divisionHash(smallest)}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // Clipboard blocked (permissions / insecure origin): put the link in the
      // hash so it's at least selectable from the address bar. Never throws.
      location.hash = divisionHash(smallest);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="ballot">
      <button className="back-btn" onClick={onBack}>← Back to representation</button>
      <h2>Your ballot</h2>
      <p className="ballot-lede">
        Everyone who represents this point, federal to local. Select anyone for their
        full cited dossier.
      </p>

      {ordered.map((entry) => (
        <div className="ballot-level" key={`${entry.layer}:${entry.ocdId}`}>
          <h3>
            {LEVEL_TITLES[entry.layer] ?? entry.layer}
            <span className="ballot-div">{ocdShortLabel(entry.ocdId)}</span>
          </h3>
          {entry.pins.length === 0 ? (
            <p className="ballot-empty">Not published for this division yet.</p>
          ) : (
            entry.pins.map((pin) => (
              <button className="ballot-row" key={pin.person_id} onClick={() => onOpen(pin)}>
                <Avatar url={pin.photo_url} name={pin.full_name ?? "?"} size={34} />
                <span className="ballot-name">
                  {pin.vacant ? "Vacant seat" : pin.full_name ?? "View profile"}
                </span>
                <PartyChip code={pin.party} />
                <span className="ballot-go">→</span>
              </button>
            ))
          )}
        </div>
      ))}

      {smallest && (
        <button type="button" className="ballot-copy" onClick={copyLink}>
          {copied ? "Link copied ✓" : "Copy link to this ballot ↗"}
        </button>
      )}
    </div>
  );
}
