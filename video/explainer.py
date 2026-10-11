"""Narrated explainer video: hardening HSS, and water vs oil.

    python video/tts.py                                   # narration (needs GEMINI_API_KEY)
    manim -qh video/explainer.py HSSExplainer             # render 1080p with audio

The quench part plays back the simulation exported by `python -m sim.run`
(web/quench_data.js).  No LaTeX is needed: all text uses Computer Modern
Unicode fonts through Pango.
"""

import base64
import json
import wave
from pathlib import Path

import numpy as np
from manim import (
    BLACK, DOWN, LEFT, ORIGIN, RIGHT, UL, UP, UR, WHITE,
    Arrow, Axes, Circle, Create, DashedLine, Dot, FadeIn, FadeOut, Group, GrowFromEdge, ImageMobject, Indicate,
    Line, MarkupText, MoveAlongPath, Polygon, Rectangle, RoundedRectangle, Scene, Square, Text,
    Transform, ValueTracker, VGroup, VMobject, Write, always_redraw, config, linear, rate_functions,
)
from manim.constants import RESAMPLING_ALGORITHMS

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "video" / "build" / "audio"
MAN = json.loads((AUDIO / "manifest.json").read_text())

config.background_color = "#0c0e12"

SERIF = "CMU Serif"
SANS = "CMU Sans Serif"
WATER = "#58C4DD"
OIL = "#F0AC5F"
MART = "#B189D6"
HOT = "#FC6255"
DIM = "#8E949C"
FG = "#ECEEF1"
YEL = "#FFE066"

MS = 215.0


# ------------------------------------------------------------------ helpers
def T(s, size=34, color=FG, font=SERIF, **kw):
    return Text(s, font=font, font_size=size, color=color, **kw)


def M(s, size=34, color=FG, font=SERIF, **kw):
    return MarkupText(s, font=font, font_size=size, color=color, **kw)


GLOW = [(20, "#7f8791"), (460, "#7f8791"), (540, "#4d2520"), (620, "#741c12"), (700, "#9b1f10"),
        (800, "#c4300d"), (900, "#e24e17"), (1000, "#f47c20"), (1100, "#faa834"), (1210, "#fdd35c"), (1300, "#fff0b5")]


def _hex(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def glow(Tc):
    for (T0, c0), (T1, c1) in zip(GLOW[:-1], GLOW[1:]):
        if Tc <= T1:
            w = np.clip((Tc - T0) / (T1 - T0), 0, 1)
            c = _hex(c0) * (1 - w) + _hex(c1) * w
            return "#%02x%02x%02x" % tuple(int(round(v)) for v in c)
    return GLOW[-1][1]


def lut(stops, n=256):
    pos = np.array([p for p, _ in stops])
    cols = np.array([_hex(c) for _, c in stops])
    x = np.linspace(0, 1, n)
    return np.stack([np.interp(x, pos, cols[:, k]) for k in range(3)], axis=1)


LUT_T = lut([(0, "#0d0a1f"), (0.15, "#2a0f4f"), (0.3, "#55136e"), (0.45, "#86206a"), (0.6, "#b8345a"),
             (0.72, "#dc5139"), (0.84, "#f28a1c"), (0.93, "#f8c43a"), (1, "#fdf3a8")])


# ------------------------------------------------------------------ simulation data
def load_sim():
    s = (ROOT / "web" / "quench_data.js").read_text()
    d = json.loads(s[s.index("{"): s.rstrip().rindex("}") + 1])
    nq = d["bar"]["quarterNodes"]
    media = {}
    for key, m in d["media"].items():
        fr = m["frames"]
        n = fr["count"]
        media[key] = {
            "t": np.array(fr["t"]),
            "T": np.frombuffer(base64.b64decode(fr["T"]), "<u2").reshape(n, nq, nq) / 50.0,
            "f": np.frombuffer(base64.b64decode(fr["f"]), "u1").reshape(n, nq, nq) / 255.0,
            "h": {k: np.array(v) for k, v in m["history"].items()},
            "summary": m["summary"],
            "hT": m["hT"], "hV": m["hV"],
        }
    return d, media


SIM, MEDIA = load_sim()


def field_at(med, t):
    ft = med["t"]
    t = min(t, ft[-1])
    k = int(np.clip(np.searchsorted(ft, t) - 1, 0, len(ft) - 2))
    w = np.clip((t - ft[k]) / (ft[k + 1] - ft[k]), 0, 1)
    return (1 - w) * med["T"][k] + w * med["T"][k + 1], (1 - w) * med["f"][k] + w * med["f"][k + 1]


def mirror(q):
    half = np.concatenate([q[:, :0:-1], q], axis=1)
    return np.concatenate([half[:0:-1], half], axis=0)


def section_image(Tq, fq):
    """RGBA image: temperature colour, tinted purple where martensite has formed."""
    Tf, ff = mirror(Tq), mirror(fq)
    idx = np.clip(((Tf - 20) / 1190 * 255).round().astype(int), 0, 255)
    rgb = LUT_T[idx]
    tint = np.clip(ff / 0.35, 0, 1)[..., None] * 0.9
    rgb = rgb * (1 - tint) + _hex(MART) * tint
    img = np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), 255.0)], axis=2)
    return img[::-1].astype(np.uint8)


def ms_contour(Tq, center, size):
    """White line along the Ms isotherm of the mirrored section (marching squares)."""
    Tf = mirror(Tq) - MS
    n = Tf.shape[0]
    v = VMobject(stroke_color=WHITE, stroke_width=2.5)
    if Tf.max() <= 0 or Tf.min() >= 0:
        return v
    x0, y0 = center[0] - size / 2, center[1] - size / 2
    step = size / (n - 1)
    a, b, c, d = Tf[:-1, :-1], Tf[:-1, 1:], Tf[1:, 1:], Tf[1:, :-1]
    cells = np.argwhere(((a < 0) != (b < 0)) | ((b < 0) != (c < 0)) | ((c < 0) != (d < 0)) | ((d < 0) != (a < 0)))
    for j, i in cells:  # j = row (y index), i = column (x index)
        corners = [(i, j, Tf[j, i]), (i + 1, j, Tf[j, i + 1]), (i + 1, j + 1, Tf[j + 1, i + 1]), (i, j + 1, Tf[j + 1, i])]
        pts = []
        for k in range(4):
            (xa, ya, va), (xb, yb, vb) = corners[k], corners[(k + 1) % 4]
            if (va < 0) != (vb < 0):
                t = va / (va - vb)
                pts.append(np.array([x0 + (xa + t * (xb - xa)) * step, y0 + (ya + t * (yb - ya)) * step, 0.0]))
        for p in range(0, len(pts) - 1, 2):
            v.start_new_path(pts[p])
            v.add_line_to(pts[p + 1])
    return v


def hist(med, key, t):
    return float(np.interp(t, med["h"]["t"], med["h"][key]))


# ------------------------------------------------------------------ narration timing
def sentence_starts(key):
    """Seconds at which each sentence of a clip starts: word-share estimate snapped to pauses."""
    m = MAN[key]
    dur = m["duration"]
    with wave.open(str(AUDIO / f"{key}.wav")) as w:
        s = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
        rate = w.getframerate()
    hop = rate // 100
    env = np.sqrt(np.array([np.mean(s[i:i + hop] ** 2) for i in range(0, len(s) - hop, hop)]))
    quiet = env < 0.05 * env.max()
    gaps, run = [], 0
    for i, q in enumerate(quiet):
        run = run + 1 if q else 0
        if q and (i + 1 == len(quiet) or not quiet[i + 1]) and run >= 18:
            gaps.append((i + 1) * hop / rate)
    out = [0.0]
    for frac in m["starts"][1:]:
        est = frac * dur
        near = [g for g in gaps if abs(g - est) < 2.5]
        out.append(min(near, key=lambda g: abs(g - est)) if near else est)
    return out


# ------------------------------------------------------------------ the video
class HSSExplainer(Scene):
    # ---- narration plumbing
    def seg(self, key):
        self.add_sound(str(AUDIO / f"{key}.wav"))
        self.t0 = self.renderer.time
        self.dur = MAN[key]["duration"]
        self.starts = sentence_starts(key)

    def at(self, k, offset=0.0):
        rem = self.t0 + self.starts[k] + offset - self.renderer.time
        if rem > 1 / 30:
            self.wait(rem)

    def avail(self, k, offset=0.0, cap=None, floor=0.4):
        """Time left until sentence k (+offset) starts, for sizing animations."""
        target = self.dur if k is None else self.starts[k]
        a = self.t0 + target + offset - self.renderer.time
        a = max(floor, a)
        return min(a, cap) if cap else a

    def end(self, gap=0.5):
        rem = self.t0 + self.dur + gap - self.renderer.time
        if rem > 1 / 30:
            self.wait(rem)

    def clear(self, rt=0.6):
        if self.mobjects:
            self.play(*[FadeOut(m) for m in self.mobjects], run_time=rt)

    # ---- drawing pieces
    def bar(self, temp, width=4.6, height=0.7, depth=0.55):
        c = glow(temp)
        front = Rectangle(width=width, height=height, stroke_width=0, fill_color=c, fill_opacity=1)
        top = Polygon(front.get_corner(UL), front.get_corner(UL) + np.array([depth, depth * 0.6, 0]),
                      front.get_corner(UR) + np.array([depth, depth * 0.6, 0]), front.get_corner(UR),
                      stroke_width=0, fill_color=c, fill_opacity=1)
        top.set_fill(_lighter(c, 0.2))
        side = Polygon(front.get_corner(UR), front.get_corner(UR) + np.array([depth, depth * 0.6, 0]),
                       front.get_corner(UR) + np.array([depth, depth * 0.6 - height, 0]), front.get_corner(DOWN + RIGHT),
                       stroke_width=0, fill_color=_lighter(c, -0.15), fill_opacity=1)
        halo = VGroup(*[
            RoundedRectangle(corner_radius=0.3 + 0.1 * i, width=width + 0.35 * i, height=height + 0.6 + 0.35 * i,
                             stroke_width=0, fill_color=c, fill_opacity=0.10 - 0.018 * i).move_to(front.get_center() + np.array([depth / 2, depth * 0.3, 0]))
            for i in range(1, 6)])
        if temp < 520:
            halo.set_opacity(0)
        return VGroup(halo, front, top, side)

    def micro(self, radius=1.3, carbides=70, seed=3, grains=True):
        rng = np.random.default_rng(seed)
        disk = Circle(radius=radius, stroke_color=DIM, stroke_width=2, fill_color="#cfd3d8", fill_opacity=1)
        group = VGroup(disk)
        if grains:
            pts = rng.uniform(-radius, radius, (14, 2))
            for (x, y) in pts:
                if x * x + y * y < radius * radius * 0.85:
                    ang = rng.uniform(0, np.pi)
                    L = rng.uniform(0.3, 0.7)
                    group.add(Line([x - L * np.cos(ang), y - L * np.sin(ang), 0], [x + L * np.cos(ang), y + L * np.sin(ang), 0],
                                   stroke_color="#8b9097", stroke_width=1.2))
        dots = VGroup()
        for _ in range(carbides):
            r = np.sqrt(rng.uniform(0, 1)) * radius * 0.92
            a = rng.uniform(0, 2 * np.pi)
            dots.add(Dot([r * np.cos(a), r * np.sin(a), 0], radius=rng.uniform(0.02, 0.055),
                         color=WHITE, stroke_color="#5c626b", stroke_width=0.8))
        group.add(dots)
        return group, dots

    def needles(self, radius=1.3, n=60, seed=5, color="#6d6680"):
        rng = np.random.default_rng(seed)
        out = VGroup()
        for _ in range(n):
            r = np.sqrt(rng.uniform(0, 1)) * radius * 0.85
            a = rng.uniform(0, 2 * np.pi)
            x, y = r * np.cos(a), r * np.sin(a)
            ang = rng.choice([0.2, 1.25, 2.3]) + rng.uniform(-0.1, 0.1)
            L = rng.uniform(0.08, 0.32)
            out.add(Line([x - L * np.cos(ang), y - L * np.sin(ang), 0], [x + L * np.cos(ang), y + L * np.sin(ang), 0],
                         stroke_color=color, stroke_width=3))
        return out

    # ------------------------------------------------------------------ construct
    def construct(self):
        self.intro()
        self.alloy()
        self.heating_and_quench()
        self.stages()
        self.htc()
        self.simulation()
        self.stress()
        self.crack()
        self.outro()

    # ---- 1
    def intro(self):
        self.seg("intro")
        bar = self.bar(1210).shift(DOWN * 0.4 + LEFT * 0.3)
        temp = T("1210 °C", 40, YEL).next_to(bar, DOWN, buff=0.6)
        self.play(FadeIn(bar, scale=0.96), run_time=1.6)
        self.play(Write(temp), run_time=1.0)
        self.at(1)
        title = T("Hardening high-speed steel", 56).to_edge(UP, buff=0.7)
        hrc = T("≈ 65 HRC, keeps its edge red hot", 28, DIM).next_to(title, DOWN, buff=0.25)
        self.play(Write(title), run_time=1.6)
        self.play(FadeIn(hrc, shift=UP * 0.2), run_time=0.8)
        self.at(2, 2.2)
        w = T("water", 40, WATER)
        o = T("oil", 40, OIL)
        q = T("?", 48, FG)
        choice = VGroup(w, q, o).arrange(RIGHT, buff=0.8).next_to(temp, DOWN, buff=0.5)
        self.play(FadeIn(w, shift=RIGHT * 0.3), FadeIn(o, shift=LEFT * 0.3), run_time=1.0)
        self.play(FadeIn(q), run_time=0.6)
        self.end()
        self.clear()

    # ---- 2
    def alloy(self):
        self.seg("alloy")
        title = T("M2  ·  HS 6-5-2", 46).to_edge(UP, buff=0.6)
        self.play(Write(title), run_time=1.2)
        self.at(1)
        elems = [("C", 0.88, YEL), ("W", 6.2, "#9CDCEB"), ("Mo", 5.0, "#83C167"), ("Cr", 4.1, "#C55F73"), ("V", 1.9, MART)]
        base = np.array([-5.6, -2.3, 0])
        bars, labels = VGroup(), VGroup()
        for i, (el, v, col) in enumerate(elems):
            x = base + RIGHT * (1.15 * i)
            r = Rectangle(width=0.7, height=v * 0.6, stroke_width=0, fill_color=col, fill_opacity=0.9)
            r.move_to(x + UP * (v * 0.3))
            bars.add(r)
            labels.add(VGroup(T(el, 30, col).next_to(r, DOWN, buff=0.15), T(f"{v:g} %", 24, FG).next_to(r, UP, buff=0.1)))
        axis = Line(base + LEFT * 0.5, base + RIGHT * 5.3, stroke_color=DIM)
        cap = T("weight %, rest iron", 22, DIM).next_to(axis, DOWN, buff=0.7)
        per = self.avail(2, cap=6) / 5
        self.play(Create(axis), FadeIn(cap), run_time=0.6)
        for r, lab in zip(bars, labels):
            self.play(GrowFromEdge(r, DOWN), FadeIn(lab), run_time=max(0.5, per - 0.1))
        self.at(2)
        mic, dots = self.micro(radius=1.6, carbides=90)
        mic.move_to(RIGHT * 3.6 + DOWN * 0.5)
        lab = T("carbides: M₆C, MC, M₂₃C₆", 26, FG).next_to(mic, DOWN, buff=0.3)
        self.play(FadeIn(mic[:-1]), run_time=0.8)
        self.play(FadeIn(dots, lag_ratio=0.02), FadeIn(lab), run_time=2.0)
        self.at(3, 2.0)
        note = T("→ hardens even when cooled gently", 30, YEL).next_to(title, DOWN, buff=0.45)
        self.play(Write(note), run_time=1.6)
        self.end()
        self.clear()

    # ---- 3 + 4 + 5: the cycle chart carries through three segments
    def heating_and_quench(self):
        self.seg("heating")
        ax = Axes(x_range=[0, 11.2, 1], y_range=[0, 1300, 200], x_length=11.5, y_length=5.2, tips=False,
                  axis_config={"stroke_color": DIM, "stroke_width": 2, "include_ticks": False},
                  y_axis_config={"include_ticks": True, "tick_size": 0.05}).shift(DOWN * 0.35)
        ylab = VGroup(*[T(str(v), 20, DIM).next_to(ax.c2p(0, v), LEFT, buff=0.15) for v in range(0, 1300, 200)])
        xcap = T("time (schematic)", 22, DIM).next_to(ax.x_axis, DOWN, buff=0.25)
        ycap = T("°C", 22, DIM).next_to(ax.y_axis, UP, buff=0.15)
        knots = [(0, 20), (0.4, 20), (1.2, 550), (1.8, 550), (2.6, 850), (3.2, 850), (4.0, 1210), (4.6, 1210),
                 (5.6, 60), (6.0, 560), (6.5, 560), (7.0, 20), (7.4, 560), (7.9, 560), (8.4, 20), (8.8, 560),
                 (9.3, 560), (9.8, 20)]

        def piece(x0, x1):
            xs = np.linspace(x0, x1, 60)
            ys = np.array([self._cycleT(knots, x) for x in xs])
            v = VMobject(stroke_color=OIL, stroke_width=5)
            v.set_points_smoothly([ax.c2p(x, y) for x, y in zip(xs, ys)])
            return v

        dot = Dot(ax.c2p(0, 20), radius=0.09, color=YEL)
        pieces = VGroup()
        self.play(Create(ax), FadeIn(ylab), FadeIn(xcap), FadeIn(ycap), run_time=1.5)
        self.add(dot)

        def run(x0, x1, rt):
            p = piece(x0, x1)
            pieces.add(p)
            self.play(Create(p), MoveAlongPath(dot, p), run_time=rt, rate_func=linear)
            return p

        self.at(1)
        rt = self.avail(2, cap=6)
        run(0, 1.8, rt * 0.45)
        l550 = T("550 °C", 22, FG).next_to(ax.c2p(1.5, 550), UP, buff=0.12)
        self.play(FadeIn(l550), run_time=0.3)
        run(1.8, 3.2, rt * 0.4)
        l850 = T("850 °C", 22, FG).next_to(ax.c2p(2.9, 850), UP, buff=0.12)
        self.play(FadeIn(l850), run_time=0.3)
        self.at(2)
        # surface races ahead of the core
        demo_s = VMobject(stroke_color=YEL, stroke_width=3)
        demo_c = VMobject(stroke_color="#ff9a5c", stroke_width=3)
        xs = np.linspace(0, 1, 40)
        demo_s.set_points_smoothly([ax.c2p(6.2 + 2.6 * x, 200 + 700 * (1 - np.exp(-5 * x))) for x in xs])
        demo_c.set_points_smoothly([ax.c2p(6.2 + 2.6 * x, 200 + 700 * (1 - np.exp(-5 * max(0, x - 0.25)))) for x in xs])
        tag_s = T("surface", 20, YEL).next_to(ax.c2p(6.6, 640), LEFT, buff=0.08)
        tag_c = T("core", 20, "#ff9a5c").next_to(ax.c2p(7.3, 380), RIGHT, buff=0.1)
        cap = T("heated too fast", 22, DIM).next_to(ax.c2p(7.5, 950), UP, buff=0.1)
        self.play(Create(demo_s), Create(demo_c), FadeIn(tag_s), FadeIn(tag_c), FadeIn(cap), run_time=2.2)
        self.at(3)
        self.play(FadeOut(VGroup(demo_s, demo_c, tag_s, tag_c, cap)), run_time=0.4)
        melt = DashedLine(ax.c2p(0, 1240), ax.c2p(11.2, 1240), stroke_color=HOT, stroke_width=2)
        mlab = T("grain boundaries begin to melt ≈ 1240 °C", 20, HOT).next_to(ax.c2p(11.2, 1240), UP + LEFT, buff=0.08)
        mlab.align_to(melt, RIGHT)
        run(3.2, 4.6, 2.2)
        self.play(Create(melt), FadeIn(mlab), run_time=1.0)
        l1210 = T("1210 °C", 22, YEL).next_to(ax.c2p(4.65, 1210), RIGHT, buff=0.12)
        self.play(FadeIn(l1210), run_time=0.4)
        self.at(4)
        mic, dots = self.micro(radius=0.95, carbides=55, seed=11)
        mic.move_to(ax.c2p(7.6, 640))
        mcap = T("carbides dissolve", 20, FG).next_to(mic, DOWN, buff=0.15)
        self.play(FadeIn(mic), FadeIn(mcap), run_time=0.8)
        rng = np.random.default_rng(1)
        gone = [d for d in dots if rng.uniform() < 0.55]
        self.play(*[FadeOut(d, scale=0.2) for d in gone], run_time=2.5)
        hold = T("2–4 min", 20, DIM).next_to(ax.c2p(4.3, 1210), UP, buff=0.4)
        self.play(FadeIn(hold), run_time=0.5)
        self.end(gap=0.3)
        self.play(FadeOut(VGroup(mic, mcap)), run_time=0.4)

        # ---- quench and martensite
        self.seg("martensite")
        msl = DashedLine(ax.c2p(0, MS), ax.c2p(11.2, MS), stroke_color=MART, stroke_width=2)
        mslab = M("M<sub>s</sub> ≈ 215 °C", 22, MART).next_to(ax.c2p(11.2, MS), UP, buff=0.08)
        mslab.align_to(msl, RIGHT)
        run(4.6, 5.6, 1.6)
        quench_lab = T("quench in oil", 22, OIL).next_to(ax.c2p(5.3, 950), RIGHT, buff=0.1)
        self.play(FadeIn(quench_lab), run_time=0.4)
        self.at(1)
        self.play(Create(msl), FadeIn(mslab), run_time=1.0)
        chart = VGroup(ax, ylab, xcap, ycap, l550, l850, l1210, hold, melt, mlab, msl, mslab, quench_lab, pieces, dot)
        # micro: austenite -> martensite needles
        mic, dots = self.micro(radius=1.1, carbides=25, seed=11)
        mic.move_to(ax.c2p(7.9, 760))
        nd = self.needles(radius=1.1, n=70).move_to(mic.get_center())
        self.play(FadeIn(mic), run_time=0.6)
        self.play(Create(nd, lag_ratio=0.05), run_time=2.4)
        mlab2 = T("martensite: hard, brittle", 22, MART).next_to(mic, DOWN, buff=0.15)
        self.play(FadeIn(mlab2), run_time=0.5)
        self.at(2)
        self.play(FadeOut(VGroup(mic, nd, mlab2)), chart.animate.scale(0.42).to_corner(UL, buff=0.35), run_time=1.0)
        # Koistinen-Marburger law
        kax = Axes(x_range=[0, 250, 50], y_range=[0, 1, 0.25], x_length=6.5, y_length=3.8, tips=False,
                   axis_config={"stroke_color": DIM, "include_ticks": True, "tick_size": 0.05}).shift(RIGHT * 2.2 + DOWN * 0.6)
        kx = VGroup(*[T(str(v), 20, DIM).next_to(kax.c2p(v, 0), DOWN, buff=0.15) for v in range(0, 251, 50)])
        ky = VGroup(*[T(f"{v:g}", 20, DIM).next_to(kax.c2p(0, v), LEFT, buff=0.15) for v in (0, 0.5, 1)])
        kxl = T("temperature (°C)", 22, DIM).next_to(kax.x_axis, DOWN, buff=0.6)
        kyl = T("martensite fraction f", 22, DIM).rotate(np.pi / 2).next_to(kax.y_axis, LEFT, buff=0.55)
        formula = M("f = 1 − e<sup>−β (M<sub>s</sub> − T)</sup>", 40, FG).next_to(kax, UP, buff=0.45)
        beta = SIM["steel"]["beta"]
        self.play(Create(kax), FadeIn(kx), FadeIn(ky), FadeIn(kxl), FadeIn(kyl), run_time=1.0)
        self.play(Write(formula), run_time=1.6)
        tr = ValueTracker(MS)
        curve = always_redraw(lambda: kax.plot(lambda x: 1 - np.exp(-beta * (MS - x)), x_range=[tr.get_value(), MS],
                                               color=MART, stroke_width=5) if tr.get_value() < MS - 0.5 else VMobject())
        kd = always_redraw(lambda: Dot(kax.c2p(tr.get_value(), 1 - np.exp(-beta * max(0, MS - tr.get_value()))), color=YEL, radius=0.08))
        msv = DashedLine(kax.c2p(MS, 0), kax.c2p(MS, 1), stroke_color=MART, stroke_width=1.5)
        self.add(curve, kd, msv)
        self.play(tr.animate.set_value(20), run_time=self.avail(3, cap=6, floor=2.5), rate_func=rate_functions.ease_in_out_sine)
        self.at(3)
        one = DashedLine(kax.c2p(0, 1), kax.c2p(250, 1), stroke_color=DIM, stroke_width=1.5)
        fr = 1 - np.exp(-beta * (MS - 20))
        gapline = Line(kax.c2p(20, fr), kax.c2p(20, 1), stroke_color=YEL, stroke_width=3)
        ra = T("≈ 25 % austenite left", 24, YEL).next_to(gapline, RIGHT, buff=0.2)
        self.play(Create(one), Create(gapline), FadeIn(ra), run_time=1.4)
        self.end(gap=0.3)
        self.play(FadeOut(VGroup(kax, kx, ky, kxl, kyl, formula, curve, kd, msv, one, gapline, ra)), run_time=0.6)
        self.play(chart.animate.scale(1 / 0.42).move_to(ORIGIN + DOWN * 0.35 + RIGHT * 0.0), run_time=0.8)

        # ---- temper
        self.seg("temper")
        for a, b in ((5.6, 7.0), (7.0, 8.4), (8.4, 9.8)):
            run(a, b, 1.5)
        t560 = T("560 °C, three times", 22, FG).next_to(ax.c2p(7.7, 600), UP, buff=0.12)
        self.play(FadeIn(t560), run_time=0.4)
        self.at(1)
        self.play(Group(*[m for m in self.mobjects if not isinstance(m, ValueTracker)]).animate.scale(0.62).to_edge(UP, buff=0.25),
                  run_time=0.8)
        vals = [("as quenched", 0.30), ("temper 1", 0.08), ("temper 2", 0.03), ("temper 3", 0.01)]
        rbars = VGroup()
        for i, (name, v) in enumerate(vals):
            r = Rectangle(width=max(0.05, v * 12), height=0.28, stroke_width=0, fill_color=OIL if i == 0 else YEL, fill_opacity=0.85)
            row = VGroup(T(name, 20, DIM), r, T(f"{round(v * 100)} %", 20, FG))
            row.arrange(RIGHT, buff=0.25)
            rbars.add(row)
        rbars.arrange(DOWN, aligned_edge=LEFT, buff=0.18).to_edge(DOWN, buff=0.45).to_edge(LEFT, buff=1.2)
        for row in rbars:
            row[1].align_to(rbars[0][1], LEFT)
        for row in rbars:
            row[2].next_to(row[1], RIGHT, buff=0.25)
        rlab = T("retained austenite", 22, FG).next_to(rbars, UP, buff=0.15).align_to(rbars, LEFT)
        sec = VGroup(T("secondary hardening:", 24, YEL), T("fine W, Mo, V carbides", 24, YEL)).arrange(DOWN, buff=0.1)
        sec.move_to(np.array([3.6, -1.4, 0]))
        per = self.avail(2, cap=8) / 5
        self.play(FadeIn(rlab), run_time=0.4)
        self.play(FadeIn(sec), run_time=max(0.5, per))
        for row in rbars:
            self.play(FadeIn(row[0]), GrowFromEdge(row[1], LEFT), FadeIn(row[2]), run_time=max(0.5, per))
        self.at(2, 1.5)
        hrc = T("64–66 HRC", 54, YEL).next_to(sec, DOWN, buff=0.35)
        self.play(Write(hrc), run_time=1.2)
        self.end()
        self.clear()

    @staticmethod
    def _cycleT(knots, x):
        for (x0, y0), (x1, y1) in zip(knots[:-1], knots[1:]):
            if x <= x1:
                p = 0 if x1 == x0 else (x - x0) / (x1 - x0)
                if y1 == y0:
                    return y0
                k = 3.0
                if y1 > y0:
                    e = (1 - np.exp(-k * p)) / (1 - np.exp(-k))
                else:
                    e = 1 - (np.exp(-k * p) - np.exp(-k)) / (1 - np.exp(-k))
                return y0 + (y1 - y0) * e
        return knots[-1][1]

    # ---- 6
    def stages(self):
        self.seg("stages")
        q = T("Why oil, and not water?", 52).move_to(UP * 0.4)
        self.play(Write(q), run_time=1.6)
        self.at(1)
        self.play(q.animate.scale(0.7).to_edge(UP, buff=0.5), run_time=0.8)
        cards = []
        for i, (name, sub) in enumerate((("1  vapour blanket", "insulating, slow"),
                                         ("2  boiling", "violent, fastest"),
                                         ("3  convection", "calm, slow"))):
            c = VGroup()
            sq = Square(1.4, stroke_width=0, fill_color=glow(1000 - 300 * i), fill_opacity=1)
            c.add(sq)
            if i == 0:
                film = RoundedRectangle(corner_radius=0.25, width=1.85, height=1.85, stroke_color=WHITE, stroke_width=6, stroke_opacity=0.5)
                c.add(film)
            elif i == 1:
                rng = np.random.default_rng(4)
                for _ in range(40):
                    side = rng.integers(4)
                    s = rng.uniform(-0.7, 0.7)
                    off = rng.uniform(0.75, 1.15)
                    p = [(s, off), (off, s), (s, -off), (-off, s)][side]
                    c.add(Circle(radius=rng.uniform(0.04, 0.11), stroke_color=WHITE, stroke_width=1.5, fill_opacity=0).move_to([p[0], p[1], 0]))
            else:
                for k in range(4):
                    w = VMobject(stroke_color=WHITE, stroke_width=1.6, stroke_opacity=0.6)
                    ys = np.linspace(0.8, 1.6, 20)
                    w.set_points_smoothly([[-0.5 + k * 0.33 + 0.06 * np.sin(8 * y), y, 0] for y in ys])
                    c.add(w)
            label = VGroup(T(name, 26, FG), T(sub, 22, DIM)).arrange(DOWN, buff=0.1).next_to(sq, DOWN, buff=0.5)
            c.add(label)
            cards.append(c)
        for i, c in enumerate(cards):
            c.move_to(np.array([-4.3 + 4.3 * i, -0.4, 0]))
        for i, c in enumerate(cards):
            self.at(1 + i, 0.3)
            self.play(FadeIn(c, shift=UP * 0.2), run_time=1.0)
        self.end()
        self.clear()

    # ---- 7
    def htc(self):
        self.seg("htc")
        ax = Axes(x_range=[0, 1190, 200], y_range=[0, 16, 4], x_length=10.5, y_length=4.8, tips=False,
                  axis_config={"stroke_color": DIM, "include_ticks": False},
                  y_axis_config={"include_ticks": True, "tick_size": 0.05}).shift(DOWN * 0.5)
        X = lambda Tc: 1210 - Tc  # hot on the left, as time runs
        xl = VGroup(*[T(str(v), 20, DIM).next_to(ax.c2p(X(v), 0), DOWN, buff=0.15) for v in (1200, 1000, 800, 600, 400, 200, 20)])
        yl = VGroup(*[T(str(v), 20, DIM).next_to(ax.c2p(0, v), LEFT, buff=0.15) for v in (0, 4, 8, 12, 16)])
        xc = T("surface temperature (°C) — cooling runs left to right", 22, DIM).next_to(ax.x_axis, DOWN, buff=0.6)
        yc = T("h (kW/m²K)", 22, DIM).next_to(ax.y_axis, UP, buff=0.15)
        band = Rectangle(width=ax.c2p(X(20), 0)[0] - ax.c2p(X(MS), 0)[0], height=ax.y_length, stroke_width=0,
                         fill_color=MART, fill_opacity=0.15).move_to(ax.c2p((X(MS) + X(20)) / 2, 8))
        blab = T("martensite forms", 20, MART).next_to(band, UP, buff=0.1)

        def curve(med, col):
            Ts = np.linspace(1210, 20, 300)
            hv = np.interp(Ts, med["hT"], med["hV"]) / 1000
            v = VMobject(stroke_color=col, stroke_width=5)
            v.set_points_as_corners([ax.c2p(X(a), b) for a, b in zip(Ts, hv)])
            return v

        cw, co = curve(MEDIA["water"], WATER), curve(MEDIA["oil"], OIL)
        lw = T("water", 26, WATER).next_to(ax.c2p(X(420), 15), UP, buff=0.1)
        lo = T("oil", 26, OIL).next_to(ax.c2p(X(470), 3.3), RIGHT, buff=0.12)
        self.play(Create(ax), FadeIn(xl), FadeIn(yl), FadeIn(xc), FadeIn(yc), run_time=1.2)
        self.play(Create(cw), Create(co), FadeIn(lw), FadeIn(lo), run_time=2.0)
        self.play(FadeIn(band), FadeIn(blab), run_time=0.8)
        self.at(1)
        wb = T("water still boils down to ≈ 110 °C", 22, WATER).move_to(ax.c2p(X(980), 12.5))
        self.play(Indicate(cw, color=WATER, scale_factor=1.0), FadeIn(wb), run_time=1.6)
        self.at(2)
        ob = T("oil boils hardest ≈ 550 °C", 22, OIL).next_to(ax.c2p(X(560), 4.3), UP, buff=0.2)
        oc = T("calm below ≈ 320 °C", 22, OIL).next_to(ax.c2p(X(320), 0.6), UP, buff=0.35)
        self.play(FadeIn(ob), Indicate(co, color=OIL, scale_factor=1.0), run_time=1.4)
        self.at(2, 4.5)
        self.play(FadeIn(oc), run_time=0.8)
        self.at(3)
        hw = float(np.interp(MS, MEDIA["water"]["hT"], MEDIA["water"]["hV"])) / 1000
        ho = float(np.interp(MS, MEDIA["oil"]["hT"], MEDIA["oil"]["hV"])) / 1000
        vline = DashedLine(ax.c2p(X(MS), 0), ax.c2p(X(MS), 16), stroke_color=FG, stroke_width=1.5)
        dw, do = Dot(ax.c2p(X(MS), hw), color=WATER, radius=0.09), Dot(ax.c2p(X(MS), ho), color=OIL, radius=0.09)
        tw = T(f"{hw:.1f}", 22, WATER).next_to(dw, RIGHT, buff=0.12)
        to = T(f"{ho:.2f}", 22, OIL).next_to(do, UP + RIGHT, buff=0.08)
        ratio = T(f"≈ {hw / ho:.0f}×", 40, YEL).move_to(ax.c2p(X(390), 8.5))
        self.play(FadeOut(wb), FadeOut(oc), FadeOut(ob), Create(vline), FadeIn(dw), FadeIn(do), FadeIn(tw), FadeIn(to), run_time=1.0)
        self.play(Write(ratio), run_time=1.0)
        self.end()
        self.clear()

    # ---- 8
    def simulation(self):
        self.seg("simulation")
        size = 3.3
        tt = ValueTracker(0.0)

        def panel(key, col, x):
            med = MEDIA[key]
            img = ImageMobject(section_image(*field_at(med, 0.0)))
            img.set_resampling_algorithm(RESAMPLING_ALGORITHMS["bilinear"])
            img.height = size
            img.move_to([x, 0.15, 0])

            def upd(m):
                m.pixel_array = section_image(*field_at(med, tt.get_value()))
            img.add_updater(upd)
            frame = Square(size, stroke_color=col, stroke_width=2).move_to(img)
            cont = always_redraw(lambda: ms_contour(field_at(med, tt.get_value())[0], img.get_center(), size))
            head = T(("water, 20 °C" if key == "water" else "oil, 50 °C"), 30, col).next_to(frame, UP, buff=0.25)
            read = always_redraw(lambda: VGroup(
                T(f"corner {hist(med, 'Tcorner', tt.get_value()):4.0f} °C", 22, FG),
                T(f"core {hist(med, 'Tcore', tt.get_value()):4.0f} °C", 22, FG)).arrange(RIGHT, buff=0.5).next_to(frame, DOWN, buff=0.25))
            return img, frame, head, read, cont

        wimg, wfr, whead, wread, wcont = panel("water", WATER, -3.2)
        oimg, ofr, ohead, oread, ocont = panel("oil", OIL, 3.2)
        clock = always_redraw(lambda: T(f"t = {tt.get_value():5.1f} s", 30, YEL).to_edge(UP, buff=0.35))
        key = VGroup(Square(0.25, stroke_width=0, fill_color=MART, fill_opacity=1), T("martensite", 20, FG),
                     Rectangle(width=1.6, height=0.22, stroke_width=0).set_fill(color=["#fdf3a8", "#dc5139", "#2a0f4f"], opacity=1),
                     T("20 → 1210 °C", 20, FG),
                     DashedLine(LEFT * 0.3, RIGHT * 0.3, stroke_color=WHITE, stroke_width=2), M("M<sub>s</sub> line", 20, FG)
                     ).arrange(RIGHT, buff=0.18).to_edge(DOWN, buff=0.3)
        self.play(FadeIn(wimg), FadeIn(oimg), Create(wfr), Create(ofr), FadeIn(whead), FadeIn(ohead), run_time=1.4)
        self.add(wread, oread, clock, wcont, ocont)
        self.play(FadeIn(key), run_time=0.6)
        sw = MEDIA["water"]["summary"]
        so = MEDIA["oil"]["summary"]

        def clock_to(t1, rt):
            t0 = tt.get_value()
            self.play(tt.animate.set_value(t1), run_time=rt,
                      rate_func=lambda a: (np.exp(a * np.log(max(t1, 0.1) / max(t0, 0.1))) - 1) / (max(t1, 0.1) / max(t0, 0.1) - 1)
                      if t1 > t0 and t0 > 0 else a)

        self.at(1)
        clock_to(0.5, 0.8)
        clock_to(sw["time_to_Ms_s"]["corner"], self.avail(1, offset=4.5, cap=5, floor=2.5))
        ring = VGroup(*[Circle(radius=0.28, stroke_color=MART, stroke_width=4).move_to(wfr.get_corner(c)) for c in (UL, UR, DOWN + LEFT, DOWN + RIGHT)])
        self.play(Create(ring), run_time=0.6)
        hotcore = T(f"core ≈ {MS + sw['core_minus_corner_at_corner_Ms_C']:.0f} °C", 24, YEL).next_to(wimg, RIGHT, buff=0.15).shift(UP * 0.0)
        self.play(FadeIn(hotcore), run_time=0.5)
        self.at(2)
        self.play(FadeOut(ring), FadeOut(hotcore), run_time=0.4)
        clock_to(sw["time_to_Ms_s"]["face"] + 1.0, self.avail(3, cap=4, floor=2.0) - 0.4)
        self.at(3)
        clock_to(so["time_to_Ms_s"]["corner"] - 6, 4.0)
        clock_to(so["time_to_Ms_s"]["core"] + 2, self.avail(None, offset=-3.0, cap=9, floor=3.0))
        oo = T(f"Δt ≈ {so['time_to_Ms_s']['core'] - so['time_to_Ms_s']['corner']:.0f} s,  ΔT ≈ {so['core_minus_corner_at_corner_Ms_C']:.0f} °C",
               24, OIL).next_to(ofr, RIGHT, buff=0.1).rotate(0)
        oo.next_to(oread, DOWN, buff=0.15)
        self.play(FadeIn(oo), run_time=0.6)
        self.end()
        for m in (wimg, oimg):
            m.clear_updaters()
        self.clear()

    # ---- 9
    def stress(self):
        self.seg("stress")
        a = Square(1.6, stroke_width=0, fill_color="#d47a3a", fill_opacity=0.9).shift(LEFT * 2.2)
        b = Square(1.6 * 1.1, stroke_width=0, fill_color=MART, fill_opacity=0.9).shift(RIGHT * 2.2)
        la = T("austenite", 26, "#f0a070").next_to(a, DOWN, buff=0.3)
        lb = T("martensite: +1 % (drawn ×10)", 26, MART).next_to(b, DOWN, buff=0.3)
        arr = Arrow(a.get_right(), b.get_left(), buff=0.3, stroke_color=DIM)
        self.play(FadeIn(a), FadeIn(la), run_time=0.8)
        self.play(Create(arr), Transform(a.copy(), b), FadeIn(lb), run_time=1.5)
        self.add(b)
        self.at(1)
        self.clear(0.5)
        shell = Square(3.2, stroke_width=0, fill_color=MART, fill_opacity=1)
        core = Square(1.9, stroke_width=0, fill_color="#e8823a", fill_opacity=1)
        ls = T("martensite shell, brittle", 24, MART).next_to(shell, UP, buff=0.3)
        lc = T("core, still austenite", 22, BLACK).move_to(core)
        self.play(FadeIn(shell), FadeIn(core), FadeIn(ls), FadeIn(lc), run_time=1.0)
        self.at(1, 2.4)
        self.play(core.animate.set_fill(MART).scale(1.12), FadeOut(lc), run_time=1.6)
        tens = VGroup(*[Arrow(shell.get_center() + d * 1.3, shell.get_center() + d * 2.25, buff=0, stroke_color=HOT, stroke_width=6)
                        for d in (UP, DOWN, LEFT, RIGHT)])
        tl = T("tension", 26, HOT).next_to(shell, RIGHT, buff=0.9)
        self.play(FadeIn(tens), FadeIn(tl), run_time=0.8)
        self.at(2)
        self.clear(0.5)
        ax = Axes(x_range=[-1, 2.6, 1], y_range=[0, 200, 50], x_length=10, y_length=4.6, tips=False,
                  axis_config={"stroke_color": DIM, "include_ticks": False}, y_axis_config={"include_ticks": True, "tick_size": 0.05}).shift(DOWN * 0.4)
        xl = VGroup(*[T(lab, 20, DIM).next_to(ax.c2p(e, 0), DOWN, buff=0.15) for e, lab in ((-1, "0.1"), (0, "1"), (1, "10"), (2, "100"))])
        yl = VGroup(*[T(str(v), 20, DIM).next_to(ax.c2p(-1, v), LEFT, buff=0.15) for v in (0, 50, 100, 150, 200)])
        xc = T("time in the bath (s, log scale)", 22, DIM).next_to(ax.x_axis, DOWN, buff=0.6)
        yc = T("tension in fresh martensite (MPa)", 22, DIM).next_to(ax.y_axis, UP, buff=0.15).shift(RIGHT * 1.6)

        def series(med, col):
            h = med["h"]
            t = np.maximum(h["t"], 0.1)
            v = VMobject(stroke_color=col, stroke_width=5)
            v.set_points_as_corners([ax.c2p(np.log10(a), b) for a, b in zip(t, h["sigBrittle"]) if a >= 0.1])
            return v

        sw, so = series(MEDIA["water"], WATER), series(MEDIA["oil"], OIL)
        self.play(Create(ax), FadeIn(xl), FadeIn(yl), FadeIn(xc), FadeIn(yc), run_time=1.0)
        self.play(Create(sw), Create(so), run_time=2.4, rate_func=linear)
        pw = MEDIA["water"]["summary"]["max_tensile_stress_in_martensite_MPa"]
        po = MEDIA["oil"]["summary"]["max_tensile_stress_in_martensite_MPa"]
        tw_ = MEDIA["water"]["summary"]["time_of_max_tensile_stress_s"]
        lw = T(f"water ≈ {pw:.0f} MPa", 26, WATER).next_to(ax.c2p(np.log10(tw_), pw), LEFT, buff=0.2)
        lo = T(f"oil ≈ {po:.0f} MPa", 26, OIL).next_to(ax.c2p(2.2, po), UP, buff=0.2)
        self.play(FadeIn(lw), run_time=0.6)
        self.at(2, 4.2)
        self.play(FadeIn(lo), run_time=0.6)
        self.end()
        self.clear()

    # ---- 10
    def crack(self):
        self.seg("crack")
        thr = {t["label"]: t["MPa"] for t in SIM["steel"]["crackThresholds"]}
        lo, hi = 5, 3000
        ax_h = 5.2
        Y = lambda v: -2.7 + (np.log10(v) - np.log10(lo)) / (np.log10(hi) - np.log10(lo)) * ax_h
        axis = Line([-4.5, Y(lo), 0], [-4.5, Y(hi), 0], stroke_color=DIM)
        ticks = VGroup()
        for v in (10, 100, 1000):
            ticks.add(Line([-4.6, Y(v), 0], [-4.4, Y(v), 0], stroke_color=DIM), T(str(v), 20, DIM).next_to([-4.6, Y(v), 0], LEFT, buff=0.1))
        cap = T("MPa (log scale)", 20, DIM).next_to(axis, UP, buff=0.15)

        def mark(v, text, col, dashed=True):
            ln = (DashedLine if dashed else Line)([-4.5, Y(v), 0], [3.0, Y(v), 0], stroke_color=col, stroke_width=2)
            return VGroup(ln, T(f"{text}  {v:.0f}", 22, col).next_to([3.0, Y(v), 0], RIGHT, buff=0.15))

        def bar_(v, col, x, name):
            r = Rectangle(width=0.9, height=Y(v) - Y(lo), stroke_width=0, fill_color=col, fill_opacity=0.9)
            r.move_to([x, (Y(v) + Y(lo)) / 2, 0])
            return VGroup(r, T(name, 24, col).next_to(r, DOWN, buff=0.15))

        pw = MEDIA["water"]["summary"]["max_tensile_stress_in_martensite_MPa"]
        po = MEDIA["oil"]["summary"]["max_tensile_stress_in_martensite_MPa"]
        bw, bo = bar_(pw, WATER, -2.0, "water"), bar_(po, OIL, 0.2, "oil")
        m_smooth = mark(thr["smooth face, fine flaw"], "smooth face", "#83C167")
        m_notch = mark(thr["sharp notch + carbide cluster"], "sharp notch + carbide cluster", HOT)
        self.play(Create(axis), FadeIn(ticks), FadeIn(cap), run_time=0.8)
        self.play(GrowFromEdge(bw[0], DOWN), FadeIn(bw[1]), GrowFromEdge(bo[0], DOWN), FadeIn(bo[1]), run_time=1.4)
        self.play(Create(m_smooth[0]), FadeIn(m_smooth[1]), run_time=1.0)
        self.at(1)
        self.play(Create(m_notch[0]), FadeIn(m_notch[1]), run_time=1.2)
        self.at(2)
        self.play(Indicate(bw[0], color=HOT, scale_factor=1.05), run_time=1.2)
        self.at(2, 1.8)
        below = T(f"{thr['sharp notch + carbide cluster'] / po:.0f}× below", 24, OIL).next_to(bo[0], RIGHT, buff=0.2)
        self.play(FadeIn(below), run_time=0.6)
        self.at(2, 4.6)
        feats = T("flutes · holes · sharp edges", 28, YEL).to_edge(UP, buff=0.4)
        self.play(Write(feats), run_time=1.4)
        self.end()
        self.clear()

    # ---- 11
    def outro(self):
        self.seg("outro")
        sw = MEDIA["water"]["summary"]
        so = MEDIA["oil"]["summary"]
        rows = [("after the quench", "water", "oil"),
                ("martensite at the end", f"{sw['martensite_fraction_end']['core'] * 100:.0f} %", f"{so['martensite_fraction_end']['core'] * 100:.0f} %"),
                ("hardness", "≈ 64 HRC", "≈ 64 HRC"),
                ("tension in fresh martensite", f"{sw['max_tensile_stress_in_martensite_MPa']:.0f} MPa", f"{so['max_tensile_stress_in_martensite_MPa']:.0f} MPa"),
                ("plastic strain (distortion)", f"{sw['mean_plastic_strain_pct']:.2f} %", f"{so['mean_plastic_strain_pct']:.2f} %")]
        table = VGroup()
        for i, (a, b, c) in enumerate(rows):
            col_a = T(a, 26, DIM)
            col_b = T(b, 28, WATER if i == 0 else FG)
            col_c = T(c, 28, OIL if i == 0 else FG)
            table.add(VGroup(col_a, col_b, col_c))
        for i, r in enumerate(table):
            y = 1.8 - i * 0.75
            r[0].move_to(np.array([-1.2, y, 0])).align_to(np.array([-0.6, 0, 0]), RIGHT)
            r[1].move_to([1.2, y, 0])
            r[2].move_to([3.6, y, 0])
        self.play(FadeIn(table[0]), run_time=0.5)
        for r in table[1:]:
            self.play(FadeIn(r, shift=UP * 0.1), run_time=0.7)
        hl = VGroup(*[r[1] for r in table[3:]])
        self.play(Indicate(hl, color=HOT, scale_factor=1.08), run_time=1.2)
        self.at(1)
        self.play(table.animate.scale(0.7).to_edge(UP, buff=0.4), run_time=0.8)
        final = VGroup(T("Harden high-speed steel in oil, salt or gas.", 38, FG),
                       T("Temper right away.", 38, FG),
                       T("Never in water.", 46, YEL)).arrange(DOWN, buff=0.35).shift(DOWN * 0.9)
        for line in final:
            self.play(FadeIn(line, shift=UP * 0.15), run_time=0.9)
        self.end(gap=1.0)
        src = T("simulation and code: github.com/adagora/HSS-heat-treatment", 22, DIM).to_edge(DOWN, buff=0.4)
        self.play(FadeIn(src), run_time=0.6)
        self.wait(2.5)
        self.clear(1.0)


def _lighter(hexcol, amt):
    c = _hex(hexcol)
    c = c + (255 - c) * amt if amt > 0 else c * (1 + amt)
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in np.clip(c, 0, 255))
