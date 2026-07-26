"""
Testing Agent：在隔离环境中执行 pytest 单元测试，返回通过/失败统计。

职责：只执行测试，不生成代码、不修复代码。
代码生成和修复由 CodeAgent 通过 LangGraph 状态协调完成。

工作流程（由 LangGraph 节点编排）：
    1. testing_agent_node 检查 state 中是否有 test_code
    2. 如果没有 → 返回 request_action("generate_test_code")
    3. 如果有 → 调用 TestingAgent.run_tests() 执行
    4. 如果执行成功 → 返回结果，流程结束
    5. 如果执行失败 → 返回 request_action("fix_test_code")
"""

import os
import re
import subprocess
import tempfile
from typing import Dict, Any

from loguru import logger


class TestingAgent:
    """纯测试执行器：只负责运行 pytest，不涉及任何代码生成"""

    def __init__(self):
        self.max_retries = 2

    # ============================================================
    # 核心方法
    # ============================================================

    def run_tests(
            self,
            target_code: str,
            test_code: str,
            module_name: str = "code_to_test"
    ) -> Dict[str, Any]:
        """
        在隔离环境中执行 pytest 测试，返回结构化结果。

        Args:
            target_code: 被测试的代码
            test_code: pytest 测试代码
            module_name: 模块名（用于文件名）

        Returns:
            {
                "success": bool,           # 测试是否全部通过
                "passed": int,             # 通过数量
                "failed": int,             # 失败数量
                "errors": int,             # 错误数量
                "output": str,             # 完整输出
                "error": str,              # 错误信息（如有）
            }
        """
        if not test_code or len(test_code.strip()) < 10:
            return {
                "success": False,
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "output": "",
                "error": "Test code is empty or too short",
            }

        logger.info(f"[TestingAgent] Running tests for module: {module_name}")

        with tempfile.TemporaryDirectory() as tmpdir:
            # 写入被测模块
            module_path = os.path.join(tmpdir, f"{module_name}.py")
            with open(module_path, "w", encoding="utf-8") as f:
                f.write(target_code)

            # 写入测试文件
            test_path = os.path.join(tmpdir, "test_generated.py")
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(test_code)

            try:
                result = subprocess.run(
                    ["pytest", test_path, "-v", "--tb=short", "--maxfail=3"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                stdout = result.stdout
                stderr = result.stderr

                # 解析输出统计
                passed_match = re.findall(r"(\d+) passed", stdout)
                failed_match = re.findall(r"(\d+) failed", stdout)
                error_match = re.findall(r"(\d+) error", stdout)

                passed = int(passed_match[0]) if passed_match else 0
                failed = int(failed_match[0]) if failed_match else 0
                errors = int(error_match[0]) if error_match else 0

                # 如果返回码非0但 failed 和 errors 都为0，可能是收集阶段失败
                if result.returncode != 0 and failed == 0 and errors == 0:
                    error_msg = stderr or stdout
                    return {
                        "success": False,
                        "passed": 0,
                        "failed": 0,
                        "errors": 0,
                        "output": stdout,
                        "error": f"Test collection failed: {error_msg[:200]}"
                    }

                return {
                    "success": result.returncode == 0,
                    "passed": passed,
                    "failed": failed,
                    "errors": errors,
                    "output": stdout,
                    "error": stderr if result.returncode != 0 else ""
                }

            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "output": "",
                    "error": "Test execution timed out (>10s)"
                }
            except FileNotFoundError:
                return {
                    "success": False,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "output": "",
                    "error": "pytest not found in PATH"
                }
            except Exception as e:
                return {
                    "success": False,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "output": "",
                    "error": str(e)
                }


# ============================================================
# 全局单例
# ============================================================
_testing_agent = None


def get_testing_agent() -> TestingAgent:
    global _testing_agent
    if _testing_agent is None:
        _testing_agent = TestingAgent()
    return _testing_agent
