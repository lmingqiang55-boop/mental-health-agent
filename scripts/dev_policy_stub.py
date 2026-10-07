# -*- coding: utf-8 -*-
"""决策模型占位服务（本地开发 / 无 GPU 协作用，**不是训练模型**）。

⚠️  这不是你们训练的 Qwen3-8B 决策模型，不加载任何权重、不占显存。
    它用关键词规则返回动作 JSON，唯一目的是让没有模型文件、没有 GPU 的队友
    也能把整条链路（对话 → 风险识别 → 落库 → 老师端）跑起来。

可以用来做：
    - 前后端联调、接口对接、流程走查
    - 没有模型文件的队友本地开发
    - 答辩前确认"页面到后端"这条路是通的

不可以用来做：
    - 比赛演示或评审时的模型能力展示
    - 任何关于模型效果的结论（它是规则，不是模型）

运行（不需要任何额外依赖，只用标准库）:
    python scripts/dev_policy_stub.py
    python scripts/dev_policy_stub.py --port 8001

    （通常不用手动跑：python scripts/start_dev.py 会在需要时自动拉起它。）

配套配置：`.env` 保持 `.env.example` 的默认值即可，不用改
    POLICY_API_BASE_URL=http://127.0.0.1:8001
    POLICY_API_MODEL=policy-model      # 本服务不校验模型名
"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENDPOINT = "127.0.0.1"

# 按顺序匹配，命中即止；危机相关放在最前。
RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (action, re.compile(pattern))
    for action, pattern in (
        ("自杀倾向", r"自杀|不想活|结束自己|结束生命|遗书|跳楼|割腕|安眠药"
                     r"|一了百了|活不下去|伤害自己|自残|去死|轻生"
                     r"|活着.{0,4}没(什么)?意思|不如死"),
        ("睡眠", r"失眠|入睡|睡不着|睡|早醒|熬夜|噩梦|多梦"),
        ("食欲", r"食欲|胃口|吃不下|饭量|体重|瘦了"),
        ("情绪", r"心情|情绪|难过|抑郁|烦躁|焦虑|低落|想哭|掉眼泪"),
        ("兴趣", r"兴趣|提不起|没乐趣|喜欢的事"),
        ("躯体症状", r"头疼|头痛|头晕|心慌|胸闷|胃疼|乏力|疲惫|没力气"),
        ("社会功能", r"朋友|同学|家人|社交|人际|相处|孤立"),
        ("精神状态", r"精神|精力|注意力|记性|集中|走神"),
        ("筛查", r"筛查|量表|问卷"),
    )
)
EMPATHY_HINTS = ("难受", "痛苦", "委屈", "无助", "绝望", "撑不住", "崩溃", "煎熬")


def decide(conversation_text: str) -> list[str]:
    """关键词规则，返回动作列表（最后一个非共情动作决定主要提问）。"""
    text = conversation_text or ""
    actions: list[str] = []
    if any(hint in text for hint in EMPATHY_HINTS):
        actions.append("共情安慰")
    topic = "其它"
    for action, pattern in RULES:
        if pattern.search(text):
            topic = action
            break
    actions.append(topic)
    return actions


def current_turn_from(payload: dict) -> str:
    """取出本轮用户发言。

    两条都必须注意：
    1. 不能扫 system 消息——系统提示词里列了全部 11 个动作名，扫它会让每个
       关键词都命中。
    2. 不能扫整段历史——历史里前几轮的关键词会一直命中（例如第 1 轮说过
       "睡不着"，后面每一轮都会被判成睡眠）。只取最后一个「用户：」之后的内容。
    """
    parts = [
        message.get("content") or ""
        for message in payload.get("messages", [])
        if isinstance(message, dict) and message.get("role") == "user"
    ]
    history = "\n".join(parts)
    marker = "用户："
    index = history.rfind(marker)
    return history[index + len(marker):] if index != -1 else history


class StubHandler(BaseHTTPRequestHandler):
    server_version = "DevPolicyStub/1.0"

    def _json(self, status: int, body: dict) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 接口
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._json(200, {"object": "list", "data": [
                {"id": "dev-policy-stub", "object": "model", "owned_by": "local-dev"}]})
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 接口
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json(404, {"error": {"message": "not found"}})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._json(400, {"error": {"message": "invalid json"}})
            return

        current_turn = current_turn_from(payload)
        actions = decide(current_turn)
        content = json.dumps({"actions": actions}, ensure_ascii=False)
        print(f"[stub] 命中 {actions}  ←  用户：{current_turn.strip()[:40]}", flush=True)
        self._json(200, {
            "id": "chatcmpl-dev-stub",
            "object": "chat.completion",
            "model": payload.get("model") or "dev-policy-stub",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
        })

    def log_message(self, *args) -> None:  # 静音默认访问日志
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="决策模型占位服务（开发用，非训练模型）")
    parser.add_argument("--port", type=int, default=8001,
                        help="监听端口，默认 8001（与 .env.example 的 POLICY_API_BASE_URL 一致）")
    args = parser.parse_args()

    banner = (
        "\n" + "=" * 68 + "\n"
        "  ⚠️  决策模型【占位服务】已启动 —— 这不是训练模型\n"
        "     它是关键词规则，用于让没有模型文件的队友跑通整条链路。\n"
        "     请勿用于比赛演示、评审或任何模型效果展示。\n"
        f"     监听 http://{ENDPOINT}:{args.port}/v1/chat/completions\n"
        "     .env 保持 .env.example 默认值即可，无需修改。\n"
        + "=" * 68 + "\n"
    )
    print(banner, flush=True)
    server = ThreadingHTTPServer((ENDPOINT, args.port), StubHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[stub] 已停止", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
