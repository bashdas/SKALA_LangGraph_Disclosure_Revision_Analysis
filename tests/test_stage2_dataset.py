import json
from pathlib import Path


def test_evaluation_dataset_has_required_split_and_is_separate_from_answers():
    root = Path(__file__).parents[1] / "evaluation"
    inputs = json.loads((root / "inputs.json").read_text())
    expected = json.loads((root / "expected.json").read_text())

    scenarios = inputs["scenarios"]
    assert len(scenarios) == 12
    assert sum(len(item["claims"]) for item in scenarios) >= 60
    assert sum(item["split"] == "development" for item in scenarios) == 8
    assert sum(item["split"] == "fixed_evaluation" for item in scenarios) == 4
    assert "classes" not in json.dumps(inputs)
    assert expected["runtime_input"] is False
    assert expected["answer_status"] == "provisional_not_human_reviewed"
    assert {item["id"] for item in scenarios} == {item["id"] for item in expected["scenarios"]}
    group_splits = {}
    for item in scenarios:
        group_splits.setdefault(item["contract_group"], set()).add(item["split"])
    assert all(len(splits) == 1 for splits in group_splits.values())
