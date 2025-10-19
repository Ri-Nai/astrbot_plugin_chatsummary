# /astrbot_plugin_chatsummary/services/scheduler_service.py

import asyncio
from datetime import datetime, timedelta
from astrbot.api import logger, html_renderer
from ..utils import parse_time_delta
from .summary_service import SummaryService
from .llm_service import LLMService


class SchedulerService:
    """定时任务服务：负责管理定时总结任务"""

    def __init__(
        self, context, config, summary_service: SummaryService, llm_service: LLMService
    ):
        self.context = context
        self.config = config
        self.summary_service = summary_service
        self.llm_service = llm_service
        self.platforms = self.context.platform_manager.get_insts()
        self.scheduled_tasks = []

    def start_all_scheduled_tasks(self):
        """启动所有配置的定时任务"""
        scheduled_groups = self.config.get_all_scheduled_groups()
        for group_info in scheduled_groups:
            task = asyncio.create_task(
                self._run_group_scheduled_summary(
                    group_info["group_id"],
                    group_info["schedule_time"],
                    group_info["interval"],
                )
            )
            self.scheduled_tasks.append(task)
            logger.info(f"已启动群 {group_info['group_id']} 的定时总结任务")

    async def _run_group_scheduled_summary(
        self, group_id: str, schedule_time_str: str, interval: str
    ):
        """
        为单个群组运行定时总结任务

        Args:
            group_id: 群组ID
            schedule_time_str: 定时时间（格式：HH:MM）
            interval: 总结时间范围
        """
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
            logger.info(
                f"群 {group_id} 的定时总结将在 {next_run.strftime('%Y-%m-%d %H:%M:%S')} 执行"
            )
            await asyncio.sleep(sleep_seconds)

            # 执行总结任务
            try:
                await self.create_and_send_scheduled_summary(group_id, interval)
                logger.info(f"群 {group_id} 定时总结执行成功")
            except Exception as e:
                logger.error(f"为群 {group_id} 发送定时总结失败: {e}")

            # 等待1分钟，避免在同一分钟内重复执行
            await asyncio.sleep(60)

    async def create_and_send_scheduled_summary(self, group_id: str, interval: str):
        """
        生成并发送定时的聊天总结

        Args:
            group_id: 群组ID
            interval: 总结时间范围
        """
        for platform in self.platforms:
            if (
                not hasattr(platform, "get_client")
                or not platform.get_client()
                or not hasattr(platform.get_client().api, "call_action")
            ):
                continue
            client = platform.get_client()

            try:
                login_info = await client.api.call_action("get_login_info")
                my_id = login_info.get("user_id")
            except Exception as e:
                logger.error(f"获取登录信息失败: {e}")
                return

            # 1. 获取消息记录
            time_delta = parse_time_delta(interval)
            if not time_delta:
                logger.error(f"无效的时间间隔: {interval}")
                return
            messages = await self.summary_service.get_messages_by_time(
                client, int(group_id), time_delta
            )

            if not messages:
                summary = "在过去的一段时间里，本群没有任何新消息。"
            else:
                # 2. 格式化消息
                formatted_chat = self.summary_service.format_messages(messages, my_id)
                logger.info(
                    f"定时总结: group_id={group_id} msg_length={len(formatted_chat)} content:\n{formatted_chat}"
                )
                if not formatted_chat:
                    summary = "筛选后没有可供总结的聊天内容。"
                else:
                    try:
                        # 3. 获取提示词、HTML模板并生成总结
                        group_config = self.config.get_group_config(str(group_id))
                        prompt = group_config.get(
                            "summary_prompt",
                            self.config.default_prompt,
                        )
                        html_template = group_config.get(
                            "html_renderer_template",
                            self.config.default_html_template,
                        )
                        summary = await self.llm_service.get_summary(
                            formatted_chat,
                            prompt,
                        )
                    except Exception as e:
                        logger.error(f"调用LLM失败: {e}")
                        summary = "抱歉,总结服务出现了一点问题。"
                        html_template = self.config.default_html_template
            summary_image_url = await html_renderer.render_t2i(
                summary,
                template_name=html_template,
            )
            # 4. 构建消息并发送
            payload = {
                "group_id": group_id,
                "message": [
                    {
                        "type": "text",
                        "data": {"text": f"【每日聊天总结】\n\n{summary}"},
                    },
                    {
                        "type": "image",
                        "data": {"file": summary_image_url},
                    },
                ],
            }

            await client.api.call_action("send_group_msg", **payload)

    async def stop_all_tasks(self):
        """停止所有定时任务"""
        logger.info(f"正在取消 {len(self.scheduled_tasks)} 个定时总结任务...")
        for task in self.scheduled_tasks:
            if not task.done():
                task.cancel()

        # 等待所有任务完成取消
        if self.scheduled_tasks:
            await asyncio.gather(*self.scheduled_tasks, return_exceptions=True)

        logger.info("所有定时任务已清理")
