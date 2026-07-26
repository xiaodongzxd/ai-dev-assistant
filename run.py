#!/usr/bin/env python
"""
AI Dev Assistant 主入口

支持三种运行模式：
1. 命令行参数：python run.py "写一个质数判断函数"
2. 交互式菜单：python run.py（无参数）
3. 调试模式：python run.py --debug "写一个函数"
"""

import argparse
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

from core.state import create_initial_state
from core.graph import compile_agent_graph
from agents.code_agent import get_code_agent
from loguru import logger


# ============================================================
# 日志配置
# ============================================================

def setup_logging(debug: bool = False):
    """配置日志：控制台和文件"""
    # 移除默认的 loguru 处理器
    logger.remove()

    # 控制台日志（根据 debug 模式调整级别）
    console_level = "DEBUG" if debug else "INFO"
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:8}</level> | <level>{message}</level>",
        level=console_level,
        colorize=True,
    )

    # 文件日志（始终 INFO 级别，便于持久化）
    logger.add(
        "logs/ai_agent.log",
        rotation="10 MB",
        retention="7 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )


# ============================================================
# 核心运行函数
# ============================================================

def run_agent(user_input: str, debug: bool = False) -> dict:
    """
    运行 Agent 主流程

    Args:
        user_input: 用户请求
        debug: 是否开启调试模式（输出更多日志）

    Returns:
        最终状态字典
    """
    # 输入清理：去除首尾空白、引号
    cleaned = user_input.strip().strip('"').strip("'").strip()
    if not cleaned:
        logger.error("Empty input after cleaning")
        return {"error": "Empty input after cleaning", "final_answer": None}

    if debug:
        logger.debug(f"Original input: {repr(user_input)}")
        logger.debug(f"Cleaned input: {repr(cleaned)}")

    logger.info("=" * 60)
    logger.info(f"Starting AI Dev Assistant (debug={'on' if debug else 'off'})")
    logger.info(f"User Input: {cleaned}")

    try:
        # 创建初始状态
        initial_state = create_initial_state(cleaned)

        # 编译并运行图
        app = compile_agent_graph()
        final_state = app.invoke(initial_state)

        logger.success("Execution completed")
        return final_state

    except Exception as e:
        logger.error(f"Execution failed: {e}")
        return {
            "error": str(e),
            "final_answer": f"Execution failed: {e}",
        }


# ============================================================
# 结果展示
# ============================================================

def print_result(result: dict):
    """格式化打印执行结果"""
    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)

    # 错误信息
    if result.get("error"):
        print(f"❌ ERROR: {result['error']}")
        return

    # 最终答案（如果有）
    if result.get("final_answer"):
        print(f"\n📝 Final Answer:\n{result['final_answer'][:500]}")

    # 代码生成结果
    if result.get("code_generated"):
        code = result["code_generated"]
        print(f"\n💻 Generated Code ({len(code)} chars):")
        print("-" * 40)
        # 限制显示长度，避免刷屏
        if len(code) > 1500:
            print(code[:1500])
            print(f"\n... (truncated, full code saved to {result.get('code_file_path', 'file system')})")
        else:
            print(code)

    # 代码审查结果
    if result.get("review_result"):
        review = result["review_result"]
        print("\n🔍 Code Review:")
        print(f"  Score: {review.get('score', 'N/A')}/10")
        if review.get("issues"):
            print("  Issues:")
            for issue in review["issues"][:5]:
                print(f"    - {issue}")
            if len(review["issues"]) > 5:
                print(f"    ... and {len(review['issues']) - 5} more")
        if review.get("suggestions"):
            print("  Suggestions:")
            for suggestion in review["suggestions"][:3]:
                print(f"    - {suggestion}")
            if len(review["suggestions"]) > 3:
                print(f"    ... and {len(review['suggestions']) - 3} more")

    # 数据处理结果
    if result.get("data_processing_result"):
        data = result["data_processing_result"]
        print("\n📊 Data Processing:")
        print(f"  Status: {data.get('status', 'unknown')}")
        if "original_shape" in data:
            print(f"  Original: {data['original_shape'][0]} rows, {data['original_shape'][1]} cols")
        if "cleaned_shape" in data:
            print(f"  Cleaned: {data['cleaned_shape'][0]} rows, {data['cleaned_shape'][1]} cols")
        if data.get("quality_report"):
            qr = data["quality_report"]
            print(f"  Quality Score: {qr.get('quality_score', 'N/A')}")
            print(f"  Inconsistent samples: {qr.get('inconsistent_count', 0)}")
        if data.get("long_tail_scenes"):
            print(f"  Long-tail scenes found: {len(data['long_tail_scenes'])}")
            for scene in data["long_tail_scenes"][:3]:
                print(f"    - {scene}")

    # 测试结果
    if result.get("test_result"):
        test = result["test_result"]
        print("\n🧪 Test Results:")
        if test.get("success"):
            print(f"  ✅ All tests passed!")
        else:
            print(f"  ❌ Tests failed")
        print(f"  Passed: {test.get('passed', 0)}")
        print(f"  Failed: {test.get('failed', 0)}")
        if test.get("error"):
            print(f"  Error: {test['error'][:200]}")
        if test.get("output"):
            print(f"  Output: {test['output'][:200]}...")

    print("\n" + "=" * 60)


# ============================================================
# 演示功能
# ============================================================

def demo_code_review():
    """代码审查演示"""
    code = """
def add(a, b):
    return a + b
"""
    agent = get_code_agent()
    result = agent.review_code(code)
    print("\n" + "=" * 40)
    print("Code Review Demo")
    print("=" * 40)
    print(f"Code:\n{code}")
    print(f"Review result:\n  Score: {result.get('score', 'N/A')}/10")
    print(f"  Issues: {result.get('issues', [])}")
    print(f"  Suggestions: {result.get('suggestions', [])}")
    print("=" * 40)


def demo_github_pr(repo_url: str = None, branch: str = "ai-bot-patch"):
    """
    GitHub PR 创建演示

    Args:
        repo_url: 仓库地址（默认使用示例地址，需要替换）
        branch: 分支名
    """
    if repo_url is None:
        repo_url = "https://github.com/your-username/test-repo.git"
        print(f"⚠️  Using example repo: {repo_url}")
        print("   Please set GITHUB_TOKEN environment variable and replace the URL.")

    agent = get_code_agent()
    sample_code = "print('Hello from AI Assistant')"
    result = agent.create_pr_from_generated_code(
        repo_url=repo_url,
        branch_name=branch,
        commit_message="Add generated code",
        pr_title="Auto-generated PR from AI Dev Assistant",
        pr_body="This PR was created automatically by the AI Dev Assistant.\n\nGenerated code:\n```python\nprint('Hello from AI Assistant')\n```",
        code=sample_code,
        file_path_in_repo="hello.py"
    )
    print("\n" + "=" * 40)
    print("GitHub PR Demo")
    print("=" * 40)
    if result.get("success"):
        print(f"✅ PR created successfully!")
        print(f"  URL: {result.get('url', 'N/A')}")
        print(f"  Number: {result.get('number', 'N/A')}")
    else:
        print(f"❌ PR creation failed: {result.get('error', 'Unknown error')}")
    print("=" * 40)


# ============================================================
# 交互式菜单
# ============================================================

def interactive_menu() -> tuple:
    """
    显示交互式菜单，返回 (mode, user_input)
    mode: 'agent', 'review', 'pr', 'quit'
    """
    print("\n" + "=" * 50)
    print("🚀 AI Dev Assistant - Interactive Menu")
    print("=" * 50)
    print("  1. Run Agent (process a request)")
    print("  2. Code Review Demo")
    print("  3. GitHub PR Demo (requires GITHUB_TOKEN)")
    print("  4. Quit")
    print("-" * 50)

    choice = input("Choose (1-4): ").strip()

    if choice == "1":
        user_input = input("Enter your request: ").strip()
        if not user_input:
            user_input = "Write a function to sort a list using quicksort"
            print(f"Using default: {user_input}")
        return "agent", user_input

    elif choice == "2":
        return "review", None

    elif choice == "3":
        repo = input("Enter repo URL (or press Enter for example): ").strip()
        if not repo:
            repo = None
        return "pr", repo

    elif choice == "4":
        return "quit", None

    else:
        print("Invalid choice, running Agent with default request...")
        return "agent", "Write a function to sort a list using quicksort"


# ============================================================
# 命令行参数解析
# ============================================================

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="AI Dev Assistant - Multi-Agent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py "写一个质数判断函数"          # 直接运行
  python run.py --review                    # 代码审查演示
  python run.py --pr                        # GitHub PR 演示
  python run.py --debug "clean dataset"     # 调试模式
        """
    )
    parser.add_argument(
        "request",
        nargs="?",
        help="用户请求（如果提供，直接运行 Agent）"
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="运行代码审查演示"
    )
    parser.add_argument(
        "--pr",
        action="store_true",
        help="运行 GitHub PR 演示"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="开启调试模式（更多日志输出）"
    )
    parser.add_argument(
        "--repo",
        type=str,
        help="GitHub PR 演示的仓库地址"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="AI Dev Assistant v1.0.0"
    )
    return parser.parse_args()


# ============================================================
# 主入口
# ============================================================

def main():
    """主入口"""
    # 解析命令行参数
    args = parse_args()

    # 设置日志
    setup_logging(debug=args.debug)

    # ---------- 模式1：代码审查演示 ----------
    if args.review:
        demo_code_review()
        return

    # ---------- 模式2：GitHub PR 演示 ----------
    if args.pr:
        demo_github_pr(repo_url=args.repo)
        return

    # ---------- 模式3：直接运行请求（命令行参数） ----------
    if args.request:
        user_input = " ".join(args.request) if isinstance(args.request, list) else args.request
        result = run_agent(user_input, debug=args.debug)
        print_result(result)
        return

    # ---------- 模式4：交互式菜单 ----------
    while True:
        mode, data = interactive_menu()

        if mode == "quit":
            print("Goodbye! 👋")
            break

        elif mode == "review":
            demo_code_review()

        elif mode == "pr":
            demo_github_pr(repo_url=data)

        elif mode == "agent":
            result = run_agent(data, debug=args.debug)
            print_result(result)

        # 询问是否继续
        print("\n" + "-" * 40)
        cont = input("Continue? (y/n): ").strip().lower()
        if cont not in ("y", "yes", ""):
            print("Goodbye! 👋")
            break


if __name__ == "__main__":
    main()
