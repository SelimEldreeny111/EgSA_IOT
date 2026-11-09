"""Render the illustrated WIOT walkthrough and its synchronized captions."""

from pathlib import Path
import json
import math
import os
import subprocess
import wave

from PIL import Image, ImageDraw, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
WORK = HERE / "tmp" / "video"
SCENES = json.loads((HERE / "walkthrough.json").read_text(encoding="utf-8"))
SIZE = (1280, 720)
BG = "#0F1B2D"
PANEL = "#192C44"
WHITE = "#F4F8FD"
MUTED = "#AABED3"
CYAN = "#67E8F9"
GREEN = "#7AE8BC"
FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
FPS = 15


def font(size, bold=False):
    return ImageFont.truetype(str(FONT_DIR / ("arialbd.ttf" if bold else "arial.ttf")), size)


def wrap(draw, value, face, width):
    lines = [""]
    for word in value.split():
        candidate = (lines[-1] + " " + word).strip()
        if draw.textlength(candidate, font=face) > width and lines[-1]:
            lines.append(word)
        else:
            lines[-1] = candidate
    return "\n".join(lines)


def card(draw, bounds, label, detail, active, number=None):
    x, y, right, bottom = bounds
    outline = CYAN if active else "#324E6B"
    draw.rounded_rectangle(bounds, radius=19, fill=PANEL, outline=outline, width=3 if active else 1)
    draw.rounded_rectangle((x + 18, y + 21, x + 23, y + 55), radius=2, fill=outline)
    title = f"{number:02d}  {label}" if number else label
    face = font(30, True)
    while draw.textlength(title, font=face) > right - x - 65:
        face = font(face.size - 1, True)
    draw.text((x + 37, y + 25), title, font=face, fill=CYAN if active else WHITE)
    if detail:
        desc = font(23)
        draw.multiline_text((x + 37, y + 77), wrap(draw, detail, desc, right - x - 68),
                            font=desc, fill=MUTED, spacing=7)


def arrow(draw, x1, y, x2, active):
    color = CYAN if active else "#516F8E"
    draw.line((x1, y, x2 - 11, y), fill=color, width=4)
    draw.polygon(((x2, y), (x2 - 13, y - 7), (x2 - 13, y + 7)), fill=color)


def make_frame(scene, chapter, step):
    img = Image.new("RGB", SIZE, BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, SIZE[0], 8), fill=CYAN)
    draw.text((62, 40), scene["kicker"], font=font(20, True), fill=GREEN)
    draw.text((1039, 40), "EgSA  /  WIOT", font=font(20, True), fill=MUTED)
    if scene["mode"] == "cover":
        asset = HERE.parent / "SystemOverview/output/WIOT_Node_Gateway_Server_Illustration.png"
        art = ImageOps.contain(Image.open(asset).convert("RGB"), (665, 425))
        x = 1218 - art.width
        y = 170 + (425 - art.height) // 2
        img.paste(art, (x, y))
        draw.multiline_text((62, 163), "WIOT from field\nto dashboard", font=font(56, True),
                            fill=WHITE, spacing=10)
        draw.multiline_text((64, 332), wrap(draw, scene["summary"], font(27), 455),
                            font=font(27), fill=MUTED, spacing=8)
        draw.text((x, y + art.height + 12), "Representative system illustration",
                  font=font(18), fill=MUTED)
    else:
        title_face = font(50, True)
        while draw.textlength(scene["title"], font=title_face) > 1155:
            title_face = font(title_face.size - 1, True)
        draw.text((62, 83), scene["title"], font=title_face, fill=WHITE)
        if scene["mode"] == "routes":
            card(draw, (62, 293, 277, 420), "STM32 leaf", "RS485 + ADC", True)
            card(draw, (343, 197, 732, 329), "Direct MQTT", "Wi-Fi or SIM800L", step == 0)
            card(draw, (343, 381, 732, 513), "LoRa gateway", "Radio to IP uplink", step == 1)
            card(draw, (800, 293, 1218, 420), "Python server", "Scoped MQTT and dashboard", step == 2)
            branches = [(0, 263), (1, 447)]
            for branch, level in sorted(branches, key=lambda item: item[0] == step):
                active = step in (branch, 2)
                color = CYAN if active else "#516F8E"
                draw.line((277, 356, 308, 356, 308, level), fill=color, width=4)
                arrow(draw, 308, level, 343, active)
                draw.line((732, level, 765, level, 765, 356), fill=color, width=4)
                arrow(draw, 765, 356, 800, active)
        else:
            for i, (label, detail) in enumerate(scene["cards"]):
                x = 62 + (i % 2) * 590
                y = 188 + (i // 2) * 184
                card(draw, (x, y, x + 566, y + 155), label, detail, i == step, i + 1)
    draw.line((62, 599, 1218, 599), fill="#36506A", width=1)
    label = scene["steps"][step][0]
    draw.text((62, 620), f"{chapter + 1:02d} / {len(SCENES):02d}     {label}",
              font=font(23, True), fill=WHITE)
    for i in range(len(SCENES)):
        x = 62 + i * 146
        draw.rounded_rectangle((x, 680, x + 134, 686), radius=3,
                               fill=CYAN if i <= chapter else "#324E6B")
    return img


def timecode(ms, separator="."):
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def transcript(value):
    for spoken, printed in {
        "S T M thirty-two": "STM32", "R S four eighty-five": "RS485",
        "SIM eight hundred": "SIM800L", "M Q T T": "MQTT", "S P I": "SPI",
        "U A R T": "UART", "S T Link": "ST-Link", "S W D": "SWD",
    }.items():
        value = value.replace(spoken, printed)
    return value


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                   cwd=WORK, check=True)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    subprocess.run(["powershell", "-NoProfile", "-File", str(HERE / "synthesize_walkthrough.ps1"),
                    "-WorkDirectory", str(WORK)], check=True)
    index = 0
    elapsed = 0
    captions = ["WEBVTT\n"]
    srt = []
    chapters = ["WEBVTT\n"]
    notes = ["# WIOT system walkthrough transcript", "",
             "Illustrated narration for the active STM32 Arduino release.", ""]
    clips = []
    for chapter, scene in enumerate(SCENES):
        start = elapsed
        notes.extend([f"## {timecode(start)[:8]} {scene['title']}", ""])
        for step, (_, spoken) in enumerate(scene["steps"]):
            cue = f"{index:02d}"
            wav = f"voice_{cue}.wav"
            with wave.open(str(WORK / wav)) as audio:
                length = audio.getnframes() / audio.getframerate()
            frames = math.ceil((length + 0.45) * FPS)
            duration = frames / FPS
            finish = elapsed + round(duration * 1000)
            caption = transcript(spoken)
            end_speech = min(finish - 100, elapsed + round(length * 1000))
            captions.append(f"{timecode(elapsed)} --> {timecode(end_speech)}\n{caption}\n")
            srt.append(f"{index + 1}\n{timecode(elapsed, ',')} --> {timecode(end_speech, ',')}\n{caption}\n")
            notes.extend([caption, ""])
            frame = f"frame_{cue}.png"
            make_frame(scene, chapter, step).save(WORK / frame)
            clip = f"clip_{cue}.mp4"
            ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", frame, "-i", wav,
                   "-af", "volume=-3dB,apad", "-t", f"{duration:.6f}", "-c:v", "libx264",
                   "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "48k", "-ar", "48000", clip)
            clips.append(f"file '{clip}'")
            elapsed = finish
            index += 1
        chapters.append(f"{timecode(start)} --> {timecode(elapsed)}\n{scene['title']}\n")
    (WORK / "clips.txt").write_text("\n".join(clips) + "\n", encoding="utf-8")
    (WORK / "captions.srt").write_text("\n".join(srt), encoding="utf-8")
    (HERE / "WIOT_System_Walkthrough.vtt").write_text("\n".join(captions), encoding="utf-8")
    (HERE / "WIOT_System_Walkthrough_Chapters.vtt").write_text("\n".join(chapters), encoding="utf-8")
    (HERE / "WIOT_System_Walkthrough_Transcript.md").write_text("\n".join(notes), encoding="utf-8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", "clips.txt",
           "-i", "captions.srt", "-map", "0:v", "-map", "0:a", "-map", "1:0",
           "-metadata", "title=WIOT system walkthrough", "-map_chapters", "-1",
           "-c", "copy", "-c:s", "mov_text",
           "-metadata:s:s:0", "language=eng", "-movflags", "+faststart",
           str(HERE / "WIOT_System_Walkthrough.mp4"))
    print(f"Rendered {len(SCENES)} chapters and {index} cues in {timecode(elapsed)}")


if __name__ == "__main__":
    main()
