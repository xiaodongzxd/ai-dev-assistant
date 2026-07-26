"""
提供在隔离环境中执行 Python 代码的能力。
增强：AST 预检、临时目录隔离、进程组管理、超时强制终止、详细返回信息。
注意：此沙箱为进程级隔离，生产环境建议使用 nsjail 或 gVisor。
"""

import ast
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, Optional

from loguru import logger


class CodeExecutor:
    @staticmethod
    def execute_python(code: str, timeout_sec: int = 5) -> Dict[str, Any]:
        """
        在隔离环境中执行一段 Python 代码，捕获 stdout/stderr。

        Args:
            code: 要执行的 Python 代码字符串
            timeout_sec: 超时秒数

        Returns:
            dict: {
                "success": bool,          # 是否正常退出（return_code == 0）
                "output": str,            # stdout 输出
                "error": str,             # stderr 输出
                "return_code": int,        # 进程退出码
                "duration_ms": float,     # 执行耗时（毫秒）
                "timeout": bool,          # 是否因超时被终止
                "syntax_error": Optional[str]  # 语法错误信息（如有）
            }
        """
        start_time = time.perf_counter()

        # ---------- 1. AST 语法预检 ----------
        try:
            ast.parse(code)
        except SyntaxError as e:
            logger.warning(f"Syntax error in submitted code: {e}")
            return {
                "success": False,
                "output": "",
                "error": "",
                "return_code": -1,
                "duration_ms": 0.0,
                "timeout": False,
                "syntax_error": f"SyntaxError at line {e.lineno}: {e.msg}",
            }

        # ---------- 2. 写入临时目录 ----------
        temp_dir = None
        script_path = None
        try:
            temp_dir = tempfile.TemporaryDirectory(prefix="code_exec_")
            script_path = Path(temp_dir.name) / "script.py"
            script_path.write_text(code, encoding="utf-8")

            # ---------- 3. 构建执行命令 ----------
            # 使用当前 Python 解释器，避免 PATH 污染
            python_exe = sys.executable

            # 根据操作系统设置进程组，确保超时后能杀死整个进程树
            if sys.platform == "win32":
                # Windows 使用 CREATE_NEW_PROCESS_GROUP
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
                preexec_fn = None
            else:
                # Unix 使用 setsid 创建新会话
                creation_flags = 0
                preexec_fn = os.setsid

            # ---------- 4. 执行 ----------
            result = subprocess.run(
                [python_exe, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=temp_dir.name,  # 工作目录设为临时目录
                env={  # 最小化环境变量（仅保留必要项）
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHON_UNBUFFERED": "1",  # 禁用缓冲，实时输出
                },
                preexec_fn=preexec_fn,
                creationflags=creation_flags,
            )

            duration_ms = (time.perf_counter() - start_time) * 1000

            return {
                "success": result.return_code == 0,
                "output": result.stdout,
                "error": result.stderr,
                "return_code": result.return_code,
                "duration_ms": duration_ms,
                "timeout": False,
                "syntax_error": None,
            }

        except subprocess.TimeoutExpired:
            # ---------- 5. 超时强制终止（杀死整个进程树） ----------
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Code execution timed out after {timeout_sec}s")

            # 终止进程组（Unix）或进程树（Windows）
            if script_path and script_path.exists():
                try:
                    # 先尝试优雅终止（仅 Unix）
                    if sys.platform != "win32" and result and hasattr(result, 'args'):
                        # 使用 subprocess 的 PID 终止进程组
                        if hasattr(result, 'pid'):
                            os.killpg(result.pid, signal.SIGTERM)
                            time.sleep(0.1)
                            os.killpg(result.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError, AttributeError):
                    pass

            return {
                "success": False,
                "output": "",
                "error": f"Execution timed out after {timeout_sec}s",
                "return_code": -1,
                "duration_ms": duration_ms,
                "timeout": True,
                "syntax_error": None,
            }

        except Exception as e:
            # ---------- 6. 其他异常 ----------
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Code execution failed: {e}")
            return {
                "success": False,
                "output": "",
                "error": f"Execution error: {e}",
                "return_code": -1,
                "duration_ms": duration_ms,
                "timeout": False,
                "syntax_error": None,
            }

        finally:
            # ---------- 7. 清理临时目录 ----------
            if temp_dir:
                try:
                    temp_dir.cleanup()
                except (OSError, PermissionError) as e:
                    logger.warning(f"Failed to cleanup temp dir: {e}")

    # ---------- 辅助方法（批量执行） ----------
    @staticmethod
    def execute_batch(codes: list, timeout_sec: int = 5) -> list:
        """
        批量执行多段代码（顺序执行，非并发），返回结果列表。
        """
        executor = CodeExecutor()
        return [executor.execute_python(code, timeout_sec) for code in codes]

    # ---------- 辅助方法（快速语法检查） ----------
    @staticmethod
    def check_syntax(code: str) -> Optional[str]:
        """
        仅检查语法，返回错误信息或 None。
        """
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"SyntaxError at line {e.lineno}: {e.msg}"
