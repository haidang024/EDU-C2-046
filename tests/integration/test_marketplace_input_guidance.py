import json

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


def test_invalid_marketplace_scope_returns_readable_guidance():
    graph = Graph(config={})
    graph.compile()
    result = graph.invoke(
        "Hello",
        ctx=InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL),
        input_context={"conversation_history": []},
    )
    assert result["status"] == "success"
    assert result["output"].startswith("Curriculum impact briefing request could not be processed.")
    assert "not valid JSON" in result["output"]


def test_success_marketplace_output_is_readable_but_api_stays_json():
    graph = Graph(config={})
    formatted_output = json.dumps(
        {
            "title": "Curriculum Change Impact Briefing",
            "review_disposition": "approved",
            "executive_summary": "The revised curriculum affects two teaching resources.",
            "affected_materials_summary": {
                "count": 2,
                "items": [{"title": "Year 8 Science Guide", "impact": "Update chapter 4."}],
            },
            "stakeholder_impacts_summary": {"count": 1, "items": ["Science teachers"]},
            "communication_considerations": ["Notify curriculum coordinators."],
            "citations": [{"citation": "Curriculum Policy 2026 section 4"}],
            "limitations": [],
            "notice": "Decision support only; this does not constitute curriculum approval.",
        }
    )
    api_result = graph.get_output({"formatted_output": formatted_output})
    marketplace_result = graph.get_output(
        {"formatted_output": formatted_output, "input_context": {"conversation_history": []}}
    )
    assert api_result.get("output", api_result.get("formatted_output")) == formatted_output
    assert marketplace_result["output"].startswith("# Curriculum Change Impact Briefing")
    assert "Year 8 Science Guide" in marketplace_result["output"]
    assert not marketplace_result["output"].lstrip().startswith("{")
