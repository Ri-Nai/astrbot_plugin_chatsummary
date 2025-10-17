# /astrbot_plugin_chatsummary/handlers/chat_handler.py

from astrbot.api.event import AstrMessageEvent
from astrbot.core import html_render
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core import logger
from ..services import SummaryService, LLMService


class ChatHandler:
    """聊天处理器：负责处理用户的总结请求"""
    
    def __init__(self, config, summary_service: SummaryService, llm_service: LLMService):
        self.config = config
        self.summary_service = summary_service
        self.llm_service = llm_service

    async def process_summary_request(
        self, event: AstrMessageEvent, group_id: int, arg: str
    ):
        """
        处理总结请求的通用函数
        
        Args:
            event: 消息事件
            group_id: 群组ID
            arg: 参数（数量或时间）
            
        Yields:
            处理结果消息
        """
        client = event.bot
        assert isinstance(event, AiocqhttpMessageEvent)

        # 获取Bot信息
        try:
            login_info = await client.api.call_action("get_login_info")
            my_id = login_info.get("user_id")
        except Exception as e:
            logger.error(f"获取登录信息失败: {e}")
            yield event.plain_result("抱歉，获取Bot信息失败，无法继续操作。")
            return

        # 获取消息列表
        messages, status_message = await self.summary_service.get_messages_by_arg(
            client, group_id, arg
        )
        yield event.plain_result(status_message)

        if not messages:
            yield event.plain_result("在指定范围内没有找到可以总结的聊天记录。")
            return

        # 格式化消息
        formatted_chat = self.summary_service.format_messages(messages, my_id)
        if not formatted_chat:
            yield event.plain_result("筛选后没有可供总结的聊天内容。")
            return

        logger.info(
            f"chat_summary: group_id={group_id} a_param={arg} msg_length={len(formatted_chat)} content:\n{formatted_chat}"
        )

        # 调用LLM生成总结
        try:
            # 获取群组配置的提示词
            group_config = self.config.get_group_config(str(group_id))
            prompt = group_config.get("summary_prompt", self.config.default_prompt)
            
            summary_text = await self.llm_service.get_summary(formatted_chat, prompt)
            yield event.plain_result(summary_text)

            summary_image_url = await html_render.render_t2i(summary_text)
            yield event.image_result(summary_image_url)
        except Exception as e:
            yield event.plain_result("抱歉，总结服务出现了一点问题，请稍后再试。")
            logger.error(f"生成总结失败: {e}")
