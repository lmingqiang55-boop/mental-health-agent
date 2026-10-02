"""In-memory PyAV decode/downmix/resample, inspired by faster-whisper audio.py.

No file paths, network inputs, VAD, or silent truncation of corrupt frames.
"""

from io import BytesIO

from backend.audio.config import ASRConfig
from backend.audio.errors import AudioError

SUPPORTED_MIME_TYPES = {
    "audio/webm": {"matroska", "webm"},
    "audio/ogg": {"ogg"},
    "application/ogg": {"ogg"},
    "audio/wav": {"wav"},
    "audio/wave": {"wav"},
    "audio/x-wav": {"wav"},
    "audio/mp4": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    "audio/x-m4a": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    "audio/mpeg": {"mp3"},
    "audio/flac": {"flac"},
}


def decode_audio(data: bytes, content_type: str, config: ASRConfig,
                 recording_duration_ms: float | None):
    # Deferred imports keep the original text-only installation usable.
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in SUPPORTED_MIME_TYPES:
        raise AudioError("UNSUPPORTED_AUDIO_FORMAT", "不支持此录音 MIME 类型。", 415)
    if not data:
        raise AudioError("INVALID_AUDIO", "录音文件为空。")
    if len(data) > config.max_upload_bytes:
        raise AudioError("AUDIO_TOO_LARGE", "录音文件超过上传大小限制。", 413)
    try:
        import av
        import numpy as np
    except ImportError as exc:
        raise AudioError("ASR_UNAVAILABLE", "音频解码依赖未安装。", 503) from exc

    chunks = []
    samples = 0
    # A small codec padding allowance; never pad the user's waveform ourselves.
    sample_limit = int((config.max_duration_seconds + 0.1) * 16000)
    try:
        # Restrict nested protocol access as well as using a file-like input.
        with av.open(BytesIO(data), mode="r", options={"protocol_whitelist": ""}) as container:
            actual_formats = set(container.format.name.split(","))
            if not actual_formats & SUPPORTED_MIME_TYPES[mime]:
                raise AudioError("UNSUPPORTED_AUDIO_FORMAT", "录音 MIME 与实际格式不一致。", 415)
            if len(container.streams.audio) != 1 or container.streams.video:
                raise AudioError("INVALID_AUDIO", "请上传只有一条音轨且不含视频的录音。")
            stream = container.streams.audio[0]
            context = stream.codec_context
            if not 8000 <= context.sample_rate <= 192000 or not 1 <= context.channels <= 8:
                raise AudioError("INVALID_AUDIO", "录音采样率或声道数不受支持。")
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)

            def collect(frames) -> None:
                nonlocal samples
                for frame in frames:
                    array = frame.to_ndarray().reshape(-1)
                    samples += array.size
                    if samples > sample_limit:
                        raise AudioError("AUDIO_TOO_LONG", "录音超过允许时长，请分次录音。")
                    chunks.append(array)

            for frame in container.decode(stream):
                frame.pts = None
                collect(resampler.resample(frame))
            # Flush the resampler to preserve the final samples/words.
            collect(resampler.resample(None))
    except AudioError:
        raise
    except Exception as exc:
        raise AudioError("INVALID_AUDIO", "录音无法完整解码，请上传收尾后的完整文件。") from exc
    if not samples:
        raise AudioError("INVALID_AUDIO", "录音没有可解码的音频样本。")
    waveform = np.concatenate(chunks).astype(np.float32, copy=False)
    if not np.isfinite(waveform).all():
        raise AudioError("INVALID_AUDIO", "录音包含无效音频样本。")
    duration_ms = samples / 16
    if recording_duration_ms is not None and abs(duration_ms - recording_duration_ms) > max(
            250, recording_duration_ms * 0.02):
        raise AudioError("AUDIO_TIME_MISMATCH", "录音时长与采集区间不符，请检查录音收尾与时间轴。")
    if float(np.max(np.abs(waveform))) <= 1e-7:
        raise AudioError("NO_SPEECH", "录音是静音，请重新录音。")
    return waveform
