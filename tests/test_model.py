"""Checks of the quench model against closed-form results.

    python -m unittest discover -s tests
"""

import math
import unittest

import numpy as np

from sim.material import M2, M2Steel
from sim.model import QuenchModel
from sim.model2d import SquareBarQuench
from sim.quenchants import OIL, WATER


class Elastic(M2Steel):
    """M2 without plasticity and with a constant modulus, for closed-form comparisons."""

    def yield_strength(self, T, f):
        return np.full(np.shape(T), 1e9)

    def youngs_modulus(self, T):
        return np.full(np.shape(T), 200e3)


class MaterialTests(unittest.TestCase):
    def test_retained_austenite_at_room_temperature(self):
        self.assertAlmostEqual(1 - float(M2.martensite_equilibrium(20.0)), M2.retained_austenite_at_20C, places=6)

    def test_no_martensite_above_ms(self):
        self.assertEqual(float(M2.martensite_equilibrium(M2.Ms + 1)), 0.0)

    def test_martensite_expands(self):
        # at the same temperature martensite is larger than austenite
        self.assertGreater(float(M2.free_strain(100.0, 1.0)), float(M2.free_strain(100.0, 0.0)))

    def test_crack_thresholds_ordered(self):
        thr = [v for _, v in M2.crack_thresholds()]
        self.assertEqual(thr, sorted(thr, reverse=True))


class QuenchantTests(unittest.TestCase):
    def test_water_boils_through_ms_oil_does_not(self):
        self.assertEqual(WATER.stage(M2.Ms), "boiling")
        self.assertEqual(OIL.stage(M2.Ms), "convection")

    def test_water_is_far_more_severe_at_ms(self):
        self.assertGreater(WATER.h(M2.Ms) / OIL.h(M2.Ms), 20)


class RoundBarTests(unittest.TestCase):
    def test_thermoelastic_stress_matches_timoshenko(self):
        """Parabolic temperature in a long free cylinder (Timoshenko & Goodier)."""
        mat = Elastic(trip_coefficient=0.0)
        model = QuenchModel(WATER, material=mat, n_elements=75)
        R = model.R
        Tn = 600 - 500 * (model.r / R) ** 2
        Tg = model._to_gauss(Tn)
        f = np.zeros(model.ngp)
        sig, _, _, _ = model._mech_step(Tg, f, f, np.zeros((model.ngp, 3)))
        a, E, nu = mat.alpha_austenite, 200e3, mat.poisson

        def integral(r):  # int_0^r eps* r dr for eps* = a (T - 20)
            return a * (580 * r**2 / 2 - 500 * r**4 / (4 * R**2))

        r = model.rg
        estar = a * (Tg - 20)
        c = E / (1 - nu)
        st = c * (integral(R) / R**2 + integral(r) / r**2 - estar)
        sz = c * (2 * integral(R) / R**2 - estar)
        # element averages remove the linear-element oscillation between Gauss points
        avg = lambda v: 0.5 * (v[0::2] + v[1::2])
        self.assertLess(np.max(np.abs(avg(sig[:, 1]) - avg(st))), 0.01 * np.max(np.abs(st)))
        self.assertLess(np.max(np.abs(avg(sig[:, 2]) - avg(sz))), 0.01 * np.max(np.abs(sz)))

    def test_energy_balance_without_transformation(self):
        """Heat lost through the surface equals the drop in stored heat (above Ms)."""
        model = QuenchModel(OIL, n_elements=40)
        T = np.full(model.nn, 1210.0)
        f = np.zeros(model.nn)
        m = model.m
        e0 = np.sum(m.density * model.cap * (450 * T + 0.075 * T**2))  # int cp dT, cp = 450 + 0.15 T
        lost, dt = 0.0, 0.01
        for _ in range(300):
            Tn, f, h = model._thermal_step(T, f, dt)
            lost += h * model.R * (0.5 * (T[-1] + Tn[-1]) - OIL.bath_temperature) * dt
            T = Tn
        e1 = np.sum(m.density * model.cap * (450 * T + 0.075 * T**2))
        self.assertAlmostEqual((e0 - e1) / lost, 1.0, delta=0.03)


class SquareBarTests(unittest.TestCase):
    def test_uniform_temperature_gives_no_stress(self):
        model = SquareBarQuench(WATER, n=8)
        Tg = np.full((model.ne, 4), 400.0)
        fg = np.zeros((model.ne, 4))
        sig, _, _, _ = model._mech_step(Tg, fg, fg, np.zeros((model.ne, 4, 4)), np.zeros((model.ne, 4)))
        self.assertLess(np.max(np.abs(sig)), 1e-6)

    def test_water_loads_martensite_much_more_than_oil(self):
        water = SquareBarQuench(WATER, n=10).run()
        oil = SquareBarQuench(OIL, n=10).run()
        self.assertGreater(water.max_brittle_sig1.max(), 5 * oil.max_brittle_sig1.max())
        # corners reach Ms long before the core in water, almost together in oil
        def lag(res):
            t = res.t
            tc = t[np.argmax(res.T[:, 0, 0] <= M2.Ms)]
            tk = t[np.argmax(res.T[:, -1, -1] <= M2.Ms)]
            core_at_corner_ms = np.interp(tk, t, res.T[:, 0, 0])
            return tc - tk, core_at_corner_ms - M2.Ms
        _, dT_water = lag(water)
        _, dT_oil = lag(oil)
        self.assertGreater(dT_water, 300)
        self.assertLess(dT_oil, 60)


if __name__ == "__main__":
    unittest.main()
