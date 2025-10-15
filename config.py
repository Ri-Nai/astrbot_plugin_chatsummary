# /astrbot_plugin_chatsummary/config.py

import os
import json
from collections.abc import Mapping
from astrbot.core import logger


class PluginConfig:
    def __init__(self, config_file_path: str, initial_data=None):
        self.prompt = "请总结以下聊天记录："
        self.wake_prefix = []
        self._data = {}

        if initial_data is not None:
            self.merge(initial_data)

        self._load_from_file(config_file_path)
        self._sync_prompt()
        self._data.setdefault("scheduled_summary", {})

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
        prompt_value = self._data.get("prompt", self.prompt)
        self.prompt = str(prompt_value).replace("\\n", "\n")

    def merge(self, data) -> None:
        self._merge_data(data)
        self._sync_prompt()

    def get(self, key, default=None):
        return self._data.get(key, default)

    def to_dict(self) -> dict:
        merged = dict(self._data)
        merged["prompt"] = self.prompt
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

    if p_config.get("scheduled_summary") is None:
        p_config.merge({"scheduled_summary": {}})

    return p_config
