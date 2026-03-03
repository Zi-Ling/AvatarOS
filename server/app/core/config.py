# app/config.py
"""
配置管理：统一管理后端配置（基于 Pydantic Settings）
"""
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
import logging


class Config(BaseSettings):
    """应用配置 — 自动从 .env 文件和环境变量加载"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM 配置
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""

    # Avatar 工作目录
    avatar_workspace: Path = Path("./workspace")

    # 服务器配置
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    # CORS 配置
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # 日志级别
    log_level: str = "INFO"

    # Whisper 语音识别配置
    whisper_model_path: Path = Path("./app/models/faster-whisper")
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"
    whisper_language: str = "zh"
    whisper_beam_size: int = 5
    whisper_vad_filter: bool = True

    # 临时文件目录
    temp_audio_dir: Path = Path("./workspace/.temp_audio")

    # Agent 自纠错配置
    max_replan_attempts: int = 2

    # Router 技能相关性阈值（旧配置，向后兼容）
    skill_relevance_threshold: float = 0.50

    # Router 配置（技能相关性判断）
    router_domain_boost: float = 0.15
    router_simple_threshold: float = 0.38
    router_medium_threshold: float = 0.32
    router_complex_threshold: float = 0.28
    router_min_exec_threshold: float = 0.2

    # 路由决策配置
    router_enable_complex_detection: bool = True
    router_complex_force_planner: bool = True

    # Embedding 模型配置
    embedding_model_path: Path = Path("./app/models/embeddings/multilingual/bge-m3/onnx")
    embedding_model_name: str = "bge-m3"
    embedding_use_local: bool = True

    @model_validator(mode="after")
    def _ensure_directories(self) -> "Config":
        """确保工作目录和临时目录存在"""
        self.avatar_workspace.mkdir(parents=True, exist_ok=True)
        self.temp_audio_dir.mkdir(parents=True, exist_ok=True)
        if not self.llm_api_key:
            logger = logging.getLogger(__name__)
            logger.warning("LLM_API_KEY 未设置，请在 .env 文件或环境变量中配置")
        return self


# 全局配置实例
config = Config()
