# server/app/avatar/perception/drivers/web_driver.py
import logging
import asyncio
from typing import List, Optional
from ...perception.base import BasePerceptionBackend
from ...perception.models import UIElement, PerceptionSource
from ...actions.web.playwright_driver import global_playwright_driver

logger = logging.getLogger(__name__)

class PlaywrightPerceptionBackend(BasePerceptionBackend):
    """
    Web Perception Backend using Playwright (Async).
    Directly inspects the DOM of the active browser page to find interactive elements.
    """
    
    @property
    def name(self) -> str:
        return "web_driver"

    @property
    def priority(self) -> int:
        return 30 # High priority (API level)

    def is_available(self) -> bool:
        # Safe check: only available if page exists and is not closed.
        # We do NOT call get_page() here because it might trigger browser launch.
        # We access _page directly to avoid side effects in the loop.
        page = global_playwright_driver._page
        if page and not page.is_closed():
            return True
        return False

    async def scan(self, target_window_title: Optional[str] = None) -> List[UIElement]:
        """
        Injects JS to find interactive elements and returns them as UIElements.
        """
        elements = []
        try:
            # We only scan if we can get a page (this might start it if we force it, 
            # but scan is usually called only if available... wait.
            # If is_available returns False, manager skips scan.
            # So we are safe to assume page exists or we shouldn't be here.
            # But let's be robust.
            
            page = await global_playwright_driver.get_page()
            
            # Simple heuristic: Find visible buttons, inputs, links
            # We use evaluate to run JS in the browser context for performance
            js_script = """
            () => {
                const items = [];
                const tags = ['button', 'input', 'textarea', 'select', 'a'];
                const allElements = document.querySelectorAll(tags.join(','));
                
                let count = 0;
                allElements.forEach((el) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden') {
                        items.push({
                            id: `web-${count++}`,
                            tagName: el.tagName.toLowerCase(),
                            text: el.innerText || el.value || el.placeholder || '',
                            rect: {
                                x: rect.x,
                                y: rect.y,
                                width: rect.width,
                                height: rect.height
                            },
                            attributes: {
                                id: el.id,
                                class: el.className,
                                href: el.href,
                                type: el.type
                            }
                        });
                    }
                });
                return items;
            }
            """
            
            dom_items = await page.evaluate(js_script)
            
            for item in dom_items:
                rect = item['rect']
                el = UIElement(
                    id=item['id'],
                    name=item['text'][:50].strip(), # Truncate long text
                    role=item['tagName'],
                    bbox=(int(rect['x']), int(rect['y']), int(rect['width']), int(rect['height'])),
                    center=(int(rect['x'] + rect['width'] / 2), int(rect['y'] + rect['height'] / 2)),
                    source=PerceptionSource.DRIVER, 
                    metadata={
                        "selector": self._generate_selector(item),
                        "attributes": item['attributes']
                    }
                )
                elements.append(el)
                
        except Exception as e:
            logger.error(f"Web driver scan failed: {e}")
            
        return elements

    def _generate_selector(self, item: dict) -> str:
        """Generate a best-effort CSS selector."""
        attrs = item['attributes']
        if attrs.get('id'):
            return f"#{attrs['id']}"
        if attrs.get('class'):
            # Use first class for simplicity, though risky
            cls = attrs['class'].split()[0] if attrs['class'] else ''
            if cls:
                return f"{item['tagName']}.{cls}"
        return item['tagName']
