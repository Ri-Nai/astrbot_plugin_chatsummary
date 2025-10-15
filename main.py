# /astrbot_plugin_chatsummary/__init__.py

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .config import load_config
from .services import SummaryService
from .handlers import ChatHandler

@register("astrbot_plugin_chatsummary", "laopanmemz", "一个基于LLM的历史聊天记录总结插件", "1.3.0-refactored")
class ChatSummary(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 1. 加载配置
        self.config = load_config(self.context)
        # 2. 初始化服务
        self.summary_service = SummaryService(self.context, self.config)
        # 3. 初始化处理器
        self.chat_handler = ChatHandler(self.context, self.config, self.summary_service)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("消息总结")
    async def summary(self, event: AstrMessageEvent, arg: str = None):
        """群聊场景触发消息总结。"""
        if arg is None:
            yield event.plain_result("请提供要总结的消息数量或时间范围。\n例如:「 /消息总结 100 」或「 /消息总结 1h 」")
            return
        
        group_id = event.get_group_id()
        async for result in self.chat_handler.process_summary_request(event, group_id, str(arg)):
            yield result

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("群总结")
    async def private_summary(self, event: AstrMessageEvent, arg: str = None, group_id: int = None):
        """私聊场景触发群消息总结。"""
        if arg is None or group_id is None:
            yield event.plain_result("参数不足！\n请按照「 /群总结 [数量或时间] [群号] 」格式发送。")
            return

        async for result in self.chat_handler.process_summary_request(event, group_id, str(arg)):
            yield result
