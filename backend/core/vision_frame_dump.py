"""把冻结后的视觉片段落盘，供阈值重校使用（默认关闭）。

为什么要有它：``backend.core.vision_thresholds`` 里的那些数字（置信度 0.6、
人脸帧比 0.7、效价 0.2……）目前是原型档位，不是本项目真实数据上的分位数。逐帧的
置信度与效价从来没有落过盘，评估库里能算出分数的记录又全部来自同一套构造会话，
所以要把门槛校准到真实分布，只能先在真实会话上把帧留下来。

打开方式：给环境变量 ``VISION_FRAME_DUMP_DIR`` 一个目录即可。不设（默认）时本
模块什么都不做，也不会去探测目录。目录**放在仓库之外**（例如仓库同级的
``vision_dump/``）；万一要放在仓库里，就用 ``vision_dump/`` 这个名字，它已在
``.gitignore`` 里，别把校准用的原始数据提交进去。

产出：一个会话一个 JSONL 文件，一行一个冻结片段。每行开头的 ``detector`` 说明这份
数据是哪条链路产出的（provider / 模型 / 人脸检测后端），重校时先按它分组再算分位数。
文件里有每帧的情绪、置信度、效价与来源，属于**调试/校准用的原始数据**——别当产品数据
长期保存。写盘失败只记一条日志，绝不影响一次真实对话。

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
from backend.vision.detector import describe_loaded_vision_detector

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


def _serialize(payload: dict) -> str:
    """一行 JSON。单独一个函数，方便测试模拟"序列化失败"这条路径。"""

    return json.dumps(payload, ensure_ascii=False)


def dump_segment(session_id: str, utterance_id: str,
                 segment: VisionSegment) -> Path | None:
    """把一个冻结片段追加到该会话的 JSONL；未开启或写失败时返回 ``None``。

    调用点必须在会话锁**之外**（见 ``backend.api.vision.freeze_segment``）：这个
    模块会真的写磁盘，占着那把全局会话锁写文件会拖慢所有会话。
    """

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
        # 重校要先按"哪条链路产出的"分组：不同 provider / 模型 / 人脸检测后端
        # （YuNet 还是降级后的 Haar）不可混在一起算分位数。
        "detector": describe_loaded_vision_detector(),
        "snapshot": (segment.vision_snapshot.model_dump(exclude={"timestamp"})
                     if segment.vision_snapshot is not None else None),
        "frames": [_frame_payload(item) for item in segment.dialogue_frames],
    }
    path = target_dir / _filename(session_id)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        line = _serialize(payload)
        with _write_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return path
    except Exception as exc:  # noqa: BLE001 - 兜底要宽：见模块 docstring
        # 刻意兜住所有异常而不是只兜 OSError：这里是"校准用的旁路"，任何失败都
        # 不该让一次真实对话失败。序列化也是失败来源之一（模型将来多一个
        # datetime/enum 字段，json.dumps 就会抛 TypeError），只写 OSError 时那句
        # "写盘失败绝不影响一次真实对话"就是一句空话。
        logger.warning("视觉片段落盘失败（%s）：%s: %s", target_dir, type(exc).__name__, exc)
        return None
