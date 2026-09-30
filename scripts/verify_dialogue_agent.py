# -*- coding: utf-8 -*-
"""第 3 步离线验证：DialogueAgent 流程 + DeepSeek 配置加载。

**本脚本不访问任何网络**，全部用 FakeDeepSeekClient 与临时 .env 完成。

运行：python scripts/verify_dialogue_agent.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.dialogue_agent import (  # noqa: E402
    DialogueAgent,
    DialogueAgentError,
)
from backend.llm.config import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_ENV_FILE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    DeepSeekConfigError,
    describe_config_status,
    load_deepseek_config,
)
from backend.models.dialogue import (  # noqa: E402
    DialogueAgentRequest,
    DialogueAgentResponse,
)
from backend.prompts.dialogue_prompt import DIALOGUE_AGENT_SYSTEM_PROMPT  # noqa: E402

FAILURES: List[str] = []
TMP_ENV_DIR = PROJECT_ROOT / "_tmp_envs"

FAKE_REPLY = (
    "听起来这段时间睡不好确实挺让人疲惫的。除了睡眠之外，"
    "最近吃饭和食欲有没有什么变化？"
)


def check(name: str, condition: bool) -> None:
    """打印一条检查结果，失败时记录下来。"""
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILURES.append(name)


def run(coro: Any) -> Any:
    """同步执行一个协程（脚本内无需 pytest-asyncio）。"""
    return asyncio.run(coro)


class FakeDeepSeekClient:
    """离线替身：记录收到的 prompt，返回预设文本，绝不访问网络。"""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_system_prompt: Optional[str] = None
        self.last_user_prompt: Optional[str] = None
        self.call_count = 0

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        self.call_count += 1
        return self.response_text


def build_request() -> DialogueAgentRequest:
    """第十一节指定的完整测试用例。"""
    return DialogueAgentRequest.model_validate(
        {
            "conversation_history": [
                {"role": "assistant", "content": "最近睡眠怎么样？"},
                {
                    "role": "user",
                    "content": "最近晚上总是睡不着。",
                    "visual": {
                        "valence": -0.4,
                        "arousal": 0.3,
                        "engagement": 0.6,
                    },
                },
            ],
            "user_memory": {"facts": ["用户最近正在准备考试"]},
            "decision": {
                "actions": ["共情安慰", "当前话题从睡眠转到食欲"],
                "topic": "食欲",
                "reason": "睡眠话题达到次数限制",
            },
            "current_user_input": {
                "text": "最近每天都睡得很晚，白天也没精神",
                "visual": {"valence": -0.5, "arousal": 0.3, "engagement": 0.6},
            },
        }
    )


def write_tmp_env(name: str, lines: List[str]) -> Path:
    """在项目内（已被 .gitignore 忽略）写一个临时 .env。"""
    TMP_ENV_DIR.mkdir(parents=True, exist_ok=True)
    path = TMP_ENV_DIR / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    print("=" * 64)
    print("DialogueAgent + DeepSeek 配置 离线验证（不访问网络）")
    print("=" * 64)

    # ================= 十一、完整案例 =================
    print("\n-- 完整案例: FakeDeepSeekClient + DialogueAgent --")
    request = build_request()
    fake = FakeDeepSeekClient(FAKE_REPLY)
    agent = DialogueAgent(fake)
    response = run(agent.generate_reply(request))

    check("1) response 是 DialogueAgentResponse", isinstance(response, DialogueAgentResponse))
    check("2) response.reply 与 Fake 返回一致", response.reply == FAKE_REPLY)
    check("3) Fake 收到 DIALOGUE_AGENT_SYSTEM_PROMPT", fake.last_system_prompt == DIALOGUE_AGENT_SYSTEM_PROMPT)

    user_prompt = fake.last_user_prompt or ""
    assert_all = {
        "历史对话分区": "【历史对话】" in user_prompt,
        "历史内容「最近睡眠怎么样？」": "最近睡眠怎么样？" in user_prompt,
        "历史内容「最近晚上总是睡不着。」": "最近晚上总是睡不着。" in user_prompt,
        "历史 user 的 visual（valence=-0.4）": "valence=-0.4" in user_prompt,
        "用户记忆分区": "【用户记忆】" in user_prompt,
        "记忆内容「用户最近正在准备考试」": "用户最近正在准备考试" in user_prompt,
        "当前用户输入分区": "【当前用户输入】" in user_prompt,
        "当前输入文本": "最近每天都睡得很晚，白天也没精神" in user_prompt,
        "当前输入 visual（valence=-0.5）": "valence=-0.5" in user_prompt,
        "decision 分区": "【上游最终决策】" in user_prompt,
        "任务分区": "【任务】" in user_prompt,
    }
    print("    4) user_prompt 内容检查：")
    for label, ok in assert_all.items():
        print(f"        [{'OK  ' if ok else 'MISS'}] {label}")
    check("4) user_prompt 包含历史/visual/记忆/decision/当前输入", all(assert_all.values()))

    decision_checks = {
        "action「共情安慰」": "共情安慰" in user_prompt,
        "action「当前话题从睡眠转到食欲」": "当前话题从睡眠转到食欲" in user_prompt,
        "topic「食欲」": "topic：食欲" in user_prompt,
        "reason「睡眠话题达到次数限制」": "reason：睡眠话题达到次数限制" in user_prompt,
    }
    print("    5) decision 字段完整性：")
    for label, ok in decision_checks.items():
        print(f"        [{'OK  ' if ok else 'MISS'}] {label}")
    check("5) decision 各字段未丢失", all(decision_checks.values()))
    check("附加) Fake 只被调用一次", fake.call_count == 1)

    # ================= 十二、strip =================
    print("\n-- 十二: 返回值 strip --")
    fake_ws = FakeDeepSeekClient("   你好   ")
    response_ws = run(DialogueAgent(fake_ws).generate_reply(request))
    check("空白被剥离，reply == '你好'", response_ws.reply == "你好")

    # ================= 十三、空返回 =================
    print("\n-- 十三: 空返回必须抛异常 --")
    empty_cases = {
        "全空白 '     '": "     ",
        "空串 ''": "",
        "换行 '\\n\\n'": "\n\n",
        "None": None,
    }
    for label, value in empty_cases.items():
        raised = False
        try:
            run(DialogueAgent(FakeDeepSeekClient(value)).generate_reply(request))
        except DialogueAgentError:
            raised = True
        check(f"Fake 返回 {label} 时抛 DialogueAgentError", raised)

    # ================= 十四、配置加载 =================
    print("\n-- 十四: DeepSeek 配置加载（临时 .env，不使用真实 Key） --")

    missing_env = write_tmp_env("missing_key.env", ["DEEPSEEK_BASE_URL=https://example.invalid"])
    missing_failed = False
    try:
        load_deepseek_config(env_file=missing_env, use_process_env=False)
    except DeepSeekConfigError as exc:
        missing_failed = True
        print(f"        -> {exc}")
    check("1) 缺少 DEEPSEEK_API_KEY 时抛出 DeepSeekConfigError", missing_failed)

    default_env = write_tmp_env("defaults.env", ["DEEPSEEK_API_KEY=test-key"])
    cfg_default = load_deepseek_config(env_file=default_env, use_process_env=False)
    check("2) base_url 默认值正确", cfg_default.base_url == DEFAULT_BASE_URL)
    check("2) model 默认值正确", cfg_default.model == DEFAULT_MODEL)
    check("2) temperature 默认值正确", cfg_default.temperature == DEFAULT_TEMPERATURE)
    check("2) max_tokens 默认值正确", cfg_default.max_tokens == DEFAULT_MAX_TOKENS)
    check("2) timeout 默认值正确", cfg_default.timeout == DEFAULT_TIMEOUT)

    typed_env = write_tmp_env(
        "typed.env",
        [
            "DEEPSEEK_API_KEY=test-key",
            "DEEPSEEK_TEMPERATURE=0.3",
            "DEEPSEEK_MAX_TOKENS=200",
            "DEEPSEEK_TIMEOUT=30",
        ],
    )
    cfg_typed = load_deepseek_config(env_file=typed_env, use_process_env=False)
    check("3) temperature 解析为 float 且值正确", isinstance(cfg_typed.temperature, float) and cfg_typed.temperature == 0.3)
    check("3) max_tokens 解析为 int 且值正确", isinstance(cfg_typed.max_tokens, int) and cfg_typed.max_tokens == 200)
    check("3) timeout 解析为 float 且值正确", isinstance(cfg_typed.timeout, float) and cfg_typed.timeout == 30.0)

    bad_env = write_tmp_env("bad.env", ["DEEPSEEK_API_KEY=test-key", "DEEPSEEK_MAX_TOKENS=abc"])
    bad_failed = False
    try:
        load_deepseek_config(env_file=bad_env, use_process_env=False)
    except DeepSeekConfigError as exc:
        bad_failed = True
        print(f"        -> {exc}")
    check("附加) 类型转换失败抛出清晰的 DeepSeekConfigError", bad_failed)

    # ================= 密钥安全 =================
    print("\n-- 密钥安全: 不泄露真实 Key --")
    secret = cfg_default.api_key
    status = describe_config_status(cfg_default)
    print("    describe_config_status 输出：")
    for line in status.splitlines():
        print(f"        {line}")
    check("状态摘要包含 api_key_present=True", "api_key_present=True" in status)
    check("状态摘要不含 Key 内容", secret not in status)
    check("repr(config) 不含 Key 内容", secret not in repr(cfg_default))

    # 环境中的真实 Key（若存在）不得出现在任何输出里
    real_key = None
    if DEFAULT_ENV_FILE.is_file():
        from backend.llm.config import parse_env_file

        real_key = parse_env_file(DEFAULT_ENV_FILE).get("DEEPSEEK_API_KEY")
    if real_key:
        check("状态摘要不含 .env 中的真实 Key", real_key not in status)
        check("repr(config) 不含 .env 中的真实 Key", real_key not in repr(cfg_default))
        # 源码中不得硬编码真实 Key
        leaked_files = []
        for candidate in [
            PROJECT_ROOT / "backend" / "llm" / "config.py",
            PROJECT_ROOT / "backend" / "llm" / "deepseek_client.py",
            PROJECT_ROOT / "backend" / "agents" / "dialogue_agent.py",
            PROJECT_ROOT / ".env.example",
            Path(__file__),
        ]:
            if real_key in candidate.read_text(encoding="utf-8"):
                leaked_files.append(candidate.name)
        check("真实 Key 未硬编码进源码/测试/.env.example", not leaked_files)
    else:
        print("        （未发现本地 .env 中的 Key，跳过真实 Key 泄露检查）")

    example_text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    check(
        ".env.example 只含占位符",
        "DEEPSEEK_API_KEY=your_deepseek_api_key_here" in example_text,
    )

    # ================= 根目录真实 .env =================
    print("\n-- 本地 .env 配置加载（只报告状态，不显示 Key） --")
    if DEFAULT_ENV_FILE.is_file():
        real_cfg = load_deepseek_config()
        print("    " + describe_config_status(real_cfg).replace("\n", "\n    "))
        check("根目录 .env 可成功加载", bool(real_cfg.api_key))
    else:
        check("根目录 .env 存在", False)

    print("=" * 64)
    if FAILURES:
        print(f"结果：失败 {len(FAILURES)} 项 -> {FAILURES}")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
