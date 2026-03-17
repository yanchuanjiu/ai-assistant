"""
文件存储抽象接口（占位）。
后续实现 VolcengineOSS / LocalStorage 继承此类。
"""
from abc import ABC, abstractmethod
from pathlib import Path


class BaseStorage(ABC):
    @abstractmethod
    def upload(self, local_path: str | Path, remote_key: str) -> str:
        """上传文件，返回访问 URL。"""

    @abstractmethod
    def download(self, remote_key: str, local_path: str | Path) -> Path:
        """下载文件到本地，返回本地路径。"""

    @abstractmethod
    def list_files(self, prefix: str = "") -> list[dict]:
        """列出文件，每条包含 key/url/size/updated_at。"""


class LocalStorage(BaseStorage):
    """开发/测试用本地文件存储。"""

    def __init__(self, root: str = "data/files"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def upload(self, local_path, remote_key: str) -> str:
        import shutil
        dest = self.root / remote_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)
        return str(dest)

    def download(self, remote_key: str, local_path) -> Path:
        import shutil
        src = self.root / remote_key
        shutil.copy2(src, local_path)
        return Path(local_path)

    def list_files(self, prefix: str = "") -> list[dict]:
        files = []
        for p in self.root.rglob("*"):
            if p.is_file() and str(p.relative_to(self.root)).startswith(prefix):
                files.append({"key": str(p.relative_to(self.root)), "url": str(p), "size": p.stat().st_size})
        return files


def get_storage() -> BaseStorage:
    """工厂函数，根据 STORAGE_PROVIDER 环境变量返回实现。"""
    import os
    provider = os.getenv("STORAGE_PROVIDER", "local")
    if provider == "local":
        return LocalStorage()
    raise NotImplementedError(f"Storage provider '{provider}' 尚未实现。")
