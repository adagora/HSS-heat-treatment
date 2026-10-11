"""Run the water vs. oil quench of an M2 tool bit and export data + figures.

    python -m sim.run            # full resolution (a few minutes)
    python -m sim.run --quick    # coarse mesh for a fast check

Outputs
  web/quench_data.js      data for the animation (window.QUENCH_DATA = {...})
  results/summary.json    key numbers per quenchant
  figures/*.png           static figures used in docs/
"""

import argparse
import base64
import json
import math
import pickle
import time
from pathlib import Path

import numpy as np

from .cct import AC1, AC3, CCT_FIELDS
from .material import M2
from .model import QuenchModel
from .model2d import SquareBarQuench
from .quenchants import AIR, OIL, WATER

ROOT = Path(__file__).resolve().parent.parent
WIDTH = 0.016  # 16 mm square tool bit
T_AUST = 1210.0
CORE_STOP = 60.0  # "hand warm" - the bit goes into the tempering furnace


def b64(arr, dtype):
    return base64.b64encode(np.ascontiguousarray(arr, dtype=dtype).tobytes()).decode("ascii")


def time_to(t, T, level):
    idx = np.nonzero(T <= level)[0]
    if len(idx) == 0:
        return None
    i = idx[0]
    if i == 0:
        return float(t[0])
    return float(t[i - 1] + (level - T[i - 1]) * (t[i] - t[i - 1]) / (T[i] - T[i - 1]))


def at_time(t, y, when):
    return float(np.interp(when, t, y))


def summarize(res):
    t = res.t
    Tc, Tf, Tk = res.T[:, 0, 0], res.T[:, 0, -1], res.T[:, -1, -1]
    ms = M2.Ms
    t_ms = {k: time_to(t, v, ms) for k, v in (("corner", Tk), ("face", Tf), ("core", Tc))}
    # cooling rate of the face centre as it passes Ms
    i = int(np.searchsorted(-Tf, -ms))
    rate_ms = float((Tf[i - 1] - Tf[i + 1]) / (t[i + 1] - t[i - 1]))
    thresholds = M2.crack_thresholds()
    peak = float(res.max_brittle_sig1.max())
    return {
        "quenchant": res.quenchant.name,
        "time_to_Ms_s": t_ms,
        "core_minus_corner_at_corner_Ms_C": at_time(t, Tc, t_ms["corner"]) - ms,
        "core_minus_face_at_face_Ms_C": at_time(t, Tc, t_ms["face"]) - ms,
        "face_cooling_rate_at_Ms_C_per_s": rate_ms,
        "t8_5_core_s": time_to(t, Tc, 500) - time_to(t, Tc, 800),
        "quench_time_to_core_60C_s": float(t[-1]),
        "max_tensile_stress_in_martensite_MPa": peak,
        "time_of_max_tensile_stress_s": float(t[int(np.argmax(res.max_brittle_sig1))]),
        "max_tensile_stress_anywhere_MPa": float(res.sig1.max()),
        "max_plastic_strain_pct": float(res.peq[-1].max() * 100),
        "mean_plastic_strain_pct": float(res.peq[-1].mean() * 100),
        "martensite_fraction_end": {"corner": float(res.f[-1, -1, -1]), "core": float(res.f[-1, 0, 0])},
        "crack_scenarios": [
            {"label": lab, "threshold_MPa": thr, "exceeded": peak >= thr} for lab, thr in thresholds
        ],
    }


def frame_times(t_end, n=160, t0=0.02):
    return np.concatenate([[0.0], np.geomspace(t0, t_end, n)])


def history_indices(t, n=420, t0=0.01):
    want = np.concatenate([[0.0], np.geomspace(t0, t[-1], n)])
    return np.unique(np.clip(np.searchsorted(t, want), 0, len(t) - 1))


def export_medium(res, q):
    t = res.t
    fi = np.unique(np.clip(np.searchsorted(t, frame_times(t[-1])), 0, len(t) - 1))
    hi = history_indices(t)
    n = res.sig1.shape[1]
    return {
        "key": q.key,
        "name": q.name,
        "bath": q.bath_temperature,
        "stageVapourAbove": q.film_boiling_below,
        "stageBoilingAbove": q.boiling_ends_below,
        "hT": list(q.table_T),
        "hV": list(q.table_h),
        "frames": {
            "count": int(len(fi)),
            "t": [round(float(x), 5) for x in t[fi]],
            "T": b64(np.round(res.T[fi] * 50.0), "<u2"),  # °C * 50
            "f": b64(np.round(res.f[fi] * 255.0), "u1"),  # 0-255
            "s1": b64(np.round(np.clip(res.sig1[fi], -32000, 32000)), "<i2"),  # MPa
            "peq": b64(np.round(np.clip(res.peq[fi] * 1e4, 0, 65000)), "<u2"),  # strain * 1e4
            "hotspot": [[int(a), int(b)] for a, b in res.max_brittle_loc[fi]],
        },
        "history": {
            "t": [round(float(x), 5) for x in t[hi]],
            "Tcorner": [round(float(x), 2) for x in res.T[hi, -1, -1]],
            "Tface": [round(float(x), 2) for x in res.T[hi, 0, -1]],
            "Tcore": [round(float(x), 2) for x in res.T[hi, 0, 0]],
            "fcorner": [round(float(x), 4) for x in res.f[hi, -1, -1]],
            "fface": [round(float(x), 4) for x in res.f[hi, 0, -1]],
            "fcore": [round(float(x), 4) for x in res.f[hi, 0, 0]],
            "hface": [round(float(x), 1) for x in res.h_face[hi]],
            "hcorner": [round(float(x), 1) for x in res.h_corner[hi]],
            "sigBrittle": [round(float(x), 2) for x in res.max_brittle_sig1[hi]],
            "sigMax": [round(float(x), 2) for x in res.sig1[hi].reshape(len(hi), -1).max(axis=1)],
            "sigMin": [round(float(x), 2) for x in res.sig1[hi].reshape(len(hi), -1).min(axis=1)],
            "peqMean": [round(float(x) * 100, 4) for x in res.peq[hi].reshape(len(hi), -1).mean(axis=1)],
        },
        "grid": {"nodes": int(n + 1), "elements": int(n)},
        "summary": summarize(res),
    }


# ----------------------------------------------------------------- figures
def make_figures(results, fig_dir):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    fig_dir.mkdir(parents=True, exist_ok=True)
    colors = {"water": "#2b6cb0", "oil": "#c05621", "air": "#718096"}
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

    # 1. heat-transfer coefficient vs surface temperature
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    Ts = np.linspace(20, 1210, 600)
    ax.axvspan(20, M2.Ms, color="#805ad5", alpha=0.10, lw=0)
    ax.text(M2.Ms - 8, 15.5, "martensite\nforms here", ha="left", va="top", color="#553c9a", fontsize=9)
    for q in (WATER, OIL, AIR):
        ax.plot(Ts, q.h(Ts) / 1000, color=colors[q.key], lw=2, label=q.name)
    ax.axvline(M2.Ms, color="#553c9a", lw=1, ls="--")
    ax.set_xlabel("Surface temperature (°C)")
    ax.set_ylabel("Heat-transfer coefficient h (kW/m²K)")
    ax.set_xlim(1210, 20)
    ax.set_ylim(0, 16)
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("Quenchant severity along the quench (time runs left → right)")
    fig.tight_layout()
    fig.savefig(fig_dir / "htc_curves.png", dpi=150)
    plt.close(fig)

    # 2. cooling curves on schematic CCT
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    for key, fld in CCT_FIELDS.items():
        pts = [(math.log10(tt), T) for T, tt in fld["points"]]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        poly = Polygon(list(zip([math.log10(10_000)] + xs + [math.log10(10_000)], [ys[0]] + ys + [ys[-1]])),
                       closed=True, color="#a0aec0", alpha=0.25, lw=0)
        ax.add_patch(poly)
        ax.plot(xs, ys, color="#718096", lw=1, ls="--")
        ax.text(xs[int(np.argmin(xs))] + 0.05, ys[int(np.argmin(xs))], fld["label"], fontsize=8, color="#4a5568", va="center")
    ax.axhline(M2.Ms, color="#553c9a", lw=1.2)
    ax.text(3.95, M2.Ms - 45, f"Ms ≈ {M2.Ms:.0f} °C\nmartensite below", color="#553c9a", fontsize=9, ha="right")
    ax.axhline(AC1, color="#a0aec0", lw=0.8, ls=":")
    ax.text(-1.95, AC1 + 12, f"Ac1 ≈ {AC1:.0f} °C", color="#718096", fontsize=8)
    for key, res in results.items():
        t = np.maximum(res.t, 1e-2)
        ax.plot(np.log10(t), res.T[:, -1, -1], color=colors[key], lw=1.2, ls=":", label=f"{key} - corner")
        ax.plot(np.log10(t), res.T[:, 0, 0], color=colors[key], lw=2.2, label=f"{key} - core")
    ax.set_xlim(-2, 4)
    ax.set_ylim(0, 1250)
    ax.set_xticks(range(-2, 5))
    ax.set_xticklabels(["0.01", "0.1", "1", "10", "100", "1000", "10000"])
    ax.set_xlabel("Time from start of quench (s, log scale)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("16 mm M2 tool bit: cooling curves on a schematic CCT diagram")
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(fig_dir / "cooling_on_cct.png", dpi=150)
    plt.close(fig)

    # 3. stress in fresh martensite vs crack thresholds
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for key, res in results.items():
        t = np.maximum(res.t, 1e-2)
        ax.plot(t, np.maximum(res.max_brittle_sig1, 1), color=colors[key], lw=2, label=f"{key}")
    for lab, thr in M2.crack_thresholds():
        ax.axhline(thr, color="#c53030", lw=0.8, ls="--")
        ax.text(0.012, thr * 1.08, f"crack threshold: {lab} ({thr:.0f} MPa)", fontsize=8, color="#9b2c2c")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.01, 400)
    ax.set_ylim(1, 3000)
    ax.set_xlabel("Time from start of quench (s)")
    ax.set_ylabel("Largest tensile stress in fresh martensite (MPa)")
    ax.set_title("Crack driving stress: water vs oil")
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(fig_dir / "martensite_tension.png", dpi=150)
    plt.close(fig)

    # 4. snapshot maps
    def full(a, nodal):
        """Mirror the quarter (x, y >= 0) into the full section; nodal arrays share the centre lines."""
        left = a[:, :0:-1] if nodal else a[:, ::-1]
        half = np.concatenate([left, a], axis=1)
        lower = half[:0:-1] if nodal else half[::-1]
        return np.concatenate([lower, half], axis=0)

    half = res.half_width * 1000
    ext = (-half, half, -half, half)
    fig, axes = plt.subplots(2, 4, figsize=(12.5, 6.6), layout="constrained")
    for row, (key, res) in enumerate(results.items()):
        t_face = time_to(res.t, res.T[:, 0, -1], M2.Ms)
        t_peak = float(res.t[int(np.argmax(res.max_brittle_sig1))])
        for col, (lab, when) in enumerate([("face centres reach Ms", t_face), ("peak tension in martensite", t_peak)]):
            i = int(np.searchsorted(res.t, when))
            ax = axes[row, col * 2]
            im = ax.imshow(full(res.T[i], True), origin="lower", cmap="inferno", vmin=20, vmax=1210, extent=ext)
            ax.contour(np.linspace(-half, half, 2 * res.T.shape[1] - 1), np.linspace(-half, half, 2 * res.T.shape[1] - 1),
                       full(res.T[i], True), levels=[M2.Ms], colors="white", linestyles="--", linewidths=1)
            ax.set_title(f"{key}, t = {res.t[i]:.1f} s ({lab})\ntemperature, dashed = Ms", fontsize=9)
            ax.set_xticks([])
            ax.set_yticks([])
            ax = axes[row, col * 2 + 1]
            im2 = ax.imshow(full(res.sig1[i], False), origin="lower", cmap="RdBu_r", vmin=-500, vmax=500, extent=ext)
            ax.set_title(f"{key}, t = {res.t[i]:.1f} s\nmax principal stress", fontsize=9)
            ax.set_xticks([])
            ax.set_yticks([])
    fig.colorbar(im, ax=axes[:, 0], shrink=0.7, label="°C", location="left")
    fig.colorbar(im2, ax=axes[:, 3], shrink=0.7, label="MPa (red = tension)")
    fig.suptitle("16 mm M2 tool bit: when the face centres pass Ms, and at the peak tension in the martensite")
    fig.savefig(fig_dir / "snapshots.png", dpi=130)
    plt.close(fig)

    # 5. typical M2 tempering response (literature-typical values, not simulated)
    fig, ax = plt.subplots(figsize=(7.5, 4.0))
    tt = [20, 100, 200, 300, 400, 450, 500, 525, 550, 575, 600, 625, 650]
    hrc = [64.5, 64.0, 62.0, 61.0, 61.5, 62.5, 64.5, 65.5, 65.8, 65.0, 63.0, 60.5, 57.5]
    ax.plot(tt, hrc, color="#2f855a", lw=2, marker="o", ms=4)
    ax.axvspan(540, 570, color="#2f855a", alpha=0.12, lw=0)
    ax.text(555, 58, "usual\ntempering\nwindow", ha="center", fontsize=8, color="#22543d")
    ax.annotate("secondary hardening:\nfine W/Mo/V carbides precipitate", xy=(550, 65.8), xytext=(260, 65.3),
                fontsize=8, arrowprops={"arrowstyle": "->", "color": "#4a5568"})
    ax.set_xlabel("Tempering temperature (°C), 2 × 2 h")
    ax.set_ylabel("Hardness (HRC)")
    ax.set_title("M2 hardened from ~1210 °C: typical tempering curve")
    fig.tight_layout()
    fig.savefig(fig_dir / "tempering_curve.png", dpi=150)
    plt.close(fig)


def make_round_bar_figure(fig_dir):
    """Residual-stress profiles of a 25 mm round blank (1-D model) for comparison."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, q, col in zip(axes, (WATER, OIL), ("#2b6cb0", "#c05621")):
        res = QuenchModel(q, diameter=0.025, n_elements=60).run(core_stop=CORE_STOP)
        r = res.r / res.radius
        i_peak = int(np.argmax(res.max_brittle_sig1))
        for i, ls, lab in ((i_peak, "-", f"t={res.t[i_peak]:.0f}s (peak tension in martensite)"), (-1, "--", "end of quench")):
            ax.plot(r, res.sig[i, :, 1], color=col, ls=ls, lw=2, label=f"hoop, {lab}")
            ax.plot(r, res.sig[i, :, 2], color="#4a5568", ls=ls, lw=1.2, label=f"axial, {lab}")
        ax.axhline(0, color="#a0aec0", lw=0.8)
        ax.set_title(f"25 mm round blank - {q.key}")
        ax.set_xlabel("r / R  (0 = centre, 1 = surface)")
        ax.legend(frameon=False, fontsize=7)
    axes[0].set_ylabel("Stress (MPa)")
    fig.tight_layout()
    fig.savefig(fig_dir / "round_bar_profiles.png", dpi=150)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="coarse mesh (fast check)")
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--figures-only", action="store_true", help="redraw figures from the last run (results/.cache.pkl)")
    args = ap.parse_args(argv)
    n = 16 if args.quick else 32
    cache = ROOT / "results" / ".cache.pkl"

    if args.figures_only:
        with open(cache, "rb") as fh:
            results = pickle.load(fh)
        make_figures(results, ROOT / "figures")
        make_round_bar_figure(ROOT / "figures")
        print(f"wrote figures to {ROOT / 'figures'}")
        return

    results, exported = {}, {}
    for q in (WATER, OIL):
        t0 = time.time()
        res = SquareBarQuench(q, width=WIDTH, n=n, austenitizing_temperature=T_AUST).run(core_stop=CORE_STOP)
        results[q.key] = res
        exported[q.key] = export_medium(res, q)
        s = exported[q.key]["summary"]
        print(f"{q.key:5s}: {time.time() - t0:5.0f}s wall | Ms reached corner/face/core at "
              f"{s['time_to_Ms_s']['corner']:.1f}/{s['time_to_Ms_s']['face']:.1f}/{s['time_to_Ms_s']['core']:.1f} s | "
              f"max tension in martensite {s['max_tensile_stress_in_martensite_MPa']:.0f} MPa | "
              f"plastic strain mean {s['mean_plastic_strain_pct']:.2f} %")

    data = {
        "generated": time.strftime("%Y-%m-%d"),
        "bar": {"width_mm": WIDTH * 1000, "austenitizing_C": T_AUST, "coreStop_C": CORE_STOP, "quarterNodes": n + 1},
        "steel": {
            "grade": "AISI M2 / HS 6-5-2 / 1.3343",
            "Ms": M2.Ms,
            "beta": M2.km_beta,
            "retainedAustenite20C": M2.retained_austenite_at_20C,
            "brittleFraction": M2.brittle_fraction,
            "Ac1": AC1,
            "Ac3": AC3,
            "crackThresholds": [{"label": lab, "MPa": round(thr, 1)} for lab, thr in M2.crack_thresholds()],
        },
        "cct": {k: {"label": v["label"], "points": v["points"]} for k, v in CCT_FIELDS.items()},
        "media": exported,
    }
    web = ROOT / "web"
    web.mkdir(exist_ok=True)
    (web / "quench_data.js").write_text(
        "// Generated by `python -m sim.run` - do not edit by hand.\nwindow.QUENCH_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n"
    )
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "summary.json").write_text(json.dumps({k: v["summary"] for k, v in exported.items()}, indent=2) + "\n")
    print(f"wrote {web / 'quench_data.js'} ({(web / 'quench_data.js').stat().st_size / 1e6:.2f} MB) and {out / 'summary.json'}")
    with open(cache, "wb") as fh:
        pickle.dump(results, fh)

    if not args.no_figures:
        make_figures(results, ROOT / "figures")
        make_round_bar_figure(ROOT / "figures")
        print(f"wrote figures to {ROOT / 'figures'}")


if __name__ == "__main__":
    main()
