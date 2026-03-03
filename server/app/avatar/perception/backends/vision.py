import logging
from typing import List, Optional
from ..base import BasePerceptionBackend
from ..models import UIElement, PerceptionSource

logger = logging.getLogger(__name__)

class VisionBackend(BasePerceptionBackend):
    """
    Visual Perception Backend (VLM-based).
    Uses screenshots + Vision LLM to detect UI elements.
    Acts as a fallback when Driver and UIA fail.
    """
    
    def __init__(self):
        # TODO: Initialize VLM client here (e.g. Qwen-VL, GPT-4o)
        pass

    @property
    def name(self) -> str:
        return "vision"

    @property
    def priority(self) -> int:
        return 10 # Lowest priority (Fallback)

    def is_available(self) -> bool:
        # Always available as long as we can take screenshots
        # TODO: Check if VLM service is reachable
        return True

    async def scan(self, target_window_title: Optional[str] = None) -> List[UIElement]:
        """
        1. Take screenshot
        2. Send to VLM
        3. Parse coordinates -> UIElement
        """
        # Placeholder implementation
        logger.debug("Vision backend scan triggered (Not implemented yet)")
        return [] 

