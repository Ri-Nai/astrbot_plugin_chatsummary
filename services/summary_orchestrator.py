# /astrbot_plugin_chatsummary/services/summary_orchestrator.py

from typing import Iterable

from astrbot.api import html_renderer, logger


class SummaryGenerationError(RuntimeError):
    """总结生成异常，包含用户可读信息"""

    def __init__(self, message: str, *, user_message: str, rate_limited: bool = False):
        super().__init__(message)
        self.user_message = user_message
        self.rate_limited = rate_limited


class SummaryOrchestrator:
    """总结编排服务：负责协调整个总结流程，不依赖同层其他Service"""

    def __init__(
        self,
        config,
        summary_service,
        llm_service,
    ):
        self.config = config
        self.summary_service = summary_service
        self.llm_service = llm_service

    async def create_summary_with_image(
        self,
        group_id: str,
        my_id: int,
        messages: Iterable | None,
        *,
        source: str | None = None,
        raise_on_failure: bool = False,
    ) -> tuple[str, str]:
        """基于已有消息生成总结与图片"""

        group_config = self.config.get_group_config(str(group_id))
        message_list = self._ensure_list(messages)

        if not message_list:
            summary = "在指定范围内没有找到可以总结的聊天记录。"
            summary_image_url = await self._render_summary_image(
                group_id,
                summary,
                group_config=group_config,
            )
            return summary, summary_image_url

        llm_for_image = self._resolve_image_llm(group_config)
        if llm_for_image:
            logger.info("启用图片描述功能，将为每张图片调用LLM获取描述")

        formatted_chat = await self.summary_service.format_messages(
            message_list,
            my_id,
            llm_for_image,
        )

        logger.info(
            "总结任务: group_id=%s source=%s formatted_length=%s",
            group_id,
            source or "-",
            len(formatted_chat),
        )
        if formatted_chat:
            logger.debug("格式化聊天内容:\n%s", formatted_chat)

        if not formatted_chat:
            summary = "筛选后没有可供总结的聊天内容。"
        else:
            summary = await self._generate_summary(
                formatted_chat,
                group_config,
                raise_on_failure=raise_on_failure,
            )

        cleaned_summary = self._cleanup_summary(summary)
        summary_image_url = await self._render_summary_image(
            group_id,
            cleaned_summary,
            group_config=group_config,
        )
        return cleaned_summary, summary_image_url

    def _resolve_image_llm(self, group_config: dict):
        enable_image_description = group_config.get(
            "enable_image_description",
            getattr(self.config, "enable_image_description", True),
        )
        return self.llm_service if enable_image_description else None

    async def _generate_summary(
        self,
        formatted_chat: str,
        group_config: dict,
        *,
        raise_on_failure: bool = False,
    ) -> str:
        prompt = group_config.get("summary_prompt", self.config.default_prompt)
        try:
            return await self.llm_service.get_summary(
                formatted_chat,
                prompt,
                max_retries=self.config.summary_max_retries,
                retry_delay=self.config.summary_retry_delay,
            )
        except Exception as e:
            error_msg = str(e)
            logger.error("调用LLM失败: %s", error_msg)

            if self._is_rate_limit_error(error_msg):
                user_message = (
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

                if raise_on_failure:
                    raise SummaryGenerationError(
                        error_msg,
                        user_message=user_message,
                        rate_limited=True,
                    ) from e

                return user_message

            user_message = (
                f"⚠️ 总结失败：{error_msg}\n\n请检查 LLM 配置或稍后重试。"
            )

            if raise_on_failure:
                raise SummaryGenerationError(
                    error_msg,
                    user_message=user_message,
                    rate_limited=False,
                ) from e

            return user_message

    @staticmethod
    def _cleanup_summary(summary: str) -> str:
        if not isinstance(summary, str):
            return ""

        cleaned = summary.strip()
        if cleaned.startswith("```md"):
            cleaned = cleaned[5:]
        if cleaned.startswith("```markdown"):
            cleaned = cleaned[11:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()

    async def _render_summary_image(
        self,
        group_id: str,
        summary: str,
        *,
        group_config: dict | None = None,
    ) -> str:
        config = group_config or self.config.get_group_config(str(group_id))
        html_template = config.get(
            "html_renderer_template",
            self.config.default_html_template,
        )
        return await html_renderer.render_t2i(
            summary,
            template_name=html_template,
        )

    @staticmethod
    def _is_rate_limit_error(error_msg: str) -> bool:
        lowered = error_msg.lower()
        return (
            "429" in error_msg
            or "request limit exceeded" in lowered
            or "rate limit" in lowered
            or "请求过于频繁" in error_msg
        )

    @staticmethod
    def _ensure_list(messages: Iterable | None) -> list:
        if messages is None:
            return []
        if isinstance(messages, list):
            return messages
        return list(messages)
