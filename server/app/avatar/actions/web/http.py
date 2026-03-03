# avatar/actions/web/http.py
from __future__ import annotations

import requests
from typing import Optional

from ..base import ActionResult, WebActionContext


def http_get(url: str, *, ctx: Optional[WebActionContext] = None, timeout: int = 10) -> ActionResult:
    try:
        resp = requests.get(url, timeout=timeout)
        return ActionResult(
            success=True,
            output={
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "text": resp.text,
            },
        )
    except Exception as e:  # noqa: BLE001
        return ActionResult(success=False, error=str(e))


def http_post(url: str, data=None, json=None, *, ctx: Optional[WebActionContext] = None, timeout: int = 10) -> ActionResult:
    try:
        resp = requests.post(url, data=data, json=json, timeout=timeout)
        return ActionResult(
            success=True,
            output={
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "text": resp.text,
            },
        )
    except Exception as e:  # noqa: BLE001
        return ActionResult(success=False, error=str(e))
