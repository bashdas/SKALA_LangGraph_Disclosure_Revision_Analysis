from decimal import Decimal

from disclosure_impact_agent.demo import example_values
from disclosure_impact_agent.graph import run_review_graph
from disclosure_impact_agent.langchain_components import calculate_verified_ratio


def test_graph_collects_retrieved_evidence_and_tool_results():
    original, correction, memo = example_values()
    state = run_review_graph(original, correction, memo)

    assert state["retrieved_evidence_ids"]
    assert all(item["found"] for item in state["tool_results"])


def test_ratio_tool_is_exact_and_refuses_invalid_denominator():
    result = calculate_verified_ratio.invoke({
        "contract_amount_krw": 9_000_000_000,
        "sales_amount_krw": 80_000_000_000,
    })
    assert result["status"] == "verified"
    assert Decimal(result["ratio"]) == Decimal("11.25")
    assert calculate_verified_ratio.invoke({
        "contract_amount_krw": 1,
        "sales_amount_krw": 0,
    })["status"] == "unresolved"
