/** Credibility-grade filter (WO-28).
 *
 *  Every provenance envelope carries a grade for HOW the fact was obtained
 *  (A bulk official source … D derived/inferred). The reader can hide grades
 *  below a threshold; the default shows everything, because the point of the
 *  scale is informed trust, not hidden data.
 *
 *  Rule 0 note: grades describe extraction method, never a judgement of the
 *  official. The palette here is deliberately neutral — no red/green, no party
 *  hues — so a locality whose records are scanned rather than exported does not
 *  render as though its officials were suspect.
 */
import { createContext, useContext } from "react";
import type { ReactNode } from "react";

/** Lower index = stronger provenance. */
export const GRADE_ORDER = { A: 0, B: 1, C: 2, D: 3 } as const;
export type Grade = keyof typeof GRADE_ORDER;
export const GRADES: readonly Grade[] = ["A", "B", "C", "D"];

/** `minGrade` is the WEAKEST grade still shown, so "D" shows everything. */
export const DEFAULT_MIN_GRADE: Grade = "D";

const KEY = "beholden:grades";
const VERSION = 1;

function isGrade(v: unknown): v is Grade {
  return typeof v === "string" && v in GRADE_ORDER;
}

export function loadMinGrade(): Grade {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_MIN_GRADE;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && isGrade(parsed.minGrade)) return parsed.minGrade;
  } catch { /* private mode, cleared storage, blocked cookies — fall through */ }
  return DEFAULT_MIN_GRADE;
}

export function saveMinGrade(minGrade: Grade): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ version: VERSION, minGrade }));
  } catch { /* storage is a convenience here, never a correctness dependency */ }
}

const MinGradeContext = createContext<Grade>(DEFAULT_MIN_GRADE);

/** Provided once at the app root so every Section filters identically — the
 *  filter can't drift per call site, the same reason the source tag lives in
 *  the Section shell rather than at each usage. */
export function GradeFilterProvider({ value, children }: { value: Grade; children: ReactNode }) {
  return <MinGradeContext.Provider value={value}>{children}</MinGradeContext.Provider>;
}

export function useMinGrade(): Grade {
  return useContext(MinGradeContext);
}

/** An UNGRADED section is never hidden: absence of a grade is a pipeline bug
 *  (the validator rejects it), and silently hiding it would conceal that bug
 *  from the one person who could report it. */
export function isBelowMinGrade(grade: string | undefined, minGrade: Grade): boolean {
  if (!isGrade(grade)) return false;
  return GRADE_ORDER[grade] > GRADE_ORDER[minGrade];
}
