"""Serve the local Job Agent dashboard and read-only job API."""

import argparse
import sqlite3

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import core
from .dashboard import DEMO_JOBS, is_review_job, load_jobs, render_dashboard

FIELDS = ("title", "company", "location", "score", "eligible", "status", "reason")
DEMO_ROWS = [(f"demo-{index}", *row) for index, row in enumerate(DEMO_JOBS, 1)]


def create_app(database=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    @app.middleware("http")
    async def prevent_caching(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def get_rows(view, limit):
        try:
            if database is not None:
                return load_jobs(database, include_id=True, review=view == "review", limit=limit)
            rows = DEMO_ROWS
        except sqlite3.Error as error:
            raise HTTPException(
                503, "The local job database is unavailable. Run main.py init first."
            ) from error
        if view == "review":
            rows = [row for row in rows if is_review_job(row[5], row[6])]
        return rows[:limit]

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        view: str = Query("all", pattern="^(all|review)$"), limit: int = Query(100, ge=1, le=500)
    ):
        return render_dashboard(get_rows(view, limit), demo=database is None, interactive=True)

    @app.get("/api/jobs")
    def jobs(
        view: str = Query("all", pattern="^(all|review)$"), limit: int = Query(100, ge=1, le=500)
    ):
        return [
            {"id": row[0], **dict(zip(FIELDS, row[1:], strict=True))}
            for row in get_rows(view, limit)
        ]

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Read the local job database.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(create_app(core.DB if args.live else None), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
