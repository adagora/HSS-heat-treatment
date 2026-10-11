"""Properties of AISI M2 / HS 6-5-2 (1.3343) high-speed steel used by the quench model.

All values are representative handbook-level numbers for M2 hardened from
~1210 °C.  They are good enough to reproduce the *trends* that decide
whether a quench cracks a tool, not to predict an exact stress for a
particular heat of steel.  Every number is a plain attribute so it can be
changed in one place.

Units: temperature °C, stress MPa, length m, time s.
"""

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class M2Steel:
    # --- nominal composition (wt.%), for reference only -------------------
    composition = {"C": 0.88, "W": 6.2, "Mo": 5.0, "Cr": 4.1, "V": 1.9}

    # --- thermal -----------------------------------------------------------
    density: float = 8150.0  # kg/m^3

    # Martensite kinetics (Koistinen-Marburger, f = 1 - exp(-beta*(Ms - T))).
    # Ms of M2 is low (~200-230 °C) because the austenite is loaded with C, W,
    # Mo, Cr and V dissolved at the hardening temperature.  beta is chosen so
    # that ~25 % austenite is retained at 20 °C, the typical as-quenched value
    # for M2 (handbooks quote 20-40 % for high-speed steels).
    Ms: float = 215.0
    retained_austenite_at_20C: float = 0.25

    # Latent heat released by the austenite -> martensite transformation.
    latent_heat: float = 5.0e8  # J/m^3

    # --- mechanical --------------------------------------------------------
    poisson: float = 0.30
    alpha_austenite: float = 20.0e-6  # 1/K, austenite expands much more ...
    alpha_martensite: float = 12.0e-6  # 1/K, ... than martensite
    # Linear strain of martensite relative to austenite at 20 °C.  Martensite
    # is less dense (bct, supersaturated with carbon) so the transformation
    # *expands* the steel - the root cause of transformation stresses.
    transformation_strain_20C: float = 0.010

    # Greenwood-Johnson / Leblond transformation plasticity coefficient.
    trip_coefficient: float = 5.0e-5  # 1/MPa

    # --- fracture of as-quenched (untempered) M2 ----------------------------
    # Once the skin is mostly martensite it is brittle (austenite is ductile).
    brittle_fraction: float = 0.5
    # A quench crack starts from a surface flaw of depth a, possibly sitting at
    # the root of a notch with stress-concentration factor Kt:
    #     K_I = Kt * 1.12 * sigma * sqrt(pi * a)  >=  K_IC
    # (label, K_IC [MPa*sqrt(m)], flaw depth a [m], Kt)
    crack_scenarios = (
        ("smooth face, fine flaw", 15.0, 20e-6, 1.0),
        ("typical tool feature", 12.0, 50e-6, 2.0),
        ("sharp notch + carbide cluster", 10.0, 150e-6, 3.0),
    )

    # ------------------------------------------------------------------------
    @property
    def km_beta(self) -> float:
        """Koistinen-Marburger rate constant (1/K) calibrated to the retained austenite."""
        return math.log(1.0 / self.retained_austenite_at_20C) / (self.Ms - 20.0)

    def conductivity(self, T):
        """W/(m K).  ~21 at room temperature, ~27 in austenite at 1200 °C."""
        return 21.0 + 0.005 * np.asarray(T)

    def specific_heat(self, T):
        """J/(kg K)."""
        return 450.0 + 0.15 * np.asarray(T)

    def martensite_equilibrium(self, T):
        """Martensite fraction reached when cooled to T (athermal, KM law)."""
        T = np.asarray(T, dtype=float)
        under = np.clip(self.Ms - T, 0.0, None)
        return 1.0 - np.exp(-self.km_beta * under)

    def youngs_modulus(self, T):
        """MPa.  ~215 GPa at room temperature, ~125 GPa at 1200 °C."""
        return 215e3 - 75.0 * np.asarray(T)

    def free_strain(self, T, f):
        """Stress-free (thermal + transformation) linear strain, reference = austenite at 20 °C."""
        T = np.asarray(T)
        eps_a = self.alpha_austenite * (T - 20.0)
        eps_m = self.alpha_martensite * (T - 20.0) + self.transformation_strain_20C
        return (1.0 - f) * eps_a + f * eps_m

    def yield_strength(self, T, f):
        """MPa.  Hot austenite is soft; fresh high-carbon martensite is very strong."""
        T = np.asarray(T)
        sy_a = np.maximum(25.0, 350.0 - 0.27 * T)
        sy_m = np.maximum(300.0, 2000.0 - 1.0 * T)
        return (1.0 - f) * sy_a + f * sy_m

    def crack_thresholds(self):
        """[(label, nominal tensile stress in MPa that starts a crack), ...] - strictest last."""
        out = []
        for label, kic, a, kt in self.crack_scenarios:
            out.append((label, kic / (kt * 1.12 * math.sqrt(math.pi * a))))
        return out


M2 = M2Steel()
