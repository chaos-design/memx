import { createReadStream, type Dirent, readdirSync, readFileSync } from "node:fs";
import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vite";

// site/ 与 docs/、artifacts/ 同处仓库根目录下，向上取一层即可定位源目录
const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const docsDir = path.join(repoRoot, "docs");
const artifactsDir = path.join(repoRoot, "artifacts");

// Expose every docs/**/*.md file as Record<key, rawMarkdown> through a virtual
// module, so the site renders the documentation at build time and stays fully
// self-contained (no runtime fetch of the repo).
function docsModule(): Plugin {
  const virtualId = "virtual:memx-docs";
  const resolvedId = `\0${virtualId}`;

  function collectMarkdown(dir: string, prefix: string, out: Map<string, string>) {
    let entries: Dirent[];
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        collectMarkdown(full, `${prefix}${entry.name}/`, out);
      } else if (entry.isFile() && entry.name.endsWith(".md")) {
        const key = `${prefix}${entry.name}`.replace(/\.md$/, "");
        out.set(key, readFileSync(full, "utf8"));
      }
    }
  }

  return {
    name: "memx-site-docs",
    enforce: "pre",
    resolveId(id) {
      if (id === virtualId) return resolvedId;
      return null;
    },
    load(id) {
      if (id !== resolvedId) return null;
      const docs = new Map<string, string>();
      collectMarkdown(docsDir, "", docs);
      const obj: Record<string, string> = {};
      for (const [k, v] of docs) obj[k] = v;
      return `export const docs = ${JSON.stringify(obj)};`;
    },
  };
}

// Serve ../artifacts/** under /artifacts/ during dev so the iframe views
// resolve exactly like they will in the built output.
function serveArtifacts(): Plugin {
  return {
    name: "memx-site-serve-artifacts",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = (req.url ?? "").split("?")[0];
        if (url !== "/artifacts" && !url.startsWith("/artifacts/")) {
          next();
          return;
        }
        const relPath = url.replace("/artifacts", "").replace(/^\/+/, "");
        const target = path.normalize(path.join(artifactsDir, relPath));
        if (!target.startsWith(artifactsDir + path.sep)) {
          next();
          return;
        }
        const stream = createReadStream(target);
        stream.on("open", () => res.setHeader("Content-Type", "text/html"));
        stream.pipe(res);
      });
    },
  };
}

// Copy the self-contained artifact HTML files into the build output after Vite
// writes the bundle, so the iframe views load next to index.html.
function copyArtifacts(): Plugin {
  let outDir = "dist";
  return {
    name: "memx-site-copy-artifacts",
    apply: "build",
    configResolved(config) {
      outDir = path.resolve(config.root, config.build.outDir);
    },
    async closeBundle() {
      const dest = path.join(outDir, "artifacts");
      await rm(dest, { recursive: true, force: true });
      await mkdir(dest, { recursive: true });
      await cp(artifactsDir, dest, { recursive: true });
    },
  };
}

export default defineConfig({
  // Relative base so the built site works from a repo root (Vercel), a
  // GitHub Pages subpath (/memx/), or a nested directory without a server
  // rewrite.
  base: "./",
  plugins: [react(), docsModule(), serveArtifacts(), copyArtifacts()],
  server: {
    host: "127.0.0.1",
    port: 5174,
    fs: { allow: [repoRoot] },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
