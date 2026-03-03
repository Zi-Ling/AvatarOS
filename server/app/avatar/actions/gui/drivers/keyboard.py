import logging
import pyautogui
import pyperclip
import platform
import time
from typing import List, Union
from ..controller import global_desktop_controller

logger = logging.getLogger(__name__)

class KeyboardDriver:
    """
    Low-level keyboard interaction driver.
    Handles text input and hotkeys.
    """

    def __init__(self):
        self.controller = global_desktop_controller

    def type_text(self, text: str, interval: float = 0.05):
        """
        Type text. 
        Smart fallback: if text contains non-ASCII (e.g. Chinese), use clipboard paste.
        """
        with self.controller.acquire_lock():
            if self._is_ascii(text):
                pyautogui.write(text, interval=interval)
            else:
                self._paste_text(text)
            logger.debug(f"Typed text: {text[:20]}...")

    def press_keys(self, keys: List[str], interval: float = 0.1):
        """Press a sequence of keys."""
        with self.controller.acquire_lock():
            pyautogui.press(keys, interval=interval)
            logger.debug(f"Pressed keys: {keys}")

    def hotkey(self, *args):
        """Execute a hotkey combination (e.g. 'ctrl', 'c')."""
        with self.controller.acquire_lock():
            pyautogui.hotkey(*args)
            logger.debug(f"Hotkey: {args}")

    def _is_ascii(self, text: str) -> bool:
        try:
            text.encode('ascii')
            return True
        except UnicodeEncodeError:
            return False

    def _paste_text(self, text: str):
        """
        Workaround for non-ASCII characters:
        1. Copy text to clipboard.
        2. Simulate Ctrl+V (or Cmd+V on Mac).
        """
        original_clipboard = pyperclip.paste()
        try:
            pyperclip.copy(text)
            # Small delay to ensure clipboard is updated
            time.sleep(0.1) 
            
            cmd_key = 'command' if platform.system() == 'Darwin' else 'ctrl'
            pyautogui.hotkey(cmd_key, 'v')
            time.sleep(0.1) 
        finally:
            # Ideally restore clipboard, but might interfere if paste is slow.
            # For now, leave the pasted text in clipboard to be safe.
            pass

