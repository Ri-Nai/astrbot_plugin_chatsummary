# /astrbot_plugin_chatsummary/__init__.py

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core import logger

from .config import load_config
from .services import SummaryService, LLMService, SchedulerService, SummaryOrchestrator
from .handlers import ChatHandler, ScheduleHandler


@register(
    "astrbot_plugin_chatsummary",
    "Ri-Nai",
    "一个基于LLM的历史聊天记录总结插件",
    "1.3.0-refactored",
)
class ChatSummary(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        # 1. 加载配置
        self.config = load_config(self.context, config)

        # 2. 初始化服务层
        self.llm_service = LLMService(
            self.context,
            enable_image_description=self.config.enable_image_description,
            image_description_cache_size=self.config.image_description_cache_size,
            max_concurrent_image_requests=self.config.max_concurrent_image_requests,
            image_request_delay=self.config.image_request_delay,
        )
        self.summary_service = SummaryService(self.config)

        # 3. 初始化编排服务
        self.summary_orchestrator = SummaryOrchestrator(
            self.config, self.summary_service, self.llm_service
        )

        # 4. 初始化调度服务
        self.scheduler_service = SchedulerService(
            self.context,
            self.config,
            self.summary_service,
            self.summary_orchestrator,
        )

        # 5. 初始化处理器层
        self.chat_handler = ChatHandler(
            self.config, self.summary_service, self.summary_orchestrator
        )
        self.schedule_handler = ScheduleHandler(self.scheduler_service)

        # 6. 启动定时任务
        self.schedule_handler.start_scheduled_tasks()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("消息总结", alias={"省流", "总结一下"})
    async def summary(self, event: AstrMessageEvent, arg: str = None):
        """群聊场景触发消息总结。"""
        if arg is None:
            yield event.plain_result(
                "请提供要总结的消息数量或时间范围。\n例如:「 /消息总结 100 」或「 /消息总结 1h 」"
            )
            return

        group_id = event.get_group_id()
        async for result in self.chat_handler.process_summary_request(
            event,
            group_id,
            str(arg),
        ):
            yield result

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("群总结")
    async def private_summary(
        self, event: AstrMessageEvent, arg: str = None, group_id: int = None
    ):
        """私聊场景触发群消息总结。"""
        if arg is None or group_id is None:
            yield event.plain_result(
                "参数不足！\n请按照「 /群总结 [数量或时间] [群号] 」格式发送。"
            )
            return

        async for result in self.chat_handler.process_summary_request(
            event,
            group_id,
            str(arg),
        ):
            yield result

    @filter.command("help", alias={"帮助", "helpme"})
    async def help(self, event: AstrMessageEvent):
        """提供帮助信息。"""
        help_text = (
            "/help - 显示此帮助信息\n"
            "/消息总结 [数量或时间] - 在群聊中总结最近的聊天记录\n"
            "/群总结 [数量或时间] [群号] - 在私聊中总结指定群的聊天记录\n"
            "数量示例: 100 (总结最近100条消息)\n"
            "时间示例: 1h30m (总结过去1小时30分钟内的消息)"
        )
        yield event.plain_result(help_text)

    async def terminate(self):
        """插件卸载时的清理操作"""
        await self.schedule_handler.stop_scheduled_tasks()
        logger.info("聊天总结插件已卸载")
