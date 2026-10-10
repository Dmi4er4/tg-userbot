"""Add six public ESC-10 environmental recordings as a separate validation set.

ESC-10 is CC BY 3.0; original clip credits are saved in the manifest. Files are
converted from WAV to 16 kHz mono Opus to exercise the Telegram decoding path.
"""
import csv
import hashlib
import io
import json
import urllib.request
from pathlib import Path

from pydub import AudioSegment

BASE = "https://raw.githubusercontent.com/karolpiczak/ESC-50/master/"
CATEGORIES = ("rain", "clock_tick", "crackling_fire", "helicopter", "dog", "sea_waves")


def fetch(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("Unexpectedly large fixture")
    return data


def main():
    metadata = list(csv.DictReader(io.StringIO(fetch("meta/esc50.csv").decode())))
    license_lines = fetch("LICENSE").decode().splitlines()
    root = Path(__file__).parent / "vad_audio"
    manifest_path = root / "manifest.json"
    manifest = [c for c in json.loads(manifest_path.read_text()) if c["category"] != "public_non_speech"]
    for category in CATEGORIES:
        row = next(r for r in metadata if r["category"] == category and r["esc10"] == "True")
        filename = row["filename"]
        data = fetch("audio/" + filename)
        audio = AudioSegment.from_file(io.BytesIO(data), format="wav").set_frame_rate(16_000).set_channels(1)
        target = f"esc10_{category}.ogg"
        audio.export(root / target, format="ogg", codec="libopus", bitrate="32k")
        key = filename.rsplit("-", 1)[0] + ".ogg"
        credit = next(line for line in license_lines if key in line)
        manifest.append({"file": target, "category": "public_non_speech", "expected": "",
                         "duration_seconds": len(audio) / 1000, "source": BASE + "audio/" + filename,
                         "source_sha256": hashlib.sha256(data).hexdigest(),
                         "license": "https://creativecommons.org/licenses/by/3.0/",
                         "attribution": credit, "modification": "resampled to mono 16kHz and encoded as Opus"})
        print(target, flush=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
