# /astrbot_plugin_chatsummary/__init__.py

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

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

        # 启动定时任务
        scheduled_config = self.config.get("scheduled_summary", {})
        if scheduled_config.get("enabled"):
            asyncio.create_task(self._run_scheduled_summaries())

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

    async def _run_scheduled_summaries(self):
        """后台定时任务，用于每天发送总结"""
        while True:
            now = datetime.now()
            schedule_time_str = self.config.get("scheduled_summary", {}).get(
                "schedule_time", "22:00"
            )
            schedule_time = datetime.strptime(schedule_time_str, "%H:%M").time()

            next_run = now.replace(
                hour=schedule_time.hour,
                minute=schedule_time.minute,
                second=0,
                microsecond=0,
            )
            if now > next_run:
                next_run += timedelta(days=1)

            sleep_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(sleep_seconds)

            # 执行总结任务
            scheduled_config = self.config.get("scheduled_summary", {})
            group_ids = scheduled_config.get("group_ids", [])
            interval = scheduled_config.get("interval", "24h")

            for group_id in group_ids:
                try:
                    await self.summary_service.create_and_send_scheduled_summary(
                        group_id, interval
                    )
                except Exception as e:
                    # 使用 AstrBot 的日志接口记录错误
                    from astrbot.core import logger

                    logger.error(f"为群 {group_id} 发送定时总结失败: {e}")
