from fastapi import FastAPI

from disclosure_impact_agent import __version__
from disclosure_impact_agent.config import get_settings

app = FastAPI(title="공시 정정 영향 추적 API", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "data_mode": settings.data_mode,
        "llm_mode": settings.llm_mode,
        "stage": "1-structural-validation",
    }
