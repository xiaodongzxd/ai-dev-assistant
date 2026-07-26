"""
构建多Agent协作的状态图
工作流：START → SUPERVISOR → (动态节点) → (循环或结束)

核心设计：
- 所有 Agent 节点都回到 Supervisor（统一协调）
- Supervisor 根据 state 中的 next_node 或 pending_action 决定路由
- 通过状态传递实现跨 Agent 协作，而非 Agent 之间直接调用

优化点：
1. 节点注册表（新增Agent只需在注册表中添加一行）
2. 自动构建条件边和固定边
3. 支持节点启用/禁用
4. 图信息可视化辅助
"""

from typing import Dict, Callable, Any

from langgraph.graph import StateGraph, END
from loguru import logger

from core.nodes import (
    supervisor_node,
    code_agent_node,
    data_agent_node,
    testing_agent_node,
)
from core.state import AgentState

# ============================================================
# 节点注册表（新增Agent只需在此添加）
# ============================================================

NODE_CONFIG = {
    "code_agent": {
        "enabled": True,
        "node_func": code_agent_node,
        "description": "代码生成、审查、修复",
    },
    "data_agent": {
        "enabled": True,
        "node_func": data_agent_node,
        "description": "数据处理、清洗、长尾挖掘",
    },
    "testing_agent": {
        "enabled": True,
        "node_func": testing_agent_node,
        "description": "测试执行（生成请求通过状态协调）",
    },
}

# 路由映射：Supervisor 返回的节点名 → 图节点名
ROUTER_MAP = {
    "code_agent": "code_agent",
    "data_agent": "data_agent",
    "testing_agent": "testing_agent",
    "END": END,
}

# ============================================================
# 边配置
# ============================================================

# 所有 Agent 执行完后都回到 Supervisor（统一由 Supervisor 决定下一步）
# 不再有固定的 TERMINAL_NODES，终结由 Supervisor 根据状态决定
RETURN_TO_SUPERVISOR = ["code_agent", "data_agent", "testing_agent"]
TERMINAL_NODES = []  # 不再有固定终结节点


# ============================================================
# 图构建核心
# ============================================================

def build_agent_graph() -> StateGraph:
    """
    定义图结构，动态添加节点和边。

    设计原则：
    1. Supervisor 是唯一的入口和路由决策点
    2. 所有 Agent 执行完后回到 Supervisor
    3. Supervisor 根据 state 中的 next_node 或 pending_action 决定路由
    """
    workflow = StateGraph(AgentState)

    # ---------- 1. 添加 Supervisor 节点 ----------
    workflow.add_node("supervisor", supervisor_node)
    workflow.set_entry_point("supervisor")

    # ---------- 2. 添加所有启用的 Agent 节点 ----------
    enabled_nodes = {}
    for node_name, cfg in NODE_CONFIG.items():
        if cfg.get("enabled", True):
            node_func = cfg.get("node_func")
            if node_func is None:
                logger.warning(f"Node '{node_name}' has no function, skipping")
                continue
            workflow.add_node(node_name, node_func)
            enabled_nodes[node_name] = cfg
            logger.debug(f"Added node: {node_name}")

    if not enabled_nodes:
        logger.warning("No enabled nodes found! Only Supervisor will run.")

    # ---------- 3. 构建条件边映射表 ----------
    conditional_targets = {name: name for name in enabled_nodes.keys()}
    conditional_targets["END"] = END

    def route_after_supervisor(state: AgentState) -> str:
        """
        路由决策函数：
        1. 如果有 pending_action → 路由到 code_agent（只有 CodeAgent 能处理 pending_action）
        2. 否则根据 next_node 路由
        3. 如果既没有 pending_action 也没有 next_node → 默认 END
        """
        # 优先级1：pending_action（跨Agent协调）
        pending_action = state.get("pending_action")
        if pending_action:
            # 只有 CodeAgent 能处理生成和修复请求
            logger.info(f"[Router] pending_action={pending_action} → routing to code_agent")
            return "code_agent"

        # 优先级2：next_node（正常路由）
        next_node = state.get("next_node", "END")
        if next_node not in conditional_targets and next_node != "END":
            logger.warning(f"Routing to unknown node: {next_node}, attempting direct route")
            return next_node

        logger.debug(f"[Router] next_node={next_node}")
        return next_node

    workflow.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        conditional_targets,
    )

    # ---------- 4. 添加固定边 ----------
    # 所有 Agent 执行完后回到 Supervisor
    for node_name in RETURN_TO_SUPERVISOR:
        if node_name in enabled_nodes:
            workflow.add_edge(node_name, "supervisor")
            logger.debug(f"Added edge: {node_name} → supervisor")

    # 如果有节点既不在 RETURN_TO_SUPERVISOR 也不在 TERMINAL_NODES 中，发出警告
    for node_name in enabled_nodes:
        if node_name not in RETURN_TO_SUPERVISOR and node_name not in TERMINAL_NODES:
            logger.warning(
                f"Node '{node_name}' has no defined edge. "
                f"Auto-adding return to supervisor."
            )
            # 自动添加回到 Supervisor 的边（安全兜底）
            workflow.add_edge(node_name, "supervisor")
            RETURN_TO_SUPERVISOR.append(node_name)

    logger.info(f"Graph built with {len(enabled_nodes)} enabled nodes")
    return workflow


def compile_agent_graph():
    """编译图，返回可调用的应用对象"""
    workflow = build_agent_graph()
    return workflow.compile()


# ============================================================
# 辅助工具（调试/可视化）
# ============================================================

def get_graph_info() -> Dict[str, Any]:
    """返回图的结构信息（用于调试和文档生成）"""
    return {
        "enabled_nodes": [name for name, cfg in NODE_CONFIG.items() if cfg.get("enabled", True)],
        "disabled_nodes": [name for name, cfg in NODE_CONFIG.items() if not cfg.get("enabled", True)],
        "return_to_supervisor": RETURN_TO_SUPERVISOR,
        "terminal_nodes": TERMINAL_NODES,
        "router_targets": list(ROUTER_MAP.keys()),
    }


def print_graph_info():
    """打印图结构信息（便于调试）"""
    info = get_graph_info()
    logger.info("=" * 50)
    logger.info("Graph Configuration:")
    logger.info(f"  Enabled nodes: {info['enabled_nodes']}")
    logger.info(f"  Disabled nodes: {info['disabled_nodes']}")
    logger.info(f"  Return to Supervisor: {info['return_to_supervisor']}")
    logger.info(f"  Terminal nodes: {info['terminal_nodes']}")
    logger.info(f"  Router targets: {info['router_targets']}")
    logger.info("=" * 50)


# ============================================================
# 节点动态注册 API（高级用法）
# ============================================================

def register_node(
        name: str,
        node_func: Callable,
        description: str = "",
        enabled: bool = True,
        return_to_supervisor: bool = True,
) -> None:
    """
    动态注册一个新节点（运行时添加）。

    Args:
        name: 节点名称（必须唯一）
        node_func: 节点函数
        description: 节点描述
        enabled: 是否启用
        return_to_supervisor: 执行完后是否回到 Supervisor（默认 True）
    """
    if name in NODE_CONFIG:
        logger.warning(f"Node '{name}' already exists, overwriting.")

    NODE_CONFIG[name] = {
        "enabled": enabled,
        "node_func": node_func,
        "description": description,
    }

    if return_to_supervisor:
        if name not in RETURN_TO_SUPERVISOR:
            RETURN_TO_SUPERVISOR.append(name)
    else:
        if name not in TERMINAL_NODES:
            TERMINAL_NODES.append(name)

    if name not in ROUTER_MAP:
        ROUTER_MAP[name] = name

    logger.info(f"Registered new node: {name} (return_to_supervisor={return_to_supervisor})")


def enable_node(name: str) -> None:
    """启用一个节点"""
    if name in NODE_CONFIG:
        NODE_CONFIG[name]["enabled"] = True
        logger.info(f"Node '{name}' enabled")


def disable_node(name: str) -> None:
    """禁用一个节点"""
    if name in NODE_CONFIG:
        NODE_CONFIG[name]["enabled"] = False
        logger.info(f"Node '{name}' disabled")
