/** The trail actually walked: "Sumner County, TN > TN-6 > Rep. X".
 *
 *  Every crumb is a real link to that view's own address, so it can be opened
 *  in a new tab or copied. An ordinary click does not follow the href, though:
 *  it walks the browser's history back to the entry the reader came through,
 *  which keeps Forward working and returns them to exactly what they left
 *  (their own place has no address of its own; see history.ts).
 *
 *  A page opened cold from a shared link has a trail of one -- itself.
 */
import type { MouseEvent } from "react";
import { nav, type Crumb } from "./history";

/** True for a click the page should handle itself; false when the reader asked
 *  the browser for a new tab or window, which must be left alone. */
export function isPlainClick(e: MouseEvent): boolean {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

export function Breadcrumb({ trail }: { trail: Crumb[] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <ol>
        {trail.map((c) => {
          const here = c.delta === 0;
          return (
            <li key={c.delta}>
              <a href={c.href} aria-current={here ? "page" : undefined}
                 data-nav-id={`crumb:${c.delta}`}
                 onClick={(e) => {
                   if (!isPlainClick(e)) return;
                   e.preventDefault();
                   nav.go(c.delta);
                 }}>
                {c.label}
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
