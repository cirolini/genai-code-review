"""
The provider interface every LLM adapter implements.

An adapter's only job is to turn a prompt into text and report what that cost.
Timing, retries and error wrapping live here so that every provider behaves the
same way when something goes wrong — which, for a bot that comments on pull
requests, matters more than the happy path.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
)
from providers.retry import RetryPolicy, with_retries

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """
    A provider call failed in a way the user needs to be told about.

    Carries a message written for a pull request comment, not a stack trace.
    """

    def __init__(self, message: str, *, provider: str, model: str, cause: Exception | None = None):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.cause = cause


class ProviderConfigurationError(ProviderError):
    """The provider was asked for something impossible before any call was made."""


@dataclass(frozen=True)
class Usage:
    """Token counts for one request. None where the provider does not report them."""

    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ReviewResult:
    """
    One completed review call.

    `usage` and `latency_s` live on the result rather than on the provider so
    that a provider instance stays reusable and thread-safe: two calls on the
    same adapter produce two results, not one mutated object.

    `parsed` stays None until Phase 2 introduces schema-validated output.
    """

    text: str
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_s: float = 0.0
    parsed: Any | None = None
    attempts: int = 1


class LLMProvider(ABC):
    """
    Base class for provider adapters.

    Subclasses implement `_complete`. Everything else — timing, retry, turning
    an SDK exception into a ProviderError — is handled here.
    """

    name: str = "unset"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = DEFAULT_TIMEOUT,
        retry_policy: RetryPolicy | None = None,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retry_policy = retry_policy or RetryPolicy()

    # --- to implement in a subclass -------------------------------------

    @abstractmethod
    def _complete(self, prompt: str, schema: dict | None) -> tuple[str, Usage]:
        """Make one request. Raise the SDK's own exception on failure."""

    def _is_retryable(self, exc: Exception) -> bool:
        """Whether this exception is worth another attempt."""
        return _looks_transient(exc)

    def _describe_failure(self, exc: Exception) -> str:
        """A message for the pull request comment. Never include the API key."""
        return f"{type(exc).__name__}: {exc}"

    # --- public interface ------------------------------------------------

    def review(self, prompt: str, schema: dict | None = None) -> ReviewResult:
        """
        Send `prompt` to the model and return the reply with its cost.

        Raises ProviderError if the call fails after the configured retries.
        """
        started = time.monotonic()
        try:
            (text, usage), attempts = with_retries(
                lambda: self._complete(prompt, schema),
                policy=self.retry_policy,
                is_retryable=self._is_retryable,
                describe=lambda e: f"{self.name}/{self.model}: {type(e).__name__}",
            )
        except Exception as exc:
            raise ProviderError(
                self._describe_failure(exc),
                provider=self.name,
                model=self.model,
                cause=exc,
            ) from exc

        latency = time.monotonic() - started
        logger.info(
            "%s/%s responded in %.2fs (in=%s out=%s, attempts=%d)",
            self.name,
            self.model,
            latency,
            usage.input_tokens,
            usage.output_tokens,
            attempts,
        )
        return ReviewResult(
            text=text,
            provider=self.name,
            model=self.model,
            usage=usage,
            latency_s=latency,
            attempts=attempts,
        )


def _looks_transient(exc: Exception) -> bool:
    """
    Decide retryability without importing every SDK's exception hierarchy.

    Each SDK defines its own error classes, and importing all of them here
    would couple this module to providers the user may not have configured.
    Matching on class name and status code keeps the base class independent;
    adapters override `_is_retryable` when they want to be precise.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        # 408 timeout, 409 conflict, 429 rate limit, and anything 5xx.
        return status in (408, 409, 429) or status >= 500

    name = type(exc).__name__.lower()
    transient_markers = ("timeout", "connection", "ratelimit", "unavailable", "overloaded")
    return any(marker in name for marker in transient_markers)
