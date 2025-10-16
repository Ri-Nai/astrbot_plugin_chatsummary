# /astrbot_plugin_chatsummary/__init__.py

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core import logger

from .config import load_config
from .services import SummaryService
from .handlers import ChatHandler

import asyncio
from datetime import datetime, timedelta


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
        # 2. 初始化服务
        self.summary_service = SummaryService(self.context, self.config)
        # 3. 初始化处理器
        self.chat_handler = ChatHandler(self.context, self.config, self.summary_service)

        # 为每个启用定时总结的群组创建独立的异步任务
        scheduled_groups = self.config.get_all_scheduled_groups()
        for group_info in scheduled_groups:
            asyncio.create_task(
                self._run_group_scheduled_summary(
                    group_info["group_id"],
                    group_info["schedule_time"],
                    group_info["interval"]
                )
            )

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
            event, group_id, str(arg)
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
            event, group_id, str(arg)
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

    async def _run_group_scheduled_summary(self, group_id: str, schedule_time_str: str, interval: str):
        """为单个群组运行定时总结任务"""
        schedule_time = datetime.strptime(schedule_time_str, "%H:%M").time()
        
        while True:
            # 计算下次执行时间
            now = datetime.now()
            next_run = now.replace(
                hour=schedule_time.hour,
                minute=schedule_time.minute,
                second=0,
                microsecond=0,
            )
            
            # 如果今天的时间已过，则设置为明天
            if now >= next_run:
                next_run += timedelta(days=1)
            
            # 等待到执行时间
            sleep_seconds = (next_run - now).total_seconds()
            logger.info(f"群 {group_id} 的定时总结将在 {next_run.strftime('%Y-%m-%d %H:%M:%S')} 执行")
            await asyncio.sleep(sleep_seconds)
            
            # 执行总结任务
            try:
                await self.summary_service.create_and_send_scheduled_summary(
                    group_id, interval
                )
                logger.info(f"群 {group_id} 定时总结执行成功")
            except Exception as e:
                logger.error(f"为群 {group_id} 发送定时总结失败: {e}")
            
            # 等待1分钟，避免在同一分钟内重复执行
            await asyncio.sleep(60)
