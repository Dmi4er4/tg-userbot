"""Generate reproducible, non-private Russian test audio with macOS Milena.

Run from the repository root: python -m benchmarks.generate_vad_audio
The checked-in OGG files can also be tested on Linux without macOS TTS.
"""

import json
import random
import subprocess
from array import array
from pathlib import Path
from tempfile import TemporaryDirectory

from pydub import AudioSegment
from pydub.generators import Sine

DESTINATION = Path(__file__).parent / "vad_audio"


def generate() -> None:
    DESTINATION.mkdir(exist_ok=True)
    manifest = []
    silence = lambda ms: AudioSegment.silent(duration=ms, frame_rate=16_000)

    def save(name, audio, category, expected="", expected_after_filter=None):
        path = DESTINATION / f"{name}.ogg"
        audio.export(path, format="ogg", codec="libopus", bitrate="32k")
        manifest.append({
            "file": path.name, "category": category, "expected": expected,
            "duration_seconds": len(audio) / 1000,
            "source": "macOS Milena TTS" if expected else "generated non-speech",
        })
        if expected_after_filter is not None:
            manifest[-1]["expected_after_filter"] = expected_after_filter

    with TemporaryDirectory() as tmp:
        phrases = {
            "yes": "Да.", "no": "Нет.", "stop": "Стоп.",
            "thanks": "Спасибо за внимание!",
            "subscribe": "Подписывайтесь на мой канал!",
            "credits": "Субтитры сделал Дима.",
            "ordinary": "Встречаемся завтра в пять. Я принесу документы.",
            "music_word": "Музыка.",
        }
        voices = {}
        for name, phrase in phrases.items():
            path = Path(tmp) / f"{name}.aiff"
            subprocess.run(["say", "-v", "Milena", "-r", "170", "-o", str(path), phrase], check=True)
            audio = AudioSegment.from_file(path).set_frame_rate(16_000).set_channels(1)
            if len(audio) == 0 or audio.max == 0:
                raise RuntimeError(f"TTS produced no speech for {name}; fixtures are invalid")
            voices[name] = audio
            filtered = "" if name in ("thanks", "subscribe", "credits") else None
            save(name, silence(150) + audio + silence(150), "speech", phrase, filtered)
            save(name + "_quiet", silence(150) + (audio - 35) + silence(150), "quiet_speech", phrase, filtered)
        save("long_pauses", silence(20_000) + voices["yes"] + silence(50_000)
             + voices["thanks"] + silence(20_000), "mixed", "Да. Спасибо за внимание!", "Да.")
        save("speech_at_end", silence(50_000) + voices["no"], "mixed", "Нет.")
        save("silence_short", silence(800), "non_speech")
        save("silence_long", silence(65_000), "non_speech")
        rng = random.Random(42)
        noise = AudioSegment(array("h", (rng.randint(-1000, 1000) for _ in range(16_000 * 8))).tobytes(),
                             sample_width=2, frame_rate=16_000, channels=1)
        save("white_noise", noise, "non_speech")
        save("quiet_noise", noise - 30, "non_speech")
        save("wind", noise.low_pass_filter(120) + noise.low_pass_filter(200), "non_speech")
        save("hum", Sine(50, sample_rate=16_000).to_audio_segment(duration=5000) - 20, "non_speech")
        clicks = silence(6000)
        for pos in (500, 1100, 2500, 4000, 4700):
            clicks = clicks.overlay(noise[:15], position=pos)
        save("clicks", clicks, "non_speech")
        melody = silence(0)
        for freq in (262, 330, 392, 330, 294, 349, 440, 349):
            melody += (Sine(freq, sample_rate=16_000).to_audio_segment(duration=500) - 15).fade_in(40).fade_out(100)
        save("instrumental", melody, "non_speech")
        save("speech_in_noise", voices["ordinary"].overlay(noise - 18), "speech_in_noise", phrases["ordinary"])
    (DESTINATION / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Generated {len(manifest)} fixtures in {DESTINATION}")


if __name__ == "__main__":
    generate()
