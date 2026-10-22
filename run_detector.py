#!/usr/bin/env python3
"""Easy launcher: scan videos in ./mp4 and write results to ./output."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
VIDEO_FOLDER = ROOT / "mp4"
OUTPUT_FOLDER = ROOT / "output"
SCRIPT = ROOT / "video_defect_detector.py"

def main():
    VIDEO_FOLDER.mkdir(exist_ok=True)
    if not any(p.is_file() and p.suffix.lower() == ".mp4" for p in VIDEO_FOLDER.rglob("*")):
        print("No MP4 videos found.")
        print(f"Put your MP4 files inside this folder:\n  {VIDEO_FOLDER}")
        print("You can also put videos into subfolders inside mp4/.")
        input("\nPress Enter to exit...")
        return 1

    cmd = [sys.executable, str(SCRIPT), str(VIDEO_FOLDER), "--output", str(OUTPUT_FOLDER)]
    print(f"Videos folder: {VIDEO_FOLDER}")
    print(f"Reports folder: {OUTPUT_FOLDER}")
    print("\nStarting scan...\n")
    result = subprocess.run(cmd)
    print("\nFinished. Results are saved in the output folder.")
    input("Press Enter to close...")
    return result.returncode

if __name__ == "__main__":
    raise SystemExit(main())
