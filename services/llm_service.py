# /astrbot_plugin_chatsummary/services/llm_service.py

from astrbot.api import logger


class LLMService:
    """LLM 服务：负责与大语言模型交互"""

    def __init__(
        self,
        context,
    ):
        self.context = context

    async def get_summary(
        self,
        formatted_chat: str,
        prompt: str,
    ) -> str:
        """
        调用LLM获取总结

        Args:
            formatted_chat: 格式化后的聊天内容
            prompt: 使用的提示词

        Returns:
            LLM生成的总结文本

        Raises:
            Exception: LLM调用失败时抛出异常
        """
        try:
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=prompt,
                contexts=[{"role": "user", "content": formatted_chat}],
            )
            return llm_response.completion_text
        except Exception as e:
            logger.error(f"调用LLM服务失败: {e}")
            raise

    async def get_image_description(
        self,
        image_url: str,
        prompt: str = "请用一段话简洁描述这张图片的内容（不超过50字）。",
    ) -> str:
        """
        调用支持视觉的LLM获取图片描述（参照 ref.py 的实现）

        Args:
            image_url: 图片URL
            prompt: 描述提示词

        Returns:
            图片描述文本，失败时返回 "[图片]"
        """
        try:
            provider = self.context.get_using_provider()
            # 检查 provider 是否支持图片
            supports_image = False
            provider_config = getattr(provider, "provider_config", {})
            try:
                modalities = provider_config.get("modalities", None)
                if isinstance(modalities, (list, tuple)):
                    ml = [str(m).lower() for m in modalities]
                    if any(k in ml for k in ["image", "vision", "multimodal"]):
                        supports_image = True
            except Exception:
                pass

            if not supports_image:
                logger.warning("当前LLM不支持视觉能力，跳过图片描述")
                return "[图片]"

            # 调用 LLM
            llm_response = await provider.text_chat(
                prompt=prompt,
                context=[],
                system_prompt="你是一个图片描述助手，请简洁准确地描述图片内容。",
                image_urls=[image_url],
            )

            # 提取文本
            description = llm_response.completion_text

            if description and description != "（未解析到可读内容）":
                logger.info(
                    f"图片描述成功: {image_url[:50]}... -> {description[:30]}..."
                )
                return f"[图片: {description}]"
            else:
                logger.warning(f"图片描述为空: {image_url[:50]}...")
                return "[图片]"

        except Exception as e:
            logger.error(f"获取图片描述失败: {e}")
            return "[图片]"
