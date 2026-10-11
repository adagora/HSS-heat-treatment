/* HSS heat treatment - animation logic.
 *
 * Part 1 (cycle) is a schematic timeline of the M2 hardening cycle with a procedurally drawn
 * microstructure.  Part 2 (quench) plays back the simulation exported by `python -m sim.run`
 * (window.QUENCH_DATA, quench_data.js).
 */
(() => {
  "use strict";

  const D = window.QUENCH_DATA;
  if (!D) {
    document.querySelector(".wrap").insertAdjacentHTML(
      "afterbegin",
      '<p class="narration">The simulation data (quench_data.js) did not load. Run <code>python -m sim.run</code> and reload.</p>'
    );
    return;
  }

  // ------------------------------------------------------------------ utilities
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const MS = D.steel.Ms;
  const BETA = D.steel.beta;

  function mulberry32(seed) {
    return function () {
      seed |= 0;
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const TOKENS = ["bg", "surface", "panel", "fg", "muted", "line", "accent", "accent-2", "water", "oil", "tension",
    "compression", "ok", "warn", "bad", "chip", "bath-water", "bath-oil", "scene", "scene-fg"];
  const C = {};
  function readTheme() {
    const cs = getComputedStyle(document.documentElement);
    for (const k of TOKENS) C[k] = cs.getPropertyValue("--" + k).trim() || "#888888";
  }
  function hex(h) {
    h = h.replace("#", "");
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function rgba(h, a) {
    const [r, g, b] = hex(h);
    return `rgba(${r},${g},${b},${a})`;
  }
  function mix(h1, h2, t) {
    const a = hex(h1), b = hex(h2);
    return `rgb(${Math.round(lerp(a[0], b[0], t))},${Math.round(lerp(a[1], b[1], t))},${Math.round(lerp(a[2], b[2], t))})`;
  }
  readTheme();

  const FONT_BODY = '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif';
  const FONT_MONO = '"IBM Plex Mono", ui-monospace, Menlo, monospace';
  const FONT_DISPLAY = '"Barlow Condensed", "Arial Narrow", sans-serif';

  function fitCanvas(canvas) {
    const r = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(r.width * dpr));
    const h = Math.max(1, Math.round(r.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w: r.width, h: r.height };
  }

  function makeLUT(stops) {
    const lut = new Uint8ClampedArray(256 * 3);
    for (let i = 0; i < 256; i++) {
      const p = i / 255;
      let j = 0;
      while (j < stops.length - 2 && p > stops[j + 1][0]) j++;
      const [p0, c0] = stops[j];
      const [p1, c1] = stops[j + 1];
      const t = clamp((p - p0) / (p1 - p0), 0, 1);
      const a = hex(c0), b = hex(c1);
      for (let k = 0; k < 3; k++) lut[i * 3 + k] = Math.round(lerp(a[k], b[k], t));
    }
    return lut;
  }
  const LUT = {
    T: makeLUT([[0, "#0d0a1f"], [0.15, "#2a0f4f"], [0.3, "#55136e"], [0.45, "#86206a"], [0.6, "#b8345a"],
      [0.72, "#dc5139"], [0.84, "#f28a1c"], [0.93, "#f8c43a"], [1, "#fdf3a8"]]),
    f: makeLUT([[0, "#e3e8ec"], [0.35, "#aea6c8"], [0.7, "#6b4f99"], [1, "#2c1850"]]),
    s: makeLUT([[0, "#1d3f7a"], [0.25, "#5585c6"], [0.5, "#efefef"], [0.75, "#e06f5d"], [1, "#9a1d18"]]),
  };
  const lutCss = (lut, p) => {
    const i = Math.round(clamp(p, 0, 1) * 255) * 3;
    return `rgb(${lut[i]},${lut[i + 1]},${lut[i + 2]})`;
  };

  // incandescent colour of steel (what the eye sees in a dim shop)
  const GLOW = [[20, "#7f8791"], [460, "#7f8791"], [540, "#4d2520"], [620, "#741c12"], [700, "#9b1f10"],
    [800, "#c4300d"], [900, "#e24e17"], [1000, "#f47c20"], [1100, "#faa834"], [1210, "#fdd35c"], [1300, "#fff0b5"]];
  function glowColor(T) {
    let j = 0;
    while (j < GLOW.length - 2 && T > GLOW[j + 1][0]) j++;
    const [T0, c0] = GLOW[j];
    const [T1, c1] = GLOW[j + 1];
    return mix(c0, c1, clamp((T - T0) / (T1 - T0), 0, 1));
  }
  const glowStrength = (T) => clamp((T - 520) / 700, 0, 1);
  const km = (T) => (T < MS ? 1 - Math.exp(-BETA * (MS - T)) : 0);

  // =========================================================== PART 1: CYCLE
  const F_Q = km(60); // martensite after the quench to hand-warm
  const RA = [1 - F_Q, 0.08, 0.03, 0.01]; // retained austenite: as-quenched, after temper 1, 2, 3

  const STAGES = [
    {
      title: "Annealed bar", chip: "Annealed", equip: "bench", label: "Soft-annealed bar, as delivered",
      text: "As delivered, M2 is soft-annealed: ferrite with roughly 20 % rounded alloy carbides (W/Mo-rich M₆C, Cr-rich M₂₃C₆ and very hard V-rich MC). At about 240 HB it can be machined, drilled and ground to shape.",
    },
    {
      title: "Preheat 1", chip: "550 °C", equip: "furnace", label: "Preheat furnace",
      text: "HSS conducts heat poorly, about 21–25 W/m·K, half as well as plain carbon steel. Heating in steps keeps the surface and the core close in temperature, which avoids cracking and distortion and cuts the time spent later at the hardening temperature.",
    },
    {
      title: "Preheat 2", chip: "850 °C", equip: "furnace", label: "Preheat furnace",
      text: "Just above Ac1 (≈ 832 °C) the ferrite starts turning into austenite. The hold lets the whole section reach the same temperature before the final jump of more than 350 °C.",
    },
    {
      title: "Austenitize", chip: "1210 °C", equip: "furnace", label: "High-heat salt bath or vacuum furnace",
      text: "M2 is hardened from 1190–1230 °C, close to where it starts to melt. Part of the alloy carbides dissolve and load the austenite with C, W, Mo, Cr and V; that is what later gives secondary hardness and red hardness. The undissolved M₆C and MC carbides pin the grain boundaries. Hold only minutes: hotter or longer gives grain growth, and above ≈ 1240 °C grain boundaries begin to melt.",
    },
    {
      title: "Quench in oil", chip: "Quench", equip: "tank", label: "Quench tank, oil 50 °C",
      text: "The tool must pass 1000–700 °C quickly so carbides do not precipitate on the grain boundaries. Below Ms ≈ 215 °C the austenite shears into martensite, but not completely: about 30 % is retained at hand-warm. The steel is now hard (≈ 64 HRC), brittle and full of stress. Temper at once.",
    },
    {
      title: "Temper 1", chip: "Temper 1", equip: "furnace", label: "Tempering furnace",
      text: "At 540–570 °C very fine W, Mo and V carbides precipitate inside the martensite. This secondary hardening lifts hardness to its peak of ≈ 65–66 HRC. The retained austenite gives up carbon and alloy to carbides, and on cooling to room temperature it transforms into fresh, untempered martensite.",
    },
    {
      title: "Temper 2", chip: "Temper 2", equip: "furnace", label: "Tempering furnace",
      text: "The second temper tempers the fresh martensite made in the first cooling and converts most of the remaining austenite. Each temper is at least 1–2 h, and the tool must cool to room temperature in between.",
    },
    {
      title: "Temper 3", chip: "Temper 3", equip: "furnace", label: "Tempering furnace",
      text: "Recommended for cutting tools: retained austenite drops below about 2 % and all martensite is tempered. The tool ends at 64–66 HRC, keeps its hardness up to ≈ 550 °C in the cut and stays dimensionally stable.",
    },
  ];

  // [stage, animation seconds, T from, T to, kind]
  const SEGS = [
    [0, 2.5, 20, 20, "hold"],
    [1, 3.0, 20, 550, "heat"], [1, 2.2, 550, 550, "hold"],
    [2, 3.0, 550, 850, "heat"], [2, 2.8, 850, 850, "hold"],
    [3, 3.0, 850, 1210, "heat"], [3, 3.8, 1210, 1210, "hold"],
    [4, 6.0, 1210, 60, "quench"],
    [5, 2.0, 60, 560, "heat"], [5, 3.0, 560, 560, "hold"], [5, 2.8, 560, 20, "cool"],
    [6, 1.6, 20, 560, "heat"], [6, 2.4, 560, 560, "hold"], [6, 2.4, 560, 20, "cool"],
    [7, 1.6, 20, 560, "heat"], [7, 2.4, 560, 560, "hold"], [7, 2.4, 560, 20, "cool"],
    [7, 2.0, 20, 20, "hold"],
  ];
  const REAL = { // real durations written on the chart at the holds
    1: "≈ 15–20 min", 2: "≈ 10–15 min", 3: "2–4 min", 5: "2 h", 6: "2 h", 7: "2 h",
  };
  let acc = 0;
  const segs = SEGS.map(([s, d, a, b, kind], i) => {
    const o = { i, s, d, a, b, kind, u0: acc };
    acc += d;
    return o;
  });
  const U_TOTAL = acc;
  const stageStart = STAGES.map((_, s) => segs.find((g) => g.s === s).u0);

  function segAt(u) {
    for (let i = segs.length - 1; i >= 0; i--) if (u >= segs[i].u0) return segs[i];
    return segs[0];
  }
  function segProgress(g, u) {
    return clamp((u - g.u0) / g.d, 0, 1);
  }
  function shapeT(g, p) {
    if (g.kind === "hold") return g.a;
    if (g.kind === "quench" || g.kind === "cool") {
      const k = g.kind === "quench" ? 4.2 : 3.0;
      const e = (Math.exp(-k * p) - Math.exp(-k)) / (1 - Math.exp(-k));
      return g.b + (g.a - g.b) * e;
    }
    const k = 3.0;
    return g.a + (g.b - g.a) * ((1 - Math.exp(-k * p)) / (1 - Math.exp(-k)));
  }
  function Tcycle(u) {
    u = clamp(u, 0, U_TOTAL);
    const g = segAt(u);
    return shapeT(g, segProgress(g, u));
  }
  // surface leads, core lags: the core follows the surface with a delay
  const Tcore = (u) => Tcycle(u - 0.55);

  function microState(u) {
    const g = segAt(u);
    const p = segProgress(g, u);
    const T = Tcycle(u);
    const s = g.s;
    const st = { T, stage: s, aust: 0, m23: 1, m6: 1, mc: 1, mart: 0, temper: 0, fresh: [0, 0, 0], freshT: [0, 0, 0], ra: 0, hot: false };
    if (s === 2) {
      st.aust = g.kind === "heat" ? 0.6 * clamp((T - 832) / 18, 0, 1) : 0.6 + 0.3 * p;
      st.m23 = 1 - 0.15 * st.aust;
    } else if (s === 3) {
      if (g.kind === "heat") {
        st.aust = lerp(0.9, 1, clamp((T - 850) / 50, 0, 1));
        st.m23 = 0.865 * (1 - clamp((T - 850) / 250, 0, 1));
        st.m6 = 1 - 0.3 * clamp((T - 1000) / 210, 0, 1);
        st.mc = 1 - 0.08 * clamp((T - 1100) / 110, 0, 1);
      } else {
        st.aust = 1;
        st.m23 = 0;
        st.m6 = 0.7 - 0.2 * p;
        st.mc = 0.92 - 0.07 * p;
      }
    } else if (s >= 4) {
      st.aust = 1;
      st.m23 = 0;
      st.m6 = 0.5;
      st.mc = 0.85;
    }
    if (s === 4) st.mart = km(T);
    if (s >= 5) st.mart = F_Q;
    // tempering: each hold tempers what exists; each cooling turns conditioned austenite into fresh martensite
    const temperIdx = s - 5; // 0, 1, 2
    if (s >= 5) {
      for (let k = 0; k < 3; k++) {
        if (k < temperIdx) {
          st.fresh[k] = RA[k] - RA[k + 1];
          st.freshT[k] = 1;
        }
      }
      for (let k = 0; k < temperIdx; k++) st.freshT[k] = k < temperIdx - 1 ? 1 : 0;
      st.temper = temperIdx;
      if (g.kind === "hold") st.temper = temperIdx + p;
      if (g.kind === "cool") {
        st.temper = temperIdx + 1;
        st.fresh[temperIdx] = (RA[temperIdx] - RA[temperIdx + 1]) * clamp((300 - T) / 280, 0, 1);
      }
      if (g.kind === "hold" && temperIdx > 0) st.freshT[temperIdx - 1] = p;
      if (g.kind === "cool" && temperIdx > 0) st.freshT[temperIdx - 1] = 1;
      if (g.i === segs.length - 1) {
        st.temper = 3;
        st.fresh = [RA[0] - RA[1], RA[1] - RA[2], RA[2] - RA[3]];
        st.freshT = [1, 1, 0];
      }
    }
    // retained austenite shown in the fact box
    if (s <= 1) st.ra = 0;
    else if (s <= 3) st.ra = st.aust;
    else if (s === 4) st.ra = 1 - st.mart;
    else st.ra = RA[0] - st.fresh.reduce((a, b) => a + b, 0);
    st.hot = T > 100;
    return st;
  }

  // as quenched, after temper 1, 2, 3 (typical for M2 hardened from ~1210 °C)
  const HARDNESS = ["≈ 64 HRC", "≈ 65.5 HRC", "≈ 65 HRC", "64–66 HRC"];
  function hardnessText(u, st) {
    const s = st.stage;
    if (s === 0) return "≈ 240 HB";
    if (st.T > 120) return "— hot";
    if (s <= 3) return "≈ 240 HB";
    if (s === 4) return HARDNESS[0];
    return segAt(u).kind === "heat" ? HARDNESS[s - 5] : HARDNESS[s - 4];
  }

  // ---------- procedural microstructure ---------------------------------
  const MICRO = 300; // offscreen resolution (px); field ≈ 40 µm
  const micro = (() => {
    const rnd = mulberry32(20261011);
    const N = MICRO;
    const seeds = (n) => Array.from({ length: n }, () => [rnd() * N, rnd() * N]);
    const fSeeds = seeds(85);
    const aSeeds = seeds(30);
    const fId = new Int16Array(N * N);
    const aId = new Int16Array(N * N);
    for (let y = 0; y < N; y++) {
      for (let x = 0; x < N; x++) {
        let best = 1e9, bi = 0;
        for (let i = 0; i < fSeeds.length; i++) {
          const dx = x - fSeeds[i][0], dy = y - fSeeds[i][1];
          const d = dx * dx + dy * dy;
          if (d < best) { best = d; bi = i; }
        }
        fId[y * N + x] = bi;
        best = 1e9; bi = 0;
        for (let i = 0; i < aSeeds.length; i++) {
          const dx = x - aSeeds[i][0], dy = y - aSeeds[i][1];
          // slightly anisotropic metric makes the grains less regular
          const d = dx * dx * (1 + 0.15 * Math.sin(i)) + dy * dy;
          if (d < best) { best = d; bi = i; }
        }
        aId[y * N + x] = bi;
      }
    }
    const isB = (ids, x, y) => {
      const i = ids[y * N + x];
      return (x + 1 < N && ids[y * N + x + 1] !== i) || (y + 1 < N && ids[(y + 1) * N + x] !== i);
    };
    function layer(ids, tones, boundary, twins) {
      const c = document.createElement("canvas");
      c.width = c.height = N;
      const ctx = c.getContext("2d");
      const img = ctx.createImageData(N, N);
      const bnd = hex(boundary);
      for (let y = 0; y < N; y++) {
        for (let x = 0; x < N; x++) {
          const k = y * N + x;
          const g = ids[k];
          let col = tones[g];
          if (twins && twins[g]) {
            const tw = twins[g];
            const d = (x - tw.cx) * tw.nx + (y - tw.cy) * tw.ny;
            if (d > tw.d0 && d < tw.d0 + tw.w) col = tw.col;
          }
          if (isB(ids, x, y)) col = bnd;
          img.data[k * 4] = col[0];
          img.data[k * 4 + 1] = col[1];
          img.data[k * 4 + 2] = col[2];
          img.data[k * 4 + 3] = 255;
        }
      }
      ctx.putImageData(img, 0, 0);
      return c;
    }
    const tone = (base, spread) => {
      const b = hex(base);
      const v = (rnd() - 0.5) * spread;
      return b.map((c) => clamp(Math.round(c + v), 0, 255));
    };
    const fTones = fSeeds.map(() => tone("#c4c8cd", 22));
    const aTones = aSeeds.map(() => tone("#e4e7ea", 10));
    const twins = aSeeds.map(([cx, cy]) => {
      if (rnd() > 0.45) return null;
      const a = rnd() * Math.PI;
      return { cx, cy, nx: Math.cos(a), ny: Math.sin(a), d0: (rnd() - 0.5) * 12, w: 3 + rnd() * 4, col: hex("#d6dade") };
    });
    const ferrite = layer(fId, fTones, "#6f757d", null);
    const austenite = layer(aId, aTones, "#7d838b", twins);

    // grain pixel lists for sampling
    const grainPix = aSeeds.map(() => []);
    for (let k = 0; k < N * N; k++) grainPix[aId[k]].push(k);
    function clipRay(g, x, y, dx, dy, maxLen) {
      let L = 0;
      while (L < maxLen) {
        const px = Math.round(x + dx * (L + 1)), py = Math.round(y + dy * (L + 1));
        if (px < 0 || py < 0 || px >= N || py >= N || aId[py * N + px] !== g) break;
        L++;
      }
      return L;
    }
    function plates(count, minL, maxL, width) {
      const out = [];
      const base = aSeeds.map(() => rnd() * Math.PI);
      for (let n = 0; n < count; n++) {
        const k = Math.floor(rnd() * N * N);
        const g = aId[k];
        const x = k % N, y = Math.floor(k / N);
        const ang = base[g] + Math.floor(rnd() * 3) * (Math.PI / 3) + (rnd() - 0.5) * 0.2;
        const dx = Math.cos(ang), dy = Math.sin(ang);
        const want = minL + rnd() * (maxL - minL);
        const a = clipRay(g, x, y, dx, dy, want);
        const b = clipRay(g, x, y, -dx, -dy, want);
        if (a + b < 3) continue;
        out.push({ x0: x - dx * b, y0: y - dy * b, x1: x + dx * a, y1: y + dy * a, w: width * (0.8 + rnd() * 0.5), len: a + b, key: rnd() });
      }
      // the first plates to form are the long ones that span a grain
      out.sort((p, q) => (q.len * (0.6 + 0.8 * q.key)) - (p.len * (0.6 + 0.8 * p.key)));
      return out;
    }
    const mPlates = plates(1100, 6, 40, 2.6);
    const fPlates = [plates(260, 3, 10, 1.8), plates(80, 3, 8, 1.6), plates(30, 2, 6, 1.4)];
    // carbides: half of the coarse ones sit on prior-austenite grain boundaries
    const bndPix = [];
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) if (isB(aId, x, y)) bndPix.push([x, y]);
    function carbides(n, rmin, rmax, onBoundary) {
      return Array.from({ length: n }, () => {
        let x, y;
        if (rnd() < onBoundary) [x, y] = bndPix[Math.floor(rnd() * bndPix.length)];
        else { x = rnd() * N; y = rnd() * N; }
        return { x, y, r: rmin + rnd() * (rmax - rmin), order: rnd(), sq: 0.75 + rnd() * 0.5, rot: rnd() * Math.PI };
      });
    }
    const carb = {
      m6: carbides(70, 2.2, 4.2, 0.5),
      mc: carbides(32, 1.4, 2.4, 0.4),
      m23: carbides(170, 1.0, 1.9, 0.3),
    };
    const sec = Array.from({ length: 700 }, () => ({ x: rnd() * N, y: rnd() * N, r: 0.55 + rnd() * 0.4, key: rnd() }));
    return { ferrite, austenite, mPlates, fPlates, carb, sec };
  })();

  const microWork = document.createElement("canvas");
  microWork.width = microWork.height = MICRO;

  function drawMicro(st) {
    const ctx = microWork.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.drawImage(micro.ferrite, 0, 0);
    if (st.aust > 0) {
      ctx.globalAlpha = st.aust;
      ctx.drawImage(micro.austenite, 0, 0);
      ctx.globalAlpha = 1;
    }
    ctx.lineCap = "round";
    // martensite from the quench
    const nM = Math.round(micro.mPlates.length * clamp(st.mart / F_Q, 0, 1));
    const tempered = clamp(st.temper, 0, 1);
    ctx.strokeStyle = mix("#8b929e", "#4b515b", tempered);
    for (let i = 0; i < nM; i++) {
      const p = micro.mPlates[i];
      ctx.lineWidth = p.w;
      ctx.beginPath();
      ctx.moveTo(p.x0, p.y0);
      ctx.lineTo(p.x1, p.y1);
      ctx.stroke();
    }
    // fresh martensite formed from retained austenite after each temper
    for (let k = 0; k < 3; k++) {
      const amount = st.fresh[k] / Math.max(RA[k] - RA[k + 1], 1e-6);
      const n = Math.round(micro.fPlates[k].length * clamp(amount, 0, 1));
      if (!n) continue;
      ctx.strokeStyle = mix("#a7aeb9", "#575d67", clamp(st.freshT[k], 0, 1));
      for (let i = 0; i < n; i++) {
        const p = micro.fPlates[k][i];
        ctx.lineWidth = p.w;
        ctx.beginPath();
        ctx.moveTo(p.x0, p.y0);
        ctx.lineTo(p.x1, p.y1);
        ctx.stroke();
      }
    }
    // secondary carbides (nanometre-sized in reality - drawn enlarged)
    if (st.temper > 0) {
      ctx.fillStyle = "#c9ced6";
      const lim = clamp(st.temper, 0, 1) * 0.9 + clamp(st.temper - 1, 0, 2) * 0.05;
      for (const d of micro.sec) {
        if (d.key > lim) continue;
        ctx.beginPath();
        ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    // primary carbides
    ctx.lineWidth = 0.9;
    const drawC = (list, remain, fill) => {
      for (const c of list) {
        if (c.order > remain) continue;
        const shrink = clamp((remain - c.order) * 6, 0.35, 1);
        ctx.fillStyle = fill;
        ctx.strokeStyle = "#5c626b";
        ctx.beginPath();
        ctx.ellipse(c.x, c.y, c.r * shrink, c.r * shrink * c.sq, c.rot, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
    };
    drawC(micro.carb.m23, st.m23, "#f3f1ec");
    drawC(micro.carb.m6, st.m6, "#fbfbf8");
    drawC(micro.carb.mc, st.mc, "#ffffff");

    // eyepiece
    const cv = $("#microCanvas");
    const { ctx: out, w } = fitCanvas(cv);
    out.clearRect(0, 0, w, w);
    out.save();
    out.beginPath();
    out.arc(w / 2, w / 2, w / 2 - 1, 0, Math.PI * 2);
    out.clip();
    out.imageSmoothingEnabled = true;
    out.drawImage(microWork, 0, 0, w, w);
    // scale bar: field is ~40 µm
    const bar = (10 / 40) * w;
    out.fillStyle = "rgba(20,22,26,0.8)";
    out.fillRect(w * 0.56 - 4, w * 0.84 - 13, bar + 8, 20);
    out.fillStyle = "#ffffff";
    out.fillRect(w * 0.56, w * 0.84, bar, 2.5);
    out.font = `500 10px ${FONT_MONO}`;
    out.textAlign = "center";
    out.fillText("10 µm", w * 0.56 + bar / 2, w * 0.84 - 3);
    out.restore();
    out.strokeStyle = C.line;
    out.lineWidth = 2;
    out.beginPath();
    out.arc(w / 2, w / 2, w / 2 - 1, 0, Math.PI * 2);
    out.stroke();
  }

  function legendFor(st) {
    const items = [];
    if (st.aust < 1) items.push(["#c4c8cd", st.aust > 0 ? "Ferrite (turning to austenite)" : "Ferrite"]);
    if (st.aust > 0 && st.stage <= 3) items.push(["#e4e7ea", "Austenite (hot)"]);
    if (st.mart > 0) items.push([st.temper >= 1 ? "#4b515b" : "#8b929e", st.temper >= 1 ? "Tempered martensite" : "Martensite (as quenched)"]);
    if (st.fresh.some((v) => v > 0)) items.push(["#a7aeb9", "Fresh martensite from retained austenite"]);
    if (st.stage >= 4 && st.ra > 0.005) items.push(["#e4e7ea", "Retained austenite"]);
    if (st.temper > 0) items.push(["#c9ced6", "Secondary carbides (shown enlarged)"]);
    items.push(["#ffffff", st.stage >= 3 ? "Undissolved carbides M₆C, MC" : "Alloy carbides M₆C, M₂₃C₆, MC"]);
    return items;
  }

  // ---------- scene ---------------------------------------------------------
  const sceneParticles = [];
  let sceneRnd = mulberry32(7);

  function drawBar(ctx, x, y, L, H, depth, Ts, Tc, alpha = 1) {
    const top = glowColor(Ts);
    const g = glowStrength(Ts);
    ctx.save();
    ctx.globalAlpha = alpha;
    if (g > 0) {
      ctx.shadowColor = glowColor(Ts + 60);
      ctx.shadowBlur = 8 + 40 * g;
    }
    // front face
    ctx.fillStyle = top;
    ctx.fillRect(x, y, L, H);
    ctx.shadowBlur = 0;
    // top face
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + depth, y - depth * 0.6);
    ctx.lineTo(x + L + depth, y - depth * 0.6);
    ctx.lineTo(x + L, y);
    ctx.closePath();
    ctx.fillStyle = mix(hexOf(top), "#ffffff", 0.18);
    ctx.fill();
    // shading on front
    const sh = ctx.createLinearGradient(0, y, 0, y + H);
    sh.addColorStop(0, "rgba(0,0,0,0)");
    sh.addColorStop(1, "rgba(0,0,0,0.28)");
    ctx.fillStyle = sh;
    ctx.fillRect(x, y, L, H);
    // end face shows the section: core vs surface
    ctx.beginPath();
    ctx.moveTo(x + L, y);
    ctx.lineTo(x + L + depth, y - depth * 0.6);
    ctx.lineTo(x + L + depth, y - depth * 0.6 + H);
    ctx.lineTo(x + L, y + H);
    ctx.closePath();
    const cx = x + L + depth / 2, cy = y + H / 2 - depth * 0.3;
    const rg = ctx.createRadialGradient(cx, cy, 1, cx, cy, Math.max(H, depth) * 0.7);
    rg.addColorStop(0, glowColor(Tc));
    rg.addColorStop(1, glowColor(Ts));
    ctx.fillStyle = rg;
    ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,0.35)";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.restore();
  }
  function hexOf(rgb) {
    const m = rgb.match(/\d+/g).map(Number);
    return "#" + m.slice(0, 3).map((v) => v.toString(16).padStart(2, "0")).join("");
  }

  function drawFurnace(ctx, w, h, setT, label) {
    const fx = w * 0.08, fy = h * 0.2, fw = w * 0.84, fh = h * 0.62;
    // shell
    ctx.fillStyle = "#3a3f47";
    ctx.fillRect(fx - 14, fy - 14, fw + 28, fh + 28);
    // brick courses
    ctx.strokeStyle = "rgba(0,0,0,0.25)";
    ctx.lineWidth = 1;
    for (let yy = fy - 14; yy < fy + fh + 14; yy += 12) {
      ctx.beginPath();
      ctx.moveTo(fx - 14, yy);
      ctx.lineTo(fx + fw + 14, yy);
      ctx.stroke();
    }
    // chamber
    const inner = glowColor(setT);
    const rg = ctx.createRadialGradient(fx + fw / 2, fy + fh / 2, 10, fx + fw / 2, fy + fh / 2, fw * 0.6);
    rg.addColorStop(0, mix(hexOf(inner), "#000000", 0.35));
    rg.addColorStop(1, mix(hexOf(inner), "#000000", 0.75));
    ctx.fillStyle = setT > 470 ? rg : "#262a30";
    ctx.fillRect(fx, fy, fw, fh);
    // heating elements
    ctx.strokeStyle = setT > 470 ? glowColor(setT + 80) : "#555b63";
    ctx.lineWidth = 2;
    for (const yy of [fy + 10, fy + fh - 10]) {
      ctx.beginPath();
      for (let xx = fx + 10; xx <= fx + fw - 10; xx += 8) ctx.lineTo(xx, yy + ((xx / 8) % 2 ? 4 : -4));
      ctx.stroke();
    }
    // hearth
    ctx.fillStyle = "#4a4f57";
    ctx.fillRect(fx + fw * 0.12, fy + fh * 0.72, fw * 0.76, 6);
    ctx.fillStyle = C["scene-fg"];
    ctx.font = `500 13px ${FONT_BODY}`;
    ctx.textAlign = "left";
    ctx.fillText(label, fx - 6, fy - 26);
  }

  function drawTank(ctx, w, h, Ts, dt, playing, contents) {
    const tx = w * 0.1, ty = h * 0.24, tw = w * 0.8, th = h * 0.66;
    ctx.fillStyle = "#3a3f47";
    ctx.fillRect(tx - 8, ty, tw + 16, th + 8);
    ctx.fillStyle = "#1d1407";
    ctx.fillRect(tx, ty + 14, tw, th - 6);
    contents(ty, th);
    const oil = ctx.createLinearGradient(0, ty + 10, 0, ty + th);
    oil.addColorStop(0, "rgba(160,104,26,0.55)");
    oil.addColorStop(1, "rgba(75,48,11,0.75)");
    ctx.fillStyle = oil;
    ctx.fillRect(tx, ty + 14, tw, th - 6);
    ctx.fillStyle = "rgba(255,214,140,0.35)";
    ctx.fillRect(tx, ty + 14, tw, 1.5);
    ctx.fillStyle = C["scene-fg"];
    ctx.font = `500 13px ${FONT_BODY}`;
    ctx.textAlign = "left";
    ctx.fillText("Quench tank · oil, 50 °C", tx - 6, ty - 14);
    // particles: vapour film above ~700 °C, boiling 320-700 °C, fumes at the top early on
    if (playing) {
      const barY = ty + th * 0.45, barX = w * 0.22, barL = w * 0.5;
      const rate = Ts > 700 ? 30 : Ts > 320 ? 90 * clamp((Ts - 320) / 250, 0.2, 1) : 0;
      const n = rate * dt + sceneRnd();
      for (let i = 0; i < Math.floor(n); i++) {
        sceneParticles.push({ x: barX + sceneRnd() * barL, y: barY - 4 + sceneRnd() * 30, vy: -30 - sceneRnd() * 40, r: 1.5 + sceneRnd() * 3, life: 1.2 + sceneRnd() });
      }
      if (Ts > 450 && sceneRnd() < dt * 8) sceneParticles.push({ x: tx + tw * (0.3 + 0.4 * sceneRnd()), y: ty + 10, vy: -25, r: 8 + sceneRnd() * 10, life: 2, smoke: true });
      for (const p of sceneParticles) {
        p.y += p.vy * dt;
        p.life -= dt;
        if (!p.smoke && p.y < ty + 18) p.life = 0;
      }
      for (let i = sceneParticles.length - 1; i >= 0; i--) if (sceneParticles[i].life <= 0) sceneParticles.splice(i, 1);
    }
    return { tx, ty, tw, th };
  }

  function drawScene(u, dt, playing) {
    const cv = $("#sceneCanvas");
    const { ctx, w, h } = fitCanvas(cv);
    const g = segAt(u);
    const stage = STAGES[g.s];
    const Ts = Tcycle(u);
    const Tc = Tcore(u);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = C.scene;
    ctx.fillRect(0, 0, w, h);
    // floor
    ctx.fillStyle = "rgba(255,255,255,0.04)";
    ctx.fillRect(0, h * 0.9, w, h * 0.1);

    const L = w * 0.5, H = Math.max(18, h * 0.1), depth = H * 0.9;
    let barX = w * 0.22, barY = h * 0.5;
    if (stage.equip === "bench") {
      ctx.fillStyle = "#4a4f57";
      ctx.fillRect(w * 0.12, h * 0.62, w * 0.76, 10);
      ctx.fillRect(w * 0.16, h * 0.62, 8, h * 0.28);
      ctx.fillRect(w * 0.82, h * 0.62, 8, h * 0.28);
      ctx.fillStyle = C["scene-fg"];
      ctx.font = `500 13px ${FONT_BODY}`;
      ctx.textAlign = "left";
      ctx.fillText(stage.label, w * 0.12, h * 0.2);
      barY = h * 0.62 - H;
      drawBar(ctx, barX, barY, L, H, depth, Ts, Tc);
    } else if (stage.equip === "furnace") {
      const setT = g.kind === "cool" ? 20 : Math.max(g.a, g.b);
      const lbl = `${stage.label} · ${g.kind === "cool" ? "out, cooling in air" : setT + " °C"}`;
      if (g.kind === "cool") {
        ctx.fillStyle = C["scene-fg"];
        ctx.font = `500 13px ${FONT_BODY}`;
        ctx.textAlign = "left";
        ctx.fillText(`${stage.title} · cooling in still air to room temperature`, w * 0.08, h * 0.2);
        ctx.fillStyle = "#4a4f57";
        ctx.fillRect(w * 0.12, h * 0.66, w * 0.76, 8);
        barY = h * 0.66 - H;
      } else {
        drawFurnace(ctx, w, h, setT, lbl);
        barY = h * 0.2 + h * 0.62 * 0.72 - H;
      }
      drawBar(ctx, barX, barY, L, H, depth, Ts, Tc);
    } else if (stage.equip === "tank") {
      drawTank(ctx, w, h, Ts, dt, playing, (ty, th) => {
        barY = ty + th * 0.45;
        drawBar(ctx, barX, barY, L, H, depth, Ts, Tc);
        if (Ts > 700) { // vapour film around the bar
          ctx.save();
          ctx.strokeStyle = "rgba(255,236,190,0.45)";
          ctx.lineWidth = 6;
          ctx.strokeRect(barX - 3, barY - depth * 0.6 - 3, L + depth + 6, H + depth * 0.6 + 6);
          ctx.restore();
        }
      });
    }
    // particles (bubbles / fumes)
    if (stage.equip === "tank") {
      for (const p of sceneParticles) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        if (p.smoke) {
          ctx.fillStyle = `rgba(200,200,200,${0.12 * clamp(p.life / 2, 0, 1)})`;
          ctx.fill();
        } else {
          ctx.strokeStyle = "rgba(255,230,170,0.6)";
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
    } else {
      sceneParticles.length = 0;
    }
    // temperature readout
    ctx.textAlign = "right";
    ctx.fillStyle = Ts > 520 ? glowColor(Math.max(Ts, 700)) : C["scene-fg"];
    ctx.font = `600 ${Math.round(clamp(w * 0.07, 26, 46))}px ${FONT_DISPLAY}`;
    ctx.fillText(`${Math.round(Ts)} °C`, w - 16, h * 0.12 + 12);
    ctx.font = `400 11px ${FONT_MONO}`;
    ctx.fillStyle = C["scene-fg"];
    ctx.fillText(`surface ${Math.round(Ts)} · core ${Math.round(Tc)} °C`, w - 16, h * 0.12 + 30);
    // phase label
    ctx.textAlign = "left";
    ctx.font = `500 12px ${FONT_MONO}`;
    ctx.fillStyle = C["scene-fg"];
    ctx.fillText(phaseText(microState(u)), 14, h - 12);
  }
  function phaseText(st) {
    if (st.stage <= 1) return "ferrite + alloy carbides";
    if (st.stage === 2) return st.aust > 0 ? "ferrite → austenite + carbides" : "ferrite + alloy carbides";
    if (st.stage === 3) return "austenite + undissolved carbides";
    if (st.stage === 4) return st.mart > 0 ? `martensite ${Math.round(st.mart * 100)} % + austenite + carbides` : "austenite + carbides (cooling)";
    return `tempered martensite + ${Math.round(st.ra * 100)} % retained austenite + carbides`;
  }

  // ---------- cycle chart ------------------------------------------------------
  function drawCycleChart(u) {
    const cv = $("#cycleChart");
    const { ctx, w, h } = fitCanvas(cv);
    ctx.clearRect(0, 0, w, h);
    const m = { l: 46, r: 12, t: 26, b: 22 };
    const X = (uu) => m.l + (uu / U_TOTAL) * (w - m.l - m.r);
    const Y = (T) => m.t + (1 - T / 1300) * (h - m.t - m.b);
    ctx.font = `400 10px ${FONT_MONO}`;
    ctx.fillStyle = C.muted;
    ctx.strokeStyle = C.line;
    ctx.lineWidth = 1;
    ctx.textAlign = "right";
    for (let T = 0; T <= 1200; T += 200) {
      ctx.beginPath();
      ctx.moveTo(m.l, Y(T));
      ctx.lineTo(w - m.r, Y(T));
      ctx.globalAlpha = 0.6;
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillText(T + "", m.l - 6, Y(T) + 3);
    }
    ctx.save();
    ctx.translate(11, m.t + (h - m.t - m.b) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillText("°C", 0, 0);
    ctx.restore();
    // reference lines
    const ref = (T, col, dash, text) => {
      ctx.strokeStyle = col;
      ctx.setLineDash(dash);
      ctx.beginPath();
      ctx.moveTo(m.l, Y(T));
      ctx.lineTo(w - m.r, Y(T));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = col;
      ctx.textAlign = "right";
      ctx.fillText(text, w - m.r - 2, Y(T) - 4);
    };
    ref(1240, C.bad, [4, 3], "grain boundaries start to melt ≈ 1240");
    ref(D.steel.Ac1, C.muted, [2, 3], `Ac1 ≈ ${D.steel.Ac1}`);
    ref(MS, C.accent, [], `Ms ≈ ${MS}`);
    // stage bands + labels
    ctx.textAlign = "center";
    ctx.font = `500 10px ${FONT_BODY}`;
    for (let s = 0; s < STAGES.length; s++) {
      const a = stageStart[s];
      const b = s + 1 < STAGES.length ? stageStart[s + 1] : U_TOTAL;
      if (s % 2 === 1) {
        ctx.fillStyle = rgba(C.fg, 0.035);
        ctx.fillRect(X(a), m.t, X(b) - X(a), h - m.t - m.b);
      }
      ctx.fillStyle = s === segAt(u).s ? C.fg : C.muted;
      ctx.fillText(STAGES[s].chip, (X(a) + X(b)) / 2, m.t - 10);
    }
    // path
    const path = (u0, u1) => {
      ctx.beginPath();
      for (let k = 0; k <= 400; k++) {
        const uu = lerp(u0, u1, k / 400);
        const x = X(uu), y = Y(Tcycle(uu));
        if (k === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    };
    ctx.lineWidth = 2;
    ctx.strokeStyle = rgba(C.fg, 0.2);
    path(0, U_TOTAL);
    ctx.strokeStyle = C["accent-2"];
    ctx.lineWidth = 2.5;
    path(0, u);
    // real durations at the holds
    ctx.font = `400 10px ${FONT_MONO}`;
    ctx.fillStyle = C.muted;
    for (const g of segs) {
      if (g.kind !== "hold" || !REAL[g.s] || g.a < 100) continue;
      ctx.textAlign = "center";
      ctx.fillText(REAL[g.s], X(g.u0 + g.d / 2), Y(g.a) - 7);
    }
    ctx.fillText("oil → 60 °C", X(stageStart[4] + 2.6), Y(700));
    // marker
    const T = Tcycle(u);
    ctx.fillStyle = T > 520 ? glowColor(Math.max(T, 750)) : C["accent-2"];
    ctx.strokeStyle = C.panel;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(X(u), Y(T), 5.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }

  // ---------- cycle controller --------------------------------------------
  const stageRep = (i) => {
    const last = segs.filter((g) => g.s === i).pop();
    return i === 0 ? 1 : last.u0 + last.d - (i === STAGES.length - 1 ? 2.05 : 0.02);
  };
  const cycle = { u: reduceMotion ? stageRep(3) - 1 : 0, playing: false };
  const chipsEl = $("#cycleChips");
  STAGES.forEach((s, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.setAttribute("role", "listitem");
    b.innerHTML = `<span class="n">${i + 1}</span>${s.chip}`;
    b.addEventListener("click", () => {
      sceneParticles.length = 0;
      if (reduceMotion) {
        cycle.u = stageRep(i); // show the state at the end of the step
        renderCycle(0);
      } else {
        cycle.u = stageStart[i];
        setCyclePlaying(true);
      }
    });
    chipsEl.appendChild(b);
  });
  const cyclePlayBtn = $("#cyclePlay");
  function setCyclePlaying(on) {
    cycle.playing = on;
    cyclePlayBtn.textContent = on ? "Pause" : "Play";
  }
  cyclePlayBtn.addEventListener("click", () => {
    if (!cycle.playing && cycle.u >= U_TOTAL - 0.01) cycle.u = 0;
    setCyclePlaying(!cycle.playing);
  });
  $("#cycleRestart").addEventListener("click", () => {
    cycle.u = 0;
    sceneParticles.length = 0;
    setCyclePlaying(true);
  });

  let lastStageShown = -1;
  function renderCycle(dt) {
    const st = microState(cycle.u);
    const s = st.stage;
    if (s !== lastStageShown) {
      lastStageShown = s;
      $("#stageStep").textContent = `Step ${s + 1} of ${STAGES.length}`;
      $("#stageTitle").textContent = STAGES[s].title;
      $("#stageText").textContent = STAGES[s].text;
      $$(".chip", chipsEl).forEach((c, i) => (i === s ? c.setAttribute("aria-current", "step") : c.removeAttribute("aria-current")));
    }
    $("#factT").textContent = `${Math.round(st.T)} °C`;
    $("#factH").textContent = hardnessText(cycle.u, st);
    $("#factRA").textContent = s <= 1 ? "0 %" : s <= 3 || st.mart === 0 ? "— hot" : `≈ ${Math.round(st.ra * 100)} %`;
    const lg = legendFor(st).map(([c, t]) => `<div><span class="sw" style="background:${c}"></span>${t}</div>`).join("");
    const legendEl = $("#microLegend");
    if (legendEl.dataset.html !== lg) {
      legendEl.innerHTML = lg;
      legendEl.dataset.html = lg;
    }
    drawMicro(st);
    drawScene(cycle.u, dt, cycle.playing);
    drawCycleChart(cycle.u);
  }

  // =========================================================== PART 2: QUENCH
  function b64bytes(s) {
    const bin = atob(s);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return u8;
  }
  const NQ = D.bar.quarterNodes; // nodes per side of the quarter
  const NE = NQ - 1;
  const THR = D.steel.crackThresholds.map((t) => t.MPa); // smooth face, typical, worst case
  const THR_WORST = Math.min(...THR);

  function prepMedium(m) {
    const fr = m.frames;
    const T = new Uint16Array(b64bytes(fr.T).buffer);
    const f = new Uint8Array(b64bytes(fr.f).buffer);
    const s1 = new Int16Array(b64bytes(fr.s1).buffer);
    const h = m.history;
    const cummax = [];
    let mx = 0;
    for (const v of h.sigBrittle) cummax.push((mx = Math.max(mx, v)));
    return {
      ...m, T, f, s1, cummax,
      nn: NQ * NQ, ne: NE * NE,
      tEnd: fr.t[fr.t.length - 1],
      bufT: new Float32Array(NQ * NQ), bufF: new Float32Array(NQ * NQ), bufS: new Float32Array(NE * NE),
      bubbles: [],
      rnd: mulberry32(m.key === "water" ? 11 : 23),
    };
  }
  const MEDIA = { water: prepMedium(D.media.water), oil: prepMedium(D.media.oil) };
  const T_MAX = Math.max(MEDIA.water.tEnd, MEDIA.oil.tEnd);
  const LOG0 = Math.log10(0.05);
  const LOG1 = Math.log10(T_MAX);
  const vToT = (v) => (v <= 0 ? 0 : Math.pow(10, lerp(LOG0, LOG1, v / 1000)));
  const tToV = (t) => (t <= 0.05 ? 0 : clamp(((Math.log10(t) - LOG0) / (LOG1 - LOG0)) * 1000, 0, 1000));

  function hInterp(arrT, arrV, x) {
    if (x <= arrT[0]) return arrV[0];
    if (x >= arrT[arrT.length - 1]) return arrV[arrV.length - 1];
    let lo = 0, hi = arrT.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (arrT[mid] <= x) lo = mid;
      else hi = mid;
    }
    const w = (x - arrT[lo]) / (arrT[hi] - arrT[lo] || 1);
    return arrV[lo] + (arrV[hi] - arrV[lo]) * w;
  }
  function hist(M, key, t) {
    return hInterp(M.history.t, M.history[key], t);
  }
  function histCumMax(M, t) {
    return hInterp(M.history.t, M.cummax, t);
  }
  const hOf = (M, Ts) => hInterp(M.hT, M.hV, Ts);
  function stageOf(M, Ts) {
    if (Ts > M.stageVapourAbove) return "vapour";
    if (Ts > M.stageBoilingAbove) return "boiling";
    return "convection";
  }
  const STAGE_TEXT = { vapour: "vapour blanket", boiling: "boiling", convection: "convection" };

  function frameAt(M, t) {
    const ft = M.frames.t;
    t = Math.min(t, M.tEnd);
    let k = 0;
    while (k < ft.length - 2 && ft[k + 1] <= t) k++;
    const w = clamp((t - ft[k]) / (ft[k + 1] - ft[k] || 1), 0, 1);
    const nn = M.nn, ne = M.ne;
    const a = k * nn, b = (k + 1) * nn;
    for (let i = 0; i < nn; i++) {
      M.bufT[i] = lerp(M.T[a + i], M.T[b + i], w) / 50;
      M.bufF[i] = lerp(M.f[a + i], M.f[b + i], w) / 255;
    }
    const c = k * ne, d = (k + 1) * ne;
    for (let i = 0; i < ne; i++) M.bufS[i] = lerp(M.s1[c + i], M.s1[d + i], w);
    return { k: w < 0.5 ? k : k + 1 };
  }

  // offscreen field images (full section mirrored from the quarter)
  const imgNodal = document.createElement("canvas");
  imgNodal.width = imgNodal.height = 2 * NQ - 1;
  const imgElem = document.createElement("canvas");
  imgElem.width = imgElem.height = 2 * NE;
  const qIdx = (I, n, nodal) => (nodal ? Math.abs(I - (n - 1)) : I >= n ? I - n : n - 1 - I);

  function paintField(M, view) {
    const nodal = view !== "s";
    const cv = nodal ? imgNodal : imgElem;
    const n = nodal ? NQ : NE;
    const size = cv.width;
    const ctx = cv.getContext("2d");
    const img = ctx.createImageData(size, size);
    const lut = LUT[view];
    for (let J = 0; J < size; J++) {
      // canvas row 0 is the top of the bar: y = +L
      const iy = qIdx(size - 1 - J, n, nodal);
      for (let I = 0; I < size; I++) {
        const ix = qIdx(I, n, nodal);
        let p;
        if (view === "T") p = (M.bufT[iy * NQ + ix] - 20) / (1210 - 20);
        else if (view === "f") p = M.bufF[iy * NQ + ix] / 0.78;
        else p = 0.5 + M.bufS[iy * NE + ix] / 1000;
        const li = Math.round(clamp(p, 0, 1) * 255) * 3;
        const o = (J * size + I) * 4;
        img.data[o] = lut[li];
        img.data[o + 1] = lut[li + 1];
        img.data[o + 2] = lut[li + 2];
        img.data[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return cv;
  }

  // marching squares for the Ms isotherm on the mirrored nodal grid
  function msContour(M) {
    const n = 2 * NQ - 1;
    const val = (I, J) => M.bufT[qIdx(J, NQ, true) * NQ + qIdx(I, NQ, true)] - MS;
    const segsOut = [];
    for (let J = 0; J < n - 1; J++) {
      for (let I = 0; I < n - 1; I++) {
        const v = [val(I, J), val(I + 1, J), val(I + 1, J + 1), val(I, J + 1)];
        const pts = [];
        const P = [[I, J], [I + 1, J], [I + 1, J + 1], [I, J + 1]];
        for (let e = 0; e < 4; e++) {
          const a = v[e], b = v[(e + 1) % 4];
          if ((a < 0) !== (b < 0)) {
            const t = a / (a - b);
            const pa = P[e], pb = P[(e + 1) % 4];
            pts.push([lerp(pa[0], pb[0], t), lerp(pa[1], pb[1], t)]);
          }
        }
        if (pts.length >= 2) segsOut.push(pts[0], pts[1]);
        if (pts.length === 4) segsOut.push(pts[2], pts[3]);
      }
    }
    return segsOut; // grid coords, J = 0 at y = -L ... drawn flipped
  }

  const quench = { v: tToV(8.5), playing: false, speed: 1, view: "T", started: false };

  function drawPanel(key, t, dtWall) {
    const M = MEDIA[key];
    const panel = $("#panel-" + key);
    const cv = $("[data-role=canvas]", panel);
    const { ctx, w, h } = fitCanvas(cv);
    frameAt(M, t);
    const done = t >= M.tEnd;
    // bath
    const bath = C[key === "water" ? "bath-water" : "bath-oil"];
    const bg = ctx.createLinearGradient(0, 0, 0, h);
    bg.addColorStop(0, bath);
    bg.addColorStop(1, mix(bath, C.fg, 0.12));
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    const S = Math.min(w * 0.62, h * 0.62);
    const x0 = (w - S) / 2, y0 = h * 0.47 - S / 2;
    const L = S / 2;
    const cxc = x0 + L, cyc = y0 + L;

    // surface state along the edges (identical on all four faces by symmetry)
    const edgeT = [];
    for (let i = 0; i < 2 * NQ - 1; i++) edgeT.push(M.bufT[(NQ - 1) * NQ + qIdx(i, NQ, true)]);
    const Tface = edgeT[NQ - 1];
    const stage = stageOf(M, Tface);
    const hFace = hOf(M, Tface);

    // vapour film
    const step = S / (2 * NQ - 2);
    ctx.save();
    ctx.lineCap = "round";
    const now = performance.now() / 1000;
    for (let side = 0; side < 4; side++) {
      for (let i = 0; i < edgeT.length - 1; i++) {
        const Ts = 0.5 * (edgeT[i] + edgeT[i + 1]);
        if (stageOf(M, Ts) !== "vapour") continue;
        const wob = 4 + 2 * Math.sin(now * 3 + i * 0.7 + side);
        const s0 = -L + i * step, s1 = s0 + step;
        const pt = (s) => side === 0 ? [cxc + s, y0 - wob] : side === 1 ? [x0 + S + wob, cyc + s] : side === 2 ? [cxc + s, y0 + S + wob] : [x0 - wob, cyc + s];
        const [ax, ay] = pt(s0), [bx, by] = pt(s1);
        ctx.strokeStyle = key === "water" ? "rgba(255,255,255,0.55)" : "rgba(255,238,200,0.5)";
        ctx.lineWidth = 6;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.stroke();
      }
    }
    ctx.restore();

    // bubbles
    if (dtWall > 0 && !done) {
      const hMax = key === "water" ? 15000 : 4200;
      for (let side = 0; side < 4; side++) {
        for (let i = 0; i < edgeT.length; i += 2) {
          const Ts = edgeT[i];
          if (stageOf(M, Ts) !== "boiling") continue;
          const rate = 7 * (hOf(M, Ts) / hMax);
          if (M.rnd() > rate * dtWall) continue;
          const s = -L + i * step;
          const [bx, by, nx, ny] = side === 0 ? [cxc + s, y0, 0, -1] : side === 1 ? [x0 + S, cyc + s, 1, 0] : side === 2 ? [cxc + s, y0 + S, 0, 1] : [x0, cyc + s, -1, 0];
          M.bubbles.push({
            x: bx + nx * 2, y: by + ny * 2, vx: nx * 18 + (M.rnd() - 0.5) * 10, vy: ny * 18,
            r: key === "water" ? 1.4 + M.rnd() * 2.2 : 2 + M.rnd() * 3, life: key === "water" ? 0.25 + M.rnd() * 0.4 : 0.8 + M.rnd() * 0.9, age: 0,
          });
        }
      }
      if (M.bubbles.length > 500) M.bubbles.splice(0, M.bubbles.length - 500);
    }
    if (dtWall > 0) {
      for (const b of M.bubbles) {
        b.vy -= 70 * dtWall; // buoyancy
        b.vx *= 0.96;
        b.x += b.vx * dtWall;
        b.y += b.vy * dtWall;
        b.age += dtWall;
      }
      M.bubbles = M.bubbles.filter((b) => b.age < b.life);
    }
    ctx.lineWidth = 1;
    for (const b of M.bubbles) {
      const a = 1 - b.age / b.life;
      // sub-cooled water: steam bubbles collapse as they leave; oil vapour bubbles live longer
      const r = key === "water" ? b.r * (0.6 + 0.6 * a) : b.r * (0.8 + 0.3 * (1 - a));
      ctx.strokeStyle = key === "water" ? `rgba(255,255,255,${0.75 * a})` : `rgba(255,244,215,${0.7 * a})`;
      ctx.fillStyle = key === "water" ? `rgba(255,255,255,${0.18 * a})` : `rgba(255,236,190,${0.15 * a})`;
      ctx.beginPath();
      ctx.arc(b.x, b.y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
    // convection shimmer above the bar
    if (stage === "convection") {
      const strength = clamp((Tface - M.bath) / 160, 0, 1) * 0.45;
      if (strength > 0.02) {
        ctx.strokeStyle = key === "water" ? `rgba(255,255,255,${strength})` : `rgba(255,240,205,${strength})`;
        ctx.lineWidth = 1.2;
        for (let j = 0; j < 5; j++) {
          const xx = x0 + S * (0.15 + 0.175 * j);
          ctx.beginPath();
          for (let k = 0; k <= 20; k++) {
            const yy = y0 - 4 - k * (y0 - 8) / 20;
            const ph = (dtWall > 0 ? now : 0) * 2 + j;
            ctx.lineTo(xx + 3 * Math.sin(k * 0.6 + ph), yy);
          }
          ctx.stroke();
        }
      }
    }

    // the section
    const view = quench.view;
    const field = paintField(M, view);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(field, x0, y0, S, S);
    ctx.strokeStyle = rgba(C.fg, 0.55);
    ctx.lineWidth = 1;
    ctx.strokeRect(x0 + 0.5, y0 + 0.5, S - 1, S - 1);

    // Ms isotherm
    if (view !== "s") {
      const seg = msContour(M);
      if (seg.length) {
        ctx.save();
        ctx.strokeStyle = view === "T" ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.8)";
        ctx.setLineDash([4, 3]);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        const n = 2 * NQ - 2;
        for (let i = 0; i < seg.length; i += 2) {
          const [ax, ay] = seg[i], [bx, by] = seg[i + 1];
          ctx.moveTo(x0 + (ax / n) * S, y0 + S - (ay / n) * S);
          ctx.lineTo(x0 + (bx / n) * S, y0 + S - (by / n) * S);
        }
        ctx.stroke();
        ctx.restore();
      }
    }

    // probe points
    const probes = [["corner", x0 + S - 3, y0 + 3], ["face", x0 + S - 3, cyc], ["core", cxc, cyc]];
    ctx.font = `500 10px ${FONT_MONO}`;
    for (const [name, px, py] of probes) {
      ctx.strokeStyle = "#ffffff";
      ctx.fillStyle = "rgba(0,0,0,0.55)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(px, py, 3.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      if (name !== "core") {
        ctx.textAlign = "left";
        const tx = x0 + S + 10, ty = name === "corner" ? y0 + 4 : cyc + 4;
        ctx.fillStyle = rgba(C.fg, 0.85);
        ctx.fillText(name, tx, ty);
      }
    }
    ctx.textAlign = "center";
    ctx.fillStyle = "rgba(255,255,255,0.9)";
    ctx.fillText("core", cxc, cyc - 8);

    // crack-risk marker: peak tension in brittle martensite above the worst-case threshold
    const peakSoFar = histCumMax(M, Math.min(t, M.tEnd));
    if (peakSoFar >= THR_WORST) {
      const fk = frameAt(M, Math.min(t, M.tEnd)).k;
      const [iy, ix] = M.frames.hotspot[Math.min(fk, M.frames.hotspot.length - 1)];
      const qx = (ix + 0.5) / NE, qy = (iy + 0.5) / NE;
      const pulse = 0.5 + 0.5 * Math.sin(now * 5);
      const spots = [[qx, qy], [-qx, qy], [qx, -qy], [-qx, -qy], [qy, qx], [-qy, qx], [qy, -qx], [-qy, -qx]];
      ctx.strokeStyle = C.bad;
      ctx.lineWidth = 2;
      const seen = new Set();
      for (const [sx, sy] of spots) {
        const px = cxc + sx * L, py = cyc - sy * L;
        const k = `${Math.round(px)},${Math.round(py)}`;
        if (seen.has(k)) continue;
        seen.add(k);
        ctx.globalAlpha = 0.55 + 0.45 * pulse;
        ctx.beginPath();
        ctx.arc(px, py, 7 + 3 * pulse, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      // illustrative hairline crack starting at the top-face hot spot
      const px = cxc + Math.min(qx, qy) * L;
      ctx.strokeStyle = "#1a0d0d";
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(px, y0);
      const depth = S * 0.16;
      for (let k = 1; k <= 6; k++) ctx.lineTo(px + (k % 2 ? 2.2 : -2.2), y0 + (depth * k) / 6);
      ctx.stroke();
      ctx.fillStyle = C.bad;
      ctx.font = `600 10.5px ${FONT_BODY}`;
      ctx.textAlign = "center";
      ctx.fillText("crack can start here at a notch or flaw", cxc, y0 - 16 > 10 ? y0 - 16 : y0 + S + 16);
    }

    // colour bar
    const cbW = Math.min(S * 1.15, w - 40), cbX = (w - cbW) / 2, cbY = y0 + S + 24;
    const grad = ctx.createLinearGradient(cbX, 0, cbX + cbW, 0);
    for (let i = 0; i <= 10; i++) grad.addColorStop(i / 10, lutCss(LUT[view], i / 10));
    ctx.fillStyle = grad;
    ctx.fillRect(cbX, cbY, cbW, 7);
    ctx.font = `400 10px ${FONT_MONO}`;
    ctx.fillStyle = rgba(C.fg, 0.8);
    const labels = view === "T" ? ["20 °C", `Ms ${MS}`, "1210 °C"] : view === "f" ? ["austenite", "", "≈ 78 % martensite"] : ["−500 MPa", "0", "+500 MPa tension"];
    ctx.textAlign = "left";
    ctx.fillText(labels[0], cbX, cbY + 19);
    ctx.textAlign = "right";
    ctx.fillText(labels[2], cbX + cbW, cbY + 19);
    if (labels[1]) {
      const p = view === "T" ? (MS - 20) / 1190 : 0.5;
      const mid = cbX + p * cbW;
      ctx.fillRect(mid - 0.5, cbY - 2, 1, 11);
      const half = ctx.measureText(labels[1]).width / 2;
      const leftEnd = cbX + ctx.measureText(labels[0]).width + 4;
      ctx.textAlign = "center";
      if (mid - half > leftEnd) ctx.fillText(labels[1], mid, cbY + 19);
      else ctx.fillText(labels[1], Math.max(mid, leftEnd + half), cbY - 6);
    }
    if (view === "T") {
      ctx.textAlign = "left";
      ctx.fillStyle = rgba(C.fg, 0.8);
      ctx.fillText(w < 400 ? "- - Ms isotherm" : "- - Ms isotherm: martensite forms on the outer side", 10, 16);
    }
    if (done) {
      ctx.textAlign = "right";
      ctx.fillStyle = rgba(C.fg, 0.85);
      ctx.font = `500 11px ${FONT_BODY}`;
      ctx.fillText(`out of the bath at ${M.tEnd.toFixed(0)} s, core 60 °C`, w - 10, 16);
    }

    // readouts
    const tt = Math.min(t, M.tEnd);
    const set = (role, txt) => {
      const el = $(`[data-role=${role}]`, panel);
      if (el.textContent !== txt) el.textContent = txt;
    };
    set("Tk", `${Math.round(hist(M, "Tcorner", tt))} °C`);
    set("Tf", `${Math.round(hist(M, "Tface", tt))} °C`);
    set("Tc", `${Math.round(hist(M, "Tcore", tt))} °C`);
    set("fm", `${Math.round(hist(M, "fcore", tt) * 100)} %`);
    const pill = $("[data-role=stage]", panel);
    const pillTxt = done ? "out of the bath" : `${STAGE_TEXT[stage]} · h ${(hFace / 1000).toFixed(1)} kW/m²K`;
    if (pill.textContent !== pillTxt) {
      pill.textContent = pillTxt;
      pill.dataset.stage = done ? "convection" : stage;
    }
    // verdict
    const fs = hist(M, "fcorner", tt);
    const peak = peakSoFar;
    let flag, cls, msg;
    if (fs < D.steel.brittleFraction) {
      const dT = hist(M, "Tcore", tt) - hist(M, "Tcorner", tt);
      flag = "ductile"; cls = "info";
      msg = fs > 0.01
        ? `Martensite is forming at the corners. Core is ${Math.round(dT)} °C hotter than the corners.`
        : `Still austenite, which is ductile. Core is ${Math.round(dT)} °C hotter than the corners.`;
    } else if (peak >= THR_WORST) {
      flag = "crack risk"; cls = "bad";
      msg = `Tension in brittle martensite has reached ${Math.round(peak)} MPa, above the ${Math.round(THR_WORST)} MPa needed to start a crack at a sharp notch with a carbide cluster.`;
    } else if (hist(M, "Tcore", tt) > MS + 3) {
      flag = "loading"; cls = "warn";
      msg = `The outside is brittle martensite while the core is still ${Math.round(hist(M, "Tcore", tt))} °C austenite. When the core transforms it will swell and pull on the shell.`;
    } else if (peak < 1) {
      flag = "safe"; cls = "ok";
      msg = "The whole section is transforming together. No tension in the brittle martensite so far.";
    } else {
      flag = peak > THR_WORST * 0.5 ? "watch" : "safe"; cls = peak > THR_WORST * 0.5 ? "warn" : "ok";
      msg = `Tension in brittle martensite: ${Math.round(peak)} MPa so far, ${(THR_WORST / Math.max(peak, 1)).toFixed(0)}× below even the worst-case crack threshold (${Math.round(THR_WORST)} MPa).`;
    }
    const vEl = $("[data-role=verdict]", panel);
    const html = `<span class="flag ${cls}">${flag}</span><span>${msg}</span>`;
    if (vEl.dataset.html !== html) {
      vEl.innerHTML = html;
      vEl.dataset.html = html;
    }
  }

  // ---------- quench charts ---------------------------------------------------
  function axesLog(ctx, w, h, m, xmin, xmax, ymin, ymax, yTicks, yLabel, yFmt) {
    const X = (t) => m.l + ((Math.log10(Math.max(t, Math.pow(10, xmin))) - xmin) / (xmax - xmin)) * (w - m.l - m.r);
    const Y = (v) => m.t + (1 - (v - ymin) / (ymax - ymin)) * (h - m.t - m.b);
    ctx.font = `400 10px ${FONT_MONO}`;
    ctx.lineWidth = 1;
    ctx.strokeStyle = C.line;
    ctx.fillStyle = C.muted;
    ctx.textAlign = "right";
    for (const v of yTicks) {
      ctx.globalAlpha = 0.7;
      ctx.beginPath();
      ctx.moveTo(m.l, Y(v));
      ctx.lineTo(w - m.r, Y(v));
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillText(yFmt(v), m.l - 5, Y(v) + 3);
    }
    ctx.textAlign = "center";
    for (let e = Math.ceil(xmin); e <= Math.floor(xmax); e++) {
      const x = X(Math.pow(10, e));
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      ctx.moveTo(x, m.t);
      ctx.lineTo(x, h - m.b);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillText(e < 0 ? Math.pow(10, e).toFixed(-e) : String(Math.pow(10, e)), x, h - m.b + 13);
    }
    ctx.fillText("time in the bath (s, log scale)", m.l + (w - m.l - m.r) / 2, h - 2);
    ctx.save();
    ctx.translate(11, m.t + (h - m.t - m.b) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(yLabel, 0, 0);
    ctx.restore();
    return { X, Y };
  }

  function drawSeries(ctx, X, Y, M, key, t, color, dash, width) {
    const H = M.history;
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.setLineDash(dash);
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < H.t.length; i++) {
      if (H.t[i] > t) break;
      const x = X(H.t[i]), y = Y(H[key][i]);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    if (started && t <= M.tEnd) ctx.lineTo(X(t), Y(hist(M, key, t)));
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawCCT(t) {
    const cv = $("#cctChart");
    const { ctx, w, h } = fitCanvas(cv);
    ctx.clearRect(0, 0, w, h);
    const m = { l: 44, r: 20, t: 8, b: 30 };
    const xmin = LOG0, xmax = 4;
    const { X, Y } = axesLog(ctx, w, h, m, xmin, xmax, 0, 1250, [0, 200, 400, 600, 800, 1000, 1200], "°C", (v) => String(v));
    // schematic CCT fields
    ctx.font = `400 9.5px ${FONT_BODY}`;
    for (const key of Object.keys(D.cct)) {
      const fld = D.cct[key];
      const pts = fld.points;
      ctx.beginPath();
      ctx.moveTo(w - m.r, Y(pts[0][0]));
      for (const [T, tt] of pts) ctx.lineTo(X(tt), Y(T));
      ctx.lineTo(w - m.r, Y(pts[pts.length - 1][0]));
      ctx.closePath();
      ctx.fillStyle = rgba(C.muted, 0.14);
      ctx.fill();
      ctx.strokeStyle = rgba(C.muted, 0.7);
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      pts.forEach(([T, tt], i) => (i ? ctx.lineTo(X(tt), Y(T)) : ctx.moveTo(X(tt), Y(T))));
      ctx.stroke();
      ctx.setLineDash([]);
      const nose = pts.reduce((a, b) => (b[1] < a[1] ? b : a));
      ctx.fillStyle = C.muted;
      ctx.textAlign = "left";
      ctx.fillText(key === "carbides" ? "carbides" : key, X(nose[1]) + 4, Y(nose[0]) + 3);
    }
    // Ms and Ac1
    ctx.strokeStyle = C.accent;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(m.l, Y(MS));
    ctx.lineTo(w - m.r, Y(MS));
    ctx.stroke();
    ctx.fillStyle = C.accent;
    ctx.textAlign = "right";
    ctx.font = `500 10px ${FONT_MONO}`;
    ctx.fillText(`Ms ${MS} °C · martensite below`, w - m.r - 2, Y(MS) + 12);
    ctx.fillStyle = C.muted;
    ctx.fillText("schematic CCT fields, M2", w - m.r - 2, m.t + 10);
    // curves
    const tw = Math.min(t, MEDIA.water.tEnd), to = Math.min(t, MEDIA.oil.tEnd);
    drawSeries(ctx, X, Y, MEDIA.oil, "Tcorner", to, C.oil, [4, 3], 1.5);
    drawSeries(ctx, X, Y, MEDIA.oil, "Tcore", to, C.oil, [], 2.4);
    drawSeries(ctx, X, Y, MEDIA.water, "Tcorner", tw, C.water, [4, 3], 1.5);
    drawSeries(ctx, X, Y, MEDIA.water, "Tcore", tw, C.water, [], 2.4);
    // cursor
    if (t > 0.05) {
      ctx.strokeStyle = rgba(C.fg, 0.4);
      ctx.beginPath();
      ctx.moveTo(X(t), m.t);
      ctx.lineTo(X(t), h - m.b);
      ctx.stroke();
    }
  }

  function drawStressChart(t) {
    const cv = $("#stressChart");
    const { ctx, w, h } = fitCanvas(cv);
    ctx.clearRect(0, 0, w, h);
    const m = { l: 44, r: 10, t: 8, b: 30 };
    const xmin = LOG0, xmax = Math.log10(400);
    const ymax = 480;
    const { X, Y } = axesLog(ctx, w, h, m, xmin, xmax, 0, ymax, [0, 100, 200, 300, 400], "MPa", (v) => String(v));
    // thresholds
    ctx.font = `400 9.5px ${FONT_BODY}`;
    const labels = ["smooth face", "typical tool feature", "sharp notch + carbide cluster"];
    D.steel.crackThresholds.forEach((thr, i) => {
      const v = thr.MPa;
      ctx.strokeStyle = C.bad;
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1;
      if (v <= ymax) {
        ctx.beginPath();
        ctx.moveTo(m.l, Y(v));
        ctx.lineTo(w - m.r, Y(v));
        ctx.stroke();
        ctx.fillStyle = C.bad;
        ctx.textAlign = "left";
        ctx.fillText(`crack threshold: ${labels[i]} (${Math.round(v)} MPa)`, m.l + 6, Y(v) - 4);
      } else {
        ctx.fillStyle = C.bad;
        ctx.textAlign = "right";
        ctx.fillText(`smooth face: ${Math.round(v)} MPa, off scale ↑`, w - m.r - 4, m.t + 10);
      }
      ctx.setLineDash([]);
    });
    const tw = Math.min(t, MEDIA.water.tEnd), to = Math.min(t, MEDIA.oil.tEnd);
    drawSeries(ctx, X, Y, MEDIA.oil, "sigBrittle", to, C.oil, [], 2.4);
    drawSeries(ctx, X, Y, MEDIA.water, "sigBrittle", tw, C.water, [], 2.4);
    if (t > 0.05) {
      ctx.strokeStyle = rgba(C.fg, 0.4);
      ctx.beginPath();
      ctx.moveTo(X(t), m.t);
      ctx.lineTo(X(t), h - m.b);
      ctx.stroke();
    }
    ctx.fillStyle = C.muted;
    ctx.textAlign = "left";
    ctx.font = `400 9.5px ${FONT_BODY}`;
    ctx.fillText("zero until the material is ≥ 50 % martensite (brittle)", m.l + 6, h - m.b - 6);
  }

  // ---------- narration and events ----------------------------------------
  const SW = MEDIA.water.summary, SO = MEDIA.oil.summary;
  function firstBelow(M, key, level) {
    const H = M.history;
    for (let i = 1; i < H.t.length; i++) if (H[key][i] <= level) return H.t[i];
    return null;
  }
  const r0 = (x) => Math.round(x);
  const events = [
    { t: 0, who: "both", text: "Both bars enter the bath at 1210 °C. A vapour film forms at once and insulates the surface; cold water's film is thinner and leaks more heat than oil's." },
    { t: firstBelow(MEDIA.water, "Tface", MEDIA.water.stageVapourAbove), who: "water", text: "Water: the steam film collapses and the water boils violently on the steel. The heat-transfer coefficient jumps to 8–15 kW/m²K." },
    { t: SW.time_to_Ms_s.corner, who: "water", text: `Water, ${SW.time_to_Ms_s.corner.toFixed(1)} s: the corners pass Ms and turn to martensite while the core is still at ${r0(MS + SW.core_minus_corner_at_corner_Ms_C)} °C.` },
    { t: SW.time_to_Ms_s.face, who: "water", text: `Water, ${SW.time_to_Ms_s.face.toFixed(1)} s: the face centres pass Ms; the core is still ${r0(MS + SW.core_minus_face_at_face_Ms_C)} °C. Water keeps boiling down to about 110 °C, right through the martensite range.` },
    { t: firstBelow(MEDIA.oil, "Tface", MEDIA.oil.stageVapourAbove), who: "oil", text: "Oil: the vapour film breaks near 700 °C. Oil boils hardest around 550 °C, exactly where HSS must cool fast to keep carbides off the grain boundaries." },
    { t: SW.time_to_Ms_s.core, who: "water", text: `Water, ${SW.time_to_Ms_s.core.toFixed(1)} s: the core finally reaches Ms. As it transforms it swells and stretches the already hard, brittle shell.` },
    { t: firstBelow(MEDIA.oil, "Tface", MEDIA.oil.stageBoilingAbove), who: "oil", text: "Oil: boiling stops near 320 °C. The bar now cools gently by convection (≈ 0.3 kW/m²K), and the core catches up with the surface." },
    { t: SW.time_of_max_tensile_stress_s, who: "water", text: `Water, ${r0(SW.time_of_max_tensile_stress_s)} s: tension in the fresh martensite peaks at ${r0(SW.max_tensile_stress_in_martensite_MPa)} MPa, ${(SW.max_tensile_stress_in_martensite_MPa / SO.max_tensile_stress_in_martensite_MPa).toFixed(0)}× the oil value.` },
    { t: SW.quench_time_to_core_60C_s, who: "water", text: `Water, ${r0(SW.quench_time_to_core_60C_s)} s: the core is at 60 °C. The water-quenched bar is done, hard and highly stressed. Oil is still on its way down.` },
    { t: SO.time_to_Ms_s.corner, who: "oil", text: `Oil, ${r0(SO.time_to_Ms_s.corner)} s: the corners pass Ms with the core only ${r0(SO.core_minus_corner_at_corner_Ms_C)} °C hotter.` },
    { t: SO.time_to_Ms_s.core, who: "oil", text: `Oil, ${r0(SO.time_to_Ms_s.core)} s: the whole section has passed Ms within ${(SO.time_to_Ms_s.core - SO.time_to_Ms_s.corner).toFixed(0)} s. Tension in the martensite stays near ${r0(SO.max_tensile_stress_in_martensite_MPa)} MPa.` },
    { t: SO.quench_time_to_core_60C_s, who: "oil", text: `Oil, ${r0(SO.quench_time_to_core_60C_s)} s: done. Both bars now have the same martensite and hardness. Only the water-quenched one carries the stress and the extra distortion.` },
  ].filter((e) => e.t != null).sort((a, b) => a.t - b.t);

  const evEl = $("#qEvents");
  evEl.innerHTML = events.filter((e) => e.t > 0).map((e) => `<i title="${e.text.replace(/"/g, "")}" style="left:${tToV(e.t) / 10}%;background:${e.who === "water" ? "var(--water)" : "var(--oil)"}"></i>`).join("");
  $("#qTicks").innerHTML = [0.1, 1, 10, 100].map((t) => `<span style="left:${tToV(t) / 10}%">${t} s</span>`).join("");

  function narrationAt(t) {
    let cur = events[0];
    for (const e of events) if (e.t <= t + 1e-6) cur = e;
    return cur.text;
  }

  // ---------- quench controller ---------------------------------------------
  const qSlider = $("#qSlider");
  const qPlayBtn = $("#qPlay");
  function setQPlaying(on) {
    quench.playing = on;
    qPlayBtn.textContent = on ? "Pause" : "Play";
  }
  qPlayBtn.addEventListener("click", () => {
    if (!quench.playing && quench.v >= 1000) quench.v = 0;
    quench.started = true;
    setQPlaying(!quench.playing);
  });
  $("#qRestart").addEventListener("click", () => {
    quench.v = 0;
    MEDIA.water.bubbles = [];
    MEDIA.oil.bubbles = [];
    quench.started = true;
    setQPlaying(true);
  });
  qSlider.addEventListener("input", () => {
    quench.v = Number(qSlider.value);
    quench.started = true;
    renderQuench(0);
  });
  $$("[data-view]").forEach((b) => b.addEventListener("click", () => {
    quench.view = b.dataset.view;
    $$("[data-view]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderQuench(0);
  }));
  $$("[data-speed]").forEach((b) => b.addEventListener("click", () => {
    quench.speed = Number(b.dataset.speed);
    $$("[data-speed]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));

  function renderQuench(dtWall) {
    const t = vToT(quench.v);
    if (Number(qSlider.value) !== Math.round(quench.v)) qSlider.value = String(Math.round(quench.v));
    $("#qClock").textContent = t < 10 ? `${t.toFixed(2)} s` : t < 100 ? `${t.toFixed(1)} s` : `${Math.round(t)} s`;
    drawPanel("water", t, dtWall);
    drawPanel("oil", t, dtWall);
    drawCCT(t);
    drawStressChart(t);
    const txt = narrationAt(t);
    const nEl = $("#qNarration");
    if (nEl.textContent !== txt) nEl.textContent = txt;
  }

  // ===================================================== results section
  function fillResults() {
    const fmt = (v, d = 0) => (v == null ? "–" : v.toFixed(d));
    const rows = [
      ["Corners / face centre / core reach Ms (s)", (s) => `${fmt(s.time_to_Ms_s.corner, 1)} / ${fmt(s.time_to_Ms_s.face, 1)} / ${fmt(s.time_to_Ms_s.core, 1)}`],
      ["Core temperature when the corners reach Ms", (s) => `${fmt(MS + s.core_minus_corner_at_corner_Ms_C)} °C`],
      ["Cooling rate of the face centre at Ms", (s) => `${fmt(s.face_cooling_rate_at_Ms_C_per_s, 1)} °C/s`],
      ["Core cooling time 800 → 500 °C", (s) => `${fmt(s.t8_5_core_s, 1)} s`],
      ["Time until the core is at 60 °C", (s) => `${fmt(s.quench_time_to_core_60C_s)} s`],
      ["Martensite at the end (core), rest retained austenite", (s) => `${fmt(s.martensite_fraction_end.core * 100)} %`],
      ["Peak tension in fresh martensite", (s) => `${fmt(s.max_tensile_stress_in_martensite_MPa)} MPa`],
      ["Plastic strain left in the bar, mean / max (distortion)", (s) => `${fmt(s.mean_plastic_strain_pct, 2)} / ${fmt(s.max_plastic_strain_pct, 1)} %`],
      ["Crack thresholds exceeded", (s) => {
        const ex = s.crack_scenarios.filter((c) => c.exceeded).map((c) => c.label);
        return ex.length ? ex.join(", ") : "none";
      }],
    ];
    const tb = $("#resultsTable");
    tb.innerHTML = `<thead><tr><th>Quantity</th><th><span class="dot" style="background:var(--water)"></span> Water, 20 °C</th><th><span class="dot" style="background:var(--oil)"></span> Oil, 50 °C</th></tr></thead><tbody>${rows
      .map(([k, fn]) => `<tr><td>${k}</td><td class="num">${fn(SW)}</td><td class="num">${fn(SO)}</td></tr>`)
      .join("")}</tbody>`;

    const ratio = SW.max_tensile_stress_in_martensite_MPa / SO.max_tensile_stress_in_martensite_MPa;
    const take = [
      ["Water adds no hardness", `Both quenches take the core from 800 to 500 °C in seconds (${SW.t8_5_core_s.toFixed(1)} s in water, ${SO.t8_5_core_s.toFixed(1)} s in oil), far faster than carbide precipitation or pearlite need. Both end with the same martensite and retained austenite, so the same ≈ 64 HRC.`],
      ["Water boils through the martensite range", `Water keeps boiling down to ≈ 110 °C. The corners turn to martensite while the core is still ${r0(MS + SW.core_minus_corner_at_corner_Ms_C)} °C. In oil, boiling stops at ≈ 320 °C and the whole section passes Ms within ${r0(SO.core_minus_corner_at_corner_Ms_C)} °C.`],
      ["The mismatch lands on brittle martensite", `Tension in fresh martensite reaches ${r0(SW.max_tensile_stress_in_martensite_MPa)} MPa in water against ${r0(SO.max_tensile_stress_in_martensite_MPa)} MPa in oil (${ratio.toFixed(0)}×). Plastic strain, which shows up as distortion, is ${(SW.mean_plastic_strain_pct / SO.mean_plastic_strain_pct).toFixed(0)}× larger.`],
      ["Notches and flaws decide the crack", `A smooth bar survives either quench in the model. In water the stress passes the threshold for a sharp notch with a carbide cluster (${r0(THR_WORST)} MPa), and real tools have flutes, holes and edges. In oil it stays ${(THR_WORST / SO.max_tensile_stress_in_martensite_MPa).toFixed(0)}× below even that. That is why HSS is quenched in oil, salt at ≈ 550 °C or pressurized gas, and tempered right away.`],
    ];
    $("#takeaways").innerHTML = take.map(([h, p]) => `<div><h3>${h}</h3><p>${p}</p></div>`).join("");
  }
  fillResults();

  // ===================================================== main loop
  let visCycle = true, visQuench = false;
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((ents) => ents.forEach((e) => (visCycle = e.isIntersecting))).observe($("#cycle"));
    new IntersectionObserver((ents) => ents.forEach((e) => {
      visQuench = e.isIntersecting;
      if (visQuench && !quench.started && !reduceMotion) {
        quench.started = true;
        quench.v = 0;
        setQPlaying(true);
      }
    }), { threshold: 0.25 }).observe($("#quench"));
  } else {
    visQuench = true;
  }

  let last = performance.now();
  let frozen = false; // set by the recording hooks
  function tick(now) {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (!frozen) {
      if (cycle.playing) {
        cycle.u += dt;
        if (cycle.u >= U_TOTAL) {
          cycle.u = U_TOTAL;
          setCyclePlaying(false);
        }
      }
      if (visCycle) renderCycle(cycle.playing ? dt : 0);
      if (quench.playing) {
        quench.v += (1000 / 34) * quench.speed * dt;
        if (quench.v >= 1000) {
          quench.v = 1000;
          setQPlaying(false);
        }
      }
      if (visQuench) renderQuench(quench.playing ? dt : 0);
    }
    requestAnimationFrame(tick);
  }

  function rerenderAll() {
    readTheme();
    lastStageShown = -1;
    renderCycle(0);
    renderQuench(0);
  }
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", rerenderAll);
  new MutationObserver(rerenderAll).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  window.addEventListener("resize", () => rerenderAll());
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(rerenderAll);

  rerenderAll();
  if (!reduceMotion) setCyclePlaying(true);
  requestAnimationFrame(tick);

  // hooks used by tools/record_video.mjs to render deterministic frames
  window.HSS = {
    freeze(on = true) { frozen = on; },
    cycleDuration: U_TOTAL,
    quenchEnd: T_MAX,
    setCycle(u, dt = 1 / 30) {
      cycle.u = clamp(u, 0, U_TOTAL);
      cycle.playing = true;
      renderCycle(dt);
    },
    setQuench(v, dt = 1 / 30, view) {
      if (view) {
        quench.view = view;
        $$("[data-view]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.view === view)));
      }
      quench.v = clamp(v, 0, 1000);
      quench.started = true;
      renderQuench(dt);
    },
    vToT, tToV,
  };
})();
