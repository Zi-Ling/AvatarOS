# server/app/avatar/perception/backends/uia.py
import asyncio
import logging
from typing import List, Optional
from ..base import BasePerceptionBackend
from ..models import UIElement, PerceptionSource

logger = logging.getLogger(__name__)

class UIABackend(BasePerceptionBackend):
    """
    Windows UI Automation Backend.
    Uses 'uiautomation' library to traverse the accessibility tree.
    """
    
    def __init__(self):
        self._available = False
        try:
            import uiautomation as auto
            self._uia = auto
            self._available = True
        except ImportError:
            logger.warning("uiautomation not installed. UIABackend disabled.")

    @property
    def name(self) -> str:
        return "uia"

    @property
    def priority(self) -> int:
        return 20 # Higher than Vision(10), lower than API(30)

    def is_available(self) -> bool:
        return self._available

    async def scan(self, target_window_title: Optional[str] = None) -> List[UIElement]:
        """
        Scans the active window (or desktop) for interactive elements.
        """
        if not self._available:
            return []

        return await asyncio.to_thread(self._scan_sync, target_window_title)

    def _scan_sync(self, target_window_title: Optional[str] = None) -> List[UIElement]:
        # Ensure COM is initialized for this thread
        if not self._available:
            return []
            
        try:
            with self._uia.UIAutomationInitializerInThread():
                return self._scan_impl(target_window_title)
        except Exception as e:
            # Sometimes it might fail if already initialized or other COM issues
            logger.warning(f"UIA scan failed with context manager, trying direct: {e}")
            try:
                 return self._scan_impl(target_window_title)
            except Exception as inner_e:
                 logger.error(f"UIA scan completely failed: {inner_e}")
                 return []

    def _scan_impl(self, target_window_title: Optional[str] = None) -> List[UIElement]:
        """
        The actual implementation of the scan logic, decoupled from COM init.
        """
        elements = []
        auto = self._uia
        
        # 1. Find target window
        if target_window_title:
            # Fuzzy search for window
            window = auto.WindowControl(searchDepth=1, Name=target_window_title, RegexName=target_window_title)
            if not window.Exists(0.5):
                # Try active window as fallback
                window = auto.GetForegroundControl().GetTopLevelControl()
        else:
            window = auto.GetForegroundControl().GetTopLevelControl()

        if not window:
            return []

        # 2. Traverse children (BFS/DFS)
        # We want controls that are interactable: Button, Edit, MenuItem, List, etc.
        
        # Queue for BFS
        queue = [window]
        visited = set()
        count = 0
        max_elements = 100 # Limit to avoid token explosion

        while queue and count < max_elements:
            ctrl = queue.pop(0)
            
            # Get properties
            try:
                rect = ctrl.BoundingRectangle
                name = ctrl.Name
                ctrl_type = ctrl.ControlTypeName
                
                # Filter: Must have a name and be visible
                if not rect or rect.width == 0 or rect.height == 0:
                    pass
                elif name and not ctrl.IsOffscreen:
                    el = UIElement(
                        id=f"uia-{count}",
                        name=name,
                        role=ctrl_type,
                        bbox=(rect.left, rect.top, rect.width, rect.height),
                        center=(rect.left + rect.width // 2, rect.top + rect.height // 2),
                        source=PerceptionSource.UIA,
                        metadata={"automationId": ctrl.AutomationId, "handle": ctrl.NativeWindowHandle}
                    )
                    # DEBUG LOG
                    logger.debug(f"Found: {name} ({ctrl_type}) at {el.center}")
                    elements.append(el)
                    count += 1
            except Exception:
                # Control might be invalid or gone
                continue

            # Add children to queue
            # Use GetChildren() which returns a list of controls
            try:
                children = ctrl.GetChildren()
                for child in children:
                    # Note: uiautomation objects are not hashable by default, so 'visited' set might be tricky.
                    # But tree traversal usually doesn't have cycles unless we go up.
                    # We can use RuntimeId or just rely on tree structure.
                    queue.append(child)
            except Exception:
                pass

        return elements
