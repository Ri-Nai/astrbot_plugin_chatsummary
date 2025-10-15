# /astrbot_plugin_chatsummary/handlers.py

from astrbot.api.event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.core import logger
from .services import SummaryService
from .utils import parse_time_delta

class ChatHandler:
    def __init__(self, context, config, service: SummaryService):
        self.context = context
        self.config = config
        self.service = service

    async def process_summary_request(self, event: AstrMessageEvent, group_id: int, arg: str):
        """处理总结逻辑的通用函数"""
        client = event.bot
        assert isinstance(event, AiocqhttpMessageEvent)
        
        try:
            login_info = await client.api.call_action("get_login_info")
            my_id = login_info.get("user_id")
        except Exception as e:
            logger.error(f"获取登录信息失败: {e}")
            yield event.plain_result("抱歉，获取Bot信息失败，无法继续操作。")
            return

        messages, status_message = await self.service.get_messages_by_arg(client, group_id, arg)
        yield event.plain_result(status_message)
        
        if not messages:
            yield event.plain_result("在指定范围内没有找到可以总结的聊天记录。")
            return

        formatted_chat = self.service._format_messages(messages, my_id)
        if not formatted_chat:
            yield event.plain_result("筛选后没有可供总结的聊天内容。")
            return
            
        logger.info(f"chat_summary: group_id={group_id} a_param={arg} msg_length={len(formatted_chat)} content:\n{formatted_chat}")
        
        try:
            summary_text = await self.service.get_summary_from_llm(formatted_chat)
            yield event.plain_result(summary_text)
        except Exception:
            yield event.plain_result("抱歉，总结服务出现了一点问题，请稍后再试。")
