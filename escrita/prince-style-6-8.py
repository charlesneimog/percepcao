
import random
import xml.etree.ElementTree as ET
from fractions import Fraction
from xml.dom import minidom

# ============================================================
# Configuration
# ============================================================

random.seed(42)

OUTPUT = "score_6-8.musicxml"
DIVISIONS = 10080
MEASURES_PER_GROUP = 4
REST_PROBABILITY = 0.15

Q = Fraction(1)
E = Fraction(1, 2)
S = Fraction(1, 4)

MEASURE_LENGTH = 3 * Q
BEAT_LENGTH = Fraction(3, 2)  # Dotted quarter

# Each rhythmic cell occupies one dotted-quarter beat.
# Durations are expressed in sixteenth-note units.
# 1 = sixteenth, 2 = eighth, 4 = quarter.

CELLS = [
    [2, 2, 2],
    [4, 2],
    [2, 4],
    [1, 1, 2, 2],
    [2, 1, 1, 2],
    [1, 2, 1, 2],
    [2, 2, 1, 1],
    [1, 1, 1, 1, 2],
]

# 24 exercises with clear compound-beat groupings.
CELL_PAIRS = [
    (0, 0), (1, 0), (0, 2), (1, 2),
    (0, 3), (3, 0), (4, 1), (2, 5),
    (3, 3), (4, 4), (5, 6), (6, 5),
    (7, 0), (0, 7), (7, 3), (3, 7),
    (4, 5), (5, 4), (6, 7), (7, 6),
    (7, 7), (3, 5), (5, 3), (6, 4),
]

# 8 more exercises with notes crossing the dotted-quarter
# boundary. Those notes will be split and tied.
SYNCOPATIONS = [
    [2, 2, 1, 2, 1, 2, 2],
    [4, 1, 2, 1, 4],
    [1, 2, 2, 2, 1, 2, 2],
    [2, 1, 2, 2, 1, 4],
    [1, 1, 2, 1, 2, 1, 2, 2],
    [2, 2, 2, 1, 2, 1, 2],
    [4, 1, 2, 2, 1, 2],
    [1, 2, 1, 1, 2, 1, 2, 2],
]

PATTERNS = [
    [Fraction(v, 4) for v in CELLS[a] + CELLS[b]]
    for a, b in CELL_PAIRS
] + [
    [Fraction(v, 4) for v in pattern]
    for pattern in SYNCOPATIONS
]

for i, pattern in enumerate(PATTERNS, 1):
    assert sum(pattern) == MEASURE_LENGTH, (
        f"Measure {i}: {sum(pattern)} instead of 3"
    )

assert len(PATTERNS) == 32


# ============================================================
# XML helper
# ============================================================

def element(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, tag, attrs)
    if text is not None:
        node.text = str(text)
    return node


# ============================================================
# Select approximately 15% rests
# ============================================================

def select_rests(patterns):
    candidates = []
    protected = set()

    for measure_index, pattern in enumerate(patterns):
        protected.add((
            measure_index,
            random.randrange(len(pattern))
        ))

        for event_index in range(len(pattern)):
            candidates.append((measure_index, event_index))

    eligible = [
        item for item in candidates
        if item not in protected
    ]

    target = round(
        len(candidates) * REST_PROBABILITY
    )

    return set(random.sample(eligible, target))


REST_EVENTS = select_rests(PATTERNS)


# ============================================================
# Random upper/lower staff assignment
# ============================================================

def distribute(pattern):
    assignments = [random.choice((1, 2))]

    for _ in pattern[1:]:
        previous = assignments[-1]

        if random.random() < 0.7:
            assignments.append(3 - previous)
        else:
            assignments.append(previous)

    return assignments


# ============================================================
# Split syncopations at dotted-quarter boundary
# ============================================================

def make_events(pattern, assignments, measure_index):
    events = []
    onset = Fraction(0)

    for event_index, (value, staff) in enumerate(
        zip(pattern, assignments)
    ):
        is_rest = (
            measure_index,
            event_index
        ) in REST_EVENTS

        end = onset + value

        if onset < BEAT_LENGTH < end:
            first = BEAT_LENGTH - onset
            second = end - BEAT_LENGTH

            events.append({
                "duration": first,
                "staff": staff,
                "onset": onset,
                "rest": is_rest,
                "tie": None if is_rest else "start",
                "attack": not is_rest,
            })

            events.append({
                "duration": second,
                "staff": staff,
                "onset": BEAT_LENGTH,
                "rest": is_rest,
                "tie": None if is_rest else "stop",
                "attack": False,
            })

        else:
            events.append({
                "duration": value,
                "staff": staff,
                "onset": onset,
                "rest": is_rest,
                "tie": None,
                "attack": not is_rest,
            })

        onset = end

    assert onset == MEASURE_LENGTH
    return events


# ============================================================
# Beam grouping for compound meter
# ============================================================

def beam_groups(events):
    result = [{} for _ in events]

    def apply_group(indices):
        if len(indices) < 2:
            return

        # Primary beam
        for k, i in enumerate(indices):
            result[i][1] = (
                "begin" if k == 0
                else "end" if k == len(indices) - 1
                else "continue"
            )

        # Secondary beam for sixteenths
        runs = []
        current = []

        for i in indices:
            if events[i]["duration"] == S:
                current.append(i)
            else:
                if current:
                    runs.append(current)
                    current = []

        if current:
            runs.append(current)

        for run in runs:
            if len(run) >= 2:
                for k, i in enumerate(run):
                    result[i][2] = (
                        "begin" if k == 0
                        else "end" if k == len(run) - 1
                        else "continue"
                    )
            else:
                i = run[0]
                k = indices.index(i)

                result[i][2] = (
                    "forward hook"
                    if k == 0
                    else "backward hook"
                )

    # Two dotted-quarter beats per measure
    for beat in range(2):
        start = beat * BEAT_LENGTH
        end = start + BEAT_LENGTH

        indices = [
            i for i, event in enumerate(events)
            if start <= event["onset"] < end
        ]

        group = []

        for i in indices:
            event = events[i]

            if event["rest"] or event["duration"] >= Q:
                apply_group(group)
                group = []
            else:
                group.append(i)

        apply_group(group)

    return result


# ============================================================
# Score
# ============================================================

root = ET.Element("score-partwise", version="4.0")

work = element(root, "work")
element(work, "work-title", "Estudos Rítmicos — 6/8")

element(root, "movement-title", "Estudos Rítmicos — 6/8")

identification = element(root, "identification")
element(identification, "creator", "", type="composer")

defaults = element(root, "defaults")
scaling = element(defaults, "scaling")
element(scaling, "millimeters", 7)
element(scaling, "tenths", 40)

part_list = element(root, "part-list")
score_part = element(part_list, "score-part", id="P1")
element(score_part, "part-name", "Percussion")

part = element(root, "part", id="P1")


# ============================================================
# Generate measures
# ============================================================

for number, pattern in enumerate(PATTERNS, 1):

    measure = element(
        part, "measure", number=str(number)
    )

    # New system every four measures
    if number > 1 and (
        number - 1
    ) % MEASURES_PER_GROUP == 0:
        element(
            measure, "print",
            **{"new-system": "yes"}
        )

    if number == 1:
        attributes = element(measure, "attributes")
        element(attributes, "divisions", DIVISIONS)

        time = element(attributes, "time")
        element(time, "beats", 6)
        element(time, "beat-type", 8)

        element(attributes, "staves", 2)

        for staff_number in (1, 2):
            staff_clef = element(
                attributes,
                "clef",
                number=str(staff_number)
            )
            element(staff_clef, "sign", "percussion")

            details = element(
                attributes,
                "staff-details",
                number=str(staff_number),
                **{"print-object": "yes"}
            )
            element(details, "staff-lines", 1)

    assignments = distribute(pattern)
    events = make_events(
        pattern, assignments, number - 1
    )

    beams = beam_groups(events)

    assert sum(
        e["duration"] for e in events
    ) == MEASURE_LENGTH

    for i, event in enumerate(events):
        value = event["duration"]
        staff_number = event["staff"]
        tie_type = event["tie"]

        n = element(measure, "note")

        if event["rest"]:
            element(n, "rest")
        else:
            pitch = element(n, "pitch")

            # Upper staff F5; lower staff E5
            element(
                pitch,
                "step",
                "F" if staff_number == 1 else "E"
            )
            element(pitch, "octave", 5)

        element(
            n, "duration",
            int(value * DIVISIONS)
        )
        element(n, "voice", 1)

        if tie_type is not None:
            element(n, "tie", type=tie_type)

        note_type = {
            Q: "quarter",
            E: "eighth",
            S: "16th",
        }[value]

        element(n, "type", note_type)

        if not event["rest"]:
            element(n, "stem", "up")

        element(n, "staff", staff_number)

        if not event["rest"]:
            for level, beam_type in sorted(
                beams[i].items()
            ):
                element(
                    n, "beam", beam_type,
                    number=str(level)
                )

        if tie_type is not None:
            notations = element(n, "notations")
            element(
                notations, "tied",
                type=tie_type
            )

    # Double barline every four measures
    if number % MEASURES_PER_GROUP == 0:
        barline = element(
            measure,
            "barline",
            location="right"
        )
        element(barline, "bar-style", "light-light")

    print(
        f"Measure {number:02d}: "
        f"{[str(v) for v in pattern]} "
        f"staff={assignments}"
    )


# ============================================================
# Export
# ============================================================

xml_bytes = ET.tostring(root, encoding="utf-8")

pretty = minidom.parseString(
    xml_bytes
).toprettyxml(
    indent="  ",
    encoding="utf-8"
)

with open(OUTPUT, "wb") as f:
    f.write(pretty)

total_events = sum(len(p) for p in PATTERNS)
total_rests = len(REST_EVENTS)

print(f"\nSaved: {OUTPUT}")
print(f"Measures: {len(PATTERNS)}")
print(f"Groups: {len(PATTERNS) // MEASURES_PER_GROUP}")
print(f"Rests: {total_rests / total_events:.1%}")

