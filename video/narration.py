"""Narration of the explainer video, one entry per spoken segment.

Each segment is synthesized as one audio clip (video/tts.py); the scene in
video/explainer.py times its animations to the sentences inside it.  Numbers
quoted here come from results/summary.json.
"""

SEGMENTS = [
    ("intro", [
        "This is a bar of high-speed steel, at twelve hundred and ten degrees Celsius.",
        "In a few minutes it will become hard enough to cut other steels, even while its own edge runs red hot.",
        "We'll follow it through the whole heat treatment, and then ask one question: what happens if we quench it in water, instead of oil?",
    ]),
    ("alloy", [
        "The steel is called M2.",
        "Besides iron, it has almost one percent carbon, about six percent tungsten, five percent molybdenum, four percent chromium, and two percent vanadium.",
        "These elements form hard carbides, the white particles you see in the microstructure.",
        "And they do something else that will matter later: they make the steel so slow to transform that it hardens even when it is cooled gently.",
    ]),
    ("heating", [
        "Here is the recipe, as temperature against time.",
        "First, heat in steps: to about five hundred and fifty degrees, then to eight hundred and fifty.",
        "This steel conducts heat poorly, so if we rushed, the surface would race ahead of the core.",
        "Then a short jump to twelve hundred and ten degrees, only about thirty degrees below the point where the grain boundaries start to melt.",
        "Here part of the carbides dissolve, and load the crystal with carbon and alloy. We hold for just a few minutes.",
    ]),
    ("martensite", [
        "Then comes the quench.",
        "Below about two hundred and fifteen degrees, the martensite start temperature, the crystal shears into a new structure: martensite. It is very hard, and very brittle.",
        "How much martensite forms depends only on how far we cool below that temperature. The fraction grows like one minus a decaying exponential.",
        "And it never quite reaches one. At room temperature, about a quarter of the old austenite is still there.",
    ]),
    ("temper", [
        "So we temper, three times, at about five hundred and sixty degrees.",
        "Each temper precipitates tiny alloy carbides, which actually raise the hardness. And each cooling turns some of the leftover austenite into fresh martensite, which the next temper then tempers.",
        "Retained austenite falls from about thirty percent to under two, and the tool ends at sixty-four to sixty-six on the Rockwell C scale.",
    ]),
    ("stages", [
        "Now, the question. Why oil, and not water? Water cools faster, after all.",
        "A liquid takes heat away in three stages. First, a blanket of vapour insulates the hot surface.",
        "Then the blanket collapses, and the liquid boils violently on the metal. That is the fast stage.",
        "Finally, below its boiling range, the liquid only carries heat away by convection.",
    ]),
    ("htc", [
        "Here is how strongly each liquid cools, against the temperature of the surface.",
        "Water boils down to about one hundred and ten degrees, so its violent stage runs straight through the martensite range.",
        "Oil boils hardest around five hundred and fifty degrees, exactly where the steel needs to be cooled quickly. By the time martensite starts to form, oil has gone calm.",
        "At two hundred and fifteen degrees, water still pulls heat about forty times harder than oil.",
    ]),
    ("simulation", [
        "We simulated a sixteen millimetre square tool bit, plunged from twelve hundred and ten degrees. Water on the left, oil on the right.",
        "In water, the corners reach the martensite start temperature after just five seconds, while the core is still above a thousand degrees.",
        "The outside is already martensite, while the inside is still glowing.",
        "In oil, nothing happens that quickly. But when the section does transform, corners, faces and core all pass the martensite start within about six seconds of each other, and within twenty degrees.",
    ]),
    ("stress", [
        "Why does that matter? Martensite takes up about one percent more space than the austenite it grows from.",
        "In water, the shell transforms first. When the core finally transforms, it swells, and pulls on a shell that is already hard and brittle.",
        "Here is the tension in that fresh martensite. In water, it peaks at about one hundred and sixty megapascals. In oil, it stays near twelve.",
    ]),
    ("crack", [
        "Is that enough to crack the tool? On a smooth face, no. A crack has to start from a flaw, and there it needs far more stress.",
        "But at a sharp notch with a small cluster of carbides, the threshold drops to about one hundred and forty megapascals.",
        "Water goes past it. Oil stays more than ten times below. And real tools are full of notches: flutes, holes, and sharp edges.",
    ]),
    ("outro", [
        "And the water bought nothing. Both bars end with the same martensite and the same hardness. Water only added stress, and about four times the distortion.",
        "That is why high-speed steel is hardened in oil, in molten salt, or in pressurized gas, and then tempered right away. Never in water.",
    ]),
]
