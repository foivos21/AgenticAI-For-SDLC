import logging
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.routes.almas import router as almas_router
from app.api.routes.admin import router as admin_router
from app.api.routes.bookings import router as bookings_router
from app.api.routes.flights import router as flights_router
from app.api.routes.jira import router as jira_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.errors import integrity_error_response
from app.db.flight_schema import ensure_flight_seat_columns
from app.db.seat_inventory import sync_seat_inventory
from app.db.session import engine
from app.config import get_settings


settings = get_settings()
REPO_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("app.validation")


def _configure_logging() -> None:
    level_name = str(settings.app_log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    has_stream_handler = False
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setLevel(level)
            handler.setFormatter(formatter)
            has_stream_handler = True

    if not has_stream_handler:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    for logger_name in ("app", "app.jira", "app.almas", "app.validation"):
        named_logger = logging.getLogger(logger_name)
        named_logger.setLevel(level)
        named_logger.propagate = True


_configure_logging()


@lru_cache
def _resolve_deploy_git_commit_hash() -> str | None:
    for key in (
        "GIT_COMMIT_SHA",
        "RAILWAY_GIT_COMMIT_SHA",
        "RAILWAY_GIT_COMMIT_HASH",
        "SOURCE_VERSION",
    ):
        value = os.getenv(key)
        if value:
            return value
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            .strip()
        )
    except Exception:
        return None

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(flights_router, prefix=settings.api_prefix)
app.include_router(bookings_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)
app.include_router(jira_router, prefix=settings.api_prefix)
app.include_router(almas_router, prefix=settings.api_prefix)


@app.exception_handler(IntegrityError)
def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
    return integrity_error_response(exc)


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    try:
        raw_body = await request.body()
        request_body = raw_body.decode("utf-8", errors="replace")
    except Exception:
        request_body = "<unavailable>"
    if len(request_body) > 4000:
        request_body = request_body[:4000] + "...<truncated>"

    logger.warning(
        "Request validation error | method=%s path=%s errors=%s body=%s",
        request.method,
        request.url.path,
        exc.errors(),
        request_body,
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "error_code": "request_validation_error",
            "message": "The request body failed validation.",
            "details": exc.errors(),
        },
    )


@app.on_event("startup")
def repair_flight_schema() -> None:
    ensure_flight_seat_columns(engine)
    sync_seat_inventory(engine)


@app.get("/health")
def healthcheck() -> dict[str, str | None]:
    return {"status": "ok", "git_commit_hash": _resolve_deploy_git_commit_hash()}


@app.get(f"{settings.api_prefix}/meta")
def metadata() -> dict[str, str | None]:
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "git_commit_hash": _resolve_deploy_git_commit_hash(),
    }
