# /astrbot_plugin_chatsummary/services/summary_orchestrator.py

from astrbot.api import html_renderer, logger
from ..utils import parse_time_delta


class SummaryOrchestrator:
    """总结编排服务：负责协调整个总结流程，不依赖同层其他Service"""

    def __init__(
        self, 
        config, 
        summary_service, 
        llm_service
    ):
        self.config = config
        self.summary_service = summary_service
        self.llm_service = llm_service

    async def create_summary_with_image(
        self, 
        client, 
        group_id: str, 
        arg: str, 
        my_id: int
    ) -> tuple[str, str]:
        """
        创建总结并生成图片
        
        Args:
            client: 平台客户端
            group_id: 群组ID
            arg: 参数（数量或时间）
            my_id: 机器人ID
            
        Returns:
            (总结文本, 图片URL)
        """
        # 1. 获取消息记录
        time_delta = parse_time_delta(arg)
        if time_delta:
            messages = await self.summary_service.get_messages_by_time(
                client, int(group_id), time_delta
            )
        elif arg.isdigit():
            count = int(arg)
            if not (0 < count <= 500):
                raise ValueError("请提供一个介于 1 和 500 之间的数字。")
            messages = await self.summary_service.get_messages_by_count(
                client, int(group_id), count
            )
        else:
            raise ValueError("参数格式不正确")

        if not messages:
            summary = "在指定范围内没有找到可以总结的聊天记录。"
        else:
            # 2. 格式化消息
            formatted_chat = self.summary_service.format_messages(messages, my_id)
            logger.info(
                f"总结: group_id={group_id} arg={arg} msg_length={len(formatted_chat)} content:\n{formatted_chat}"
            )
            
            if not formatted_chat:
                summary = "筛选后没有可供总结的聊天内容。"
            else:
                try:
                    # 3. 获取提示词并生成总结
                    group_config = self.config.get_group_config(str(group_id))
                    prompt = group_config.get(
                        "summary_prompt",
                        self.config.default_prompt,
                    )
                    summary = await self.llm_service.get_summary(formatted_chat, prompt)
                except Exception as e:
                    logger.error(f"调用LLM失败: {e}")
                    summary = "抱歉,总结服务出现了一点问题。"
        if summary.startswith("```md"):
            summary = summary[5:]
        if summary.startswith("```markdown"):
            summary = summary[11:]
        if summary.endswith("```"):
            summary = summary[:-3]
        # 4. 生成图片
        group_config = self.config.get_group_config(str(group_id))
        html_template = group_config.get(
            "html_renderer_template",
            self.config.default_html_template,
        )
        
        summary_image_url = await html_renderer.render_t2i(
            summary,
            template_name=html_template,
        )
        
        return summary, summary_image_url