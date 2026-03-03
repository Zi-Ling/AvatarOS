from typing import Optional

from app.llm.base import BaseLLMClient
from app.llm.config import load_llm_config
from app.llm.logging import create_default_llm_logger
from app.llm.providers.ollama import OllamaClient
from app.llm.providers.openai import OpenAIClient
from app.llm.providers.deepseek import DeepSeekClient

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

