from types import SimpleNamespace

import pytest

from disclosure_impact_agent.memo_models import ClaimBatch
from disclosure_impact_agent.openai_llm import OpenAIClaimExtractor


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_adapter_uses_responses_structured_output_and_configured_model():
    memo = "회사는 제조업체다."
    parsed = ClaimBatch(sentences=[], claims=[])
    responses = FakeResponses(SimpleNamespace(status="completed", output_parsed=parsed))
    client = SimpleNamespace(responses=responses)

    result = OpenAIClaimExtractor(model="configured-model", client=client).extract(memo)

    assert result == parsed
    assert responses.kwargs["model"] == "configured-model"
    assert responses.kwargs["text_format"] is ClaimBatch
    assert responses.kwargs["store"] is False
    assert memo in responses.kwargs["input"][0]["content"]


def test_adapter_rejects_incomplete_or_missing_structured_output():
    client = SimpleNamespace(responses=FakeResponses(SimpleNamespace(status="incomplete", output_parsed=None)))
    with pytest.raises(RuntimeError, match="did not complete"):
        OpenAIClaimExtractor(model="configured-model", client=client).extract("memo")


def test_adapter_server_validates_returned_offsets():
    bad = ClaimBatch.model_validate({
        "sentences":[{"sentence_id":"s","span":{"start":0,"end":5,"text":"wrong"}}],
        "claims":[]
    })
    client = SimpleNamespace(responses=FakeResponses(SimpleNamespace(status="completed", output_parsed=bad)))
    with pytest.raises(ValueError, match="span"):
        OpenAIClaimExtractor(model="configured-model", client=client).extract("memo")
