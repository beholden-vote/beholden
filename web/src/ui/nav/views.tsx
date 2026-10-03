/** The person and record altitudes, as the shell mounts them.
 *
 *  PersonView owns what DossierView never had to: the wait while a dossier
 *  loads, and the answer when there is none. Until now a link to a dossier that
 *  no longer exists -- the official left office and the object was removed --
 *  did nothing at all. It now says so.
 */
import { Suspense, useEffect, useState, type ComponentType } from "react";
import type { Dossier } from "../../types";
import { loadDossier } from "../../lib/data";
import type { DossierTab } from "../../router";
import { STRINGS } from "../../strings";
import { DossierView } from "../DossierView";
import { nav } from "./history";
import { RECORD_VIEWS, type RecordRoute, type RecordViewProps } from "./registry";

export function PersonView({ personId, tab, onReady }: {
  personId: string;
  tab: DossierTab;
  /** The heading has changed (loading -> dossier, or -> not found); the shell
   *  moves focus to it if focus was sitting on the heading it replaced. */
  onReady: () => void;
}) {
  // Keyed by person in the shell, so this state is always this person's.
  const [dossier, setDossier] = useState<Dossier | null | undefined>(undefined);

  useEffect(() => {
    let live = true;
    void loadDossier(personId).then((d) => {
      if (!live) return;
      setDossier(d);
      if (d) nav.retitle(d.identity.full_name);
    });
    return () => { live = false; };
  }, [personId]);

  useEffect(() => { if (dossier !== undefined) onReady(); }, [dossier, onReady]);

  if (dossier === undefined) {
    return <div className="view-wait"><h2 tabIndex={-1}>{STRINGS.dossierLoading}</h2></div>;
  }
  if (dossier === null) {
    return (
      <div className="not-found">
        <h2 tabIndex={-1}>{STRINGS.notFoundTitle}</h2>
        <p>{STRINGS.notFoundBody}</p>
        {!navigator.onLine && <p>{STRINGS.notFoundOffline}</p>}
        <p className="mono not-found-id">{personId}</p>
        <button type="button" className="fix-ghost" onClick={nav.close}>{STRINGS.notFoundAction}</button>
      </div>
    );
  }
  return (
    <DossierView
      dossier={dossier}
      tab={tab}
      // A tab is not an altitude: it replaces the entry, it never stacks Back.
      onSelectTab={(t) => nav.replace({ kind: "person", personId, tab: t, title: dossier.identity.full_name })}
      onOpenPerson={(id) => nav.push({ kind: "person", personId: id, tab: "overview" })}
    />
  );
}

/** A bill, a roll call or a comparison: whatever the registry has for it. The
 *  router only yields a record view when an entry exists, so `View` is set. */
export function RecordView({ route }: { route: RecordRoute }) {
  const View = RECORD_VIEWS[route.kind] as unknown as ComponentType<RecordViewProps> | undefined;
  if (!View) return null;
  return (
    <Suspense fallback={<p className="empty-note">{STRINGS.viewLoading}</p>}>
      <View route={route} onTitle={nav.retitle} />
    </Suspense>
  );
}
