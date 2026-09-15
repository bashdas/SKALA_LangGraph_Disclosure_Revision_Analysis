from disclosure_impact_agent.demo import build_demo, example_values, run_demo


def test_gradio_demo_runs_main_mock_flow():
    original, correction, memo = example_values()
    status, changes, impacts, proposals = run_demo(original, correction, memo, "fake", "")

    assert "분석 완료" in status
    assert len(changes) == 3
    assert [row[1] for row in impacts] == [
        "DIRECT_FACT_CHANGE", "DERIVED_VALUE_CHANGE", "DIRECT_FACT_CHANGE",
        "INTERPRETATION_REVIEW", "NO_IMPACT",
    ]
    assert "90억원" in proposals and "11.25%" in proposals and "2027-03-31" in proposals


def test_gradio_blocks_can_be_built_without_launching_server():
    demo = build_demo()
    assert demo is not None
