"""FastAPI application: API routers, error mapping, request logging, startup migrations and
seed, and the built React SPA served from / (one URL, no CORS). OpenAPI at /docs."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from procure_engine.policy_schema import PolicyError

from .config import get_settings
from .services.policy_service import NotFound

log = logging.getLogger("corvo")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "logger": record.name, "msg": record.getMessage(),
                   "at": self.formatTime(record, "%Y-%m-%dT%H:%M:%S")}
        for key in ("request_id", "method", "path", "status", "ms", "user"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_corvo", False) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler._corvo = True  # type: ignore[attr-defined]
    if get_settings().log_json:
        handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)


def run_migrations() -> None:
    from alembic.config import Config

    from alembic import command

    from .db import get_engine

    get_engine()  # creates the SQLite folder when needed

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")


def startup() -> None:
    from .db import session_scope
    from .seed.loader import seed_all

    settings = get_settings()
    run_migrations()
    if settings.seed_on_start:
        started = time.perf_counter()
        with session_scope() as s:
            seed_all(s, settings)
        log.info("seed complete", extra={"ms": int((time.perf_counter() - started) * 1000)})


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    startup()
    yield


def create_app(*, run_startup: bool = True) -> FastAPI:
    app = FastAPI(
        title="Corvo PR-to-PO",
        version="1.0.0",
        description="Policy-driven procurement decisions for Corvo Engineering. Deterministic engine; "
                    "policy as versioned data; AI only translates text into structured proposals.",
        lifespan=lifespan if run_startup else None,
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        if request.url.path.startswith("/api") or request.url.path in ("/healthz", "/readyz"):
            log.info("request", extra={"request_id": rid, "method": request.method, "path": request.url.path,
                                       "status": response.status_code, "ms": int((time.perf_counter() - started) * 1000),
                                       "user": request.headers.get("X-User", "")})
        return response

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(PolicyError)
    async def policy_error(_: Request, exc: PolicyError) -> JSONResponse:
        return JSONResponse({"detail": "policy validation failed", "errors": exc.messages}, status_code=422)

    from .api import batch, master, policy, workspace

    app.include_router(batch.router)
    app.include_router(policy.router)
    app.include_router(workspace.router)
    app.include_router(master.router)
    try:
        from .api import chat

        app.include_router(chat.router)
    except ImportError:  # pragma: no cover
        pass

    static = get_settings().static_dir
    if (static / "index.html").exists():
        if (static / "assets").exists():
            app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            if full_path.startswith(("api/", "docs", "openapi.json")):
                raise HTTPException(404)
            candidate = static / full_path
            if full_path and candidate.is_file() and static in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html")

    return app


app = create_app()
