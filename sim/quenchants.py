"""Heat-transfer coefficient h(T_surface) of quench media.

A liquid quenchant removes heat in three stages as the surface cools:

  A  vapour blanket (film boiling, Leidenfrost) - an insulating steam/oil-vapour
     film; slow cooling, heat goes out mostly by radiation and through the film.
  B  nucleate boiling - the film collapses, liquid touches the metal and boils
     violently; this is the fastest stage.
  C  convection - the surface is below the liquid's boiling range; slow.

What matters for high-speed steel is *where* stage B sits relative to the
martensite range (Ms ~215 °C down to room temperature):

* water boils at 100 °C, so its violent boiling stage runs from ~700 °C all
  the way down to ~110 °C - straight through Ms;
* quench oil boils at 250-350 °C, so it boils fast at 400-650 °C (where HSS
  must be cooled quickly to avoid carbide precipitation) and has already
  switched to gentle convection when martensite starts forming.

The tables below are representative of a still bath (h referred to the bath
temperature).  Peak values: oil ~4 kW/m^2K at ~550 °C (measured mineral oils
peak at 4.7-6 kW/m^2K around 520-550 °C), water ~15 kW/m^2K around 400 °C and
still ~11 kW/m^2K at 200 °C.  In the vapour-blanket stage cold, strongly
sub-cooled water (~1.2 kW/m^2K) removes heat faster than hot oil (~0.5 kW/m^2K).
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Quenchant:
    key: str
    name: str
    bath_temperature: float  # °C
    table_T: tuple  # surface temperature, °C (ascending)
    table_h: tuple  # W/(m^2 K)
    film_boiling_below: float  # vapour blanket collapses below this surface T
    boiling_ends_below: float  # nucleate boiling stops below this surface T

    def h(self, Ts):
        return np.interp(Ts, self.table_T, self.table_h)

    def stage(self, Ts):
        """'vapour', 'boiling', 'convection' (or 'air' for a gas)."""
        if self.film_boiling_below is None:
            return "air"
        if Ts > self.film_boiling_below:
            return "vapour"
        if Ts > self.boiling_ends_below:
            return "boiling"
        return "convection"


WATER = Quenchant(
    key="water",
    name="Water, 20 °C, still",
    bath_temperature=20.0,
    table_T=(20, 80, 100, 120, 150, 200, 300, 400, 500, 600, 700, 800, 1300),
    table_h=(800, 1000, 2000, 4500, 8000, 11500, 14000, 15000, 13000, 8000, 2500, 1200, 1200),
    film_boiling_below=720.0,
    boiling_ends_below=110.0,
)

OIL = Quenchant(
    key="oil",
    name="Mineral quench oil, 50 °C, still",
    bath_temperature=50.0,
    table_T=(50, 150, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 1300),
    table_h=(250, 280, 320, 450, 900, 1800, 3000, 3800, 4200, 3500, 2000, 900, 550, 500),
    film_boiling_below=700.0,
    boiling_ends_below=320.0,
)

# Still air - not a liquid, shown only as the slow reference limit.
AIR = Quenchant(
    key="air",
    name="Still air, 20 °C",
    bath_temperature=20.0,
    # natural convection + radiation (emissivity ~0.8)
    table_T=(20, 200, 400, 600, 800, 1000, 1300),
    table_h=(10, 22, 35, 55, 85, 125, 190),
    film_boiling_below=None,
    boiling_ends_below=None,
)

QUENCHANTS = {q.key: q for q in (WATER, OIL, AIR)}
