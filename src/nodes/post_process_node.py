"""PostProcessNode — traceable output post-processing for EDU-C2-046."""

from __future__ import annotations

from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.llm_runtime import provider_metadata, request_advisory
from src.schemas.state import from_json, to_json


class PostProcessNode(FunctionNode):
    """Prepare the final review disposition, impact summary, and traceable output.

    Outer pipeline node (VERIFIED_EXTERNAL — outer trust boundary).

    Retains sufficient provenance for operator verification and audit.
    Never exposes credentials or raw restricted provider payloads.
    Adds domain output validation via _extra_security_gate_output().
    """

    # Outer post-process node — VERIFIED_EXTERNAL (outer backbone, not inner graph)
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """S-3 extension: ensure formatted_output does not contain credential patterns.

        Raises:
            SecurityViolationError: if any credential-like string is detected in output.

        Returns:
            result (unchanged) on the non-error path.
        """
        import re

        output_str = str(result.get("formatted_output", ""))
        # Check for patterns that look like API keys or bearer tokens in the output
        if re.search(r"(api[_-]?key|bearer\s+[A-Za-z0-9\-._~+/]+=*)", output_str, re.IGNORECASE):
            raise SecurityViolationError(
                "PostProcessNode: formatted_output appears to contain credential material. " "Output rejected."
            )
        return result

    def __init__(self, llm: object | None = None, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._llm = llm
        self._config = config or {}

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Assemble and return the final traceable impact briefing output.

        Reads:
            briefing_draft_json, citations_json, affected_materials_json,
            stakeholder_impacts_json, communication_reqs_json,
            review_outcome, review_correction

        Returns state delta with:
            formatted_output — JSON-encoded structured briefing output
            result           — same as formatted_output (for API response)
        """
        if state.get("input_error_message"):
            message = str(state["input_error_message"])
            return {"status": AgentStatus.SUCCESS.value, "result": message, "formatted_output": message}

        request_advisory(
            state,
            "Review the EDU-C2-046 result for clarity, grounding, and safe human review.",
            self._llm,
            timeout_s=float(self._config.get("timeout_s", 30.0)),
            max_retry=int(self._config.get("max_retry", 3)),
        )
        metadata = provider_metadata(state)
        review_outcome = state.get("review_outcome", "")
        briefing_draft = from_json(state.get("briefing_draft_json"), default={})
        citations = from_json(state.get("citations_json"), default=[])
        affected_materials = from_json(state.get("affected_materials_json"), default=[])
        stakeholder_impacts = from_json(state.get("stakeholder_impacts_json"), default=[])
        communication_reqs = from_json(state.get("communication_reqs_json"), default=[])
        review_correction = state.get("review_correction", "")

        # Build the final structured output
        final_output: dict[str, Any] = {
            "agent": "EDU-C2-046",
            "title": briefing_draft.get("title", "Curriculum Change Impact Briefing"),
            "review_disposition": review_outcome or "pending",
            "executive_summary": briefing_draft.get("executive_summary", ""),
            "scope": briefing_draft.get("scope", {}),
            "affected_materials_summary": {
                "count": len(affected_materials),
                "items": affected_materials,
            },
            "stakeholder_impacts_summary": {
                "count": len(stakeholder_impacts),
                "items": stakeholder_impacts,
            },
            "communication_considerations": communication_reqs,
            "citations": citations,
            "limitations": briefing_draft.get("limitations", []),
            "generated_at": briefing_draft.get("generated_at", ""),
            "notice": (
                "This output is decision support only. "
                "It does not constitute curriculum approval and does not initiate communications."
            ),
        }

        # Inner workflow failed (e.g. an unavailable credential or connector).
        # Report it on a SUCCESS envelope: the Marketplace runner only forwards
        # `output` when status == "success", so status=error would leave the
        # caller with no reason at all.
        if state.get("workflow_error_message"):
            reason = str(state["workflow_error_message"])
            message = (
                "The curriculum change impact review could not be completed.\n\n"
                f"Reason: {reason}\n\n"
                "How to continue:\n"
                "- Confirm the agent's required credentials are provisioned in this environment.\n"
                "- Verify the upstream services this agent depends on are reachable.\n"
                "- Retry once the issue above is resolved, or contact your administrator."
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "result": message,
                "formatted_output": message,
            }

        # Incorporate operator correction when review outcome is 'corrected'
        if review_outcome == "corrected" and review_correction:
            final_output["operator_correction"] = review_correction

        # Handle rejected outcome: keep provenance but mark as rejected
        if review_outcome == "rejected":
            final_output["executive_summary"] = "[REJECTED BY REVIEWER] " + final_output["executive_summary"]

        emit_trace_event(
            "PostProcessNode_output_prepared",
            {
                "review_disposition": review_outcome,
                "materials_count": len(affected_materials),
                "stakeholders_count": len(stakeholder_impacts),
                "citations_count": len(citations),
                "has_correction": bool(review_correction),
            },
            state,
        )

        formatted = to_json(final_output)

        return {
            "formatted_output": formatted,
            "result": formatted,
            "status": AgentStatus.SUCCESS.value,
            **metadata,
        }
