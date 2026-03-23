# server/app/services/browser/config.py
"""Browser Automation Executor 配置加载。"""
from __future__ import annotations

import os

from app.services.browser.models import BrowserAutomationConfig


def load_browser_config() -> BrowserAutomationConfig:
    """从环境变量加载配置，未设置则使用默认值。"""
    kwargs: dict = {}
    _int_env = {
        "BROWSER_MAX_SESSIONS": "max_concurrent_sessions",
        "BROWSER_MAX_PAGES": "max_pages_per_session",
        "BROWSER_IDLE_TIMEOUT": "session_idle_timeout_seconds",
        "BROWSER_NAV_TIMEOUT_MS": "default_navigation_timeout_ms",
        "BROWSER_ACTION_TIMEOUT_MS": "default_action_timeout_ms",
        "BROWSER_VIEWPORT_W": "viewport_width",
        "BROWSER_VIEWPORT_H": "viewport_height",
        "BROWSER_MAX_ARTIFACTS": "max_artifacts_per_session",
        "BROWSER_MAX_SCREENSHOT_BYTES": "max_screenshot_size_bytes",
        "BROWSER_MAX_DOWNLOAD_BYTES": "max_download_size_bytes",
        "BROWSER_DOWNLOAD_QUOTA_BYTES": "download_dir_quota_bytes",
        "BROWSER_RECORDING_RETENTION": "recording_retention_count",
    }
    for env_key, field_name in _int_env.items():
        val = os.environ.get(env_key)
        if val is not None:
            kwargs[field_name] = int(val)

    headless_val = os.environ.get("BROWSER_HEADLESS")
    if headless_val is not None:
        kwargs["headless"] = headless_val.lower() not in ("0", "false", "no")

    return BrowserAutomationConfig(**kwargs)
