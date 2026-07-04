# CLAUDE.md

Instructions for Claude Code and other AI agents on this repo live in
[`AGENTS.md`](AGENTS.md) — read it first. This file restates only the rules that
must never be violated, so they stay in context.

## Never violate these
1. **No provenance, no publish.** Every published fact carries a source envelope. Never
   add a path that bypasses the dossier builder's provenance validator.
2. **Fail closed.** Quality-gate failures halt the pipeline. Never lower a threshold or
   swallow a gate error to make a run pass.
3. **Symmetric by construction.** No feature, copy, or presentation may apply
   asymmetrically by party.
4. **Operational privacy.** Commit as `Beholden Maintainers <maintainers@beholden.vote>`
   (or GitHub noreply). No personal emails, names, or other-project references in code,
   docs, or commit messages.

## Fast facts
- Zero-server v1: nightly GitHub Actions + DuckDB → static JSON + PMTiles on Cloudflare.
- Pipeline: `pipelines/beholden_etl` (Python ≥3.11). Stages: `fetch → transform → build → publish` via the [`Makefile`](Makefile).
- Before pipeline commits: `cd pipelines && pytest && ruff check .`
- A navigable knowledge graph of this repo is in `graphify-out/` — run
  `graphify query "<question>"` for architecture questions before re-reading files;
  `graphify . --update` after code changes.

See [`AGENTS.md`](AGENTS.md), [`CONTRIBUTING.md`](CONTRIBUTING.md), and [`docs/`](docs/) for detail.
