import http from "node:http";
import next from "next";

const port = Number(process.env.PORT ?? process.env.DATABRICKS_APP_PORT ?? 3000);
const hostname = "0.0.0.0";
const dev = process.env.NODE_ENV === "development";

const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

await app.prepare();

http.createServer((req, res) => handle(req, res)).listen(port, hostname, () => {
  console.log(`Visual Inspection listening on http://${hostname}:${port}`);
});
