# app/api/settings.py
"""
设置 API — LLM 配置 + Agent 配置 + 连接测试
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.config import config
from app.core.user_config import get_user_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ── 模型 ──────────────────────────────────────────────────────────────────────

class LLMConfig(BaseModel):
    provider: str = "deepseek"
    model: str
    base_url: str
    api_key: str
    temperature: float = 0.7
    max_tokens: int = 4096


class AgentConfig(BaseModel):
    max_replan_attempts: int = 2
    enable_self_correction: bool = True
    enable_context_memory: bool = True
    enable_verbose_logging: bool = False
    enable_plan_cache: bool = True
    enable_parallel_execution: bool = False


# ── LLM ──────────────────────────────────────────────────────────────────────

@router.get("/llm")
async def get_llm_config():
    """读取当前 LLM 配置（从 .env / config 实例）"""
    return {
        "provider": _infer_provider(config.llm_base_url),
        "model": config.llm_model,
        "base_url": config.llm_base_url,
        "api_key": config.llm_api_key,
        "temperature": 0.7,
        "max_tokens": 4096,
    }


@router.put("/llm")
async def save_llm_config(body: LLMConfig):
    """保存 LLM 配置到 .env 文件，并热更新 config 实例"""
    try:
        _write_env_vars({
            "LLM_MODEL": body.model,
            "LLM_BASE_URL": body.base_url,
            "LLM_API_KEY": body.api_key,
        })
        # 热更新
        config.llm_model = body.model
        config.llm_base_url = body.base_url
        config.llm_api_key = body.api_key
        return {"success": True}
    except Exception as e:
        logger.error(f"Save LLM config failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-llm")
async def test_llm_connection(body: LLMConfig):
    """测试 LLM 连接"""
    try:
        from openai import AsyncOpenAI
        api_key = body.api_key or "ollama"  # Ollama 需要占位 key
        client = AsyncOpenAI(api_key=api_key, base_url=body.base_url)
        await client.chat.completions.create(
            model=body.model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return {"success": True, "message": f"连接成功：{body.model}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ── Agent ─────────────────────────────────────────────────────────────────────

@router.get("/agent")
async def get_agent_config():
    """读取 Agent 行为配置（从 config.yaml）"""
    uc = get_user_config()
    agent = uc.get("agent") or {}
    return {
        "max_replan_attempts": agent.get("max_replan_attempts", config.max_replan_attempts),
        "enable_self_correction": agent.get("enable_self_correction", True),
        "enable_context_memory": agent.get("enable_context_memory", True),
        "enable_verbose_logging": agent.get("enable_verbose_logging", False),
        "enable_plan_cache": agent.get("enable_plan_cache", True),
        "enable_parallel_execution": agent.get("enable_parallel_execution", False),
    }


@router.put("/agent")
async def save_agent_config(body: AgentConfig):
    """保存 Agent 配置到 config.yaml，并热更新 config 实例"""
    try:
        uc = get_user_config()
        uc.set("agent.max_replan_attempts", body.max_replan_attempts)
        uc.set("agent.enable_self_correction", body.enable_self_correction)
        uc.set("agent.enable_context_memory", body.enable_context_memory)
        uc.set("agent.enable_verbose_logging", body.enable_verbose_logging)
        uc.set("agent.enable_plan_cache", body.enable_plan_cache)
        uc.set("agent.enable_parallel_execution", body.enable_parallel_execution)
        # 热更新 config 实例
        config.max_replan_attempts = body.max_replan_attempts
        return {"success": True}
    except Exception as e:
        logger.error(f"Save agent config failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _infer_provider(base_url: str) -> str:
    url = base_url.lower()
    if "ollama" in url or "11434" in url:
        return "ollama"
    if "openai" in url:
        return "openai"
    if "deepseek" in url:
        return "deepseek"
    if "moonshot" in url:
        return "moonshot"
    if "dashscope" in url or "qwen" in url:
        return "qwen"
    if "bigmodel" in url or "glm" in url:
        return "glm"
    return "openai"


def _write_env_vars(updates: dict[str, str]) -> None:
    """读取 .env 文件，更新指定 key，写回"""
    from pathlib import Path
    env_path = Path(".env")
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    existing_keys = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f'{key}={updates[key]}')
            existing_keys.add(key)
        else:
            new_lines.append(line)

    # 追加不存在的 key
    for key, val in updates.items():
        if key not in existing_keys:
            new_lines.append(f'{key}={val}')

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
