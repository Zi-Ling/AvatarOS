import logging
import threading
import platform
import pyautogui
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class DesktopController:
    """
    Central controller for all desktop interactions.
    Handles safety locks, coordinate normalization, and global state.
    Singleton pattern.
    """
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DesktopController, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._setup_safety()
        self._screen_size = pyautogui.size()
        logger.info(f"DesktopController initialized. Screen: {self._screen_size}")

    def _setup_safety(self):
        """Configure PyAutoGUI safety features."""
        # Fail-safe: moving mouse to corner will throw FailSafeException
        pyautogui.FAILSAFE = True 
        # Default pause between actions (can be overridden by drivers)
        pyautogui.PAUSE = 0.1

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Return current screen (width, height)."""
        return self._screen_size

    def normalize_coordinates(self, x: int, y: int) -> Tuple[int, int]:
        """
        Validate and normalize coordinates.
        Future expansion: Handle HiDPI scaling here if needed.
        """
        w, h = self.screen_size
        # Clamp coordinates to screen bounds
        safe_x = max(0, min(x, w - 1))
        safe_y = max(0, min(y, h - 1))
        return safe_x, safe_y

    def acquire_lock(self):
        """
        Acquire the global GUI lock.
        Use this before starting a sequence of mouse/keyboard actions.
        """
        return self._lock

global_desktop_controller = DesktopController()

