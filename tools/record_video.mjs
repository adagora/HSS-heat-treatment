// Render the animations of web/index.html frame by frame and encode them with ffmpeg.
//
//   node tools/record_video.mjs            -> media/hss_cycle.mp4, media/hss_quench_water_vs_oil.mp4,
//                                             media/hss_quench_water_vs_oil.gif
//
// Frames are rendered deterministically through the window.HSS hooks in web/app.js, so the
// video does not depend on how fast the machine is.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPlaywright } from "./pw.mjs";

const { chromium } = loadPlaywright();
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(root, "media");
fs.mkdirSync(outDir, { recursive: true });
const FPS = 30;

function ffmpeg(args) {
  const r = spawnSync("ffmpeg", ["-y", "-loglevel", "error", ...args], { stdio: "inherit" });
  if (r.status !== 0) throw new Error("ffmpeg failed: " + args.join(" "));
}

// Scroll the first element to the top and return the viewport clip from it to the last one.
async function clipOf(page, firstSel, lastSel, pad = 12) {
  return page.evaluate(([a, b, p]) => {
    const top = document.querySelector(a).getBoundingClientRect().top + window.scrollY;
    window.scrollTo(0, Math.max(0, top - p));
    const r1 = document.querySelector(a).getBoundingClientRect();
    const r2 = document.querySelector(b).getBoundingClientRect();
    const x = Math.max(0, Math.floor(Math.min(r1.left, r2.left) - p));
    const y = Math.max(0, Math.floor(r1.top - p));
    const w = Math.ceil(Math.max(r1.right, r2.right) - x + p);
    const h = Math.ceil(r2.bottom - y + p);
    return { x, y, width: w - (w % 2), height: h - (h % 2) };
  }, [firstSel, lastSel, pad]);
}

async function record(page, name, clip, frames, setFrame) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `hss-${name}-`));
  for (let i = 0; i < frames; i++) {
    await page.evaluate(setFrame, i);
    await page.screenshot({ path: path.join(dir, `f${String(i).padStart(5, "0")}.png`), clip });
    if (i % 150 === 0) console.log(`${name}: frame ${i}/${frames}`);
  }
  const mp4 = path.join(outDir, `${name}.mp4`);
  ffmpeg(["-framerate", String(FPS), "-i", path.join(dir, "f%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
    "-crf", "20", "-movflags", "+faststart", mp4]);
  console.log("wrote", mp4);
  return { dir, mp4 };
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1280, height: 1400 }, colorScheme: "light", deviceScaleFactor: 1 });
await page.goto("file://" + path.join(root, "web", "index.html"));
await page.waitForTimeout(1200);
await page.evaluate(() => window.HSS.freeze(true));

// ---- part 1: the full cycle ----------------------------------------------------
const cycleDur = await page.evaluate(() => window.HSS.cycleDuration);
const cycleFrames = Math.ceil((cycleDur + 1) * FPS);
let clip = await clipOf(page, "#cycle .controls", "#cycle .chart-box");
await record(page, "hss_cycle", clip, cycleFrames, (i) => window.HSS.setCycle(i / 30, 1 / 30));

// ---- part 2: water vs oil -----------------------------------------------------
clip = await clipOf(page, "#quench .timebar", "#quench .charts");
const passFrames = 32 * FPS;
const hold = 2 * FPS;
const views = ["T", "s"];
const { dir } = await record(page, "hss_quench_water_vs_oil", clip, views.length * (passFrames + hold), (i) => {
  const per = 32 * 30 + 2 * 30;
  const pass = Math.floor(i / per);
  const k = i % per;
  const v = Math.min(1000, (k / (32 * 30)) * 1000);
  window.HSS.setQuench(v, 1 / 30, ["T", "s"][pass]);
});

// short GIF preview of the temperature pass
ffmpeg(["-framerate", String(FPS), "-i", path.join(dir, "f%05d.png"), "-frames:v", String(passFrames + hold),
  "-vf", "fps=12,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
  path.join(outDir, "hss_quench_water_vs_oil.gif")]);
console.log("wrote", path.join(outDir, "hss_quench_water_vs_oil.gif"));
await browser.close();
