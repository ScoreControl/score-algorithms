#!/usr/bin/env python3
"""diff_scores.py - Compare two musical scores using musicdiff (text or PDF output).

Accepts MuseScore files (.mscz, .mscx) or MusicXML files (.musicxml, .xml).
If MuseScore files are provided, they are automatically exported to MusicXML.

Usage Examples:
    # Print notation diffs directly to the console:
    $ python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --text

    # Generate annotated comparison PDFs (saved to ./diffs/ by default):
    $ python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --pdf

    # Custom PDF output paths:
    $ python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --pdf diff1.pdf diff2.pdf
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, Tuple

import music21 as m21
from musicdiff import DetailLevel, diff

from extract_score import export_musicxml, find_musescore_binary


def _configure_music21_musescore() -> None:
    """Configures music21 to use the detected MuseScore executable for PDF rendering."""
    musescore_bin = find_musescore_binary()
    if musescore_bin:
        env = m21.environment.Environment()
        env["musescoreDirectPNGPath"] = musescore_bin
        env["musicxmlPath"] = musescore_bin


def resolve_to_musicxml(score_path: Path, cache_dir: Path) -> Path:
    """Returns path to a MusicXML file, converting .mscz/.mscx if necessary."""
    if not score_path.is_file():
        raise FileNotFoundError(f"Score file not found: {score_path}")

    suffix = score_path.suffix.lower()
    if suffix in (".musicxml", ".xml", ".mxl"):
        return score_path

    if suffix in (".mscz", ".mscx"):
        cache_dir.mkdir(parents=True, exist_ok=True)
        xml_path = cache_dir / f"{score_path.stem}.musicxml"
        if not xml_path.is_file() or xml_path.stat().st_mtime < score_path.stat().st_mtime:
            print(f"Converting '{score_path.name}' to MusicXML...")
            export_musicxml(score_path, xml_path)
        return xml_path

    raise ValueError(f"Unsupported score format '{suffix}'. Supported: .mscz, .mscx, .musicxml, .xml")


def run_diff(
    score1: Path | str,
    score2: Path | str,
    pdf_paths: Optional[Tuple[Path, Path]] = None,
    print_text: bool = False,
    cache_dir: Path = Path("./extracted"),
    detail: DetailLevel | int = DetailLevel.Default,
) -> Optional[int]:
    """Runs musicdiff between two score files (auto-converts .mscz if needed)."""
    score1_p = Path(score1)
    score2_p = Path(score2)

    xml1 = resolve_to_musicxml(score1_p, cache_dir)
    xml2 = resolve_to_musicxml(score2_p, cache_dir)

    use_pdf = pdf_paths is not None
    out_p1, out_p2 = pdf_paths if use_pdf else (None, None)

    if use_pdf:
        _configure_music21_musescore()

    print(f"\nComparing '{score1_p.name}' and '{score2_p.name}' with musicdiff...")
    num_diffs = diff(
        score1=xml1,
        score2=xml2,
        out_path1=out_p1,
        out_path2=out_p2,
        visualize_diffs=use_pdf,
        print_text_output=print_text,
        detail=detail,
    )
    return num_diffs


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two musical scores (.mscz, .mscx, or .musicxml) with musicdiff.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("score1", type=Path, help="Path to first score file")
    parser.add_argument("score2", type=Path, help="Path to second score file")

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="Print text diff of musical differences to stdout",
    )
    mode_group.add_argument(
        "-p",
        "--pdf",
        nargs="*",
        metavar="PDF_PATH",
        help=(
            "Generate marked-up visual PDFs. Pass 0 arguments for default "
            "(./diffs/<score>_diff.pdf) or 2 custom file paths."
        ),
    )

    parser.add_argument(
        "-c",
        "-e",
        "--cache-dir",
        "--extract-dir",
        dest="cache_dir",
        type=Path,
        default=Path("./extracted"),
        help="Directory to cache exported .musicxml files (default: ./extracted)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    pdf_paths: Optional[Tuple[Path, Path]] = None
    if args.pdf is not None:
        if len(args.pdf) == 0:
            diffs_dir = Path("./diffs")
            diffs_dir.mkdir(parents=True, exist_ok=True)
            pdf_paths = (
                diffs_dir / f"{args.score1.stem}_diff.pdf",
                diffs_dir / f"{args.score2.stem}_diff.pdf",
            )
        elif len(args.pdf) == 2:
            p1, p2 = Path(args.pdf[0]), Path(args.pdf[1])
            p1.parent.mkdir(parents=True, exist_ok=True)
            p2.parent.mkdir(parents=True, exist_ok=True)
            pdf_paths = (p1, p2)
        else:
            print("Error: --pdf accepts either 0 arguments or exactly 2 paths.", file=sys.stderr)
            sys.exit(1)

    try:
        num_diffs = run_diff(
            score1=args.score1,
            score2=args.score2,
            pdf_paths=pdf_paths,
            print_text=args.text,
            cache_dir=args.cache_dir,
        )
    except Exception as exc:
        print(f"Diff Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if num_diffs is None:
        print("Error: musicdiff failed to compare the scores.", file=sys.stderr)
        sys.exit(1)
    elif num_diffs == 0:
        print("\nScores are identical (0 musical differences).")
    else:
        print(f"\nTotal musical differences (cost): {num_diffs}")
        if pdf_paths:
            print(f"Visual diff PDFs generated:\n  1: {pdf_paths[0]}\n  2: {pdf_paths[1]}")


if __name__ == "__main__":
    main()
