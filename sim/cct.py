"""Schematic continuous-cooling (CCT) fields of M2 / HS 6-5-2 austenitized at ~1210 °C.

These are *schematic* start curves drawn after the general shape of published
CCT diagrams for HS 6-5-2: high-temperature precipitation of carbides on the
austenite grain boundaries, a pearlite nose around 750 °C, a stable austenite
"bay" around 450-600 °C, bainite only after very long times, and martensite
below Ms.  Time is measured from the start of the quench.  They are used only
to show *where* the computed cooling curves run - positions are approximate.
"""

CCT_FIELDS = {
    "carbides": {
        "label": "Carbide precipitation on grain boundaries",
        "points": [(1150, 700), (1050, 260), (950, 160), (900, 150), (850, 170), (800, 240), (760, 400)],
    },
    "pearlite": {
        "label": "Pearlite (annealed structure)",
        "points": [(850, 2600), (800, 1200), (750, 900), (700, 1000), (650, 1700), (620, 3500)],
    },
    "bainite": {
        "label": "Bainite",
        "points": [(420, 6000), (380, 2500), (330, 1800), (280, 2200), (250, 5000)],
    },
}

AC1 = 832.0  # °C, start of austenite formation on heating (M2)
AC3 = 877.0  # °C
