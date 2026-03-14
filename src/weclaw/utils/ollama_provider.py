#!/usr/bin/env python3
"""
Ollama Provider 工具类

功能：
- 检测系统是否安装了 Ollama
- 获取 Ollama 版本信息
- 检查 Ollama 服务是否正在运行
- 列出已安装的模型
- 获取指定模型的详细信息
"""

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Ollama 默认 API 地址
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
        """模型大小（GB）"""
        return round(self.size / (1024 ** 3), 2)

    @property
    def size_display(self) -> str:
        """模型大小的可读字符串"""
        if self.size >= 1024 ** 3:
            return f"{self.size_gb} GB"
        elif self.size >= 1024 ** 2:
            return f"{round(self.size / (1024 ** 2), 1)} MB"
        elif self.size >= 1024:
            return f"{round(self.size / 1024, 1)} KB"
        return f"{self.size} B"

    @property
    def family(self) -> str:
        """模型家族（如 llama, qwen 等）"""
        return self.details.get("family", "unknown")

    @property
    def parameter_size(self) -> str:
        """模型参数量（如 7B, 13B 等）"""
        return self.details.get("parameter_size", "unknown")

    @property
    def quantization_level(self) -> str:
        """量化级别（如 Q4_0, Q8_0 等）"""
        return self.details.get("quantization_level", "unknown")


class OllamaProvider:
    """
    Ollama Provider 工具类

    提供 Ollama 安装检测、服务状态检查、模型管理等功能。

    用法示例::

        provider = OllamaProvider()

        # 检测是否安装
        if provider.is_installed():
            print(f"Ollama 版本: {provider.get_version()}")

        # 检查服务是否运行
        if provider.is_running():
            models = provider.list_models()
            for m in models:
                print(f"{m.name} - {m.size_display}")
    """

    def __init__(self, host: str | None = None) -> None:
        """
        初始化 OllamaProvider。

        Args:
            host: Ollama API 地址，默认为 http://localhost:11434
        """
        self.host = (host or DEFAULT_OLLAMA_HOST).rstrip("/")

    # ──────────────────────────────────────────────
    # 安装检测
    # ──────────────────────────────────────────────

    def is_installed(self) -> bool:
        """
        检测系统是否安装了 Ollama。

        Returns:
            True 表示已安装，False 表示未安装
        """
        return shutil.which("ollama") is not None

    def get_install_path(self) -> str | None:
        """
        获取 Ollama 可执行文件路径。

        Returns:
            可执行文件的绝对路径，未安装则返回 None
        """
        return shutil.which("ollama")

    def get_version(self) -> str | None:
        """
        获取 Ollama 版本号。

        Returns:
            版本号字符串（如 "0.1.32"），获取失败返回 None
        """
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # 输出格式通常为 "ollama version 0.x.x"
                output = result.stdout.strip()
                # 尝试提取版本号
                if "version" in output.lower():
                    return output.split("version")[-1].strip()
                return output
            return None
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
            logger.debug(f"获取 Ollama 版本失败: {e}")
            return None

    # ──────────────────────────────────────────────
    # 服务状态检查
    # ──────────────────────────────────────────────

    def is_running(self, timeout: float = 3.0) -> bool:
        """
        检查 Ollama 服务是否正在运行。

        通过请求 Ollama API 根路径来判断服务是否可用。

        Args:
            timeout: 请求超时时间（秒）

        Returns:
            True 表示服务正在运行，False 表示服务未运行
        """
        try:
            resp = httpx.get(self.host, timeout=timeout)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
            logger.debug(f"Ollama 服务未响应: {e}")
            return False

    # ──────────────────────────────────────────────
    # 模型管理
    # ──────────────────────────────────────────────

    def list_models(self, timeout: float = 10.0) -> list[OllamaModel]:
        """
        列出所有已安装的模型。

        通过 Ollama API (/api/tags) 获取模型列表。

        Args:
            timeout: 请求超时时间（秒）

        Returns:
            OllamaModel 列表，获取失败返回空列表
        """
        try:
            resp = httpx.get(f"{self.host}/api/tags", timeout=timeout)
            if resp.status_code != 200:
                logger.warning(f"获取模型列表失败，状态码: {resp.status_code}")
                return []

            data = resp.json()
            models = []
            for item in data.get("models", []):
                model = OllamaModel(
                    name=item.get("name", ""),
                    size=item.get("size", 0),
                    digest=item.get("digest", ""),
                    modified_at=item.get("modified_at", ""),
                    details=item.get("details", {}),
                )
                models.append(model)

            return models

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(f"连接 Ollama 服务失败: {e}")
            return []
        except Exception as e:
            logger.warning(f"获取模型列表异常: {e}")
            return []

    def list_models_via_cli(self) -> list[str]:
        """
        通过命令行列出已安装的模型（不依赖 API 服务）。

        Returns:
            模型名称列表，获取失败返回空列表
        """
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.warning(f"ollama list 命令失败: {result.stderr}")
                return []

            lines = result.stdout.strip().splitlines()
            models = []
            for line in lines[1:]:  # 跳过表头
                parts = line.split()
                if parts:
                    models.append(parts[0])  # 第一列是模型名称

            return models

        except FileNotFoundError:
            logger.warning("ollama 命令未找到")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("ollama list 命令超时")
            return []
        except Exception as e:
            logger.warning(f"获取模型列表异常: {e}")
            return []

    def get_model_info(self, model_name: str, timeout: float = 10.0) -> dict[str, Any] | None:
        """
        获取指定模型的详细信息。

        Args:
            model_name: 模型名称（如 "llama3.2", "qwen2.5:7b"）
            timeout: 请求超时时间（秒）

        Returns:
            模型详细信息字典，获取失败返回 None
        """
        try:
            resp = httpx.post(
                f"{self.host}/api/show",
                json={"name": model_name},
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"获取模型 '{model_name}' 信息失败，状态码: {resp.status_code}")
            return None

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(f"连接 Ollama 服务失败: {e}")
            return None
        except Exception as e:
            logger.warning(f"获取模型信息异常: {e}")
            return None

    def has_model(self, model_name: str, timeout: float = 10.0) -> bool:
        """
        检查指定模型是否已安装。

        Args:
            model_name: 模型名称
            timeout: 请求超时时间（秒）

        Returns:
            True 表示已安装，False 表示未安装或无法检测
        """
        models = self.list_models(timeout=timeout)
        # 支持精确匹配和前缀匹配（如 "llama3.2" 匹配 "llama3.2:latest"）
        for m in models:
            if m.name == model_name or m.name.startswith(f"{model_name}:"):
                return True
        return False

    # ──────────────────────────────────────────────
    # 诊断报告
    # ──────────────────────────────────────────────

    def diagnose(self) -> dict[str, Any]:
        """
        生成完整的 Ollama 环境诊断报告。

        Returns:
            包含安装状态、版本、服务状态、模型列表等信息的字典
        """
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
                {
                    "name": m.name,
                    "size": m.size_display,
                    "family": m.family,
                    "parameter_size": m.parameter_size,
                    "quantization_level": m.quantization_level,
                    "modified_at": m.modified_at,
                }
                for m in models
            ]

        return report

    def print_diagnose(self) -> None:
        """打印格式化的诊断报告到控制台。"""
        report = self.diagnose()

        print("=" * 50)
        print("  Ollama 环境诊断报告")
        print("=" * 50)

        # 安装状态
        if report["installed"]:
            print(f"  ✔ Ollama 已安装: {report['install_path']}")
            if report["version"]:
                print(f"  ✔ 版本: {report['version']}")
        else:
            print("  ✘ Ollama 未安装")
            print("  💡 安装方法: https://ollama.com/download")
            return

        # 服务状态
        if report["service_running"]:
            print(f"  ✔ 服务运行中 ({report['host']})")
        else:
            print(f"  ✘ 服务未运行 ({report['host']})")
            print("  💡 启动方法: ollama serve")
            return

        # 模型列表
        models = report["models"]
        if models:
            print(f"\n  📦 已安装模型 ({len(models)} 个):")
            print(f"  {'模型名称':<30} {'大小':<10} {'参数量':<12} {'量化':<10} {'家族'}")
            print(f"  {'─' * 80}")
            for m in models:
                print(
                    f"  {m['name']:<30} "
                    f"{m['size']:<10} "
                    f"{m['parameter_size']:<12} "
                    f"{m['quantization_level']:<10} "
                    f"{m['family']}"
                )
        else:
            print("\n  ⚠ 暂无已安装的模型")
            print("  💡 安装模型: ollama pull <模型名称>")

        print()


def main():
    """主函数：打印 Ollama 环境状态"""
    provider = OllamaProvider()
    provider.print_diagnose()


if __name__ == "__main__":
    main()


