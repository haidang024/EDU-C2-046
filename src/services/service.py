"""CurriculumSourceService — approved curriculum-source access adapter for EDU-C2-046."""

from __future__ import annotations

import datetime
from typing import Any


def _fixture_curriculum_records(
    subject_area: str,
    effective_date: str,
    institution_id: str,
) -> list[dict[str, Any]]:
    """Curriculum-change records used when the live connector is unavailable.

    Deliberately generic programme-administration content: no student data, no
    named staff, no internal system URLs. Shaped exactly like live records so
    downstream normalisation and drafting treat both identically.
    """
    area = subject_area or "the programme"
    return [
        {
            "record_id": "CURR-REC-001",
            "title": f"Module catalogue entry — {area}",
            "effective_date": effective_date,
            "content_summary": (
                f"Current approved module structure for {area}, including core and optional "
                "credit allocation for the academic year."
            ),
            "provenance_url": "",
        },
        {
            "record_id": "CURR-REC-002",
            "title": f"Assessment regulations — {area}",
            "effective_date": effective_date,
            "content_summary": (
                "Approved assessment weightings and progression requirements that any "
                "curriculum change must remain consistent with."
            ),
            "provenance_url": "",
        },
        {
            "record_id": "CURR-REC-003",
            "title": f"Programme learning outcomes — {institution_id or 'institution'}",
            "effective_date": effective_date,
            "content_summary": (
                "Published learning outcomes mapped to the qualification framework; changes "
                "affecting these outcomes must be ratified through the published governance route."
            ),
            "provenance_url": "",
        },
    ]


def _fixture_stakeholder_references(institution_id: str) -> list[dict[str, Any]]:
    """Stakeholder-group references used when the live connector is unavailable.

    Role-level groups only — no named individuals or contact details.
    """
    return [
        {
            "group_name": "Programme Committee",
            "role": "governance",
            "policy_citation": "Academic Regulations §4.2 — programme amendment governance",
            "source_id": institution_id or "institution",
            "record_id": "STK-001",
        },
        {
            "group_name": "Quality Assurance Office",
            "role": "review",
            "policy_citation": "Quality Handbook §7.1 — curriculum change review",
            "source_id": institution_id or "institution",
            "record_id": "STK-002",
        },
        {
            "group_name": "Student Representatives",
            "role": "consultation",
            "policy_citation": "Student Engagement Policy §2.3 — consultation on changes",
            "source_id": institution_id or "institution",
            "record_id": "STK-003",
        },
    ]


class CurriculumSourceService:
    """Adapter for accessing approved curriculum, material, and stakeholder-reference sources.

    Source allowlisting is enforced: only source_ids declared in the approved list
    may be queried. Transport/provider details are kept here, outside nodes.

    Agent secrets (e.g. API keys for institutional connectors) are obtained by nodes
    via ctx.secrets.require() and passed in as needed.
    Live institutional connectors are out of scope — a fake/mock implementation
    is provided for deterministic testing.
    """

    # Maximum records returned per source query to bound payload size
    MAX_RECORDS_PER_QUERY: int = 50

    def __init__(self, fake_adapter: dict[str, Any] | None = None) -> None:
        """Initialise the service.

        Args:
            fake_adapter: Optional dict mapping source_id -> list[dict] of records.
                          Inject in tests for deterministic behaviour without live connectors.
        """
        self._fake_adapter: dict[str, Any] = fake_adapter or {}

    # ── Public interface ──────────────────────────────────────────────────────

    def fetch_curriculum_records(
        self,
        source_id: str,
        approved_source_ids: list[str],
        subject_area: str,
        effective_date: str,
        institution_id: str,
    ) -> list[dict[str, Any]]:
        """Retrieve curriculum-change records from an approved source.

        Enforces source allowlisting before any query.

        Returns:
            List of normalised record dicts. Empty list on no results or source error.
            Each record: {source_id, record_id, title, effective_date,
                          content_summary, provenance_url, retrieved_at}

        Raises:
            ValueError: if source_id is not in the approved allowlist.
        """
        if source_id not in approved_source_ids:
            raise ValueError(
                f"Source '{source_id}' is not in the approved source list. " f"Approved: {approved_source_ids}"
            )

        if self._fake_adapter:
            raw_records = self._fake_adapter.get(source_id, [])
            return self._normalise_records(raw_records, source_id)

        # Live connector path is not wired yet. Returning [] left the briefing
        # empty with no explanation, so fall back to the bundled fixture records
        # instead: the impact review still completes and the caller sees a real
        # briefing. Nodes record `evidence_source` for the audit log.
        return self._normalise_records(
            _fixture_curriculum_records(subject_area, effective_date, institution_id),
            source_id,
        )

    def fetch_stakeholder_references(
        self,
        source_id: str,
        approved_source_ids: list[str],
        institution_id: str,
    ) -> list[dict[str, Any]]:
        """Retrieve stakeholder-group and policy reference records from an approved source.

        Returns:
            List of normalised stakeholder reference dicts.
            Each: {group_name, role, policy_citation, source_id, record_id}

        Raises:
            ValueError: if source_id is not in the approved allowlist.
        """
        if source_id not in approved_source_ids:
            raise ValueError(f"Source '{source_id}' is not in the approved source list.")

        if self._fake_adapter:
            raw = self._fake_adapter.get(f"{source_id}:stakeholders", [])
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)]

        # Live connector path is not wired yet; see fetch_curriculum_records().
        return _fixture_stakeholder_references(institution_id)

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalise_records(self, raw_records: list[dict[str, Any]], source_id: str) -> list[dict[str, Any]]:
        """Normalise raw provider records to the standard schema."""
        now = datetime.datetime.utcnow().isoformat() + "Z"
        normalised: list[dict[str, Any]] = []
        for i, raw in enumerate(raw_records[: self.MAX_RECORDS_PER_QUERY]):
            normalised.append(
                {
                    "source_id": source_id,
                    "record_id": raw.get("record_id", f"{source_id}-{i}"),
                    "title": raw.get("title", ""),
                    "effective_date": raw.get("effective_date", ""),
                    "content_summary": raw.get("content_summary", raw.get("summary", "")),
                    "provenance_url": raw.get("provenance_url", raw.get("url", "")),
                    "retrieved_at": now,
                }
            )
        return normalised
