#!/usr/bin/env python3
"""Heuristic MP4 visual and audio-signal defect scanner."""
import argparse, csv, math, shutil, subprocess, tempfile, wave
from collections import Counter
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw

FIELDS = ["video","start_timestamp","end_timestamp","start_seconds","end_seconds","issue_type","confidence","details","evidence_screenshot","evidence_audio"]

def ts(x):
    x=max(0.0,float(x)); return f"{int(x//3600):02d}:{int((x%3600)//60):02d}:{x%60:06.3f}"

def mkdir(p): p.mkdir(parents=True,exist_ok=True)

def extract_audio(video, wavpath):
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg:
        print("[WARN] ffmpeg not found; skipping audio checks. Install with: brew install ffmpeg"); return False
    r=subprocess.run([ffmpeg,"-hide_banner","-loglevel","error","-y","-i",str(video),"-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(wavpath)],capture_output=True,text=True)
    if r.returncode:
        print(f"[WARN] Could not extract audio from {video.name}: {r.stderr.strip()[:250]}"); return False
    return True

def save_clip(samples,sr,start,end,dest):
    a=max(0,int(start*sr)); b=min(len(samples),int(end*sr))
    if b<=a:return False
    pcm=np.clip(samples[a:b]*32768,-32768,32767).astype("<i2")
    with wave.open(str(dest),"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
    return True

def audio_scan(video,evidence):
    with tempfile.TemporaryDirectory(prefix="defect_audio_") as td:
        wavpath=Path(td)/"audio.wav"
        if not extract_audio(video,wavpath): return []
        try:
            with wave.open(str(wavpath),"rb") as w:
                sr=w.getframerate(); channels=w.getnchannels(); width=w.getsampwidth(); raw=w.readframes(w.getnframes())
            if width!=2 or not raw:return []
            samples=np.frombuffer(raw,dtype="<i2").astype(np.float32)/32768
            if channels>1:samples=samples.reshape(-1,channels).mean(axis=1)
        except Exception as e:
            print(f"[WARN] Could not read audio for {video.name}: {e}"); return []
        dur=len(samples)/sr; win=max(1,int(sr*.02)); n=len(samples)//win
        if n<2:return []
        blocks=samples[:n*win].reshape(n,win)
        rms=np.sqrt(np.mean(blocks**2,axis=1)+1e-12); peak=np.max(np.abs(blocks),axis=1)
        rmsdb=20*np.log10(np.maximum(rms,1e-8)); peakdb=20*np.log10(np.maximum(peak,1e-8))
        rows=[]
        def add(kind,start,end,conf,details):
            end=min(dur,max(start+.02,end)); start=max(0,start)
            clip=evidence/f"{video.stem}_audio_{kind}_{start:.2f}s.wav".replace(" ","_")
            save_clip(samples,sr,max(0,start-.35),min(dur,end+.35),clip)
            rows.append(dict(video=str(video),start_timestamp=ts(start),end_timestamp=ts(end),start_seconds=round(start,3),end_seconds=round(end,3),issue_type=kind,confidence=conf,details=details,evidence_screenshot="",evidence_audio=str(clip) if clip.exists() else ""))
        # Short high peaks compared with local RMS may be clicks/pops (false positives possible).
        transient=(peakdb>-8)&((peakdb-rmsdb)>17)
        groups=[]
        for ix in np.flatnonzero(transient):
            ix=int(ix)
            if not groups or ix-groups[-1][-1]>3:groups.append([ix])
            else:groups[-1].append(ix)
        for g in groups:
            i=g[len(g)//2]; add("audio_click_or_pop",i*.02,i*.02+.04,"low","Short high-peak transient; could be a click/pop or a harmless sharp sound.")
        # Sustained near-full-scale peaks.
        clipped=peak>=.999; i=0
        while i<len(clipped):
            if not clipped[i]:i+=1;continue
            j=i+1
            while j<len(clipped) and clipped[j]:j+=1
            if j-i>=3:add("audio_clipping",i*.02,j*.02,"medium",f"Near-full-scale peaks persisted for {(j-i)*.02:.2f}s; possible clipping/distortion.")
            i=j
        # Detect one clear abrupt volume jump.
        for i in range(5,len(rmsdb)-5):
            before=float(np.median(rmsdb[i-5:i])); after=float(np.median(rmsdb[i:i+5]))
            if before>-42 and after>-42 and abs(after-before)>=24:
                add("audio_abrupt_level_change",i*.02,(i+5)*.02,"low",f"Audio level changed abruptly by about {abs(after-before):.0f} dB across adjacent 100 ms windows."); break
        return rows

def video_scan(video,evidence,sample_fps):
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():print(f"[WARN] Cannot open video: {video}");return []
    fps=cap.get(cv2.CAP_PROP_FPS) or 30.; total=cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    dur=total/fps if fps else 0; step=max(1,int(round(fps/max(sample_fps,.1))))
    print(f"[SCAN] {video} ({dur:.1f}s, {fps:.2f} fps; sample every {step} frame(s))")
    rows=[]; geometries=[]; idx=0
    while True:
        ok,frame=cap.read()
        if not ok:break
        if idx%step==0:
            h,w=frame.shape[:2]; gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            mean=float(gray.mean()); darkfrac=float(np.mean(gray<12)); sec=idx/fps
            if mean<3 or darkfrac>.985:
                shot=evidence/f"{video.stem}_black_frame_{sec:.2f}s.jpg";cv2.imwrite(str(shot),frame)
                rows.append(dict(video=str(video),start_timestamp=ts(sec),end_timestamp=ts(sec+1/max(sample_fps,1)),start_seconds=round(sec,3),end_seconds=round(sec+1/max(sample_fps,1),3),issue_type="black_or_near_black_frame",confidence="medium",details=f"Frame brightness mean={mean:.2f}; dark pixels={darkfrac:.1%}.",evidence_screenshot=str(shot),evidence_audio=""))
            dark=gray<18; rd=dark.mean(axis=1); cd=dark.mean(axis=0)
            top=0
            while top<h//4 and rd[top]>.985:top+=1
            bot=h-1
            while bot>3*h//4 and rd[bot]>.985:bot-=1
            left=0
            while left<w//4 and cd[left]>.985:left+=1
            right=w-1
            while right>3*w//4 and cd[right]>.985:right-=1
            geometries.append(((left,top,right,bot),sec,frame.copy()))
        idx+=1
    cap.release()
    if len(geometries)>=5:
        common=Counter(x[0] for x in geometries).most_common(1)[0][0]
        for g,sec,frame in geometries:
            if max(abs(g[i]-common[i]) for i in range(4))>12:
                shot=evidence/f"{video.stem}_border_change_{sec:.2f}s.jpg";cv2.imwrite(str(shot),frame)
                rows.append(dict(video=str(video),start_timestamp=ts(sec),end_timestamp=ts(sec+1/max(sample_fps,1)),start_seconds=round(sec,3),end_seconds=round(sec+1/max(sample_fps,1),3),issue_type="possible_border_or_crop_change",confidence="low",details=f"Detected dark-border geometry {g}; common geometry {common}. Verify manually.",evidence_screenshot=str(shot),evidence_audio=""))
    return rows

def make_contact_sheet(rows,out):
    imgs=[r for r in rows if r.get("evidence_screenshot") and Path(r["evidence_screenshot"]).exists()]
    if not imgs:return
    tiles=[]
    for r in imgs[:60]:
        im=Image.open(r["evidence_screenshot"]).convert("RGB"); im.thumbnail((320,180))
        tile=Image.new("RGB",(340,220),"white");tile.paste(im,((340-im.width)//2,6))
        ImageDraw.Draw(tile).text((8,190),f'{r["issue_type"]} @ {r["start_timestamp"]}',fill="black");tiles.append(tile)
    cols=3; sheet=Image.new("RGB",(cols*340,math.ceil(len(tiles)/cols)*220),"#ddd")
    for i,im in enumerate(tiles):sheet.paste(im,((i%cols)*340,(i//cols)*220))
    sheet.save(out/"contact_sheet.jpg",quality=90)

def main():
    p=argparse.ArgumentParser(description="Detect possible visual and audio-signal defects in videos.")
    p.add_argument("input",nargs="?",default="mp4",help="Input folder (default ./mp4)")
    p.add_argument("-o","--output",default="output",help="Output folder (default ./output)")
    p.add_argument("--sample-fps",type=float,default=2.,help="Video sampling rate, default 2 frames/sec")
    p.add_argument("--no-audio",action="store_true",help="Disable audio signal checks")
    a=p.parse_args(); inp=Path(a.input).expanduser().resolve();out=Path(a.output).expanduser().resolve()
    if not inp.is_dir():print(f"[ERROR] Input folder not found: {inp}");return 2
    videos=sorted(x for x in inp.iterdir() if x.is_file() and x.suffix.lower() in {".mp4",".m4v",".mov"})
    if not videos:print(f"[ERROR] No MP4/M4V/MOV videos found in {inp}");return 2
    mkdir(out); evidence=out/"evidence";mkdir(evidence);allrows=[]
    for video in videos:
        allrows.extend(video_scan(video,evidence,a.sample_fps))
        if not a.no_audio:
            print(f"[AUDIO] Checking audio signal: {video.name}")
            allrows.extend(audio_scan(video,evidence))
    with (out/"report.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore");w.writeheader();w.writerows(allrows)
    make_contact_sheet(allrows,out)
    print(f"\\n[DONE] Scanned {len(videos)} video(s). Found {len(allrows)} possible issue(s).")
    print(f"[REPORT] {out/'report.csv'}");print(f"[EVIDENCE] {evidence}")
    print("Audio checks are heuristic and can produce false positives; listen to clips to confirm.")
    return 0

if __name__=="__main__":raise SystemExit(main())
