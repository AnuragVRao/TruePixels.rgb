"""Error codes raised by M2, per PRD2 section 11.

Every M2 failure surfaces as one of these four codes. The HTTP status is
carried on the exception so the router can translate without a lookup table.
"""

from __future__ import annotations


class InferenceError(Exception):
    """Base class for M2 failures. INF_FAILED (500) when raised directly.

    Used for an unhandled failure inside a classifier or the fusion module.
    Per PRD2 section 11.1, an exception in either branch fails the whole
    request - M2 never returns a prediction based on the surviving branch
    alone, because a hybrid detector running on one branch is a different
    system and must not pretend otherwise.
    """

    code = "INF_FAILED"
    http_status = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ModelUnavailableError(InferenceError):
    """No active model of a required type in D3, or the artefact failed to load."""

    code = "INF_MODEL_UNAVAILABLE"
    http_status = 503


class TimeoutError(InferenceError):  # noqa: A001 - name fixed by the contract
    """Inference exceeded the configured wall-clock budget."""

    code = "INF_TIMEOUT"
    http_status = 504


class PredictionNotFoundError(InferenceError):
    """prediction_id does not exist or is not visible to the caller."""

    code = "INF_PREDICTION_NOT_FOUND"
    http_status = 404
