import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Static SPA build; output is published to Cloudflare Pages (see docs/ARCHITECTURE.md §3).
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Map engine is the bulk of the bundle and changes far less often than
        // app code — split it so returning visitors hit cache (PRD: TTI <2s).
        manualChunks(id) {
          if (id.includes("node_modules/maplibre-gl")) return "maplibre";
          if (id.includes("node_modules/pmtiles")) return "pmtiles";
        },
      },
    },
  },
});
