# Contributing to Beholden

## The three rules that outrank everything
1. **No provenance, no publish.** Every fact needs a source envelope; the builder
   enforces this and CI runs the same validation on PRs.
2. **Fail closed.** Quality-gate failures halt the pipeline. Never ship partial data.
3. **Symmetric by construction.** No feature or presentation choice may apply
   asymmetrically by party. See PRD §2 and §9.

## Workflow
- Branch from `main`; PRs require green CI — `.github/workflows/ci.yml` runs ruff +
  pytest (which includes contract validation) and the web typecheck/build.
- Data-touching PRs must link the relevant contract section (docs/DATA-CONTRACTS.md).
- New data source = registry entry (pipelines config) + methodology entry +
  coverage-dashboard row + freshness SLA, plus a default credibility grade reason
  (data-contracts §1.1). An unregistered source cannot publish — the dossier
  builder raises rather than stamping an ungraded, unattributed fact.
- Copy that touches money or legal-adjacent surfaces (net worth, late-filing flags)
  comes from the approved string table only — never composed inline.

## Style
Python: ruff, rule set pinned in `pipelines/pyproject.toml` (not left to the
installed ruff's defaults, which have widened between releases). SQL: canonical DDL lives in db/migrations; DuckDB shims are
applied at load, never hand-forked. Frontend: no runtime data joins the contracts
don't define.

## Operational privacy
Commits must use the project identity (or GitHub noreply addresses) — never personal
emails. No personal names, other-project references, or identifying brand language in
code, docs, or commit messages. Configure before committing:
```bash
git config user.name "Beholden Maintainers"
git config user.email "maintainers@beholden.vote"
```
