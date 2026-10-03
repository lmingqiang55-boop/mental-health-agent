"""Benchmark real ASR using supplied test audio; run with python -m scripts.benchmark_asr.

Prints JSON to stdout without saving audio or changing any conversation. File
names and transcripts can contain sensitive data: use synthetic/public samples.
"""

import argparse
from contextlib import redirect_stdout
import importlib.metadata
import json
import mimetypes
import sys
from pathlib import Path
from time import perf_counter

from backend.audio.config import ASRConfig
from backend.audio.decoder import decode_audio
from backend.audio.transcriber import SenseVoiceRecognizer, clean_transcript


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--language", choices=["auto", "zh", "en", "yue", "ja", "ko"])
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        parser.error("--repeat must be in [1, 20]")
    base = ASRConfig.from_env()
    from dataclasses import replace
    config = replace(base, provider="sensevoice", device=args.device,
                     language=args.language or base.language)
    recognizer = SenseVoiceRecognizer(config)
    start = perf_counter()
    with redirect_stdout(sys.stderr):
        recognizer.load()
    load_ms = (perf_counter() - start) * 1000
    records = []
    for path in args.files:
        mime = mimetypes.guess_type(path.name)[0]
        mime = {".wav": "audio/wav", ".webm": "audio/webm", ".m4a": "audio/mp4",
                ".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".flac": "audio/flac"}.get(
                    path.suffix.lower(), mime)
        data = path.read_bytes()
        # CLI has no client time axis. Obtain duration from a first validated decode.
        waveform = decode_audio(data, mime or "", config, None)
        duration_ms = waveform.size / 16
        trials = []
        for _ in range(args.repeat):
            start = perf_counter()
            waveform = decode_audio(data, mime or "", config, duration_ms)
            decoded = perf_counter()
            with redirect_stdout(sys.stderr):
                text = clean_transcript(recognizer.recognize(waveform))
            end = perf_counter()
            trials.append({"decode_ms": round((decoded - start) * 1000, 2),
                           "asr_ms": round((end - decoded) * 1000, 2),
                           "total_ms": round((end - start) * 1000, 2), "text": text})
        records.append({"file": path.name, "audio_duration_ms": round(duration_ms, 2),
                        "bytes": len(data), "trials": trials})
    result = {
        "device": args.device, "language": config.language,
        "model": config.model, "revision": config.model_revision,
        "load_and_warmup_ms": round(load_ms, 2),
        "versions": {name: importlib.metadata.version(name) for name in (
            "funasr", "modelscope", "torch", "torchaudio", "av", "numpy")},
        "records": records,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
