#!/usr/bin/env python3
"""test.py - Streamlined wrapper for score diffing.

Extracts MuseScore (.mscz) files to standard MusicXML and compares them with musicdiff.
Delegates to diff_scores.py.

Usage:
    python3 test.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --text
    python3 test.py msczs/tbd-ss-8-12.mscz msczs/tbd-ss-8-16.mscz --pdf
"""

from diff_scores import main

if __name__ == "__main__":
    main()
