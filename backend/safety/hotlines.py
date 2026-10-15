# -*- coding: utf-8 -*-
"""已核实心理援助热线配置（新 Safety 专用）。

【为什么单独一个模块】
热线号码属于**部署配置**，不是会话数据，也不是模型可以生成的内容。
历史上这些号码硬编码在前端十多个 Vue 文件里；现在统一收敛到后端，
由 :func:`load_hotlines` 校验后随安全结论下发。

【两条硬规则】
1. 缺少核实信息（``verified_at`` / ``verified_by`` / ``source_url``）的条目
   **拒绝加载**——宁可少给号码，也不给学生一个打不通的号码。
2. 只有 ``region_code`` 与部署地区一致的条目才会下发。
   部署地区未配置时返回空列表，**绝不假定未知地区适用中国大陆号码**。

【待核实候选（当前故意未登记）】
调研文档 docs/research/ 中出现过 北京心理危机研究与干预中心 010-82951332、
全国希望24热线 400-161-9995。这两个号码**在本仓库内没有官方来源可依**，
因此不进入注册表；如要启用，请补齐 verified_at / verified_by / source_url。
"""

from __future__ import annotations

import os
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "Hotline",
    "DEPLOYMENT_REGION_ENV",
    "configured_hotlines",
    "load_hotlines",
    "allowed_hotline_numbers",
    "hotline_labels",
    "hotline_configuration_warning",
]

#: 部署地区环境变量。未设置时视为未知地区 -> 不下发任何号码。
DEPLOYMENT_REGION_ENV = "SAFETY_DEPLOYMENT_REGION"


class Hotline(BaseModel):
    """一条已核实的心理援助/紧急救助热线。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    number: str = Field(pattern=r"^[\d\-\+]{3,20}$", description="仅数字与 - + ")
    label: str = Field(min_length=1, max_length=60)
    scope: Literal["national", "regional"]
    region_code: str = Field(min_length=1, max_length=16, description="如 CN / CN-BJ")
    hours: str | None = Field(default=None, max_length=60)

    # --- 核实信息：三者缺一不可，否则该条目不进入注册表 ---
    verified_at: date
    verified_by: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=500)

    @field_validator("verified_by", "source_url")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("核实信息不得为空白")
        return value.strip()


#: 已核实热线注册表。新增条目必须补齐核实信息。
_REGISTRY: tuple[Hotline, ...] = (
    Hotline(
        number="12356",
        label="全国心理援助热线",
        scope="national",
        region_code="CN",
        hours="以当地卫生健康部门公布的服务时间为准",
        verified_at=date(2025, 12, 26),
        verified_by="国家卫生健康委员会新闻发布会",
        source_url=(
            "https://www.nhc.gov.cn/xcs/c100122/202512/"
            "9731f93a7e0d451284a0da462527cbd2.shtml"
        ),
    ),
)


def configured_hotlines() -> tuple[Hotline, ...]:
    """全部已核实条目（不经地区过滤）。用于白名单与诊断。"""
    return _REGISTRY


def load_hotlines(deployment_region: str | None = None) -> list[Hotline]:
    """按部署地区返回可用热线。

    部署地区为 None / 空白 / ``"unknown"`` 时返回空列表：
    未知地区不假定适用任何国家或地区的号码。
    """
    region = (deployment_region if deployment_region is not None
              else os.environ.get(DEPLOYMENT_REGION_ENV, ""))
    region = (region or "").strip()
    if not region or region.lower() == "unknown":
        return []
    return [item for item in _REGISTRY if item.region_code == region]


def allowed_hotline_numbers() -> frozenset[str]:
    """全部已核实号码。用于 :func:`assemble_verdict` 的白名单校验。

    注意：这是**全部**注册号码，不受部署地区限制；地区筛选发生在
    :func:`load_hotlines`，白名单只负责拦截模型编造的号码。
    """
    return frozenset(item.number for item in _REGISTRY)


def hotline_labels() -> dict[str, str]:
    """号码 -> 名称，供前端展示。"""
    return {item.number: item.label for item in _REGISTRY}


def hotline_configuration_warning(deployment_region: str | None = None) -> str | None:
    """部署地区未配置（或该地区无已核实号码）时返回运维告警文案，否则 None。

    这是**可见性**要求：未配置时高危学生只会看到不含号码的支持话术，
    这是刻意设计（不假定未知地区适用任何号码），但绝不允许静默上线——
    启动时必须把这件事打印出来。
    """
    if load_hotlines(deployment_region):
        return None
    region = (deployment_region if deployment_region is not None
              else os.environ.get(DEPLOYMENT_REGION_ENV, "")).strip()
    if not region or region.lower() == "unknown":
        reason = f"环境变量 {DEPLOYMENT_REGION_ENV} 未设置"
    else:
        reason = f"部署地区 {region!r} 没有已核实的热线条目"
    return (f"[Safety] {reason}：安全支持模式下不会下发任何热线号码。"
            f"如需下发，请设置 {DEPLOYMENT_REGION_ENV} 并确保注册表中存在对应的已核实号码。")
