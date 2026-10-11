"""Quench model of an AISI M2 (HS 6-5-2) high-speed-steel bar.

The package simulates the hardening quench of a long round bar after
austenitizing at ~1210 °C and compares quenchants (water vs. oil):

* :mod:`sim.material`   - temperature/phase dependent properties of M2
* :mod:`sim.quenchants` - heat-transfer coefficient h(T_surface) of each medium
* :mod:`sim.model`      - coupled thermal / phase / stress solver
* :mod:`sim.run`        - command line entry point (data export + figures)
"""
