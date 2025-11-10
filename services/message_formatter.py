# /astrbot_plugin_chatsummary/services/message_formatter.py

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING

from astrbot.api import logger

from ..utils import JsonMessageParser

if TYPE_CHECKING:
    from .llm_service import LLMService


@dataclass(frozen=True)
class MessagePartContext:
    """封装消息段处理所需的上下文信息"""

    my_id: int
    part: Dict[str, Any]
    all_messages: list
    indent: int
    llm_service: "LLMService | None"

    @property
    def data(self) -> Dict[str, Any]:
        raw = self.part.get("data", {})
        return raw if isinstance(raw, dict) else {}

    @property
    def indent_str(self) -> str:
        return " " * self.indent


PartHandler = Callable[[MessagePartContext], Awaitable[str]]


class MessageFormatter:
    """消息格式化服务：负责将原始消息格式化为可读文本"""

    def __init__(self, config):
        self.config = config
        self._part_handlers: Dict[str, PartHandler] = {
            "text": self._handle_text_part,
            "image": self._handle_image_part,
            "video": self._handle_video_part,
            "face": self._handle_face_part,
            "reply": self._handle_reply_part,
            "json": self._handle_json_part,
            "forward": self._handle_forward_part,
        }

    async def _collect_message_text(
        self,
        my_id: int,
        message_parts: list,
        all_messages: list,
        current_indent: int,
        llm_service=None,
        skip_reply: bool = False,
    ) -> str:
        """汇总一条消息中的各个部分文本"""
        if not isinstance(message_parts, list):
            return ""

        collected_parts: list[str] = []

        for part in message_parts:
            if not isinstance(part, dict):
                continue

            if skip_reply and part.get("type") == "reply":
                continue

            context = MessagePartContext(
                my_id=my_id,
                part=part,
                all_messages=all_messages,
                indent=current_indent,
                llm_service=llm_service,
            )

            try:
                part_text = await self._format_message_part(context)
                if part_text:
                    collected_parts.append(part_text)
            except Exception as e:
                logger.error(f"处理消息部分失败，已跳过: {e}")
                if part.get("type") == "image":
                    collected_parts.append("[图片]")

        return " ".join(collected_parts).strip()

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

    async def _format_message_part(self, context: MessagePartContext) -> str:
        """基于注册表分发消息段处理逻辑"""
        part_type = context.part.get("type")
        handler = self._part_handlers.get(part_type, self._handle_unknown_part)
        return await handler(context)

    async def _handle_text_part(self, context: MessagePartContext) -> str:
        return context.data.get("text", "").strip()

    async def _handle_image_part(self, context: MessagePartContext) -> str:
        llm_service = context.llm_service
        image_summary = context.data.get("summary", "")
        if image_summary == "[动画表情]":
            return "[动画表情]"
        if llm_service:
            img_url = self._extract_image_url(context.data)
            if img_url and self._is_valid_image_url(img_url):
                try:
                    logger.info(f"正在为图片获取描述: {img_url[:50]}...")
                    description = await llm_service.get_image_description(img_url)
                    return description
                except Exception as e:
                    logger.warning(
                        f"图片描述失败（已降级）: {img_url[:50]}... - {e}"
                    )
        return "[图片]"

    async def _handle_video_part(self, context: MessagePartContext) -> str:  # noqa: D401
        return "[视频]"

    async def _handle_face_part(self, context: MessagePartContext) -> str:  # noqa: D401
        return "[表情]"

    async def _handle_reply_part(self, context: MessagePartContext) -> str:
        reply_id = context.data.get("id")
        replied_message = self._find_replied_message(reply_id, context.all_messages)

        reply_sender = ""
        reply_content = ""

        if replied_message:
            reply_sender = self._get_sender_display_name(
                replied_message.get("sender", {})
            )
            reply_content = await self._collect_message_text(
                context.my_id,
                replied_message.get("message", []),
                context.all_messages,
                context.indent,
                context.llm_service,
                skip_reply=True,
            )
            if not reply_content:
                raw_message = replied_message.get("raw_message")
                if isinstance(raw_message, str):
                    reply_content = raw_message.strip()
        else:
            nickname = context.data.get("nickname") or context.data.get("name")
            if isinstance(nickname, str) and nickname.strip():
                reply_sender = nickname.strip()
            else:
                reply_sender_id = context.data.get("qq") or context.data.get("user_id")
                if reply_sender_id:
                    reply_sender = str(reply_sender_id)

            fallback_text = context.data.get("text")
            if isinstance(fallback_text, str) and fallback_text.strip():
                reply_content = fallback_text.strip()

        if reply_content:
            return f"[回复消息: {reply_sender}: {reply_content}]"
        if reply_sender:
            return f"[回复消息: {reply_sender}]"
        return "[回复消息]"

    async def _handle_json_part(self, context: MessagePartContext) -> str:
        try:
            json_data = json.loads(context.data.get("data", "{}"))
            parsed = JsonMessageParser.parse_json(json_data, context.indent + 2)
            return f"\n{parsed}\n{context.indent_str}"
        except json.JSONDecodeError:
            return "[无法读取的分享内容]"

    async def _handle_forward_part(self, context: MessagePartContext) -> str:
        forward_msg_list = context.data.get("content", [])
        formatted_forward = await self.format_messages(
            forward_msg_list,
            context.my_id,
            indent=context.indent + 2,
            llm_service=context.llm_service,
        )
        return (
            f"\n{context.indent_str}{{\n"
            f"{formatted_forward}\n"
            f"{context.indent_str}}}"
        )

    async def _handle_unknown_part(self, context: MessagePartContext) -> str:  # noqa: D401
        return ""

    def _find_replied_message(self, reply_id: Any, messages: list) -> Optional[dict]:
        if reply_id is None or not isinstance(messages, list):
            return None

        reply_id_str = str(reply_id)
        for candidate in messages:
            if not isinstance(candidate, dict):
                continue
            candidate_id_match = any(
                reply_id_str == str(candidate.get(key))
                for key in ("message_id", "message_seq", "id")
            )
            if candidate_id_match:
                return candidate
        return None

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
        if not isinstance(messages, list):
            messages = list(messages)

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

            pure_text = await self._collect_message_text(
                my_id,
                message_parts,
                messages,
                indent,
                llm_service,
            )

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