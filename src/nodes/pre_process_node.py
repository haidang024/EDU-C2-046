"""PreProcessNode — change-scope validation and normalization for EDU-C2-046."""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import to_json


class PreProcessNode(FunctionNode):
    """Validate and normalize curriculum-change scope before any retrieval.

    Outer pipeline (trust boundary) node. Validates change scope, effective dates,
    institution/unit filters, and approved source identifiers from user_input.
    Does NOT approve curriculum changes or retrieve records.
    """

    # S-1: outer boundary node — VERIFIED_EXTERNAL (trust-trap avoided by keeping
    # inner DomainWorkflowGraph nodes at ANONYMOUS).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    # ISO-8601 date pattern for effective_date validation
    _DATE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    # Allowed change type values
    _ALLOWED_CHANGE_TYPES: ClassVar[frozenset[str]] = frozenset({"addition", "removal", "revision", "restructure"})

    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-2 extension: domain-specific input validation for curriculum scope.

        Checks:
        - user_input is non-empty
        - Content does not exceed maximum allowed length (4096 chars)
        - Framing check: input must not request automated approvals or communications

        Returns:
            state (unchanged) on the non-error path.

        Raises:
            SecurityViolationError: on prohibited request framing.
        """
        raw = state.get("user_input", "") or ""
        if len(raw) > 4096:
            raise SecurityViolationError("PreProcessNode: user_input exceeds maximum length of 4096 characters.")
        # Guard: the agent produces decision-support briefings only; it must not
        # be used to automate approvals or send communications.
        lower = raw.lower()
        if any(phrase in lower for phrase in ("approve change", "send email", "send notification", "publish to")):
            raise SecurityViolationError(
                "PreProcessNode: request contains prohibited framing — this agent "
                "produces impact briefings only; it does not approve curriculum changes "
                "or send communications."
            )
        return state

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize the curriculum-change scope from user_input.

        Expects user_input to be a JSON-encoded dict with keys:
            subject_area (str, required)
            effective_date (str, ISO-8601, required)
            institution_id (str, required)
            unit_ids (list[str], optional)
            change_type (str, required)
            change_description (str, required)
            change_reference (str, optional)
            approved_source_ids (list[str], required)

        Returns:
            State delta with change_scope_json, approved_source_ids_json, validated_input.
        """
        input_context = state.get("input_context", {})
        raw_input = input_context.get("raw") if isinstance(input_context, dict) else None
        user_input = raw_input if isinstance(raw_input, str) else state.get("user_input", "")

        if not user_input or not user_input.strip():
            emit_trace_event(
                "PreProcessNode_validation_failed",
                {"reason": "empty_input"},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": "No curriculum change scope was provided.",
                "input_error_guidance": [
                    "Provide a JSON object with subject_area, effective_date, institution_id, change_type, change_description, and approved_source_ids.",
                    "Use YYYY-MM-DD for effective_date.",
                ],
            }

        # Parse JSON input
        try:
            scope = json.loads(user_input)
        except (json.JSONDecodeError, TypeError):
            emit_trace_event(
                "PreProcessNode_validation_failed",
                {"reason": "json_parse_error"},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": "The curriculum change scope is not valid JSON.",
                "input_error_guidance": ["Provide a complete JSON object with the curriculum scope fields."],
            }

        if not isinstance(scope, dict):
            emit_trace_event(
                "PreProcessNode_validation_failed",
                {"reason": "not_a_dict"},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": "The curriculum change scope must be a JSON object.",
                "input_error_guidance": [
                    "Provide subject_area, effective_date, institution_id, change_type, change_description, and approved_source_ids."
                ],
            }

        # Validate required fields
        errors: list[str] = []

        subject_area = scope.get("subject_area", "").strip()
        if not subject_area:
            errors.append("subject_area is required and must be non-empty.")

        effective_date = scope.get("effective_date", "").strip()
        if not effective_date:
            errors.append("effective_date is required.")
        elif not self._DATE_PATTERN.match(effective_date):
            errors.append(f"effective_date '{effective_date}' is not a valid ISO-8601 date (YYYY-MM-DD).")

        institution_id = scope.get("institution_id", "").strip()
        if not institution_id:
            errors.append("institution_id is required and must be non-empty.")

        change_type = scope.get("change_type", "").strip().lower()
        if not change_type:
            errors.append("change_type is required.")
        elif change_type not in self._ALLOWED_CHANGE_TYPES:
            errors.append(
                f"change_type '{change_type}' is not allowed. " f"Allowed: {sorted(self._ALLOWED_CHANGE_TYPES)}"
            )

        change_description = scope.get("change_description", "").strip()
        if not change_description:
            errors.append("change_description is required and must be non-empty.")

        approved_source_ids = scope.get("approved_source_ids", [])
        if not isinstance(approved_source_ids, list) or not approved_source_ids:
            errors.append("approved_source_ids must be a non-empty list of source identifiers.")

        if errors:
            emit_trace_event(
                "PreProcessNode_validation_failed",
                {"errors": errors},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": "The curriculum change scope failed validation: " + "; ".join(errors),
                "input_error_guidance": [
                    "Use addition, removal, revision, or restructure for change_type.",
                    "Include at least one approved source identifier.",
                ],
            }

        # Build normalized scope dict (no credentials, no restricted content)
        normalized_scope = {
            "subject_area": subject_area,
            "effective_date": effective_date,
            "institution_id": institution_id,
            "unit_ids": [u for u in scope.get("unit_ids", []) if isinstance(u, str)],
            "change_type": change_type,
            "change_description": change_description,
            "change_reference": scope.get("change_reference", "").strip(),
        }

        emit_trace_event(
            "PreProcessNode_scope_validated",
            {
                "subject_area": subject_area,
                "effective_date": effective_date,
                "institution_id": institution_id,
                "change_type": change_type,
                "source_count": len(approved_source_ids),
                "channel": input_context.get("channel", "unknown"),
            },
            state,
        )

        return {
            "validated_input": f"curriculum_impact_briefing:{institution_id}:{subject_area}:{effective_date}",
            "change_scope_json": to_json(normalized_scope),
            "approved_source_ids_json": to_json(approved_source_ids),
            "enriched_context": {
                "source": "EDU-C2-046",
                "channel": input_context.get("channel", "unknown"),
            },
            "status": AgentStatus.SUCCESS.value,
        }
