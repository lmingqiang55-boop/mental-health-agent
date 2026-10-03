"""Reference Whisper benchmark on the same validated 16 kHz recordings.

Run with python -m scripts.benchmark_whisper; model weights go to --model-cache.
This does not select the production model or submit chat messages.
"""

import argparse
from contextlib import redirect_stdout
import importlib.metadata
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from backend.audio.config import ASRConfig
from backend.audio.decoder import decode_audio


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument("--model-cache", required=True, type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        parser.error("--repeat must be in [1, 20]")
    dll_handle = None
    if os.name == "nt" and args.device == "cuda":
        # Reuse installed PyTorch's CUDA runtime without machine-specific paths.
        import torch
        dll_dir = Path(torch.__file__).parent / "lib"
        os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
        dll_handle = os.add_dll_directory(str(dll_dir))
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    start = perf_counter()
    with redirect_stdout(sys.stderr):
        directory = Path(download_model(
            args.model, cache_dir=str(args.model_cache), revision=args.revision))
    download_ms = (perf_counter() - start) * 1000
    # Native Windows file openers may fail on Unicode cache paths. Load bytes
    # through the official files= API, keeping all caches at the caller's path.
    files = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
    start = perf_counter()
    model = WhisperModel(
        args.model, files=files, device=args.device,
        compute_type="float16" if args.device == "cuda" else "int8", cpu_threads=4)
    files.clear()
    import numpy as np
    language = None if args.language == "auto" else args.language
    def recognize(waveform):
        segments, info = model.transcribe(
            waveform, language=language, beam_size=5, temperature=0,
            vad_filter=False, condition_on_previous_text=False)
        return "".join(segment.text for segment in segments).strip(), info
    recognize(np.zeros(16000, dtype=np.float32))
    load_ms = (perf_counter() - start) * 1000
    records = []
    mimes = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".webm": "audio/webm",
             ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".flac": "audio/flac"}
    for path in args.files:
        data = path.read_bytes()
        mime = mimes.get(path.suffix.lower(), "")
        waveform = decode_audio(data, mime, ASRConfig(), None)
        duration_ms = waveform.size / 16
        trials = []
        for _ in range(args.repeat):
            start = perf_counter()
            waveform = decode_audio(data, mime, ASRConfig(), duration_ms)
            decoded = perf_counter()
            text, info = recognize(waveform)
            end = perf_counter()
            trials.append({"decode_ms": round((decoded-start)*1000, 2),
                           "asr_ms": round((end-decoded)*1000, 2),
                           "total_ms": round((end-start)*1000, 2), "text": text,
                           "language": info.language})
        records.append({"file": path.name, "audio_duration_ms": round(duration_ms, 2),
                        "bytes": len(data), "trials": trials})
    report = {"model": args.model, "revision": directory.name,
              "device": args.device, "language": args.language,
              "compute_type": "float16" if args.device == "cuda" else "int8",
              "beam_size": 5, "temperature": 0, "vad_filter": False,
              "condition_on_previous_text": False,
              "download_or_cache_lookup_ms": round(download_ms, 2),
              "load_and_warmup_ms": round(load_ms, 2),
              "versions": {name: importlib.metadata.version(name) for name in (
                  "faster-whisper", "ctranslate2", "av", "numpy")}, "records": records}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if dll_handle is not None:
        dll_handle.close()


if __name__ == "__main__":
    main()
