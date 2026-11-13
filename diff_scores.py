#!/usr/bin/env python3
"""diff_scores.py - Compare two musical scores using musicdiff and audio settings diffing.

Accepts MuseScore files (.mscz, .mscx) or MusicXML files (.musicxml, .xml).
If MuseScore files are provided, they are automatically exported to MusicXML for
notation diffing, and their embedded `audiosettings.json` files are compared to
detect soundfont, preset, mixer, and FX changes.

Usage Examples:
    # Print notation + audio/soundfont diffs directly to the console:
    $ python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --text

    # Compare only MuseScore audio/soundfont settings (fast, skips MusicXML export):
    $ python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --audio-only

    # Generate annotated comparison PDFs (saved to ./diffs/ by default):
    $ python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --pdf

    # Custom PDF output paths:
    $ python3 diff_scores.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --pdf diff1.pdf diff2.pdf
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import music21 as m21
from musicdiff import DetailLevel, diff

from extract_score import export_musicxml, extract_audio_settings, find_musescore_binary


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


def _try_load_audio_settings(score_path: Path) -> Optional[Dict[str, Any]]:
    """Loads audiosettings.json for MuseScore inputs, or None for non-MuseScore formats."""
    if not score_path.is_file():
        raise FileNotFoundError(f"Score file not found: {score_path}")
    if score_path.suffix.lower() not in (".mscz", ".mscx"):
        return None
    data = extract_audio_settings(score_path)
    return data or None


def _diff_values(val1: Any, val2: Any, prefix: str = "") -> List[Tuple[str, Any, Any]]:
    """Recursively compares two JSON values and returns (path, old_val, new_val) tuples."""
    if val1 == val2:
        return []

    if isinstance(val1, dict) and isinstance(val2, dict):
        diffs: List[Tuple[str, Any, Any]] = []
        for key in sorted(set(val1) | set(val2)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in val1:
                diffs.append((path, None, val2[key]))
            elif key not in val2:
                diffs.append((path, val1[key], None))
            else:
                diffs.extend(_diff_values(val1[key], val2[key], path))
        return diffs

    if isinstance(val1, list) and isinstance(val2, list):
        diffs = []
        common_len = min(len(val1), len(val2))
        for idx in range(common_len):
            diffs.extend(_diff_values(val1[idx], val2[idx], f"{prefix}[{idx}]"))
        for idx in range(common_len, len(val1)):
            diffs.append((f"{prefix}[{idx}]", val1[idx], None))
        for idx in range(common_len, len(val2)):
            diffs.append((f"{prefix}[{idx}]", None, val2[idx]))
        return diffs

    return [(prefix, val1, val2)]


def _index_tracks(tracks: List[Dict[str, Any]]) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    """Indexes track entries by (partId, instrumentId, occurrence) for order-independent diffing."""
    counts: Dict[Tuple[str, str], int] = defaultdict(int)
    indexed: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for track in tracks:
        base_key = (str(track.get("partId", "")), str(track.get("instrumentId", "")))
        occ = counts[base_key]
        counts[base_key] += 1
        indexed[(base_key[0], base_key[1], occ)] = track
    return indexed


def _format_track_label(key: Tuple[str, str, int]) -> str:
    part_id, inst_id, occ = key
    label = f"part {part_id or '?'} ({inst_id or 'unknown'})"
    return f"{label} #{occ + 1}" if occ > 0 else label


def _summarize_track_soundfont(track: Dict[str, Any]) -> str:
    """Formats a track's input resourceMeta / soundfont configuration concisely."""
    res_meta = (track.get("in") or {}).get("resourceMeta") or {}
    attrs = res_meta.get("attributes") or {}
    parts: List[str] = []
    if res_meta.get("vendor") or res_meta.get("type"):
        parts.append("/".join(x for x in (res_meta.get("vendor"), res_meta.get("type")) if x))
    if attrs.get("soundFontName"):
        parts.append(f"soundFont={attrs['soundFontName']!r}")
    if attrs.get("presetName"):
        parts.append(f"preset={attrs['presetName']!r}")
    if attrs.get("presetBank") is not None or attrs.get("presetProgram") is not None:
        parts.append(f"bank={attrs.get('presetBank')}, program={attrs.get('presetProgram')}")
    if not parts and res_meta.get("id"):
        parts.append(f"id={res_meta['id']!r}")
    return " | ".join(parts) or "(no soundfont metadata)"


def diff_audio_settings(score1: Path | str, score2: Path | str) -> Dict[str, Any]:
    """Compares MuseScore audiosettings.json (soundfonts, presets, mixer, FX) between two scores."""
    p1, p2 = Path(score1), Path(score2)
    audio1 = _try_load_audio_settings(p1)
    audio2 = _try_load_audio_settings(p2)

    if audio1 is None or audio2 is None:
        missing = [p.name for p, a in ((p1, audio1), (p2, audio2)) if a is None]
        return {
            "available": False,
            "reason": f"audiosettings.json not present for: {', '.join(missing)}",
            "global_changes": [],
            "track_changes": [],
            "soundfont_changes": [],
            "mixer_changes": [],
            "total_changes": 0,
        }

    global_changes: List[Dict[str, Any]] = []
    for key in sorted((set(audio1) | set(audio2)) - {"tracks"}):
        for path, old_val, new_val in _diff_values(audio1.get(key), audio2.get(key), key):
            global_changes.append({"field": path, "old": old_val, "new": new_val})

    tracks1 = _index_tracks(audio1.get("tracks") or [])
    tracks2 = _index_tracks(audio2.get("tracks") or [])

    track_changes: List[Dict[str, Any]] = []
    soundfont_changes: List[Dict[str, Any]] = []
    mixer_changes: List[Dict[str, Any]] = []

    for key in sorted(set(tracks1) | set(tracks2)):
        label = _format_track_label(key)
        if key not in tracks1:
            track_changes.append({
                "op": "added",
                "track": label,
                "partId": key[0],
                "instrumentId": key[1],
                "soundfont": _summarize_track_soundfont(tracks2[key]),
            })
            continue
        if key not in tracks2:
            track_changes.append({
                "op": "removed",
                "track": label,
                "partId": key[0],
                "instrumentId": key[1],
                "soundfont": _summarize_track_soundfont(tracks1[key]),
            })
            continue

        t1, t2 = tracks1[key], tracks2[key]
        for path, old_val, new_val in _diff_values(t1.get("in"), t2.get("in"), "in"):
            soundfont_changes.append({
                "track": label,
                "partId": key[0],
                "instrumentId": key[1],
                "field": path,
                "old": old_val,
                "new": new_val,
            })

        for subk in sorted((set(t1) | set(t2)) - {"in", "partId", "instrumentId"}):
            for path, old_val, new_val in _diff_values(t1.get(subk), t2.get(subk), subk):
                mixer_changes.append({
                    "track": label,
                    "partId": key[0],
                    "instrumentId": key[1],
                    "field": path,
                    "old": old_val,
                    "new": new_val,
                })

    total = len(global_changes) + len(track_changes) + len(soundfont_changes) + len(mixer_changes)
    return {
        "available": True,
        "global_changes": global_changes,
        "track_changes": track_changes,
        "soundfont_changes": soundfont_changes,
        "mixer_changes": mixer_changes,
        "total_changes": total,
    }


def format_audio_diff(audio_diff: Dict[str, Any]) -> str:
    """Formats an audio-settings diff dictionary into a human-readable report."""
    if not audio_diff.get("available"):
        return f"Audio settings diff skipped ({audio_diff.get('reason', 'unavailable')})."

    if audio_diff["total_changes"] == 0:
        return "Audio settings & soundfonts are identical (0 changes)."

    lines: List[str] = [f"Audio Settings / Soundfont Diff ({audio_diff['total_changes']} change(s)):"]
    if audio_diff["soundfont_changes"]:
        lines.append("  Soundfont / Preset changes:")
        for ch in audio_diff["soundfont_changes"]:
            lines.append(f"    ~ {ch['track']} {ch['field']}: {ch['old']!r} -> {ch['new']!r}")

    if audio_diff["track_changes"]:
        lines.append("  Track audio additions / removals:")
        for ch in audio_diff["track_changes"]:
            sign = "+" if ch["op"] == "added" else "-"
            lines.append(f"    {sign} {ch['track']}: {ch['soundfont']}")

    if audio_diff["global_changes"]:
        lines.append("  Global / Sound Profile / Master / Aux changes:")
        for ch in audio_diff["global_changes"]:
            lines.append(f"    ~ {ch['field']}: {ch['old']!r} -> {ch['new']!r}")

    if audio_diff["mixer_changes"]:
        lines.append("  Track mixer / FX / mute-solo changes:")
        for ch in audio_diff["mixer_changes"]:
            lines.append(f"    ~ {ch['track']} {ch['field']}: {ch['old']!r} -> {ch['new']!r}")

    return "\n".join(lines)


def run_diff(
    score1: Path | str,
    score2: Path | str,
    pdf_paths: Optional[Tuple[Path, Path]] = None,
    print_text: bool = False,
    cache_dir: Path = Path("./extracted"),
    detail: DetailLevel | int = DetailLevel.Default,
    include_audio: bool = True,
) -> Optional[int]:
    """Runs musicdiff (and optionally audiosettings.json diff) between two score files."""
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

    if include_audio:
        audio_diff = diff_audio_settings(score1_p, score2_p)
        if print_text or audio_diff["total_changes"] > 0:
            print("\n" + format_audio_diff(audio_diff))

    return num_diffs


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two musical scores (.mscz, .mscx, or .musicxml) with musicdiff and audio settings diff.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("score1", type=Path, help="Path to first score file")
    parser.add_argument("score2", type=Path, help="Path to second score file")

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="Print text diff of musical and audio/soundfont differences to stdout",
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
    mode_group.add_argument(
        "-a",
        "--audio-only",
        action="store_true",
        help="Compare only MuseScore audiosettings.json (soundfonts, presets, mixer, FX; skips musicdiff)",
    )

    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Skip comparing MuseScore audiosettings.json during --text or --pdf diffs",
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

    if args.audio_only:
        try:
            audio_diff = diff_audio_settings(args.score1, args.score2)
        except Exception as exc:
            print(f"Diff Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(format_audio_diff(audio_diff))
        return

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
            include_audio=not args.no_audio,
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
