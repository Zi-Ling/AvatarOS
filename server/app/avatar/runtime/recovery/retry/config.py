# app/avatar/runtime/retry.py
"""
重试机制

支持：
1. 指数退避（Exponential Backoff）
2. 可配置的重试次数
3. 可重试错误类型判断
4. 重试日志记录
"""
from __future__ import annotations

import time
import logging
from typing import Callable, TypeVar, Optional, Type, Tuple
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryConfig:
    """重试配置"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    ):
        """
        初始化重试配置
        
        Args:
            max_attempts: 最大尝试次数（包括首次）
            base_delay: 基础延迟（秒）
            max_delay: 最大延迟（秒）
            exponential_base: 指数退避基数
            retryable_exceptions: 可重试的异常类型
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_exceptions = retryable_exceptions or (
            # 默认可重试的异常
            ConnectionError,
            TimeoutError,
            OSError,
        )
    
    def calculate_delay(self, attempt: int) -> float:
        """
        计算延迟时间（指数退避）
        
        Args:
            attempt: 当前尝试次数（从 0 开始）
        
        Returns:
            延迟时间（秒）
        """
        delay = self.base_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)
    
    def is_retryable(self, exception: Exception) -> bool:
        """
        判断异常是否可重试
        
        Args:
            exception: 异常对象
        
        Returns:
            是否可重试
        """
        return isinstance(exception, self.retryable_exceptions)


def retry_with_backoff(
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    重试装饰器（指数退避）
    
    Args:
        config: 重试配置
        on_retry: 重试回调函数 (exception, attempt, delay)
    
    Returns:
        装饰器函数
    
    Example:
        ```python
        @retry_with_backoff(RetryConfig(max_attempts=3))
        def fetch_data():
            response = requests.get("https://api.example.com/data")
            return response.json()
        ```
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # 检查是否可重试
                    if not config.is_retryable(e):
                        logger.warning(
                            f"[Retry] Non-retryable error: {type(e).__name__}: {e!r}"
                        )
                        raise
                    
                    # 最后一次尝试失败，不再重试
                    if attempt == config.max_attempts - 1:
                        logger.error(f"[Retry] Max attempts ({config.max_attempts}) reached, giving up")
                        raise
                    
                    # 计算延迟
                    delay = config.calculate_delay(attempt)
                    
                    # 记录日志
                    logger.warning(
                        f"[Retry] Attempt {attempt + 1}/{config.max_attempts} failed: "
                        f"{type(e).__name__}: {e}. Retrying in {delay:.1f}s..."
                    )
                    
                    # 调用回调
                    if on_retry:
                        on_retry(e, attempt + 1, delay)
                    
                    # 等待后重试
                    time.sleep(delay)
            
            # 理论上不会到这里，但为了类型安全
            raise last_exception
        
        return wrapper
    return decorator


async def async_retry_with_backoff(
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
) -> Callable:
    """
    异步重试装饰器（指数退避）
    
    Args:
        config: 重试配置
        on_retry: 重试回调函数
    
    Returns:
        装饰器函数
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            import asyncio
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if not config.is_retryable(e):
                        logger.warning(f"[AsyncRetry] Non-retryable error: {type(e).__name__}: {e}")
                        raise
                    
                    if attempt == config.max_attempts - 1:
                        logger.error(f"[AsyncRetry] Max attempts ({config.max_attempts}) reached")
                        raise
                    
                    delay = config.calculate_delay(attempt)
                    
                    logger.warning(
                        f"[AsyncRetry] Attempt {attempt + 1}/{config.max_attempts} failed: "
                        f"{type(e).__name__}: {e}. Retrying in {delay:.1f}s..."
                    )
                    
                    if on_retry:
                        on_retry(e, attempt + 1, delay)
                    
                    await asyncio.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator


class RetryableError(Exception):
    """可重试的错误基类"""
    pass


class NonRetryableError(Exception):
    """不可重试的错误基类"""
    pass

