# Test Specification — EDU-C2-046

## Test Strategy
- Coverage target: 80%
- Test types: Unit / Integration

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Imports without error; `State` extends `AgentState`; `to_json`/`from_json` helpers present and functional | ✅ PASS |
| TC-02 | `SecurityViolationError` fires on S-2 gate | `PreProcessNode._extra_security_gate_input()` raises `SecurityViolationError` on prohibited framing | ✅ PASS |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations | ✅ PASS |
| TC-04 | `InvocationContext` constructed only via `from_state()` inside nodes | Direct construction is limited to the authenticated HTTP adapter; domain nodes use `InvocationContext.from_state(state)` | ✅ PASS |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from all `execute()` bodies | ✅ PASS |
| TC-06 | S-2: `_security_gate_input()` not overridden | `TypeError` at class definition if overridden — framework final gate enforced | ✅ PASS |
| TC-07 | S-3: `_security_gate_output()` not overridden | `TypeError` at class definition if overridden — framework final gate enforced | ✅ PASS |
| TC-08 | `required_trust_level` enforced | `ANONYMOUS` caller rejected for `VERIFIED_EXTERNAL` outer nodes | ✅ PASS |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial | `PreProcessNode`: length limit + prohibited-framing guard raise `SecurityViolationError` | ✅ PASS |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial | `PostProcessNode`: credential regex scan raises `SecurityViolationError` on bearer/api_key match | ✅ PASS |
| TC-11 | S-4: at least one domain `emit_trace_event()` per `execute()` | All 6 domain nodes (`PreProcess`, `EvidenceRetrieval`, `AffectedMaterialAnalysis`, `StakeholderMapping`, `BriefingHitl`, `PostProcess`) emit at least one domain event | ✅ PASS |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures (verified via TC-11 monkeypatch) | ✅ PASS |
| PB-2 | State serialization | `State` contains only `str` primitives (no `dict`, `list`, `Pydantic`) | AST scan: 0 violations | ✅ PASS |
| PB-3 | Level 2 → External service | `CurriculumSourceService` fake adapter returns normalised records | Data retrieved and provenance preserved | ✅ PASS (BL-08) |
| PB-4 | Import isolation | No Level 0 imports in `src/` | AST scan: 0 violations | ✅ PASS |
| PB-5 | Checkpoint safety *(conditional)* | When checkpointing is enabled and AgentCore exposes both ingress-protection hooks, inspect checkpoint, metadata, and pending writes for raw ingress | Full-surface inspection; otherwise auto-waive for unavailable framework capability | ⏭ AUTO-WAIVED — installed AgentCore lacks ingress hooks |
| PB-6 | Invoke execution order | `__call__()`: `S-1 trust gate → node_start → S-2 → execute → S-3 → node_complete`; dedicated lower-trust call proves denial occurs before `execute()` | Order verified for all 6 concrete node classes; negative S-1 proof passes | ✅ PASS |
| PB-7 | HITL interrupt propagation *(active — `hitl.enabled: true`)* | `interrupt()` raises `GraphInterrupt` when `hitl_allowed=True`; no interrupt when `hitl_allowed=False` | `GraphInterrupt` propagates; `hitl_allowed=False` completes without deadlock | ✅ PASS |

## Standalone Adapter Boundary Tests

- Boots without constructing a process-global LLM client.
- Resolves Azure OpenAI credentials from the current invocation and degrades safely on provider failure.
- Proves external and internal bearer tokens map only to their declared trust levels; invalid tokens receive HTTP 401.

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | Valid scope accepted and normalized | JSON scope with all required fields | `change_scope_json` + `approved_source_ids_json` populated; `status=success` | ✅ PASS |
| BL-02 | Empty user_input rejected | `""` | `status=error`; error_log populated | ✅ PASS |
| BL-03 | Non-JSON input rejected | `"not json"` | `status=error` | ✅ PASS |
| BL-04 | Missing required field rejected | Scope without `subject_area` | `status=error`; `subject_area` in error_log | ✅ PASS |
| BL-05 | Invalid date format rejected | `effective_date="01-09-2026"` | `status=error` | ✅ PASS |
| BL-05b | Invalid change_type rejected | `change_type="approve_immediately"` | `status=error` | ✅ PASS |
| BL-05c | Empty approved_source_ids rejected | `approved_source_ids=[]` | `status=error` | ✅ PASS |
| BL-06 | Empty approved sources → empty records | `approved_source_ids_json=[]` | `curriculum_records_json=[]`; `status=success` | ✅ PASS |
| BL-07 | Missing scope → retrieval error | `change_scope_json=""` | `status=error` | ✅ PASS |
| BL-08 | Provider records mapped with provenance | Fake adapter with record | Records in `curriculum_records_json`; `provenance_url` preserved | ✅ PASS |
| BL-09 | Affected materials with evidence links | Curriculum records with URL | `affected_materials_json` with `evidence_link` + `uncertainty` | ✅ PASS |
| BL-10 | No records → uncertainty marker | Empty records | `uncertainty="high — ..."` in placeholder | ✅ PASS |
| BL-11 | Citations collected from records | Record with `provenance_url` | `citations_json` populated; `url` present | ✅ PASS |
| BL-12 | Gap flagged when no policy references | No stakeholder refs from source | `gap_flag=True` in `stakeholder_impacts_json` | ✅ PASS |
| BL-13 | Communication output is advisory, not send | Stakeholder mapping output | No "email sent" / "notification sent" in output | ✅ PASS |
| BL-14 | Briefing assembled with HITL disabled | `hitl_allowed=False` | `briefing_draft_json` populated; `review_outcome=approved` | ✅ PASS |
| BL-15 | Resume: approve → approved | `hitl_feedback="approve"` | `review_outcome=approved` | ✅ PASS |
| BL-15b | Resume: correct → corrected | `hitl_feedback={"action":"correct",...}` | `review_outcome=corrected`; `review_correction` set | ✅ PASS |
| BL-15c | Resume: reject → rejected | `hitl_feedback={"action":"reject",...}` | `review_outcome=rejected`; `status=error` | ✅ PASS |
| BL-16 | Approved output includes all sections | `review_outcome=approved` | `executive_summary`, `affected_materials_summary`, `stakeholder_impacts_summary`, `citations` present | ✅ PASS |
| BL-16b | Rejected output marked | `review_outcome=rejected` | `[REJECTED BY REVIEWER]` in `executive_summary` | ✅ PASS |
| BL-16c | Corrected output includes correction | `review_outcome=corrected` | `operator_correction` field present | ✅ PASS |
| BL-17 | Full pipeline completes without provider | `graph.invoke()` end-to-end, no provider records | Completes; uncertainty markers present | ✅ PASS |
| BL-18 | Pre-process failure stops pipeline | Non-JSON scope | `status=error` propagated | ✅ PASS |

## Test Execution Summary

- Execution date: 2026-08-18
- Runtime used for local compatibility verification: AgentCore 1.0.0 (the configured 1.0.1 distribution was unavailable from the package indexes)
- Total tests: 57
- Pass: 56 / Fail: 0 / Skip: 1 (PB-5 framework-capability auto-waiver)
- Ruff: pass; formatting: pass; strict mypy: pass
- Proof-of-boundary suite: 11 pass / 1 skip
- Stage 5 provisional invoke evidence: PASS (HTTP 200, valid JSON, responsive `status=success`, no security violation)
- Coverage: not measured by `check-local.sh`; target remains 80%
