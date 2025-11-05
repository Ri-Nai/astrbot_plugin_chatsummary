# /astrbot_plugin_chatsummary/services/llm_service.py

import asyncio
from typing import Dict
from astrbot.api import logger


class LLMService:
    """LLM 服务：负责与大语言模型交互"""

    def __init__(
        self,
        context,
        enable_image_description: bool = True,
        image_description_cache_size: int = 100,
        max_concurrent_image_requests: int = 3,
        image_request_delay: float = 0.5,
    ):
        self.context = context
        self.enable_image_description = enable_image_description
        self.max_concurrent_image_requests = max_concurrent_image_requests
        self.image_request_delay = image_request_delay
        
        # 图片描述缓存 {image_url: description}
        self._image_cache: Dict[str, str] = {}
        self._cache_size = image_description_cache_size
        
        # 并发控制信号量
        self._image_semaphore = asyncio.Semaphore(max_concurrent_image_requests)
        
        # 统计信息
        self._cache_hits = 0
        self._cache_misses = 0
        self._failed_requests = 0

    async def get_summary(
        self,
        formatted_chat: str,
        prompt: str,
        max_retries: int = 2,
        retry_delay: float = 2.0,
    ) -> str:
        """
        调用LLM获取总结（带重试机制）

        Args:
            formatted_chat: 格式化后的聊天内容
            prompt: 使用的提示词
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）

        Returns:
            LLM生成的总结文本

        Raises:
            Exception: LLM调用失败时抛出异常
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    # 指数退避：第一次重试等待 retry_delay，第二次等待 retry_delay * 2
                    wait_time = retry_delay * (2 ** (attempt - 1))
                    logger.info(f"LLM调用重试 {attempt}/{max_retries}，等待 {wait_time} 秒...")
                    await asyncio.sleep(wait_time)
                
                llm_response = await self.context.get_using_provider().text_chat(
                    prompt=prompt,
                    contexts=[{"role": "user", "content": formatted_chat}],
                )
                
                # 调用成功
                if attempt > 0:
                    logger.info(f"LLM调用在第 {attempt} 次重试后成功")
                
                return llm_response.completion_text
                
            except Exception as e:
                error_msg = str(e)
                last_error = e
                
                # 检查是否是 429 错误
                if "429" in error_msg or "Request limit exceeded" in error_msg or "rate limit" in error_msg.lower():
                    logger.warning(f"LLM调用遇到请求限制 (429)：{error_msg}")
                    # 如果还有重试机会，继续；否则退出循环
                    if attempt < max_retries:
                        continue
                    else:
                        logger.error("LLM调用已达到最大重试次数，仍然遇到请求限制")
                        raise Exception("请求过于频繁，请稍后再试。建议降低图片描述功能的并发数或增加延迟。") from e
                else:
                    # 非 429 错误，直接抛出
                    logger.error(f"调用LLM服务失败: {e}")
                    raise
        
        # 所有重试都失败
        if last_error:
            raise last_error

    def _manage_cache(self, url: str, description: str):
        """管理缓存大小，使用 LRU 策略"""
        try:
            self._image_cache[url] = description
            
            # 如果缓存超过限制，删除最旧的条目
            if len(self._image_cache) > self._cache_size:
                # 删除第一个键（最旧的）
                first_key = next(iter(self._image_cache))
                del self._image_cache[first_key]
        except Exception as e:
            # 缓存操作失败不应影响主流程
            logger.warning(f"缓存操作失败: {e}")
    
    async def get_image_description(
        self,
        image_url: str,
        prompt: str = "请描述这张图片的内容（不超过50字），并总结出该图片的主要信息。",
    ) -> str:
        """
        调用支持视觉的LLM获取图片描述（带缓存和限流）
        
        注意：此方法保证永远不会抛出异常，失败时总是返回 "[图片]"

        Args:
            image_url: 图片URL
            prompt: 描述提示词

        Returns:
            图片描述文本，失败时返回 "[图片]"
        """
        try:
            # 检查是否启用图片描述
            if not self.enable_image_description:
                return "[图片]"
            
            # 检查缓存
            if image_url in self._image_cache:
                self._cache_hits += 1
                logger.debug(f"图片描述命中缓存: {image_url[:50]}...")
                return self._image_cache[image_url]
            
            self._cache_misses += 1
            
            # 使用信号量控制并发
            async with self._image_semaphore:
                # 添加请求延迟，避免过于频繁
                if self.image_request_delay > 0:
                    await asyncio.sleep(self.image_request_delay)
                
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
                        result = "[图片]"
                        self._manage_cache(image_url, result)
                        return result

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
                        result = f"[图片: {description}]"
                    else:
                        logger.warning(f"图片描述为空: {image_url[:50]}...")
                        result = "[图片]"
                    
                    # 缓存结果
                    self._manage_cache(image_url, result)
                    return result

                except Exception as e:
                    self._failed_requests += 1
                    error_msg = str(e)
                    
                    # 检查是否是 429 错误
                    if "429" in error_msg or "Request limit exceeded" in error_msg:
                        logger.warning(f"图片描述请求限制: {error_msg}，已跳过该图片")
                    else:
                        logger.error(f"获取图片描述失败: {e}")
                    
                    # 缓存失败结果，避免重复请求
                    result = "[图片]"
                    self._manage_cache(image_url, result)
                    return result
        except Exception as e:
            # 最外层保护：确保任何未预期的异常都不会传播
            logger.error(f"图片描述出现未预期的错误（已降级）: {e}")
            self._failed_requests += 1
            return "[图片]"
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计信息"""
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "cache_size": len(self._image_cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "failed_requests": self._failed_requests,
            "hit_rate": f"{hit_rate:.2f}%",
        }
