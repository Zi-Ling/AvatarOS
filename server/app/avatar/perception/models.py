# server/app/avatar/perception/models.py
from pydantic import BaseModel, Field
from typing import List, Optional, Tuple, Dict, Any, Union
from enum import Enum

class PerceptionSource(str, Enum):
    DRIVER = "driver"
    UIA = "uia"
    VISION = "vision"

class UIElement(BaseModel):
    """
    Unified representation of a UI element.
    Whether from DOM, UIA tree, or Vision, it converts to this structure.
    """
    id: str = Field(..., description="Unique ID for this session (e.g. 'uia-123' or 'vis-456')")
    name: str = Field("", description="Text content, label, or accessible name")
    role: str = Field("unknown", description="Control type: Button, Edit, Window, MenuItem, etc.")
    
    # Bounding Box: (left, top, width, height)
    bbox: Tuple[int, int, int, int] = Field(..., description="(left, top, width, height)")
    
    # Center point: (x, y) - derived or explicit
    center: Tuple[int, int] = Field(..., description="(x, y) center point for clicking")
    
    source: PerceptionSource
    confidence: float = Field(1.0, description="Confidence score (1.0 for API/UIA, <1.0 for Vision)")
    
    # Raw metadata for debugging or backend-specific actions (e.g. automationId, hwnd)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Hierarchical structure (optional)
    children: List["UIElement"] = Field(default_factory=list)

    def to_prompt_format(self) -> str:
        """Convert to a short string for LLM prompt."""
        return f"[{self.role}] '{self.name}' id={self.id} at ({self.center[0]}, {self.center[1]})"

class ScreenModel(BaseModel):
    """
    The complete state of the screen at a moment in time.
    """
    width: int
    height: int
    
    # The screenshot itself (base64) - optional to save memory if not needed
    screenshot_base64: Optional[str] = None
    
    # Flattened list of interactable elements
    elements: List[UIElement] = Field(default_factory=list)
    
    # Which window is currently active
    active_window_title: Optional[str] = None
    active_window_bbox: Optional[Tuple[int, int, int, int]] = None

