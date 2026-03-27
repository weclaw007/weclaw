"""技能管理器 - 负责技能的加载、缓存、格式化和操作系统过滤。"""

import asyncio
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

from weclaw.utils.paths import get_active_skills_dir, get_config_file_path, get_third_party_skills_dir

logger = logging.getLogger(__name__)


class SkillManager:
    """技能管理器单例：扫描 SKILL.md、解析 front matter、OS 过滤、启用/禁用持久化。"""

    _instance: "SkillManager | None" = None

    def __init__(self, skills_dir: str | Path | None = None):
        self.skills_dir = Path(skills_dir) if skills_dir else None
        self._cache: dict[str, dict[str, Any]] = {}
        self.config_file = get_config_file_path()
        self.skill_states: dict[str, bool] = {}

    @classmethod
    def get_instance(cls, skills_dir: str | Path | None = None) -> "SkillManager":
        if cls._instance is None:
            cls._instance = cls(skills_dir)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    # ── 配置持久化 ──

    def _load_config(self) -> None:
        if not self.config_file.exists():
            self.skill_states = {}
            return
        try:
            content = self.config_file.read_text(encoding="utf-8")
            config = yaml.safe_load(content) or {}
            self.skill_states = config.get("skills", {})
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}")
            self.skill_states = {}

    def _save_config(self) -> None:
        config = {"skills": self.skill_states}
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            self.config_file.write_text(
                yaml.dump(config, allow_unicode=True, default_flow_style=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"保存配置文件失败: {e}")

    # ── 技能状态管理 ──

    def has_skill(self, skill_name: str) -> bool:
        return skill_name in self._cache

    def get_skill_metadata(self, skill_name: str) -> dict[str, Any] | None:
        return self._cache.get(skill_name)

    def get_skill_names(self) -> list[str]:
        return list(self._cache.keys())

    def enable_skill(self, skill_id: str) -> bool:
        if skill_id not in self._cache:
            return False
        self.skill_states[skill_id] = True
        self._save_config()
        return True

    def disable_skill(self, skill_id: str) -> bool:
        if skill_id not in self._cache:
            return False
        self.skill_states[skill_id] = False
        self._save_config()
        return True

    def is_skill_enabled(self, skill_id: str) -> bool:
        return self.skill_states.get(skill_id, True)

    def get_enabled_skills(self) -> dict[str, dict[str, Any]]:
        return {sid: meta for sid, meta in self._cache.items() if self.is_skill_enabled(sid)}

    def get_enabled_skill_names(self) -> list[str]:
        """返回所有已启用技能的名称列表。"""
        return [sid for sid in self._cache if self.is_skill_enabled(sid)]

    # ── SKILL.md 解析与加载 ──

    @staticmethod
    def _extract_front_matter(md_text: str) -> dict[str, Any]:
        lines = md_text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}
        end_index = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_index = idx
                break
        if end_index is None:
            return {}
        try:
            data = yaml.safe_load("\n".join(lines[1:end_index]))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def load(self) -> dict[str, dict[str, Any]]:
        """读取内置和第三方技能目录下的 SKILL.md，缓存 front matter + body。"""
        scan_dirs: list[Path] = []
        if self.skills_dir and self.skills_dir.exists():
            scan_dirs.append(self.skills_dir)

        third_party_dir = get_third_party_skills_dir()
        if third_party_dir.exists() and third_party_dir.is_dir():
            scan_dirs.append(third_party_dir)

        if not scan_dirs:
            self._cache = {}
            return self._cache

        skill_files: list[tuple[Path, bool]] = []
        for scan_dir in scan_dirs:
            is_builtin = (self.skills_dir is not None and scan_dir == self.skills_dir)
            found = await asyncio.to_thread(lambda d=scan_dir: sorted(d.glob("*/SKILL.md")))
            skill_files.extend((f, is_builtin) for f in found)

        cache: dict[str, dict[str, Any]] = {}
        for md_file, is_builtin in skill_files:
            try:
                content = await asyncio.to_thread(md_file.read_text, encoding="utf-8")
                front_matter = self._extract_front_matter(content)

                # 提取 body（front matter 之后的内容）
                lines = content.splitlines()
                body = ""
                if lines and lines[0].strip() == "---":
                    for idx in range(1, len(lines)):
                        if lines[idx].strip() == "---":
                            body = "\n".join(lines[idx + 1:]).strip()
                            break

                if front_matter:
                    front_matter["_location"] = str(md_file)
                    front_matter["_body"] = body
                    front_matter["_builtin"] = is_builtin
                    cache[md_file.parent.name] = front_matter
            except Exception as e:
                logger.warning(f"读取技能文件失败: {md_file}, error={e}")

        self._cache = cache
        self._load_config()
        return self._cache

    def get_skills_for_current_os(self) -> dict[str, dict[str, Any]]:
        """根据当前操作系统过滤可用的技能。"""
        if not self._cache:
            return {}
        current_platform = sys.platform
        compatible = {}
        for skill_id, metadata in self._cache.items():
            required_os = metadata.get("metadata", {}).get("openclaw", {}).get("os", [])
            if not required_os or current_platform in required_os:
                compatible[skill_id] = metadata
        return compatible

    def get_all_skills_status(self) -> list[dict[str, Any]]:
        return [
            {
                "id": sid,
                "name": meta.get("name", sid),
                "description": meta.get("description", ""),
                "enabled": self.is_skill_enabled(sid),
            }
            for sid, meta in self._cache.items()
        ]

    # ── 运行时 active_skills 目录构建 ──

    @staticmethod
    def _remove_link_or_copy(entry: Path) -> None:
        """安全移除 symlink / junction / 复制目录。

        - symlink / junction → unlink
        - 复制的真实目录（带 .copied 标记文件）→ shutil.rmtree
        - 其他真实目录 → 跳过（避免误删）
        """
        if entry.is_symlink():
            entry.unlink()
        elif entry.is_dir():
            # 带标记文件的是我们复制的，可以安全删除
            if (entry / ".weclaw_copied").exists():
                shutil.rmtree(entry)
            else:
                logger.warning(f"active_skills 中发现未知目录，跳过: {entry}")

    @staticmethod
    def _create_dir_link(source: Path, target: Path) -> None:
        """创建目录链接，跨平台兼容。

        优先级：
        1. symlink（macOS/Linux 直接可用，Windows 需开发者模式）
        2. Junction（Windows 专属，不需要管理员权限）
        3. 复制目录（最终兜底，放置 .weclaw_copied 标记文件）
        """
        # 1. 尝试 symlink
        try:
            target.symlink_to(source)
            return
        except OSError:
            if sys.platform != "win32":
                raise  # 非 Windows 上 symlink 失败是真正的错误

        # 2. Windows: 尝试 Junction（目录联接，不需要管理员权限）
        try:
            import _winapi  # type: ignore[import-not-found]
            _winapi.CreateJunction(str(source), str(target))
            return
        except (ImportError, OSError) as e:
            logger.debug(f"Junction 创建失败，回退到复制: {e}")

        # 3. 最终兜底：复制目录 + 放置标记文件
        shutil.copytree(source, target)
        (target / ".weclaw_copied").write_text(
            "此目录是 active_skills 的复制副本，可安全删除。\n",
            encoding="utf-8",
        )

    def rebuild_active_skills_dir(self) -> Path:
        """重建 active_skills 运行时目录，只为启用且 OS 兼容的技能创建链接。

        跨平台策略：
        - macOS / Linux: symlink
        - Windows（开发者模式）: symlink
        - Windows（无开发者模式）: Junction → 复制兜底

        SkillsMiddleware 扫描此目录下的 */SKILL.md 来发现可用技能。
        通过链接将过滤逻辑与框架解耦：框架加载全部，我们控制哪些可见。

        Returns:
            active_skills 目录的 Path
        """
        active_dir = get_active_skills_dir()

        # 清理旧的链接 / 复制目录
        if active_dir.exists():
            for entry in active_dir.iterdir():
                self._remove_link_or_copy(entry)
        active_dir.mkdir(parents=True, exist_ok=True)

        # 为启用 + OS 兼容的技能创建链接
        compatible = self.get_skills_for_current_os()
        for skill_id, metadata in compatible.items():
            if not self.is_skill_enabled(skill_id):
                continue
            location = metadata.get("_location")
            if not location:
                continue
            source_dir = Path(location).parent  # SKILL.md 所在目录
            link_path = active_dir / skill_id
            try:
                self._create_dir_link(source_dir, link_path)
                logger.debug(f"link: {link_path} -> {source_dir}")
            except OSError as e:
                logger.warning(f"创建技能链接失败: {skill_id}, error={e}")

        return active_dir
