// Serves web/fixtures/ as if it were data.beholden.vote. A path with no file answers 404,
// exactly like the real host, so "nothing published" code paths are exercised too.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.FIXTURE_PORT ?? 5199);

createServer(async (req, res) => {
  const cors = { "Access-Control-Allow-Origin": "*" };
  const path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (path.includes("..")) { res.writeHead(400, cors).end(); return; }
  try {
    const body = await readFile(join(root, path));
    res.writeHead(200, { ...cors, "Content-Type": "application/json" }).end(body);
  } catch {
    res.writeHead(404, cors).end();
  }
}).listen(port, () => console.log(`fixtures on http://localhost:${port}`));
