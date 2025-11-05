# /astrbot_plugin_chatsummary/services/summary_service.py

from datetime import timedelta
from typing import Iterable

from ..utils import parse_time_delta
from .message_formatter import MessageFormatter
from .message_retriever import MessageRetriever


class SummaryService:
    """消息总结服务：负责协调消息获取和格式化"""

    def __init__(
        self,
        config,
    ):
        self.config = config
        self.message_retriever = MessageRetriever()
        self.message_formatter = MessageFormatter(config)

    async def get_messages_by_arg(
        self,
        client,
        group_id: int,
        arg: str,
    ) -> tuple[list | None, str]:
        """
        根据参数获取消息，返回消息列表和一条状态消息。

        Args:
            client: 平台客户端
            group_id: 群组ID
            arg: 参数（数量或时间）

        Returns:
            (消息列表, 状态消息)
        """
        time_delta = parse_time_delta(arg)

        if time_delta:
            status_message = (
                f"正在为您总结群 {group_id} 过去 {arg} 内的聊天记录，请稍候..."
            )
            messages = await self.message_retriever.get_messages_by_time(
                client,
                group_id,
                time_delta,
            )
            return self._ensure_list(messages), status_message
        elif arg.isdigit():
            count = int(arg)
            if not (0 < count <= 500):
                return None, "请提供一个介于 1 和 500 之间的数字。"
            status_message = (
                f"正在为您总结群 {group_id} 最近 {count} 条聊天记录，请稍候..."
            )
            messages = await self.message_retriever.get_messages_by_count(
                client,
                group_id,
                count,
            )
            return self._ensure_list(messages), status_message
        else:
            return (
                None,
                "参数格式不正确哦~\n请使用如「 /消息总结 30 」(数量) 或「 /消息总结 1h30m 」(时间) 的格式。",
            )

    async def format_messages(
        self, messages: list, my_id: int, llm_service=None, indent: int = 0
    ) -> str:
        """
        将从API获取的消息列表格式化为文本

        Args:
            messages: 消息列表
            my_id: 机器人自己的ID
            llm_service: 可选的LLM服务，如果提供则为图片生成描述
            indent: 当前的缩进级别

        Returns:
            格式化后的聊天文本
        """
        return await self.message_formatter.format_messages(
            messages,
            my_id,
            indent,
            llm_service,
        )

    async def get_messages_by_time(
        self, client, group_id: int, time_delta: timedelta
    ) -> list:
        """
        通过渐进式拉取的方式获取指定时间范围内的消息

        Args:
            client: 平台客户端
            group_id: 群组ID
            time_delta: 时间范围

        Returns:
            消息列表
        """
        messages = await self.message_retriever.get_messages_by_time(
            client,
            group_id,
            time_delta,
        )
        return self._ensure_list(messages)

    async def get_messages_by_count(
        self,
        client,
        group_id: int,
        count: int,
    ) -> list:
        """
        按数量获取消息

        Args:
            client: 平台客户端
            group_id: 群组ID
            count: 消息数量

        Returns:
            消息列表
        """
        messages = await self.message_retriever.get_messages_by_count(
            client,
            group_id,
            count,
        )
        return self._ensure_list(messages)

    @staticmethod
    def _ensure_list(messages: Iterable | None) -> list:
        if messages is None:
            return []
        if isinstance(messages, list):
            return messages
        return list(messages)
