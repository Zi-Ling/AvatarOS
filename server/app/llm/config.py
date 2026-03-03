import os
from typing import Optional

from app.llm.types import LLMConfig


def load_llm_config() -> LLMConfig:
    """
    Load LLM configuration from app.config (single source of truth).
    Provider is inferred from base_url unless LLM_PROVIDER env is set.
    """
    from app.core.config import config as app_config

    model = app_config.llm_model
    base_url = app_config.llm_base_url
    api_key = app_config.llm_api_key

    # Infer provider from base_url
    provider = os.getenv("LLM_PROVIDER")
    if not provider:
        if "deepseek" in base_url:
            provider = "deepseek"
        elif "openai" in base_url:
            provider = "openai"
        elif "localhost" in base_url or "11434" in base_url:
            provider = "ollama"
        else:
            provider = "openai"  # Default to OpenAI-compatible

    return LLMConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        timeout=int(os.getenv("LLM_TIMEOUT", "120")),
    )
