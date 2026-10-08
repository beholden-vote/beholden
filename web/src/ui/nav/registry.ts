/** The view registry: route kind -> lazily imported component.
 *
 *  The router (src/router.ts) already parses #/b/{bill_id}, #/v/{roll_call_id}
 *  and #/c/{person_id}/{person_id}, and the shell already gives each a history
 *  entry, a breadcrumb crumb, Back/Escape and focus handling. What is missing is
 *  the component that draws it. A later lane adds ONE entry below and ONE file
 *  in its own directory -- nothing else in the shell changes:
 *
 *      import { lazy } from "react";                          // with the first entry
 *      bill: lazy(() => import("../votes/BillView")),         // #/b/{bill_id}
 *      vote: lazy(() => import("../votes/RollCallView")),     // #/v/{roll_call_id}
 *      compare: lazy(() => import("../stand/CompareView")),   // #/c/{id}/{id}
 *
 *  The component is the file's default export and takes RecordViewProps<kind>.
 *  It must render an <h2> (the shell moves focus to the first <h2> of a new
 *  view) and should call `onTitle` once it knows what to call itself. To link
 *  TO a record from anywhere, write a plain anchor -- <a href={billHash(id)}>
 *  -- and the shell turns the navigation into a pushed history entry, with the
 *  crumb, Back, Escape and focus handling every other view gets.
 *
 *  A route kind with no entry here falls back to home. No placeholder screens.
 *  Place and person views are not registered: they are the shell's own.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import type { Route } from "../../router";

export type RecordKind = "bill" | "vote" | "compare";
export type RecordRoute = Extract<Route, { kind: RecordKind }>;

export interface RecordViewProps<K extends RecordKind = RecordKind> {
  route: Extract<Route, { kind: K }>;
  /** Name this view for the breadcrumb once known ("H.R. 1234"). */
  onTitle: (title: string) => void;
}

export const RECORD_VIEWS: {
  [K in RecordKind]?: LazyExoticComponent<ComponentType<RecordViewProps<K>>>;
} = {
  bill: lazy(() => import("../votes/BillView")),       // WO-23b
  vote: lazy(() => import("../votes/RollCallView")),   // WO-23b
  // compare: WO-38
};

/** Crumb label until a record view names itself. */
export const RECORD_LABELS: Record<RecordKind, string> = {
  bill: "Bill", vote: "Roll call", compare: "Comparison",
};
