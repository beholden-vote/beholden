# Beholden — Setup (zero to running pipeline)

## 0. Domain (one-time, ~$10-15/yr — the only mandatory spend)
1. Register **beholden.vote** with WHOIS privacy/redaction enabled (Cloudflare
   Registrar and Porkbun include it free). Optionally **beholden.vote** as a redirect.
   **Do NOT register the .us variant** — the usTLD registry prohibits WHOIS privacy,
   so a .us registration publishes the registrant's contact information.
2. Register under the operating entity (LLC), not an individual, and use the
   entity's email/address. Get this right BEFORE first registration: DNS/WHOIS
   history services archive records permanently.
3. Add the domain to the entity's Cloudflare account (free plan).

## 1. Accounts & keys (all free)
| What | Where | Used for |
|---|---|---|
| Congress.gov API key | api.congress.gov (sign up via api.data.gov) | members, bills, votes |
| FEC API key | api.open.fec.gov | campaign finance |
| Cloudflare account | cloudflare.com | Pages + R2 + analytics |
| OpenStates key (later) | open.pluralpolicy.com | state layer (E4) |

## 2. Cloudflare resources
1. **R2:** create bucket `beholden` (free tier: 10 GB). Enable versioning.
   Create an R2 API token (Object Read & Write) — note the Access Key ID,
   Secret, and the account endpoint URL.
2. **R2 custom domain:** attach `data.beholden.vote` to the bucket (this is what
   makes egress free and CDN-cached).
3. **Pages:** create project `beholden` (no build config needed — deploys come
   from the GitHub Action).
4. **Web Analytics:** enable for beholden.vote, copy the snippet into `web/index.html`.

## 3. GitHub repository
```bash
# from the repo root (this directory)
gh repo create beholden --private --source . --push
# or manually: create private repo, then
git remote add origin git@github.com:<you>/beholden.git
git push -u origin main
```
Then add **Actions secrets** (Settings → Secrets and variables → Actions):
`CONGRESS_GOV_API_KEY` · `FEC_API_KEY` · `R2_ACCESS_KEY_ID` ·
`R2_SECRET_ACCESS_KEY` · `R2_ENDPOINT` · `CLOUDFLARE_API_TOKEN` ·
`CLOUDFLARE_ACCOUNT_ID`

> Note: the free-tier design assumes a **public** repo for unlimited Actions
> minutes. Private repos get 2,000 free minutes/mo — comfortably enough for the
> nightly pipeline during buildout (≈30–60 min/day). Flip to public at launch.

## 4. First runs
1. **Tiles (one-time per vintage):** Actions → `tiles-build` → Run workflow.
   Verify `us-cd-2024.pmtiles` etc. appear in R2 under `/tiles/`.
2. **Pipeline:** Actions → `etl-nightly` → Run workflow. Watch the quality
   gates; a spine-resolution failure halts publish by design.
3. **Frontend:** set `VITE_DATA_BASE=https://data.beholden.vote` in the Pages
   project env; push to `main` — `deploy-web` publishes automatically.

## 5. Local development
```bash
make spike                 # no credentials needed
pip install -e ./pipelines
export CONGRESS_GOV_API_KEY=... FEC_API_KEY=...
make fetch transform build # artifacts land in dist/data for inspection
cd web && npm install && npm run dev
```

## 6. Verification checklist
- [ ] `data.beholden.vote/tiles/us-cd-2024.pmtiles` returns 206 on a Range request
- [ ] `data.beholden.vote/stylefeeds/cd.json` maps every CD ocd_id
- [ ] A dossier JSON validates: every section has a provenance envelope
- [ ] Coverage dashboard JSON shows all sources within SLA
