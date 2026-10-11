// Render web/index.html headless and save screenshots (desktop + phone, light + dark).
//   node tools/screenshot.mjs [outDir]
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPlaywright } from "./pw.mjs";

const { chromium } = loadPlaywright();

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = process.argv[2] || path.join(root, "screenshots");
const url = "file://" + path.join(root, "web", "index.html");

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const errors = [];
for (const [name, viewport, scheme] of [
  ["desktop-light", { width: 1280, height: 900 }, "light"],
  ["desktop-dark", { width: 1280, height: 900 }, "dark"],
  ["phone-light", { width: 390, height: 844 }, "light"],
]) {
  const page = await browser.newPage({ viewport, colorScheme: scheme, deviceScaleFactor: 1 });
  page.on("console", (m) => m.type() === "error" && errors.push(`${name}: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`${name}: ${e.message}`));
  await page.goto(url);
  await page.waitForTimeout(1500);
  await page.evaluate(() => { window.HSS.freeze(true); window.HSS.setCycle(18.5); });
  await page.screenshot({ path: path.join(out, `${name}-top.png`) });
  const q = await page.$("#quench");
  await q.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.HSS.setQuench(window.HSS.tToV(9.0)));
  await q.screenshot({ path: path.join(out, `${name}-quench.png`) });
  const sw = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (sw > 0) errors.push(`${name}: horizontal overflow ${sw}px`);
  await page.close();
}
await browser.close();
console.log(errors.length ? errors.join("\n") : "no console errors, no overflow");
