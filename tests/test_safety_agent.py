# -*- coding: utf-8 -*-
"""新版 Safety Agent 的单元测试。

这一层是系统唯一的安全判定入口，因此这里锁定的是**判定契约**：
- 模型无法编造路由或热线号码；
- 任何失败都不放行（fail-to-REVIEW）；
- 孤立危险关键词不产生结论；
- 否定与转述必须在提示词层面被要求处理；
- 每次判定使用新的客户端（事件循环安全的回归保护）。
"""

import asyncio

import pytest

from backend.safety import agent as agent_module
from backend.safety.agent import (
    SAFETY_FALLBACK_MESSAGE,
    SAFETY_SYSTEM_PROMPT,
    SafetyAgent,
    parse_safety_content,
    scan_keywords,
)
from backend.safety.hotlines import (
    DEPLOYMENT_REGION_ENV,
    allowed_hotline_numbers,
    configured_hotlines,
    hotline_configuration_warning,
    load_hotlines,
)
from backend.safety.projection import (
    most_severe_verdict,
    project_to_risk_result,
    safety_level_priority,
    verdict_is_more_severe,
)
from backend.safety.schemas import (
    ModelStatus,
    SafetyLevel,
    SafetyModelOutput,
    SafetyRoute,
    SafetySignal,
    SafetyVerdict,
    assemble_verdict,
    build_failed_verdict,
    derive_route,
)
from backend.safety.support import (
    SUPPORT_MODE_CONTINUATION_MESSAGE,
    safety_blocks_normal_flow,
    safety_next_strategy,
    safety_reply_messages,
    safety_session_stage,
    safety_stage_value,
)
from backend.models.enums import SessionStage


# ---------------------------------------------------------------------------
# 假客户端
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, *, content: str = "", error: Exception | None = None,
                 delay: float = 0.0) -> None:
        self.content = content
        self.error = error
        self.delay = delay
        self.closed = False
        self.prompts: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append((system_prompt, user_prompt))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.content

    async def close(self) -> None:  # pragma: no cover - 由 _aclose 通过 .client 调用
        self.closed = True


def _agent(client: _FakeClient, **kwargs) -> SafetyAgent:
    return SafetyAgent(lambda: client, deployment_region="CN", **kwargs)


# ---------------------------------------------------------------------------
# 联系方式：只下发达标号码，未知地区不下发
# ---------------------------------------------------------------------------

def test_registry_entries_carry_verification_provenance() -> None:
    """下发给学生的号码必须有可追溯的核实依据。"""
    entries = configured_hotlines()
    assert entries, "至少应配置一条已核实热线"
    for entry in entries:
        assert entry.verified_at is not None
        assert entry.verified_by
        assert entry.source_url.startswith("https://")


def test_hotlines_only_for_known_region(monkeypatch) -> None:
    assert [h.number for h in load_hotlines("CN")] == ["12356"]
    # 未知地区绝不假定适用。``None`` 的含义是"去读环境变量"，所以先把它清掉，
    # 否则这条断言的结果会随开发机 .env 里有没有配置地区而变化。
    monkeypatch.delenv(DEPLOYMENT_REGION_ENV, raising=False)
    for unknown in (None, "", "   ", "unknown", "US"):
        assert load_hotlines(unknown) == []


def test_agent_without_known_region_sends_no_number(monkeypatch) -> None:
    """没有可用地区时不下发任何号码；环境变量未配置等同于未知地区。

    这里刻意覆盖三种形态，避免测试结果依赖运行环境的 .env：
    未配置 / 显式 unknown / 配置为有已核实条目的地区。
    """
    monkeypatch.delenv(DEPLOYMENT_REGION_ENV, raising=False)
    unset = SafetyAgent(lambda: _FakeClient(content=""), deployment_region=None)
    assert unset.hotlines == []

    unknown = SafetyAgent(lambda: _FakeClient(content=""), deployment_region="unknown")
    assert unknown.hotlines == []

    # 配置了正确地区时才下发，并且确实带出那条已核实号码。
    known = SafetyAgent(lambda: _FakeClient(content=""), deployment_region="CN")
    assert known.hotlines == ["12356"]


def test_unconfigured_region_is_loud_not_silent(monkeypatch) -> None:
    """未配置部署地区时刻意不下发号码，但必须留下可见告警。

    这是运维要求：一旦以这种形态上线，高危学生看到的话术里没有可拨号码。
    允许这样部署（不假定未知地区适用任何国家的号码），但不允许静默。
    """
    monkeypatch.delenv(DEPLOYMENT_REGION_ENV, raising=False)
    warning = hotline_configuration_warning()
    assert warning is not None and DEPLOYMENT_REGION_ENV in warning

    # 设置了地区但注册表里没有该地区的号码，同样要告警，且要点出具体地区。
    regional = hotline_configuration_warning("US")
    assert regional is not None and "US" in regional

    # 配置正确的地区时没有告警，并且确实能下发号码。
    assert hotline_configuration_warning("CN") is None
    assert [h.number for h in load_hotlines("CN")] == ["12356"]


def test_hotline_warning_reads_the_deployment_environment(monkeypatch) -> None:
    monkeypatch.setenv(DEPLOYMENT_REGION_ENV, "CN")
    assert hotline_configuration_warning() is None
    monkeypatch.setenv(DEPLOYMENT_REGION_ENV, "unknown")
    assert hotline_configuration_warning() is not None


def test_most_severe_verdict_never_downgrades() -> None:
    """合并「本轮结论」与「会话已有结论」时只允许变严。"""
    normal = assemble_verdict(output=SafetyModelOutput(
        risk_level=SafetyLevel.NORMAL, rationale="平稳", support_message=""), status=ModelStatus.ok)
    high = assemble_verdict(output=SafetyModelOutput(
        risk_level=SafetyLevel.HIGH, rationale="有风险", support_message="请先确保有人陪着你。"),
        status=ModelStatus.ok)

    assert safety_level_priority(high) > safety_level_priority(normal)
    assert verdict_is_more_severe(high, normal) and not verdict_is_more_severe(normal, high)
    # 顺序无关，取更严重的那份
    assert most_severe_verdict(normal, high) is high
    assert most_severe_verdict(high, normal) is high
    assert most_severe_verdict(normal, None) is normal
    assert most_severe_verdict(None, None) is None


# ---------------------------------------------------------------------------
# 等级 -> 路由：由后端派生，不由模型决定
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("level", "route"), [
    (SafetyLevel.NORMAL, SafetyRoute.CONTINUE),
    (SafetyLevel.UNCERTAIN, SafetyRoute.SAFETY_REVIEW),
    (SafetyLevel.HIGH, SafetyRoute.SAFETY_STOP),
    (SafetyLevel.IMMINENT, SafetyRoute.SAFETY_STOP),
])
def test_route_is_derived_from_level(level, route) -> None:
    assert derive_route(level) is route


def test_model_output_cannot_declare_route_or_numbers() -> None:
    """模型输出结构里根本没有 route / hotline_numbers / risk_detected。"""
    fields = set(SafetyModelOutput.model_fields)
    assert "route" not in fields
    assert "hotline_numbers" not in fields
    assert "risk_detected" not in fields
    with pytest.raises(Exception):
        SafetyModelOutput.model_validate(
            {"risk_level": "NORMAL", "route": "SAFETY_STOP"})


def test_verdict_rejects_inconsistent_level_and_route() -> None:
    with pytest.raises(Exception):
        SafetyVerdict(risk_detected=True, risk_level=SafetyLevel.NORMAL,
                      route=SafetyRoute.SAFETY_STOP, model_status=ModelStatus.ok)
    with pytest.raises(Exception):
        SafetyVerdict(risk_detected=False, risk_level=SafetyLevel.HIGH,
                      route=SafetyRoute.SAFETY_STOP, model_status=ModelStatus.ok)


def test_failed_model_never_continues() -> None:
    """模型未成功时 route 不得是 CONTINUE。"""
    with pytest.raises(Exception):
        SafetyVerdict(risk_detected=False, risk_level=SafetyLevel.NORMAL,
                      route=SafetyRoute.CONTINUE, model_status=ModelStatus.timeout)


def test_non_normal_level_requires_a_message() -> None:
    with pytest.raises(Exception):
        SafetyModelOutput(risk_level=SafetyLevel.HIGH)
    # NORMAL 允许没有消息
    assert SafetyModelOutput(risk_level=SafetyLevel.NORMAL).support_message == ""


# ---------------------------------------------------------------------------
# 失败一律进入人工复核
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [
    ModelStatus.timeout, ModelStatus.parse_error, ModelStatus.unavailable])
def test_every_failure_mode_goes_to_review(status) -> None:
    verdict = build_failed_verdict(status, [], SAFETY_FALLBACK_MESSAGE)
    assert verdict.risk_level is SafetyLevel.UNCERTAIN
    assert verdict.route is SafetyRoute.SAFETY_REVIEW
    assert verdict.risk_detected is True
    assert verdict.hotline_numbers == []
    assert verdict.model_status is status
    assert verdict.messages == [SAFETY_FALLBACK_MESSAGE]


def test_failed_verdict_rejects_ok_status() -> None:
    with pytest.raises(ValueError):
        build_failed_verdict(ModelStatus.ok)


# ---------------------------------------------------------------------------
# 关键词只作线索
# ---------------------------------------------------------------------------

def test_keywords_are_signals_not_conclusions() -> None:
    signals = scan_keywords("我想自杀")
    assert any(s.term == "自杀" and not s.negated for s in signals)
    # 模型判 NORMAL 时，即使关键词命中也不得升级为 STOP
    verdict = assemble_verdict(
        output=SafetyModelOutput(risk_level=SafetyLevel.NORMAL),
        status=ModelStatus.ok,
        extra_signals=signals,
    )
    assert verdict.route is SafetyRoute.CONTINUE
    assert verdict.risk_detected is False
    # 但线索要被记录下来供人工复核
    assert [s.term for s in verdict.keyword_signals] == ["自杀"]


def test_negated_keyword_statement_is_marked_negated() -> None:
    """否定表述必须被标记，不能当作肯定意图。"""
    negated = scan_keywords("我不会自杀的，你别担心")
    assert any(s.term == "自杀" and s.negated for s in negated)
    asserted = scan_keywords("我想自杀")
    assert any(s.term == "自杀" and not s.negated for s in asserted)


def test_keyword_scan_deduplicates_terms() -> None:
    signals = scan_keywords("自杀，自杀，还是自杀")
    assert len([s for s in signals if s.term == "自杀"]) == 1


# ---------------------------------------------------------------------------
# 提示词：否定、转述、号码
# ---------------------------------------------------------------------------

def test_prompt_requires_negation_and_third_party_handling() -> None:
    """提示词必须明确要求处理否定与转述，否则会误判为高风险。"""
    for marker in ("否定", "转述", "他人"):
        assert marker in SAFETY_SYSTEM_PROMPT, f"提示词缺少「{marker}」处理要求"


def test_prompt_forbids_phone_numbers_in_reply() -> None:
    """面向学生的消息里不得出现号码，号码由后端注入。"""
    assert "号码" in SAFETY_SYSTEM_PROMPT
    output = SafetyModelOutput(risk_level=SafetyLevel.HIGH,
                               support_message="请拨打 12356 求助。")
    with pytest.raises(ValueError):
        assemble_verdict(output=output, status=ModelStatus.ok,
                         hotlines=["12356"],
                         allowed_hotlines=allowed_hotline_numbers())


def test_prompt_carries_message_and_history_and_signals() -> None:
    from backend.safety.prompt import build_safety_user_prompt
    prompt = build_safety_user_prompt(
        "我不想活了",
        [("user", "最近压力大"), ("assistant", "我在听")],
        scan_keywords("我不想活了"),
    )
    assert "我不想活了" in prompt
    assert "最近压力大" in prompt
    assert "我在听" in prompt
    assert "不想活" in prompt


def test_history_is_not_mutated() -> None:
    from backend.safety.prompt import build_safety_user_prompt
    history = [("user", "a")]
    build_safety_user_prompt("b", history, [])
    assert history == [("user", "a")]


# ---------------------------------------------------------------------------
# 号码白名单强制
# ---------------------------------------------------------------------------

def test_unverified_number_is_rejected() -> None:
    with pytest.raises(ValueError):
        assemble_verdict(
            output=SafetyModelOutput(risk_level=SafetyLevel.HIGH,
                                     support_message="请联系可信任的成人。"),
            status=ModelStatus.ok, hotlines=["400-000-0000"],
            allowed_hotlines=allowed_hotline_numbers())


def test_numbers_only_accompany_stop() -> None:
    allowed = allowed_hotline_numbers()
    review = assemble_verdict(
        output=SafetyModelOutput(risk_level=SafetyLevel.UNCERTAIN,
                                 support_message="我想确认一下。"),
        status=ModelStatus.ok, hotlines=["12356"], allowed_hotlines=allowed)
    assert review.hotline_numbers == []
    stop = assemble_verdict(
        output=SafetyModelOutput(risk_level=SafetyLevel.IMMINENT,
                                 support_message="请联系可信任的成人。"),
        status=ModelStatus.ok, hotlines=["12356"], allowed_hotlines=allowed)
    assert stop.hotline_numbers == ["12356"]


# ---------------------------------------------------------------------------
# 解析容错
# ---------------------------------------------------------------------------

def test_parse_tolerates_fences_and_surrounding_text() -> None:
    fenced = parse_safety_content(
        '```json\n{"risk_level":"HIGH","support_message":"在的"}\n```')
    assert fenced.risk_level is SafetyLevel.HIGH
    noisy = parse_safety_content('结论如下 {"risk_level":"NORMAL"} 完毕')
    assert noisy.risk_level is SafetyLevel.NORMAL


@pytest.mark.parametrize("bad", ["", "no json here", "{", '{"risk_level":"WAT"}',
                                 '{"unknown":1}', "[1,2,3]"])
def test_parse_rejects_unusable_output(bad) -> None:
    with pytest.raises(agent_module.SafetyAgentError):
        parse_safety_content(bad)


# ---------------------------------------------------------------------------
# Agent 行为
# ---------------------------------------------------------------------------

def test_agent_returns_verdict_for_valid_model_output() -> None:
    client = _FakeClient(content='{"risk_level":"NORMAL","support_message":""}')
    verdict = asyncio.run(_agent(client).judge("最近睡不好", []))
    assert verdict.risk_level is SafetyLevel.NORMAL
    assert verdict.route is SafetyRoute.CONTINUE
    assert verdict.model_status is ModelStatus.ok


def test_agent_uses_a_fresh_client_for_every_call() -> None:
    """回归保护：AsyncOpenAI 绑定在创建它的事件循环上。

    本项目是「同步端点 + 每请求 asyncio.run()」，复用同一客户端会让
    第二次之后的判定全部失败。因此每次判定都必须新建客户端。
    """
    created: list[_FakeClient] = []

    def factory() -> _FakeClient:
        client = _FakeClient(content='{"risk_level":"NORMAL"}')
        created.append(client)
        return client

    agent = SafetyAgent(factory, deployment_region="CN")
    for _ in range(3):
        asyncio.run(agent.judge("普通发言", []))
    assert len(created) == 3
    # 每个客户端都被关闭，不泄漏连接
    assert all(client.closed for client in created)


def test_agent_turns_timeout_into_review() -> None:
    client = _FakeClient(content='{"risk_level":"NORMAL"}', delay=0.5)
    verdict = asyncio.run(_agent(client, timeout=0.05).judge("随便说说", []))
    assert verdict.model_status is ModelStatus.timeout
    assert verdict.route is SafetyRoute.SAFETY_REVIEW


def test_agent_turns_parse_failure_into_review() -> None:
    verdict = asyncio.run(_agent(_FakeClient(content="抱歉，我不确定")).judge("随便说说", []))
    assert verdict.model_status is ModelStatus.parse_error
    assert verdict.route is SafetyRoute.SAFETY_REVIEW


def test_agent_never_raises_on_unexpected_error() -> None:
    """未知异常绝不能冒泡成 500 从而绕过安全判定。"""
    client = _FakeClient(error=RuntimeError("boom"))
    verdict = asyncio.run(_agent(client).judge("随便说说", []))
    assert verdict.model_status is ModelStatus.unavailable
    assert verdict.route is SafetyRoute.SAFETY_REVIEW
    assert verdict.hotline_numbers == []


def test_agent_never_raises_when_client_cannot_be_built() -> None:
    def broken() -> _FakeClient:
        raise RuntimeError("no config")

    verdict = asyncio.run(SafetyAgent(broken).judge("随便说说", []))
    assert verdict.route is SafetyRoute.SAFETY_REVIEW
    assert verdict.model_status is ModelStatus.unavailable


def test_stop_verdict_carries_hotline_but_messages_never_contain_numbers() -> None:
    client = _FakeClient(content=(
        '{"risk_level":"IMMINENT","support_message":"请立刻联系身边可信任的成人。"}'))
    verdict = asyncio.run(_agent(client).judge("我今晚就去跳楼", []))
    assert verdict.route is SafetyRoute.SAFETY_STOP
    assert verdict.hotline_numbers == ["12356"]
    for message in verdict.messages:
        assert "12356" not in message


def test_image_or_long_history_does_not_break_prompt() -> None:
    client = _FakeClient(content='{"risk_level":"NORMAL"}')
    history = [("user", f"第{i}轮") for i in range(60)]
    verdict = asyncio.run(_agent(client).judge("还在", history))
    assert verdict.model_status is ModelStatus.ok


# ---------------------------------------------------------------------------
# 单向投影（仅供评估报告字段）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("level", "report_level", "intervention"), [
    (SafetyLevel.NORMAL, "low", False),
    (SafetyLevel.UNCERTAIN, "medium", True),
    (SafetyLevel.HIGH, "high", True),
    (SafetyLevel.IMMINENT, "high", True),
])
def test_projection_is_one_way_and_total(level, report_level, intervention) -> None:
    allowed = allowed_hotline_numbers()
    verdict = assemble_verdict(
        output=SafetyModelOutput(
            risk_level=level,
            support_message="" if level is SafetyLevel.NORMAL else "在的"),
        status=ModelStatus.ok,
        hotlines=["12356"] if level in (SafetyLevel.HIGH, SafetyLevel.IMMINENT) else [],
        allowed_hotlines=allowed)
    risk = project_to_risk_result(verdict)
    assert risk.risk_level.value == report_level
    assert risk.requires_intervention is intervention


def test_projection_never_degrades_after_model_failure() -> None:
    """判定失败时评估报告必须是「需关注」，不能是低风险。"""
    verdict = build_failed_verdict(ModelStatus.unavailable, [], SAFETY_FALLBACK_MESSAGE)
    risk = project_to_risk_result(verdict)
    assert risk.requires_intervention is True
    assert risk.risk_level.value != "low"


# ---------------------------------------------------------------------------
# 安全分支的操作规则
# ---------------------------------------------------------------------------

def test_normal_verdict_keeps_normal_flow() -> None:
    assert safety_stage_value(
        assemble_verdict(output=SafetyModelOutput(risk_level=SafetyLevel.NORMAL),
                         status=ModelStatus.ok), "none") == "none"
    assert safety_session_stage("none") is None


def test_review_can_return_to_none_but_stopped_cannot() -> None:
    review = assemble_verdict(
        output=SafetyModelOutput(risk_level=SafetyLevel.UNCERTAIN, support_message="确认一下"),
        status=ModelStatus.ok)
    normal = assemble_verdict(
        output=SafetyModelOutput(risk_level=SafetyLevel.NORMAL), status=ModelStatus.ok)
    assert safety_stage_value(review, "none") == "review"
    # 澄清后恢复正常表达可以回到普通评估
    assert safety_stage_value(normal, "review") == "none"
    # 停止锁一旦落下，任何后续判定都不能把它退回 review/none
    assert safety_stage_value(normal, "stopped") == "stopped"
    assert safety_stage_value(review, "stopped") == "stopped"
    assert safety_session_stage("stopped") is SessionStage.SAFETY_STOP
    assert safety_session_stage("review") is SessionStage.SAFETY_REVIEW


def test_safety_blocks_normal_flow() -> None:
    assert safety_blocks_normal_flow(safety_halted=False, safety_stage="none") is False
    assert safety_blocks_normal_flow(safety_halted=False, safety_stage="review") is True
    assert safety_blocks_normal_flow(safety_halted=False, safety_stage="stopped") is True
    assert safety_blocks_normal_flow(safety_halted=True, safety_stage="none") is True


def test_support_mode_always_produces_a_reply() -> None:
    """支持模式持续对话：即使本轮判 NORMAL，也要有面向用户的回应。"""
    normal = assemble_verdict(
        output=SafetyModelOutput(risk_level=SafetyLevel.NORMAL), status=ModelStatus.ok)
    assert safety_reply_messages(normal, already_halted=True) == [
        SUPPORT_MODE_CONTINUATION_MESSAGE]
    assert safety_next_strategy(normal, already_halted=True) == "safety_support"
    # 未处于支持模式且判 NORMAL 时不产生多余消息
    assert safety_reply_messages(normal, already_halted=False) == []


def test_review_mode_has_a_fallback_message() -> None:
    review = assemble_verdict(
        output=SafetyModelOutput(risk_level=SafetyLevel.UNCERTAIN, support_message="在的"),
        status=ModelStatus.ok)
    assert safety_reply_messages(review, already_halted=False) == ["在的"]
    assert safety_next_strategy(review, already_halted=False) == "safety_review"
