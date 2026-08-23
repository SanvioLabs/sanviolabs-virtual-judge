"""Retry utility for transient API failures."""

import logging
import time
from collections.abc import Callable
from functools import wraps

logger = logging.getLogger(__name__)


def retry(max_attempts: int = 3, backoff_base: float = 1.0, retryable_exceptions: tuple = (Exception,)):
    """Decorator that retries a function on transient failures.

    Args:
        max_attempts: Total attempts (including the first).
        backoff_base: Base seconds for exponential backoff (1s, 2s, 4s...).
        retryable_exceptions: Tuple of exception types to retry on.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    wait = backoff_base * (2 ** (attempt - 1))
                    logger.warning(f"{func.__name__} attempt {attempt} failed: {e}. Retrying in {wait:.1f}s...")
                    time.sleep(wait)
            raise last_exception  # Should never reach here
        return wrapper
    return decorator
