# /astrbot_plugin_chatsummary/config.py

import os
import json
from astrbot.core import logger

class PluginConfig:
    def __init__(self, config_file_path: str):
        self.prompt = "请总结以下聊天记录："
        self.wake_prefix = []
        
        try:
            with open(config_file_path, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
                self.prompt = str(config.get('prompt', self.prompt)).replace('\\n', '\n')
        except FileNotFoundError:
            logger.warning("聊天总结插件配置文件未找到，将使用默认Prompt。")
        except Exception as e:
            logger.error(f"加载聊天总结插件配置文件时出错: {e}")

def load_config(context) -> PluginConfig:
    """加载插件配置"""
    # 从主配置获取唤醒前缀
    main_config = context.get_config()
    
    # 加载插件自己的配置
    plugin_config_path = os.path.join('data', 'config', 'astrbot_plugin_chatsummary_config.json')
    p_config = PluginConfig(plugin_config_path)
    
    # 合并配置
    p_config.wake_prefix = main_config.get("wake_prefix", [])
    
    return p_config
