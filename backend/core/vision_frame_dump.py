"""把冻结后的视觉片段落盘，供阈值重校使用（默认关闭）。

为什么要有它：``backend.core.vision_thresholds`` 里的那些数字（置信度 0.6、
人脸帧比 0.7、效价 0.2……）目前是原型档位，不是本项目真实数据上的分位数。逐帧的
置信度与效价从来没有落过盘，评估库里能算出分数的记录又全部来自同一套构造会话，
所以要把门槛校准到真实分布，只能先在真实会话上把帧留下来。

打开方式：给环境变量 ``VISION_FRAME_DUMP_DIR`` 一个目录即可。不设（默认）时本
模块什么都不做，也不会去探测目录。

产出：一个会话一个 JSONL 文件，一行一个冻结片段。文件里有每帧的情绪、置信度、
效价与来源，属于**调试/校准用的原始数据**——别当产品数据长期保存，也别把目录提交
进仓库。写盘失败只记一条日志，绝不影响一次真实对话。

重校步骤见 :mod:`backend.core.vision_thresholds` 的模块说明。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from threading import RLock

from backend.models.states import VisionFrameObservation, VisionSegment

logger = logging.getLogger(__name__)

#: 落盘目录的环境变量名；不设置或留空即关闭本功能。
DUMP_DIR_ENV = "VISION_FRAME_DUMP_DIR"

_UNSAFE_NAME = re.compile(r"[^0-9A-Za-z_-]+")
_write_lock = RLock()


def dump_dir() -> Path | None:
    """返回落盘目录；未开启时返回 ``None``。"""

    raw = (os.getenv(DUMP_DIR_ENV) or "").strip()
    return Path(raw) if raw else None


def _filename(session_id: str) -> str:
    """会话标识直接当文件名，先剔掉路径分隔符等字符。"""

    safe = _UNSAFE_NAME.sub("_", session_id).strip("_")[:64]
    return f"{safe or 'session'}.jsonl"


def _frame_payload(item: VisionFrameObservation) -> dict:
    return {
        "frame_id": item.frame_id,
        "captured_at_ms": item.captured_at_ms,
        "source": item.source,
        "image_digest": item.image_digest,
        "state": item.state.model_dump(exclude={"timestamp"}),
    }


def dump_segment(session_id: str, utterance_id: str,
                 segment: VisionSegment) -> Path | None:
    """把一个冻结片段追加到该会话的 JSONL；未开启或写失败时返回 ``None``。"""

    target_dir = dump_dir()
    if target_dir is None:
        return None
    payload = {
        "session_id": session_id,
        "utterance_id": utterance_id,
        "capture_id": segment.capture_id,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "frame_count": segment.frame_count,
        "valid_frame_count": segment.valid_frame_count,
        "snapshot": (segment.vision_snapshot.model_dump(exclude={"timestamp"})
                     if segment.vision_snapshot is not None else None),
        "frames": [_frame_payload(item) for item in segment.dialogue_frames],
    }
    path = target_dir / _filename(session_id)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False)
        with _write_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return path
    except OSError as exc:
        logger.warning("视觉片段落盘失败（%s）：%s", target_dir, exc)
        return None
