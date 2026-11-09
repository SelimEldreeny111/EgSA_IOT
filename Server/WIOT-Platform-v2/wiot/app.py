"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import admin, auth, commands, farm, operations, org, stream, telemetry
from .config import Settings, get_settings
from .logging_setup import configure_logging, request_id_var
from .security import SESSION_COOKIE
from .services.commands import CommandError
from .services.metrics import HTTP_REQUESTS, HTTP_SECONDS
from .services.runtime import Runtime

log = logging.getLogger("wiot")
API_PREFIX = "/api/v2"
MAX_BODY = 64 * 1024

def build_csp(settings: Settings) -> str:
    """Strict CSP; the only third-party origins are the configured map tile hosts."""
    from urllib.parse import urlsplit
    hosts = sorted({f"{urlsplit(u).scheme}://{urlsplit(u).netloc}" for u in (settings.map_tile_url, settings.map_labels_url)
                    if u and urlsplit(u).netloc})
    return ("default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
            "script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
            f"img-src 'self' data: blob: {' '.join(hosts)}; connect-src 'self'")


def _error(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse({"detail": message, **extra}, status_code=status)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_dir, settings.log_json)
    csp = build_csp(settings)
    runtime = Runtime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.hub.bind_loop(asyncio.get_running_loop())
        runtime.startup()
        log.info("WIOT Platform %s listening on %s:%s (%s)", __version__, settings.host,
                 settings.port, settings.env)
        yield
        runtime.shutdown()

    app = FastAPI(
        title="WIOT Platform API", version=__version__, lifespan=lifespan,
        docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json",
        description="Ingestion, control and analytics for the EgSA WIOT water-IoT fleet.",
    )
    app.state.runtime = runtime

    # ------------------------------------------------------------ middleware
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY:
            request_id_var.reset(token)
            return _error(413, "Request body too large")
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_SECONDS.labels(path).observe(time.perf_counter() - started)
        response.headers["X-Request-ID"] = rid
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache"  # revalidate via ETag after upgrades
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.url.path.startswith("/api/docs") and not request.url.path.startswith("/api/redoc"):
            response.headers["Content-Security-Policy"] = csp
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # -------------------------------------------------------- error handlers
    @app.exception_handler(CommandError)
    async def _command_error(_: Request, exc: CommandError):
        return _error(exc.status, str(exc), **exc.extra)

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError):
        return _error(400, str(exc))

    @app.exception_handler(PermissionError)
    async def _perm_error(_: Request, exc: PermissionError):
        return _error(403, str(exc))

    @app.exception_handler(LookupError)
    async def _lookup_error(_: Request, exc: LookupError):
        return _error(404, str(exc.args[0]) if exc.args else "Not found")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        return _error(422, f"{where}: {first.get('msg', 'invalid input')}".strip(": "),
                      errors=[{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()][:10])

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error(500, "Internal server error", request_id=request_id_var.get())

    # --------------------------------------------------------------- routers
    for module in (auth, admin, telemetry, commands, farm, operations, org):
        app.include_router(module.router, prefix=API_PREFIX)
    app.include_router(farm.public_router)
    app.include_router(stream.router, prefix=API_PREFIX)
    app.include_router(operations.health_router)

    # ------------------------------------------------------------- web UI
    web = settings.web_dir
    app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def root(request: Request):
        if not request.cookies.get(SESSION_COOKIE):
            return RedirectResponse("/login")
        return FileResponse(web / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/login", include_in_schema=False)
    async def login_page():
        return FileResponse(web / "login.html", headers={"Cache-Control": "no-store"})

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        return FileResponse(web / "assets" / "favicon.svg", media_type="image/svg+xml")

    return app
