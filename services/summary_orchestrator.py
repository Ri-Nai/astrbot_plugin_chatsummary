# /astrbot_plugin_chatsummary/services/summary_orchestrator.py

from typing import Iterable

from astrbot.api import html_renderer, logger
from ..utils import ImageRenderer

from .llm_service import (
    LLMEmptyResponseError,
    LLMRateLimitError,
    LLMTransientError,
)


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
        images_enabled = llm_for_image is not None
        if images_enabled:
            logger.info("启用图片描述功能，将为每张图片调用LLM获取描述")

        formatted_chat = await self.summary_service.format_messages(
            message_list,
            my_id,
            llm_for_image,
        )
        current_formatted_chat = formatted_chat
        summary_notes: list[str] = []
        degrade_info: tuple[str, bool] | None = None

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
            try:
                summary = await self._generate_summary(
                    formatted_chat,
                    group_config,
                )
            except LLMRateLimitError as rate_error:
                (
                    summary,
                    current_formatted_chat,
                    extra_notes,
                    degrade_info,
                ) = await self._handle_rate_limit_retry(
                    message_list=message_list,
                    my_id=my_id,
                    group_config=group_config,
                    base_error=rate_error,
                    formatted_chat=formatted_chat,
                    images_enabled=images_enabled,
                )
                summary_notes.extend(extra_notes)
            except (LLMTransientError, LLMEmptyResponseError) as transient_error:
                logger.error("调用LLM失败: %s", transient_error)
                degrade_info = (str(transient_error), False)
                summary = self._build_failure_summary(
                    str(transient_error),
                    current_formatted_chat,
                )
            except Exception as unexpected_error:
                logger.error("调用LLM失败(未分类): %s", unexpected_error)
                degrade_info = (str(unexpected_error), False)
                summary = self._build_failure_summary(
                    str(unexpected_error),
                    current_formatted_chat,
                )

        if summary_notes:
            summary = f"{summary}\n\n" + "\n".join(summary_notes)

        cleaned_summary = self._cleanup_summary(summary)

        if raise_on_failure and degrade_info is not None:
            error_message, rate_limited = degrade_info
            raise SummaryGenerationError(
                error_message,
                user_message=cleaned_summary,
                rate_limited=rate_limited,
            )

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

    async def _handle_rate_limit_retry(
        self,
        message_list: list,
        my_id: int,
        group_config: dict,
        base_error: Exception,
        formatted_chat: str,
        *,
        images_enabled: bool,
    ) -> tuple[str, str, list[str], tuple[str, bool] | None]:
        """限流时尝试在关闭图片描述后重试总结"""
        error_text = str(base_error)
        if not images_enabled:
            logger.error("总结触发限流，但图片描述已关闭: %s", error_text)
            summary = self._build_failure_summary(error_text, formatted_chat)
            return summary, formatted_chat, [], (error_text, True)

        logger.warning(
            "总结触发限流，将关闭图片描述后重试: %s",
            error_text,
        )
        notes = ["⚠️ 已自动关闭图片描述功能以避免触发限流。"]

        no_image_chat = await self.summary_service.format_messages(
            message_list,
            my_id,
            llm_service=None,
        )

        try:
            summary = await self._generate_summary(no_image_chat, group_config)
            return summary, no_image_chat, notes, None
        except LLMRateLimitError as retry_rate_error:
            retry_text = str(retry_rate_error)
            logger.error(
                "关闭图片描述后仍触发限流: %s",
                retry_text,
            )
            notes.append("⚠️ 关闭图片描述后仍触发限流，已输出降级结果。")
            summary = self._build_failure_summary(retry_text, no_image_chat)
            return summary, no_image_chat, notes, (retry_text, True)
        except (LLMTransientError, LLMEmptyResponseError) as retry_error:
            retry_text = str(retry_error)
            logger.error(
                "关闭图片描述后总结仍失败: %s",
                retry_text,
            )
            notes.append("⚠️ 关闭图片描述后仍无法生成自动总结。")
            summary = self._build_failure_summary(retry_text, no_image_chat)
            return summary, no_image_chat, notes, (retry_text, False)
        except Exception as unexpected:
            retry_text = str(unexpected)
            logger.error(
                "关闭图片描述后总结出现异常: %s",
                retry_text,
            )
            notes.append("⚠️ 关闭图片描述后仍无法生成自动总结。")
            summary = self._build_failure_summary(retry_text, no_image_chat)
            return summary, no_image_chat, notes, (retry_text, False)

    async def _generate_summary(
        self,
        formatted_chat: str,
        group_config: dict,
    ) -> str:
        prompt = group_config.get("summary_prompt", self.config.default_prompt)
        return await self.llm_service.get_summary(
            formatted_chat,
            prompt,
            max_retries=self.config.summary_max_retries,
            retry_delay=self.config.summary_retry_delay,
        )

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
        html_template_name = config.get(
            "html_renderer_template",
            self.config.default_html_template,
        )
        
        try:
            # 优先尝试本地渲染
            renderer = ImageRenderer(template_name=html_template_name)
            return await renderer.render(summary, group_id=str(group_id))
        except Exception as e:
            logger.error(f"本地渲染失败，尝试使用远程渲染: {e}")
            # 降级到远程渲染
            return await html_renderer.render_t2i(
                summary,
                template_name=html_template_name,
            )
        
    @staticmethod
    def _ensure_list(messages: Iterable | None) -> list:
        if messages is None:
            return []
        if isinstance(messages, list):
            return messages
        return list(messages)

    def _build_failure_summary(
        self,
        reason: str,
        formatted_chat: str | None,
        *,
        excerpt_length: int = 800,
    ) -> str:
        parts = ["⚠️ 总结失败：系统暂时无法生成自动总结。"]
        reason = reason.strip()
        if reason:
            parts.append(f"原因：{reason}")

        excerpt = self._build_chat_excerpt(formatted_chat, excerpt_length)
        if excerpt:
            parts.append("以下为最近聊天摘录：")
            parts.append(excerpt)

        return "\n\n".join(parts).strip()

    @staticmethod
    def _build_chat_excerpt(
        formatted_chat: str | None,
        max_chars: int = 800,
    ) -> str:
        if not formatted_chat:
            return ""

        text = formatted_chat.strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"
