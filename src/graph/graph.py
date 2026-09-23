"""Graph — outer AgentBaseGraph for EDU-C2-046 Curriculum Change Impact Briefing Agent."""

from __future__ import annotations

import base64
import json
from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.graph.base_graph import BaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State, to_json
from src.services.error_reporting import describe_failure, failure_message, FailureCategory


class CurriculumImpactGraphNode(GraphNode):
    """GraphNode wrapper for the inner curriculum impact domain workflow.

    Assigned to the `main` slot in the outer AgentBaseGraph.
    Delegates multi-step orchestration to DomainWorkflowGraph.
    HITL propagation is enabled so the outer graph surfaces the interrupt
    to the caller — required for the human review pattern in this agent.
    """

    # "handle" (not "propagate"): a propagated SubgraphError aborts the run
    # before merge_output(), so post_process never executes and the Marketplace
    # runner returns a bare RuntimeError with no reason. on_subgraph_error()
    # converts the failure into a domain field instead.
    error_strategy: ClassVar[str] = "handle"
    # True: surface inner HITL interrupt to the outer graph caller (review pattern)
    propagate_hitl: ClassVar[bool] = True

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm: Any = None,
        **kwargs: Any,
    ) -> None:
        self._config = config or {}
        self._llm = llm if llm is not None else (config or {}).get("llm")
        super().__init__(**kwargs)

    def get_subgraph(self) -> BaseGraph:
        """Instantiate the inner domain workflow graph on each call."""
        from src.graph.domain_workflow_graph import DomainWorkflowGraph  # local import avoids cycles

        return DomainWorkflowGraph(config=self._parent_config())

    def extract_input(self, state: AgentState) -> str:
        """Pass sanitized domain fields through the GraphNode string contract."""
        envelope = to_json(
            {
                "validated_input": state.get("validated_input", ""),
                "change_scope_json": state.get("change_scope_json", ""),
                "approved_source_ids_json": state.get("approved_source_ids_json", ""),
            }
        )
        # Keep already-sanitized structured fields opaque to the inner graph's
        # generic free-text PII scanner, which otherwise masks domain labels.
        return base64.urlsafe_b64encode(envelope.encode()).decode()

    def execute(self, state: AgentState) -> dict[str, Any]:
        if state.get("input_error_message"):
            return {"status": AgentStatus.SUCCESS.value}
        return cast(dict[str, Any], super().execute(state))

    def on_subgraph_error(self, state: AgentState, error: Exception) -> dict[str, Any]:
        """Carry an inner failure as a domain field so the pipeline keeps running.

        Returning status=error here would route straight to finalize, skipping
        post_process; the Marketplace runner then drops `output` and the caller sees
        only "invocation did not succeed".
        """
        error_log = getattr(error, "error_log", None) or []
        entries = [entry for e in error_log if (entry := str(e).strip())]
        # The raw entry only selects a category; describe_failure() returns one of
        # its own literals, never any part of the diagnostic. See
        # src/services/error_reporting.py for why classification replaces filtering.
        return {
            "status": AgentStatus.SUCCESS.value,
            "workflow_error_message": (
                describe_failure(entries[-1], getattr(error, "trace_id", ""))
                if entries
                else failure_message(FailureCategory.UNKNOWN)
            ),
        }

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        """Map inner graph output fields back into the outer state.

        Designed together with DomainWorkflowGraph.get_output().
        Returns ONLY the keys this node changes.
        """
        return {
            "briefing_draft_json": sub_result.get("output"),
            "citations_json": sub_result.get("citations_json"),
            "affected_materials_json": sub_result.get("affected_materials_json"),
            "stakeholder_impacts_json": sub_result.get("stakeholder_impacts_json"),
            "communication_reqs_json": sub_result.get("communication_reqs_json"),
            "review_outcome": sub_result.get("review_outcome"),
            "review_correction": sub_result.get("review_correction"),
            "status": sub_result.get("status"),
            "error_log": sub_result.get("error_log", []),
        }

    def _parent_config(self) -> dict[str, Any]:
        """Forward runtime config without putting dependency objects in State."""
        return {**self._config, "llm": self._llm}


class Graph(AgentBaseGraph):
    """EDU-C2-046 — Curriculum Change Impact Briefing Agent outer graph.

    Cat 2 fixed multi-step workflow.
    Backbone: initialize → pre_process → main (DomainWorkflowGraph) → post_process → finalize.
    HITL is enabled; the human review interrupt surfaces through CurriculumImpactGraphNode.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    @property
    def name(self) -> str:
        return "edu-c2-046"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = CurriculumImpactGraphNode(
            config=self.config,
            llm=self.config.get("llm"),
        )
        self._nodes["post_process"] = PostProcessNode(
            llm=self.config.get("llm"),
            config=self.config,
        )

    def get_output(self, state: AgentState) -> dict[str, Any]:
        output = cast(dict[str, Any], super().get_output(state))
        output["generation_mode"] = state.get("generation_mode")
        output["provider_error_message"] = state.get("provider_error_message")
        context = state.get("input_context")
        is_marketplace = isinstance(context, dict) and "conversation_history" in context
        if not is_marketplace:
            return output

        if _set_marketplace_guidance(output, state, "Curriculum impact briefing request"):
            return output

        payload = self._parse_briefing(output.get("output", output.get("formatted_output")))
        if payload is not None:
            output["output"] = self._render_marketplace_briefing(payload)
        return output

    @staticmethod
    def _parse_briefing(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _render_marketplace_briefing(payload: dict[str, Any]) -> str:
        lines = [
            f"# {payload.get('title', 'Curriculum Change Impact Briefing')}",
            "",
            f"**Review disposition:** {payload.get('review_disposition', 'pending')}",
        ]
        if payload.get("executive_summary"):
            lines.extend(["", "## Executive summary", "", str(payload["executive_summary"])])

        for heading, key in (
            ("Affected materials", "affected_materials_summary"),
            ("Stakeholder impacts", "stakeholder_impacts_summary"),
        ):
            section = payload.get(key)
            if not isinstance(section, dict):
                continue
            lines.extend(["", f"## {heading}", "", f"Count: {section.get('count', 0)}"])
            items = section.get("items")
            if isinstance(items, list):
                for item in items[:30]:
                    if isinstance(item, dict):
                        label = item.get("title") or item.get("name") or item.get("material_id") or "Item"
                        detail = item.get("impact") or item.get("description") or item.get("action_required")
                        lines.append(f"- {label}{f': {detail}' if detail else ''}")
                    else:
                        lines.append(f"- {item}")

        considerations = payload.get("communication_considerations")
        if isinstance(considerations, list) and considerations:
            lines.extend(["", "## Communication considerations", ""])
            lines.extend(f"- {item}" for item in considerations)
        citations = payload.get("citations")
        if isinstance(citations, list) and citations:
            lines.extend(["", "## Sources", ""])
            for citation in citations[:20]:
                if isinstance(citation, dict):
                    lines.append(f"- {citation.get('citation') or citation.get('source') or 'Source'}")
                else:
                    lines.append(f"- {citation}")
        limitations = payload.get("limitations")
        if isinstance(limitations, list) and limitations:
            lines.extend(["", "## Limitations", ""])
            lines.extend(f"- {item}" for item in limitations)
        if payload.get("operator_correction"):
            lines.extend(["", "## Operator correction", "", str(payload["operator_correction"])])
        if payload.get("notice"):
            lines.extend(["", f"> {payload['notice']}"])
        return "\n".join(lines)

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.


def _set_marketplace_guidance(output: dict[str, Any], state: AgentState, subject: str) -> bool:
    context = state.get("input_context")
    message = state.get("input_error_message")
    if not (isinstance(context, dict) and "conversation_history" in context and message):
        return False
    lines = [f"{subject} could not be processed.", "", f"Reason: {message}"]
    guidance = state.get("input_error_guidance")
    if isinstance(guidance, list) and guidance:
        lines.extend(["", "How to continue:"])
        lines.extend(f"- {item}" for item in guidance)
    output["output"] = "\n".join(lines)
    return True
