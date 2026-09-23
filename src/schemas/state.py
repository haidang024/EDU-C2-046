"""State — flat TypedDict schema for EDU-C2-046 Curriculum Change Impact Briefing Agent."""

from __future__ import annotations

import json
from typing import Any

from framework.schemas.agent_state import AgentState


# ─── msgpack-safety helpers (MANDATORY — must be present in every state.py) ───


def to_json(value: Any) -> str:
    """Encode structured value to JSON string before storing in State."""
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str | None, default: Any = None) -> Any:
    """Decode JSON string from State back to structured value."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# ─── State schema ─────────────────────────────────────────────────────────────
# Rules:
#   - ALL fields must be primitives: str, int, float, bool, or None
#   - Structured data (dict, list) → JSON-encode with to_json(); declare field as str
#   - NEVER use: List[dict], dict, list, Optional[dict], Pydantic, dataclass
#   - NEVER store: JWT, API keys, InvocationContext, credentials
#
# Producer-consumer ownership:
#   change_scope_json        → PreProcessNode writes; inner nodes read
#   approved_source_ids_json → PreProcessNode writes; EvidenceRetrievalNode reads
#   curriculum_records_json  → EvidenceRetrievalNode writes; AffectedMaterialAnalysisNode reads
#   affected_materials_json  → AffectedMaterialAnalysisNode writes; StakeholderMappingNode reads
#   stakeholder_impacts_json → StakeholderMappingNode writes; BriefingHitlNode reads
#   communication_reqs_json  → StakeholderMappingNode writes; BriefingHitlNode reads
#   briefing_draft_json      → BriefingHitlNode writes (draft); PostProcessNode reads
#   citations_json           → BriefingHitlNode writes; PostProcessNode reads
#   review_outcome           → BriefingHitlNode writes on resume; PostProcessNode reads
#   review_correction        → BriefingHitlNode writes on corrected resume
#   formatted_output         → PostProcessNode writes; outer graph returns to caller


class State(AgentState):
    """Agent state for EDU-C2-046 — Curriculum Change Impact Briefing Agent.

    All shared fields (user_input, status, session_id, node_history,
    error_log, hitl_*, etc.) are inherited from AgentState.

    All structured fields are JSON-encoded strings (msgpack-safe).
    Use to_json() to write and from_json() to read structured fields.
    """

    # ── Input / scope ─────────────────────────────────────────────────────────
    # JSON-encoded dict: {subject_area, effective_date, institution_id, unit_ids,
    #                      change_type, change_description, change_reference}
    change_scope_json: str

    # JSON-encoded list[str]: approved source identifiers configured by the operator
    approved_source_ids_json: str

    # ── Evidence retrieval ────────────────────────────────────────────────────
    # JSON-encoded list[dict]: records from approved curriculum sources
    # Each record: {source_id, record_id, title, effective_date, content_summary,
    #               provenance_url, retrieved_at}
    curriculum_records_json: str
    # Which source answered: "live" when CURRICULUM_CONNECTOR_API_KEY is
    # provisioned, "fixture" when the bundled records were used.
    # Operator-facing only — the rendered briefing is identical either way.
    evidence_source: str | None
    stakeholder_source: str | None

    # ── Affected-material analysis ────────────────────────────────────────────
    # JSON-encoded list[dict]: affected course materials, assessments, resources
    # Each: {material_id, material_type, title, impacted_by, evidence_link,
    #        uncertainty, action_required}
    affected_materials_json: str

    # ── Stakeholder / communication mapping ───────────────────────────────────
    # JSON-encoded list[dict]: stakeholder groups and their impact
    # Each: {group_name, role, impact_description, source_citation, gap_flag}
    stakeholder_impacts_json: str

    # JSON-encoded list[dict]: communication considerations (NOT automated sends)
    # Each: {consideration, policy_citation, gap_flag}
    communication_reqs_json: str

    # ── Briefing & HITL ───────────────────────────────────────────────────────
    # JSON-encoded dict: the assembled impact briefing draft pending human review
    # Keys: {title, executive_summary, scope, affected_materials, stakeholder_impacts,
    #         communication_considerations, citations, limitations, generated_at}
    briefing_draft_json: str

    # JSON-encoded list[dict]: citation records for traceability
    # Each: {source_id, record_id, url, accessed_at}
    citations_json: str

    # String: "approved" | "corrected" | "rejected" — set by BriefingHitlNode on resume
    review_outcome: str

    # String: operator correction text when review_outcome == "corrected"
    review_correction: str

    # ── Output ────────────────────────────────────────────────────────────────
    # Final formatted impact briefing (JSON-encoded structured output)
    formatted_output: str
    input_error_message: str | None
    input_error_guidance: list[str]
    # Inner-workflow failure reason, carried as a domain field so the run keeps
    # a valid AgentStatus and still reaches post_process.
    workflow_error_message: str | None
    generation_mode: str | None
    provider_error_message: str | None
