# server/app/avatar/actions/web/playwright_driver.py
import json
import logging
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Page,
    Browser,
    BrowserContext,
    Playwright,
)

logger = logging.getLogger(__name__)

# Cookie 持久化路径（放在 server/data/ 下）
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_STORAGE_STATE_PATH = _DATA_DIR / "browser_storage_state.json"


class PlaywrightDriver:
    """
    Singleton driver for Playwright browser automation (Async).
    Manages browser instance, context, and cookie persistence.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._initialized = True

    async def start(self, headless: bool = False):
        """Start the browser if not already running. Restores cookies if available."""
        if self._page and not self._page.is_closed():
            return

        logger.info("Starting Async Playwright browser...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)

        # 确保 data 目录存在
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        # 创建 context（带 storage state 恢复）
        context_opts = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "accept_downloads": True,
        }

        # 尝试从 storage state 恢复（包含 cookies + localStorage）
        if _STORAGE_STATE_PATH.exists():
            try:
                # 先验证 JSON 可读
                with open(_STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
                    json.load(f)
                context_opts["storage_state"] = str(_STORAGE_STATE_PATH)
                logger.info(f"Restoring browser state from {_STORAGE_STATE_PATH}")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Corrupted storage state file, starting fresh: {e}")
                _STORAGE_STATE_PATH.unlink(missing_ok=True)

        self._context = await self._browser.new_context(**context_opts)
        self._page = await self._context.new_page()

    async def get_page(self) -> Page:
        """Get the current active page. Starts browser if needed."""
        if self._page is None or self._page.is_closed():
            await self.start()
        return self._page

    async def get_context(self) -> BrowserContext:
        """Get the current browser context. Starts browser if needed."""
        if self._context is None:
            await self.start()
        return self._context

    async def save_cookies(self):
        """Persist cookies and storage state to disk."""
        if not self._context:
            return
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(_STORAGE_STATE_PATH))
            logger.info(f"Browser state saved to {_STORAGE_STATE_PATH}")
        except Exception as e:
            logger.warning(f"Failed to save browser state: {e}")

    async def save_cookies_after_navigation(self):
        """Lightweight save after navigation/interaction — fire-and-forget style."""
        if not self._context:
            return
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(_STORAGE_STATE_PATH))
            logger.debug("Browser state auto-saved after navigation")
        except Exception as e:
            # Non-critical, don't propagate
            logger.debug(f"Auto-save cookies skipped: {e}")

    async def clear_cookies(self):
        """Clear all cookies and storage state."""
        if self._context:
            await self._context.clear_cookies()
        _STORAGE_STATE_PATH.unlink(missing_ok=True)
        logger.info("Browser cookies and storage state cleared")

    async def close(self):
        """Save state, then close the browser and cleanup."""
        await self.save_cookies()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Playwright browser closed.")


# Global instance
global_playwright_driver = PlaywrightDriver()
