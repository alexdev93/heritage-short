"""Stage: assembly — FFmpeg only, no models. Deterministic: same inputs, same film.

Reads:  storyboard.json + the narration, shots and music manifests
Writes: outputs/final/film_9x16.mp4, outputs/final/film_16x9.mp4, outputs/final/subtitles_en.srt
        (--radio) outputs/radio_cut.mp4: narration + music on black, for the first user test

Steps: narration lines placed at each shot's start (+offset) -> music trimmed, faded and ducked
under the voice (sidechaincompress) -> loudness normalised to -14 LUFS / -1 dBTP -> one video
segment per shot (Wan clip reframed, or Ken Burns over the keyframe; cached per shot) -> end card
-> concat -> English subtitles burned inside the safe area -> both aspect ratios.

Usage: python -m pipeline.assemble [--radio] [--draft] [--aspect 9x16|16x9|both]
"""
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

from pipeline import common as C
from pipeline import narration as N

FPS = 24
SIZES = {"9x16": (1080, 1920), "16x9": (1920, 1080)}
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS)]
SEG_VERSION = 1  # bump to invalidate cached segments after changing the filters below
DUCK = "threshold=0.02:ratio=6:attack=300:release=1500"  # starting point from the brief; tune by ear
LOUDNORM = "loudnorm=I=-14:TP=-1:LRA=11"


# ---------- audio ----------

def voice_bed(sb: dict, narr: dict, total: float, out: Path) -> None:
    tl, _ = C.timeline(sb)
    items = [(narr[s["id"]]["path"], start + s["narration"].get("offset_s", 0.3)) for s, start in tl if s["id"] in narr]
    if not items:
        C.ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{total:.3f}", str(out))
        return
    args, chains = [], []
    for i, (path, t) in enumerate(items):
        ms = int(round(t * 1000))
        args += ["-i", path]
        chains.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(items)))
    chains.append(f"{mix}amix=inputs={len(items)}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.3f}[out]")
    C.ffmpeg(*args, "-filter_complex", ";".join(chains), "-map", "[out]", "-ar", "48000", str(out))


def mix(voice: Path, music: str, volume_db: float, total: float, out: Path) -> None:
    fade_out = max(total - 2.5, 0)
    fc = (f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.3f},asetpts=N/SR/TB,"
          f"volume={volume_db}dB,afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out:.2f}:d=2.5[m];"
          "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[v1][v2];"
          f"[m][v1]sidechaincompress={DUCK}[duck];"
          f"[duck][v2]amix=inputs=2:normalize=0,{LOUDNORM},atrim=0:{total:.3f}[out]")
    C.ffmpeg("-i", str(voice), "-stream_loop", "-1", "-i", music, "-filter_complex", fc,
             "-map", "[out]", "-ar", "48000", "-t", f"{total:.3f}", str(out))


# ---------- subtitles ----------

def subtitle_cues(sb: dict, narr: dict, width_chars: int) -> list[tuple[float, float, list[str]]]:
    """[(start, end, lines)], at most 2 lines per cue, long lines split over time by length."""
    tl, base = C.timeline(sb)
    cues = []
    for shot, start in tl:
        text = shot["narration"]["subtitle_en"].strip()
        if not text:
            continue
        t0 = start + shot["narration"].get("offset_s", 0.3)
        n = narr.get(shot["id"])
        t1 = t0 + n["duration_s"] if n else start + shot["duration_s"] - 0.2
        t1 = min(max(t1, t0 + 1.0), base)
        lines = textwrap.wrap(text, width_chars)
        chunks = [lines[i:i + 2] for i in range(0, len(lines), 2)]
        weights = [sum(len(l) for l in c) for c in chunks]
        t = t0
        for chunk, w in zip(chunks, weights):
            dt = (t1 - t0) * w / sum(weights)
            cues.append((t, t + dt, chunk))
            t += dt
    return cues


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_srt(cues, path: Path) -> None:
    blocks = [f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n" + "\n".join(lines) for i, (a, b, lines) in enumerate(cues, 1)]
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_ass(cues, path: Path, w: int, h: int, vertical: bool) -> None:
    """ASS with PlayRes = the video size, so sizes and margins are in real pixels.
    Vertical: kept well above the bottom 20% that TikTok/Reels/Shorts cover with buttons."""
    fs = round(w * 0.05) if vertical else round(h * 0.045)
    mv = round(h * 0.20) if vertical else round(h * 0.07)
    ml = round(w * 0.08)
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,DejaVu Sans,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,"
            f"{max(2, fs // 14)},1,2,{ml},{ml},{mv},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    events = []
    for a, b, lines in cues:
        text = r"\N".join(l.replace("{", "(").replace("}", ")") for l in lines)
        events.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,{text}")
    path.write_text(head + "\n".join(events) + "\n", encoding="utf-8")


# ---------- video ----------

def kenburns_filter(move: str, w: int, h: int, frames: int, fx: float) -> str:
    ar = w / h
    crop = f"crop=w='min(iw,ih*{ar:.6f})':h='min(ih,iw/{ar:.6f})':x='(iw-ow)*{fx}':y='(ih-oh)/2'"
    f, zmax = max(frames - 1, 1), 0.12
    centre_x, centre_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    z, x, y = {
        "push_in": (f"1+{zmax}*on/{f}", centre_x, centre_y),
        "pull_out": (f"{1 + zmax}-{zmax}*on/{f}", centre_x, centre_y),
        "pan_left": (f"{1 + zmax}", f"(iw-iw/zoom)*(1-on/{f})", centre_y),
        "pan_right": (f"{1 + zmax}", f"(iw-iw/zoom)*on/{f}", centre_y),
        "static": ("1", "0", "0"),
    }[move]
    return (f"{crop},scale={w * 2}:{h * 2},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS},"
            "setsar=1,format=yuv420p")


def clip_filter(w: int, h: int, fx: float, dur: float) -> str:
    return (f"fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:x='(iw-ow)*{fx}':y='(ih-oh)/2',"
            f"tpad=stop_mode=clone:stop_duration={dur:.3f},setsar=1,format=yuv420p")


def segment(shot: dict, entry: dict, w: int, h: int, segdir: Path) -> tuple[Path, bool]:
    dur = float(shot["duration_s"])
    frames = int(round(dur * FPS))
    fx = float(entry.get("crop_focus_x", 0.5))
    key = C.sha({"src": entry["hash"], "source": entry["source"], "move": entry.get("kenburns"), "fx": fx,
                 "trim": entry.get("trim_start_s", 0), "frames": frames, "w": w, "h": h, "v": SEG_VERSION})
    out = segdir / f"{shot['id']}-{key}.mp4"
    if out.exists():
        return out, False
    if entry["source"] == "clip":
        C.ffmpeg("-ss", f"{entry.get('trim_start_s', 0)}", "-i", entry["path"], "-vf", clip_filter(w, h, fx, dur),
                 "-frames:v", str(frames), "-an", *ENC, str(out))
    else:
        C.ffmpeg("-i", entry["path"], "-vf", kenburns_filter(entry.get("kenburns", "push_in"), w, h, frames, fx),
                 "-frames:v", str(frames), "-an", *ENC, str(out))
    return out, True


def _font(size: int):
    from PIL import ImageFont

    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
              "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def end_card(sb: dict, w: int, h: int, segdir: Path) -> Path:
    from PIL import Image, ImageDraw

    text, dur = sb["end_card"]["text"], float(sb["end_card"]["duration_s"])
    key = C.sha({"text": text, "dur": dur, "w": w, "h": h, "v": SEG_VERSION})
    mp4 = segdir / f"endcard-{key}.mp4"
    if mp4.exists():
        return mp4
    png = segdir / f"endcard-{key}.png"
    size = round(min(w, h) * 0.055)
    font = _font(size)
    lines = textwrap.wrap(text, max(12, int(w * 0.8 / (size * 0.55))))
    img = Image.new("RGB", (w, h), (12, 12, 12))
    draw = ImageDraw.Draw(img)
    line_h = int(size * 1.35)
    y = (h - line_h * len(lines)) // 2
    for line in lines:
        tw = draw.textlength(line, font=font)
        draw.text(((w - tw) / 2, y), line, font=font, fill=(240, 240, 240))
        y += line_h
    img.save(png)
    frames = int(round(dur * FPS))
    C.ffmpeg("-loop", "1", "-i", str(png), "-vf", f"fps={FPS},fade=t=in:st=0:d=0.6,format=yuv420p,setsar=1",
             "-frames:v", str(frames), "-an", *ENC, str(mp4))
    return mp4


def concat(parts: list[Path], out: Path) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    C.ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))


def finish(video: Path, audio: Path, subs: Path | None, out: Path) -> None:
    vf = f"subtitles=filename={C.rel(subs)}" if subs else "null"
    C.ffmpeg("-i", str(video), "-i", str(audio), "-vf", vf, "-map", "0:v", "-map", "1:a", *ENC,
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(out))


# ---------- main ----------

def run(radio: bool, draft: bool, aspects: list[str]) -> None:
    sb = C.load_storyboard(require_consent=not radio)
    tl, base = C.timeline(sb)
    total = base + float(sb["end_card"]["duration_s"])

    narr = C.Manifest(C.OUT / "narration" / "manifest.json").data
    for shot in sb["shots"]:
        if shot["narration"]["text"].strip():
            entry = narr.get(shot["id"])
            if not entry or entry["hash"] != N.cache_key(sb, shot):
                C.die(f"narration for {shot['id']} is missing or out of date; run narration first")
    music = C.Manifest(C.OUT / "music" / "manifest.json").data
    if not music:
        C.die("no music manifest; run `python -m pipeline.music build` first")

    tmp, final = C.stage_dir("tmp"), C.stage_dir("final")
    voice, mixed = tmp / "voice.wav", tmp / "mix.wav"
    voice_bed(sb, narr, total, voice)
    mix(voice, music["path"], float(music.get("volume_db", -8)), total, mixed)
    write_srt(subtitle_cues(sb, narr, 42), final / "subtitles_en.srt")
    burn = C.has_ffmpeg_filter("subtitles")
    if not burn:
        C.warn("this FFmpeg has no libass 'subtitles' filter: subtitles written to SRT but not burned in")

    if radio:
        w, h = 960, 540
        black = tmp / "black.mp4"
        C.ffmpeg("-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={FPS}:d={total:.3f}", *ENC, str(black))
        subs = tmp / "subs_radio.ass"
        write_ass(subtitle_cues(sb, narr, 42), subs, w, h, vertical=False)
        out = C.OUT / "radio_cut.mp4"
        finish(black, mixed, subs if burn else None, out)
        print(f"  ✓ radio cut: {C.rel(out)} ({C.media_duration(out):.1f}s, music: {music['source']})")
        return

    shots = C.Manifest(C.OUT / "shots" / "manifest.json").data
    missing = [s["id"] for s in sb["shots"] if s["id"] not in shots]
    if missing:
        C.die(f"no shot sources for {missing}; run `python -m pipeline.shots build` first")

    for aspect in aspects:
        w, h = SIZES[aspect]
        if draft:
            w, h = w // 2, h // 2
        segdir = C.stage_dir(f"tmp/segments/{w}x{h}")
        parts, rendered = [], []
        for shot, _ in tl:
            path, new = segment(shot, shots[shot["id"]], w, h, segdir)
            parts.append(path)
            if new:
                rendered.append(shot["id"])
        parts.append(end_card(sb, w, h, segdir))
        video = tmp / f"video_{aspect}.mp4"
        concat(parts, video)
        subs = tmp / f"subs_{aspect}.ass"
        write_ass(subtitle_cues(sb, narr, 32 if aspect == "9x16" else 42), subs, w, h, vertical=aspect == "9x16")
        out = final / f"film_{aspect}{'_draft' if draft else ''}.mp4"
        finish(video, mixed, subs if burn else None, out)
        cached = len(tl) - len(rendered)
        print(f"  ✓ {C.rel(out)} {w}x{h}, {C.media_duration(out):.1f}s — segments rendered: "
              f"{', '.join(rendered) or 'none'}; cached: {cached}")

    sources = {}
    for e in shots.values():
        label = "kenburns (fallback)" if e.get("fallback") else e["source"]
        sources[label] = sources.get(label, 0) + 1
    print(f"    shot sources: {sources}; music: {music['source']}")
    if not 60 <= total <= 90:
        C.warn(f"film is {total:.1f}s; the brief requires 60–90 s")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radio", action="store_true", help="narration + music on black, for user testing")
    ap.add_argument("--draft", action="store_true", help="half resolution, faster")
    ap.add_argument("--aspect", choices=["9x16", "16x9", "both"], default="both")
    args = ap.parse_args(argv)
    aspects = ["9x16", "16x9"] if args.aspect == "both" else [args.aspect]
    with C.stage_timer("assemble-radio" if args.radio else "assemble", draft=args.draft):
        run(args.radio, args.draft, aspects)


if __name__ == "__main__":
    main()
