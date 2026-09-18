from __future__ import annotations


class IntelligenceError(RuntimeError):
    """Base exception for optional intelligence failures."""


class IntelligenceNotConfiguredError(IntelligenceError):
    pass


class IntelligenceTimeoutError(IntelligenceError):
    pass


class IntelligenceRateLimitError(IntelligenceError):
    pass


class IntelligenceProviderUnavailableError(IntelligenceError):
    pass


class IntelligenceInvalidResponseError(IntelligenceError):
    pass
