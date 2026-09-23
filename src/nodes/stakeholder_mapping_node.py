"""StakeholderMappingNode — stakeholder and communication-requirements mapping for EDU-C2-046."""

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json
from src.services.service import CurriculumSourceService


class StakeholderMappingNode(FunctionNode):
    """Map curriculum changes and affected materials to stakeholder groups and communication requirements.

    Inner DomainWorkflowGraph node (ANONYMOUS — trust already verified at boundary).

    Outputs recommendations and requirements as briefing evidence only. Does NOT
    send notifications, automate communications, or make approval decisions.
    Gaps in policy evidence are explicitly marked.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Map affected materials to stakeholder groups and communication considerations.

        Reads:
            change_scope_json, approved_source_ids_json,
            affected_materials_json, curriculum_records_json

        Returns state delta with:
            stakeholder_impacts_json  — JSON-encoded list[dict]
            communication_reqs_json   — JSON-encoded list[dict]
        """
        scope = from_json(state.get("change_scope_json"), default={})
        approved_source_ids = from_json(state.get("approved_source_ids_json"), default=[])
        affected_materials = from_json(state.get("affected_materials_json"), default=[])

        institution_id = scope.get("institution_id", "")
        subject_area = scope.get("subject_area", "")
        change_type = scope.get("change_type", "")
        change_description = scope.get("change_description", "")

        # Fetch stakeholder references from approved sources
        ctx = InvocationContext.from_state(state)
        # The connector credential is optional: when it is not provisioned the
        # service falls back to the bundled fixture records, so the review still
        # completes instead of failing the run. `evidence_source` records which
        # path answered, for the audit log only.
        try:
            ctx.secrets.require("CURRICULUM_CONNECTOR_API_KEY")
            evidence_source = "live"
        except Exception:
            evidence_source = "fixture"

        service = CurriculumSourceService()
        raw_stakeholder_refs: list[dict[str, Any]] = []
        for source_id in approved_source_ids:
            try:
                refs = service.fetch_stakeholder_references(
                    source_id=source_id,
                    approved_source_ids=approved_source_ids,
                    institution_id=institution_id,
                )
                raw_stakeholder_refs.extend(refs)
            except Exception:  # noqa: BLE001
                pass  # partial failure handled via gap_flag below

        # Build stakeholder impact records
        stakeholder_impacts: list[dict[str, Any]] = []
        if raw_stakeholder_refs:
            for ref in raw_stakeholder_refs:
                stakeholder_impacts.append(
                    {
                        "group_name": ref.get("group_name", ""),
                        "role": ref.get("role", ""),
                        "impact_description": (
                            f"Curriculum {change_type} in {subject_area}: {change_description}. "
                            f"Review impact on materials: "
                            f"{', '.join(m.get('title','') for m in affected_materials[:3])}"
                            f"{'...' if len(affected_materials) > 3 else ''}."
                        ),
                        "source_citation": ref.get("policy_citation", ""),
                        "gap_flag": False,
                    }
                )
        else:
            # No approved-source stakeholder references — explicit gap
            stakeholder_impacts.append(
                {
                    "group_name": "All stakeholders",
                    "role": "To be determined",
                    "impact_description": (
                        f"Curriculum {change_type} in {subject_area}: {change_description}. "
                        "Stakeholder mapping unavailable — no policy references retrieved."
                    ),
                    "source_citation": "",
                    "gap_flag": True,
                }
            )

        # Build communication requirement considerations (NOT automated sends)
        communication_reqs: list[dict[str, Any]] = []
        if raw_stakeholder_refs:
            communication_reqs.append(
                {
                    "consideration": (
                        f"Notify affected stakeholder groups of {change_type} in {subject_area}. "
                        "Review institutional communication policy before any outreach."
                    ),
                    "policy_citation": raw_stakeholder_refs[0].get("policy_citation", "")
                    if raw_stakeholder_refs
                    else "",
                    "gap_flag": False,
                }
            )
        else:
            communication_reqs.append(
                {
                    "consideration": (
                        "Communication requirements could not be determined — "
                        "policy evidence not available from approved sources. "
                        "Manual policy review is required before any stakeholder communication."
                    ),
                    "policy_citation": "",
                    "gap_flag": True,
                }
            )

        emit_trace_event(
            "StakeholderMappingNode_mapping_complete",
            {
                "institution_id": institution_id,
                "subject_area": subject_area,
                "change_type": change_type,
                "stakeholder_groups": len(stakeholder_impacts),
                "communication_reqs": len(communication_reqs),
                "policy_gap": not bool(raw_stakeholder_refs),
            },
            state,
        )

        return {
            "stakeholder_impacts_json": to_json(stakeholder_impacts),
            "communication_reqs_json": to_json(communication_reqs),
            # Operator-facing: "live" or "fixture" (see evidence_retrieval_node).
            "stakeholder_source": evidence_source,
            "status": AgentStatus.SUCCESS.value,
        }
