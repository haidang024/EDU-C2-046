"""PB-7: HITL interrupt propagation for EDU-C2-046."""

from __future__ import annotations

import json
import pathlib
import warnings

import pytest

_CONFIG_PATH = pathlib.Path(__file__).parents[2] / "config" / "config.yaml"


def _hitl_enabled() -> bool:
    """Return whether runtime configuration enables HITL."""
    if not _CONFIG_PATH.exists():
        warnings.warn(f"{_CONFIG_PATH} not found — PB-7 applicability is unknown.", stacklevel=2)
        return False
    try:
        import yaml

        data = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
    except Exception as exc:
        warnings.warn(f"{_CONFIG_PATH} could not be read ({exc}) — PB-7 applicability is unknown.", stacklevel=2)
        return False
    hitl = data.get("hitl", {}) if isinstance(data, dict) else None
    if not isinstance(hitl, dict):
        warnings.warn(f"{_CONFIG_PATH} has no valid hitl mapping.", stacklevel=2)
        return False
    return bool(hitl.get("enabled", False))


pytestmark = pytest.mark.skipif(
    not _hitl_enabled(),
    reason="config/config.yaml does not set hitl.enabled: true — PB-7 not applicable",
)

from src.nodes.briefing_hitl_node import BriefingHitlNode  # noqa: E402
from framework.schemas.trust_level import TrustLevel  # noqa: E402


def _base_state(**overrides: object) -> dict:
    state = {
        "caller_trust_level": TrustLevel.ANONYMOUS.value,
        "correlation_id": "pb7-test",
        "session_id": "pb7-session",
        "thread_id": "pb7-thread",
        "trace_id": "pb7-trace",
        "node_history": [],
        "error_log": [],
        "hitl_allowed": True,
        "hitl_count": 0,
        "change_scope_json": json.dumps(
            {
                "subject_area": "Computer Science",
                "effective_date": "2026-09-01",
                "institution_id": "INST-001",
                "unit_ids": ["CS101"],
                "change_type": "revision",
                "change_description": "Update data structures curriculum",
                "change_reference": "CS-REF-2026-001",
            }
        ),
        "affected_materials_json": json.dumps([]),
        "stakeholder_impacts_json": json.dumps([]),
        "communication_reqs_json": json.dumps([]),
        "citations_json": json.dumps([]),
    }
    state.update(overrides)
    return state


def test_pb7_hitl_interrupt_propagates(monkeypatch) -> None:
    """A real GraphInterrupt must escape BaseNode.__call__ unchanged."""
    from langgraph.errors import GraphInterrupt
    import langgraph.types as langgraph_types

    def raise_interrupt(value: object) -> None:
        raise GraphInterrupt(value)

    monkeypatch.setattr(langgraph_types, "interrupt", raise_interrupt)

    with pytest.raises(GraphInterrupt):
        BriefingHitlNode()(_base_state(hitl_allowed=True))


def test_pb7_hitl_allowed_false_skips_interrupt(monkeypatch) -> None:
    """The non-interactive path must never call interrupt()."""
    import langgraph.types as langgraph_types

    def unexpected_interrupt(_value: object) -> None:
        pytest.fail("interrupt() called with hitl_allowed=False")

    monkeypatch.setattr(langgraph_types, "interrupt", unexpected_interrupt)
    result = BriefingHitlNode()(_base_state(hitl_allowed=False))

    assert result.get("briefing_draft_json")
    assert result.get("review_outcome") == "approved"
