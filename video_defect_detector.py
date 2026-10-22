#!/usr/bin/env python3
"""
MP4 Video Defect Detector
Scans a folder recursively for MP4 files and flags:
  - unexpected black bars on left/right or top/bottom
  - near-completely black frames / black flashes
  - changes in detected black-border geometry compared with neighboring frames

Outputs:
  - report.csv
  - evidence/*.jpg (annotated frames)
  - contact_sheet.jpg (all incidents, when any are found)

Requires: Python 3.10+, opencv-python, numpy, Pillow

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python video_defect_detector.py
"""
from __future__ import annotations

import argparse
import csv
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass
class FrameResult:
    frame_idx: int
    time_s: float
    width: int
    height: int
    left: int
    right: int
    top: int
    bottom: int
    black_fraction: float
    full_black: bool
    border_detected: bool
    signature: tuple[int, int, int, int]


@dataclass
class Incident:
    video: Path
    start_s: float
    end_s: float
    kind: str
    confidence: str
    details: str
    evidence: Path
    frame_idx: int


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def frame_metrics(frame: np.ndarray, args) -> dict:
    """Estimate black edge runs and whole-frame blackness from grayscale pixels."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # A pixel counts as near-black only below this threshold. A small tolerance
    # handles compression noise, but raise it cautiously to avoid dark scenes.
    black = gray <= args.black_threshold
    black_fraction = float(np.mean(black))
    full_black = black_fraction >= args.full_black_fraction

    # Evaluate edge strips, excluding corners so a dark scene doesn't trigger
    # just because the corner pixels are dark.
    x0, x1 = int(w * 0.20), int(w * 0.80)
    y0, y1 = int(h * 0.20), int(h * 0.80)
    min_run_x = max(2, int(w * args.min_bar_fraction))
    min_run_y = max(2, int(h * args.min_bar_fraction))
    edge_black_fraction = args.edge_black_fraction

    def row_is_bar(y: int) -> bool:
        return float(np.mean(black[y, x0:x1])) >= edge_black_fraction

    def col_is_bar(x: int) -> bool:
        return float(np.mean(black[y0:y1, x])) >= edge_black_fraction

    top = 0
    while top < int(h * args.max_bar_fraction) and row_is_bar(top):
        top += 1
    bottom = 0
    while bottom < int(h * args.max_bar_fraction) and row_is_bar(h - 1 - bottom):
        bottom += 1
    left = 0
    while left < int(w * args.max_bar_fraction) and col_is_bar(left):
        left += 1
    right = 0
    while right < int(w * args.max_bar_fraction) and col_is_bar(w - 1 - right):
        right += 1

    # Reject tiny edge runs and normalize them to zero.
    if top < min_run_y:
        top = 0
    if bottom < min_run_y:
        bottom = 0
    if left < min_run_x:
        left = 0
    if right < min_run_x:
        right = 0

    border_detected = any((left, right, top, bottom))
    return {
        "left": left, "right": right, "top": top, "bottom": bottom,
        "black_fraction": black_fraction, "full_black": full_black,
        "border_detected": border_detected,
        "signature": (left, right, top, bottom),
    }


def annotate(frame: np.ndarray, metrics: dict, label: str) -> np.ndarray:
    image = frame.copy()
    h, w = image.shape[:2]
    color = (0, 80, 255)
    thickness = max(2, min(w, h) // 300)
    left, right, top, bottom = (metrics[k] for k in ("left", "right", "top", "bottom"))
    if left:
        cv2.rectangle(image, (0, 0), (left, h - 1), color, thickness)
    if right:
        cv2.rectangle(image, (w - right, 0), (w - 1, h - 1), color, thickness)
    if top:
        cv2.rectangle(image, (0, 0), (w - 1, top), color, thickness)
    if bottom:
        cv2.rectangle(image, (0, h - bottom), (w - 1, h - 1), color, thickness)
    overlay_h = min(72, max(40, h // 10))
    cv2.rectangle(image, (0, 0), (w, overlay_h), (20, 20, 20), -1)
    cv2.putText(image, label[:150], (12, min(28, overlay_h - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, max(0.45, min(0.8, w / 1400)),
                (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(image, f"black={metrics['black_fraction']:.1%} bars L/R/T/B="
                f"{left}/{right}/{top}/{bottom}",
                (12, min(overlay_h - 8, 52)), cv2.FONT_HERSHEY_SIMPLEX,
                max(0.4, min(0.65, w / 1600)), (0, 220, 255), 1, cv2.LINE_AA)
    return image


def sample_video(video: Path, args, evidence_dir: Path) -> list[Incident]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"[WARN] Could not open: {video}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or not math.isfinite(fps) or fps <= 0:
        fps = 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if frame_count > 0 else 0.0
    step = max(1, int(round(fps / args.sample_fps)))
    results: list[FrameResult] = []
    frame_idx = 0
    print(f"[SCAN] {video} ({duration:.1f}s, {fps:.2f} fps; sample every {step} frame(s))")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step == 0:
            t = frame_idx / fps
            m = frame_metrics(frame, args)
            h, w = frame.shape[:2]
            results.append(FrameResult(
                frame_idx, t, w, h, m["left"], m["right"], m["top"], m["bottom"],
                m["black_fraction"], m["full_black"], m["border_detected"], m["signature"]
            ))
        frame_idx += 1
    cap.release()

    if not results:
        return []

    # Establish a baseline border signature from the most common sampled geometry.
    # This helps distinguish persistent/intentional letterboxing from bars that appear
    # only in a portion of the video.
    from collections import Counter
    sig_counts = Counter(r.signature for r in results if not r.full_black)
    baseline = sig_counts.most_common(1)[0][0] if sig_counts else (0, 0, 0, 0)

    flags: list[tuple[FrameResult, str, str, str]] = []
    for i, r in enumerate(results):
        prev_r = results[i - 1] if i > 0 else None
        next_r = results[i + 1] if i + 1 < len(results) else None

        if r.full_black:
            # Only flag black flashes, not an all-black video or long black intro/outro.
            neighbors_nonblack = sum(
                n is not None and not n.full_black
                for n in (prev_r, next_r)
            )
            if neighbors_nonblack:
                flags.append((r, "Black frame / flash", "Medium",
                              f"{r.black_fraction:.1%} of pixels are near-black; inspect for intentional transition"))
            continue

        # A border is suspicious when its geometry differs from the common baseline,
        # especially if it appears only in one/few sampled frames.
        sig = r.signature
        if sig != baseline and r.border_detected:
            # Avoid flagging normal bars present throughout the video.
            neighboring_baseline = any(
                n is not None and n.signature == baseline
                for n in (prev_r, next_r)
            )
            duration_hint = "border geometry differs from video baseline"
            if neighboring_baseline:
                flags.append((r, "Unexpected black bars", "High", duration_hint))
            else:
                flags.append((r, "Black bars (review)", "Low", duration_hint))
        # A strong geometry jump from adjacent frames can indicate a clip aspect change.
        if prev_r is not None and sig != prev_r.signature:
            delta = sum(abs(a - b) for a, b in zip(sig, prev_r.signature))
            threshold = max(8, int(min(r.width, r.height) * args.geometry_change_fraction))
            if delta >= threshold and (r.border_detected or prev_r.border_detected):
                flags.append((r, "Border/aspect change", "Medium",
                              f"border measurement changed by {delta}px from previous sample"))

    if not flags:
        return []

    # Merge flags of same kind that occur within the configured gap.
    flags.sort(key=lambda item: item[0].time_s)
    groups: list[list[tuple[FrameResult, str, str, str]]] = []
    for flag in flags:
        r, kind, confidence, details = flag
        if groups and groups[-1][-1][1] == kind and (
            r.time_s - groups[-1][-1][0].time_s <= args.merge_gap
        ):
            groups[-1].append(flag)
        else:
            groups.append([flag])

    incidents: list[Incident] = []
    safe_stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in video.stem)
    for number, group in enumerate(groups, 1):
        first = group[0][0]
        last = group[-1][0]
        kinds = list(dict.fromkeys(x[1] for x in group))
        kind = kinds[0] if len(kinds) == 1 else " / ".join(kinds)
        confidence_order = {"High": 3, "Medium": 2, "Low": 1}
        confidence = max((x[2] for x in group), key=lambda c: confidence_order[c])
        details = "; ".join(dict.fromkeys(x[3] for x in group))
        evidence_path = evidence_dir / f"{safe_stem}_{number:04d}_{first.time_s:.3f}s.jpg"
        # Re-read exact first flagged frame for high-quality evidence.
        cap = cv2.VideoCapture(str(video))
        cap.set(cv2.CAP_PROP_POS_FRAMES, first.frame_idx)
        ok, frame = cap.read()
        cap.release()
        if ok:
            m = {
                "left": first.left, "right": first.right, "top": first.top, "bottom": first.bottom,
                "black_fraction": first.black_fraction
            }
            label = f"{video.name} | {fmt_time(first.time_s)} | {kind}"
            cv2.imwrite(str(evidence_path), annotate(frame, m, label), [cv2.IMWRITE_JPEG_QUALITY, 92])
        else:
            evidence_path = Path("")
        incidents.append(Incident(video, first.time_s, last.time_s, kind, confidence,
                                  details, evidence_path, first.frame_idx))
    return incidents


def make_contact_sheet(incidents: list[Incident], output: Path, thumb_w: int = 360,
                       thumb_h: int = 220, columns: int = 3) -> None:
    valid = [i for i in incidents if i.evidence and i.evidence.exists()]
    if not valid:
        return
    rows = math.ceil(len(valid) / columns)
    label_h = 48
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    for idx, incident in enumerate(valid):
        x = (idx % columns) * thumb_w
        y = (idx // columns) * (thumb_h + label_h)
        with Image.open(incident.evidence) as im:
            im = im.convert("RGB")
            im.thumbnail((thumb_w, thumb_h))
            sheet.paste(im, (x, y))
        label = f"{incident.video.name[:42]}\n{fmt_time(incident.start_s)}–{fmt_time(incident.end_s)} | {incident.kind}"
        draw.text((x + 5, y + thumb_h + 4), label, fill="black", font=font)
    sheet.save(output, quality=90)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect possible black bars and black flashes in MP4 videos.")
    parser.add_argument("input_folder", nargs="?", default="mp4", help="Folder containing MP4 files (default: ./mp4)")
    parser.add_argument("-o", "--output", default="output", help="Output directory (default: ./output)")
    parser.add_argument("--sample-fps", type=float, default=2.0, help="Frames inspected per second (default: 2; use 5-10 for short defects)")
    parser.add_argument("--black-threshold", type=int, default=18, help="Grayscale value 0-255 considered near-black (default: 18)")
    parser.add_argument("--edge-black-fraction", type=float, default=0.96, help="Fraction of edge strip pixels that must be black (default: 0.96)")
    parser.add_argument("--full-black-fraction", type=float, default=0.985, help="Whole-frame near-black fraction to count as black (default: 0.985)")
    parser.add_argument("--min-bar-fraction", type=float, default=0.012, help="Minimum bar width/height as fraction of frame (default: 0.012)")
    parser.add_argument("--max-bar-fraction", type=float, default=0.30, help="Maximum edge bar search depth as fraction of frame (default: 0.30)")
    parser.add_argument("--geometry-change-fraction", type=float, default=0.015, help="Border geometry change threshold relative to shorter dimension")
    parser.add_argument("--merge-gap", type=float, default=2.0, help="Merge same-kind detections within this many seconds (default: 2)")
    parser.add_argument("--include-hidden", action="store_true", help="Include hidden folders/files")
    args = parser.parse_args()

    if not 0 <= args.black_threshold <= 255:
        parser.error("--black-threshold must be between 0 and 255")
    if args.sample_fps <= 0:
        parser.error("--sample-fps must be greater than 0")
    root = Path(args.input_folder).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Input folder does not exist or is not a directory: {root}")
    output = Path(args.output).expanduser().resolve()
    evidence_dir = output / "evidence"
    output.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    videos = [
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() == ".mp4"
        and (args.include_hidden or not any(part.startswith(".") for part in p.relative_to(root).parts))
    ]
    videos.sort()
    if not videos:
        print(f"No MP4 files found under {root}")
        return 0

    incidents: list[Incident] = []
    for video in videos:
        try:
            incidents.extend(sample_video(video, args, evidence_dir))
        except Exception as exc:
            print(f"[ERROR] {video}: {exc}")

    report = output / "report.csv"
    with report.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["video", "start_timestamp", "end_timestamp", "start_seconds", "end_seconds",
                         "issue_type", "confidence", "details", "evidence_screenshot"])
        for i in incidents:
            writer.writerow([
                str(i.video), fmt_time(i.start_s), fmt_time(i.end_s),
                f"{i.start_s:.3f}", f"{i.end_s:.3f}", i.kind, i.confidence,
                i.details, str(i.evidence) if i.evidence else ""
            ])

    sheet = output / "contact_sheet.jpg"
    make_contact_sheet(incidents, sheet)
    print("\n=== Scan complete ===")
    print(f"Videos scanned: {len(videos)}")
    print(f"Incidents flagged: {len(incidents)}")
    print(f"CSV report: {report}")
    print(f"Evidence screenshots: {evidence_dir}")
    print(f"Contact sheet: {sheet if sheet.exists() else 'not created (no evidence screenshots)'}")
    print("\nReview flagged items manually; these are potential defects, not guaranteed errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
