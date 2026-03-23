"""
health.py — Health check and resilience monitoring API.

Provides:
- GET /health — Basic health check
- GET /health/resilience — Circuit breaker, bulkhead, retry status
"""

from __future__ import annotations

import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    """Basic health check."""
    return {"status": "ok"}


@router.get("/resilience")
async def resilience_report():
    """Report status of all resilience primitives."""
    try:
        from app.core.resilience import ResilienceRegistry
        registry = ResilienceRegistry.get_instance()
        return registry.health_report()
    except Exception as e:
        return {"error": str(e)}
