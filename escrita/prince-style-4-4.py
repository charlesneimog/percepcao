import random
import xml.etree.ElementTree as ET
from fractions import Fraction
from xml.dom import minidom

# ============================================================
# Configuration
# ============================================================

random.seed(42)

OUTPUT = "score.musicxml"
DIVISIONS = 10080
MEASURES_PER_GROUP = 4
REST_PROBABILITY = 0.15

Q = Fraction(1)
E = Fraction(1, 2)
S = Fraction(1, 4)

# All measures contain exactly two beats.
# Every four measures form one exercise group.

PATTERNS = [
    # Group 1 — Basic rhythms
    [E, E, Q],
    [Q, E, E],
    [E, E, E, E],
    [Q, Q],
    # Group 2 — Sixteenth notes
    [S, S, E, Q],
    [E, S, S, Q],
    [Q, S, S, E],
    [S, S, S, S, Q],
    # Group 3 — Mixed subdivisions
    [E, E, S, S, E],
    [S, S, E, E, E],
    [E, S, S, E, E],
    [S, S, S, S, E, E],
    # Group 4 — Syncopations
    [E, S, E, S, E],
    [S, E, E, S, E],
    [S, E, S, E, E],
    [E, E, S, E, S],
    # Group 5 — Across beat boundaries
    [E, S, E, E, S],
    [S, E, E, E, S],
    [E, S, E, S, E],
    [S, E, S, E, E],
    # Group 6 — More subdivisions
    [S, S, E, S, E, S],
    [E, S, S, S, E, S],
    [S, E, S, S, S, E],
    [E, S, E, S, S, S],
    # Group 7 — Advanced syncopations
    [S, E, E, S, E],
    [E, S, E, E, S],
    [S, S, E, S, E, S],
    [E, S, S, E, S, S],
    # Group 8 — Review
    [S, E, S, E, E],
    [E, E, S, E, S],
    [E, S, E, S, E],
    [S, E, E, E, S],
]

NUM_MEASURES = len(PATTERNS)

for i, pattern in enumerate(PATTERNS, 1):
    assert sum(pattern) == 2, f"Measure {i}: invalid duration {sum(pattern)}"


# ============================================================
# XML helpers
# ============================================================


def element(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, tag, attrs)

    if text is not None:
        node.text = str(text)

    return node


# ============================================================
# Global rest selection
# ============================================================


def select_rests(patterns, probability):
    """
    Select approximately 15% of the original events
    as visible rests.

    Preserve at least one sounding note per measure.
    """

    candidates = []
    protected = set()

    for measure_index, pattern in enumerate(patterns):
        # One guaranteed sounding event per measure.
        protected_index = random.randrange(len(pattern))
        protected.add((measure_index, protected_index))

        for event_index in range(len(pattern)):
            candidates.append((measure_index, event_index))

    eligible = [item for item in candidates if item not in protected]

    target = round(len(candidates) * probability)
    target = min(target, len(eligible))

    return set(random.sample(eligible, target))


REST_EVENTS = select_rests(PATTERNS, REST_PROBABILITY)


# ============================================================
# Staff distribution
# ============================================================


def distribute(pattern):
    """
    Randomly assign original events to two staves.

    The durations never change.
    """

    first = random.choice((1, 2))
    assignments = [first]

    for _ in pattern[1:]:
        previous = assignments[-1]

        if random.random() < 0.7:
            current = 3 - previous
        else:
            current = previous

        assignments.append(current)

    if len(pattern) > 1 and len(set(assignments)) == 1:
        index = random.randrange(1, len(pattern))
        assignments[index] = 3 - assignments[index]

    return assignments


# ============================================================
# Events and syncopations
# ============================================================


def make_events(pattern, assignments, measure_index):
    """
    Create a shared timeline.

    Notes crossing the second beat are split and tied.
    Rests crossing the second beat are split without ties.

    A tied continuation is NOT an additional onset.
    """

    events = []
    onset = Fraction(0)

    for event_index, (value, staff) in enumerate(zip(pattern, assignments)):

        is_rest = (measure_index, event_index) in REST_EVENTS

        end = onset + value

        if onset < Q < end:
            first = Q - onset
            second = end - Q

            events.append(
                {
                    "duration": first,
                    "staff": staff,
                    "onset": onset,
                    "rest": is_rest,
                    "tie": None if is_rest else "start",
                    "attack": not is_rest,
                }
            )

            events.append(
                {
                    "duration": second,
                    "staff": staff,
                    "onset": Q,
                    "rest": is_rest,
                    "tie": None if is_rest else "stop",
                    "attack": False,
                }
            )

        else:
            events.append(
                {
                    "duration": value,
                    "staff": staff,
                    "onset": onset,
                    "rest": is_rest,
                    "tie": None,
                    "attack": not is_rest,
                }
            )

        onset = end

    assert onset == 2
    return events


# ============================================================
# Cross-staff beams
# ============================================================


def beam_groups(events):
    """
    Beaming is computed from a single shared timeline.

    - Eighth notes: level 1
    - Sixteenth notes: levels 1 and 2
    - Rests interrupt beams
    - Quarter notes interrupt beams
    - Beams do not cross the second-beat boundary
    """

    result = [{} for _ in events]

    def apply_group(indices):
        if len(indices) < 2:
            return

        # Primary beam
        for k, i in enumerate(indices):
            result[i][1] = (
                "begin" if k == 0 else "end" if k == len(indices) - 1 else "continue"
            )

        # Secondary beams
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
                        "begin"
                        if k == 0
                        else "end" if k == len(run) - 1 else "continue"
                    )
            else:
                i = run[0]
                k = indices.index(i)

                if k == 0:
                    result[i][2] = "forward hook"
                elif k == len(indices) - 1:
                    result[i][2] = "backward hook"
                else:
                    # Prefer a beam hook toward the
                    # beginning of the current beat.
                    result[i][2] = "backward hook"

    # Process each beat independently
    for beat in range(2):
        start = Fraction(beat)
        end = start + Q

        indices = [i for i, event in enumerate(events) if start <= event["onset"] < end]

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
# MusicXML initialization
# ============================================================

root = ET.Element("score-partwise", version="4.0")

work = element(root, "work")
element(work, "work-title", "Estudos Rítmicos")

element(root, "movement-title", "Estudos Rítmicos")

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

    measure = element(part, "measure", number=str(number))

    # New system after every four measures
    if number > 1 and (number - 1) % MEASURES_PER_GROUP == 0:
        element(measure, "print", **{"new-system": "yes"})

    # Initial score attributes
    if number == 1:

        attributes = element(measure, "attributes")

        element(attributes, "divisions", DIVISIONS)

        time = element(attributes, "time")
        element(time, "beats", 2)
        element(time, "beat-type", 4)

        element(attributes, "staves", 2)

        # IMPORTANT:
        # Percussion clef on BOTH one-line staves.
        for staff_number in (1, 2):

            staff_clef = element(attributes, "clef", number=str(staff_number))
            element(staff_clef, "sign", "percussion")

            details = element(
                attributes,
                "staff-details",
                number=str(staff_number),
                **{"print-object": "yes"},
            )
            element(details, "staff-lines", 1)

    assignments = distribute(pattern)

    events = make_events(pattern, assignments, number - 1)

    beams = beam_groups(events)

    assert sum(e["duration"] for e in events) == 2

    for i, event in enumerate(events):

        value = event["duration"]
        staff_number = event["staff"]
        tie_type = event["tie"]

        n = element(measure, "note")

        if event["rest"]:
            # Visible rest on the assigned staff.
            element(n, "rest")
        else:
            pitch = element(n, "pitch")
            element(pitch, "step", "E" if staff_number == 1 else "F")
            element(pitch, "octave", 5)

        element(n, "duration", int(value * DIVISIONS))

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
            for level, beam_type in sorted(beams[i].items()):
                element(n, "beam", beam_type, number=str(level))

        if tie_type is not None:
            notations = element(n, "notations")
            element(notations, "tied", type=tie_type)

    # Double barline every four measures.
    if number % MEASURES_PER_GROUP == 0:
        barline = element(measure, "barline", location="right")
        element(barline, "bar-style", "light-light")

    rest_count = sum((number - 1, i) in REST_EVENTS for i in range(len(pattern)))

    print(
        f"Measure {number:02d}: "
        f"{[str(v) for v in pattern]} "
        f"staff={assignments} "
        f"rests={rest_count}"
    )


# ============================================================
# Export
# ============================================================

xml_bytes = ET.tostring(root, encoding="utf-8")

pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8")

with open(OUTPUT, "wb") as f:
    f.write(pretty)

total_events = sum(len(p) for p in PATTERNS)
total_rests = len(REST_EVENTS)

print(f"\nSaved: {OUTPUT}")
print(f"Measures: {NUM_MEASURES}")
print(f"Groups: {NUM_MEASURES // MEASURES_PER_GROUP}")
print(f"Original rhythmic events: {total_events}")
print(f"Rests: {total_rests}")
print(f"Rest proportion: {total_rests / total_events:.1%}")
