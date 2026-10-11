"""Coupled thermal / martensite / stress model of quenching a long round bar.

Geometry: an infinitely long solid cylinder (axisymmetric, generalized plane
strain), i.e. the middle of a round HSS tool blank far from its ends.

Physics per time step
---------------------
1. Heat conduction  rho*cp*dT/dt = 1/r d/dr(k r dT/dr)  with the quenchant's
   boundary condition  -k dT/dr = h(T_s) (T_s - T_bath)  (linear finite
   elements, lumped capacity, backward Euler).
2. Martensite: athermal Koistinen-Marburger law f = 1 - exp(-beta (Ms - T)),
   irreversible, with its latent heat fed back into the temperature.
3. Stresses: 1-D axisymmetric finite elements (radial displacement + uniform
   axial strain, zero axial force).  Eigenstrain = thermal + transformation
   (isotropic) + plastic + transformation plasticity (deviatoric).  Von Mises
   perfect plasticity with a yield strength that depends on temperature and
   martensite fraction; the local update (TRIP + radial return) is implicit.
4. Crack driving force: the largest tensile (max principal) stress in material
   that is already mostly martensite (brittle), to be compared with the
   flaw/notch scenarios of M2Steel.crack_thresholds().
"""

from dataclasses import dataclass, field
import math

import numpy as np

from .material import M2, M2Steel
from .quenchants import Quenchant

SQ3 = math.sqrt(3.0)


def _thomas(lower, diag, upper, rhs):
    """Solve a tridiagonal system (lower[0] and upper[-1] unused)."""
    n = len(diag)
    c = np.empty(n)
    d = np.empty(n)
    c[0] = upper[0] / diag[0]
    d[0] = rhs[0] / diag[0]
    for i in range(1, n):
        m = diag[i] - lower[i] * c[i - 1]
        c[i] = upper[i] / m if i < n - 1 else 0.0
        d[i] = (rhs[i] - lower[i] * d[i - 1]) / m
    x = np.empty(n)
    x[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        x[i] = d[i] - c[i] * x[i + 1]
    return x


@dataclass
class QuenchResult:
    quenchant: Quenchant
    radius: float
    r: np.ndarray  # node radii, m
    t: np.ndarray  # (nt,) s
    T: np.ndarray  # (nt, nn) °C
    f: np.ndarray  # (nt, nn) martensite fraction
    sig: np.ndarray  # (nt, nn, 3) sigma_r, sigma_theta, sigma_z  MPa (nodal)
    h: np.ndarray  # (nt,) surface heat-transfer coefficient
    surf_sig1: np.ndarray  # (nt,) max principal stress at the surface
    surf_f: np.ndarray  # (nt,) martensite fraction at the surface Gauss point
    max_brittle_sig1: np.ndarray  # (nt,) largest sigma1 where martensite >= brittle fraction
    meta: dict = field(default_factory=dict)

    # ---- convenience ------------------------------------------------------
    @property
    def T_surface(self):
        return self.T[:, -1]

    @property
    def T_core(self):
        return self.T[:, 0]

    def time_to(self, which, temperature):
        """First time the surface/core reaches `temperature` (linear interpolation)."""
        T = self.T_surface if which == "surface" else self.T_core
        idx = np.nonzero(T <= temperature)[0]
        if len(idx) == 0:
            return None
        i = idx[0]
        if i == 0:
            return float(self.t[0])
        t0, t1, T0, T1 = self.t[i - 1], self.t[i], T[i - 1], T[i]
        return float(t0 + (temperature - T0) * (t1 - t0) / (T1 - T0))


class QuenchModel:
    def __init__(
        self,
        quenchant: Quenchant,
        material: M2Steel = M2,
        diameter: float = 0.025,
        n_elements: int = 75,
        austenitizing_temperature: float = 1210.0,
    ):
        self.q = quenchant
        self.m = material
        self.R = diameter / 2.0
        self.T0 = austenitizing_temperature
        ne = n_elements
        self.ne = ne
        self.nn = ne + 1
        self.r = np.linspace(0.0, self.R, self.nn)
        dr = self.R / ne
        self.dr = dr
        ra, rb = self.r[:-1], self.r[1:]

        # lumped capacity weights  int(N_i r dr)
        cap = np.zeros(self.nn)
        np.add.at(cap, np.arange(ne), dr / 6.0 * (2 * ra + rb))
        np.add.at(cap, np.arange(1, ne + 1), dr / 6.0 * (ra + 2 * rb))
        self.cap = cap
        self.rmid = 0.5 * (ra + rb)

        # Gauss points (2 per element)
        off = dr / (2.0 * SQ3)
        rg = np.empty(2 * ne)
        rg[0::2] = self.rmid - off
        rg[1::2] = self.rmid + off
        self.rg = rg
        self.gp_el = np.repeat(np.arange(ne), 2)
        self.Na = (rb[self.gp_el] - rg) / dr
        self.Nb = (rg - ra[self.gp_el]) / dr
        self.wg = rg * dr / 2.0  # Gauss weight (=1) * jacobian * r
        self.ngp = 2 * ne

        # B matrices (ngp, 3 strains, 3 local dofs [u_a, u_b, eps_z])
        B = np.zeros((self.ngp, 3, 3))
        B[:, 0, 0] = -1.0 / dr
        B[:, 0, 1] = 1.0 / dr
        B[:, 1, 0] = self.Na / rg
        B[:, 1, 1] = self.Nb / rg
        B[:, 2, 2] = 1.0
        self.B = B
        zdof = self.nn  # index of the uniform axial strain dof
        self.ndof = self.nn + 1
        self.gdofs = np.stack([self.gp_el, self.gp_el + 1, np.full(self.ngp, zdof)], axis=1)

    # ------------------------------------------------------------------ heat
    def _thermal_step(self, T, f, dt):
        m, q = self.m, self.q
        T_new = T.copy()
        for _ in range(2):  # Picard on T-dependent properties and h(Ts)
            Tev = 0.5 * (T + T_new)
            k_el = m.conductivity(0.5 * (Tev[:-1] + Tev[1:]))
            kk = k_el * self.rmid / self.dr
            C = m.density * m.specific_heat(Tev) * self.cap / dt
            diag = C.copy()
            diag[:-1] += kk
            diag[1:] += kk
            lower = np.zeros(self.nn)
            upper = np.zeros(self.nn)
            lower[1:] = -kk
            upper[:-1] = -kk
            h = float(q.h(Tev[-1]))
            diag[-1] += h * self.R
            rhs = C * T
            rhs[-1] += h * self.R * q.bath_temperature
            T_new = _thomas(lower, diag, upper, rhs)

        # latent heat of the martensite transformation (energy conserving)
        cfac = m.latent_heat / (m.density * m.specific_heat(T_new))
        beta = m.km_beta
        Tt = T_new.copy()
        Tc = T_new.copy()
        for _ in range(30):
            F = m.martensite_equilibrium(Tc)
            dfa = F - f
            active = (dfa > 0) & (Tc < m.Ms)
            g = Tc - Tt - cfac * np.where(active, dfa, 0.0)
            dg = 1.0 + np.where(active, cfac * beta * (1.0 - F), 0.0)
            step = g / dg
            Tc -= step
            if np.max(np.abs(step)) < 1e-6:
                break
        f_new = np.maximum(f, m.martensite_equilibrium(Tc))
        return Tc, f_new, h

    # -------------------------------------------------------------- stresses
    def _elastic_constants(self, Tg):
        E = self.m.youngs_modulus(Tg)
        nu = self.m.poisson
        lam = E * nu / ((1 + nu) * (1 - 2 * nu))
        mu = E / (2 * (1 + nu))
        kappa = E / (3 * (1 - 2 * nu))
        D = np.zeros((self.ngp, 3, 3))
        D[:] = lam[:, None, None]
        idx = np.arange(3)
        D[:, idx, idx] += 2 * mu[:, None]
        return D, mu, kappa

    def _assemble(self, D):
        ke = np.einsum("gji,gjk,gkl->gil", self.B, D, self.B) * self.wg[:, None, None]
        K = np.zeros((self.ndof, self.ndof))
        rows = np.repeat(self.gdofs, 3, axis=1)
        cols = np.tile(self.gdofs, (1, 3))
        np.add.at(K, (rows.ravel(), cols.ravel()), ke.reshape(self.ngp, 9).ravel())
        return K[1:, 1:]  # u(0) = 0

    def _load(self, D, eps_star):
        fe = np.einsum("gji,gjk,gk->gi", self.B, D, eps_star) * self.wg[:, None]
        F = np.zeros(self.ndof)
        np.add.at(F, self.gdofs.ravel(), fe.ravel())
        return F[1:]

    def _strains(self, U):
        u = np.concatenate([[0.0], U])
        ua = u[self.gp_el]
        ub = u[self.gp_el + 1]
        eps = np.empty((self.ngp, 3))
        eps[:, 0] = (ub - ua) / self.dr
        eps[:, 1] = (self.Na * ua + self.Nb * ub) / self.rg
        eps[:, 2] = u[self.nn]
        return eps

    def _mech_step(self, Tg, fg_old, fg_new, eps_in_old):
        m = self.m
        D, mu, kappa = self._elastic_constants(Tg)
        K = self._assemble(D)
        eps_f = m.free_strain(Tg, fg_new)
        phi = lambda x: x * (2.0 - x)  # Leblond/Desalos TRIP saturation function
        dphi = np.clip(phi(fg_new) - phi(fg_old), 0.0, None)
        a = 1.0 + 3.0 * mu * m.trip_coefficient * dphi
        sy = m.yield_strength(Tg, fg_new)

        eps_in = eps_in_old.copy()
        for it in range(200):
            eps_star = eps_f[:, None] + eps_in
            U = np.linalg.solve(K, self._load(D, eps_star))
            eps = self._strains(U)
            e_tr = eps - eps_f[:, None] - eps_in_old
            vol = e_tr.sum(axis=1)
            s_tr = 2 * mu[:, None] * (e_tr - vol[:, None] / 3.0)
            s1 = s_tr / a[:, None]
            q1 = np.sqrt(1.5 * np.sum(s1 * s1, axis=1))
            over = q1 > sy
            safe_q = np.where(q1 > 0, q1, 1.0)
            s = np.where(over[:, None], s1 * (sy / safe_q)[:, None], s1)
            d_trip = 1.5 * m.trip_coefficient * dphi[:, None] * s1
            dgam = np.where(over, (q1 - sy) / (3 * mu), 0.0)
            d_p = 1.5 * dgam[:, None] * s1 / safe_q[:, None]
            eps_in_new = eps_in_old + d_trip + d_p
            change = np.max(np.abs(eps_in_new - eps_in))
            eps_in = eps_in_new
            if change < 1e-8:
                break
        sigma = s + (kappa * vol)[:, None]
        return sigma, eps_in, it + 1, U

    # ------------------------------------------------------------------ run
    def run(self, t_end=None, core_stop=60.0, target_dT=2.0, dt_max=1.0, verbose=False):
        m, q = self.m, self.q
        T = np.full(self.nn, self.T0)
        f = np.zeros(self.nn)
        fg = np.zeros(self.ngp)
        eps_in = np.zeros((self.ngp, 3))
        sig_g = np.zeros((self.ngp, 3))
        t, dt = 0.0, 1e-3
        out_t, out_T, out_f, out_s, out_h = [0.0], [T.copy()], [f.copy()], [self._nodal(sig_g)], [float(q.h(T[-1]))]
        out_s1, out_fs, out_mb = [0.0], [0.0], [0.0]
        iters_total, nsteps = 0, 0

        while True:
            T_new, f_new, h = self._thermal_step(T, f, dt)
            dTmax = np.max(np.abs(T_new - T))
            if dTmax > 2.5 * target_dT and dt > 2e-4:
                dt *= 0.5
                continue
            Tg = self._to_gauss(T_new)
            fg_new = np.maximum(fg, m.martensite_equilibrium(Tg))
            if np.max(fg_new - fg) > 0.02 and dt > 2e-4:
                dt *= 0.5
                continue
            sig_g, eps_in, nit, _ = self._mech_step(Tg, fg, fg_new, eps_in)
            iters_total += nit
            nsteps += 1
            T, f, fg = T_new, f_new, fg_new
            t += dt

            s1 = float(np.max(sig_g[-1]))  # surface (outermost Gauss point, sigma_r ~ 0)
            s1_all = np.max(sig_g, axis=1)
            brittle = fg >= m.brittle_fraction
            mb = float(max(np.max(s1_all[brittle]), 0.0)) if brittle.any() else 0.0

            out_t.append(t)
            out_T.append(T.copy())
            out_f.append(f.copy())
            out_s.append(self._nodal(sig_g))
            out_h.append(h)
            out_s1.append(s1)
            out_fs.append(float(fg[-1]))
            out_mb.append(mb)

            if verbose and nsteps % 200 == 0:
                print(f"  t={t:8.3f}s dt={dt:.4f} Ts={T[-1]:7.1f} Tc={T[0]:7.1f} "
                      f"f_s={fg[-1]:.2f} f_c={f[0]:.2f} s1={s1:7.1f} it={nit}")

            if T[0] <= core_stop or (t_end is not None and t >= t_end):
                break
            # adapt step to keep the temperature change per step near target_dT
            grow = target_dT / max(dTmax, 1e-9)
            dt = float(np.clip(dt * min(1.5, max(0.5, grow)), 2e-4, dt_max))

        res = QuenchResult(
            quenchant=q,
            radius=self.R,
            r=self.r.copy(),
            t=np.array(out_t),
            T=np.array(out_T),
            f=np.array(out_f),
            sig=np.array(out_s),
            h=np.array(out_h),
            surf_sig1=np.array(out_s1),
            surf_f=np.array(out_fs),
            max_brittle_sig1=np.array(out_mb),
            meta={"steps": nsteps, "mean_iterations": iters_total / max(nsteps, 1)},
        )
        return res

    # ---------------------------------------------------------------- helpers
    def _to_gauss(self, nodal):
        return self.Na * nodal[self.gp_el] + self.Nb * nodal[self.gp_el + 1]

    def _nodal(self, sig_g):
        """Element-average stresses interpolated to the nodes (ends extrapolated)."""
        el = 0.5 * (sig_g[0::2] + sig_g[1::2])
        nod = np.empty((self.nn, 3))
        nod[1:-1] = 0.5 * (el[:-1] + el[1:])
        nod[0] = el[0]
        nod[-1] = sig_g[-1]  # outermost Gauss point ~ surface
        nod[-1, 0] = 0.0  # traction-free surface
        return nod
