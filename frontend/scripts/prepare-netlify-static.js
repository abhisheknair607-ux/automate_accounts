const fs = require("fs");
const path = require("path");

const root = process.cwd();
const nextDir = path.join(root, ".next");
const serverAppDir = path.join(nextDir, "server", "app");
const staticDir = path.join(nextDir, "static");
const publicNextDir = path.join(nextDir, "_next");
const publicStaticDir = path.join(publicNextDir, "static");

function ensureExists(targetPath, description) {
  if (!fs.existsSync(targetPath)) {
    throw new Error(`Missing ${description}: ${targetPath}`);
  }
}

function copyFile(from, to) {
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.copyFileSync(from, to);
}

function copyDir(from, to) {
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.cpSync(from, to, { recursive: true, force: true });
}

ensureExists(nextDir, ".next build output");
ensureExists(serverAppDir, "server app output");
ensureExists(path.join(serverAppDir, "index.html"), "server app index.html");
ensureExists(path.join(serverAppDir, "_not-found.html"), "server app 404.html");
ensureExists(staticDir, "Next static assets");

copyFile(path.join(serverAppDir, "index.html"), path.join(nextDir, "index.html"));
copyFile(path.join(serverAppDir, "_not-found.html"), path.join(nextDir, "404.html"));
copyDir(staticDir, publicStaticDir);

const redirects = "/* /index.html 200\n";
fs.writeFileSync(path.join(nextDir, "_redirects"), redirects, "utf8");
