# server/app/avatar/perception/manager.py
import asyncio
import logging
from typing import List, Optional, Tuple
from .models import ScreenModel, UIElement, PerceptionSource
from .base import BasePerceptionBackend

logger = logging.getLogger(__name__)

# Priority Mapping for sorting elements
PRIORITY_MAP = {
    PerceptionSource.DRIVER: 30,
    PerceptionSource.UIA: 20,
    PerceptionSource.VISION: 10,
    # Fallback for unknown sources
    "unknown": 0 
}

class PerceptionManager:
    def __init__(self):
        self.backends: List[BasePerceptionBackend] = []

    def register_backend(self, backend: BasePerceptionBackend):
        self.backends.append(backend)
        # Sort backends by priority descending (High -> Low)
        self.backends.sort(key=lambda x: x.priority, reverse=True)
        logger.info(f"Registered perception backend: {backend.name} (priority={backend.priority})")

    async def perceive(self, target_window_title: Optional[str] = None) -> ScreenModel:
        """
        Execute the hybrid perception pipeline.
        """
        all_elements: List[UIElement] = []
        screenshot: Optional[str] = None
        width, height = 1920, 1080 # Default fallback

        # 1. Iterate through backends to gather raw data
        # We scan all backends because Vision might see things UIA misses (fill-in-the-blank)
        for backend in self.backends:
            if not backend.is_available():
                continue
            
            try:
                logger.debug(f"Scanning with backend: {backend.name}")
                elements = await backend.scan(target_window_title)
                
                if elements:
                    all_elements.extend(elements)
                    
                    # TODO: If this backend provides screen dimensions (e.g. from screenshot), update them
                    
            except Exception as e:
                logger.error(f"Backend {backend.name} scan failed: {e}")

        # 2. De-duplication & Fusion
        merged_elements = self._merge_elements(all_elements)

        return ScreenModel(
            width=width,
            height=height,
            screenshot_base64=screenshot,
            elements=merged_elements
        )

    def _merge_elements(self, elements: List[UIElement]) -> List[UIElement]:
        """
        Merge duplicate elements from different sources using IoU + Priority.
        """
        if not elements:
            return []

        # 1. Sort all elements by Source Priority (High -> Low)
        # This ensures that when we iterate, we see the "trusted" elements first.
        elements.sort(
            key=lambda x: PRIORITY_MAP.get(x.source, 0), 
            reverse=True
        )

        final_list: List[UIElement] = []

        for current in elements:
            is_duplicate = False
            
            # Check against already accepted elements
            for accepted in final_list:
                iou = self._calculate_iou(current.bbox, accepted.bbox)
                
                # Fusion Rule:
                # If IoU > 0.8 (80% overlap), we consider them the SAME element.
                # Since 'accepted' is already in the list, it has higher (or equal) priority.
                # So we discard 'current'.
                if iou > 0.8:
                    is_duplicate = True
                    # Optional: Merge metadata (e.g. if Vision saw a better name but UIA has better bbox)
                    # For now, strictly keep High Priority one.
                    break
            
            if not is_duplicate:
                final_list.append(current)
        
        return final_list

    def _calculate_iou(self, bbox1: Tuple[int, int, int, int], bbox2: Tuple[int, int, int, int]) -> float:
        """
        Calculate Intersection over Union (IoU) for two bounding boxes.
        bbox: (x, y, w, h)
        """
        x1_min, y1_min, w1, h1 = bbox1
        x1_max = x1_min + w1
        y1_max = y1_min + h1

        x2_min, y2_min, w2, h2 = bbox2
        x2_max = x2_min + w2
        y2_max = y2_min + h2

        # Calculate intersection
        inter_x_min = max(x1_min, x2_min)
        inter_y_min = max(y1_min, y2_min)
        inter_x_max = min(x1_max, x2_max)
        inter_y_max = min(y1_max, y2_max)

        inter_w = max(0, inter_x_max - inter_x_min)
        inter_h = max(0, inter_y_max - inter_y_min)

        intersection_area = inter_w * inter_h

        if intersection_area == 0:
            return 0.0

        # Calculate union
        area1 = w1 * h1
        area2 = w2 * h2
        union_area = area1 + area2 - intersection_area

        if union_area == 0:
            return 0.0

        return intersection_area / union_area
