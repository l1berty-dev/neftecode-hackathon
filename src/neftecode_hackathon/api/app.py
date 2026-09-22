"""FastAPI transport for the shared application service."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from neftecode_hackathon.api.models import (
    ControlsResponse,
    DecisionListResponse,
    DecisionRequest,
    DecisionResponse,
    EpisodesResponse,
    ErrorResponse,
    HealthResponse,
    ModelledPresetsResponse,
    ModelledRunResponse,
    ModelledRunsResponse,
    ReplayAdvanceRequest,
    ReplayStartRequest,
    SaveDecisionResponse,
    ScenarioRequest,
    ScenarioResponse,
    SnapshotResponse,
    StoredDecisionResponse,
)
from neftecode_hackathon.api.service import (
    ApplicationError,
    ApplicationService,
    NotReadyError,
    build_calculation_runtime,
    repository_root,
)
from neftecode_hackathon.contracts import ModelledChainRequest

API_PREFIX = "/api/v1"


def _error(status_code: int, code: str, message: str, details=None) -> JSONResponse:
    payload = ErrorResponse(code=code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def create_app(service: ApplicationService | None = None) -> FastAPI:
    injected = service

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.service = injected
        app.state.startup_issues = []
        root = repository_root()
        data_root = _configured_directory(root, "DATA_DIR", "data/processed")
        model_root = _configured_directory(root, "MODEL_DIR", "artifacts")
        data_files = (
            data_root / "audit_report.json",
            data_root / "data_dictionary.json",
            data_root / "telemetry.parquet",
            data_root / "analyses.parquet",
        )
        model_files = (model_root / "manifest.json", model_root / "model.joblib")
        app.state.data_ready = injected is not None or all(path.is_file() for path in data_files)
        app.state.model_ready = injected is not None or all(path.is_file() for path in model_files)
        app.state.database_ready = injected is not None
        if injected is None:
            try:
                runtime = build_calculation_runtime(root)
            except Exception as error:  # health stays available during partial startup
                app.state.model_ready = False
                app.state.startup_issues.append(_safe_startup_issue(error))
            else:
                try:
                    app.state.service = ApplicationService.from_environment(runtime)
                    app.state.database_ready = True
                except Exception as error:  # health stays available during partial startup
                    app.state.startup_issues.append(_safe_startup_issue(error))
        yield

    app = FastAPI(
        title="Neftecode operator adviser API",
        version="1.0.0",
        description=(
            "Decision support for historical replay and explicit modelled full-chain scenarios. "
            "The service recommends and explains; it never controls equipment."
        ),
        lifespan=lifespan,
    )
    frontend_port = os.environ.get("FRONTEND_PORT", "5173")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://localhost:{frontend_port}",
            f"http://127.0.0.1:{frontend_port}",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(ApplicationError)
    async def application_error_handler(_request: Request, error: ApplicationError):
        return _error(error.status_code, error.code, error.message, error.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, error: RequestValidationError):
        return _error(422, "request_validation", "Request validation failed.", error.errors())

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(_request: Request, _error_value: SQLAlchemyError):
        return _error(503, "database_unavailable", "PostgreSQL is unavailable.")

    def require_service(request: Request) -> ApplicationService:
        current = request.app.state.service
        if current is None:
            raise NotReadyError(
                "Application data, model, or PostgreSQL is not ready. Run prepare, train, and migrations.",
                {"issues": tuple(request.app.state.startup_issues)},
            )
        return current

    @app.get(f"{API_PREFIX}/health", response_model=HealthResponse, tags=["system"])
    def health(request: Request) -> HealthResponse:
        data_ready = bool(request.app.state.data_ready)
        model_ready = bool(request.app.state.model_ready)
        database_ready = bool(request.app.state.database_ready)
        if injected is None and request.app.state.service is not None:
            try:
                request.app.state.service.check_database()
            except SQLAlchemyError:
                database_ready = False
            else:
                database_ready = True
            request.app.state.database_ready = database_ready
        return HealthResponse(
            ready=data_ready and model_ready and database_ready,
            data_ready=data_ready,
            model_ready=model_ready,
            database_ready=database_ready,
            issues=tuple(request.app.state.startup_issues),
        )

    @app.get(f"{API_PREFIX}/controls", response_model=ControlsResponse, tags=["configuration"])
    def controls(request: Request) -> ControlsResponse:
        return require_service(request).controls()

    @app.get(f"{API_PREFIX}/episodes", response_model=EpisodesResponse, tags=["replay"])
    def episodes(request: Request) -> EpisodesResponse:
        return require_service(request).episodes()

    @app.post(f"{API_PREFIX}/replay/start", response_model=SnapshotResponse, tags=["replay"])
    def replay_start(
        payload: ReplayStartRequest,
        request: Request,
    ) -> SnapshotResponse:
        return require_service(request).start_replay(payload.episode_id)

    @app.post(f"{API_PREFIX}/replay/advance", response_model=SnapshotResponse, tags=["replay"])
    def replay_advance(
        payload: ReplayAdvanceRequest,
        request: Request,
    ) -> SnapshotResponse:
        return require_service(request).advance_replay(payload.expected_snapshot_id)

    @app.get(f"{API_PREFIX}/snapshots/current", response_model=SnapshotResponse, tags=["snapshots"])
    def current_snapshot(
        request: Request,
    ) -> SnapshotResponse:
        return require_service(request).current_snapshot()

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}",
        response_model=SnapshotResponse,
        tags=["snapshots"],
    )
    def snapshot(
        snapshot_id: UUID,
        request: Request,
    ) -> SnapshotResponse:
        return require_service(request).snapshot(snapshot_id)

    @app.post(f"{API_PREFIX}/decisions", response_model=DecisionResponse, tags=["decisions"])
    def create_decision(
        payload: DecisionRequest,
        request: Request,
    ) -> DecisionResponse:
        changes = payload.operator_action.changes if payload.operator_action is not None else None
        label = (
            payload.operator_action.label
            if payload.operator_action is not None
            else "Вариант оператора"
        )
        return require_service(request).create_decision(payload.snapshot_id, changes, label)

    @app.post(
        f"{API_PREFIX}/scenarios/evaluate",
        response_model=ScenarioResponse,
        tags=["scenarios"],
    )
    def evaluate_scenario(
        payload: ScenarioRequest,
        request: Request,
    ) -> ScenarioResponse:
        return require_service(request).evaluate(payload.snapshot_id, payload.changes)

    @app.post(
        f"{API_PREFIX}/decisions/{{decision_id}}/save",
        response_model=SaveDecisionResponse,
        tags=["decisions"],
    )
    def save_decision(
        decision_id: UUID,
        request: Request,
    ) -> SaveDecisionResponse:
        return require_service(request).save_decision(decision_id)

    @app.get(f"{API_PREFIX}/decisions", response_model=DecisionListResponse, tags=["decisions"])
    def decisions(
        request: Request,
        saved_only: bool = True,
        limit: int = Query(default=20, ge=1, le=100),  # noqa: B008
    ) -> DecisionListResponse:
        return require_service(request).decisions(saved_only=saved_only, limit=limit)

    @app.get(
        f"{API_PREFIX}/decisions/{{decision_id}}",
        response_model=StoredDecisionResponse,
        tags=["decisions"],
    )
    def decision(
        decision_id: UUID,
        request: Request,
    ) -> StoredDecisionResponse:
        return require_service(request).decision(decision_id)

    @app.get(
        f"{API_PREFIX}/modelled-presets",
        response_model=ModelledPresetsResponse,
        tags=["modelled scenarios"],
    )
    def modelled_presets(request: Request) -> ModelledPresetsResponse:
        return require_service(request).modelled_presets()

    @app.post(
        f"{API_PREFIX}/modelled-runs",
        response_model=ModelledRunResponse,
        tags=["modelled scenarios"],
    )
    def create_modelled_run(payload: ModelledChainRequest, request: Request) -> ModelledRunResponse:
        return require_service(request).create_modelled_run(payload)

    @app.get(
        f"{API_PREFIX}/modelled-runs",
        response_model=ModelledRunsResponse,
        tags=["modelled scenarios"],
    )
    def modelled_runs(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),  # noqa: B008
    ) -> ModelledRunsResponse:
        return require_service(request).modelled_runs(limit=limit)

    @app.get(
        f"{API_PREFIX}/modelled-runs/{{run_id}}",
        response_model=ModelledRunResponse,
        tags=["modelled scenarios"],
    )
    def modelled_run(run_id: UUID, request: Request) -> ModelledRunResponse:
        return require_service(request).modelled_run(run_id)

    return app


def _safe_startup_issue(error: Exception) -> str:
    if isinstance(error, NotReadyError):
        return error.message
    if isinstance(error, FileNotFoundError):
        return "Prepared data or trained model artifact is missing."
    if isinstance(error, SQLAlchemyError):
        return "PostgreSQL is unavailable or migrations are not applied."
    return f"Application startup validation failed: {type(error).__name__}."


def _configured_directory(root: Path, variable: str, default: str) -> Path:
    configured = Path(os.environ.get(variable, default))
    return (configured if configured.is_absolute() else root / configured).resolve()


app = create_app()
