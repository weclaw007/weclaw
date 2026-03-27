"""Ollama Provider 工具类 - 检测安装、服务状态、模型管理"""

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_HOST = "http://localhost:11434"


@dataclass
class OllamaModel:
    """Ollama 模型信息"""
    name: str
    size: int = 0
    digest: str = ""
    modified_at: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def size_gb(self) -> float:
        return round(self.size / (1024 ** 3), 2)

    @property
    def size_display(self) -> str:
        if self.size >= 1024 ** 3:
            return f"{self.size_gb} GB"
        elif self.size >= 1024 ** 2:
            return f"{round(self.size / (1024 ** 2), 1)} MB"
        elif self.size >= 1024:
            return f"{round(self.size / 1024, 1)} KB"
        return f"{self.size} B"

    @property
    def family(self) -> str:
        return self.details.get("family", "unknown")

    @property
    def parameter_size(self) -> str:
        return self.details.get("parameter_size", "unknown")

    @property
    def quantization_level(self) -> str:
        return self.details.get("quantization_level", "unknown")


class OllamaProvider:
    """Ollama Provider 工具类"""

    def __init__(self, host: str | None = None) -> None:
        self.host = (host or DEFAULT_OLLAMA_HOST).rstrip("/")

    def is_installed(self) -> bool:
        return shutil.which("ollama") is not None

    def get_install_path(self) -> str | None:
        return shutil.which("ollama")

    def get_version(self) -> str | None:
        try:
            result = subprocess.run(
                ["ollama", "--version"], capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if "version" in output.lower():
                    return output.split("version")[-1].strip()
                return output
            return None
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            return None

    def is_running(self, timeout: float = 3.0) -> bool:
        try:
            resp = httpx.get(self.host, timeout=timeout)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, Exception):
            return False

    async def ais_running(self, timeout: float = 3.0) -> bool:
        """异步版本的 is_running，避免阻塞事件循环。"""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(self.host, timeout=timeout)
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, Exception):
            return False

    def list_models(self, timeout: float = 10.0) -> list[OllamaModel]:
        try:
            resp = httpx.get(f"{self.host}/api/tags", timeout=timeout)
            if resp.status_code != 200:
                return []
            data = resp.json()
            return self._parse_models(data)
        except Exception:
            return []

    async def alist_models(self, timeout: float = 10.0) -> list[OllamaModel]:
        """异步版本的 list_models，避免阻塞事件循环。"""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.host}/api/tags", timeout=timeout)
                if resp.status_code != 200:
                    return []
                data = resp.json()
                return self._parse_models(data)
        except Exception:
            return []

    @staticmethod
    def _parse_models(data: dict) -> list["OllamaModel"]:
        """解析 Ollama API 返回的模型列表。"""
        return [
            OllamaModel(
                name=item.get("name", ""),
                size=item.get("size", 0),
                digest=item.get("digest", ""),
                modified_at=item.get("modified_at", ""),
                details=item.get("details", {}),
            )
            for item in data.get("models", [])
        ]

    def list_models_via_cli(self) -> list[str]:
        try:
            result = subprocess.run(
                ["ollama", "list"], capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
            lines = result.stdout.strip().splitlines()
            return [parts[0] for line in lines[1:] if (parts := line.split())]
        except Exception:
            return []

    def get_model_info(self, model_name: str, timeout: float = 10.0) -> dict[str, Any] | None:
        try:
            resp = httpx.post(
                f"{self.host}/api/show", json={"name": model_name}, timeout=timeout,
            )
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    def has_model(self, model_name: str, timeout: float = 10.0) -> bool:
        models = self.list_models(timeout=timeout)
        return any(m.name == model_name or m.name.startswith(f"{model_name}:") for m in models)

    def diagnose(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "installed": self.is_installed(),
            "install_path": self.get_install_path(),
            "version": None,
            "service_running": False,
            "host": self.host,
            "models": [],
        }
        if not report["installed"]:
            return report
        report["version"] = self.get_version()
        report["service_running"] = self.is_running()
        if report["service_running"]:
            models = self.list_models()
            report["models"] = [
                {"name": m.name, "size": m.size_display, "family": m.family,
                 "parameter_size": m.parameter_size, "quantization_level": m.quantization_level,
                 "modified_at": m.modified_at}
                for m in models
            ]
        return report
