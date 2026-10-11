"""2-D quench model of a square HSS tool bit (cross-section far from the ends).

Same physics as :mod:`sim.model` (heat conduction with the quenchant's
h(T_surface), Koistinen-Marburger martensite with latent heat, thermo-
elastic-plastic stresses with transformation plasticity) but on the square
cross-section of a lathe tool bit, so that the corners - which are cooled
from two faces at once - are resolved.

Discretisation: one quarter of the section (two symmetry planes), a
structured grid of bilinear quadrilaterals (2x2 Gauss points), generalized
plane strain (uniform axial strain with zero axial force = long bar with
free ends).
"""

from dataclasses import dataclass, field
import math

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from .material import M2, M2Steel
from .quenchants import Quenchant

G = 1.0 / math.sqrt(3.0)
GAUSS = np.array([[-G, -G], [G, -G], [G, G], [-G, G]])


@dataclass
class Quench2DResult:
    quenchant: Quenchant
    half_width: float
    x: np.ndarray  # node coordinates (1-D grid), m
    t: np.ndarray
    T: np.ndarray  # (nt, ny, nx) nodal temperature
    f: np.ndarray  # (nt, ny, nx) nodal martensite fraction
    sig1: np.ndarray  # (nt, ey, ex) element max principal stress, MPa
    sigvm: np.ndarray  # (nt, ey, ex) element von Mises stress, MPa
    fel: np.ndarray  # (nt, ey, ex) element martensite fraction
    h_face: np.ndarray  # (nt,) h at the middle of the face
    h_corner: np.ndarray  # (nt,) h at the corner
    peq: np.ndarray  # (nt, ey, ex) accumulated equivalent plastic strain (distortion proxy)
    max_brittle_sig1: np.ndarray  # (nt,) largest sigma1 where martensite >= brittle fraction
    max_brittle_loc: np.ndarray  # (nt, 2) element (iy, ix) of that maximum
    meta: dict = field(default_factory=dict)


class SquareBarQuench:
    def __init__(
        self,
        quenchant: Quenchant,
        material: M2Steel = M2,
        width: float = 0.016,
        n: int = 32,
        austenitizing_temperature: float = 1210.0,
    ):
        self.q = quenchant
        self.m = material
        self.L = width / 2.0  # quarter model: 0 <= x, y <= L
        self.n = n
        self.T0 = austenitizing_temperature
        nx = n + 1
        self.nx = nx
        self.nn = nx * nx
        self.ne = n * n
        self.d = self.L / n
        self.x = np.linspace(0.0, self.L, nx)

        # connectivity (counter-clockwise), node id = iy * nx + ix
        iy, ix = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        n0 = (iy * nx + ix).ravel()
        self.conn = np.stack([n0, n0 + 1, n0 + 1 + nx, n0 + nx], axis=1)

        # reference shape-function data for a square element of side d
        d = self.d
        xi, eta = GAUSS[:, 0], GAUSS[:, 1]
        self.Ngp = 0.25 * np.stack(
            [(1 - xi) * (1 - eta), (1 + xi) * (1 - eta), (1 + xi) * (1 + eta), (1 - xi) * (1 + eta)], axis=1
        )  # (4 gp, 4 nodes)
        dN_dxi = 0.25 * np.stack([-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)], axis=1)
        dN_deta = 0.25 * np.stack([-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)], axis=1)
        dNdx = dN_dxi * (2.0 / d)
        dNdy = dN_deta * (2.0 / d)
        self.wdet = (d / 2.0) ** 2  # Gauss weight 1 * det J

        # thermal reference matrices (per unit conductivity / capacity)
        self.Kt_ref = np.einsum("gi,gj->ij", dNdx, dNdx) * self.wdet + np.einsum("gi,gj->ij", dNdy, dNdy) * self.wdet
        self.cap_node = np.zeros(self.nn)
        np.add.at(self.cap_node, self.conn.ravel(), d * d / 4.0)

        # exposed boundary: x = L and y = L edges (lumped, length per node)
        self.bnd_len = np.zeros(self.nn)
        right = np.arange(nx) * nx + n
        top = n * nx + np.arange(nx)
        for edge in (right, top):
            self.bnd_len[edge[:-1]] += d / 2.0
            self.bnd_len[edge[1:]] += d / 2.0
        self.bnodes = np.nonzero(self.bnd_len)[0]
        self.face_node = right[0]  # middle of a face (on the symmetry plane y = 0)
        self.corner_node = right[-1]

        # mechanical B matrix (strain [exx, eyy, ezz, gxy]) for the 8 element dofs + eps_z
        B = np.zeros((4, 4, 9))
        for g in range(4):
            B[g, 0, 0:8:2] = dNdx[g]
            B[g, 1, 1:8:2] = dNdy[g]
            B[g, 2, 8] = 1.0
            B[g, 3, 0:8:2] = dNdy[g]
            B[g, 3, 1:8:2] = dNdx[g]
        self.B = B
        self.ndof = 2 * self.nn + 1
        edofs = np.empty((self.ne, 9), dtype=int)
        edofs[:, 0:8:2] = 2 * self.conn
        edofs[:, 1:8:2] = 2 * self.conn + 1
        edofs[:, 8] = 2 * self.nn
        self.edofs = edofs
        # symmetry: u_x = 0 on x = 0, u_y = 0 on y = 0
        fixed = np.concatenate([2 * (np.arange(nx) * nx), 2 * np.arange(nx) + 1])
        free = np.ones(self.ndof, dtype=bool)
        free[fixed] = False
        self.free = np.nonzero(free)[0]
        self.ngp = 4 * self.ne

    # ------------------------------------------------------------------ heat
    def _thermal_step(self, T, f, dt):
        m, q = self.m, self.q
        T_new = T.copy()
        rows = np.repeat(self.conn, 4, axis=1).ravel()
        cols = np.tile(self.conn, (1, 4)).ravel()
        for _ in range(2):
            Tev = 0.5 * (T + T_new)
            k_el = m.conductivity(Tev[self.conn].mean(axis=1))
            vals = (k_el[:, None, None] * self.Kt_ref[None]).ravel()
            K = sp.csr_matrix((vals, (rows, cols)), shape=(self.nn, self.nn))
            C = m.density * m.specific_heat(Tev) * self.cap_node / dt
            h = q.h(Tev)
            hb = h * self.bnd_len
            A = K + sp.diags(C + hb)
            rhs = C * T + hb * q.bath_temperature
            T_new = spla.spsolve(A.tocsc(), rhs)

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
    def _to_gauss(self, nodal):
        return np.einsum("gi,ei->eg", self.Ngp, nodal[self.conn])  # (ne, 4)

    def _D(self, Tg):
        E = self.m.youngs_modulus(Tg)
        nu = self.m.poisson
        lam = E * nu / ((1 + nu) * (1 - 2 * nu))
        mu = E / (2 * (1 + nu))
        D = np.zeros(Tg.shape + (4, 4))
        D[..., :3, :3] = lam[..., None, None]
        for i in range(3):
            D[..., i, i] += 2 * mu
        D[..., 3, 3] = mu
        return D, mu, E / (3 * (1 - 2 * nu))

    def _mech_step(self, Tg, fg_old, fg_new, ein_old, peq_old):
        m = self.m
        D, mu, kappa = self._D(Tg)  # (ne, 4, 4, 4)
        ke = np.einsum("gai,egab,gbj->eij", self.B, D, self.B) * self.wdet
        rows = np.repeat(self.edofs, 9, axis=1).ravel()
        cols = np.tile(self.edofs, (1, 9)).ravel()
        K = sp.csr_matrix((ke.ravel(), (rows, cols)), shape=(self.ndof, self.ndof))
        Kf = K[self.free][:, self.free].tocsc()
        lu = spla.splu(Kf)

        eps_f = m.free_strain(Tg, fg_new)  # (ne, 4)
        iso = np.array([1.0, 1.0, 1.0, 0.0])
        phi = lambda x: x * (2.0 - x)
        dphi = np.clip(phi(fg_new) - phi(fg_old), 0.0, None)
        a = 1.0 + 3.0 * mu * m.trip_coefficient * dphi
        sy = m.yield_strength(Tg, fg_new)
        eng = np.array([1.0, 1.0, 1.0, 2.0])  # tensor -> engineering strain

        ein = ein_old.copy()
        for it in range(300):
            estar = eps_f[..., None] * iso + ein
            fe = np.einsum("gai,egab,egb->ei", self.B, D, estar) * self.wdet
            F = np.zeros(self.ndof)
            np.add.at(F, self.edofs.ravel(), fe.ravel())
            U = np.zeros(self.ndof)
            U[self.free] = lu.solve(F[self.free])
            eps = np.einsum("gai,ei->ega", self.B, U[self.edofs])
            e = eps - eps_f[..., None] * iso - ein_old
            vol = e[..., 0] + e[..., 1] + e[..., 2]
            s_tr = np.empty_like(e)
            s_tr[..., :3] = 2 * mu[..., None] * (e[..., :3] - vol[..., None] / 3.0)
            s_tr[..., 3] = mu * e[..., 3]
            s1 = s_tr / a[..., None]
            q1 = np.sqrt(1.5 * (np.sum(s1[..., :3] ** 2, axis=-1) + 2 * s1[..., 3] ** 2))
            over = q1 > sy
            safe = np.where(q1 > 0, q1, 1.0)
            s = np.where(over[..., None], s1 * (sy / safe)[..., None], s1)
            dgam = np.where(over, (q1 - sy) / (3 * mu), 0.0)
            dein = (1.5 * m.trip_coefficient * dphi[..., None] * s1 + 1.5 * (dgam / safe)[..., None] * s1) * eng
            ein_new = ein_old + dein
            change = np.max(np.abs(ein_new - ein))
            ein = ein_new
            if change < 1e-8:
                break
        sig = s.copy()
        sig[..., :3] += (kappa * vol)[..., None]
        return sig, ein, peq_old + dgam, it + 1

    @staticmethod
    def _principal(sig):
        sxx, syy, szz, sxy = sig[..., 0], sig[..., 1], sig[..., 2], sig[..., 3]
        c = 0.5 * (sxx + syy)
        rad = np.sqrt((0.5 * (sxx - syy)) ** 2 + sxy**2)
        s1 = np.maximum(c + rad, szz)
        vm = np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * sxy**2)
        return s1, vm

    # ------------------------------------------------------------------ run
    def run(self, core_stop=60.0, target_dT=3.0, dt_max=1.0, t_end=None, verbose=False):
        m, q = self.m, self.q
        T = np.full(self.nn, self.T0)
        f = np.zeros(self.nn)
        fg = np.zeros((self.ne, 4))
        ein = np.zeros((self.ne, 4, 4))
        sig = np.zeros((self.ne, 4, 4))
        peq = np.zeros((self.ne, 4))
        n = self.n
        t, dt = 0.0, 2e-3

        def record(h):
            s1, vm = self._principal(sig)
            s1e, vme, fe = s1.mean(axis=1), vm.mean(axis=1), fg.mean(axis=1)
            out["t"].append(t)
            out["T"].append(T.reshape(self.nx, self.nx).copy())
            out["f"].append(f.reshape(self.nx, self.nx).copy())
            out["s1"].append(s1e.reshape(n, n))
            out["vm"].append(vme.reshape(n, n))
            out["fe"].append(fe.reshape(n, n))
            out["pe"].append(peq.mean(axis=1).reshape(n, n))
            out["hf"].append(float(h[self.face_node]))
            out["hc"].append(float(h[self.corner_node]))
            brittle = np.where(fe >= m.brittle_fraction, s1e, -np.inf)
            k = int(np.argmax(brittle))
            out["mb"].append(float(max(brittle[k], 0.0)) if np.isfinite(brittle[k]) else 0.0)
            out["ml"].append((k // n, k % n))

        out = {k: [] for k in ("t", "T", "f", "s1", "vm", "fe", "pe", "hf", "hc", "mb", "ml")}
        record(q.h(T))
        iters, steps = 0, 0
        core = 0  # node (0, 0) is the centre of the bar
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
            sig, ein, peq, nit = self._mech_step(Tg, fg, fg_new, ein, peq)
            iters += nit
            steps += 1
            T, f, fg = T_new, f_new, fg_new
            t += dt
            record(h)
            if verbose and steps % 100 == 0:
                print(f"  t={t:8.3f} dt={dt:.4f} Tcorner={T[self.corner_node]:7.1f} Tface={T[self.face_node]:7.1f} "
                      f"Tcore={T[core]:7.1f} maxS1brittle={out['mb'][-1]:7.1f} it={nit}")
            if T[core] <= core_stop or (t_end is not None and t >= t_end):
                break
            grow = target_dT / max(dTmax, 1e-9)
            dt = float(np.clip(dt * min(1.5, max(0.5, grow)), 2e-4, dt_max))

        return Quench2DResult(
            quenchant=q,
            half_width=self.L,
            x=self.x.copy(),
            t=np.array(out["t"]),
            T=np.array(out["T"]),
            f=np.array(out["f"]),
            sig1=np.array(out["s1"]),
            sigvm=np.array(out["vm"]),
            fel=np.array(out["fe"]),
            peq=np.array(out["pe"]),
            h_face=np.array(out["hf"]),
            h_corner=np.array(out["hc"]),
            max_brittle_sig1=np.array(out["mb"]),
            max_brittle_loc=np.array(out["ml"]),
            meta={"steps": steps, "mean_iterations": iters / max(steps, 1)},
        )
