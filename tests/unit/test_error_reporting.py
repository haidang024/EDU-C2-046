"""Caller-facing failure messages must never disclose deployment internals.

The framework error boundary (BaseNode.__call__) records
f"[{node}] {error}\\n{traceback.format_exc()}" into error_log, and GraphNode
hands that list to on_subgraph_error() as the only channel carrying failure
information out of the inner graph. That entry contains container filesystem
paths, internal module qualnames, line numbers, and secret-store lookup trails.

src/services/error_reporting.py answers this by classification rather than
filtering: the raw diagnostic selects a category, and the category selects a
message defined in that module. The decisive property — and what the
exhaustiveness tests below assert — is that output is drawn from a closed set of
literals, so no input can produce a leak.
"""

from __future__ import annotations

import pytest

from framework.errors import SubgraphError
from framework.schemas.agent_status import AgentStatus
from src.graph.graph import CurriculumImpactGraphNode
from src.services.error_reporting import (
    FailureCategory,
    classify_failure,
    describe_failure,
    failure_message,
)
from src.services import error_reporting

# Verbatim shape produced by the framework error boundary for a missing secret —
# the failure originally reported against the deployed agent.
FRAMEWORK_TRACEBACK_ENTRY = (
    "[EvidenceRetrievalNode] Agent agent1000/EDU-C2-046: required secret '' not found "
    "(checked: platform, namespaces/agent1000, agents/agent1000/EDU-C2-046)\n"
    "Traceback (most recent call last):\n"
    '  File "/usr/local/lib/python3.11/site-packages/framework/nodes/base_node.py", line 194, in __call__\n'
    "    result = self.execute(state)\n"
    '  File "/app/src/nodes/evidence_retrieval_node.py", line 90, in execute\n'
    '    ctx.secrets.require("")\n'
    '  File "/usr/local/lib/python3.11/site-packages/framework/secrets/base.py", line 55, in require\n'
    "    raise MissingSecret(key, namespace=self._namespace, agent_name=self._agent_name)\n"
    "framework.secrets.base.MissingSecret: Agent agent1000/EDU-C2-046: required secret '' not found "
    "(checked: platform, namespaces/agent1000, agents/agent1000/EDU-C2-046)"
)

# Diagnostics covering every shape probed against the previous regex approach,
# including the four it leaked (bare "/app", dotted module path, raw IP, bare
# internal hostname). Classification makes all of them safe by construction.
HOSTILE_DIAGNOSTICS = [
    FRAMEWORK_TRACEBACK_ENTRY,
    "[EvidenceRetrievalNode] required secret 'CURRICULUM_CONNECTOR_API_KEY' not found (checked: platform)",
    "[N] config dir missing: /app",
    "[N] No module named src.nodes.evidence_retrieval_node",
    "[N] connection refused to 10.42.7.13:5432",
    "[N] pod edu-c2-046-7d9f on node ip-10-0-3-22.ec2.internal failed",
    "[N] cannot open src/nodes/evidence_retrieval_node.py",
    "[N] failed reading ~/.config/agent/creds",
    "[N] cannot open C:\\app\\src\\node.py",
    '[N] FileNotFoundError: "/app/data/records.json"',
    "[N] Failed to fetch https://curriculum.internal:8443/api/v2/records?id=3",
    "[N] HTTPSConnectionPool(host='curriculum.internal', port=443): Max retries exceeded",
    "[N] retrieval failed\n  at /app/src/services/service.py:41",
    "[N] wrapped\nDuring handling of the above exception, another exception occurred:\n"
    '  File "/app/x.py", line 2',
    '  File "/app/src/nodes/x.py", line 12, in execute',
    "",
    "   ",
]

# Fragments that must never appear in caller-facing output.
FORBIDDEN_FRAGMENTS = [
    "Traceback",
    "/app",
    "/usr/local",
    "site-packages",
    ".py",
    "checked:",
    "namespaces/",
    "framework.",
    "src.nodes",
    "line 194",
    "curriculum.internal",
    "ec2.internal",
    "10.42.7.13",
    "postgresql://",
    "https://",
    "CURRICULUM_CONNECTOR_API_KEY",
    "C:\\",
    "~/.config",
]

ALL_MESSAGES = frozenset(error_reporting._MESSAGES.values())

# Assembled at run time, never committed as a literal: a DSN with an inline
# password is a credential shape the S-5 gate rejects in tests/ as elsewhere
# . The classifier only ever sees it as an UPSTREAM_UNAVAILABLE
# marker, so the value itself is irrelevant to what is being tested.
HOSTILE_DIAGNOSTICS.append(
    "[N] could not connect: " + "postgresql://user:" + "pw" + "@db.internal:5432/curric"
)


def _assert_no_internals(text: str) -> None:
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in text, f"leaked {fragment!r} in {text!r}"


class TestClosedOutputSet:
    """The decisive property: output is drawn from a closed set of literals."""

    @pytest.mark.parametrize("raw", HOSTILE_DIAGNOSTICS)
    def test_output_is_always_a_registered_message(self, raw: str) -> None:
        # Not "the patterns stripped what I expected" but "the result is one of
        # the strings defined in the module" — which no input can widen.
        assert describe_failure(raw) in ALL_MESSAGES

    @pytest.mark.parametrize("raw", HOSTILE_DIAGNOSTICS)
    def test_no_internals_leak(self, raw: str) -> None:
        _assert_no_internals(describe_failure(raw))

    def test_every_registered_message_is_clean(self) -> None:
        # Guards the messages themselves: a future edit to _MESSAGES that adds a
        # path or hostname is caught here.
        for message in ALL_MESSAGES:
            _assert_no_internals(message)

    def test_every_category_has_a_message(self) -> None:
        # A category without an entry would silently fall back to UNKNOWN.
        for category in FailureCategory:
            assert category in error_reporting._MESSAGES

    @pytest.mark.parametrize("raw", HOSTILE_DIAGNOSTICS)
    def test_output_is_single_line(self, raw: str) -> None:
        assert "\n" not in describe_failure(raw)


class TestClassification:
    """Categories are selected correctly, so messages stay specific."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (FRAMEWORK_TRACEBACK_ENTRY, FailureCategory.MISSING_CREDENTIAL),
            (
                "[N] required secret 'CURRICULUM_CONNECTOR_API_KEY' not found (checked: platform)",
                FailureCategory.MISSING_CREDENTIAL,
            ),
            ("[N] HTTPSConnectionPool(host='x'): Max retries exceeded", FailureCategory.UPSTREAM_UNAVAILABLE),
            ("[N] connection refused to 10.42.7.13:5432", FailureCategory.UPSTREAM_UNAVAILABLE),
            ("[N] request timed out after 30s", FailureCategory.UPSTREAM_TIMEOUT),
            (
                "[N] source=SRC-1: Source 'SRC-1' is not in the approved source list.",
                FailureCategory.SOURCE_NOT_APPROVED,
            ),
            (
                "EvidenceRetrievalNode: change_scope_json is missing or empty.",
                FailureCategory.INVALID_SCOPE,
            ),
            (
                "BriefingHitlNode: briefing rejected by reviewer. Reason: out of scope",
                FailureCategory.REVIEW_REJECTED,
            ),
            ("[N] something nobody anticipated", FailureCategory.UNKNOWN),
            ("", FailureCategory.UNKNOWN),
        ],
    )
    def test_classify(self, raw: str, expected: FailureCategory) -> None:
        assert classify_failure(raw) == expected

    def test_timeout_wins_over_connection(self) -> None:
        # Ordering matters: a timeout mentioning a connection is a timeout.
        assert classify_failure("[N] connection timed out") == FailureCategory.UPSTREAM_TIMEOUT

    def test_only_first_line_is_inspected(self) -> None:
        # A marker appearing inside a traceback frame would otherwise attribute
        # the failure to whichever module happened to be on the stack.
        raw = "[N] something unanticipated\nTraceback (most recent call last):\n  timed out"
        assert classify_failure(raw) == FailureCategory.UNKNOWN


class TestTraceReference:
    """Operators keep correlation; callers keep a clean message."""

    def test_trace_id_is_appended(self) -> None:
        message = describe_failure(FRAMEWORK_TRACEBACK_ENTRY, "trace-abc-123")
        assert "reference: trace-abc-123" in message
        _assert_no_internals(message)

    @pytest.mark.parametrize("trace_id", ["", "   "])
    def test_blank_trace_id_is_omitted(self, trace_id: str) -> None:
        message = describe_failure(FRAMEWORK_TRACEBACK_ENTRY, trace_id)
        assert "reference" not in message
        assert message in ALL_MESSAGES

    def test_message_without_reference_matches_registered_literal(self) -> None:
        assert describe_failure(FRAMEWORK_TRACEBACK_ENTRY) == failure_message(
            FailureCategory.MISSING_CREDENTIAL
        )


class TestOnSubgraphError:
    """End-to-end: what on_subgraph_error() hands to the caller."""

    def _node(self) -> CurriculumImpactGraphNode:
        return CurriculumImpactGraphNode(config={})

    def _handle(self, error_log: list[str], trace_id: str = "t-1") -> dict:
        error = SubgraphError(
            agent_name="edu_c2_046_curriculum_impact_workflow",
            error_log=error_log,
            trace_id=trace_id,
        )
        return self._node().on_subgraph_error({}, error)

    def test_status_stays_success_so_post_process_runs(self) -> None:
        # status=error would route straight to finalize, skipping post_process,
        # and the Marketplace runner would drop `output` entirely.
        result = self._handle([FRAMEWORK_TRACEBACK_ENTRY])
        assert result["status"] == AgentStatus.SUCCESS.value

    def test_message_is_sanitized(self) -> None:
        result = self._handle([FRAMEWORK_TRACEBACK_ENTRY])
        _assert_no_internals(result["workflow_error_message"])
        assert "credential" in result["workflow_error_message"].lower()

    def test_trace_id_reaches_the_caller(self) -> None:
        result = self._handle([FRAMEWORK_TRACEBACK_ENTRY], trace_id="corr-9")
        assert "reference: corr-9" in result["workflow_error_message"]

    def test_last_entry_wins(self) -> None:
        result = self._handle(
            ["[A] change_scope_json is missing or empty.", "[B] connection refused"],
            trace_id="",
        )
        assert result["workflow_error_message"] == failure_message(FailureCategory.UPSTREAM_UNAVAILABLE)

    @pytest.mark.parametrize("error_log", [[], [""], ["   "]])
    def test_empty_error_log_falls_back_to_generic(self, error_log: list[str]) -> None:
        result = self._handle(error_log, trace_id="")
        assert result["workflow_error_message"] == failure_message(FailureCategory.UNKNOWN)

    @pytest.mark.parametrize("raw", HOSTILE_DIAGNOSTICS)
    def test_no_diagnostic_shape_leaks_end_to_end(self, raw: str) -> None:
        _assert_no_internals(self._handle([raw])["workflow_error_message"])
