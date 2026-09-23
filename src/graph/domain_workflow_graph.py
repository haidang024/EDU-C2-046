"""DomainWorkflowGraph — inner BaseGraph for EDU-C2-046 Curriculum Change Impact Briefing Agent."""

from __future__ import annotations

from typing import Any

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from langgraph.graph import END, START
from src.nodes.affected_material_analysis_node import AffectedMaterialAnalysisNode
from src.nodes.briefing_hitl_node import BriefingHitlNode
from src.nodes.evidence_retrieval_node import EvidenceRetrievalNode
from src.nodes.stakeholder_mapping_node import StakeholderMappingNode
from src.schemas.state import State


class DomainWorkflowGraph(BaseGraph):
    """Inner domain workflow graph for EDU-C2-046.

    Inherits BaseGraph for fully custom node topology.
    Called by CurriculumImpactGraphNode.get_subgraph() in graph.py.

    Pipeline:
        START
          → evidence_retrieval
          → affected_material_analysis
          → stakeholder_mapping
          → briefing_hitl
          → END
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "edu_c2_046_curriculum_impact_workflow"

    @property
    def state_schema(self) -> type:
        return State

    # ── Config validation ─────────────────────────────────────────────────────

    def _validate_config(self) -> None:
        """No mandatory config for the inner graph; configuration flows via state."""
        pass

    # ── Node registration ─────────────────────────────────────────────────────

    def register_nodes(self) -> None:
        """Register all domain nodes. No super() call — BaseGraph.register_nodes() is abstract.

        Inner nodes use ANONYMOUS trust level (trust already verified at PreProcessNode).
        """
        self._nodes["evidence_retrieval"] = EvidenceRetrievalNode()
        self._nodes["affected_material_analysis"] = AffectedMaterialAnalysisNode()
        self._nodes["stakeholder_mapping"] = StakeholderMappingNode()
        self._nodes["briefing_hitl"] = BriefingHitlNode()

    # ── Edge wiring ───────────────────────────────────────────────────────────

    def add_edges(self) -> None:
        """Wire the linear domain topology with early-exit on error."""
        self._sg.add_edge(START, "evidence_retrieval")
        self._sg.add_conditional_edges("evidence_retrieval", self._route_after_retrieval)
        self._sg.add_edge("affected_material_analysis", "stakeholder_mapping")
        self._sg.add_edge("stakeholder_mapping", "briefing_hitl")
        self._sg.add_edge("briefing_hitl", END)

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(self, state: AgentState) -> str:
        """Required by BaseGraph ABC; used via add_conditional_edges."""
        if state.get("status") == AgentStatus.ERROR.value:
            return str(END)
        return "affected_material_analysis"

    def _route_after_retrieval(self, state: AgentState) -> str:
        """Route after evidence_retrieval: abort on error, continue on success."""
        if state.get("status") == AgentStatus.ERROR.value:
            return str(END)
        return "affected_material_analysis"

    # ── Output shape ──────────────────────────────────────────────────────────

    def get_output(self, state: AgentState) -> dict[str, Any]:
        """Shape the sub_result dict returned to CurriculumImpactGraphNode.merge_output().

        Keys MUST match what merge_output() reads from sub_result.
        """
        return {
            "output": state.get("briefing_draft_json"),
            "citations_json": state.get("citations_json"),
            "affected_materials_json": state.get("affected_materials_json"),
            "stakeholder_impacts_json": state.get("stakeholder_impacts_json"),
            "communication_reqs_json": state.get("communication_reqs_json"),
            "review_outcome": state.get("review_outcome"),
            "review_correction": state.get("review_correction"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "error_log": state.get("error_log", []),
        }
