import logging
import pyautogui
import base64
import io
from typing import Tuple, Optional, Dict, Any
from PIL import Image
from ..controller import global_desktop_controller

logger = logging.getLogger(__name__)

class ScreenDriver:
    """
    Low-level screen interaction driver.
    Handles screenshots and screen info.
    """

    def __init__(self):
        self.controller = global_desktop_controller

    def get_size(self) -> Tuple[int, int]:
        """Get screen resolution."""
        return self.controller.screen_size

    def capture(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """
        Capture screenshot.
        region: (left, top, width, height)
        """
        with self.controller.acquire_lock():
            # PyAutoGUI screenshot() returns a PIL Image
            return pyautogui.screenshot(region=region)

    def capture_base64(self, region: Optional[Tuple[int, int, int, int]] = None) -> str:
        """Capture screenshot and return as Base64 string (PNG)."""
        img = self.capture(region)
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return img_str

    def get_screen_info(self) -> Dict[str, Any]:
        """Return structured screen info."""
        w, h = self.get_size()
        x, y = pyautogui.position()
        return {
            "width": w,
            "height": h,
            "cursor_x": x,
            "cursor_y": y
        }

