"""AffectedMaterialAnalysisNode — determine affected course materials for EDU-C2-046."""

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json


class AffectedMaterialAnalysisNode(FunctionNode):
    """Determine potentially affected course materials from normalised evidence.

    Inner DomainWorkflowGraph node (ANONYMOUS — trust already verified at boundary).

    Produces traceable affected-material records with evidence/citation links and
    uncertainty markers. Makes no unsupported inference when source data is incomplete.
    Does NOT approve changes or send communications.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    # Material type categories derived from curriculum record analysis
    _MATERIAL_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"course_outline", "assessment", "reading_list", "learning_resource", "published_reference"}
    )

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Analyse curriculum records to identify potentially affected materials.

        Reads:
            change_scope_json, curriculum_records_json

        Returns state delta with:
            affected_materials_json — JSON-encoded list[dict]
            citations_json          — JSON-encoded list[dict] (evidence links)
        """
        scope = from_json(state.get("change_scope_json"), default={})
        records = from_json(state.get("curriculum_records_json"), default=[])

        subject_area = scope.get("subject_area", "")
        change_type = scope.get("change_type", "")
        change_description = scope.get("change_description", "")

        if not records:
            # Safe partial result: no records retrieved — mark all as uncertain
            emit_trace_event(
                "AffectedMaterialAnalysisNode_no_evidence",
                {
                    "subject_area": subject_area,
                    "change_type": change_type,
                    "uncertainty": "no_curriculum_records_available",
                },
                state,
            )
            placeholder = {
                "material_id": "UNKNOWN",
                "material_type": "unknown",
                "title": "Unable to determine — no curriculum records retrieved",
                "impacted_by": change_description,
                "evidence_link": "",
                "uncertainty": "high — no source records available",
                "action_required": "Manual review required; no automated evidence available.",
            }
            return {
                "affected_materials_json": to_json([placeholder]),
                "citations_json": to_json([]),
                "status": AgentStatus.SUCCESS.value,
            }

        # Derive affected materials from each record
        affected_materials: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []

        for record in records:
            source_id = record.get("source_id", "")
            record_id = record.get("record_id", "")
            title = record.get("title", "")
            content_summary = record.get("content_summary", "")
            provenance_url = record.get("provenance_url", "")
            retrieved_at = record.get("retrieved_at", "")

            # Classify material type from content summary heuristics
            mat_type = self._classify_material_type(content_summary, title)

            # Determine uncertainty: mark as uncertain if content_summary is absent
            uncertainty = "low" if content_summary else "high — content summary absent"

            # Determine action from change_type
            action = self._derive_action(change_type, mat_type)

            affected_materials.append(
                {
                    "material_id": record_id,
                    "material_type": mat_type,
                    "title": title or record_id,
                    "impacted_by": change_description,
                    "evidence_link": provenance_url,
                    "uncertainty": uncertainty,
                    "action_required": action,
                }
            )

            if provenance_url:
                citations.append(
                    {
                        "source_id": source_id,
                        "record_id": record_id,
                        "url": provenance_url,
                        "accessed_at": retrieved_at,
                    }
                )

        emit_trace_event(
            "AffectedMaterialAnalysisNode_analysis_complete",
            {
                "subject_area": subject_area,
                "change_type": change_type,
                "records_analysed": len(records),
                "materials_identified": len(affected_materials),
                "citations_collected": len(citations),
            },
            state,
        )

        return {
            "affected_materials_json": to_json(affected_materials),
            "citations_json": to_json(citations),
            "status": AgentStatus.SUCCESS.value,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _classify_material_type(self, content_summary: str, title: str) -> str:
        """Classify material type from summary and title text."""
        combined = f"{title} {content_summary}".lower()
        if any(k in combined for k in ("exam", "assessment", "quiz", "test")):
            return "assessment"
        if any(k in combined for k in ("reading", "bibliography", "reference list")):
            return "reading_list"
        if any(k in combined for k in ("course outline", "syllabus", "curriculum")):
            return "course_outline"
        if any(k in combined for k in ("resource", "module", "learning material")):
            return "learning_resource"
        if any(k in combined for k in ("published", "journal", "textbook", "article")):
            return "published_reference"
        return "course_outline"  # default

    def _derive_action(self, change_type: str, material_type: str) -> str:
        """Derive a recommended action from change type and material type."""
        action_map: dict[str, str] = {
            "removal": "Review and update or retire this material.",
            "addition": "Review whether this material requires extension or new content.",
            "revision": "Review and revise material to align with curriculum changes.",
            "restructure": "Review structural alignment and update as necessary.",
        }
        base_action = action_map.get(change_type, "Review required.")
        if material_type == "assessment":
            return f"{base_action} Confirm assessment validity under new curriculum."
        return base_action
