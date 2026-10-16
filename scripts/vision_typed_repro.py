# -*- coding: utf-8 -*-
"""复现断点 A：**只打字不点麦克风，摄像头采集永远不会启动**。

背景与结论见 docs/vision_capture_defect_report_20261016.md 第二节。

机制：
  sendManualText() -> segment() 的第一行 `if (!active.value || ...) return null`
  active 只在 useVision.start() 里置真，而 start() 只被 begin() 调用，
  begin() 只被麦克风按钮的 @click 触发。打字路径完全绕过 begin()。
  且采集状态行在 v-if="started && !closing" 里，started 一直为 false，
  所以界面上连"摄像头没开"的提示都不会出现。

对照的第二组会先点一次麦克风按钮（!started 时它只执行 begin()，不会开始录音），
用来验证这条绕过办法确实能让帧上传。

    python scripts/vision_typed_repro.py [前端地址]
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


def run(page, frontend: str, click_mic_first: bool, wait_ms: int) -> dict:
    session_id = http_json("POST", "/api/session")["session_id"]
    frame_calls = {"count": 0}

    def on_response(response):
        if "/api/vision/frame" in response.url:
            frame_calls["count"] += 1

    page.on("response", on_response)
    page.goto(f"{frontend}/assess/session/{session_id}", wait_until="domcontentloaded")
    page.wait_for_selector(".session__manual-input", timeout=30_000)
    page.wait_for_timeout(1200)

    if click_mic_first:
        page.click(".session__mic, .session__dock button", timeout=10_000)
        page.wait_for_timeout(wait_ms)

    page.fill(".session__manual-input", "我最近特别累")
    page.press(".session__manual-input", "Enter")
    page.wait_for_selector(".session__turn--assistant", timeout=120_000)
    page.wait_for_timeout(3000)

    element = page.query_selector(".session__vision")
    state = http_json("GET", f"/api/session/{session_id}")
    bound = sum(1 for message in (state.get("conversation_history") or [])
                if message.get("vision_snapshot"))
    page.remove_listener("response", on_response)
    return {
        "会话": session_id[:8],
        "采集状态行": element.inner_text().strip() if element else "（不存在）",
        "active_vision_capture_id": state.get("active_vision_capture_id"),
        "frame 响应条数": frame_calls["count"],
        "带快照的消息": bound,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("frontend", nargs="?", default=FRONTEND)
    args = parser.parse_args()

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

        for label, click_first, wait_ms in (
            ("① 只打字（默认测试方式）", False, 0),
            ("② 先点一次麦克风，等 12 秒，再打字", True, 12_000),
        ):
            result = run(page, args.frontend, click_first, wait_ms)
            print(f"\n【{label}】")
            for key, value in result.items():
                print(f"    {key}: {value}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
