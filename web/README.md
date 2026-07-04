# web/ — Beholden frontend
Vite + React static SPA. MapLibre GL renders PMTiles straight from R2/CDN (no tile
server); deck.gl layers for pins and the network view; dossiers fetched as pre-built
JSON. Deployed to Cloudflare Pages by .github/workflows/deploy-web.yml.
Set `VITE_DATA_BASE` to your data domain (R2 custom domain).
