"""
内存文件系统实现，用于替代真实磁盘 I/O。
支持目录创建、文件读写、列表等基本操作，所有数据存储在内存字典中。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class MockFile:
    """内存中的文件或目录节点"""
    name: str
    content: str = ""
    is_dir: bool = False
    children: Dict[str, "MockFile"] = field(default_factory=dict)


class MockFileSystem:
    def __init__(self):
        self.root: MockFile = MockFile(name="", is_dir=True, children={})
        self.current_path: List[str] = []

    def _resolve_path(self, path: str) -> List[str]:
        """将绝对或相对路径解析为路径组件列表（Unix风格，忽略根）"""
        if not path or path == "/" or path == ".":
            return []
        if path.startswith("/"):
            parts = [p for p in path.split("/") if p]
        else:
            parts = self.current_path + [p for p in path.split("/") if p and p != "."]
        return parts

    def _navigate(self, parts: List[str]) -> Optional[MockFile]:
        """根据路径组件导航到目标目录，如果不存在则返回 None"""
        if not parts:
            return self.root
        current = self.root
        for part in parts:
            if part not in current.children:
                return None
            current = current.children[part]
            if not current.is_dir:
                return None
        return current

    def mkdir(self, path: str) -> bool:
        """创建目录（父目录必须存在）"""
        parts = self._resolve_path(path)
        if not parts:
            return False
        parent_parts = parts[:-1]
        dir_name = parts[-1]
        parent = self._navigate(parent_parts) if parent_parts else self.root
        if not parent:
            logger.error(f"Parent directory not found: {path}")
            return False
        if dir_name not in parent.children:
            parent.children[dir_name] = MockFile(name=dir_name, is_dir=True)
            logger.info(f"Directory created: {path}")
            return True
        return False

    def write_file(self, path: str, content: str) -> bool:
        """写入文件内容（自动创建父目录？这里要求父目录已存在）"""
        parts = self._resolve_path(path)
        if not parts:
            return False
        dir_parts = parts[:-1]
        file_name = parts[-1]
        parent = self._navigate(dir_parts) if dir_parts else self.root
        if not parent:
            logger.error(f"Directory not found for: {path}")
            return False
        parent.children[file_name] = MockFile(name=file_name, content=content)
        logger.info(f"File written: {path} ({len(content)} chars)")
        return True

    def read_file(self, path: str) -> Optional[str]:
        """读取文件内容，如果文件不存在或为目录则返回 None"""
        parts = self._resolve_path(path)
        if not parts:
            return None
        file_name = parts[-1]
        parent_parts = parts[:-1]
        parent = self._navigate(parent_parts) if parent_parts else self.root
        if not parent or file_name not in parent.children:
            logger.error(f"File not found: {path}")
            return None
        file_obj = parent.children[file_name]
        if file_obj.is_dir:
            logger.error(f"Cannot read directory: {path}")
            return None
        return file_obj.content

    def list_dir(self, path: str = ".") -> List[str]:
        """列出目录内容，返回文件名列表"""
        parts = self._resolve_path(path)
        target = self._navigate(parts) if parts else self.root
        if not target or not target.is_dir:
            logger.error(f"Directory not found: {path}")
            return []
        return list(target.children.keys())

    def file_exists(self, path: str) -> bool:
        """检查文件是否存在（不能是目录）"""
        parts = self._resolve_path(path)
        if not parts:
            return False
        file_name = parts[-1]
        parent_parts = parts[:-1]
        parent = self._navigate(parent_parts) if parent_parts else self.root
        if not parent or file_name not in parent.children:
            return False
        return not parent.children[file_name].is_dir


# 全局单例（注意：并发不安全，仅供单请求演示使用）
_default_fs = None


def get_file_system() -> MockFileSystem:
    global _default_fs
    if _default_fs is None:
        _default_fs = MockFileSystem()
        # 初始化一些默认目录，方便演示
        _default_fs.mkdir("/src")
        _default_fs.mkdir("/tests")
        _default_fs.mkdir("/data")
        logger.info("Mock file system initialized")
    return _default_fs
