// npm run dev:fixtures -- the fixture host plus Vite pointed at it.
import { spawn } from "node:child_process";
import "./serve.mjs";

const port = process.env.FIXTURE_PORT ?? 5199;
spawn("npx", ["vite"], {
  stdio: "inherit", shell: true,
  env: { ...process.env, VITE_DATA_BASE: `http://localhost:${port}` },
}).on("exit", (code) => process.exit(code ?? 0));
