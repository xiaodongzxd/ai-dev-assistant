#!/usr/bin/env python
"""
运行评估器，在自定义任务集上测试 Agent 的代码生成能力，输出成功率报告。

用法：
    python run_evaluation.py                    # 运行评估（默认 tasks.json）
    python run_evaluation.py --debug            # 调试模式（更多日志）
    python run_evaluation.py --tasks custom.json # 使用自定义任务集
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swe_bench_evaluator import SWEBenchEvaluator
from loguru import logger


def generate_markdown_report(summary: dict) -> str:
    """
    根据评估摘要生成 Markdown 报告
    """
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

    if failed:
        md_report += "\n## Failures Detail\n\n"
        for res in failed:
            desc = res.get("description", f"Task {res['task_id']}")
            error = res.get("syntax_error") or res.get("test_details", {}).get("error", "Unknown error")
            md_report += f"### Task {res['task_id']}: {desc}\n"
            md_report += f"- **Error**: {error[:300]}\n"
            if res.get("code_preview"):
                md_report += f"- **Code preview**:\n```python\n{res['code_preview']}\n```\n"
            md_report += "\n"

    return md_report


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run AI Dev Assistant Evaluation")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--tasks", type=str, help="Path to tasks.json (default: tasks.json)")
    parser.add_argument("--quiet", action="store_true", help="Reduce log output")
    args = parser.parse_args()

    # 配置日志
    if not args.quiet:
        logger.add(sys.stdout, level="DEBUG" if args.debug else "INFO")
    else:
        logger.add(sys.stdout, level="WARNING")

    print("=" * 70)
    print("🚀 Starting AI Dev Assistant Evaluation")
    print("=" * 70)

    # 初始化评估器
    tasks_path = args.tasks or str(Path(__file__).parent / "tasks.json")
    evaluator = SWEBenchEvaluator(
        tasks_path=tasks_path,
        debug=args.debug
    )

    # 运行评估
    try:
        summary = evaluator.run_full_evaluation()
        evaluator.print_summary(summary)

        # ========== 保存 JSON 结果 ==========
        with open("evaluation/evaluation_results.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str, ensure_ascii=False)
        print("✅ Results saved to evaluation_results.json")

        # ========== 生成 Markdown 报告 ==========
        md_report = generate_markdown_report(summary)
        with open("evaluation/evaluation_report.md", "w", encoding="utf-8") as f:
            f.write(md_report)
        print("✅ Markdown report saved to evaluation_report.md")

        # 报告位置
        print("📄 Markdown report: evaluation_report.md")
        print("📄 JSON results: evaluation_results.json")

    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
