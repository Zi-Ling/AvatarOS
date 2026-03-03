# server/app/avatar/perception/base.py
from abc import ABC, abstractmethod
from typing import List, Optional
from .models import UIElement, ScreenModel

class BasePerceptionBackend(ABC):
    """
    Abstract base class for all perception backends.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name (e.g. 'uia', 'vision')"""
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """
        Priority for fusion strategy.
        Higher number = Higher priority (more trusted).
        e.g. API Driver (30) > UIA (20) > Vision (10)
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend can run in the current environment."""
        pass

    @abstractmethod
    async def scan(self, target_window_title: Optional[str] = None) -> List[UIElement]:
        """
        Core method: Scan the screen/window and return a list of UI elements.
        """
        pass
