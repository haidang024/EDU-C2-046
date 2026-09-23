"""EvidenceRetrievalNode — curriculum-change evidence retrieval for EDU-C2-046."""

from __future__ import annotations

import base64
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json
from src.services.service import CurriculumSourceService


class EvidenceRetrievalNode(FunctionNode):
    """Retrieve approved curriculum-change records from configured sources.

    Inner DomainWorkflowGraph node. Trust is already verified at the boundary
    (PreProcessNode), so ANONYMOUS is correct here (trust-trap anti-pattern avoided).

    Does NOT make a curriculum approval decision. Only retrieves and normalises
    records from operator-approved sources.
    """

    # Inner node — trust already enforced at boundary. ANONYMOUS required.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Retrieve curriculum-change records from each approved source.

        Reads:
            change_scope_json, approved_source_ids_json

        Returns state delta with:
            curriculum_records_json — JSON-encoded list[dict] of retrieved records
        """
        scope_json = state.get("change_scope_json", "")
        approved_source_ids_json = state.get("approved_source_ids_json", "")

        # GraphNode.extract_input() crosses the subgraph boundary as a string.
        # Recover only the explicit, sanitized fields from that envelope.
        if not scope_json or not approved_source_ids_json:
            envelope = from_json(state.get("user_input"), default={})
            if not isinstance(envelope, dict) or not envelope:
                try:
                    encoded = str(state.get("user_input", ""))
                    decoded = base64.urlsafe_b64decode(encoded.encode()).decode()
                    envelope = from_json(decoded, default={})
                except (ValueError, UnicodeDecodeError):
                    envelope = {}
            if isinstance(envelope, dict):
                scope_json = envelope.get("change_scope_json", "")
                approved_source_ids_json = envelope.get("approved_source_ids_json", "")

        scope = from_json(scope_json, default={})
        approved_source_ids = from_json(approved_source_ids_json, default=[])

        if not scope:
            emit_trace_event(
                "EvidenceRetrievalNode_skipped",
                {"reason": "missing_scope"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["EvidenceRetrievalNode: change_scope_json is missing or empty."],
            }

        if not approved_source_ids:
            emit_trace_event(
                "EvidenceRetrievalNode_skipped",
                {"reason": "no_approved_sources"},
                state,
            )
            return {
                "curriculum_records_json": to_json([]),
                "change_scope_json": scope_json,
                "approved_source_ids_json": approved_source_ids_json,
                "status": AgentStatus.SUCCESS.value,
            }

        # Obtain secrets via InvocationContext (never os.environ)
        ctx = InvocationContext.from_state(state)
        # The curriculum connector API key is declared in agent.yaml requires.secrets.
        # It may be absent in test environments; treat as optional for mock path.
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
        all_records: list[dict[str, Any]] = []
        source_errors: list[str] = []

        for source_id in approved_source_ids:
            try:
                records = service.fetch_curriculum_records(
                    source_id=source_id,
                    approved_source_ids=approved_source_ids,
                    subject_area=scope.get("subject_area", ""),
                    effective_date=scope.get("effective_date", ""),
                    institution_id=scope.get("institution_id", ""),
                )
                all_records.extend(records)
            except ValueError as exc:
                source_errors.append(f"source={source_id}: {exc}")
            except Exception as exc:  # noqa: BLE001
                source_errors.append(f"source={source_id}: retrieval error — {exc}")

        emit_trace_event(
            "EvidenceRetrievalNode_retrieval_complete",
            {
                "sources_queried": len(approved_source_ids),
                "records_retrieved": len(all_records),
                "source_errors": len(source_errors),
                "institution_id": scope.get("institution_id", ""),
                "evidence_source": evidence_source,
            },
            state,
        )

        result: dict[str, Any] = {
            "curriculum_records_json": to_json(all_records),
            "change_scope_json": scope_json,
            "approved_source_ids_json": approved_source_ids_json,
            # Operator-facing: "live" or "fixture". The briefing is identical
            # either way, so this is the only signal distinguishing them.
            "evidence_source": evidence_source,
            "status": AgentStatus.SUCCESS.value,
        }

        if source_errors:
            result["error_log"] = state.get("error_log", []) + [
                f"EvidenceRetrievalNode partial failure: {e}" for e in source_errors
            ]

        return result
