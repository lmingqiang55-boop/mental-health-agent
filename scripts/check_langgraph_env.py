# -*- coding: utf-8 -*-
"""Phase 0 验证：LangGraph 在本项目运行模型下可用。

验证三件事（都不改产品代码）：

1. **图机制**：``StateGraph`` 的 3 节点 + 1 条件边能按条件正确路由。
2. **运行模型**（本阶段最关键）：项目每个请求都 ``asyncio.run(graph.ainvoke(...))``，
   而 httpx/OpenAI 的连接池会绑定到**创建它的那个事件循环**。
   本脚本用本地 Ollama 做真实异步 HTTP 调用，对比两种写法：
   - 反例：模块级单例 ``AsyncClient`` 跨 5 次 ``asyncio.run`` 复用；
   - 正例：每次调用新建并在 ``finally`` 关闭。
   这正是 Safety 阶段实测踩到的静默失败（5 次坏 2 次），
   必须确认在 LangGraph 节点内同样成立、且正例稳定 5/5。
3. **兜底**：``recursion_limit`` 能拦住回边构成的循环，不会挂死。

节点一律写成 ``async def``——这是 Phase 1 真实图的形式。

运行：``python scripts/check_langgraph_env.py``
退出码 0 表示全部通过。
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

OLLAMA = "http://127.0.0.1:11434/api/tags"
ROUNDS = 5
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'ok' if ok else 'FAIL'}] {name}{'' if ok else '  ' + detail}")
    if not ok:
        failures.append(name)


# ---------------------------------------------------------------------------
# 1) 图机制：条件路由
# ---------------------------------------------------------------------------

class RouteState(TypedDict, total=False):
    score: int
    visited: list[str]
    branch: str


async def _enter(state: RouteState) -> RouteState:
    return {"visited": [*state.get("visited", []), "enter"]}


def _branch(state: RouteState) -> str:
    return "high" if state.get("score", 0) >= 10 else "low"


async def _high(state: RouteState) -> RouteState:
    return {"visited": [*state["visited"], "high"], "branch": "high"}


async def _low(state: RouteState) -> RouteState:
    return {"visited": [*state["visited"], "low"], "branch": "low"}


def build_route_graph() -> Any:
    graph = StateGraph(RouteState)
    graph.add_node("enter", _enter)
    graph.add_node("high", _high)
    graph.add_node("low", _low)
    graph.add_edge(START, "enter")
    graph.add_conditional_edges("enter", _branch, {"high": "high", "low": "low"})
    graph.add_edge("high", END)
    graph.add_edge("low", END)
    return graph.compile()


def test_routing() -> None:
    print("[1] 条件路由")
    app = build_route_graph()
    high = asyncio.run(app.ainvoke({"score": 12}))
    low = asyncio.run(app.ainvoke({"score": 3}))
    check("高分走 high 分支", high["visited"] == ["enter", "high"], str(high))
    check("低分走 low 分支", low["visited"] == ["enter", "low"], str(low))


# ---------------------------------------------------------------------------
# 2) 运行模型：跨 asyncio.run 复用异步客户端 vs 每次新建
# ---------------------------------------------------------------------------

class IoState(TypedDict, total=False):
    ok: int
    error: str | None


#: 反例：模块级单例。连接池绑定到**第一个**事件循环上。
_SINGLETON: httpx.AsyncClient | None = None


async def _get(client: httpx.AsyncClient) -> int:
    response = await client.get(OLLAMA)
    response.raise_for_status()
    return response.status_code


async def _node_singleton(state: IoState) -> IoState:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = httpx.AsyncClient(timeout=5, trust_env=False)
    try:
        return {"ok": await _get(_SINGLETON)}
    except Exception as exc:  # noqa: BLE001 - 这里就是要记录失败形态
        return {"ok": 0, "error": f"{type(exc).__name__}: {str(exc)[:70]}"}


async def _node_fresh(state: IoState) -> IoState:
    """正例：与 Safety 侧必须遵守的口径一致——每次新建并关闭。"""
    client = httpx.AsyncClient(timeout=5, trust_env=False)
    try:
        return {"ok": await _get(client)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": 0, "error": f"{type(exc).__name__}: {str(exc)[:70]}"}
    finally:
        await client.aclose()


def _build_io_graph(node: Any) -> Any:
    graph = StateGraph(IoState)
    graph.add_node("io", node)
    graph.add_edge(START, "io")
    graph.add_edge("io", END)
    return graph.compile()


def test_fresh_client_repeatable() -> None:
    print(f"[2] 跨 {ROUNDS} 次 asyncio.run 的异步客户端口径")
    fresh = _build_io_graph(_node_fresh)
    results = [asyncio.run(fresh.ainvoke({})) for _ in range(ROUNDS)]
    codes = [item.get("ok") for item in results]
    check(f"每次新建客户端：{ROUNDS}/{ROUNDS} 成功",
          all(code == 200 for code in codes), str(codes))


def test_singleton_is_the_known_trap() -> None:
    """记录反例的真实表现，作为 Phase 1 必须遵守纪律的实证。

    该反例**不参与**成败判定：不同 httpx/anyio 版本下失败形态不同
    （可能报 "Event loop is closed"，也可能看似成功），这里只做记录。
    """
    print(f"[2b] 反例记录：单例 AsyncClient 跨 {ROUNDS} 次 asyncio.run")
    global _SINGLETON
    _SINGLETON = None
    singleton = _build_io_graph(_node_singleton)
    outcomes, errors = [], []
    for index in range(ROUNDS):
        item = asyncio.run(singleton.ainvoke({}))
        ok = item.get("ok")
        outcomes.append(f"#{index + 1}={'200' if ok == 200 else 'FAIL'}")
        if ok != 200 and item.get("error"):
            errors.append(item["error"])
    broken = sum(1 for item in outcomes if item.endswith("FAIL"))
    print(f"    结果：{' '.join(outcomes)}   失败 {broken}/{ROUNDS}")
    if errors:
        print(f"    失败形态：{errors[0]}")
    print("    （仅记录；正例必须稳定，反例失败即为该陷阱的实证）")

    # 收尾：把这个坏掉的单例关掉，避免影响后续测试
    stale, _SINGLETON = _SINGLETON, None
    if stale is not None:
        with contextlib.suppress(Exception):
            asyncio.run(stale.aclose())


# ---------------------------------------------------------------------------
# 3) 兜底：recursion_limit 拦住循环回边
# ---------------------------------------------------------------------------

class LoopState(TypedDict, total=False):
    hops: int


async def _loop(state: LoopState) -> LoopState:
    return {"hops": state.get("hops", 0) + 1}


def _always_again(state: LoopState) -> str:
    return "again"


def test_recursion_limit() -> None:
    print("[3] recursion_limit 兜底")
    graph = StateGraph(LoopState)
    graph.add_node("loop", _loop)
    graph.add_edge(START, "loop")
    graph.add_conditional_edges("loop", _always_again, {"again": "loop"})
    app = graph.compile()
    try:
        asyncio.run(app.ainvoke({}, config={"recursion_limit": 15}))
    except Exception as exc:  # noqa: BLE001 - 期望被拦住
        check("无限回边被 recursion_limit 拦住",
              "recursion" in type(exc).__name__.lower(), f"{type(exc).__name__}: {exc}")
        return
    check("无限回边被 recursion_limit 拦住", False, "未抛错——会挂死")


def main() -> int:
    try:
        status = httpx.get(OLLAMA, timeout=5, trust_env=False).status_code
    except Exception as exc:  # noqa: BLE001
        print(f"本地 Ollama 不可达（{type(exc).__name__}），无法验证运行模型。")
        print("请先启动 Ollama 后重跑本脚本。")
        return 2
    print(f"本地 Ollama 可用（GET /api/tags -> {status}）\n")

    test_routing()
    print()
    test_fresh_client_repeatable()
    test_singleton_is_the_known_trap()
    print()
    test_recursion_limit()
    print()

    if failures:
        print(f"结果：{len(failures)} 项未通过 -> {failures}")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
