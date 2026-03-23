from typing import Optional

from app.llm.base import BaseLLMClient
from app.llm.config import load_llm_config
from app.llm.logging import create_default_llm_logger
from app.llm.providers.ollama import OllamaClient
from app.llm.providers.openai import OpenAIClient
from app.llm.providers.deepseek import DeepSeekClient
from app.llm.types import LLMConfig

def create_llm_client(config=None, logger=None) -> BaseLLMClient:
    """
    Factory to create LLM client based on configuration.
    """
    if config is None:
        config = load_llm_config()
    
    # Default Logger if not provided
    if logger is None:
        logger = create_default_llm_logger(source="llm_factory")
    
    if config.provider == "ollama":
        return OllamaClient(config, logger)
    elif config.provider == "openai":
        return OpenAIClient(config, logger)
    elif config.provider == "deepseek":
        return DeepSeekClient(config, logger)
    else:
        raise ValueError(f"Unsupported LLM provider: {config.provider}")


def create_vision_llm_client(logger=None) -> BaseLLMClient:
    """创建 vision 专用 LLM client。

    优先使用 VISION_LLM_* 环境变量配置；
    如果未配置，fallback 到主 LLM client（调用时若不支持 vision 会抛错）。
    """
    from app.core.config import config as app_config
    import os

    # 检查是否配了 vision 专用 provider
    vision_base_url = app_config.vision_llm_base_url
    vision_model = app_config.vision_llm_model

    if not vision_base_url or not vision_model:
        # 没配 vision 专用，fallback 到主 LLM
        return create_llm_client(logger=logger)

    # 推断 provider
    provider = app_config.vision_llm_provider
    if not provider:
        if "deepseek" in vision_base_url:
            provider = "deepseek"
        elif "localhost" in vision_base_url or "11434" in vision_base_url:
            provider = "ollama"
        else:
            provider = "openai"

    vision_config = LLMConfig(
        provider=provider,
        model=vision_model,
        base_url=vision_base_url,
        api_key=app_config.vision_llm_api_key or app_config.llm_api_key,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        timeout=int(os.getenv("LLM_TIMEOUT", "120")),
    )

    if logger is None:
        logger = create_default_llm_logger(source="vision_llm_factory")

    return create_llm_client(config=vision_config, logger=logger)
