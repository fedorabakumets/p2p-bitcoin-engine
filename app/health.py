"""Tiny HTTP health check for later admin and webhooks. Buttons do not pass through it."""

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import libpq_url


def create_health_app() -> FastAPI:
    app = FastAPI(title="p2p-bitcoin-engine", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz", response_model=None)
    def healthz() -> JSONResponse | dict[str, str]:
        try:
            with psycopg.connect(libpq_url(), connect_timeout=3) as connection:
                connection.execute("SELECT 1")
        except Exception:
            return JSONResponse(status_code=503, content={"status": "error"})
        return {"status": "ok"}

    return app
