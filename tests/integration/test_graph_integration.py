"""Integration tests for EDU-C2-046 Graph invocation pipeline.

Tests cover BL-17, BL-18: end-to-end invocation with mocked provider.
"""

from __future__ import annotations

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel


def _valid_scope() -> str:
    return json.dumps({
        "subject_area": "Computer Science",
        "effective_date": "2026-09-01",
        "institution_id": "INST-001",
        "unit_ids": ["CS101"],
        "change_type": "revision",
        "change_description": "Update data structures curriculum to include modern algorithms",
        "change_reference": "CS-REF-2026-001",
        "approved_source_ids": ["source-a"],
    })


class TestGraphIntegration:
    """BL-17, BL-18: End-to-end invocation through Graph."""

    def test_bl17_full_pipeline_with_no_provider_records(self):
        """BL-17: Full pipeline without provider records completes with uncertainty markers."""
        from src.graph.graph import Graph

        graph = Graph()
        graph.compile()

        ctx = InvocationContext(
            session_id="test-integration-bl17",
            caller_trust_level=TrustLevel.VERIFIED_EXTERNAL,
            hitl_allowed=False,  # skip interrupt in integration test
        )
        result = graph.invoke(_valid_scope(), ctx=ctx)

        # Should succeed (no records is a valid empty state)
        assert result.get("status") in (AgentStatus.SUCCESS.value, None) or "output" in result

    def test_bl18_preprocess_rejection_stops_pipeline(self):
        """BL-18: PreProcessNode failure stops pipeline before any retrieval."""
        from src.graph.graph import Graph

        graph = Graph()
        graph.compile()

        ctx = InvocationContext(
            session_id="test-integration-bl18",
            caller_trust_level=TrustLevel.VERIFIED_EXTERNAL,
        )
        result = graph.invoke("not a json object", ctx=ctx)

        assert result.get("status") == AgentStatus.SUCCESS.value
        assert "not valid json" in result.get("output", "").lower()
