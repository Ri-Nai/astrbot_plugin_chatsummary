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
            # 2. 格式化消息（支持图片描述）
            group_config = self.config.get_group_config(str(group_id))
            enable_image_description = group_config.get("enable_image_description", True)
            
            # 如果启用图片描述，传入 llm_service，否则传 None
            llm_for_image = self.llm_service if enable_image_description else None
            if enable_image_description:
                logger.info("启用图片描述功能，将为每张图片调用LLM获取描述")
            
            formatted_chat = await self.summary_service.format_messages(
                messages, my_id, llm_for_image
            )
                
            logger.info(
                f"总结: group_id={group_id} arg={arg} msg_length={len(formatted_chat)} content:\n{formatted_chat}"
            )
            
            if not formatted_chat:
                summary = "筛选后没有可供总结的聊天内容。"
            else:
                try:
                    # 3. 获取提示词并生成总结
                    prompt = group_config.get(
                        "summary_prompt",
                        self.config.default_prompt,
                    )
                    summary = await self.llm_service.get_summary(
                        formatted_chat, 
                        prompt,
                        max_retries=self.config.summary_max_retries,
                        retry_delay=self.config.summary_retry_delay,
                    )
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"调用LLM失败: {e}")
                    
                    # 根据错误类型提供不同的提示信息
                    if "429" in error_msg or "Request limit exceeded" in error_msg or "请求过于频繁" in error_msg:
                        summary = (
                            "⚠️ 总结失败：API 请求频率超限\n\n"
                            "可能的原因：\n"
                            "1. 图片描述功能调用过于频繁\n"
                            "2. API 配额已用尽\n\n"
                            "建议解决方案：\n"
                            "• 降低图片描述并发数（配置项：max_concurrent_image_requests，建议设为 1-2）\n"
                            "• 增加图片请求延迟（配置项：image_request_delay，建议设为 1.0-2.0）\n"
                            "• 暂时关闭图片描述功能（配置项：enable_image_description，设为 false）\n"
                            "• 等待几分钟后重试"
                        )
                    else:
                        summary = f"⚠️ 总结失败：{error_msg}\n\n请检查 LLM 配置或稍后重试。"
        if summary.startswith("```md"):
            summary = summary[5:]
        if summary.startswith("```markdown"):
            summary = summary[11:]
        if summary.endswith("```"):
            summary = summary[:-3]
        summary = summary.strip()
        # 4. 生成图片
        if 'group_config' not in locals():
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