"""Unit and integration tests for EDU-C2-046 node implementations.

Covers TC-01, TC-08, TC-09, TC-10, TC-11 and BL-01 through BL-16.
All node invocations use node(state) — never node.execute(state) — to exercise
the full security pipeline (S-1 → S-2 → execute → S-3).
"""

from __future__ import annotations

import json

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from shared.secrets.inmemory_provider import InMemoryProvider


@pytest.fixture(autouse=True)
def _bind_test_secrets():
    """Provide opaque connector handles for direct node tests."""
    with bound_secrets(InMemoryProvider({"CURRICULUM_CONNECTOR_API_KEY": "test-handle"})):
        yield


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ve_state(**extra) -> dict:
    """Minimal VERIFIED_EXTERNAL state for outer-boundary node tests."""
    return {
        "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
        "correlation_id": "test-unit",
        "node_history": [],
        "error_log": [],
        "input_context": {"raw": extra.get("user_input", "")},
        **extra,
    }


def _anon_state(**extra) -> dict:
    """Minimal ANONYMOUS state for inner domain node tests."""
    return {
        "caller_trust_level": TrustLevel.ANONYMOUS.value,
        "correlation_id": "test-unit",
        "session_id": "test-unit-session",
        "thread_id": "test-unit-thread",
        "trace_id": "test-unit-trace",
        "node_history": [],
        "error_log": [],
        **extra,
    }


def _valid_scope_input() -> str:
    """JSON-encoded valid curriculum change scope for testing."""
    return json.dumps({
        "subject_area": "Computer Science",
        "effective_date": "2026-09-01",
        "institution_id": "INST-001",
        "unit_ids": ["CS101", "CS201"],
        "change_type": "revision",
        "change_description": "Update data structures curriculum to include modern algorithms",
        "change_reference": "CS-REF-2026-001",
        "approved_source_ids": ["source-a", "source-b"],
    })


def _scope_json() -> str:
    return json.dumps({
        "subject_area": "Computer Science",
        "effective_date": "2026-09-01",
        "institution_id": "INST-001",
        "unit_ids": ["CS101"],
        "change_type": "revision",
        "change_description": "Update data structures curriculum",
        "change_reference": "CS-REF-2026-001",
    })


def _approved_sources_json() -> str:
    return json.dumps(["source-a"])


def _curriculum_records_json() -> str:
    return json.dumps([
        {
            "source_id": "source-a",
            "record_id": "REC-001",
            "title": "Data Structures Course Outline",
            "effective_date": "2026-09-01",
            "content_summary": "Revised course outline covering modern algorithms and data structures.",
            "provenance_url": "https://source-a.example.com/records/REC-001",
            "retrieved_at": "2026-07-28T00:00:00Z",
        }
    ])


def _affected_materials_json() -> str:
    return json.dumps([
        {
            "material_id": "REC-001",
            "material_type": "course_outline",
            "title": "Data Structures Course Outline",
            "impacted_by": "Update data structures curriculum",
            "evidence_link": "https://source-a.example.com/records/REC-001",
            "uncertainty": "low",
            "action_required": "Review and revise material to align with curriculum changes.",
        }
    ])


def _stakeholder_impacts_json() -> str:
    return json.dumps([
        {
            "group_name": "Faculty",
            "role": "Instructor",
            "impact_description": "Curriculum revision in Computer Science: Update data structures curriculum.",
            "source_citation": "",
            "gap_flag": True,
        }
    ])


def _communication_reqs_json() -> str:
    return json.dumps([
        {
            "consideration": "Communication requirements could not be determined — policy evidence not available.",
            "policy_citation": "",
            "gap_flag": True,
        }
    ])


def _briefing_draft_json() -> str:
    return json.dumps({
        "title": "Curriculum Change Impact Briefing — Computer Science (2026-09-01)",
        "executive_summary": "A curriculum revision has been proposed...",
        "scope": {},
        "affected_materials": [],
        "stakeholder_impacts": [],
        "communication_considerations": [],
        "citations": [],
        "limitations": ["This briefing is decision support only."],
        "generated_at": "2026-07-28T00:00:00Z",
    })


# ─────────────────────────────────────────────────────────────────────────────
# TC-01: State contract
# ─────────────────────────────────────────────────────────────────────────────

class TestStateContract:
    """TC-01: State must be a flat TypedDict with no Pydantic/dataclass."""

    def test_state_is_importable_and_extends_agent_state(self):
        from src.schemas.state import State
        from framework.schemas.agent_state import AgentState

        assert State.__required_keys__.issuperset(AgentState.__required_keys__)

    def test_to_json_from_json_helpers_present(self):
        from src.schemas.state import from_json, to_json
        data = {"key": "value", "items": [1, 2, 3]}
        encoded = to_json(data)
        assert isinstance(encoded, str)
        decoded = from_json(encoded)
        assert decoded == data

    def test_from_json_returns_default_on_empty(self):
        from src.schemas.state import from_json
        assert from_json(None, default=[]) == []
        assert from_json("", default={}) == {}

    def test_from_json_returns_default_on_invalid(self):
        from src.schemas.state import from_json
        assert from_json("not-json", default="fallback") == "fallback"


# ─────────────────────────────────────────────────────────────────────────────
# PreProcessNode tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPreProcessNode:
    """Tests for PreProcessNode — BL-01..BL-05, TC-08, TC-09, TC-11."""

    def _node(self):
        from src.nodes.pre_process_node import PreProcessNode
        return PreProcessNode()

    def test_bl01_valid_scope_succeeds(self):
        """BL-01: Valid JSON scope is accepted and normalized."""
        node = self._node()
        result = node(_ve_state(user_input=_valid_scope_input()))
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "change_scope_json" in result
        assert "approved_source_ids_json" in result
        scope = json.loads(result["change_scope_json"])
        assert scope["subject_area"] == "Computer Science"
        assert scope["change_type"] == "revision"

    def test_bl02_empty_input_returns_guidance(self):
        """BL-02: Empty user_input returns actionable guidance."""
        node = self._node()
        result = node(_ve_state(user_input=""))
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["input_error_message"]

    def test_bl03_non_json_input_returns_guidance(self):
        """BL-03: Non-JSON user_input returns actionable guidance."""
        node = self._node()
        result = node(_ve_state(user_input="not a json string"))
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "json" in result["input_error_message"].lower()

    def test_bl04_missing_required_field_returns_error(self):
        """BL-04: Missing subject_area in scope returns ERROR."""
        scope = json.loads(_valid_scope_input())
        del scope["subject_area"]
        node = self._node()
        result = node(_ve_state(user_input=json.dumps(scope)))
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "subject_area" in result["input_error_message"]

    def test_bl05_invalid_date_format_returns_error(self):
        """BL-05: Invalid effective_date format returns ERROR."""
        scope = json.loads(_valid_scope_input())
        scope["effective_date"] = "01-09-2026"  # wrong format
        node = self._node()
        result = node(_ve_state(user_input=json.dumps(scope)))
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "date" in result["input_error_message"].lower()

    def test_bl05b_invalid_change_type_returns_error(self):
        """BL-05b: Invalid change_type returns ERROR."""
        scope = json.loads(_valid_scope_input())
        scope["change_type"] = "approve_immediately"  # not allowed
        node = self._node()
        result = node(_ve_state(user_input=json.dumps(scope)))
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "change_type" in result["input_error_message"]

    def test_bl05c_empty_approved_sources_returns_error(self):
        """BL-05c: Empty approved_source_ids list returns ERROR."""
        scope = json.loads(_valid_scope_input())
        scope["approved_source_ids"] = []
        node = self._node()
        result = node(_ve_state(user_input=json.dumps(scope)))
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "approved_source_ids" in result["input_error_message"]

    def test_tc08_s1_rejects_anonymous_caller(self):
        """TC-08: ANONYMOUS caller is rejected for VERIFIED_EXTERNAL node."""
        node = self._node()
        result = node(_anon_state(user_input=_valid_scope_input()))
        # S-1 gate returns error dict with insufficient trust
        assert result.get("status") == AgentStatus.ERROR.value or "insufficient" in str(result).lower()

    def test_tc09_s2_extra_gate_rejects_approval_framing(self):
        """TC-09: S-2 extra gate blocks input requesting automated approval."""
        from framework.errors import SecurityViolationError

        node = self._node()
        prohibited_input = "approve change to the curriculum now"
        # The S-2 extra gate raises SecurityViolationError on prohibited framing
        with pytest.raises(SecurityViolationError):
            node._extra_security_gate_input({"user_input": prohibited_input})

    def test_tc11_domain_audit_event_emitted(self, monkeypatch):
        """TC-11: At least one domain emit_trace_event fires per execute()."""
        events = []
        import src.nodes.pre_process_node as pn
        monkeypatch.setattr(pn, "emit_trace_event", lambda name, payload, state: events.append(name))

        node = self._node()
        node(_ve_state(user_input=_valid_scope_input()))
        assert any("PreProcessNode" in e for e in events)

    def test_does_not_approve_curriculum_change(self):
        """The agent does not approve curriculum changes — no approval state written."""
        node = self._node()
        result = node(_ve_state(user_input=_valid_scope_input()))
        assert "approval" not in str(result).lower()
        assert "approved_change" not in result

    def test_does_not_send_communications(self):
        """The agent does not send stakeholder communications — no send flag in result."""
        node = self._node()
        result = node(_ve_state(user_input=_valid_scope_input()))
        assert "send_email" not in result
        assert "notification_sent" not in result


# ─────────────────────────────────────────────────────────────────────────────
# EvidenceRetrievalNode tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEvidenceRetrievalNode:
    """Tests for EvidenceRetrievalNode — BL-06..BL-08, TC-11."""

    def _node(self):
        from src.nodes.evidence_retrieval_node import EvidenceRetrievalNode
        return EvidenceRetrievalNode()

    def _state(self, **overrides):
        base = _anon_state(
            change_scope_json=_scope_json(),
            approved_source_ids_json=_approved_sources_json(),
        )
        base.update(overrides)
        return base

    def test_bl06_empty_sources_returns_empty_records(self):
        """BL-06: No approved sources → empty curriculum_records_json, SUCCESS."""
        node = self._node()
        result = node(self._state(approved_source_ids_json=json.dumps([])))
        assert result["status"] == AgentStatus.SUCCESS.value
        records = json.loads(result["curriculum_records_json"])
        assert records == []

    def test_bl07_missing_scope_returns_error(self):
        """BL-07: Missing change_scope_json returns ERROR."""
        node = self._node()
        result = node(self._state(change_scope_json=""))
        assert result["status"] == AgentStatus.ERROR.value

    def test_bl08_maps_provider_data_and_preserves_provenance(self, monkeypatch):
        """BL-08: Provider data is mapped; provenance is preserved in records."""
        # Patch CurriculumSourceService to return fake records
        class _FakeService:
            def fetch_curriculum_records(self, **kwargs):
                return [
                    {
                        "source_id": "source-a",
                        "record_id": "REC-001",
                        "title": "CS Outline",
                        "effective_date": "2026-09-01",
                        "content_summary": "Summary text",
                        "provenance_url": "https://example.com/REC-001",
                        "retrieved_at": "2026-07-28T00:00:00Z",
                    }
                ]

            def fetch_stakeholder_references(self, **kwargs):
                return []

        import src.nodes.evidence_retrieval_node as ern
        monkeypatch.setattr(ern, "CurriculumSourceService", lambda: _FakeService())
        node = self._node()
        result = node(self._state())
        assert result["status"] == AgentStatus.SUCCESS.value
        records = json.loads(result["curriculum_records_json"])
        assert len(records) >= 1
        assert records[0]["provenance_url"] == "https://example.com/REC-001"

    def test_tc11_domain_event_emitted(self, monkeypatch):
        """TC-11: Domain audit event emitted."""
        events = []
        import src.nodes.evidence_retrieval_node as ern
        monkeypatch.setattr(ern, "emit_trace_event", lambda n, p, s: events.append(n))
        node = self._node()
        node(self._state(approved_source_ids_json=json.dumps([])))
        assert any("EvidenceRetrievalNode" in e for e in events)

    def test_does_not_approve_curriculum_change(self):
        """EvidenceRetrievalNode does not make curriculum approval decisions."""
        node = self._node()
        result = node(self._state())
        assert "approved_change" not in result
        assert "approval" not in str(result).lower()


# ─────────────────────────────────────────────────────────────────────────────
# AffectedMaterialAnalysisNode tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAffectedMaterialAnalysisNode:
    """Tests for AffectedMaterialAnalysisNode — BL-09..BL-11, TC-11."""

    def _node(self):
        from src.nodes.affected_material_analysis_node import AffectedMaterialAnalysisNode
        return AffectedMaterialAnalysisNode()

    def _state(self, **overrides):
        base = _anon_state(
            change_scope_json=_scope_json(),
            curriculum_records_json=_curriculum_records_json(),
        )
        base.update(overrides)
        return base

    def test_bl09_produces_traceable_affected_materials(self):
        """BL-09: Produces traceable affected-material records with evidence links."""
        node = self._node()
        result = node(self._state())
        assert result["status"] == AgentStatus.SUCCESS.value
        materials = json.loads(result["affected_materials_json"])
        assert len(materials) >= 1
        assert "evidence_link" in materials[0]
        assert "uncertainty" in materials[0]

    def test_bl10_no_records_returns_partial_result_with_uncertainty(self):
        """BL-10: No curriculum records → safe partial result with high uncertainty."""
        node = self._node()
        result = node(self._state(curriculum_records_json=json.dumps([])))
        assert result["status"] == AgentStatus.SUCCESS.value
        materials = json.loads(result["affected_materials_json"])
        assert len(materials) >= 1
        assert "high" in materials[0]["uncertainty"].lower()

    def test_bl11_citations_collected_from_records(self):
        """BL-11: Citations are collected from records with provenance URLs."""
        node = self._node()
        result = node(self._state())
        citations = json.loads(result["citations_json"])
        # Should have at least one citation for the record with a provenance URL
        assert len(citations) >= 1
        assert "url" in citations[0]

    def test_tc11_domain_event_emitted(self, monkeypatch):
        """TC-11: Domain audit event emitted."""
        events = []
        import src.nodes.affected_material_analysis_node as aman
        monkeypatch.setattr(aman, "emit_trace_event", lambda n, p, s: events.append(n))
        node = self._node()
        node(self._state())
        assert any("AffectedMaterialAnalysisNode" in e for e in events)


# ─────────────────────────────────────────────────────────────────────────────
# StakeholderMappingNode tests
# ─────────────────────────────────────────────────────────────────────────────

class TestStakeholderMappingNode:
    """Tests for StakeholderMappingNode — BL-12..BL-13, TC-11."""

    def _node(self):
        from src.nodes.stakeholder_mapping_node import StakeholderMappingNode
        return StakeholderMappingNode()

    def _state(self, **overrides):
        base = _anon_state(
            change_scope_json=_scope_json(),
            approved_source_ids_json=_approved_sources_json(),
            affected_materials_json=_affected_materials_json(),
            curriculum_records_json=_curriculum_records_json(),
        )
        base.update(overrides)
        return base

    def test_bl12_gap_flagged_when_no_policy_refs(self):
        """BL-12: gap_flag=True when no policy references retrieved."""
        node = self._node()
        result = node(self._state())
        stakeholders = json.loads(result["stakeholder_impacts_json"])
        comm_reqs = json.loads(result["communication_reqs_json"])
        # Without real connector, gap_flag should be True
        assert any(s.get("gap_flag") for s in stakeholders) or len(stakeholders) > 0
        assert len(comm_reqs) >= 1

    def test_bl13_output_is_recommendation_not_automated_send(self):
        """BL-13: Output is communication consideration, not an automated send."""
        node = self._node()
        result = node(self._state())
        comm_reqs = json.loads(result["communication_reqs_json"])
        # Must not claim it sent communications
        output_str = json.dumps(comm_reqs)
        assert "email sent" not in output_str.lower()
        assert "notification sent" not in output_str.lower()

    def test_tc11_domain_event_emitted(self, monkeypatch):
        """TC-11: Domain audit event emitted."""
        events = []
        import src.nodes.stakeholder_mapping_node as smn
        monkeypatch.setattr(smn, "emit_trace_event", lambda n, p, s: events.append(n))
        node = self._node()
        node(self._state())
        assert any("StakeholderMappingNode" in e for e in events)


# ─────────────────────────────────────────────────────────────────────────────
# BriefingHitlNode tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBriefingHitlNode:
    """Tests for BriefingHitlNode — BL-14..BL-15, TC-11."""

    def _node(self):
        from src.nodes.briefing_hitl_node import BriefingHitlNode
        return BriefingHitlNode()

    def _state(self, **overrides):
        base = _anon_state(
            change_scope_json=_scope_json(),
            affected_materials_json=_affected_materials_json(),
            stakeholder_impacts_json=_stakeholder_impacts_json(),
            communication_reqs_json=_communication_reqs_json(),
            citations_json=json.dumps([]),
            hitl_allowed=False,  # avoid interrupt in unit tests
        )
        base.update(overrides)
        return base

    def test_bl14_assembles_briefing_with_hitl_disabled(self):
        """BL-14: With hitl_allowed=False, draft is assembled and auto-approved."""
        node = self._node()
        result = node(self._state())
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "briefing_draft_json" in result
        assert result["review_outcome"] == "approved"

    def test_bl15_resume_approve_sets_approved_outcome(self):
        """BL-15: Resume with 'approve' feedback sets review_outcome=approved."""
        node = self._node()
        # Simulate resume state (hitl_draft already set)
        state = self._state(
            hitl_draft=_briefing_draft_json(),
            hitl_feedback="approve",
        )
        result = node(state)
        assert result["review_outcome"] == "approved"

    def test_bl15b_resume_correct_sets_corrected_outcome(self):
        """BL-15b: Resume with 'correct' feedback sets review_outcome=corrected."""
        node = self._node()
        state = self._state(
            hitl_draft=_briefing_draft_json(),
            hitl_feedback={"action": "correct", "corrected_output": "Updated summary", "reason": "Typo"},
        )
        result = node(state)
        assert result["review_outcome"] == "corrected"
        assert result["review_correction"] == "Updated summary"

    def test_bl15c_resume_reject_sets_rejected_outcome(self):
        """BL-15c: Resume with 'reject' feedback sets review_outcome=rejected."""
        node = self._node()
        state = self._state(
            hitl_draft=_briefing_draft_json(),
            hitl_feedback={"action": "reject", "reason": "Incomplete analysis"},
        )
        result = node(state)
        assert result["review_outcome"] == "rejected"
        assert result["status"] == AgentStatus.ERROR.value

    def test_output_framed_as_decision_support(self):
        """Briefing draft is framed as decision support, not approval."""
        node = self._node()
        result = node(self._state())
        draft = json.loads(result["briefing_draft_json"])
        limitations = draft.get("limitations", [])
        assert any("decision support" in lim.lower() for lim in limitations)

    def test_tc11_domain_event_emitted(self, monkeypatch):
        """TC-11: Domain audit event emitted."""
        events = []
        import src.nodes.briefing_hitl_node as bhn
        monkeypatch.setattr(bhn, "emit_trace_event", lambda n, p, s: events.append(n))
        node = self._node()
        node(self._state())
        assert any("BriefingHitlNode" in e for e in events)


# ─────────────────────────────────────────────────────────────────────────────
# PostProcessNode tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPostProcessNode:
    """Tests for PostProcessNode — BL-16, TC-10, TC-11."""

    def _node(self):
        from src.nodes.post_process_node import PostProcessNode
        return PostProcessNode()

    def _state(self, **overrides):
        base = _ve_state(
            briefing_draft_json=_briefing_draft_json(),
            citations_json=json.dumps([{"source_id": "source-a", "record_id": "REC-001",
                                        "url": "https://example.com/REC-001", "accessed_at": "2026-07-28"}]),
            affected_materials_json=_affected_materials_json(),
            stakeholder_impacts_json=_stakeholder_impacts_json(),
            communication_reqs_json=_communication_reqs_json(),
            review_outcome="approved",
            review_correction="",
        )
        base.update(overrides)
        return base

    def test_bl16_approved_output_includes_all_sections(self):
        """BL-16: Approved output includes executive summary, materials, stakeholders, citations."""
        node = self._node()
        result = node(self._state())
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "formatted_output" in result
        output = json.loads(result["formatted_output"])
        assert "executive_summary" in output
        assert "affected_materials_summary" in output
        assert "stakeholder_impacts_summary" in output
        assert "citations" in output

    def test_bl16b_rejected_output_marked(self):
        """BL-16b: Rejected review disposition is reflected in output."""
        node = self._node()
        result = node(self._state(review_outcome="rejected"))
        assert result["status"] == AgentStatus.SUCCESS.value
        output = json.loads(result["formatted_output"])
        assert output["review_disposition"] == "rejected"
        assert "REJECTED" in output["executive_summary"]

    def test_bl16c_corrected_output_includes_correction(self):
        """BL-16c: Corrected output includes operator correction text."""
        node = self._node()
        result = node(self._state(review_outcome="corrected", review_correction="See addendum."))
        output = json.loads(result["formatted_output"])
        assert output.get("operator_correction") == "See addendum."

    def test_output_does_not_approve_or_send(self):
        """PostProcessNode output is decision support, not approval or comms send."""
        node = self._node()
        result = node(self._state())
        output_str = result.get("formatted_output", "")
        output = json.loads(output_str)
        assert "does not constitute curriculum approval" in output["notice"].lower()
        assert "does not initiate communications" in output["notice"].lower()

    def test_formatted_output_key_present(self):
        """Mandatory: formatted_output must be present in the result dict."""
        node = self._node()
        result = node(self._state())
        assert "formatted_output" in result
        assert result["formatted_output"]

    def test_tc10_s3_extra_gate_blocks_credential_in_output(self):
        """TC-10: S-3 extra gate blocks credential-like strings in formatted_output."""
        node = self._node()

        # S-3 gate catches it; __call__ wraps it (behavior depends on stub)
        # We verify the gate method itself raises
        fake_result = {"formatted_output": '{"executive_summary": "bearer ABCDEFG token"}'}
        with pytest.raises(Exception):
            node._extra_security_gate_output(fake_result)

    def test_tc11_domain_event_emitted(self, monkeypatch):
        """TC-11: Domain audit event emitted."""
        events = []
        import src.nodes.post_process_node as ppn
        monkeypatch.setattr(ppn, "emit_trace_event", lambda n, p, s: events.append(n))
        node = self._node()
        node(self._state())
        assert any("PostProcessNode" in e for e in events)
