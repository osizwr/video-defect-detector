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
python -m pip install -r requirements.txt
```

## First-time setup (Windows)

Install Python from [python.org](https://www.python.org/downloads/windows/). During installation, select **Add python.exe to PATH**.

Open PowerShell in this project folder and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks the activation script, allow locally created scripts for your user account, then activate the environment again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

If you are using Command Prompt instead of PowerShell, use these equivalent commands:

```bat
py -3 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
```

## Every time you want to scan

1. Put MP4 files in the `mp4` folder (subfolders are also searched).
2. Open Terminal (Mac), PowerShell, or Command Prompt (Windows) in the project folder.
3. Activate the environment:

   **Mac:**
```bash
source .venv/bin/activate
```

   **Windows PowerShell:**
```powershell
.\.venv\Scripts\Activate.ps1
```

   **Windows Command Prompt:**
```bat
.venv\Scripts\activate.bat
```

4. Run:

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
