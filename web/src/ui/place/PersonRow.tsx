/** One official in a place: who they are, when their term ends, and a way to
 *  reach them without leaving the list.
 *
 *  A row holds two controls -- open the dossier, reveal contact -- so it is a
 *  list item with a link and a button side by side, never one inside the other.
 *  The link is a real #/p/ address (new tab, copy link); an ordinary click is
 *  handed to the shell so the trail knows the name before the dossier loads.
 *
 *  Contact actions are the dossier header's own (HeaderActions), fetched for
 *  this one official on demand through the cached loadDossier. They are
 *  deliberately NOT in the pins feeds, which load eagerly for every official in
 *  the country. Same row, same controls, same order for every official (Rule 0).
 */
import { useState } from "react";
import type { Dossier, Pin } from "../../types";
import { formatDate, loadDossier } from "../../lib/data";
import { personHash } from "../../router";
import { STRINGS } from "../../strings";
import { Avatar, EmptyNote, HeaderActions, PartyChip } from "../bits";
import { isPlainClick } from "../nav/Breadcrumb";

type Contact = Dossier["identity"]["contact"];

/** Mirrors HeaderActions' own gate, so "nothing published" can be said aloud
 *  instead of rendering an empty reveal. */
function hasActions(c: Contact): boolean {
  return !!c && !!(c.phone || c.email || c.contact_form || c.website);
}

export function PersonRow({ pin, onOpen }: { pin: Pin; onOpen: (pin: Pin) => void }) {
  const [open, setOpen] = useState(false);
  const [found, setFound] = useState<{ contact: Contact } | "failed" | null>(null);
  const name = pin.vacant ? "Vacant seat" : pin.full_name ?? "View profile";
  // Absent or null renders nothing: a term end is published or it is not shown.
  const termEnds = formatDate(pin.term_ends);
  const regionId = `contact-${pin.person_id}`;

  const toggle = () => {
    setOpen((v) => !v);
    if (open || (found && found !== "failed")) return;
    setFound(null);
    void loadDossier(pin.person_id).then((d) => setFound(d ? { contact: d.identity.contact } : "failed"));
  };

  return (
    <li className="prow">
      <a className="prow-main" href={personHash(pin.person_id)} data-nav-id={`p:${pin.person_id}`}
         onClick={(e) => { if (isPlainClick(e)) { e.preventDefault(); onOpen(pin); } }}>
        <Avatar url={pin.photo_url} name={pin.full_name ?? "?"} size={40} />
        <span className="person-id-cell">
          <span className="person-name">{name}</span>
          {pin.office && <span className="person-office">{pin.office}</span>}
          {termEnds && <span className="prow-term">{STRINGS.termEnds} {termEnds}</span>}
        </span>
        <PartyChip code={pin.party} />
        <span className="person-go" aria-hidden="true">&rarr;</span>
      </a>
      <button type="button" className="prow-contact" aria-expanded={open} aria-controls={regionId}
              aria-label={`${STRINGS.rowContact}: ${name}`} onClick={toggle}>
        {STRINGS.rowContact}
      </button>
      <div className="prow-actions" id={regionId} hidden={!open}>
        {found === null ? <EmptyNote>{STRINGS.rowContactLoading}</EmptyNote>
          : found === "failed" ? <EmptyNote>{STRINGS.rowContactFailed}</EmptyNote>
          : hasActions(found.contact) ? <HeaderActions contact={found.contact} />
          : <EmptyNote>{STRINGS.rowContactNone}</EmptyNote>}
      </div>
    </li>
  );
}
