"""
自定义任务集评估器：加载 tasks.json 中的编程问题，依次调用 Code Agent 生成代码，
再用 Testing Agent 运行测试，统计成功率。
"""

import json
import sys
import time
from pathlib import Path
from typing import Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.code_agent import get_code_agent
from agents.testing_agent import get_testing_agent
from loguru import logger


class SWEBenchEvaluator:
    def __init__(self, tasks_path: str = None, debug: bool = False):
        if tasks_path is None:
            tasks_path = Path(__file__).parent / "tasks.json"
        with open(tasks_path, "r") as f:
            self.tasks = json.load(f)

        self.code_agent = get_code_agent()
        self.testing_agent = get_testing_agent()
        self.debug = debug
        self.max_retries = 1

        if debug:
            logger.add(sys.stdout, level="DEBUG")

    def _extract_error_from_output(self, output: str) -> str:
        """从 pytest 输出中提取关键错误信息"""
        if not output:
            return "No output available"

        # 尝试提取 FAILED 或 ERROR 行
        lines = output.split("\n")
        error_lines = []

        # 收集失败相关的行
        for i, line in enumerate(lines):
            if any(keyword in line for keyword in ["FAILED", "ERROR", "E ", "_________________", "============="]):
                if "test session starts" not in line:
                    error_lines.append(line)

        if error_lines:
            # 取前 20 行错误信息
            return "\n".join(error_lines[:20])

        # 如果没有找到，返回最后 30 行
        return "\n".join(lines[-30:])

    def _extract_error_from_test_result(self, test_details: Dict) -> str:
        """从测试结果中提取可读的错误信息"""
        # 优先使用已有的 error
        if test_details.get("error"):
            return test_details["error"][:800]

        # 从 output 中提取
        output = test_details.get("output", "")
        if output:
            extracted = self._extract_error_from_output(output)
            return extracted[:800]

        return "No error details available"

    def evaluate_single_task(self, task: Dict, retry: int = 0) -> Dict:
        """评估单个任务"""
        task_id = task["id"]
        description = task["description"]
        module_name = task.get("module_name", "code_to_test")

        logger.info(f"[Task {task_id}] Evaluating: {description[:50]}...")
        start_time = time.time()

        # ============================================================
        # 步骤1：生成业务代码
        # ============================================================
        logger.debug(f"[Task {task_id}] Generating business code...")
        try:
            biz_result = self.code_agent.generate_code(description)
            biz_code = biz_result.get("code", "")
        except Exception as e:
            logger.error(f"[Task {task_id}] Business code generation failed: {e}")
            return self._error_result(task_id, f"Business code generation error: {e}", time.time() - start_time)

        if not biz_code or len(biz_code.strip()) < 20:
            return self._error_result(task_id, "Business code is too short or empty", time.time() - start_time)

        # 语法检查
        biz_syntax_ok = True
        biz_syntax_error = None
        try:
            compile(biz_code, "<string>", "exec")
        except SyntaxError as e:
            biz_syntax_ok = False
            biz_syntax_error = f"SyntaxError at line {e.lineno}: {e.msg}"
            logger.warning(f"[Task {task_id}] Business code syntax error: {biz_syntax_error}")

            if retry < self.max_retries:
                logger.info(f"[Task {task_id}] Attempting to fix business code (retry {retry + 1})...")
                fixed = self.code_agent.auto_fix(biz_code, [biz_syntax_error])
                if fixed and fixed != biz_code:
                    try:
                        compile(fixed, "<string>", "exec")
                        biz_code = fixed
                        biz_syntax_ok = True
                        biz_syntax_error = None
                        logger.info(f"[Task {task_id}] Business code auto-fix succeeded")
                    except SyntaxError as e2:
                        biz_syntax_error = f"SyntaxError after fix at line {e2.lineno}: {e2.msg}"

        if not biz_syntax_ok:
            return self._error_result(task_id, f"Business code syntax error: {biz_syntax_error}",
                                      time.time() - start_time)

        # ============================================================
        # 步骤2：生成测试代码
        # ============================================================
        test_prompt = f"""
            Generate pytest unit tests for the following Python code.
            Cover edge cases, typical inputs, and error conditions.
            
            Code to test (module name: {module_name}):
            {biz_code}
            
            Requirements:
            - Use pytest style (functions named test_*).
            - Assume the module is named '{module_name}'.
            - Do NOT write import statements (they will be injected automatically).
            - Write at least 3 distinct test functions covering positive, negative, and edge cases.
            
            Output only the raw test code:
        """
        try:
            test_result = self.code_agent.generate_code(test_prompt)
            test_code = test_result.get("code", "")
        except Exception as e:
            logger.error(f"[Task {task_id}] Test code generation failed: {e}")
            return self._error_result(task_id, f"Test code generation error: {e}", time.time() - start_time)

        if not test_code or len(test_code.strip()) < 20:
            return self._error_result(task_id, "Test code is too short or empty", time.time() - start_time)

        # ============================================================
        # 步骤3：执行测试
        # ============================================================
        logger.debug(f"[Task {task_id}] Running tests...")
        try:
            test_exec_result = self.testing_agent.run_tests(
                target_code=biz_code,
                test_code=test_code,
                module_name=module_name
            )
        except Exception as e:
            logger.error(f"[Task {task_id}] Test execution error: {e}")
            return self._error_result(task_id, f"Test execution error: {e}", time.time() - start_time)

        tests_passed = test_exec_result.get("success", False)
        test_details = {
            "passed": test_exec_result.get("passed", 0),
            "failed": test_exec_result.get("failed", 0),
            "errors": test_exec_result.get("errors", 0),
            "output": test_exec_result.get("output", "")[:1500],  # 增加输出长度
            "error": test_exec_result.get("error", ""),
        }

        # ============================================================
        # 步骤4：如果测试失败，尝试重试
        # ============================================================
        if not tests_passed and retry < self.max_retries:
            logger.info(f"[Task {task_id}] Tests failed, attempting to regenerate test code (retry {retry + 1})...")
            error_log = test_exec_result.get("error", test_exec_result.get("output", ""))
            fix_prompt = f"""
                The following pytest test code failed to execute. Please generate corrected test code.
                
                Error log:
                {error_log[:500]}
                
                Code to test (module name: {module_name}):
                {biz_code}
                
                Generate new pytest tests that should pass.
                Output only the raw test code:
            """
            try:
                new_test_result = self.code_agent.generate_code(fix_prompt)
                new_test_code = new_test_result.get("code", "")
                if new_test_code and len(new_test_code.strip()) > 20:
                    new_exec_result = self.testing_agent.run_tests(
                        target_code=biz_code,
                        test_code=new_test_code,
                        module_name=module_name
                    )
                    if new_exec_result.get("success", False):
                        test_code = new_test_code
                        tests_passed = True
                        test_exec_result = new_exec_result
                        test_details = {
                            "passed": new_exec_result.get("passed", 0),
                            "failed": new_exec_result.get("failed", 0),
                            "errors": new_exec_result.get("errors", 0),
                            "output": new_exec_result.get("output", "")[:1500],
                            "error": new_exec_result.get("error", ""),
                        }
                        logger.info(f"[Task {task_id}] Test code regeneration succeeded")
            except Exception as e:
                logger.warning(f"[Task {task_id}] Test code regeneration error: {e}")

        # ============================================================
        # 步骤5：综合判定
        # ============================================================
        overall_success = biz_syntax_ok and tests_passed

        # 提取可读的错误信息（用于报告）
        readable_error = ""
        if not tests_passed:
            readable_error = self._extract_error_from_test_result(test_details)

        elapsed = time.time() - start_time
        logger.info(f"[Task {task_id}] {'✅ PASS' if overall_success else '❌ FAIL'} "
                    f"(biz_syntax: {biz_syntax_ok}, tests: {tests_passed}, time: {elapsed:.2f}s)")

        return {
            "task_id": task_id,
            "success": overall_success,
            "syntax_ok": biz_syntax_ok,
            "syntax_error": biz_syntax_error,
            "tests_passed": tests_passed,
            "test_details": test_details,
            "time_seconds": elapsed,
            "retry_count": retry,
            "code_preview": biz_code[:500] + ("..." if len(biz_code) > 500 else ""),
            "module_name": module_name,
            "description": description[:100],
            "test_code_preview": test_code[:300] + ("..." if len(test_code) > 300 else ""),
            "error_summary": readable_error,  # 新增：可读的错误摘要
        }

    def _error_result(self, task_id: int, error_msg: str, elapsed: float) -> Dict:
        """生成错误结果字典"""
        return {
            "task_id": task_id,
            "success": False,
            "syntax_ok": False,
            "syntax_error": error_msg,
            "tests_passed": False,
            "test_details": {"error": error_msg},
            "time_seconds": elapsed,
            "retry_count": 0,
            "code_preview": "",
            "description": "",
            "error_summary": error_msg,
        }

    def run_full_evaluation(self) -> Dict[str, Any]:
        """运行所有任务并汇总结果"""
        results = []
        for task in self.tasks:
            result = self.evaluate_single_task(task, retry=0)
            results.append(result)

        total = len(results)
        successful = sum(1 for r in results if r["success"])
        avg_time = sum(r["time_seconds"] for r in results) / total if total else 0

        syntax_ok_count = sum(1 for r in results if r.get("syntax_ok", False))
        tests_passed_count = sum(1 for r in results if r.get("tests_passed", False))

        return {
            "total_tasks": total,
            "successful": successful,
            "success_rate": successful / total if total else 0,
            "avg_time_seconds": avg_time,
            "syntax_ok_count": syntax_ok_count,
            "tests_passed_count": tests_passed_count,
            "detailed_results": results,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def print_summary(self, summary: Dict):
        """打印可读的评估报告"""
        print("\n" + "=" * 70)
        print("📊 EVALUATION SUMMARY")
        print("=" * 70)
        print(f"  Timestamp:   {summary['timestamp']}")
        print(f"  Total tasks: {summary['total_tasks']}")
        print(f"  ✅ Successful: {summary['successful']}")
        print(f"  ❌ Failed:     {summary['total_tasks'] - summary['successful']}")
        print(f"  📈 Success rate: {summary['success_rate'] * 100:.1f}%")
        print(f"  ⏱️  Avg time:    {summary['avg_time_seconds']:.2f}s")
        print(f"  📝 Syntax OK:   {summary['syntax_ok_count']}/{summary['total_tasks']}")
        print(f"  🧪 Tests OK:    {summary['tests_passed_count']}/{summary['total_tasks']}")
        print("-" * 70)
        print("Detailed results:")
        print(f"{'ID':>4} | {'Status':>10} | {'Syntax':>8} | {'Tests':>8} | {'Time':>8} | {'Retry':>6}")
        print("-" * 70)
        for res in summary["detailed_results"]:
            status = "✅ PASS" if res["success"] else "❌ FAIL"
            syntax = "✅ OK" if res.get("syntax_ok", False) else "❌ ERR"
            tests = "✅ OK" if res.get("tests_passed", False) else "❌ ERR"
            print(
                f"{res['task_id']:>4} | {status:>10} | {syntax:>8} | {tests:>8} | {res['time_seconds']:>8.2f}s | {res.get('retry_count', 0):>6}")

        failed = [r for r in summary["detailed_results"] if not r["success"]]
        if failed:
            print("-" * 70)
            print("❌ Failures detail:")
            for res in failed:
                desc = res.get("description", "N/A")
                error = res.get("error_summary",
                                res.get("syntax_error", res.get("test_details", {}).get("error", "Unknown")))
                print(f"  Task {res['task_id']}: {desc}")
                # 打印更详细的错误信息
                error_lines = error.split("\n")
                if len(error_lines) > 3:
                    print(f"    Error: {error_lines[0]}")
                    for line in error_lines[1:3]:
                        print(f"           {line}")
                else:
                    print(f"    Error: {error[:200]}")
        print("=" * 70)


# ============================================================
# Markdown 报告生成
# ============================================================

def generate_markdown_report(summary: Dict) -> str:
    """生成完整的 Markdown 报告（含详细错误信息）"""
    failed = [r for r in summary["detailed_results"] if not r["success"]]

    md_report = f"""
# Evaluation Report

Generated on: {summary['timestamp']}

## Summary

- **Total tasks**: {summary['total_tasks']}
- **Successful**: {summary['successful']}
- **Failed**: {summary['total_tasks'] - summary['successful']}
- **Success rate**: {summary['success_rate'] * 100:.1f}%
- **Average time per task**: {summary['avg_time_seconds']:.2f}s
- **Syntax OK**: {summary['syntax_ok_count']}/{summary['total_tasks']}
- **Tests OK**: {summary['tests_passed_count']}/{summary['total_tasks']}

## Detailed Results

| Task ID | Status | Syntax | Tests | Time (s) |
|---------|--------|--------|-------|----------|
"""
    for res in summary["detailed_results"]:
        status = "✅ PASS" if res["success"] else "❌ FAIL"
        syntax = "✅" if res.get("syntax_ok", False) else "❌"
        tests = "✅" if res.get("tests_passed", False) else "❌"
        md_report += f"| {res['task_id']} | {status} | {syntax} | {tests} | {res['time_seconds']:.2f} |\n"

    # ===== 失败详情（含完整错误信息） =====
    if failed:
        md_report += "\n## Failures Detail\n\n"
        for res in failed:
            task_id = res['task_id']
            desc = res.get('description', f'Task {task_id}')
            error = res.get('error_summary', 'Unknown error')

            md_report += f"### Task {task_id}: {desc}\n\n"
            md_report += f"**Error:**\n```\n{error}\n```\n\n"

            if res.get('code_preview'):
                md_report += f"**Business code preview:**\n```python\n{res['code_preview']}\n```\n\n"

            if res.get('test_code_preview'):
                md_report += f"**Test code preview:**\n```python\n{res['test_code_preview']}\n```\n\n"

            # 如果有详细的测试输出
            test_details = res.get('test_details', {})
            if test_details.get('output'):
                md_report += f"**Test output:**\n```\n{test_details['output'][:800]}...\n```\n\n"

            md_report += "---\n\n"

    # ===== 成功任务详情（可选） =====
    passed = [r for r in summary["detailed_results"] if r["success"]]
    if passed:
        md_report += "\n## Success Detail\n\n"
        for res in passed:
            md_report += f"- **Task {res['task_id']}**: {res.get('description', 'N/A')} (time: {res['time_seconds']:.2f}s)\n"

    return md_report


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run evaluation on custom tasks")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--tasks", type=str, help="Path to tasks.json (default: evaluation/tasks.json)")
    args = parser.parse_args()

    evaluator = SWEBenchEvaluator(
        tasks_path=args.tasks,
        debug=args.debug
    )
    summary = evaluator.run_full_evaluation()
    evaluator.print_summary(summary)

    # 保存 JSON 结果
    with open("evaluation_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str, ensure_ascii=False)
    print("\n✅ Results saved to evaluation_results.json")

    # 生成 Markdown 报告（使用完整版本）
    md_report = generate_markdown_report(summary)
    with open("evaluation_report.md", "w", encoding="utf-8") as f:
        f.write(md_report)
    print("✅ Markdown report saved to evaluation_report.md")
