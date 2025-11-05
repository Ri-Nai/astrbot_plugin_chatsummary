# /astrbot_plugin_chatsummary/services/scheduler_service.py

import asyncio
from datetime import datetime, timedelta
from astrbot.api import logger, html_renderer
from .summary_orchestrator import SummaryOrchestrator


class SchedulerService:
    """定时任务服务：负责管理定时总结任务"""

    def __init__(
        self,
        context,
        config,
        summary_service,
        summary_orchestrator: SummaryOrchestrator,
    ):
        self.context = context
        self.config = config
        self.summary_service = summary_service
        self.summary_orchestrator = summary_orchestrator
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
        platforms = self.context.platform_manager.get_insts()
        platform = next(
            (
                platform
                for platform in platforms
                if platform.metadata.name == "aiocqhttp"
            ),
            None,
        )

        if platform is None:
            logger.error("未找到 aiocqhttp 平台实例，无法发送定时总结")
            return
        client = platform.get_client()

        try:
            login_info = await client.api.call_action("get_login_info")
            my_id = login_info.get("user_id")
            my_name = login_info.get("nickname")
        except Exception as e:
            logger.error(f"获取登录信息失败: {e}")
            return

        # 使用编排服务创建总结和图片
        try:
            messages, status_message = await self.summary_service.get_messages_by_arg(
                client,
                int(group_id),
                interval,
            )

            if messages is None:
                logger.error(
                    "群 %s 定时总结获取消息失败: %s",
                    group_id,
                    status_message,
                )
                return

            summary, summary_image_url = (
                await self.summary_orchestrator.create_summary_with_image(
                    str(group_id),
                    my_id,
                    messages,
                    source=f"schedule:{interval}",
                )
            )
        except ValueError as e:
            logger.error(f"参数错误: {e}")
            return
        except Exception as e:
            logger.error(f"生成总结失败: {e}")
            summary = "抱歉,总结服务出现了一点问题。"
            # 使用默认模板生成错误图片
            group_config = self.config.get_group_config(str(group_id))
            html_template = group_config.get(
                "html_renderer_template",
                self.config.default_html_template,
            )
            summary_image_url = await html_renderer.render_t2i(
                summary,
                template_name=html_template,
            )
        # 4. 构建消息并发送
        text_payload = {
            "group_id": group_id,
            "messages": [
                {
                    "type": "node",
                    "data": {
                        "user_id": my_id,
                        "nickname": "AstrBot",
                        "content": [
                            {
                                "type": "text",
                                "data": {
                                    "text": f"【每日聊天总结】\n\n{summary}",
                                },
                            }
                        ],
                    },
                }
            ],
        }
        image_payload = {
            "group_id": group_id,
            "message": [
                {
                    "type": "image",
                    "data": {"file": summary_image_url},
                },
            ],
        }

        await client.api.call_action("send_group_forward_msg", **text_payload)
        await client.api.call_action("send_group_msg", **image_payload)

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
