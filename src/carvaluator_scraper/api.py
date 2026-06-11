from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from carvaluator_scraper.auth import (
    AuthUser,
    SESSION_COOKIE_NAME,
    authenticate_user,
    create_session,
    create_user,
    delete_all_prediction_history,
    delete_prediction_history_item,
    delete_session,
    get_current_user,
    initialize_auth_db,
    list_prediction_history,
    record_prediction_history,
)
from carvaluator_scraper.inference import predict_from_link


DEFAULT_MODEL_BUNDLE = Path("data/model_results_xl_log/best_model.joblib")
DEFAULT_SIMILARITY_CSV = Path("data/autovit_xl.csv")
WEB_DIR = Path(__file__).resolve().parent / "web"


class PredictRequest(BaseModel):
    site: str = Field(default="autovit", description="Supported values: autovit, mobilede")
    url: str = Field(..., min_length=1, description="Listing URL to score")
    threshold_percent: float = Field(default=15.0, gt=0.0, le=100.0)
    ensemble_method: str = Field(
        default="inverse_mae_with_agreement",
        description="Supported values: inverse_mae, inverse_mae_with_agreement",
    )
    model_bundle_path: str | None = Field(
        default=None,
        description="Optional override for the saved model bundle path. Intended for local development.",
    )
    similar_limit: int = Field(default=5, ge=0, le=12)
    similarity_csv_path: str | None = Field(
        default=None,
        description="Optional override for the CSV dataset used to suggest similar listings.",
    )


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=256)


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=254, description="Email or username")
    password: str = Field(..., min_length=1, max_length=256)


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


def _resolve_similarity_csv_path(request_path: str | None = None) -> Path:
    configured_path = request_path or os.getenv("CARVALUATOR_SIMILARITY_CSV")
    path = Path(configured_path) if configured_path else DEFAULT_SIMILARITY_CSV
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _resolve_model_artifact_path(filename: str) -> Path:
    if Path(filename).name != filename or not filename.endswith(".png"):
        raise ValueError("Only PNG model artifacts from the active model directory can be served.")
    model_bundle = _resolve_model_bundle_path()
    return (model_bundle.parent / filename).resolve()


def _attach_session_cookie(response: Response, token: str, expires_at: object) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=os.getenv("CARVALUATOR_COOKIE_SECURE", "0") == "1",
        samesite="lax",
        expires=expires_at,
        max_age=7 * 24 * 60 * 60,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", samesite="lax")


def create_app() -> FastAPI:
    initialize_auth_db()
    app = FastAPI(
        title="CarValuator API",
        version="0.1.0",
        description="Small inference API for scoring used-car listing prices.",
    )

    allow_origins = _allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
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
        similarity_csv = _resolve_similarity_csv_path()
        model_artifact_dir = model_bundle.parent
        return {
            "status": "ok",
            "supported_sites": ["autovit", "mobilede"],
            "default_model_bundle": str(model_bundle),
            "model_bundle_exists": model_bundle.exists(),
            "similarity_dataset": str(similarity_csv),
            "similarity_dataset_exists": similarity_csv.exists(),
            "model_artifacts": {
                "model_performance": (model_artifact_dir / "model_performance.png").exists(),
                "actual_vs_predicted": (model_artifact_dir / "actual_vs_predicted.png").exists(),
            },
        }

    @app.get("/model-artifacts/{filename}", include_in_schema=False)
    def model_artifact(filename: str) -> FileResponse:
        try:
            path = _resolve_model_artifact_path(filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Model artifact not found: {filename}")
        return FileResponse(path)

    @app.post("/auth/register")
    def register(payload: RegisterRequest, response: Response) -> dict[str, object]:
        user = create_user(email=payload.email, username=payload.username, password=payload.password)
        token, expires_at = create_session(user.id)
        _attach_session_cookie(response, token, expires_at)
        return {"user": user.to_dict()}

    @app.post("/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, object]:
        user = authenticate_user(identifier=payload.identifier, password=payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="Email/username sau parola incorecta.")
        token, expires_at = create_session(user.id)
        _attach_session_cookie(response, token, expires_at)
        return {"user": user.to_dict()}

    @app.get("/auth/me")
    def me(user: object = Depends(get_current_user)) -> dict[str, object]:
        return {"user": user.to_dict()}

    @app.post("/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, object]:
        delete_session(request.cookies.get(SESSION_COOKIE_NAME))
        _clear_session_cookie(response)
        return {"ok": True}

    @app.get("/history")
    def history(limit: int = 20, user: AuthUser = Depends(get_current_user)) -> dict[str, object]:
        items = list_prediction_history(user_id=user.id, limit=limit)
        return {"items": [item.to_dict() for item in items]}

    @app.delete("/history/{history_id}")
    def delete_history_item(history_id: int, user: AuthUser = Depends(get_current_user)) -> dict[str, object]:
        deleted = delete_prediction_history_item(user_id=user.id, history_id=history_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Analiza nu exista in istoricul acestui cont.")
        return {"ok": True, "deleted": 1}

    @app.delete("/history")
    def delete_history(user: AuthUser = Depends(get_current_user)) -> dict[str, object]:
        deleted = delete_all_prediction_history(user_id=user.id)
        return {"ok": True, "deleted": deleted}

    @app.post("/predict")
    def predict(request: PredictRequest, user: AuthUser = Depends(get_current_user)) -> dict[str, object]:
        model_bundle = _resolve_model_bundle_path(request.model_bundle_path)
        similarity_csv = _resolve_similarity_csv_path(request.similarity_csv_path)
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
                similarity_csv_path=similarity_csv,
                similar_limit=request.similar_limit,
                ensemble_method=request.ensemble_method,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Prediction failed: {exc}") from exc

        payload = prediction.to_dict()
        history_item = record_prediction_history(user_id=user.id, prediction=payload)
        payload["history_id"] = history_item.id
        return payload

    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.getenv("CARVALUATOR_API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("CARVALUATOR_API_PORT", "8000")))
    uvicorn.run("carvaluator_scraper.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
