# Template Design Specification — EDU-C2-046

## Position in AgentCore Architecture

- **Agent Class**: `Graph` (in `src/graph/graph.py`)
- **L1 Base**: `AgentBaseGraph` (outer) + `BaseGraph` (inner `DomainWorkflowGraph`)
- **Three-Layer Separation**:
  - State: flat TypedDict composition — all structured fields JSON-encoded (msgpack-safe)
  - Node: L1 inheritance (`FunctionNode` for domain nodes, `GraphNode` for `main` slot)
  - Graph: composition (`register_nodes()` for node substitution; inner graph in `domain_workflow_graph.py`)

## Architecture Overview

### Node Configuration

| Node | Responsibility | Input State Fields | Output State Fields | Inherits |
|------|---------------|-------------------|---------------------|---------|
| initialize | Framework lifecycle init | — | — | `InitializeNode` (framework default) |
| pre_process | Parse/validate curriculum-change scope; check approved sources | `user_input`, `input_context` | `change_scope_json`, `approved_source_ids_json`, `validated_input` | `FunctionNode` (`PreProcessNode`) |
| main | Wraps inner DomainWorkflowGraph | `validated_input`, outer state | `briefing_draft_json`, `citations_json`, `affected_materials_json`, `stakeholder_impacts_json`, `communication_reqs_json`, `review_outcome`, `review_correction` | `GraphNode` (`CurriculumImpactGraphNode`) |
| post_process | Assemble final traceable output; S-3 credential guard | `briefing_draft_json`, `review_outcome`, `review_correction`, all *_json fields | `formatted_output`, `result` | `FunctionNode` (`PostProcessNode`) |
| finalize | Framework lifecycle finalize | — | — | `FinalizeNode` (framework default) |

### Inner DomainWorkflowGraph Nodes

| Node | Responsibility | Trust Level |
|------|---------------|-------------|
| evidence_retrieval | Retrieve approved curriculum-change records from sources | `ANONYMOUS` |
| affected_material_analysis | Identify affected course materials with evidence links | `ANONYMOUS` |
| stakeholder_mapping | Map impacts to stakeholder groups; identify communication considerations | `ANONYMOUS` |
| briefing_hitl | Assemble briefing draft; interrupt for human review (D6 pattern) | `ANONYMOUS` |

### Data Flow

```
User invokes → Graph.invoke(user_input=<JSON scope>)

Outer backbone:
START → initialize → pre_process → main → {route} → post_process → finalize → END
                                        ↓ (RETRY, max 3)
                                      pre_process

Inside main (CurriculumImpactGraphNode):
  DomainWorkflowGraph.invoke(base64-encoded JSON envelope of sanitized scope + source IDs)
    → evidence_retrieval
    → [conditional: ERROR → END]
    → affected_material_analysis
    → stakeholder_mapping
    → briefing_hitl ──[interrupt if hitl_allowed=True]──→ human review
    → END

merge_output() maps inner sub_result → outer state
post_process formats final output
```

### State Definition

| Field | Type | Purpose | Producer |
|-------|------|---------|---------|
| `change_scope_json` | `str` (JSON-encoded dict) | Normalized curriculum-change scope | `PreProcessNode` |
| `approved_source_ids_json` | `str` (JSON-encoded list) | Operator-configured source allowlist | `PreProcessNode` |
| `curriculum_records_json` | `str` (JSON-encoded list[dict]) | Retrieved records from approved sources | `EvidenceRetrievalNode` |
| `affected_materials_json` | `str` (JSON-encoded list[dict]) | Potentially affected course materials | `AffectedMaterialAnalysisNode` |
| `stakeholder_impacts_json` | `str` (JSON-encoded list[dict]) | Stakeholder group impact records | `StakeholderMappingNode` |
| `communication_reqs_json` | `str` (JSON-encoded list[dict]) | Communication considerations (advisory) | `StakeholderMappingNode` |
| `briefing_draft_json` | `str` (JSON-encoded dict) | Assembled impact briefing draft | `BriefingHitlNode` |
| `citations_json` | `str` (JSON-encoded list[dict]) | Provenance citations for audit trail | `AffectedMaterialAnalysisNode` |
| `review_outcome` | `str` | `"approved"` / `"corrected"` / `"rejected"` | `BriefingHitlNode` (on resume) |
| `review_correction` | `str` | Operator correction text when corrected | `BriefingHitlNode` (on resume) |
| `formatted_output` | `str` | Final structured briefing (JSON) | `PostProcessNode` |

**State Constraints (mandatory):**
- Flat TypedDict only — no Pydantic, no dataclass (msgpack incompatible)
- ALL fields are primitives (`str`) — structured data is JSON-string-encoded with `to_json()`
- `to_json()` / `from_json()` helpers mandatory in every `state.py`
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- `InvocationContext` accessed via `InvocationContext.from_state(state)` inside nodes, never stored in State

## Framework Utilization

### Shared Components Used
- [x] `InvocationContext` — `ctx.secrets.require("CURRICULUM_CONNECTOR_API_KEY")` in inner nodes
- [x] `SecurityViolationError` — S-2 gate (`PreProcessNode._extra_security_gate_input`)
- [x] S-2: `_extra_security_gate_input()` — length limit + prohibited-framing guard (`PreProcessNode`)
- [x] S-3: `_extra_security_gate_output()` — credential-pattern scan on `formatted_output` (`PostProcessNode`)
- [x] S-4: `emit_trace_event()` — at least one domain event per `execute()` per node
- [x] HITL: `langgraph.types.interrupt()` via D6 pattern, guarded by `hitl_allowed`

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclasses always use the framework final gates; extensions
>   are implemented only through `_extra_security_gate_input()` and
>   `_extra_security_gate_output()`.
> - `GraphNode` deliberately delegates gate enforcement to the upstream and
>   inner nodes.
> - A custom `BaseNode` subclass must implement both abstract security gates.

### Security Gate Summary

| Node | S-2 `_extra_security_gate_input()` | S-3 `_extra_security_gate_output()` |
|------|------------------------------------|--------------------------------------|
| `PreProcessNode` | ✅ Length limit (4096) + prohibited-framing keywords | None needed (input JSON, no credential risk) |
| `PostProcessNode` | None needed (result is structured dict) | ✅ Regex scan for credential-like patterns in `formatted_output` |
| Inner domain nodes | Not applicable (`FunctionNode` framework default gate applies) | Not applicable |

### Composition Pattern

- **Pattern**: Cat 2 — `GraphNode` (inner `DomainWorkflowGraph` subgraph)
- **Composition target**: `DomainWorkflowGraph` (inner `BaseGraph`)
- **Error propagation strategy**: `propagate` (re-raise inner errors as `SubgraphError`)
- **HITL propagation**: `propagate_hitl = True` (inner HITL interrupt surfaced to outer caller)

### Dependency and Configuration Contract

| Dependency | Delivery | Behaviour when absent |
|------------|----------|-----------------------|
| Curriculum connector | `CURRICULUM_CONNECTOR_API_KEY` via `InvocationContext.from_state(state).secrets.require(...)` | Invocation fails closed at the connector boundary |
| Azure OpenAI advisory | Nodes resolve Azure credentials from the invocation context | The deterministic workflow remains functional when the provider is unavailable |

The optional client is an in-memory dependency only. It is never placed in
`State`, and no decision or control-flow branch depends on model output.

## EU AI Act Art.13 Design-Time Evidence

The proposal declares this intended use outside Annex III scope. These
transparency controls remain part of the design as defence in depth.

| Evidence item | Design reference / description |
|---------------|--------------------------------|
| Intended purpose and operating context | Decision support for authorised institutional staff assessing the impact of a proposed curriculum change. |
| System capabilities and limitations | Retrieves approved records, identifies potentially affected materials and stakeholders, and drafts a briefing. It cannot approve changes, mutate records, or send communications. |
| User-facing transparency information | The briefing includes citations, evidence-gap markers, limitations, provenance, and a decision-support disclaimer. |
| Human oversight mechanism | `BriefingHitlNode` interrupts for review when allowed; non-interactive invocation is explicit through `hitl_allowed=False` and remains non-authoritative. |

## Import Isolation Confirmation
- [x] Template does not import `agenticstar-platform` SDK (Level 0)
- [x] Import targets: `framework/` and `shared/` only

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | `AgentBaseGraph` | `AutonomousBaseGraph` | `AgentBaseGraph` | Deterministic multi-step pipeline; no autonomous loop required |
| Composition pattern | `GraphNode` (inner subgraph) | Flat `AgentBaseGraph` (Cat 1) | `GraphNode` + inner `BaseGraph` | 4 distinct domain steps require separate node files for testability |
| HITL propagation | `propagate_hitl=True` | `propagate_hitl=False` | `True` | Human review of impact briefing must surface to outer caller |
| Error strategy | `propagate` | `handle` | `propagate` | Fail-fast preferred for evidence pipeline; degraded output is not acceptable |
| Trust level (outer nodes) | `VERIFIED_EXTERNAL` | `ANONYMOUS` | `VERIFIED_EXTERNAL` | Outer `pre_process`/`post_process` are the trust boundary |
| Trust level (inner nodes) | `ANONYMOUS` | `VERIFIED_EXTERNAL` | `ANONYMOUS` | Trust already verified at `PreProcessNode`; inner nodes are not re-entry points |
| Optional LLM delivery | Node resolves a provider credential | Server constructs and injects a client | Explicit constructor injection | Matches the scaffold contract and keeps provider objects out of checkpointed State |
| Generation contract | LLM-generated decisions | Deterministic analysis and briefing | Deterministic | All material selection, stakeholder mapping, and review routing remain reproducible |
