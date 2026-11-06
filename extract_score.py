#!/usr/bin/env python3
"""extract_score.py - Extract MusicXML and metadata from MuseScore files (.mscz / .mscx).

Provides both a CLI and Python API to:
  1. Extract rich score metadata (title, composer, parts, instrumentation, MIDI)
     directly from the .mscz zip archive in pure Python (no external dependencies).
  2. Export clean, standard MusicXML using the MuseScore CLI.

Usage Examples:
    # Extract both MusicXML and metadata JSON:
    $ python3 extract_score.py msczs/tbd-ss-8-12.mscz

    # Extract metadata only (fast, pure Python, printed to console):
    $ python3 extract_score.py msczs/tbd-ss-8-12.mscz --meta-only --print-meta

    # Specify custom output paths:
    $ python3 extract_score.py msczs/tbd-ss-8-12.mscz -o score.musicxml -m meta.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def find_musescore_binary() -> Optional[str]:
    """Find available MuseScore executable across Linux, WSL, macOS, and Windows."""
    # 1. Search PATH and local user bin
    candidates = ["mscore", "musescore", "musescore4", "musescore3"]
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found

    user_local = Path.home() / ".local" / "bin" / "mscore"
    if user_local.is_file() and os.access(user_local, os.X_OK):
        return str(user_local)

    # 2. Windows / WSL standard install paths
    win_paths = [
        Path("/mnt/c/Program Files/MuseScore 4/bin/MuseScore4.exe"),
        Path("/mnt/c/Program Files/MuseScore 3/bin/MuseScore3.exe"),
        Path("C:/Program Files/MuseScore 4/bin/MuseScore4.exe"),
        Path("C:/Program Files/MuseScore 3/bin/MuseScore3.exe"),
    ]
    for wp in win_paths:
        if wp.is_file():
            return str(wp)

    # 3. macOS standard application bundles
    mac_paths = [
        Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore"),
        Path("/Applications/MuseScore 3.app/Contents/MacOS/mscore"),
    ]
    for mp in mac_paths:
        if mp.is_file():
            return str(mp)

    return None


def _to_cli_path(file_path: Path, is_win_binary: bool) -> str:
    """Converts Linux path to Windows format if running a Windows binary under WSL."""
    abs_str = str(file_path.resolve())
    if is_win_binary and abs_str.startswith("/") and shutil.which("wslpath"):
        res = subprocess.run(["wslpath", "-w", abs_str], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    return abs_str


def parse_mscx_element_tree(score_path: Path) -> ET.Element:
    """Parses root XML Element from either a .mscz zip archive or a .mscx file."""
    if not score_path.is_file():
        raise FileNotFoundError(f"File not found: {score_path}")

    if score_path.suffix.lower() == ".mscz":
        with zipfile.ZipFile(score_path, "r") as archive:
            mscx_names = [n for n in archive.namelist() if n.endswith(".mscx")]
            if not mscx_names:
                raise ValueError(f"No .mscx file found inside {score_path.name}")
            xml_data = archive.read(mscx_names[0])
            return ET.fromstring(xml_data)
    elif score_path.suffix.lower() == ".mscx":
        return ET.parse(score_path).getroot()
    else:
        raise ValueError(f"Unsupported format '{score_path.suffix}'. Expected .mscz or .mscx.")


def extract_metadata(score_path: Path | str) -> Dict[str, Any]:
    """Extracts score properties and full instrumentation metadata in pure Python."""
    score_path = Path(score_path)
    root = parse_mscx_element_tree(score_path)
    score_el = root.find("Score") if root.find("Score") is not None else root

    # Extract general metaTags
    meta: Dict[str, Any] = {}
    for meta_tag in score_el.findall("metaTag"):
        name = meta_tag.get("name")
        val = (meta_tag.text or "").strip()
        if name and val:
            meta[name] = val

    # Measure count
    staves = score_el.findall("Staff")
    if staves:
        measures = staves[0].findall("Measure")
        meta["measureCount"] = len(measures)

    # Extract instrumentation & parts
    instruments: List[Dict[str, Any]] = []
    for part in score_el.findall("Part"):
        part_info: Dict[str, Any] = {
            "partId": part.get("id"),
            "trackName": (part.findtext("trackName") or "").strip(),
        }
        inst = part.find("Instrument")
        if inst is not None:
            part_info.update({
                "instrumentId": (inst.get("id") or inst.findtext("instrumentId") or "").strip(),
                "longName": (inst.findtext("longName") or "").strip(),
                "shortName": (inst.findtext("shortName") or "").strip(),
                "clef": (inst.findtext("clef") or "").strip(),
            })
            channel = inst.find("Channel")
            if channel is not None:
                prog = channel.find("program")
                part_info["midiChannel"] = channel.findtext("midiChannel")
                part_info["midiProgram"] = prog.get("value") if prog is not None else None
                part_info["synthesizer"] = channel.findtext("synti")

        instruments.append(part_info)

    return {
        "file": score_path.name,
        "metadata": meta,
        "instrumentation": instruments,
    }


def export_musicxml(score_path: Path | str, output_path: Optional[Path | str] = None) -> Path:
    """Exports .mscz / .mscx to standard MusicXML using MuseScore CLI."""
    score_path = Path(score_path)
    if not score_path.is_file():
        raise FileNotFoundError(f"Input score file not found: {score_path}")

    if output_path is None:
        output_path = score_path.with_suffix(".musicxml")
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    musescore_bin = find_musescore_binary()
    if not musescore_bin:
        raise RuntimeError(
            "MuseScore CLI binary not found. Please ensure MuseScore is installed."
        )

    is_win_exe = musescore_bin.lower().endswith(".exe")
    in_arg = _to_cli_path(score_path, is_win_exe)
    out_arg = _to_cli_path(output_path, is_win_exe)

    cmd = [musescore_bin, "-o", out_arg, in_arg]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0 or not output_path.is_file():
        err_msg = result.stderr.strip() or result.stdout.strip() or f"Process exited with {result.returncode}"
        raise RuntimeError(f"MuseScore conversion failed: {err_msg}")

    return output_path


def extract_score(
    score_path: Path | str,
    output_xml: Optional[Path | str] = None,
    output_json: Optional[Path | str] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """Convenience helper that extracts both MusicXML and metadata."""
    score_path = Path(score_path)
    metadata = extract_metadata(score_path)
    musicxml_path = export_musicxml(score_path, output_xml)

    if output_json is not None:
        json_path = Path(output_json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

    return musicxml_path, metadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract MusicXML and metadata from MuseScore files (.mscz / .mscx)."
    )
    parser.add_argument("score", type=Path, help="Path to .mscz or .mscx score file")
    parser.add_argument("-o", "--output-xml", type=Path, help="Destination .musicxml path")
    parser.add_argument("-m", "--metadata-out", type=Path, help="Destination .json path for metadata")
    parser.add_argument("--print-meta", action="store_true", help="Print extracted metadata JSON to stdout")
    parser.add_argument("--meta-only", action="store_true", help="Only extract metadata (skip MusicXML export)")
    parser.add_argument("--xml-only", action="store_true", help="Only export MusicXML (skip saving metadata JSON)")

    args = parser.parse_args()

    # 1. Extract metadata
    metadata = extract_metadata(args.score)

    if args.print_meta or args.meta_only:
        print(json.dumps(metadata, indent=2))

    # Save metadata JSON if requested (or default if not xml-only)
    if not args.xml_only and args.metadata_out is not None:
        with open(args.metadata_out, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        print(f"Saved metadata JSON to: {args.metadata_out}")

    # 2. Export MusicXML
    if not args.meta_only:
        out_xml = args.output_xml or args.score.with_suffix(".musicxml")
        exported = export_musicxml(args.score, out_xml)
        print(f"Exported MusicXML to: {exported}")


if __name__ == "__main__":
    main()
