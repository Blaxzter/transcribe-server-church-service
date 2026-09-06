/*
 * Builds src/__preview.tsx and folds the result into one self-contained HTML
 * file that can be opened anywhere — no dev server, no API. The browser
 * tooling on this machine cannot reach localhost, so this is how a dialog gets
 * looked at before it ships.
 *
 *   node scripts/preview-dialog.mjs [out.html]
 */
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = dirname(dirname(fileURLToPath(import.meta.url)));
const out = resolve(process.argv[2] ?? join(web, "dist-preview", "dialog.html"));

execFileSync("npx", ["vite", "build", "--config", "vite.preview.config.ts"], {
  cwd: web,
  stdio: "inherit",
  shell: process.platform === "win32",
});

const assets = join(web, "dist-preview", "assets");
const pick = (extension) => {
  const name = readdirSync(assets).find((file) => file.endsWith(extension));
  if (!name) throw new Error(`no ${extension} in ${assets}`);
  return readFileSync(join(assets, name), "utf8");
};

// Written as artifact body content: the host supplies doctype, html and head.
writeFileSync(
  out,
  [
    "<title>Export-Dialog</title>",
    `<style>\n${pick(".css")}\n</style>`,
    '<div id="root"></div>',
    `<script type="module">\n${pick(".js")}\n</script>`,
  ].join("\n"),
  "utf8",
);
console.log(`wrote ${out} (${(readFileSync(out).length / 1024).toFixed(0)} kB)`);
