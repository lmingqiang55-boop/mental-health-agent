# -*- coding: utf-8 -*-
"""复现：直达会话链接 vs 完整流程，摄像头采帧结果完全不同。

背景与结论见 docs/vision_capture_defect_report_20261016.md 第三节。

    A. 直接打开 /assess/session/{id}（等价于"只把会话链接发给别人"）
       -> sessionStorage 里没有 xq_device_cam -> 「仅语音模式（摄像头未开启）」-> 0 帧
    B. 走完整流程：/assess/consent -> /assess/check（拨开摄像头）-> 开始测评 -> 点麦克风
       -> 「摄像头已开启 · 已上传 N 帧」-> 后端 state 变 ready

用 Chromium 的假摄像头（--use-fake-device-for-media-stream），不需要真摄像头。

    python scripts/vision_capture_repro.py [前端地址]
"""

from __future__ import annotations

import argparse
import json
import urllib.request

FRONTEND = "http://127.0.0.1:4180"
BACKEND = "http://127.0.0.1:8011"

#: 无头环境下把浏览器语音降级实现换成会触发 onend 的桩，
#: 否则 speak() 的 Promise 永不 resolve，输入框会一直禁用（与视觉无关的干扰项）。
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


def status_text(page) -> str:
    element = page.query_selector(".session__vision")
    if element is None:
        return "（页面上没有采集状态元素：还没开始对话）"
    return element.inner_text().replace("\n", " ").strip()


def launch(playwright):
    return playwright.chromium.launch(
        channel="msedge", headless=True,
        args=["--no-proxy-server",
              "--use-fake-ui-for-media-stream",
              "--use-fake-device-for-media-stream",
              "--mute-audio"])


def new_page(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.add_init_script(TTS_STUB)
    return page


def path_a(browser, frontend: str) -> None:
    print("=" * 72)
    print("路径 A：直接打开会话链接（没有走过设备检查页）")
    print(f"  启动前后端视觉状态：{vision_state()}")
    page = new_page(browser)
    session_id = http_json("POST", "/api/session")["session_id"]
    page.goto(f"{frontend}/assess/session/{session_id}", wait_until="domcontentloaded")
    page.wait_for_selector(".session__manual-input", timeout=30_000)
    page.wait_for_timeout(1200)
    cam_flag = page.evaluate("() => sessionStorage.getItem('xq_device_cam')")
    print(f"  sessionStorage['xq_device_cam'] = {cam_flag}")
    page.click(".session__mic, .session__dock button", timeout=10_000)
    page.wait_for_timeout(6000)
    print(f"  点开始后采集状态：{status_text(page)}")
    print(f"  后端视觉状态：{vision_state()}")
    state = http_json("GET", f"/api/session/{session_id}")
    print(f"  active_vision_capture_id = {state.get('active_vision_capture_id')}")
    print(f"  vision_segments 条数 = {len(state.get('vision_segments') or {})}")
    page.close()


def path_b(browser, frontend: str) -> None:
    print()
    print("=" * 72)
    print("路径 B：完整流程（知情同意 → 设备检查拨开摄像头 → 开始测评）")
    page = new_page(browser)
    page.goto(f"{frontend}/assess/consent", wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    page.click("text=家长和学生已知情并同意", timeout=20_000)
    page.wait_for_url("**/assess/check", timeout=30_000)
    page.wait_for_timeout(2500)                     # 等麦克风自检
    switch = page.query_selector(".px-switch")
    print(f"  摄像头开关初始 aria-checked = "
          f"{switch.get_attribute('aria-checked') if switch else '未找到'}")
    if switch and switch.get_attribute("aria-checked") != "true":
        switch.click()
        page.wait_for_timeout(2500)
    switch = page.query_selector(".px-switch")
    print(f"  拨开后 aria-checked = "
          f"{switch.get_attribute('aria-checked') if switch else '未找到'}")
    cam_flag = page.evaluate("() => sessionStorage.getItem('xq_device_cam')")
    print(f"  sessionStorage['xq_device_cam'] = {cam_flag}")
    start_button = page.query_selector("text=开始测评")
    print(f"  「开始测评」可点 = {not start_button.is_disabled() if start_button else '未找到'}")
    start_button.click()
    page.wait_for_url("**/assess/session/**", timeout=30_000)
    page.wait_for_selector(".session__manual-input", timeout=30_000)
    page.wait_for_timeout(1200)
    session_id = page.url.rstrip("/").split("/")[-1]
    page.click(".session__mic, .session__dock button", timeout=10_000)
    page.wait_for_timeout(8000)
    print(f"  点开始 8 秒后采集状态：{status_text(page)}")
    print(f"  后端视觉状态：{vision_state()}")
    state = http_json("GET", f"/api/session/{session_id}")
    print(f"  active_vision_capture_id = {state.get('active_vision_capture_id')}")
    page.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("frontend", nargs="?", default=FRONTEND)
    parser.add_argument("--only", default="AB", help="只跑某条路径，如 --only B")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = launch(p)
        if "A" in args.only:
            path_a(browser, args.frontend)
        if "B" in args.only:
            path_b(browser, args.frontend)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
