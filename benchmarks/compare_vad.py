"""Compare both filters on the same real Groq responses, without Telegram writes.

python -m benchmarks.compare_vad --env-file .env.dmi4er4
python -m benchmarks.compare_vad --replay benchmarks/vad_comparison.json
"""

import argparse
import asyncio
import io
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from pydub import AudioSegment

from benchmarks.legacy_filter import _strip_hallucinations
from src_py.impl.groq_whisper_transcriber import GroqWhisperTranscriber, _split_audio
from src_py.impl.speech_activity import (
    CONFIDENT_SPEECH, MIN_SPEECH_SECONDS, SPEECH_PAD_SECONDS,
    SileroSpeechDetector, SpeechActivity,
)
from src_py.impl.transcription_filter import filter_by_audio, filter_transcription
from src_py.impl.transcription_artifacts import strip_boilerplate

LABELS = ("baseline", "vad_only", "new")
POLICY = "Suppress subtitle/outro phrases even when spoken; preserve other speech"


def words(text):
    return re.findall(r"\w+", text.lower().replace("ё", "е"))


def edit_distance(expected, actual):
    row = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        next_row = [i]
        for j, right in enumerate(actual, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j-1] + (left != right)))
        row = next_row
    return row[-1]


def summarize(cases):
    totals = {}
    for case in cases:
        reference = case.get("expected_after_filter", case["expected"])
        category_name = "stop_phrase" if case["expected"] and not reference else case["category"]
        category = totals.setdefault(category_name, {"cases": 0, "reference_words": 0,
            **{label + suffix: 0 for label in LABELS for suffix in ("_empty", "_word_errors")}})
        category["cases"] += 1
        expected = words(reference)
        category["reference_words"] += len(expected)
        for label in LABELS:
            actual = words(case[label])
            category[label + "_empty"] += not actual
            category[label + "_word_errors"] += edit_distance(expected, actual)
    return totals


async def compare(args):
    root = Path(__file__).parent / "vad_audio"
    config = dict(confident_speech=CONFIDENT_SPEECH, min_speech_seconds=MIN_SPEECH_SECONDS,
                  speech_pad_seconds=SPEECH_PAD_SECONDS, suppress_boilerplate=True)
    manifest = json.loads((root / "manifest.json").read_text())
    fixtures = {case["file"]: case for case in manifest}
    if args.replay:
        report = json.loads(Path(args.replay).read_text())
        for case in report["cases"]:
            digest = hashlib.sha256((root / case["file"]).read_bytes()).hexdigest()
            if case.get("audio_sha256", digest) != digest:
                raise ValueError(f"Fixture changed since recording: {case['file']}")
            case["audio_sha256"] = digest
            if "expected_after_filter" in fixtures[case["file"]]:
                case["expected_after_filter"] = fixtures[case["file"]]["expected_after_filter"]
            texts, audio_only = [], []
            for chunk in case["chunks"]:
                activity = SpeechActivity(chunk["duration"], tuple(chunk["vad_probabilities"]))
                texts.append(filter_transcription(chunk["payload"], activity)
                             if activity.has_possible_speech else "")
                audio_only.append(filter_by_audio(chunk["payload"], activity)
                                  if activity.has_possible_speech else "")
            case["new"] = strip_boilerplate(" ".join(text for text in texts if text))
            case["vad_only"] = " ".join(text for text in audio_only if text)
        report["summary"] = summarize(report["cases"])
        report["evaluated_at"] = datetime.now(timezone.utc).isoformat()
        report["filter_config"] = config
        report["policy"] = POLICY
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        return

    api_key = dotenv_values(args.env_file).get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing")
    transcriber = GroqWhisperTranscriber(api_key)
    detector = SileroSpeechDetector()
    report = {"created_at": datetime.now(timezone.utc).isoformat(),
              "model": "whisper-large-v3-turbo", "silero_vad_lite": "0.4.0",
              "method": "same verbose_json response for both filters; original 60s splitting and MP3 encoding",
              "complete": False, "cases": []}
    if args.resume and Path(args.output).exists():
        report = json.loads(Path(args.output).read_text())
        report["complete"] = False
    report["filter_config"] = config
    report["policy"] = POLICY
    completed = {case["file"] for case in report["cases"]}
    last_call = -float("inf")
    for fixture in manifest:
        if fixture["file"] in completed:
            continue
        case = {**fixture, "chunks": [],
                "audio_sha256": hashlib.sha256((root / fixture["file"]).read_bytes()).hexdigest()}
        baseline, audio_only, new = [], [], []
        audio = AudioSegment.from_file(root / fixture["file"])
        if fixture["expected"] and (len(audio) == 0 or audio.max == 0):
            raise ValueError(f"Speech fixture is empty: {fixture['file']}")
        for chunk in _split_audio(audio):
            activity = detector.analyze(chunk)
            if chunk.max == 0:
                payload = {"text": "", "segments": []}
            else:
                await asyncio.sleep(max(0, 6.0 - (time.monotonic() - last_call)))
                last_call = time.monotonic()
                buf = io.BytesIO()
                chunk.export(buf, format="mp3", bitrate="64k")
                payload = await transcriber._call_groq_api(buf.getvalue(), "ru", None)
                if payload is None:
                    raise RuntimeError(f"Groq failed for {fixture['file']}; comparison incomplete")
            old_text = _strip_hallucinations(payload["text"])
            new_text = filter_transcription(payload, activity) if activity.has_possible_speech else ""
            baseline.append(old_text)
            audio_only.append(filter_by_audio(payload, activity) if activity.has_possible_speech else "")
            new.append(new_text)
            case["chunks"].append({"duration": activity.duration,
                "vad_probabilities": activity.probabilities,
                "payload": {"text": payload["text"], "segments": payload["segments"]}})
        case["baseline"] = " ".join(text for text in baseline if text)
        case["vad_only"] = " ".join(text for text in audio_only if text)
        case["new"] = strip_boilerplate(" ".join(text for text in new if text))
        report["cases"].append(case)
        report["summary"] = summarize(report["cases"])
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"file": fixture["file"], "expected": fixture["expected"],
              "baseline": case["baseline"], "new": case["new"]}, ensure_ascii=False), flush=True)
    report["complete"] = True
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.dmi4er4")
    parser.add_argument("--output", default="benchmarks/vad_comparison.json")
    parser.add_argument("--replay")
    parser.add_argument("--resume", action="store_true")
    asyncio.run(compare(parser.parse_args()))
