"""
使用 gitpython 封装常用 Git 操作：克隆、创建分支、添加文件、提交、推送。
提供创建 GitHub PR 的辅助方法（通过 gh CLI）。
"""

import os
import tempfile
from typing import Optional, Dict, Any

from git import Repo, GitCommandError
from loguru import logger


class GitOperations:
    def __init__(self, repo_path: Optional[str] = None):
        self.repo_path = repo_path
        self.repo: Optional[Repo] = None
        if repo_path and os.path.exists(repo_path):
            self.repo = Repo(repo_path)

    def clone_repo(self, repo_url: str, target_dir: Optional[str] = None) -> str:
        """克隆仓库到本地目录，返回目标路径"""
        if target_dir is None:
            target_dir = tempfile.mkdtemp(prefix="tesla_git_")
        try:
            logger.info(f"Cloning {repo_url} to {target_dir}")
            self.repo = Repo.clone_from(repo_url, target_dir)
            self.repo_path = target_dir
            return target_dir
        except GitCommandError as e:
            logger.error(f"Clone failed: {e}")
            raise

    def create_branch(self, branch_name: str) -> bool:
        """创建并切换到新分支（基于当前 HEAD）"""
        if not self.repo:
            raise ValueError("No repository opened. Call clone_repo first.")
        try:
            # 使用 git checkout -b 创建并切换
            self.repo.git.checkout("HEAD", b=branch_name)
            logger.info(f"Created and switched to branch: {branch_name}")
            return True
        except GitCommandError as e:
            logger.error(f"Branch creation failed: {e}")
            return False

    def add_file(self, file_path: str) -> bool:
        """添加文件到暂存区（路径相对于仓库根目录）"""
        if not self.repo:
            return False
        try:
            full_path = os.path.join(self.repo_path, file_path)
            self.repo.index.add([full_path])
            logger.info(f"Added {file_path} to staging")
            return True
        except Exception as e:
            logger.error(f"Add failed: {e}")
            return False

    def commit(self, message: str) -> bool:
        """提交暂存区变更"""
        if not self.repo:
            return False
        try:
            self.repo.index.commit(message)
            logger.info(f"Committed: {message}")
            return True
        except Exception as e:
            logger.error(f"Commit failed: {e}")
            return False

    def push(self, remote: str = "origin", branch: Optional[str] = None) -> bool:
        """推送到远程仓库"""
        if not self.repo:
            return False
        try:
            branch = branch or self.repo.active_branch.name
            origin = self.repo.remote(remote)
            origin.push(refspec=f"{branch}:{branch}")
            logger.info(f"Pushed {branch} to {remote}")
            return True
        except GitCommandError as e:
            logger.error(f"Push failed: {e}")
            return False

    def create_pull_request_via_cli(self, repo_owner: str, repo_name: str,
                                    title: str, body: str, head_branch: str,
                                    base_branch: str = "main") -> Dict[str, Any]:
        """使用 GitHub CLI (gh) 创建 PR，需要预先安装 gh 并登录"""
        import subprocess
        try:
            cmd = [
                "gh", "pr", "create",
                "--repo", f"{repo_owner}/{repo_name}",
                "--title", title,
                "--body", body,
                "--head", head_branch,
                "--base", base_branch
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            pr_url = result.stdout.strip()
            logger.info(f"PR created: {pr_url}")
            return {"url": pr_url, "success": True}
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"gh CLI failed: {e}")
            return {"success": False, "error": str(e)}


# 全局单例（注意：每个请求应独立实例，此处仅为方便演示）
_default_git = None


def get_git_ops(repo_path: Optional[str] = None) -> GitOperations:
    global _default_git
    if _default_git is None or repo_path:
        _default_git = GitOperations(repo_path)
    return _default_git
