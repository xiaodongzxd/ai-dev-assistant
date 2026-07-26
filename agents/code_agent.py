"""
Code Agent：负责代码生成、审查、自动修复，以及将代码提交到Git仓库并创建PR。
"""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from loguru import logger

from llm.ollama_client import get_llm_client
from tools.file_tools import get_file_system
from tools.git_tools import GitOperations
from tools.github_mcp_server import get_github_mcp_server


class CodeAgent:
    def __init__(self):
        self.llm = get_llm_client()
        self.fs = get_file_system()
        # 修复阈值：低于此分数会自动触发修复
        self.quality_threshold = 6
        # 最大修复迭代次数（防止无限循环）
        self.max_fix_rounds = 2
        # 代码日志文件路径（项目根目录）
        self.code_log_path = Path(__file__).parent.parent / "logs" / "generated_code.log"

    # ============================================================
    # 1. 代码生成
    # ============================================================
    def generate_code(self, user_request: str) -> Dict[str, Any]:
        """
        根据自然语言生成 Python 代码，并保存到 Mock 文件系统。
        增加：生成后自动进行轻量级语法检查。
        """
        prompt = f"""
            You are an expert Python developer. Write clean, well-structured Python code for the following request.
            
            Request: {user_request}
            
            Requirements:
            1. Write only the code, no explanations, no markdown fences.
            2. Include proper error handling (try/except for I/O or network operations).
            3. Follow PEP 8 style guidelines.
            4. Add docstrings for all functions and classes.
            5. Use type annotations where appropriate.
            6. Keep functions focused and single-purpose.
            
            Output the Python code directly:
        """
        code = self.llm.generate(prompt)

        # 清理可能残留的 markdown 标记
        code = self._clean_code_output(code)

        # 语法预检（不保存有语法错误的代码，但仅警告，不影响保存）
        if not self._validate_syntax(code):
            logger.warning("Generated code has syntax errors, but still saving for debugging.")

        # 保存到 Mock 文件系统
        file_hash = abs(hash(user_request)) % 10000
        file_path = f"/src/generated_{file_hash}.py"
        self.fs.write_file(file_path, code)

        # 生成的代码保存到 本地文件：generated_code.py
        self._log_code_to_file(code, source="GENERATED", context=user_request[:50])

        logger.info(f"Code generated and saved to {file_path} ({len(code)} chars)")

        return {
            "code": code,
            "file_path": file_path,
            "language": "python"
        }

    # ============================================================
    # 2. 代码审查
    # ============================================================
    def review_code(self, code: str) -> Dict[str, Any]:
        """
        代码审查：返回问题列表、建议和分数(0-10)。
        增强：更健壮的 JSON 提取 + 字段验证 + 分数裁剪。
        """
        prompt = f"""
            You are a senior code reviewer. Analyze the following Python code and provide a review.
            
            Output **only** a valid JSON object with exactly these keys:
            - "issues": a list of strings, each describing a problem (bugs, security, style, performance)
            - "suggestions": a list of strings, each giving improvement advice
            - "score": an integer between 0 and 10, where 10 is perfect
            
            Example output:
            {{"issues": ["No error handling", "Variable name 'x' is unclear"], "suggestions": ["Add try/except", "Rename to 'count'"], "score": 6}}
            
            Code:
            {code}
        """
        response = self.llm.generate(prompt)

        # 提取 JSON
        result = self._extract_json(response)

        # 规范化输出结构
        normalized = {
            "issues": result.get("issues", []),
            "suggestions": result.get("suggestions", []),
            "score": self._clamp_score(result.get("score", 0))
        }

        # 如果 issues 或 suggestions 不是列表，做类型转换
        if not isinstance(normalized["issues"], list):
            normalized["issues"] = [str(normalized["issues"])]
        if not isinstance(normalized["suggestions"], list):
            normalized["suggestions"] = [str(normalized["suggestions"])]

        logger.info(f"Review completed. Score: {normalized['score']}, Issues: {len(normalized['issues'])}")
        return normalized

    # ============================================================
    # 3. 自动修复
    # ============================================================
    def auto_fix(self, code: str, issues: List[str]) -> str:
        """
        根据问题列表自动修复代码。
        增强：Prompt 更明确地要求“只修问题不改结构”。
        """
        if not issues:
            logger.info("No issues to fix, returning original code.")
            return code

        issues_text = "\n".join(f"- {issue}" for issue in issues)
        prompt = f"""
            The following Python code has issues. Please fix ONLY the issues listed below.
            
            **Rules:**
            1. Do NOT rewrite the entire function or change its core behavior.
            2. Make minimal changes to address each specific issue.
            3. Keep the existing code structure as much as possible.
            4. Output only the corrected code, no explanations.
            
            Issues to fix:
            {issues_text}
            
            Original code:
            {code}
            
            Output only the corrected code:
        """
        fixed_code = self.llm.generate(prompt)

        # 清理可能残留的 markdown
        fixed_code = self._clean_code_output(fixed_code)

        # 修复后的代码保存到 本地文件：generated_code.py
        self._log_code_to_file(fixed_code, source="FIXED", context=f"Fixed {len(issues)} issues")

        # 如果修复后代码长度变化过大（删减超过 50% 或增加超过 300%），发出警告
        len_ratio = len(fixed_code) / max(len(code), 1)
        if len_ratio < 0.5:
            logger.warning(
                f"Fixed code is significantly shorter (ratio: {len_ratio:.2f}). LLM may have deleted too much.")
        elif len_ratio > 3.0:
            logger.warning(f"Fixed code is significantly longer (ratio: {len_ratio:.2f}). LLM may have over-generated.")

        return fixed_code

    # ============================================================
    # 新增：代码日志记录
    # ============================================================
    def _log_code_to_file(self, code: str, source: str, context: str = "") -> None:
        """
        将代码追加记录到 generated_code.py 文件中。

        Args:
            code: 代码内容
            source: 来源标识（如 "GENERATED", "FIXED"）
            context: 上下文信息（如用户请求或修复原因）
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 构建记录块
            header = f"""
# ============================================================
# {source} | {timestamp}
# Context: {context}
# ============================================================
"""
            # 写入文件（追加模式）
            with open(self.code_log_path, "a", encoding="utf-8") as f:
                f.write(header)
                f.write(code)
                f.write("\n\n\n")  # 3 个空行分隔

            logger.debug(f"Code logged to {self.code_log_path} ({source})")

        except Exception as e:
            # 写入失败不影响主流程，只记录警告
            logger.warning(f"Failed to log code to file: {e}")

    # ============================================================
    # 4. 创建 PR（Git + GitHub MCP）
    # ============================================================
    def create_pr_from_generated_code(
            self,
            repo_url: str,
            branch_name: str,
            commit_message: str,
            pr_title: str,
            pr_body: str,
            code: str,
            file_path_in_repo: str = "generated_code.py",
            base_branch: str = "main"  # 新增参数，默认值保持兼容
    ) -> Dict[str, Any]:
        """
        将生成的代码提交到真实 Git 仓库并创建 PR。
        新增 base_branch 参数，不硬编码 "main"。
        """
        tmp_dir = tempfile.mkdtemp(prefix="tesla_pr_")
        git_ops = GitOperations()

        try:
            # 克隆仓库
            git_ops.clone_repo(repo_url, tmp_dir)

            # 创建分支
            if not git_ops.create_branch(branch_name):
                return {"success": False, "error": "Failed to create branch"}

            # 写入代码文件
            full_path = os.path.join(tmp_dir, file_path_in_repo)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(code)

            # 添加并提交
            if not git_ops.add_file(file_path_in_repo):
                return {"success": False, "error": "Failed to add file"}
            if not git_ops.commit(commit_message):
                return {"success": False, "error": "Failed to commit"}
            if not git_ops.push(branch=branch_name):
                return {"success": False, "error": "Failed to push"}

            # 使用 GitHub MCP Server 创建 PR（支持动态 base）
            mcp = get_github_mcp_server()
            match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", repo_url)
            if not match:
                return {"success": False, "error": "Invalid repo URL"}
            repo_full = match.group(1)

            result = mcp.call_tool_sync(
                "create_pr",
                repo=repo_full,
                title=pr_title,
                body=pr_body,
                head=branch_name,
                base=base_branch  # 使用动态 base
            )
            return result

        except Exception as e:
            logger.error(f"PR creation failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            # 清理临时目录
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    # ============================================================
    # 辅助方法（内部使用）
    # ============================================================

    def _clean_code_output(self, raw: str) -> str:
        """清理 LLM 可能输出的 markdown 代码块标记"""
        cleaned = re.sub(r'```python\n?|```\n?', '', raw)
        return cleaned.strip()

    def _validate_syntax(self, code: str) -> bool:
        """使用 AST 检查 Python 代码是否有语法错误"""
        try:
            import ast
            ast.parse(code)
            return True
        except SyntaxError as e:
            logger.debug(f"Syntax validation failed: {e}")
            return False

    def _extract_json(self, response: str) -> Dict[str, Any]:
        """从 LLM 响应中提取 JSON，支持多种边界情况"""
        # 尝试多种方式提取 JSON
        patterns = [
            r'```json\s*([\s\S]*?)\s*```',  # markdown json 代码块
            r'```\s*([\s\S]*?)\s*```',  # 普通 markdown 代码块
            r'\{[\s\S]*\}',  # 裸 JSON 花括号
        ]

        for pattern in patterns:
            match = re.search(pattern, response, re.DOTALL)
            if match:
                try:
                    # 如果是 markdown 模式，取 group(1)，否则取整个匹配
                    candidate = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                    return json.loads(candidate.strip())
                except json.JSONDecodeError:
                    continue

        # 如果所有提取都失败，返回默认结构
        logger.warning("Failed to extract JSON from response, using default.")
        return {"issues": [f"Failed to parse: {response[:100]}"], "suggestions": [], "score": 0}

    def _clamp_score(self, score: Any) -> int:
        """确保 score 是 0-10 之间的整数"""
        try:
            s = int(score)
            return max(0, min(10, s))
        except (ValueError, TypeError):
            return 0


# 全局单例
_code_agent = None


def get_code_agent() -> CodeAgent:
    global _code_agent
    if _code_agent is None:
        _code_agent = CodeAgent()
    return _code_agent
