import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Static SPA build; output is published to Cloudflare Pages (see docs/ARCHITECTURE.md §3).
export default defineConfig({
  plugins: [react()],
});
