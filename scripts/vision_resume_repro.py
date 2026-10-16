# -*- coding: utf-8 -*-
"""复现：**续测会话（turn_count > 0）永远不会启动摄像头采集**。

背景与结论见 docs/vision_capture_defect_report_20261016.md 第二节。

机制：只有 begin() 会调用 startVision()，而 begin() 只被
`@click="!started ? begin() : ..."` 触发；init() 在恢复历史后把
`started.value = state.turn_count > 0`，于是续测时 begin() 再也不会被调用，
采集永不启动——而界面会一直停在「摄像头开启中…」，看起来像在开。

脚本先造一个已聊过 2 轮的会话，再预置摄像头开关为开，然后打开会话页观察。

    python scripts/vision_resume_repro.py [前端地址]
"""

from __future__ import annotations

import argparse
import json
import urllib.request

FRONTEND = "http://127.0.0.1:4180"
BACKEND = "http://127.0.0.1:8011"

TTS_STUB = (
    "window.speechSynthesis = { speak(u){ setTimeout(() => u.onend && u.onend(), 20); },"
    " cancel(){}, getVoices(){return []}, addEventListener(){}, removeEventListener(){} };"
    "window.SpeechSynthesisUtterance = function(t){ this.text = t; };"
)


def http_json(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{BACKEND}{path}", data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def vision_state() -> str:
    return http_json("GET", "/api/vision/status")["state"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("frontend", nargs="?", default=FRONTEND)
    parser.add_argument("--turns", type=int, default=2, help="先把会话聊到几轮")
    args = parser.parse_args()

    session_id = http_json("POST", "/api/session")["session_id"]
    for text in ("我13岁", "初一", "学习太难")[: args.turns]:
        http_json("POST", "/api/chat", {"session_id": session_id, "text": text})
    state = http_json("GET", f"/api/session/{session_id}")
    print(f"会话 {session_id[:8]} turn_count = {state['turn_count']}"
          f"（已聊过，属于续测）")
    print(f"此时后端视觉状态 = {vision_state()}（进程级，别用它判断本会话）")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="msedge", headless=True,
            args=["--no-proxy-server", "--use-fake-ui-for-media-stream",
                  "--use-fake-device-for-media-stream", "--mute-audio"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script(TTS_STUB)
        # 等价于"用户已经在设备检查页把摄像头拨开了"
        page.add_init_script("sessionStorage.setItem('xq_device_cam', '1');")
        page.goto(f"{args.frontend}/assess/session/{session_id}", wait_until="domcontentloaded")
        page.wait_for_selector(".session__manual-input", timeout=30_000)
        page.wait_for_timeout(3000)

        cam_flag = page.evaluate("() => sessionStorage.getItem('xq_device_cam')")
        print(f"  sessionStorage['xq_device_cam'] = {cam_flag}")
        element = page.query_selector(".session__vision")
        print(f"  采集状态文案：{element.inner_text().strip() if element else '（未进入对话态）'}")
        page.wait_for_timeout(8000)
        element = page.query_selector(".session__vision")
        print(f"  再等 8 秒：{element.inner_text().strip() if element else '（无）'}")
        print(f"  后端视觉状态 = {vision_state()}")
        after = http_json("GET", f"/api/session/{session_id}")
        print(f"  active_vision_capture_id = {after.get('active_vision_capture_id')}"
              "   <- None 就是连 capture 请求都没发出过")
        print(f"  vision_segments 条数 = {len(after.get('vision_segments') or {})}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
