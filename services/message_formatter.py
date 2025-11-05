# /astrbot_plugin_chatsummary/services/message_formatter.py

import json
from datetime import datetime
from astrbot.api import logger
from ..utils import JsonMessageParser


class MessageFormatter:
    """消息格式化服务：负责将原始消息格式化为可读文本"""

    def __init__(self, config):
        self.config = config

    def _get_sender_display_name(self, sender: dict) -> str:
        """获取发送者的显示名称，优先使用card，然后是nickname，最后是未知用户"""
        return sender.get("card") or sender.get("nickname", "未知用户")

    @staticmethod
    def _extract_image_url(data: dict) -> str:
        """从图片消息段中提取URL"""
        url = data.get("url") or data.get("file")
        if isinstance(url, str) and url:
            return url
        return ""

    @staticmethod
    def _is_valid_image_url(url: str) -> bool:
        """检查是否是有效的图片URL（HTTP(S)开头）"""
        if not isinstance(url, str) or not url:
            return False
        url_lower = url.lower()
        return url_lower.startswith("http://") or url_lower.startswith("https://")

    async def _format_message_part(self, my_id: int, part: dict, messages: list, current_indent: int, llm_service=None) -> str:
        """格式化单个消息部分"""
        part_type = part.get("type")
        data = part.get("data", {})
        indent_str = " " * current_indent

        if part_type == "text":
            return data.get("text", "").strip()
        elif part_type == "image":
            # 如果提供了 llm_service，则调用LLM获取图片描述
            if llm_service:
                img_url = self._extract_image_url(data)
                if img_url and self._is_valid_image_url(img_url):
                    try:
                        logger.info(f"正在为图片获取描述: {img_url[:50]}...")
                        description = await llm_service.get_image_description(img_url)
                        return description
                    except Exception as e:
                        # 双重保护：即使 get_image_description 内部失败，这里也能捕获
                        logger.warning(f"图片描述失败（已降级）: {img_url[:50]}... - {e}")
                        return "[图片]"
            return "[图片]"
        elif part_type == "video":
            return "[视频]"
        elif part_type == "face":
            return "[表情]"
        elif part_type == "reply":
            return "[回复消息]"
        elif part_type == "json":
            try:
                json_data = json.loads(data.get("data", "{}"))
                return f"\n{JsonMessageParser.parse_json(json_data, current_indent + 2)}\n{indent_str}"
            except json.JSONDecodeError:
                return "[无法读取的分享内容]"
        elif part_type == "forward":
            forward_msg_list = data.get("content", [])
            formatted_forward = await self.format_messages(
                forward_msg_list,
                my_id,
                indent=current_indent + 2,
                llm_service=llm_service,
            )
            return (
                f"\n{indent_str}{{\n"
                f"{formatted_forward}\n"
                f"{indent_str}}}"
            )
        return "" # 未知消息类型

    async def format_messages(self, messages: list, my_id: int, indent: int = 0, llm_service=None) -> str:
        """
        将从API获取的消息列表格式化为文本

        Args:
            messages: 消息列表
            my_id: 机器人自己的ID
            indent: 当前的缩进级别
            llm_service: 可选的LLM服务，如果提供则为图片生成描述

        Returns:
            格式化后的聊天文本
        """
        formatted_lines = []
        indent_str = " " * indent

        for msg in messages:
            sender = msg.get("sender", {})
            if my_id == sender.get("user_id"):
                continue # 忽略机器人自己的消息

            # 确保 message 是列表类型
            message_parts = msg.get("message")
            if not isinstance(message_parts, list) or not message_parts:
                continue

            nickname = self._get_sender_display_name(sender)
            msg_time = datetime.fromtimestamp(msg.get("time", 0))

            full_message_text = []
            for part in message_parts:
                try:
                    part_text = await self._format_message_part(my_id, part, messages, indent, llm_service)
                    if part_text:
                        full_message_text.append(part_text)
                except Exception as e:
                    # 确保单个消息部分处理失败不会影响整个消息
                    logger.error(f"处理消息部分失败，已跳过: {e}")
                    # 如果是图片类型，添加占位符
                    if part.get("type") == "image":
                        full_message_text.append("[图片]")
                    continue

            pure_text = " ".join(full_message_text).strip()

            # 处理唤醒前缀
            is_wake_message = False
            for prefix in self.config.wake_prefix:
                if pure_text.startswith(f"{prefix}image"):
                    pure_text = pure_text[len(f"{prefix}image"):].strip()
                    is_wake_message = True
                    break # 找到匹配项后跳出
                elif pure_text.startswith(prefix):
                    is_wake_message = True
                    break

            if is_wake_message:
                 continue # 如果是唤醒消息且配置为不包含，则跳过

            # 只有当消息内容不为空时才添加
            if pure_text:
                formatted_lines.append(
                    f"{indent_str}"
                    f"[{msg_time.strftime('%Y-%m-%d %H:%M:%S')}]"
                    f"「{nickname}」: "
                    f"{pure_text}"
                )
        return "\n".join(formatted_lines)