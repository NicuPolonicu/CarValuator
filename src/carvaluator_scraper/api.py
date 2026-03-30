from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from carvaluator_scraper.inference import predict_from_link


DEFAULT_MODEL_BUNDLE = Path("data/model_results_log/best_model.joblib")
WEB_DIR = Path(__file__).resolve().parent / "web"


class PredictRequest(BaseModel):
    site: str = Field(default="autovit", description="Supported values: autovit")
    url: str = Field(..., min_length=1, description="Listing URL to score")
    threshold_percent: float = Field(default=15.0, gt=0.0, le=100.0)
    model_bundle_path: str | None = Field(
        default=None,
        description="Optional override for the saved model bundle path. Intended for local development.",
    )


def _allowed_origins() -> list[str]:
    raw = os.getenv("CARVALUATOR_ALLOW_ORIGINS", "*")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["*"]


def _resolve_model_bundle_path(request_path: str | None = None) -> Path:
    configured_path = request_path or os.getenv("CARVALUATOR_MODEL_BUNDLE")
    path = Path(configured_path) if configured_path else DEFAULT_MODEL_BUNDLE
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CarValuator API",
        version="0.1.0",
        description="Small inference API for scoring used-car listing prices.",
    )

    allow_origins = _allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/health")
    def health() -> dict[str, object]:
        model_bundle = _resolve_model_bundle_path()
        return {
            "status": "ok",
            "supported_sites": ["autovit"],
            "default_model_bundle": str(model_bundle),
            "model_bundle_exists": model_bundle.exists(),
        }

    @app.post("/predict")
    def predict(request: PredictRequest) -> dict[str, object]:
        model_bundle = _resolve_model_bundle_path(request.model_bundle_path)
        if not model_bundle.exists():
            raise HTTPException(
                status_code=500,
                detail=f"Model bundle not found at {model_bundle}. Set CARVALUATOR_MODEL_BUNDLE or pass model_bundle_path.",
            )

        try:
            prediction = predict_from_link(
                site=request.site,
                url=request.url,
                model_bundle_path=model_bundle,
                threshold_percent=request.threshold_percent,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Prediction failed: {exc}") from exc

        return prediction.to_dict()

    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.getenv("CARVALUATOR_API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("CARVALUATOR_API_PORT", "8000")))
    uvicorn.run("carvaluator_scraper.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
