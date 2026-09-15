from disclosure_impact_agent.demo import example_values
from disclosure_impact_agent.graph import build_review_graph, run_review_graph


def test_graph_runs_main_path_in_node_order():
    original, correction, memo = example_values()
    state = run_review_graph(original, correction, memo)

    assert state["outcome"] == "complete"
    assert state["events"] == [
        "parse_filings", "compare_changes", "analyze_claims", "complete_review"
    ]
    assert state["result"].reviewed_claim_count == 5
    assert len(state["result"].proposals) == 3


def test_graph_routes_failed_fake_input_to_review():
    original, correction, _ = example_values()
    state = run_review_graph(original, correction, "지원하지 않는 메모")

    assert state["outcome"] == "needs_review"
    assert state["events"][-1] == "mark_needs_review"
    assert state["result"].failures


def test_graph_structure_matches_demo_skeleton():
    graph = build_review_graph()
    node_names = set(graph.get_graph().nodes)
    assert {"__start__", "parse_filings", "compare_changes", "analyze_claims", "complete_review", "mark_needs_review", "__end__"} <= node_names
