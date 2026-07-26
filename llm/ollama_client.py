"""
封装 Ollama 的 HTTP API，提供同步/异步生成和流式输出。
支持配置模型、温度、最大 token 等参数。
"""

import time
from typing import Optional

from loguru import logger
from ollama import Client, AsyncClient


class OllamaLLMClient:
    def __init__(
            self,
            model: str = "qwen2.5-coder:1.5b",
            base_url: str = "http://localhost:11434",
            temperature: float = 0.7,
            max_tokens: int = 2048,
    ):
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client = Client(host=base_url)
        self.async_client = AsyncClient(host=base_url)

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """同步生成，返回模型输出的文本"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            start_time = time.time()
            response = self.client.chat(model=self.model, messages=messages)
            elapsed = time.time() - start_time
            content = response.get("message", {}).get("content", "")
            logger.info(f"Generation completed in {elapsed:.2f}s, tokens: {len(content)}")
            return content
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return f"[ERROR] Failed to generate: {e}"

    async def async_generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """异步生成，用于不阻塞事件循环的场景"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        try:
            response = await self.async_client.chat(model=self.model, messages=messages)
            return response.get("message", {}).get("content", "")
        except Exception as e:
            logger.error(f"Async generation failed: {e}")
            return f"[ERROR] Failed to generate: {e}"

    def generate_stream(self, prompt: str):
        """流式生成，适用于逐步输出"""
        try:
            stream = self.client.chat(model=self.model, messages=[
                {"role": "user", "content": prompt}
            ], stream=True)
            for chunk in stream:
                if chunk.get("message", {}).get("content"):
                    yield chunk["message"]["content"]
        except Exception as e:
            logger.error(f"Stream generation failed: {e}")
            yield f"[ERROR] {e}"


# 全局单例（无状态，可共享）
_default_client = None


def get_llm_client() -> OllamaLLMClient:
    global _default_client
    if _default_client is None:
        _default_client = OllamaLLMClient()
    return _default_client
