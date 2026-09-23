"""Caller-facing failure messages for EDU-C2-046.

Single source of truth for every failure message this agent shows to a caller.

**Why this module exists.** The framework error boundary
(``BaseNode.__call__``) records ``f"[{node}] {error}\\n{traceback.format_exc()}"``
into ``state["error_log"]``, and ``GraphNode`` hands that list to
``on_subgraph_error()`` as the only channel carrying failure information out of
the inner graph. That string is an *operator* diagnostic: it contains container
filesystem paths, internal module qualnames, line numbers, and secret-store
lookup trails. It is not caller-facing content and must never be shown as-is.

**Design: classify, do not filter.** An earlier implementation tried to scrub the
diagnostic with regexes and emit what survived. That approach is fail-open — any
path shape not anticipated by the patterns leaks — and its correctness cannot be
established by reading it, only probed input by input.

This module inverts that: the raw diagnostic selects a :class:`FailureCategory`,
and the category selects a message written here. The raw string is *never* part
of the output. Every byte a caller can receive is a literal in ``_MESSAGES``
below, so "can a path leak?" is answered by reading this file rather than by
testing unbounded inputs. Unrecognised input is not a gap — it falls to
:data:`FailureCategory.UNKNOWN` and yields the generic message.

**Operator diagnostics are not lost.** The framework already records the full
entry in ``error_log`` and emits it via the S-4 ``node_error`` trace event. The
caller receives a correlating ``trace_id`` instead of the detail.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["FailureCategory", "classify_failure", "failure_message", "describe_failure"]


class FailureCategory(str, Enum):
    """Kinds of failure this agent can explain to a caller.

    ``str`` mixin mirrors the framework's ``AgentStatus`` / ``HitlStatus``
    convention so values compare directly with strings.
    """

    MISSING_CREDENTIAL = "missing_credential"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    SOURCE_NOT_APPROVED = "source_not_approved"
    INVALID_SCOPE = "invalid_scope"
    REVIEW_REJECTED = "review_rejected"
    UNKNOWN = "unknown"


# The complete set of strings this module can emit. Nothing outside this mapping
# ever reaches a caller — no substring of a framework diagnostic, no exception
# text, no path. Keep each message actionable and free of internal identifiers
# (node names, module paths, hostnames, secret keys).
_MESSAGES: dict[FailureCategory, str] = {
    FailureCategory.MISSING_CREDENTIAL: (
        "A credential this agent requires is not configured in the current environment."
    ),
    FailureCategory.UPSTREAM_UNAVAILABLE: ("An upstream curriculum source could not be reached."),
    FailureCategory.UPSTREAM_TIMEOUT: ("An upstream curriculum source did not respond in time."),
    FailureCategory.SOURCE_NOT_APPROVED: ("One or more requested sources are not in the approved source list."),
    FailureCategory.INVALID_SCOPE: ("The curriculum change scope was incomplete or invalid."),
    FailureCategory.REVIEW_REJECTED: ("The briefing was rejected during human review."),
    FailureCategory.UNKNOWN: ("The curriculum change impact review workflow could not be completed."),
}

# Lowercase markers that identify a category within a raw diagnostic.
#
# These are matched against the diagnostic ONLY to pick a category — they never
# contribute to output, so an over-broad marker degrades the specificity of the
# message, never its safety. Ordering matters: the first category with a
# matching marker wins, so more specific categories are listed first.
_MARKERS: tuple[tuple[FailureCategory, tuple[str, ...]], ...] = (
    # MissingSecret formats as "required secret 'KEY' not found (checked: ...)".
    (FailureCategory.MISSING_CREDENTIAL, ("required secret", "missingsecret", "secret not found")),
    (FailureCategory.UPSTREAM_TIMEOUT, ("timeout", "timed out", "deadline exceeded")),
    (
        FailureCategory.UPSTREAM_UNAVAILABLE,
        (
            "connection",
            "connectionerror",
            "unreachable",
            "max retries exceeded",
            "name or service not known",
            "temporary failure in name resolution",
            "httperror",
            "bad gateway",
            "service unavailable",
        ),
    ),
    (FailureCategory.SOURCE_NOT_APPROVED, ("not in the approved source list",)),
    (
        FailureCategory.INVALID_SCOPE,
        ("change_scope_json is missing", "is not valid json", "failed validation"),
    ),
    (FailureCategory.REVIEW_REJECTED, ("rejected by reviewer",)),
)


def classify_failure(raw: str) -> FailureCategory:
    """Map a raw framework diagnostic to a :class:`FailureCategory`.

    Only the *first line* of the diagnostic is inspected. Traceback frames carry
    source paths and quoted code, and matching a marker inside a frame would
    attribute the failure to whichever module happened to appear in the stack
    rather than to the actual error.

    Args:
        raw: An ``error_log`` entry, typically
            ``"[NodeName] <error>\\n<traceback>"``.

    Returns:
        The matching category, or :data:`FailureCategory.UNKNOWN` when no marker
        applies. ``UNKNOWN`` is the safe default, not a failure of this function.
    """
    first_line = next((line for line in raw.splitlines() if line.strip()), "")
    haystack = first_line.lower()
    if not haystack:
        return FailureCategory.UNKNOWN

    for category, markers in _MARKERS:
        if any(marker in haystack for marker in markers):
            return category
    return FailureCategory.UNKNOWN


def failure_message(category: FailureCategory) -> str:
    """Return the caller-facing message for ``category``."""
    return _MESSAGES.get(category, _MESSAGES[FailureCategory.UNKNOWN])


def describe_failure(raw: str, trace_id: str = "") -> str:
    """Convert a raw framework diagnostic into a caller-safe message.

    The returned string is always one of the literals in :data:`_MESSAGES`,
    optionally followed by a reference code for operator correlation.

    Args:
        raw: An ``error_log`` entry. Its content selects a category and is
            otherwise discarded.
        trace_id: Correlation id for the invocation. Appended so a caller can
            quote it to an administrator, who can then retrieve the full
            diagnostic from the audit log. Non-identifying on its own.

    Returns:
        A caller-safe message containing no path, hostname, module name, or
        secret identifier.
    """
    message = failure_message(classify_failure(raw))
    reference = trace_id.strip()
    if reference:
        return f"{message} (reference: {reference})"
    return message
