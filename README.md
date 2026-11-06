# score-algorithms

Turn score edits into rich diffs using a combination of algorithms and LLMs for **ScoreControl: Git For Sheet Music**.

This branch provides two lightweight, modular scripts for parsing MuseScore files and computing score notation differences:
1. **`extract_score.py`**: Extracts standard MusicXML and rich score metadata (including full instrumentation) from MuseScore files (`.mscz` / `.mscx`).
2. **`diff_scores.py`**: Compares two musical scores (`.mscz`, `.mscx`, or `.musicxml`) using [`musicdiff`](https://github.com/musicdiff/musicdiff) and outputs either console text diffs or visual marked-up PDFs.

---

## Prerequisites

- **Python 3.10+** (e.g., in the `score-algos` Conda environment)
- **Python dependencies**:
  ```bash
  pip install -r requirements.txt
  ```
- **MuseScore 3 or 4**: Required for MusicXML export and visual PDF rendering. The scripts automatically detect MuseScore executables across Linux (`mscore`, `musescore`), Windows / WSL mounts (`/mnt/c/Program Files/MuseScore 4/bin/MuseScore4.exe`), and macOS application bundles.

---

## 1. `extract_score.py`: Score Extraction & Metadata

Extracts standard MusicXML and parses score metadata along with complete instrumentation.

- **Instant Metadata Extraction (Pure Python)**: Unzips `.mscz` archives in memory to parse score properties and instrumentation in milliseconds using Python's standard library (`zipfile` + `xml.etree.ElementTree`).
- **MusicXML Export**: Invokes the MuseScore CLI to export fully rendered MusicXML 4.0 files.

### CLI Usage

```bash
# Extract both MusicXML and metadata JSON:
python3 extract_score.py msczs/tbd-ss-8-12.mscz -o extracted/tbd-ss-8-12.musicxml -m extracted/tbd-ss-8-12.json

# Extract metadata only (fast, pure Python, printed to stdout):
python3 extract_score.py msczs/tbd-ss-8-12.mscz --meta-only --print-meta

# Export MusicXML only:
python3 extract_score.py msczs/tbd-ss-8-12.mscz --xml-only -o score.musicxml
```

### CLI Arguments

| Argument | Description |
|---|---|
| `score` | Path to `.mscz` or `.mscx` input file |
| `-o`, `--output-xml` | Destination file path for `.musicxml` |
| `-m`, `--metadata-out` | Destination file path for metadata `.json` |
| `--print-meta` | Print formatted metadata JSON to console |
| `--meta-only` | Only extract metadata (pure Python, skips MuseScore CLI) |
| `--xml-only` | Only export MusicXML (skips saving metadata JSON) |

### Python API

```python
from extract_score import extract_metadata, export_musicxml, extract_score

# Extract metadata dictionary (title, composer, parts, instruments, MIDI):
meta = extract_metadata("msczs/tbd-ss-8-12.mscz")
print(meta["metadata"])
print(meta["instrumentation"])

# Export MusicXML:
xml_path = export_musicxml("msczs/tbd-ss-8-12.mscz", "output.musicxml")

# Convenience helper for both:
xml_path, meta = extract_score("msczs/tbd-ss-8-12.mscz", output_json="meta.json")
```

#### Metadata Structure Example

```json
{
  "file": "tbd-ss-8-12.mscz",
  "metadata": {
    "workTitle": "Untitled score",
    "composer": "Composer / arranger",
    "creationDate": "2025-10-03",
    "measureCount": 107
  },
  "instrumentation": [
    {
      "partId": "1",
      "trackName": "Alto",
      "instrumentId": "alto",
      "longName": "Girl Solo",
      "shortName": "G.S.",
      "clef": "",
      "midiChannel": "0",
      "midiProgram": "52",
      "synthesizer": "Fluid"
    }
  ]
}
```

---

## 2. `diff_scores.py`: Score Comparison via `musicdiff`

Compares two scores and reports notation differences (pitches, rhythms, lyrics, dynamics, barlines, staves, ties, etc.).

- Directly accepts `.mscz`, `.mscx`, or `.musicxml` files.
- Automatically converts `.mscz` files to MusicXML and caches them in `./extracted`.
- Automatically configures `music21`'s MuseScore backend so marked-up PDF generation works seamlessly.

### CLI Usage

```bash
# Print musical notation text diff to stdout:
python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --text

# Generate annotated visual comparison PDFs (saved to ./diffs/ by default):
python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --pdf

# Specify custom PDF output paths:
python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --pdf out1.pdf out2.pdf
```

### CLI Arguments

| Argument | Description |
|---|---|
| `score1`, `score2` | Paths to the two scores to compare (`.mscz`, `.mscx`, or `.musicxml`) |
| `-t`, `--text` | Print notation diffs directly to the terminal |
| `-p`, `--pdf [PDF ...]` | Generate annotated PDFs. Pass 0 arguments for default (`./diffs/<score>_diff.pdf`) or 2 paths |
| `-c`, `-e`, `--cache-dir` | Directory to cache exported MusicXML files (default: `./extracted`) |

### Python API

```python
from pathlib import Path
from diff_scores import run_diff

# Console text diff:
num_diffs = run_diff("score1.mscz", "score2.mscz", print_text=True)

# Visual PDF diff:
num_diffs = run_diff(
    "score1.mscz",
    "score2.mscz",
    pdf_paths=(Path("diffs/s1.pdf"), Path("diffs/s2.pdf")),
)
print(f"Total notation differences: {num_diffs}")
```

---

## Backward Compatibility: `test.py`

`test.py` is maintained as a lightweight wrapper delegating directly to `diff_scores.py`. Existing commands like:

```bash
python3 test.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --text
```

continue to work as expected without the legacy wordy manual parser.
