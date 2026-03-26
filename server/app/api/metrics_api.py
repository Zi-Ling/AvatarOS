"""Metrics API — expose multi-agent runtime metrics.

GET /metrics/multi-agent — summary of all collected metrics
GET /metrics/multi-agent/recent — recent metric data points
"""
from __future__ import annotations

import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/multi-agent")
async def get_multi_agent_metrics():
    """Get summary of multi-agent runtime metrics."""
    from app.avatar.runtime.multiagent.observability.metrics import get_metrics
    return get_metrics().get_summary()


@router.get("/multi-agent/recent")
async def get_recent_metrics(limit: int = 100):
    """Get recent metric data points."""
    from app.avatar.runtime.multiagent.observability.metrics import get_metrics
    return {"points": get_metrics().get_recent_points(limit)}
