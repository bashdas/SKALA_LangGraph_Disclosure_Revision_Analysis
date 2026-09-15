from fastapi.testclient import TestClient

from disclosure_impact_agent.api import app


def test_health_uses_offline_defaults(monkeypatch):
    monkeypatch.delenv("DATA_MODE", raising=False)
    monkeypatch.delenv("LLM_MODE", raising=False)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "data_mode": "fixture",
        "llm_mode": "fake",
        "stage": "1-structural-validation",
    }
