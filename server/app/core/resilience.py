"""
resilience.py — Production-grade resilience primitives.

Provides:
- CircuitBreaker: Prevents cascading failures with open/half-open/closed states
- BulkheadLimiter: Limits concurrent access to a resource
- RetryStrategy: Configurable retry with exponential backoff + jitter

All primitives are async-native and non-blocking.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing — reject calls
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout_s: float = 30.0
    half_open_max_calls: int = 1
    success_threshold: int = 2  # successes needed to close from half-open


class CircuitBreaker:
    """Async circuit breaker with open/half-open/closed states."""

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> None:
        self.name = name
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls: int = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self._config.recovery_timeout_s:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
                logger.info(f"[CircuitBreaker:{self.name}] OPEN → HALF_OPEN")
        return self._state

    def is_call_allowed(self) -> bool:
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return self._half_open_calls < self._config.half_open_max_calls
        return False  # OPEN

    def record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info(f"[CircuitBreaker:{self.name}] HALF_OPEN → CLOSED")
        else:
            self._failure_count = 0

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning(f"[CircuitBreaker:{self.name}] HALF_OPEN → OPEN")
        elif self._failure_count >= self._config.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                f"[CircuitBreaker:{self.name}] CLOSED → OPEN "
                f"(failures={self._failure_count})"
            )

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self.is_call_allowed():
            raise CircuitOpenError(
                f"Circuit '{self.name}' is {self.state.value}"
            )
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def reset(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "config": {
                "failure_threshold": self._config.failure_threshold,
                "recovery_timeout_s": self._config.recovery_timeout_s,
            },
        }


class CircuitOpenError(Exception):
    pass


# ---------------------------------------------------------------------------
# BulkheadLimiter
# ---------------------------------------------------------------------------

class BulkheadLimiter:
    """Limits concurrent access to a resource (bulkhead isolation pattern).

    Prevents one slow/failing subsystem from consuming all available
    concurrency slots and starving other subsystems.
    """

    def __init__(self, name: str, max_concurrent: int = 10, max_queue: int = 20) -> None:
        self.name = name
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue_count = 0
        self._active_count = 0
        self._rejected_count = 0

    async def acquire(self, timeout: Optional[float] = None) -> bool:
        if self._queue_count >= self.max_queue:
            self._rejected_count += 1
            logger.warning(
                f"[Bulkhead:{self.name}] Queue full "
                f"(active={self._active_count}, queued={self._queue_count})"
            )
            return False
        self._queue_count += 1
        try:
            if timeout is not None:
                acquired = await asyncio.wait_for(
                    self._semaphore.acquire(), timeout=timeout,
                )
            else:
                acquired = await self._semaphore.acquire()
            if acquired:
                self._active_count += 1
            return acquired
        except asyncio.TimeoutError:
            self._rejected_count += 1
            return False
        finally:
            self._queue_count -= 1

    def release(self) -> None:
        self._active_count = max(0, self._active_count - 1)
        self._semaphore.release()

    async def __aenter__(self) -> "BulkheadLimiter":
        ok = await self.acquire()
        if not ok:
            raise BulkheadRejectError(
                f"Bulkhead '{self.name}' rejected: queue full"
            )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.release()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "active": self._active_count,
            "max_concurrent": self.max_concurrent,
            "queue": self._queue_count,
            "max_queue": self.max_queue,
            "rejected_total": self._rejected_count,
        }


class BulkheadRejectError(Exception):
    pass


# ---------------------------------------------------------------------------
# RetryStrategy
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (Exception,)


class RetryStrategy:
    """Async retry with exponential backoff + jitter."""

    def __init__(self, name: str, config: Optional[RetryConfig] = None) -> None:
        self.name = name
        self._config = config or RetryConfig()
        self._total_retries = 0
        self._total_failures = 0

    async def execute(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(self._config.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except self._config.retryable_exceptions as e:
                last_exc = e
                if attempt >= self._config.max_retries:
                    self._total_failures += 1
                    break
                self._total_retries += 1
                delay = self._compute_delay(attempt)
                logger.info(
                    f"[Retry:{self.name}] Attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    def _compute_delay(self, attempt: int) -> float:
        delay = self._config.base_delay_s * (
            self._config.exponential_base ** attempt
        )
        delay = min(delay, self._config.max_delay_s)
        if self._config.jitter:
            delay *= 0.5 + random.random()
        return delay

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total_retries": self._total_retries,
            "total_failures": self._total_failures,
            "config": {
                "max_retries": self._config.max_retries,
                "base_delay_s": self._config.base_delay_s,
                "max_delay_s": self._config.max_delay_s,
            },
        }


# ---------------------------------------------------------------------------
# ResilienceRegistry — centralized access to all resilience primitives
# ---------------------------------------------------------------------------

class ResilienceRegistry:
    """Singleton registry for all resilience primitives.

    Provides centralized access for monitoring and health checks.
    """

    _instance: Optional["ResilienceRegistry"] = None

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._bulkheads: dict[str, BulkheadLimiter] = {}
        self._retries: dict[str, RetryStrategy] = {}

    @classmethod
    def get_instance(cls) -> "ResilienceRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_or_create_breaker(
        self, name: str, config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]

    def get_or_create_bulkhead(
        self, name: str, max_concurrent: int = 10, max_queue: int = 20,
    ) -> BulkheadLimiter:
        if name not in self._bulkheads:
            self._bulkheads[name] = BulkheadLimiter(name, max_concurrent, max_queue)
        return self._bulkheads[name]

    def get_or_create_retry(
        self, name: str, config: Optional[RetryConfig] = None,
    ) -> RetryStrategy:
        if name not in self._retries:
            self._retries[name] = RetryStrategy(name, config)
        return self._retries[name]

    def health_report(self) -> dict:
        return {
            "circuit_breakers": {
                name: cb.to_dict() for name, cb in self._breakers.items()
            },
            "bulkheads": {
                name: bh.to_dict() for name, bh in self._bulkheads.items()
            },
            "retries": {
                name: rs.to_dict() for name, rs in self._retries.items()
            },
        }
