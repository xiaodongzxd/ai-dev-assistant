"""全局配置 - 支持环境变量"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent

# Ollama 配置
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:1.5b")

# Git 配置
GIT_USER_NAME = os.getenv("GIT_USER_NAME", "Ai Dev Assistant")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "assistant@tesla.local")

# 模型路由
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "local")  # local / cloud
CLOUD_MODEL = os.getenv("CLOUD_MODEL", "claude-3-haiku-20240307")

# 是否允许真实 Git 操作（默认 False，避免意外提交）
ALLOW_REAL_GIT = os.getenv("ALLOW_REAL_GIT", "false").lower() == "true"

# 临时工作目录（用于克隆仓库等）
WORKSPACE_DIR = ROOT_DIR / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)
