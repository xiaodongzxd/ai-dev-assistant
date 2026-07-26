"""
LangGraph 共享状态定义 - 所有Agent共用的"账本"
字段使用Annotated支持自动追加（如messages列表）
"""

import json
import operator
from typing import Annotated, List, Dict, Any, Optional, Literal, Set, TypedDict


class AgentState(TypedDict):
    """
    多Agent协作的全局状态。

    字段分组：
    ──────────────────────────────────────────────
    1. 用户输入层   : user_input
    2. 决策层       : task_type, sub_tasks, next_node
    3. CodeAgent层  : code_generated, code_file_path, review_result, need_review
    4. DataAgent层  : data_processing_result, data_path
    5. TestingAgent层: test_code_generated, test_result, test_passed, test_error, test_retry_count, module_name
    6. 跨Agent协调层 : pending_action, pending_context
    7. 控制层       : iteration_count, error, final_answer
    8. 历史层       : messages (自动追加)
    """

    # ========== 1. 用户输入层 ==========
    user_input: str
    """用户的原始请求文本"""

    # ========== 2. 决策层 ==========
    task_type: Optional[Literal["code_generation", "data_processing", "testing", "code_review", "unknown"]]
    """当前任务类型（由Supervisor判定）"""

    sub_tasks: List[str]
    """任务拆解后的子任务列表"""

    next_node: Optional[str]
    """路由目标节点名（由Supervisor写入，图引擎读取）"""

    # ========== 3. Code Agent 层 ==========
    code_generated: Optional[str]
    """CodeAgent生成的代码内容"""

    code_file_path: Optional[str]
    """生成的代码在Mock文件系统中的路径"""

    review_result: Optional[Dict[str, Any]]
    """代码审查结果：{issues: list, suggestions: list, score: int}"""

    need_review: Optional[bool]
    """是否需要触发代码审查（由Supervisor或用户指令触发）"""

    # ========== 4. Data Agent 层 ==========
    data_processing_result: Optional[Dict[str, Any]]
    """数据处理结果：{status, original_shape, cleaned_shape, quality_report, long_tail_scenes, ...}"""

    data_path: Optional[str]
    """数据文件路径（用于DataAgent读取，可选）"""

    # ========== 5. Testing Agent 层 ==========
    test_code_generated: Optional[str]
    """TestingAgent生成的测试代码"""

    test_result: Optional[Dict[str, Any]]
    """测试执行结果：{success, passed, failed, output, errors, ...}"""

    test_passed: Optional[bool]
    """测试是否通过（便于快速判断）"""

    test_error: Optional[str]
    """测试失败时的错误日志"""

    test_retry_count: int
    """测试重试次数（用于防无限循环）"""

    module_name: str
    """当前测试的模块名（默认 code_to_test）"""

    # ========== 6. 跨 Agent 协调层 ==========
    pending_action: Optional[str]
    """
    待处理的动作（跨Agent请求）。
    可选值：
        - "generate_test_code" : 请求生成测试代码
        - "fix_test_code"      : 请求修复测试代码
        - "fix_code"           : 请求修复业务代码
        - None                 : 无待处理请求
    """

    pending_context: Optional[Dict[str, Any]]
    """
    待处理动作的上下文数据。
    - generate_test_code: {"target_code": str, "context": str, "module_name": str}
    - fix_test_code: {"target_code": str, "test_code": str, "error_log": str, "module_name": str, "retry_count": int}
    - fix_code: {"code": str, "issues": List[str], "error_log": str}
    """

    # ========== 7. 控制层 ==========
    iteration_count: int
    """当前迭代次数（用于防无限循环）"""

    error: Optional[str]
    """错误信息（非空时表示流程异常）"""

    final_answer: Optional[str]
    """最终输出结果（供用户或下游使用）"""

    # ========== 8. 历史层 ==========
    messages: Annotated[List[Dict[str, str]], operator.add]
    """对话消息历史（自动追加，用于多轮交互）"""


# ============================================================
# 工厂函数
# ============================================================

def create_initial_state(user_input: str) -> AgentState:
    """
    创建初始状态（所有字段设为默认值）
    """
    return AgentState(
        user_input=user_input,
        messages=[],
        task_type=None,
        sub_tasks=[],
        code_generated=None,
        code_file_path=None,
        review_result=None,
        need_review=None,
        data_processing_result=None,
        data_path=None,
        test_code_generated=None,
        test_result=None,
        test_passed=None,
        test_error=None,
        test_retry_count=0,
        module_name="code_to_test",
        pending_action=None,
        pending_context=None,
        error=None,
        next_node=None,
        iteration_count=0,
        final_answer=None,
    )


# ============================================================
# 状态工具函数
# ============================================================

def state_to_snapshot(state: AgentState, include_fields: Optional[Set[str]] = None) -> Dict[str, Any]:
    """生成状态快照（用于日志/持久化）"""
    if include_fields is None:
        include_fields = set(state.keys())

    snapshot = {}
    for key in include_fields:
        if key not in state:
            continue
        value = state[key]

        if key == "messages":
            if isinstance(value, list) and len(value) > 10:
                snapshot[key] = value[:10] + [{"...": f"and {len(value) - 10} more"}]
            else:
                snapshot[key] = value
        elif isinstance(value, (str, int, float, bool)) or value is None:
            snapshot[key] = value
        elif isinstance(value, (list, dict)):
            try:
                json.dumps(value)
                snapshot[key] = value
            except (TypeError, ValueError):
                snapshot[key] = str(value)[:200] + "..."
        else:
            snapshot[key] = str(value)[:200] + "..."

    return snapshot


def diff_states(old_state: AgentState, new_state: AgentState) -> Dict[str, Any]:
    """对比两个状态的差异"""
    all_keys = set(old_state.keys()) | set(new_state.keys())

    added = {}
    removed = {}
    changed = {}
    unchanged = []

    for key in all_keys:
        old_val = old_state.get(key)
        new_val = new_state.get(key)

        if key not in old_state:
            added[key] = new_val
        elif key not in new_state:
            removed[key] = old_val
        elif old_val != new_val:
            changed[key] = {"old": old_val, "new": new_val}
        else:
            unchanged.append(key)

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }


def validate_state(state: AgentState) -> List[str]:
    """校验状态字段合法性"""
    errors = []

    if not state.get("user_input"):
        errors.append("user_input is empty or missing")

    iter_count = state.get("iteration_count", -1)
    if not isinstance(iter_count, int) or iter_count < 0:
        errors.append(f"iteration_count must be non-negative integer, got {iter_count}")

    test_retry = state.get("test_retry_count", -1)
    if not isinstance(test_retry, int) or test_retry < 0:
        errors.append(f"test_retry_count must be non-negative integer, got {test_retry}")

    task_type = state.get("task_type")
    if task_type is not None:
        valid_types = {"code_generation", "data_processing", "testing", "code_review", "unknown"}
        if task_type not in valid_types:
            errors.append(f"invalid task_type: {task_type}")

    pending_action = state.get("pending_action")
    if pending_action is not None:
        valid_actions = {"generate_test_code", "fix_test_code", "fix_code"}
        if pending_action not in valid_actions:
            errors.append(f"invalid pending_action: {pending_action}")

    messages = state.get("messages", [])
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            errors.append(f"messages[{idx}] is not a dict")
        elif "role" not in msg or "content" not in msg:
            errors.append(f"messages[{idx}] missing 'role' or 'content'")
        elif msg["role"] not in {"user", "assistant", "system"}:
            errors.append(f"messages[{idx}] invalid role: {msg['role']}")

    return errors


def summarize_state(state: AgentState) -> str:
    """生成状态摘要（用于日志）"""
    task = state.get("task_type") or "unknown"
    iter_count = state.get("iteration_count", 0)
    pending = state.get("pending_action") or "none"
    module = state.get("module_name", "unknown")
    retry = state.get("test_retry_count", 0)
    code_len = len(state.get("code_generated") or "")
    has_data = state.get("data_processing_result") is not None
    has_test = state.get("test_result") is not None
    msg_count = len(state.get("messages", []))
    error = state.get("error")

    summary = (
        f"State(task={task}, iter={iter_count}, pending={pending}, "
        f"module={module}, retry={retry}, messages={msg_count}, "
        f"code={code_len}chars, data={'✅' if has_data else '❌'}, "
        f"test={'✅' if has_test else '❌'}"
    )
    if error:
        summary += f", error={error[:50]}..."
    return summary


# ============================================================
# 便捷函数：跨 Agent 协调
# ============================================================

def request_action(action: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    创建跨 Agent 协调请求的返回字典。

    Args:
        action: 动作类型（如 "generate_test_code"）
        context: 上下文数据

    Returns:
        可直接作为节点返回的状态更新字典
    """
    return {
        "pending_action": action,
        "pending_context": context,
        "next_node": "supervisor",
    }


def clear_pending_action() -> Dict[str, Any]:
    """清除待处理动作"""
    return {
        "pending_action": None,
        "pending_context": None,
        "next_node": "supervisor",
    }
