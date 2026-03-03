import logging
import pyautogui
from typing import Tuple
from ..controller import global_desktop_controller

logger = logging.getLogger(__name__)

class MouseDriver:
    """
    Low-level mouse interaction driver.
    Delegates safety and locking to DesktopController.
    """
    
    def __init__(self):
        self.controller = global_desktop_controller

    def move_to(self, x: int, y: int, duration: float = 0.5):
        """Move mouse to specific coordinates with easing."""
        safe_x, safe_y = self.controller.normalize_coordinates(x, y)
        with self.controller.acquire_lock():
            # TODO: Implement human-like bezier curve movement in future
            pyautogui.moveTo(safe_x, safe_y, duration=duration, tween=pyautogui.easeInOutQuad)
            logger.debug(f"Mouse moved to ({safe_x}, {safe_y})")

    def click(self, button: str = 'left', clicks: int = 1, interval: float = 0.1):
        """Click current position."""
        with self.controller.acquire_lock():
            pyautogui.click(button=button, clicks=clicks, interval=interval)
            logger.debug(f"Mouse clicked {button} x{clicks}")

    def click_at(self, x: int, y: int, button: str = 'left', clicks: int = 1):
        """Move and click."""
        self.move_to(x, y)
        self.click(button, clicks)

    def drag_to(self, x: int, y: int, duration: float = 0.5, button: str = 'left'):
        """Drag from current position to target."""
        safe_x, safe_y = self.controller.normalize_coordinates(x, y)
        with self.controller.acquire_lock():
            pyautogui.dragTo(safe_x, safe_y, duration=duration, button=button)
            logger.debug(f"Mouse dragged to ({safe_x}, {safe_y})")

    def scroll(self, clicks: int):
        """Scroll wheel (positive=up, negative=down)."""
        with self.controller.acquire_lock():
            pyautogui.scroll(clicks)
            logger.debug(f"Mouse scrolled {clicks}")

    def position(self) -> Tuple[int, int]:
        """Get current mouse position."""
        return pyautogui.position()

