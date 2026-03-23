# server/app/services/browser/verification_engine.py
"""独立验证引擎：action-level + step-level 两层验证。"""
from __future__ import annotations

import re
from typing import Any

from app.services.browser.models import (
    BrowserVerificationResult,
    BrowserVerificationStrategy,
    PageStateSnapshot,
    VerificationSpec,
)


class VerificationEngine:
    """独立验证引擎，与 ActionDispatcher 解耦。"""

    async def verify_action(
        self,
        verification: VerificationSpec,
        page: Any,
        snapshot_fn: Any = None,
    ) -> BrowserVerificationResult:
        """action-level 验证：单个操作后验证。"""
        return await self._verify(verification, page, snapshot_fn)

    async def verify_step(
        self,
        verifications: list[VerificationSpec],
        page: Any,
        snapshot_fn: Any = None,
    ) -> list[BrowserVerificationResult]:
        """step-level 验证：操作序列完成后批量验证。"""
        results = []
        for v in verifications:
            r = await self._verify(v, page, snapshot_fn)
            results.append(r)
        return results

    async def _verify(
        self,
        spec: VerificationSpec,
        page: Any,
        snapshot_fn: Any = None,
    ) -> BrowserVerificationResult:
        strategy = spec.strategy
        try:
            if strategy == BrowserVerificationStrategy.ELEMENT_APPEARED:
                return await self._check_element_appeared(spec, page, snapshot_fn)
            elif strategy == BrowserVerificationStrategy.ELEMENT_DISAPPEARED:
                return await self._check_element_disappeared(spec, page, snapshot_fn)
            elif strategy == BrowserVerificationStrategy.TEXT_CONTAINS:
                return await self._check_text_contains(spec, page, snapshot_fn)
            elif strategy == BrowserVerificationStrategy.TEXT_EQUALS:
                return await self._check_text_equals(spec, page, snapshot_fn)
            elif strategy == BrowserVerificationStrategy.URL_CHANGED:
                return await self._check_url_changed(spec, page, snapshot_fn)
            elif strategy == BrowserVerificationStrategy.URL_MATCHES:
                return await self._check_url_matches(spec, page, snapshot_fn)
            elif strategy == BrowserVerificationStrategy.ELEMENT_COUNT:
                return await self._check_element_count(spec, page, snapshot_fn)
            elif strategy == BrowserVerificationStrategy.ATTRIBUTE_EQUALS:
                return await self._check_attribute_equals(spec, page, snapshot_fn)
            else:
                return BrowserVerificationResult(
                    passed=False, strategy=strategy.value,
                    detail=f"Unknown verification strategy: {strategy}",
                )
        except Exception as exc:
            snapshot = await snapshot_fn() if snapshot_fn else None
            return BrowserVerificationResult(
                passed=False, strategy=strategy.value,
                detail=f"Verification error: {exc}",
                page_snapshot=snapshot,
            )

    async def _check_element_appeared(self, spec, page, snapshot_fn):
        el = await page.query_selector(spec.selector)
        passed = el is not None
        detail = "" if passed else f"Element not found: {spec.selector}"
        snapshot = None if passed else (await snapshot_fn() if snapshot_fn else None)
        return BrowserVerificationResult(
            passed=passed, strategy=spec.strategy.value,
            expected=spec.selector, actual="found" if passed else "not_found",
            detail=detail, page_snapshot=snapshot,
        )

    async def _check_element_disappeared(self, spec, page, snapshot_fn):
        el = await page.query_selector(spec.selector)
        passed = el is None
        detail = "" if passed else f"Element still present: {spec.selector}"
        snapshot = None if passed else (await snapshot_fn() if snapshot_fn else None)
        return BrowserVerificationResult(
            passed=passed, strategy=spec.strategy.value,
            expected="disappeared", actual="gone" if passed else "still_present",
            detail=detail, page_snapshot=snapshot,
        )

    async def _check_text_contains(self, spec, page, snapshot_fn):
        text = await page.text_content(spec.selector) if spec.selector else await page.content()
        text = text or ""
        expected = str(spec.expected or "")
        passed = expected in text
        detail = "" if passed else f"Expected text '{expected}' not found in '{text[:200]}'"
        snapshot = None if passed else (await snapshot_fn() if snapshot_fn else None)
        return BrowserVerificationResult(
            passed=passed, strategy=spec.strategy.value,
            expected=expected, actual=text[:500],
            detail=detail, page_snapshot=snapshot,
        )

    async def _check_text_equals(self, spec, page, snapshot_fn):
        text = await page.text_content(spec.selector) if spec.selector else ""
        text = (text or "").strip()
        expected = str(spec.expected or "").strip()
        passed = text == expected
        detail = "" if passed else f"Expected '{expected}', got '{text[:200]}'"
        snapshot = None if passed else (await snapshot_fn() if snapshot_fn else None)
        return BrowserVerificationResult(
            passed=passed, strategy=spec.strategy.value,
            expected=expected, actual=text[:500],
            detail=detail, page_snapshot=snapshot,
        )

    async def _check_url_changed(self, spec, page, snapshot_fn):
        current_url = page.url if hasattr(page, "url") else ""
        expected = str(spec.expected or "")
        passed = expected in current_url
        detail = "" if passed else f"URL '{current_url}' does not contain '{expected}'"
        snapshot = None if passed else (await snapshot_fn() if snapshot_fn else None)
        return BrowserVerificationResult(
            passed=passed, strategy=spec.strategy.value,
            expected=expected, actual=current_url,
            detail=detail, page_snapshot=snapshot,
        )

    async def _check_url_matches(self, spec, page, snapshot_fn):
        current_url = page.url if hasattr(page, "url") else ""
        pattern = str(spec.expected or "")
        passed = bool(re.search(pattern, current_url))
        detail = "" if passed else f"URL '{current_url}' does not match pattern '{pattern}'"
        snapshot = None if passed else (await snapshot_fn() if snapshot_fn else None)
        return BrowserVerificationResult(
            passed=passed, strategy=spec.strategy.value,
            expected=pattern, actual=current_url,
            detail=detail, page_snapshot=snapshot,
        )

    async def _check_element_count(self, spec, page, snapshot_fn):
        elements = await page.query_selector_all(spec.selector)
        actual_count = len(elements) if elements else 0
        expected_count = int(spec.expected or 0)
        comp = spec.comparison or "eq"
        ops = {
            "eq": actual_count == expected_count,
            "gt": actual_count > expected_count,
            "lt": actual_count < expected_count,
            "gte": actual_count >= expected_count,
            "lte": actual_count <= expected_count,
        }
        passed = ops.get(comp, False)
        detail = "" if passed else f"Element count {actual_count} {comp} {expected_count} failed"
        snapshot = None if passed else (await snapshot_fn() if snapshot_fn else None)
        return BrowserVerificationResult(
            passed=passed, strategy=spec.strategy.value,
            expected=f"{comp} {expected_count}", actual=actual_count,
            detail=detail, page_snapshot=snapshot,
        )

    async def _check_attribute_equals(self, spec, page, snapshot_fn):
        attr_name = spec.expected.get("attribute") if isinstance(spec.expected, dict) else ""
        expected_val = spec.expected.get("value", "") if isinstance(spec.expected, dict) else str(spec.expected or "")
        actual_val = await page.get_attribute(spec.selector, attr_name) if spec.selector else None
        actual_val = actual_val or ""
        passed = actual_val == expected_val
        detail = "" if passed else f"Attribute '{attr_name}' expected '{expected_val}', got '{actual_val}'"
        snapshot = None if passed else (await snapshot_fn() if snapshot_fn else None)
        return BrowserVerificationResult(
            passed=passed, strategy=spec.strategy.value,
            expected=expected_val, actual=actual_val,
            detail=detail, page_snapshot=snapshot,
        )
