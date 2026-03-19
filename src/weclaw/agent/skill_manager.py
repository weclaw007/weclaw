"""技能管理器 - 核心模块

负责技能的加载、缓存、格式化和操作系统过滤。
安装/卸载/状态检查功能委托给子模块。
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from weclaw.utils.paths import get_config_file_path, get_third_party_skills_dir

# 将markdown 文件的body 部分也缓存起来，以便后续需要时直接使用，而不必再次读取文件
# 提示词就不需要有location 标签，只需要name就可以。节省 tokens


class SkillManager:
    _instance: "SkillManager | None" = None

    def __init__(self, skills_dir: str | Path | None = None):
        """初始化 SkillManager。请勿直接调用，应使用 get_instance() 获取单例。"""
        self.skills_dir = skills_dir
        self._cache: dict[str, dict[str, Any]] = {}
        self.config_file = get_config_file_path()
        self.skill_states: dict[str, bool] = {}  # skill_id -> enabled (True/False)

    @classmethod
    def get_instance(cls, skills_dir: str | Path | None = None) -> "SkillManager":
        """获取单例实例。

        首次调用时创建实例，后续调用返回相同实例。
        注意：skills_dir 仅在首次创建时生效。
        """
        if cls._instance is None:
            cls._instance = cls(skills_dir)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None

    def _load_config(self) -> None:
        """从配置文件加载 skill 状态"""
        if not self.config_file.exists():
            self.skill_states = {}
            return
        
        try:
            content = self.config_file.read_text(encoding="utf-8")
            config = yaml.safe_load(content) or {}
            self.skill_states = config.get("skills", {})
            logging.info(f"已加载配置文件: {self.config_file}")
        except Exception as e:
            logging.warning(f"加载配置文件失败: {e}")
            self.skill_states = {}

    def _save_config(self) -> None:
        """保存 skill 状态到配置文件"""
        config = {"skills": self.skill_states}
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            self.config_file.write_text(
                yaml.dump(config, allow_unicode=True, default_flow_style=False),
                encoding="utf-8"
            )
            logging.info(f"已保存配置文件: {self.config_file}")
        except Exception as e:
            logging.warning(f"保存配置文件失败: {e}")

    def has_skill(self, skill_name: str) -> bool:
        """判断技能是否存在于缓存中"""
        return skill_name in self._cache

    def get_skill_metadata(self, skill_name: str) -> dict[str, Any] | None:
        """获取指定技能的 front_matter 元数据，不存在则返回 None"""
        return self._cache.get(skill_name)

    def get_skill_names(self) -> list[str]:
        """获取所有技能名称列表"""
        return list(self._cache.keys())

    def enable_skill(self, skill_id: str) -> bool:
        """启用指定的 skill"""
        if skill_id not in self._cache:
            logging.warning(f"技能不存在: {skill_id}")
            return False
        self.skill_states[skill_id] = True
        self._save_config()
        logging.info(f"已启用技能: {skill_id}")
        return True

    def disable_skill(self, skill_id: str) -> bool:
        """禁用指定的 skill"""
        if skill_id not in self._cache:
            logging.warning(f"技能不存在: {skill_id}")
            return False
        self.skill_states[skill_id] = False
        self._save_config()
        logging.info(f"已禁用技能: {skill_id}")
        return True

    def is_skill_enabled(self, skill_id: str) -> bool:
        """检查 skill 是否启用（默认为启用）"""
        return self.skill_states.get(skill_id, True)

    def get_enabled_skills(self) -> dict[str, dict[str, Any]]:
        """获取所有启用的 skill"""
        return {
            skill_id: metadata
            for skill_id, metadata in self._cache.items()
            if self.is_skill_enabled(skill_id)
        }

    @staticmethod
    def _extract_front_matter(md_text: str) -> dict[str, Any]:
        """从 Markdown 的 front matter 中提取所有键值。"""
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

        yaml_text = "\n".join(lines[1:end_index])
        try:
            data = yaml.safe_load(yaml_text)
        except Exception as e:
            logging.warning(f"解析 front matter 失败: {e}")
            return {}

        if isinstance(data, dict):
            return data
        return {}

    async def load(self) -> dict[str, dict[str, Any]]:
        """读取 skills 子目录下 SKILL.md 的头部信息和 body，并缓存所有 front matter 键值到内存。
        
        同时从内置技能目录(self.skills_dir)和第三方技能目录(get_third_party_skills_dir())中读取。
        如果两个目录中存在同名技能，第三方技能会覆盖内置技能。
        """
        # 收集所有需要扫描的目录
        scan_dirs: list[Path] = []
        if self.skills_dir.exists() and self.skills_dir.is_dir():
            scan_dirs.append(self.skills_dir)
        
        third_party_dir = get_third_party_skills_dir()
        if third_party_dir.exists() and third_party_dir.is_dir():
            scan_dirs.append(third_party_dir)
        
        if not scan_dirs:
            self._cache = {}
            return self._cache

        # 从所有目录中收集技能文件，并记录来源
        # 元组: (Path, bool)  —— bool=True 表示内置技能
        skill_files: list[tuple[Path, bool]] = []
        for scan_dir in scan_dirs:
            is_builtin = (scan_dir == Path(self.skills_dir))
            found = await asyncio.to_thread(lambda d=scan_dir: sorted(d.glob("*/SKILL.md")))
            skill_files.extend((f, is_builtin) for f in found)
        
        cache: dict[str, dict[str, Any]] = {}

        for md_file, is_builtin in skill_files:
            try:
                content = await asyncio.to_thread(md_file.read_text, encoding="utf-8")
                front_matter = self._extract_front_matter(content)
                
                # 提取 markdown body 部分（front matter 之后的内容）
                lines = content.splitlines()
                body = ""
                if lines and lines[0].strip() == "---":
                    end_index = None
                    for idx in range(1, len(lines)):
                        if lines[idx].strip() == "---":
                            end_index = idx
                            break
                    if end_index is not None:
                        body = "\n".join(lines[end_index + 1:]).strip()
                
                if front_matter:
                    # 大模型偶尔会拼接错误，还是使用全路径
                    front_matter["_location"] = str(md_file)
                    front_matter["_body"] = body
                    front_matter["_builtin"] = is_builtin
                    cache[md_file.parent.name] = front_matter
            except Exception as e:
                logging.warning(f"读取技能文件失败: {md_file}, error={e}")

        self._cache = cache
        
        # 加载配置文件中的 skill 状态
        self._load_config()
        
        return self._cache

    def format_as_json(self) -> str:
        """将技能缓存格式化为 JSON 字符串，只包含当前操作系统支持且未被禁用的技能。"""
        skills_list = []
        compatible_skills = self.get_skills_for_current_os()
        
        for skill_id, metadata in compatible_skills.items():
            if not self.is_skill_enabled(skill_id):
                continue
            location = metadata.get("_location", "")
            # 取 SKILL.md 所在目录作为技能目录，保留 ~ 缩写
            if location:
                location = str(Path(location).parent)
            skills_list.append({
                "name": metadata.get("name", skill_id),
                "description": metadata.get("description", ""),
                "location": location
            })

        return json.dumps({"available_skills": skills_list}, ensure_ascii=False, indent=2)

    def get_skills_for_current_os(self) -> dict[str, dict[str, Any]]:
        """根据当前操作系统过滤可用的技能。
        
        返回只包含适用于当前操作系统且已启用的技能字典。
        """
        if not self._cache:
            return {}
            
        current_platform = sys.platform
        compatible_skills = {}
        
        for skill_id, metadata in self._cache.items():
            # 获取技能的操作系统要求
            openclaw_metadata = metadata.get('metadata', {}).get('openclaw', {})
            required_os = openclaw_metadata.get('os', [])
            
            # 如果没有指定os字段，或者当前操作系统在支持列表中，则包含该技能
            if not required_os or current_platform in required_os:
                compatible_skills[skill_id] = metadata
        
        return compatible_skills

    def get_all_skills_status(self) -> list[dict[str, Any]]:
        """获取所有 skill 的状态列表"""
        result = []
        for skill_id, metadata in self._cache.items():
            result.append({
                "id": skill_id,
                "name": metadata.get("name", skill_id),
                "description": metadata.get("description", ""),
                "enabled": self.is_skill_enabled(skill_id),
            })
        return result


