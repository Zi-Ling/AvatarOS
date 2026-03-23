# app/services/computer/uia_service.py
"""UIAutomationService — Windows UIA COM API 封装."""

from __future__ import annotations

import logging
from typing import Optional

from .models import UIAElement
from .desktop_models import ControlSnapshot

logger = logging.getLogger(__name__)


class UIAutomationService:
    """Windows UIAutomation COM API 封装."""

    async def get_control_tree(
        self,
        window_title: Optional[str] = None,
        max_depth: int = 5,
    ) -> list[UIAElement]:
        """获取指定窗口（或前台窗口）的控件树."""
        try:
            import uiautomation as auto  # type: ignore[import-untyped]

            if window_title:
                root = auto.WindowControl(Name=window_title, searchDepth=1)
            else:
                root = auto.GetForegroundControl()

            if not root or not root.Exists(maxSearchSeconds=2):
                return []

            elements: list[UIAElement] = []
            self._walk_tree(root, elements, max_depth, 0)
            return elements
        except ImportError:
            logger.warning("uiautomation package not installed")
            return []
        except Exception as e:
            logger.warning("UIA COM error: %s", e)
            return []

    async def find_element(
        self,
        name: Optional[str] = None,
        control_type: Optional[str] = None,
        automation_id: Optional[str] = None,
        window_title: Optional[str] = None,
    ) -> Optional[UIAElement]:
        """按属性查找单个控件."""
        try:
            import uiautomation as auto  # type: ignore[import-untyped]

            if window_title:
                root = auto.WindowControl(Name=window_title, searchDepth=1)
            else:
                root = auto.GetForegroundControl()

            if not root or not root.Exists(maxSearchSeconds=2):
                return None

            kwargs: dict = {}
            if name:
                kwargs["Name"] = name
            if control_type:
                kwargs["ControlType"] = getattr(
                    auto.ControlType, control_type, None
                )
            if automation_id:
                kwargs["AutomationId"] = automation_id

            if not kwargs:
                return None

            ctrl = root.Control(searchDepth=5, **kwargs)
            if ctrl and ctrl.Exists(maxSearchSeconds=1):
                return self._to_element(ctrl)
            return None
        except ImportError:
            return None
        except Exception as e:
            logger.warning("UIA find_element error: %s", e)
            return None

    async def get_focused_element(self) -> Optional[UIAElement]:
        """获取当前焦点控件."""
        try:
            import uiautomation as auto  # type: ignore[import-untyped]

            ctrl = auto.GetFocusedControl()
            if ctrl:
                return self._to_element(ctrl)
            return None
        except ImportError:
            return None
        except Exception as e:
            logger.warning("UIA get_focused error: %s", e)
            return None

    # ── enhanced: ControlSnapshot API ─────────────────────────────────

    async def get_control_snapshot(
        self,
        name: Optional[str] = None,
        control_type: Optional[str] = None,
        automation_id: Optional[str] = None,
        class_name: Optional[str] = None,
        window_title: Optional[str] = None,
    ) -> Optional[ControlSnapshot]:
        """按属性查找控件并返回丰富的 ControlSnapshot."""
        try:
            import uiautomation as auto  # type: ignore[import-untyped]

            if window_title:
                root = auto.WindowControl(Name=window_title, searchDepth=1)
            else:
                root = auto.GetForegroundControl()

            if not root or not root.Exists(maxSearchSeconds=2):
                return None

            kwargs: dict = {}
            if name:
                kwargs["Name"] = name
            if control_type:
                kwargs["ControlType"] = getattr(
                    auto.ControlType, control_type, None
                )
            if automation_id:
                kwargs["AutomationId"] = automation_id
            if class_name:
                kwargs["ClassName"] = class_name

            if not kwargs:
                return self._to_snapshot(root)

            ctrl = root.Control(searchDepth=8, **kwargs)
            if ctrl and ctrl.Exists(maxSearchSeconds=1):
                parent_name = getattr(root, "Name", "") or ""
                return self._to_snapshot(ctrl, parent_name=parent_name)
            return None
        except ImportError:
            return None
        except Exception as e:
            logger.warning("UIA get_control_snapshot error: %s", e)
            return None

    async def get_focused_snapshot(self) -> Optional[ControlSnapshot]:
        """获取当前焦点控件的 ControlSnapshot."""
        try:
            import uiautomation as auto  # type: ignore[import-untyped]

            ctrl = auto.GetFocusedControl()
            if ctrl:
                return self._to_snapshot(ctrl)
            return None
        except ImportError:
            return None
        except Exception as e:
            logger.warning("UIA get_focused_snapshot error: %s", e)
            return None

    async def click_control(
        self,
        name: Optional[str] = None,
        automation_id: Optional[str] = None,
        control_type: Optional[str] = None,
        window_title: Optional[str] = None,
    ) -> bool:
        """通过 UIA 语义定位并点击控件（不依赖坐标）."""
        try:
            import uiautomation as auto  # type: ignore[import-untyped]

            if window_title:
                root = auto.WindowControl(Name=window_title, searchDepth=1)
            else:
                root = auto.GetForegroundControl()

            if not root or not root.Exists(maxSearchSeconds=2):
                return False

            kwargs: dict = {}
            if name:
                kwargs["Name"] = name
            if automation_id:
                kwargs["AutomationId"] = automation_id
            if control_type:
                kwargs["ControlType"] = getattr(
                    auto.ControlType, control_type, None
                )

            ctrl = root.Control(searchDepth=8, **kwargs)
            if ctrl and ctrl.Exists(maxSearchSeconds=1):
                # 优先用 InvokePattern，其次 Click
                try:
                    invoke = ctrl.GetInvokePattern()
                    if invoke:
                        invoke.Invoke()
                        return True
                except Exception:
                    pass
                ctrl.Click()
                return True
            return False
        except ImportError:
            return False
        except Exception as e:
            logger.warning("UIA click_control error: %s", e)
            return False

    async def set_control_value(
        self,
        value: str,
        name: Optional[str] = None,
        automation_id: Optional[str] = None,
        window_title: Optional[str] = None,
    ) -> bool:
        """通过 UIA ValuePattern 设置控件值（不依赖键盘输入）."""
        try:
            import uiautomation as auto  # type: ignore[import-untyped]

            if window_title:
                root = auto.WindowControl(Name=window_title, searchDepth=1)
            else:
                root = auto.GetForegroundControl()

            if not root or not root.Exists(maxSearchSeconds=2):
                return False

            kwargs: dict = {}
            if name:
                kwargs["Name"] = name
            if automation_id:
                kwargs["AutomationId"] = automation_id

            ctrl = root.Control(searchDepth=8, **kwargs)
            if ctrl and ctrl.Exists(maxSearchSeconds=1):
                try:
                    vp = ctrl.GetValuePattern()
                    if vp:
                        vp.SetValue(value)
                        return True
                except Exception:
                    pass
                # fallback: 点击 + 清空 + 粘贴
                ctrl.Click()
                import time as _time
                _time.sleep(0.1)
                import pyautogui
                pyautogui.hotkey("ctrl", "a")
                _time.sleep(0.05)
                import pyperclip
                pyperclip.copy(value)
                pyautogui.hotkey("ctrl", "v")
                _time.sleep(0.1)
                return True
            return False
        except ImportError:
            return False
        except Exception as e:
            logger.warning("UIA set_control_value error: %s", e)
            return False

    # ── private helpers ───────────────────────────────────────────────

    def _walk_tree(
        self,
        control: object,
        elements: list[UIAElement],
        max_depth: int,
        current_depth: int,
    ) -> None:
        if current_depth > max_depth:
            return
        elem = self._to_element(control)
        if elem:
            elements.append(elem)
        try:
            children = getattr(control, "GetChildren", lambda: [])()
            for child in children:
                self._walk_tree(child, elements, max_depth, current_depth + 1)
        except Exception:
            pass

    @staticmethod
    def _extract_bbox(control: object) -> Optional[tuple[int, int, int, int]]:
        """从 UIA 控件提取 bounding rect."""
        rect = getattr(control, "BoundingRectangle", None)
        if not rect:
            return None
        return (
            getattr(rect, "left", 0),
            getattr(rect, "top", 0),
            getattr(rect, "width", lambda: 0)()
            if callable(getattr(rect, "width", None))
            else getattr(rect, "right", 0) - getattr(rect, "left", 0),
            getattr(rect, "height", lambda: 0)()
            if callable(getattr(rect, "height", None))
            else getattr(rect, "bottom", 0) - getattr(rect, "top", 0),
        )

    @staticmethod
    def _to_element(control: object) -> Optional[UIAElement]:
        try:
            bbox = UIAutomationService._extract_bbox(control)

            children = getattr(control, "GetChildren", lambda: [])()
            return UIAElement(
                name=getattr(control, "Name", "") or "",
                control_type=str(getattr(control, "ControlTypeName", "")),
                bounding_rect=bbox,
                is_enabled=bool(getattr(control, "IsEnabled", True)),
                is_visible=bool(getattr(control, "IsOffscreen", False)) is False,
                value=getattr(control, "GetValuePattern", lambda: None)(),
                automation_id=getattr(control, "AutomationId", "") or "",
                children_count=len(children) if children else 0,
            )
        except Exception:
            return None

    @staticmethod
    def _to_snapshot(
        control: object, depth: int = 0, parent_name: str = ""
    ) -> Optional[ControlSnapshot]:
        """转换为丰富的 ControlSnapshot."""
        try:
            bbox = UIAutomationService._extract_bbox(control)
            children = getattr(control, "GetChildren", lambda: [])()

            # 提取 ValuePattern
            value = None
            try:
                vp = getattr(control, "GetValuePattern", lambda: None)()
                if vp and hasattr(vp, "Value"):
                    value = str(vp.Value)
                elif isinstance(vp, str):
                    value = vp
            except Exception:
                pass

            # 提取 TextPattern
            text_content = None
            try:
                tp = getattr(control, "GetTextPattern", lambda: None)()
                if tp and hasattr(tp, "DocumentRange"):
                    text_content = str(tp.DocumentRange.GetText(-1))[:500]
            except Exception:
                pass

            return ControlSnapshot(
                automation_id=getattr(control, "AutomationId", "") or "",
                name=getattr(control, "Name", "") or "",
                class_name=getattr(control, "ClassName", "") or "",
                control_type=str(getattr(control, "ControlTypeName", "")),
                bounding_rect=bbox,
                is_enabled=bool(getattr(control, "IsEnabled", True)),
                is_offscreen=bool(getattr(control, "IsOffscreen", False)),
                has_keyboard_focus=bool(
                    getattr(control, "HasKeyboardFocus", False)
                ),
                value=value,
                text_content=text_content,
                depth=depth,
                children_count=len(children) if children else 0,
                parent_name=parent_name,
            )
        except Exception:
            return None
