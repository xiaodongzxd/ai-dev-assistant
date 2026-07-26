"""
LangGraph 各节点的具体实现
包括 Supervisor（LLM 路由 + 规则兜底）、Code Agent、Data Agent、Testing Agent
"""

import json
import re
from typing import Dict, Any
from typing import Optional

from loguru import logger

from agents.code_agent import get_code_agent
from agents.data_agent import get_data_agent
from agents.testing_agent import get_testing_agent
from core.state import AgentState
from core.state import request_action
from llm.ollama_client import get_llm_client
from tools.file_tools import get_file_system


# ============================================================
# 常量配置（便于统一调整）
# ============================================================

class NodeConfig:
    """节点相关配置常量"""
    MAX_ITERATIONS = 5  # 最大循环次数
    CODE_QUALITY_THRESHOLD = 5  # 代码质量阈值（低于此值触发自动修复）
    MIN_CODE_LENGTH_FOR_REVIEW = 20  # 触发自动审查的最小代码长度
    MAX_FIX_ROUNDS = 2  # 最大修复轮次（防止无限修复）


# ============================================================
# Supervisor 节点
# ============================================================

def supervisor_node(state: AgentState) -> Dict[str, Any]:
    """
    Supervisor 节点：
    1. 迭代计数与安全限制
    2. 任务完成检测（数据处理 / 代码生成）
    3. 智能路由：先规则匹配，再 LLM 决策
    4. 前置条件校验（自动补全缺失的代码）
    """
    user_input = state.get("user_input", "")
    iteration = state.get("iteration_count", 0) + 1
    logger.info(f"[Supervisor] Analyzing (iter={iteration}): {user_input[:80]}...")

    # ============================================================
    # 1. 安全限制：最大迭代次数
    # ============================================================
    if iteration > NodeConfig.MAX_ITERATIONS:
        logger.warning(f"Max iterations ({NodeConfig.MAX_ITERATIONS}) reached, ending.")
        return {
            "next_node": "END",
            "error": f"Max iterations ({NodeConfig.MAX_ITERATIONS}) exceeded",
            "iteration_count": iteration,
            "final_answer": "Task terminated due to iteration limit.",
        }

    # ============================================================
    # 2. 任务完成检测（快速结束）
    # ============================================================
    if state.get("data_processing_result") is not None:
        logger.info("[Supervisor] Data processing already done, finishing.")
        return {
            "next_node": "END",
            "final_answer": "Data processing completed.",
            "iteration_count": iteration,
        }

    if state.get("code_generated") is not None and not state.get("need_review"):
        logger.info("[Supervisor] Code already generated, finishing.")
        return {
            "next_node": "END",
            "final_answer": state["code_generated"][:500],
            "iteration_count": iteration,
        }

    # ============================================================
    # 3. 路由决策：规则匹配 → LLM 兜底
    # ============================================================
    task_type = _fast_route_by_keywords(user_input)

    if task_type is None:
        task_type, sub_tasks = _llm_route(user_input)
    else:
        sub_tasks = [f"Process {task_type} task"]
        logger.info(f"[Supervisor] Fast-route matched: {task_type}")

    # ============================================================
    # 4. 前置条件校验（智能补全）
    # ============================================================
    # 规则1：如果想去 TestingAgent，但代码不存在 → 自动转向 CodeAgent
    if task_type == "testing":
        has_code = state.get("code_generated") is not None
        if not has_code:
            logger.info("[Supervisor] Testing requested but no code found. Auto-routing to code_agent first.")
            return {
                "next_node": "code_agent",
                "task_type": "code_generation",
                "sub_tasks": ["Generate code for testing"],
                "iteration_count": iteration,
                "messages": [{
                    "role": "system",
                    "content": "No code found for testing. Generating code first."
                }]
            }

    # 规则2：如果想去 CodeReview，但代码不存在 → 自动转向 CodeAgent
    if task_type == "code_review":
        if state.get("code_generated") is None:
            logger.info("[Supervisor] Review requested but no code found. Auto-routing to code_agent first.")
            return {
                "next_node": "code_agent",
                "task_type": "code_generation",
                "sub_tasks": ["Generate code for review"],
                "iteration_count": iteration,
                "messages": [{
                    "role": "system",
                    "content": "No code found for review. Generating code first."
                }]
            }

    # ============================================================
    # 5. 路由映射
    # ============================================================
    next_node_map = {
        "code_generation": "code_agent",
        "code_review": "code_agent",
        "data_processing": "data_agent",
        "testing": "testing_agent",
        "unknown": "END",
    }
    next_node = next_node_map.get(task_type, "END")

    logger.info(f"[Supervisor] Routed to: {next_node} (task_type={task_type})")

    return {
        "next_node": next_node,
        "task_type": task_type,
        "sub_tasks": sub_tasks,
        "iteration_count": iteration,
    }


def _fast_route_by_keywords(user_input: str) -> Optional[str]:
    """
    基于关键词的快速路由（减少不必要的 LLM 调用）
    """
    text = user_input.lower()

    # 优先级：测试 > 数据 > 审查 > 生成
    if any(kw in text for kw in ["test", "单元测试", "pytest", "运行测试"]):
        return "testing"
    if any(kw in text for kw in ["数据", "清洗", "dataset", "clean", "标注", "长尾"]):
        return "data_processing"
    if any(kw in text for kw in ["review", "审查", "代码审查", "检查代码"]):
        return "code_review"
    if any(kw in text for kw in ["写", "生成", "实现", "create", "generate", "function", "函数"]):
        return "code_generation"

    return None


def _llm_route(user_input: str) -> tuple:
    """
    使用 LLM 进行路由决策，返回 (task_type, sub_tasks)
    """
    llm = get_llm_client()
    prompt = f"""
        You are a task dispatcher. Analyze the user request and decide:
        - task_type: one of ["code_generation", "code_review", "data_processing", "testing", "unknown"]
        - sub_tasks: break down the request into 1-3 simple steps
        
        User request: {user_input}
        
        Output only a JSON object like:
        {{"task_type": "code_generation", "sub_tasks": ["Write function", "Add docstring"]}}
    """
    response = llm.generate(prompt)

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            decision = json.loads(json_match.group())
        else:
            decision = {}
    except Exception as e:
        logger.warning(f"Failed to parse LLM response: {e}")
        decision = {"task_type": "unknown", "sub_tasks": []}

    task_type = decision.get("task_type", "unknown")
    sub_tasks = decision.get("sub_tasks", [])
    return task_type, sub_tasks


# ============================================================
# Code Agent 节点
# ============================================================

def code_agent_node(state: AgentState) -> Dict[str, Any]:
    """
    Code Agent 节点：生成代码 → 自动审查 → 低分自动修复（最多 2 轮）
    """
    user_input = state.get("user_input", "")
    task_type = state.get("task_type", "code_generation")
    code_agent = get_code_agent()
    fs = get_file_system()

    # ---------- 场景：纯代码审查（已有代码） ----------
    existing_code = state.get("code_generated")
    if task_type == "code_review" and existing_code:
        logger.info("[CodeAgent] Performing code review (existing code)")
        review_result = code_agent.review_code(existing_code)

        review_text = (
            f"Review score: {review_result.get('score')}/10\n"
            f"Issues: {review_result.get('issues', [])}\n"
            f"Suggestions: {review_result.get('suggestions', [])}"
        )
        return {
            "review_result": review_result,
            "messages": [{"role": "assistant", "content": review_text}],
            "next_node": "supervisor",
            "need_review": False,
        }

    # ---------- 场景：生成新代码 ----------
    logger.info("[CodeAgent] Generating new code")
    result = code_agent.generate_code(user_input)
    code = result["code"]
    file_path = result["file_path"]

    # ---------- 自动审查 + 修复循环（最多 2 轮） ----------
    review_result = None
    current_code = code
    fix_round = 0

    # 只有代码足够长且不是明显的空代码时才触发审查
    if len(current_code.strip()) > NodeConfig.MIN_CODE_LENGTH_FOR_REVIEW:
        while fix_round <= NodeConfig.MAX_FIX_ROUNDS:
            review_result = code_agent.review_code(current_code)
            score = review_result.get("score", 0)

            logger.info(f"[CodeAgent] Review round {fix_round + 1}: score={score}")

            # 分数达标 或 已达到最大修复轮次 → 退出循环
            if score >= NodeConfig.CODE_QUALITY_THRESHOLD or fix_round >= NodeConfig.MAX_FIX_ROUNDS:
                break

            # 低分 → 自动修复
            logger.warning(f"[CodeAgent] Score {score} < {NodeConfig.CODE_QUALITY_THRESHOLD}, auto-fixing...")
            issues = review_result.get("issues", [])
            if not issues:
                # 没有具体问题，但仍低分 → 强制添加通用修复指令
                issues = ["Improve code quality, readability, and error handling"]

            current_code = code_agent.auto_fix(current_code, issues)
            # 修复后保存到文件系统
            fs.write_file(file_path, current_code)
            fix_round += 1

        # 最终审查（用于返回）
        final_review = code_agent.review_code(current_code)
        logger.info(f"[CodeAgent] Final score: {final_review.get('score')}")
        review_result = final_review

    # ---------- 返回结果 ----------
    return {
        "code_generated": current_code,
        "code_file_path": file_path,
        "review_result": review_result,
        "messages": [
            {
                "role": "assistant",
                "content": f"Code generated and saved to {file_path} "
                           f"(score: {review_result.get('score') if review_result else 'N/A'})"
            }
        ],
        "next_node": "supervisor",
    }


# ============================================================
# Data Agent 节点
# ============================================================

def data_agent_node(state: AgentState) -> Dict[str, Any]:
    """
    Data Agent 节点：处理数据清洗、质检、长尾挖掘。
    完成后直接设置 next_node="supervisor"，由 Supervisor 检测 result 并结束。
    """
    logger.info("[DataAgent] Processing data request")
    user_input = state.get("user_input", "")
    data_agent = get_data_agent()
    data_path = state.get("data_path")  # 可选

    try:
        result = data_agent.process_data_request(user_input, data_path)
        success = result.get("status") == "success"
        msg = (
            f"Data processing {'completed' if success else 'failed'}. "
            f"Original: {result.get('original_shape')}, Cleaned: {result.get('cleaned_shape')}"
        )
        if result.get("quality_report"):
            msg += f", Quality: {result['quality_report'].get('quality_score', 'N/A')}"
        logger.info(f"[DataAgent] {msg}")

        return {
            "data_processing_result": result,
            "messages": [{"role": "assistant", "content": msg}],
            "next_node": "supervisor",  # Supervisor 检测到 result 后结束
        }

    except Exception as e:
        logger.error(f"[DataAgent] Error: {e}")
        return {
            "data_processing_result": {"status": "error", "error": str(e)},
            "messages": [{"role": "assistant", "content": f"Data processing failed: {e}"}],
            "next_node": "END",  # 出错时直接结束，避免无限循环
            "error": str(e),
        }


# ============================================================
# Testing Agent 节点
# ============================================================

def testing_agent_node(state: AgentState) -> Dict[str, Any]:
    """
    Testing Agent 节点：通过状态协调完成测试生成 → 执行 → 修复的闭环。
    """
    target_code = state.get("code_generated")
    test_code = state.get("test_code_generated")
    module_name = state.get("module_name", "code_to_test")
    retry_count = state.get("test_retry_count", 0)

    # ===== 场景1：没有被测代码 =====
    if not target_code:
        return {
            "error": "No code to test",
            "next_node": "END",
            "final_answer": "No code found for testing",
        }

    # ===== 场景2：没有测试代码 → 请求生成 =====
    if not test_code:
        logger.info("[TestingAgent] No test code found, requesting generation...")
        return request_action(
            action="generate_test_code",
            context={
                "target_code": target_code,
                "context": state.get("user_input", ""),
                "module_name": module_name,
            }
        )

    # ===== 场景3：有测试代码 → 执行 =====
    logger.info("[TestingAgent] Executing tests...")
    agent = get_testing_agent()
    result = agent.run_tests(target_code, test_code, module_name)

    # 成功 → 结束
    if result["success"]:
        logger.info(f"[TestingAgent] ✅ All tests passed ({result['passed']} passed)")
        return {
            "test_result": result,
            "test_passed": True,
            "next_node": "END",
            "final_answer": f"✅ All {result['passed']} tests passed",
        }

    # ===== 场景4：测试失败 → 请求修复（最多重试2次） =====
    new_retry_count = retry_count + 1
    if new_retry_count <= agent.max_retries:
        logger.warning(
            f"[TestingAgent] ❌ Tests failed (attempt {new_retry_count}/{agent.max_retries}), "
            f"requesting fix..."
        )
        return request_action(
            action="fix_test_code",
            context={
                "target_code": target_code,
                "test_code": test_code,
                "error_log": result.get("error", result.get("output", "")),
                "module_name": module_name,
                "retry_count": new_retry_count,
            }
        )

    # ===== 重试次数用尽 → 结束并报告 =====
    logger.error(f"[TestingAgent] ❌ Tests failed after {agent.max_retries} retries")
    return {
        "test_result": result,
        "test_passed": False,
        "error": f"Tests failed after {agent.max_retries} retries",
        "next_node": "END",
        "final_answer": f"❌ Tests failed: {result.get('failed', 0)} failed, {result.get('errors', 0)} errors",
    }
