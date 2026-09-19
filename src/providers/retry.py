"""
Retry with exponential backoff and jitter.

Thirty lines instead of a dependency. The SDKs each have their own retry
support with their own defaults; doing it here means one policy applies to
every provider and the run log says the same thing whichever one is in use.
"""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from config import RETRY_ATTEMPTS, RETRY_BASE_DELAY, RETRY_MAX_DELAY

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = RETRY_ATTEMPTS
    base_delay: float = RETRY_BASE_DELAY
    max_delay: float = RETRY_MAX_DELAY


def with_retries[T](
    call: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    is_retryable: Callable[[Exception], bool] = lambda _: True,
    describe: Callable[[Exception], str] = lambda e: type(e).__name__,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, int]:
    """
    Call `call`, retrying transient failures.

    Returns the result and how many attempts it took. Re-raises the last
    exception once the attempts are used up, or immediately if `is_retryable`
    says the failure is permanent — retrying a 401 only wastes the user's time.

    `sleep` is injectable so tests do not actually wait.
    """
    policy = policy or RetryPolicy()
    last: Exception

    for attempt in range(1, policy.attempts + 1):
        try:
            return call(), attempt
        except Exception as exc:  # re-raised below once retries are exhausted
            last = exc
            if not is_retryable(exc):
                logger.info("%s is not retryable, giving up", describe(exc))
                raise
            if attempt == policy.attempts:
                logger.warning("%s failed after %d attempts", describe(exc), attempt)
                raise

            delay = min(policy.base_delay * (2 ** (attempt - 1)), policy.max_delay)
            delay += random.uniform(0, delay * 0.1)
            logger.warning(
                "%s on attempt %d/%d, retrying in %.1fs",
                describe(exc),
                attempt,
                policy.attempts,
                delay,
            )
            sleep(delay)

    raise last  # unreachable; keeps type checkers happy
