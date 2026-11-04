#!/usr/bin/env python3
"""Generate melodies with a piano accompaniment from two MusicXML files.

Each result has 2 silent flute introduction measures, 4 random two-measure
melody patterns (8 measures), and a final flute measure (E5): 11 in total.

The piano file supplies three one-measure accompaniment patterns:
    measure 1: E minor
    measure 2: B major
    measure 3: B minor

Piano accompaniment follows the harmony of each selected melody pattern:
Em in its first measure and B or Bm in its second measure. Both the
introduction and ending use Em. All chord symbols are removed. The flute contains only single notes/rests;
the piano retains its played chords. Tempo is 90 BPM.

Examples:
    python generate_random_melodies.py menor.musicxml --count 10 --midi
    python generate_random_melodies.py menor.musicxml --piano piano.musicxml -n 10

Requires: pip install music21
"""

import argparse
import copy
import random
from pathlib import Path
import subprocess


from music21 import (
    chord,
    clef,
    converter,
    harmony,
    instrument,
    key,
    layout,
    metadata,
    tempo,
    meter,
    note,
    stream,
)

PATTERN_COUNT = 4

# Each block contains three B-major patterns, followed by their
# B-minor variants. Asterisk (*) identifies the minor variant.
PATTERN_LABELS = (
    "A",
    "B",
    "C",
    "A*",
    "B*",
    "C*",
    "D",
    "E",
    "F",
    "D*",
    "E*",
    "F*",
    "G",
    "H",
    "I",
    "G*",
    "H*",
    "I*",
)
INTRO_MEASURES = 2
ENDING_PITCH = "E5"


def make_e_measure(number, beats):
    measure = stream.Measure(number=number)
    measure.insert(0, note.Note(ENDING_PITCH, quarterLength=beats))
    return measure


def copy_notes(source_measure, number):
    """Copy only single flute notes/rests, excluding chords and chord symbols."""
    measure = stream.Measure(number=number)

    for original in source_measure.notesAndRests:
        if not isinstance(original, (note.Note, note.Rest)):
            continue
        item = copy.deepcopy(original)
        if isinstance(item, note.Note) and item.pitch.accidental is not None:
            item.pitch.accidental.displayStatus = None
        measure.insert(original.offset, item)

    return measure


def copy_initial_notation(source_measure, target_measure):
    for item in source_measure:
        if isinstance(item, (clef.Clef, key.KeySignature, meter.TimeSignature)):
            target_measure.insert(0, copy.deepcopy(item))


def second_measure_harmony(source_measure):
    """Return piano template index 1 (B) or 2 (Bm)."""
    for symbol in source_measure.recurse().getElementsByClass(harmony.ChordSymbol):
        if symbol.root() is not None and symbol.root().step == "B":
            if symbol.chordKind == "major":
                return 1
            if symbol.chordKind == "minor":
                return 2

    raise ValueError("Each pattern's second measure must have a B or Bm chord symbol")


def copy_piano_measure(source_measure, number, template_index):
    """Copy all piano notation, including voices, rhythms and both hands."""
    measure = copy.deepcopy(source_measure)
    measure.number = number

    # Remove written chord names; retain actual harmonic notes/chords.
    for symbol in list(measure.recurse().getElementsByClass(harmony.ChordSymbol)):
        symbol.activeSite.remove(symbol)

    # The supplied Bm template is labeled Bm but contains D-sharps.
    # D natural is required for a B minor chord (B-D-F#).
    if template_index == 2:
        for item in measure.recurse().notes:
            if isinstance(item, note.Note):
                pitches = [item.pitch]
            elif isinstance(item, chord.Chord):
                pitches = item.pitches
            else:
                continue

            for pitch in pitches:
                if pitch.step == "D" and pitch.alter == 1:
                    pitch.accidental = None

    # Do not repeat the final barline from measure 3 of piano.musicxml.
    measure.leftBarline = None
    measure.rightBarline = None

    # The original first measure carries clefs, key and time signature.
    # Keep them only at the start of each output part.
    if number != 1:
        for item in list(
            measure.getElementsByClass(
                (clef.Clef, key.KeySignature, meter.TimeSignature)
            )
        ):
            measure.remove(item)

    return measure


def generate(source_measures, piano_parts, pattern_indices, beats, title):
    score = stream.Score()
    score.metadata = metadata.Metadata()
    score.metadata.title = title

    flute = stream.Part()
    flute.partName = "Flute"
    flute.partAbbreviation = "Fl."
    flute.insert(0, instrument.Flute())

    # Keep two silent introductory bars so the flute enters in bar 3.
    for number in range(1, INTRO_MEASURES + 1):
        measure = stream.Measure(number=number)
        if number == 1:
            copy_initial_notation(source_measures[0], measure)
            measure.insert(0, tempo.MetronomeMark(number=90))
        measure.insert(0, note.Rest(quarterLength=beats))
        flute.append(measure)

    # 0 = Em, 1 = B major, 2 = B minor.
    piano_sequence = [0] * INTRO_MEASURES
    next_number = INTRO_MEASURES + 1

    for index in pattern_indices:
        first = source_measures[2 * index]
        second = source_measures[2 * index + 1]

        flute.append(copy_notes(first, next_number))
        flute.append(copy_notes(second, next_number + 1))
        piano_sequence.extend([0, second_measure_harmony(second)])
        next_number += 2

    flute.append(make_e_measure(next_number, beats))
    piano_sequence.append(0)
    score.append(flute)

    # music21 usually imports the two piano staves as two PartStaff objects.
    # Repeat the matching measure in each staff to preserve the arrangement.
    output_piano_parts = []

    for original_part in piano_parts:
        original_measures = list(original_part.getElementsByClass(stream.Measure))
        if len(original_measures) < 3:
            raise ValueError("piano.musicxml must contain the three Em, B, Bm measures")

        if isinstance(original_part, stream.PartStaff):
            piano_part = stream.PartStaff()
        else:
            piano_part = stream.Part()

        piano_part.partName = "Piano"
        piano_part.partAbbreviation = "Pno."
        piano_part.insert(0, instrument.Piano())

        for number, template_index in enumerate(piano_sequence, start=1):
            measure = copy_piano_measure(
                original_measures[template_index], number, template_index
            )
            if number == len(piano_sequence):
                # Final bar: E3 whole note, instead of the Em accompaniment.
                for element in list(measure):
                    if isinstance(element, stream.Voice):
                        measure.remove(element)
                for element in list(measure.notesAndRests):
                    measure.remove(element)
                if original_part is piano_parts[-1]:
                    measure.insert(0, note.Note("E3", quarterLength=beats))
                else:
                    measure.insert(0, note.Rest(quarterLength=beats))
            piano_part.append(measure)

        score.append(piano_part)
        output_piano_parts.append(piano_part)

    if len(output_piano_parts) > 1:
        group = layout.StaffGroup(
            *output_piano_parts,
            name="Piano",
            abbreviation="Pno.",
            symbol="brace",
            barTogether=True,
        )
        score.insert(0, group)

    return score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, help="MusicXML with two-measure flute patterns"
    )
    parser.add_argument(
        "--piano",
        type=Path,
        default=None,
        help="MusicXML with Em, B and Bm in measures 1, 2 and 3 "
        "(default: piano.musicxml next to input)",
    )
    parser.add_argument(
        "--count", "-n", type=int, default=1, help="Number of melodies (default: 1)"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("generated"))
    parser.add_argument(
        "--seed", type=int, default=None, help="Seed for reproducible results"
    )
    parser.add_argument("--midi", action="store_true", help="Also write MIDI files")
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be at least 1")

    piano_path = args.piano or args.input.with_name("piano.musicxml")
    original_score = converter.parse(str(args.input))
    piano_score = converter.parse(str(piano_path))
    source_measures = list(original_score.parts[0].getElementsByClass(stream.Measure))

    if len(source_measures) % 2:
        parser.error("The melody input must have an even number of measures")

    total_patterns = len(source_measures) // 2
    if total_patterns != len(PATTERN_LABELS):
        parser.error(
            f"Expected {len(PATTERN_LABELS)} labeled patterns; found {total_patterns}"
        )
    if total_patterns < PATTERN_COUNT:
        parser.error(f"The melody input needs at least {PATTERN_COUNT} patterns")

    beats = source_measures[0].barDuration.quarterLength
    rng = random.Random(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for number in range(1, args.count + 1):
        selected = rng.sample(range(total_patterns), PATTERN_COUNT)
        pattern_name = "-".join(PATTERN_LABELS[index] for index in selected)
        title = pattern_name
        score = generate(source_measures, piano_score.parts, selected, beats, title)
        filename = args.output_dir / pattern_name
        # If the same sequence is drawn twice, avoid overwriting a file.
        if filename.with_suffix(".musicxml").exists():
            filename = args.output_dir / f"{pattern_name}_{number:03d}"

        filename = Path(str(filename).replace("*", "m"))

        xml_file = filename.with_suffix(".musicxml")
        mp3_file = filename.with_suffix(".mp3")

        score.write("musicxml", fp=str(xml_file))

        subprocess.run(
            ["mscore", "-o", str(mp3_file), str(xml_file)],
            check=True,
        )

        if args.midi:
            score.write("midi", fp=str(filename.with_suffix(".mid")))

        print(f"{filename}: {pattern_name}")


if __name__ == "__main__":
    main()
