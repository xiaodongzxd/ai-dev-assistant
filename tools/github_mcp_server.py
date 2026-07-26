"""
GitHub MCP 风格服务器：封装 PyGithub 提供的 API 为标准化工具。
实现获取文件内容、创建 PR、列出 Issues 等常用功能。
"""

import os
from typing import Dict, Any, Optional

from github import Github, GithubException
from github.Repository import Repository
from loguru import logger

from .base_tool import MCPBaseServer, ToolDefinition, ToolPermission


class GitHubMCPServer(MCPBaseServer):
    def __init__(self, token: Optional[str] = None):
        super().__init__("github_mcp")
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            logger.warning("GITHUB_TOKEN not set. GitHub API calls will fail.")
            self.client = None
        else:
            self.client = Github(self.token)
        self._register_all_tools()

    def _register_all_tools(self):
        """注册所有工具"""
        self.register_tool(ToolDefinition(
            name="get_file_content",
            description="Get content of a file from a GitHub repository",
            handler=self._get_file_content_async,
            permission=ToolPermission.READ,
            parameters_schema={
                "repo": "string (owner/repo)",
                "path": "string (file path)",
                "ref": "string (optional branch/tag)"
            }
        ))
        self.register_tool(ToolDefinition(
            name="create_pr",
            description="Create a pull request",
            handler=self._create_pr_async,
            permission=ToolPermission.WRITE,
            parameters_schema={
                "repo": "string", "title": "string", "body": "string",
                "head": "string", "base": "string"
            }
        ))
        self.register_tool(ToolDefinition(
            name="list_issues",
            description="List repository issues",
            handler=self._list_issues_async,
            permission=ToolPermission.READ
        ))

    async def _get_file_content_async(self, repo: str, path: str, ref: Optional[str] = None) -> Dict[str, Any]:
        """获取仓库中文件的内容"""
        if not self.client:
            return {"error": "GitHub client not initialized"}
        try:
            repo_obj: Repository = self.client.get_repo(repo)
            content = repo_obj.get_contents(path, ref=ref)
            if content.type == "file":
                return {"content": content.decoded_content.decode("utf-8"), "sha": content.sha}
            return {"error": "Path is a directory"}
        except GithubException as e:
            logger.error(f"GitHub API error: {e}")
            return {"error": str(e)}

    async def _create_pr_async(self, repo: str, title: str, body: str,
                               head: str, base: str = "main") -> Dict[str, Any]:
        """创建 Pull Request"""
        if not self.client:
            return {"error": "GitHub client not initialized"}
        try:
            repo_obj = self.client.get_repo(repo)
            pr = repo_obj.create_pull(title=title, body=body, head=head, base=base)
            return {"url": pr.html_url, "number": pr.number, "success": True}
        except GithubException as e:
            return {"error": str(e)}

    async def _list_issues_async(self, repo: str, state: str = "open") -> Dict[str, Any]:
        """列出仓库的 Issues"""
        if not self.client:
            return {"error": "GitHub client not initialized"}
        try:
            repo_obj = self.client.get_repo(repo)
            issues = repo_obj.get_issues(state=state)
            return {"issues": [{"number": i.number, "title": i.title} for i in issues[:10]]}
        except GithubException as e:
            return {"error": str(e)}

    # 同步包装，方便在非 async 环境中调用
    def call_tool_sync(self, name: str, **kwargs) -> Any:
        import asyncio
        return asyncio.run(self.call_tool(name, **kwargs))


# 全局单例
_github_server = None


def get_github_mcp_server() -> GitHubMCPServer:
    global _github_server
    if _github_server is None:
        _github_server = GitHubMCPServer()
    return _github_server
