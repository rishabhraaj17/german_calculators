from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import params as P
from .models import AnalyseRequest
from .service import analyse

app = FastAPI(title="Elterngeld & zvE Calculator", version="1.0.0")

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "supported_birth_dates": [P.SUPPORTED_BIRTH_FROM.isoformat(), P.SUPPORTED_BIRTH_TO.isoformat()],
        "income_cap": str(P.INCOME_CAP_ZVE),
        "sources": {
            "BEEG": "https://www.gesetze-im-internet.de/beeg/ (as amended by Art. 19 Abs. 2 G v. 22.12.2025)",
            "Richtlinien zum BEEG": "BMBFSFJ, version 07/2026",
            "PAP": "https://www.bmf-steuerrechner.de (Lohnsteuer2025.xml, Lohnsteuer2026.xml)",
            "Official calculator (parity tests)": "https://gitlab.opencode.de/digitalservicebund/elterngeldrechner",
            "EStG": "https://www.gesetze-im-internet.de/estg/",
        },
    }


@app.post("/api/analyse")
def analyse_endpoint(req: AnalyseRequest) -> dict:
    try:
        return analyse(req)
    except ValueError as exc:  # out-of-scope inputs (e.g. unsupported birth date)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


if FRONTEND.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")
