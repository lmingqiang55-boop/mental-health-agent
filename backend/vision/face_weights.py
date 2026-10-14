"""YuNet 人脸检测权重的获取与加载。

这里解决两个独立的问题：

1. **权重从哪来**：OpenCV 的 pip 包不附带任何 ``.onnx``（只有 Haar 级联），
   而仓库按惯例不分发本地模型产物（见 ``.gitignore`` 的 ``/models/``）。所以
   第一次使用时需要下载一次，约 227 KB，下完按 SHA256 校验。
2. **为什么不用路径加载**：Windows 上 OpenCV 把文件名按 ANSI 代码页交给窄字符
   ``fopen``。本项目目录含非 ASCII 字符（中文路径），于是
   ``cv2.FaceDetectorYN.create(路径)`` 直接报 ``Can't read ONNX file``；
   ``CascadeClassifier`` 有同样的毛病但更隐蔽——它只往 stderr 写日志、不抛异常，
   表现为 ``empty() == True``。因此权重一律用 Python 读成字节、再用 OpenCV ≥4.9
   的 buffer 重载创建，彻底绕开路径编码。

只负责"拿到并创建"，不做检测，便于单独测试。
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_BYTES = 232589

#: ``raw.githubusercontent.com`` 对 Git LFS 文件只返回 131 字节的指针文本，
#: 必须用 ``/raw/`` 或 media 域名。备用镜像用于主地址不可达时。
YUNET_URLS = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
    + YUNET_FILENAME,
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
    "face_detection_yunet/" + YUNET_FILENAME,
)

DOWNLOAD_TIMEOUT_SECONDS = 30.0


def default_weights_path() -> Path:
    """权重默认落盘的绝对路径；可用 ``VISION_YUNET_MODEL`` 覆盖。"""
    override = os.getenv("VISION_YUNET_MODEL", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "weights" / YUNET_FILENAME


def sha256_of(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _looks_like_lfs_pointer(data: bytes) -> bool:
    return data[:64].lstrip().startswith(b"version https://git-lfs")


def _download(url: str, target: Path) -> bytes:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        data = response.read()
    if _looks_like_lfs_pointer(data):
        raise RuntimeError(f"{url} 返回的是 Git LFS 指针而不是权重文件。")
    if hashlib.sha256(data).hexdigest() != YUNET_SHA256:
        raise RuntimeError(f"{url} 下载到的权重校验失败（SHA256 不符）。")
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    part.write_bytes(data)
    part.replace(target)
    return data


def ensure_yunet_weights(path: Path | None = None, *, allow_download: bool = True) -> Path:
    """返回校验通过的权重路径，必要时下载一次。

    已经存在的文件也要校验：半截的下载或错误镜像留下的文件比没有更危险。
    """
    target = path or default_weights_path()
    if sha256_of(target) == YUNET_SHA256:
        return target
    if not allow_download:
        raise RuntimeError(
            f"缺少 YuNet 权重 {target}（约 {YUNET_BYTES // 1024} KB）。"
            "请联网后执行 python -m backend.vision.face_weights 下载。"
        )
    errors: list[str] = []
    for url in YUNET_URLS:
        try:
            _download(url, target)
            return target
        except Exception as exc:  # noqa: BLE001 - 逐个镜像试，最后统一报错
            errors.append(f"{url}: {exc}")
    raise RuntimeError(
        f"YuNet 权重下载失败，请手动下载 {YUNET_FILENAME} （SHA256 {YUNET_SHA256}）"
        f" 放到 {target}。尝试过的地址：\n" + "\n".join(errors)
    )


def create_face_detector(
    *,
    score_threshold: float = 0.6,
    nms_threshold: float = 0.3,
    top_k: int = 5000,
    weights_path: Path | None = None,
):
    """用 buffer 重载创建 YuNet 检测器（非 ASCII 路径安全）。

    ``top_k`` 是 NMS 之前保留的候选数，不是最终返回的人脸数上限；
    调用方仍要自己取最大的一张。
    """
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV 未安装，请先激活项目环境，再执行 python -m pip install -r requirements.txt。"
        ) from exc
    if not hasattr(cv2, "FaceDetectorYN"):
        raise RuntimeError(
            f"当前 OpenCV（{cv2.__version__}）没有 FaceDetectorYN，请升级到 4.9 以上。"
        )
    path = ensure_yunet_weights(weights_path)
    # np.fromfile 走 Python 的文件 I/O，不受 OpenCV 窄字符 fopen 的编码限制。
    buffer = np.fromfile(str(path), dtype=np.uint8)
    if buffer.size != YUNET_BYTES:
        raise RuntimeError(f"YuNet 权重长度异常：{path} 为 {buffer.size} 字节。")
    try:
        return cv2.FaceDetectorYN.create(
            "onnx", buffer, b"", (0, 0),
            score_threshold, nms_threshold, top_k,
        )
    except cv2.error as exc:
        raise RuntimeError(f"YuNet 检测器创建失败：{exc}") from exc


if __name__ == "__main__":
    resolved = ensure_yunet_weights()
    print(f"YuNet 权重就绪：{resolved}")
