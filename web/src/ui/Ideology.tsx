/** The ideology section of the dossier (WO-38). The single left-right bar is retired:
 *  a member is drawn as a profile of separate measures and two chamber plots
 *  (ui/stand/), never as one number on one axis. Symmetric by construction: the
 *  same card, from the same published file, for every member. */
import type { Dossier } from "../types";
import { parseHash } from "../router";
import { ProfileCard } from "./stand/ProfileCard";

export function IdeologyScale({ ideology }: {
  ideology: NonNullable<Dossier["ideology"]>; partyCode: string;
}) {
  // The dossier shell mounts this for the person route, whose hash names the member.
  const route = parseHash();
  void ideology;
  return route.kind === "person" ? <ProfileCard personId={route.personId} /> : null;
}
