"""Render the fictional screenshot tour locally with FFmpeg and macOS speech.

No browser, application, database or network is accessed. Inputs are committed fictional captures.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "docs" / "demo"


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def filter_path(path):
    return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def stamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def ass_stamp(seconds):
    return stamp(seconds).replace(",", ".")[:-1]


def speech_duration(ffmpeg, path):
    result = run([ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-"])
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
    if not match:
        raise ValueError("Could not read narration duration.")
    h, m, s = map(float, match.groups())
    return h * 3600 + m * 60 + s


def render(args):
    if not shutil.which("say"):
        raise ValueError("Rendering narration requires macOS say; playback does not.")
    data = json.loads((DEMO / "video-storyboard.json").read_text())
    captions, transcript, clips = [], [], []
    offset = 0
    with tempfile.TemporaryDirectory(prefix="astracore-video-") as folder:
        temp = Path(folder)
        for index, scene in enumerate(data["scenes"]):
            image = DEMO / "video-screens" / scene["image"]
            if not image.is_file():
                raise ValueError(f"Missing fictional capture: {image.name}")
            sentences = re.split(r"(?<=[.!?])\s+", scene["narration"])
            speech_files, sentence_lengths = [], []
            for cue, sentence in enumerate(sentences):
                speech = temp / f"speech-{index}-{cue}.txt"
                speech.write_text(sentence.replace("AstraCore", "Astra Core")
                                  .replace("DalShooth", "Dal Shoot").replace("EVE", "Eve"))
                spoken = temp / f"speech-{index}-{cue}.aiff"
                run(["say", "-v", args.voice, "-r", str(args.rate), "-f", str(speech), "-o", str(spoken)])
                speech_files.append(spoken)
                sentence_lengths.append(speech_duration(args.ffmpeg, spoken))
            audio_list = temp / f"audio-{index}.txt"
            audio_list.write_text("\n".join(f"file '{path}'" for path in speech_files))
            audio = temp / f"speech-{index}.wav"
            run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                 "-i", str(audio_list), "-ar", "48000", "-ac", "1", str(audio)])
            duration = max(12, sum(sentence_lengths) + 1)
            title = temp / f"title-{index}.txt"
            title.write_text(scene["title"])
            points = temp / f"points-{index}.txt"
            points.write_text("\n\n".join(scene["points"]))
            subtitle = temp / f"captions-{index}.ass"
            cues = ["[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n"
                    "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
                    "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                    "Style: Default,Arial,34,&H00FFFFFF,&H00FFFFFF,&H00131610,&H00131610,"
                    "0,0,0,0,100,100,0,0,3,1,0,2,60,60,132,1\n"
                    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
            start = 0.3
            for cue, sentence in enumerate(sentences):
                end = start + sentence_lengths[cue]
                lines = textwrap.fill(sentence, width=90)
                ass_text = lines.replace("\n", "\\N")
                cues.append(f"Dialogue: 0,{ass_stamp(start)},{ass_stamp(end)},Default,,0,0,0,,{ass_text}")
                captions.append(f"{len(captions) + 1}\n{stamp(offset + start)} --> {stamp(offset + end)}\n{lines}\n")
                start = end
            subtitle.write_text("\n".join(cues))
            font = filter_path(args.font)
            graph = (
                "[0:v]scale=1152:648:force_original_aspect_ratio=decrease,"
                "pad=1152:648:(ow-iw)/2:(oh-ih)/2:color=0x101316[screen];"
                f"color=c=0x080b0e:s=1920x1080:r=24:d={duration}[bg];"
                "[bg][screen]overlay=x=48:y=192,"
                f"drawtext=fontfile='{font}':text='ASTRACORE / FICTIONAL PI TOUR':fontsize=38:fontcolor=white:x=48:y=42,"
                f"drawtext=fontfile='{font}':text='0{index + 1} / 06':fontsize=24:fontcolor=0xff7a18:x=48:y=110,"
                f"drawtext=fontfile='{font}':textfile='{filter_path(title)}':expansion=none:fontsize=42:fontcolor=white:x=1250:y=220,"
                f"drawtext=fontfile='{font}':textfile='{filter_path(points)}':expansion=none:fontsize=30:line_spacing=18:fontcolor=0xcbd0d5:x=1250:y=330,"
                f"drawtext=fontfile='{font}':text='Fictional pilots and locations / Illustrative figures / No live EVE actions':fontsize=25:fontcolor=0xff7a18:x=48:y=1020,"
                f"subtitles='{filter_path(subtitle)}'[video]"
            )
            clip = temp / f"clip-{index}.mp4"
            run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", str(image),
                 "-i", str(audio), "-filter_complex", graph, "-map", "[video]", "-map", "1:a",
                 "-af", "adelay=300:all=1,apad", "-t", str(duration), "-c:v", "libx264", "-preset", "fast",
                 "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", str(clip)])
            clips.append(clip)
            transcript.append(f"## {stamp(offset)[:-4]} — {scene['title']}\n\n{scene['narration']}\n")
            offset += duration
        if not 60 <= offset <= 90:
            raise ValueError(f"Narration produced {offset:.1f} seconds; adjust speech rate for a 60–90 second tour.")
        listing = temp / "clips.txt"
        listing.write_text("\n".join(f"file '{clip}'" for clip in clips))
        run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", "-movflags", "+faststart", "-metadata", "title=AstraCore fictional PI screenshot tour",
             "-metadata", "comment=Fictional data; illustrative fixed figures; not an executable plan.",
             "-y", str(args.output)])
    caption_text = "\n".join(captions)
    args.output.with_suffix(".srt").write_text(caption_text)
    web_captions = "WEBVTT\n\n" + re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", caption_text)
    args.output.with_suffix(".vtt").write_text(web_captions)
    player = args.output.with_suffix(".html")
    if player.is_file():
        # Embedded captions also work when the player is opened directly from a saved folder.
        source = "data:text/vtt;charset=utf-8," + quote(web_captions, safe="")
        player.write_text(re.sub(r'(<track kind="captions" src=")[^"]+("[^>]*>)',
                                 lambda match: match[1] + source + match[2], player.read_text()))
    capture_updates = " ".join(
        f"{name} refreshed at {source['build']} ({source['commit'][:7]})."
        for name, source in data.get("updated_captures", {}).items())
    args.output.with_suffix(".md").write_text(
        "# Fictional PI walkthrough transcript\n\n"
        f"Original captures: {data['capture_build']} ({data['capture_commit'][:7]}). "
        f"{capture_updates} Fictional runner only; no real profiles, live prices or executable colony plan. "
        "English narration uses macOS synthetic speech; the captions repeat it.\n\n" + "\n".join(transcript) +
        "\nCredits: DalShooth maintains the templates; EVE Online and official imagery belong to CCP hf. "
        "AstraCore is independent and built by capsuleers and contributors. VOC is an independent provider. "
        "See README.md and ../../THIRD_PARTY_NOTICES.md for attribution and limits.\n")
    print(f"Rendered {offset:.1f}s fictional tour: {args.output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--voice", default="Samantha")
    parser.add_argument("--rate", type=int, default=190)
    parser.add_argument("--output", type=Path, default=DEMO / "walkthrough.mp4")
    render(parser.parse_args())


if __name__ == "__main__":
    main()
