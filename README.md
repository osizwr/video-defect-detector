# MP4 Video Defect Detector

## Simple folder setup

Keep this structure:

```text
mp4_video_defect_detector/
├── mp4/                         <- Put your MP4 videos here
├── output/                      <- Reports are saved here automatically
├── video_defect_detector.py
├── requirements.txt
└── README.md
```

## First-time setup (Mac)

Open Terminal in this project folder and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Every time you want to scan

1. Put MP4 files in the `mp4` folder (subfolders are also searched).
2. Open Terminal in the project folder.
3. Activate the environment if you are using one:

```bash
source .venv/bin/activate
```

4. Run exactly:

```bash
python video_defect_detector.py
```

The script automatically reads videos from `./mp4` and saves results in `./output`. No paths or extra arguments are required.

## Output files

- `output/report.csv` — timestamps and suspected issue types
- `output/evidence/` — annotated screenshots
- `output/contact_sheet.jpg` — overview of flagged incidents

The source videos are not modified. Results are potential defects and should be reviewed manually.

## Optional: more thorough scan

To inspect more frames per second:

```bash
python video_defect_detector.py --sample-fps 5
```

## False positives

- Persistent black bars are compared with the most common border geometry in the video, which helps avoid flagging intentional letterboxing.
- Very dark scenes and intentional fade-to-black transitions can still be flagged. Review the evidence screenshots.
- The default scan samples 2 frames per second. Increase `--sample-fps` to 5 or more to better catch brief defects.
