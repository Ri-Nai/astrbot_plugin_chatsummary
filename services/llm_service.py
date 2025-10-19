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
