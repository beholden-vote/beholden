/** Runnable check for the client route table (docs/DATA-CONTRACTS.md 8.6).
 *  No test runner in web/, and none needed for this: `node src/router.check.ts`
 *  (Node 22.18+ runs TypeScript directly). Prints "router: ok" or throws. */
import { compareHash, divisionHash, isRouteHash, parseHash, personHash, routeHash, type Route } from "./router.ts";

function same(got: unknown, want: unknown, what: string) {
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    throw new Error(`${what}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  }
}

const HOME = { kind: "home" };
const OCD = "ocd-division/country:us/state:tn/county:sumner";

// Every route round-trips through its own hash.
const routes: Route[] = [
  { kind: "person", personId: "abc-123", tab: null },
  { kind: "person", personId: "abc-123", tab: "money" },
  { kind: "division", ocdId: OCD },
  { kind: "bill", billId: "hr/1234-119" },
  { kind: "vote", rollCallId: "h2025-17" },
  { kind: "compare", a: "abc", b: "def" },
];
for (const r of routes) same(parseHash(routeHash(r)), r, `round trip ${r.kind}`);

// The default tab is never written, so old person links stay bit-identical.
same(personHash("abc", "overview"), "#/p/abc", "default tab omitted");
// A junk tab degrades to the default; it never breaks the person link.
same(parseHash("#/p/abc/banana"), { kind: "person", personId: "abc", tab: null }, "junk tab");
// A division id is encoded when written and accepted unencoded when typed.
same(divisionHash(OCD).includes("/country"), false, "division id is encoded");
same(parseHash(`#/d/${OCD}`), { kind: "division", ocdId: OCD }, "hand-typed division id");
// Half a comparison, an empty id, a stray "%" and every info hash are home.
for (const h of ["", "#", "#about", "#methodology/key-votes", "#/p/", "#/c/abc", "#/p/%E0%A4%A", "#/x/abc"]) {
  same(parseHash(h), HOME, `home for "${h}"`);
}
same(isRouteHash("#/b/x") && isRouteHash(compareHash("a", "b")) && !isRouteHash("#privacy"), true, "isRouteHash");

console.log("router: ok");
