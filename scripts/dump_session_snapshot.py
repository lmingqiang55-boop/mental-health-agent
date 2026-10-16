# -*- coding: utf-8 -*-
"""把一个会话的完整状态导出成 JSON，避免证据随进程重启 / TTL 到期一起消失。

为什么需要它：会话是**进程内存储**（`backend/core/session_manager.py`），
重启即清空，且有 **2 小时 TTL**。对话里的逐帧视觉数据（`vision_segments`）
从来没有落过盘，只存在于内存里。

    python scripts/dump_session_snapshot.py <session_id> [--out 目录]
    python scripts/dump_session_snapshot.py --all-known <id1> <id2> ...

默认写到 `data/diagnostics/session_<id前8位>_<时间戳>.json`（`data/` 已被 .gitignore 忽略）。
同时打印一份人眼可读的摘要：每轮的文本、视觉快照、以及采集状态。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BACKEND = "http://127.0.0.1:8011"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "diagnostics"


def fetch(session_id: str) -> dict:
    url = f"{BACKEND}/api/session/{session_id}"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def vision_status() -> dict:
    with urllib.request.urlopen(f"{BACKEND}/api/vision/status", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def summarize(session: dict) -> None:
    history = session.get("conversation_history") or []
    segments = session.get("vision_segments") or {}
    bound = [m for m in history if m.get("vision_snapshot")]
    print(f"  消息 {len(history)} 条，其中带视觉快照 {len(bound)} 条")
    print(f"  active_vision_capture_id = {session.get('active_vision_capture_id')}")
    print(f"  last_visual_observation_turn = {session.get('last_visual_observation_turn')}"
          "    （一直为 None = 从未采纳过表情）")
    print(f"  vision_segments = {len(segments)} 条")
    for key, segment in segments.items():
        frames = segment.get("dialogue_frames") or []
        sources = {frame.get("source") for frame in frames}
        faces = sum(1 for frame in frames
                    if (frame.get("state") or {}).get("face_detected"))
        print(f"    · utterance {key[:8]}: frames={len(frames)} "
              f"source={sources or '-'} 有脸帧={faces}")
    if session.get("latest_safety"):
        safety = session["latest_safety"]
        print(f"  latest_safety: level={safety.get('risk_level')} "
              f"route={safety.get('route')} "
              f"hotlines={safety.get('hotline_numbers')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id", nargs="?", help="要导出的会话 id")
    parser.add_argument("--all-known", nargs="+", metavar="ID",
                        help="一次导出多个会话")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录")
    args = parser.parse_args()

    ids = args.all_known or ([args.session_id] if args.session_id else [])
    if not ids:
        parser.error("请给出 session_id，或用 --all-known 一次给多个")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        status = vision_status()
        print(f"视觉模型状态：{json.dumps(status, ensure_ascii=False)}")
    except urllib.error.URLError as exc:
        print(f"后端不可达（{exc}）；请确认 uvicorn 已启动", file=sys.stderr)
        return 1

    for session_id in ids:
        print(f"\n会话 {session_id}")
        try:
            session = fetch(session_id)
        except urllib.error.HTTPError as exc:
            print(f"  导出失败：HTTP {exc.code}（会话可能已过期或被重启清空）")
            continue
        target = out_dir / f"session_{session_id[:8]}_{stamp}.json"
        payload = {"exported_at": datetime.now().isoformat(timespec="seconds"),
                   "vision_status": status, "session": session}
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"  已写出 {target}")
        summarize(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
