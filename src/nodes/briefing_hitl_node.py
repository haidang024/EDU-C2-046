"""BriefingHitlNode — review-ready impact briefing assembly and HITL for EDU-C2-046."""

from __future__ import annotations

import datetime
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json


class BriefingHitlNode(FunctionNode):
    """Assemble factual impact briefing and request authorized human review.

    Inner DomainWorkflowGraph node (ANONYMOUS — trust already verified at boundary).

    Uses the D6 interrupt() pattern guarded by hitl_allowed. Supports approved,
    corrected, and rejected resume outcomes. Frames output as decision support
    only — not a curriculum approval or outbound communication.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Assemble the impact briefing and request human review via interrupt().

        On first call:
            Assembles the briefing from scope, affected materials, stakeholder impacts,
            communication requirements, and citations. Interrupts for human review if
            hitl_allowed is True, or returns the draft directly if False.

        On resume (hitl_draft already set):
            Reads hitl_feedback and routes: approved / corrected / rejected.
        """
        # ── Idempotency guard: resume path ────────────────────────────────────
        if state.get("hitl_draft"):
            return self._handle_resume(state)

        # ── First call: assemble briefing ─────────────────────────────────────
        scope = from_json(state.get("change_scope_json"), default={})
        affected_materials = from_json(state.get("affected_materials_json"), default=[])
        stakeholder_impacts = from_json(state.get("stakeholder_impacts_json"), default=[])
        communication_reqs = from_json(state.get("communication_reqs_json"), default=[])
        citations = from_json(state.get("citations_json"), default=[])

        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

        # Detect partial-result conditions
        has_gaps = (
            any(m.get("uncertainty", "").startswith("high") for m in affected_materials)
            or any(s.get("gap_flag") for s in stakeholder_impacts)
            or any(c.get("gap_flag") for c in communication_reqs)
        )

        limitations: list[str] = []
        if has_gaps:
            limitations.append(
                "One or more analysis sections contain evidence gaps. "
                "Human review should verify completeness before any decisions are made."
            )
        limitations.append(
            "This briefing is decision support only. "
            "It does not constitute approval of curriculum changes "
            "and does not initiate stakeholder communications."
        )

        briefing_draft = {
            "title": (
                f"Curriculum Change Impact Briefing — "
                f"{scope.get('subject_area', 'Unknown Area')} "
                f"({scope.get('effective_date', 'Unknown Date')})"
            ),
            "executive_summary": (
                f"A curriculum {scope.get('change_type', 'change')} has been proposed "
                f"for {scope.get('subject_area', 'the subject area')} "
                f"at institution {scope.get('institution_id', 'unknown')}, "
                f"effective {scope.get('effective_date', 'TBD')}. "
                f"Change: {scope.get('change_description', '')}. "
                f"{len(affected_materials)} material(s) identified as potentially affected."
            ),
            "scope": scope,
            "affected_materials": affected_materials,
            "stakeholder_impacts": stakeholder_impacts,
            "communication_considerations": communication_reqs,
            "citations": citations,
            "limitations": limitations,
            "generated_at": now,
        }

        emit_trace_event(
            "BriefingHitlNode_draft_assembled",
            {
                "subject_area": scope.get("subject_area", ""),
                "effective_date": scope.get("effective_date", ""),
                "institution_id": scope.get("institution_id", ""),
                "materials_count": len(affected_materials),
                "has_gaps": has_gaps,
                "hitl_allowed": state.get("hitl_allowed", True),
            },
            state,
        )

        # ── HITL interrupt (D6 pattern) ────────────────────────────────────────
        if state.get("hitl_allowed", True):
            from langgraph.types import interrupt  # local import avoids conftest stub conflict

            interrupt(
                {
                    "message": "Curriculum change impact briefing requires human review.",
                    "briefing_summary": briefing_draft["executive_summary"],
                    "has_gaps": has_gaps,
                    "action": "Please review the full briefing and respond: approve / correct / reject",
                }
            )
            # Execution resumes here after human feedback; hitl_draft is now set.

        # hitl_allowed=False path: return draft directly (no interrupt)
        return {
            "briefing_draft_json": to_json(briefing_draft),
            "hitl_draft": to_json(briefing_draft),
            "review_outcome": "approved",  # auto-approved when HITL bypassed
            "status": AgentStatus.SUCCESS.value,
        }

    # ── Resume handler ────────────────────────────────────────────────────────

    def _handle_resume(self, state: dict[str, Any]) -> dict[str, Any]:
        """Handle resume after human feedback.

        feedback may be a plain string ("approve" / "correct" / "reject")
        or a dict {"action": ..., "corrected_output": ..., "reason": ...}.
        """
        feedback = state.get("hitl_feedback") or {}

        if isinstance(feedback, str):
            action = feedback.strip().lower()
            corrected_output = ""
            reason = ""
        elif isinstance(feedback, dict):
            action = str(feedback.get("action", "")).strip().lower()
            corrected_output = str(feedback.get("corrected_output", ""))
            reason = str(feedback.get("reason", ""))
        else:
            action = "reject"
            corrected_output = ""
            reason = "Unrecognised feedback format."

        emit_trace_event(
            "BriefingHitlNode_review_received",
            {
                "action": action,
                "has_correction": bool(corrected_output),
                "has_reason": bool(reason),
            },
            state,
        )

        if action in ("approve", "approved"):
            return {
                "briefing_draft_json": state.get("hitl_draft", state.get("briefing_draft_json", "")),
                "review_outcome": "approved",
                "status": AgentStatus.SUCCESS.value,
            }

        if action in ("correct", "corrected"):
            return {
                "briefing_draft_json": state.get("hitl_draft", state.get("briefing_draft_json", "")),
                "review_outcome": "corrected",
                "review_correction": corrected_output,
                "status": AgentStatus.SUCCESS.value,
            }

        # reject / unknown
        return {
            "review_outcome": "rejected",
            "status": AgentStatus.ERROR.value,
            "error_log": state.get("error_log", [])
            + [f"BriefingHitlNode: briefing rejected by reviewer. Reason: {reason}"],
        }
