# /astrbot_plugin_chatsummary/config.py

import os
import json
from collections.abc import Mapping
from astrbot.core import logger


class PluginConfig:
    def __init__(
        self,
        config_file_path: str,
        initial_data=None,
    ):
        self.default_prompt = "请总结以下聊天记录："
        self.default_html_template = "base"  # 默认HTML渲染模板
        self.wake_prefix = []
        self._data = {}
        self._groups = {}  # 存储群组配置

        if initial_data is not None:
            self.merge(initial_data)

        self._load_from_file(config_file_path)
        self._sync_prompt()
        self._parse_groups()

    def _load_from_file(self, config_file_path: str) -> None:
        try:
            with open(config_file_path, "r", encoding="utf-8-sig") as f:
                config = json.load(f)
                self._merge_data(config)
        except FileNotFoundError:
            logger.warning("聊天总结插件配置文件未找到，将使用默认Prompt。")
        except Exception as e:
            logger.error(f"加载聊天总结插件配置文件时出错: {e}")

    def _merge_data(self, data) -> None:
        if data is None:
            return

        if isinstance(data, PluginConfig):
            candidate = data.to_dict()
        elif isinstance(data, Mapping):
            candidate = dict(data)
        elif hasattr(data, "__dict__"):
            candidate = {k: v for k, v in vars(data).items() if not k.startswith("_")}
        else:
            return

        self._data.update(candidate)

    def _sync_prompt(self) -> None:
        # 先获取 default_prompt，如果没有则使用内置默认值
        default_prompt_value = self._data.get("default_prompt", self.default_prompt)
        self.default_prompt = str(default_prompt_value).replace("\\n", "\n")

    def _parse_groups(self) -> None:
        """解析群组配置"""
        for key, value in self._data.items():
            if key.startswith("group") and isinstance(value, dict):
                group_id = value.get("id")
                if group_id:
                    # 如果群组没有配置 summary_prompt，使用 default_prompt
                    group_prompt = value.get("summary_prompt")
                    if not group_prompt:
                        group_prompt = self.default_prompt

                    # 如果群组没有配置 html_renderer_template，使用 default_html_template
                    html_template = value.get("html_renderer_template")
                    if not html_template:
                        html_template = self.default_html_template

                    self._groups[str(group_id)] = {
                        "summary_prompt": group_prompt,
                        "html_renderer_template": html_template,
                        "scheduled_summary": value.get("scheduled_summary", {}),
                    }

    def get_group_config(self, group_id: str) -> dict:
        """获取指定群组的配置"""
        return self._groups.get(
            str(group_id),
            {
                "summary_prompt": self.default_prompt,
                "html_renderer_template": self.default_html_template,
                "scheduled_summary": {},
            },
        )

    def get_all_scheduled_groups(self) -> list:
        """获取所有启用了定时总结的群组配置"""
        scheduled_groups = []
        for group_id, config in self._groups.items():
            scheduled_config = config.get("scheduled_summary", {})
            if scheduled_config.get("enabled"):
                scheduled_groups.append(
                    {
                        "group_id": group_id,
                        "schedule_time": scheduled_config.get("schedule_time", "22:00"),
                        "interval": scheduled_config.get("interval", "24h"),
                    }
                )
        return scheduled_groups

    def merge(self, data) -> None:
        self._merge_data(data)
        self._sync_prompt()
        self._parse_groups()

    def get(self, key, default=None):
        return self._data.get(key, default)

    def to_dict(self) -> dict:
        merged = dict(self._data)
        merged["default_prompt"] = self.default_prompt
        merged["default_html_template"] = self.default_html_template
        merged["wake_prefix"] = self.wake_prefix
        return merged


def load_config(context, runtime_config=None) -> PluginConfig:
    """加载插件配置"""
    main_config = context.get_config() or {}

    plugin_config_path = os.path.join(
        "data", "config", "astrbot_plugin_chatsummary_config.json"
    )
    p_config = PluginConfig(plugin_config_path, runtime_config)

    p_config.wake_prefix = main_config.get("wake_prefix", [])
    p_config.merge({"wake_prefix": p_config.wake_prefix})

    return p_config
